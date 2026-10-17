# Design an event-driven order processing workflow (e-commerce): the 5-page summary

An order touches inventory, payments, fulfilment and notifications, each with its own database, so there is no single ACID transaction to lean on. The single most important idea: an orchestrated saga of local transactions, with transactional outboxes, idempotent consumers and reconciliation, protects three invariants: never oversell, never keep money without an order, never lose an acknowledged order.

## Page 1. The problem, scope and numbers

**Pitch:** take an order from a cart, reserve stock, collect payment, confirm and ship it, correctly, at 25k orders/s on a festive sale morning, while PSPs (payment service providers) send late or duplicate webhooks.

**Who uses it:** shoppers (UPI, confirmation in seconds), sellers (accurate order feed), support agents (order timeline, safe refunds), finance ops (reconciliation).

**In scope:**
- **Create order** idempotently from a cart snapshot with an Idempotency-Key header.
- **Reserve inventory** per item per warehouse, atomically, with a TTL; fail fast on out-of-stock.
- **Payments** via PSP adapters (UPI, cards, wallets, net banking, EMI, COD); idempotent webhooks and status polls.
- **Saga** with timers and compensations: confirm, ship, notify; or refund, release, cancel.
- **Cancellation, read models, reconciliation** and an ops console to retry or force a compensation.

**Out of scope:** cart, pricing and coupons; returns and exchanges; last-mile logistics; fraud model design (consumed as a risk score).

**Non-functional targets:**
- **Latency:** create order + reserve p99 under 500 ms, excluding the PSP screen; payment to confirmed order p99 under 5 s.
- **Availability:** checkout 99.99% monthly; post-payment workflow 99.95% (backlog allowed, no loss).
- **Consistency:** inventory and payments strongly consistent per key; read models within 2 s p99.
- **Durability:** zero lost orders after 201 Created; Kafka RF 3, min ISR 2; semi-sync DB replication.
- **Idempotency:** every API and consumer safe to retry; stuck sagas detected within 5 minutes.

**Capacity math (10M orders/day, 2.5 items, 12 events per order):**
- **Orders:** 10M / 86,400 = about 116/s; the 25k/s peak is about 215x that. So size for bursts, not averages.
- **Reservations:** 25k x 2.5 = 62.5k ops/s. Top 100 hero SKUs take 30%, about 19k ops/s, and one blockbuster can see 5k+/s on one SKU, above a DB row lock's 1-2k/s. So shard hot stock in Redis.
- **Events:** 120M/day = 1.4k/s average; peak 25k x 5 = 125k/s; x 1 KB x 3 replicas = 375 MB/s broker writes. So at least 25 partitions per topic; use 64-128.
- **Storage:** 10M x (2 KB + 2.5 x 0.5 KB) = about 33 GB/day; 2 years hot = 24 TB. So shard 16-32 ways by order_id.

## Page 2. The architecture

```
 Client --POST /checkout (Idempotency-Key)--> Gateway (waiting room)
                     |
                     v
 Order svc: orders + outbox --sync reserve--> Inventory svc (TTL 15 min,
   (one local txn)                             DB rows + Redis hot SKUs)
        | CDC outbox relay (Debezium)               | outbox relay
        v                                           v
 Kafka: order|inventory|payment events, cmd.* (key order_id, RF 3)
     |              |                  |                  |
     v              v                  v                  v
 Saga orchestr. <-> Payment svc     Fulfilment/WMS     Notification
 (state, timers)    (PSP adapters,  (shipments per     (email, SMS,
     |               webhooks)       warehouse)         push)
     v                  v
 Saga state store   External PSPs (UPI, cards, wallets)
 Reconciliation jobs       Read models (CQRS): history, seller feed
```

- **Gateway:** auth, rate limits, Idempotency-Key, virtual waiting room for flash deals.
- **Order service:** builds the order from the cart snapshot; order and outbox in one transaction.
- **Saga orchestrator:** per-order state machine, durable timers, compensations; Temporal or DB-backed.
- **Inventory service:** available, reserved, committed per sku x warehouse; reserve, confirm, release.
- **Payment service:** intents, attempts, PSP routing, webhooks, polling, refunds, ledger.
- **Fulfilment service:** one shipment per warehouse or seller via the WMS.
- **Outbox relay (Debezium CDC):** tails outbox tables, publishes to Kafka in commit order.
- **Kafka:** event and command topics keyed by order_id; DLQ per consumer.
- **Reconciliation:** matches PSP files, payments, orders, reservations; auto-refunds and releases.

**Flow A: happy path, prepaid order**
1. POST /checkout; Order service calls reserve(order_id, items, ttl 15 min).
2. Insert order PENDING_PAYMENT plus OrderCreated in one transaction; return 201 with a payment session.
3. Orchestrator consumes OrderCreated and starts a 15-minute payment timer.
4. PSP webhook arrives; Payment service verifies the signature, records CAPTURED, emits PaymentCaptured.
5. Orchestrator sets PAID, confirms the reservation, creates shipments, sets CONFIRMED, notifies.

**Flow B: payment timeout (compensation)**
1. No capture in 15 minutes: the orchestrator first queries Payment for the latest status.
2. Still not captured: release the reservation, set CANCELLED (PAYMENT_TIMEOUT), notify.
3. A capture arriving later hits a terminal state, so the saga auto-refunds and logs the orphan.

## Page 3. The core deep dives

### 1. Saga plus outbox: no 2PC, no dual writes
The orchestrator is a deterministic function from (state, event) to (new state, commands). It saves each transition with an optimistic version check (UPDATE ... WHERE version = ?) in the same transaction as outbox command rows, so either both happen or neither. Compensations run in reverse and are idempotent. PENDING_PAYMENT and HELD reservations act as semantic locks. Consumers insert (consumer, event_id) into an inbox table in the same transaction as their change; a duplicate insert means "already done", so CDC replays are harmless. Choreography is used only for side effects like notifications and read models.

### 2. Hot-SKU reservation
Normal SKUs: UPDATE stock SET available = available - q, reserved = reserved + q WHERE available >= q. A blockbuster deal serialises on that row. So hero SKUs split stock into 16 Redis keys; a Lua script decrements a random shard and tries others on failure; when all are zero, the SKU is sold out. Each success is appended to a durable reservation stream and written to the DB asynchronously. Example: 200k users hit a 5,000-unit deal at noon; the waiting room admits about 1.5x the remaining stock per window, and the sold-out flag reaches the gateway within a second.

### 3. Unknown payment outcomes
A PSP timeout (10 s) is unknown, not failed: the attempt goes PENDING. Intents use key order_id + attempt_no; webhooks are deduped on psp_event_id and applied only if they move state forward, so a late AUTHORIZED after CAPTURED is ignored. If Shreya approves UPI at minute 16, after her order was cancelled, the saga refunds automatically. Reconciliation polls pending attempts every 15 minutes and matches settlement files daily.

**Data model:**
- **orders / order_items / saga_state:** sharded by order_id; version, status, deadline_at for timers.
- **outbox:** PK event_id; Kafka key = aggregate_id (order_id); purged after 7 days.
- **inbox:** PK (consumer, event_id), written with the state change.
- **stock / reservations:** stock PK (sku, warehouse_id, shard_no); reservation PK (order_id, sku, warehouse_id), index (status, expires_at).
- **payments / attempts / ledger:** UNIQUE (order_id, attempt_no) and psp_payment_id; double-entry, never updated in place.

**Key APIs:**
- `POST /v1/checkout`: same Idempotency-Key returns the same response for 24 h.
- `GET /v1/orders/{order_id}`: read model; primary fallback for orders under 10 s old.
- `POST /internal/inventory/reservations`: idempotent on order_id, all or nothing.
- `POST /internal/payments/intents`: key order_id + attempt_no; PSP order id reused on retry.
- `POST /webhooks/psp/{psp}`: verify signature, dedup on psp_event_id, process async.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot-SKU inventory:** more stock shards, Redis atomic path with a durable log, waiting room admitting only as many users as units.
- **PSP capacity:** multi-PSP routing, pre-negotiated TPS, pacing checkout to what PSPs accept.
- **Order writes:** more shards by order_id; Kafka partitions keyed by order_id; one relay per shard.
- **Reads:** order status from CQRS read models and cache, never the transactional DB.
- **Bulkheads:** post-order backlog never blocks checkout.

**Failure modes:**
- **Inventory slow or down:** checkout fails fast (200 ms timeout, one retry), circuit breaker opens; no order or payment without a reservation.
- **PSP outage:** health-based router sends new intents to a backup PSP; pending attempts polled; alternative methods offered.
- **Kafka down briefly:** services keep committing outbox rows; the relay catches up; saga pauses, nothing lost.
- **Orchestrator crash:** state and timers are durable; another instance resumes; timers fire late rather than never.
- **Order DB shard failover:** semi-sync replica promoted; clients retry with the same Idempotency-Key.
- **Redis hot-SKU cluster lost mid-deal:** pause the deal, rebuild counters from DB plus the reservation log, conservatively.
- **Poison event:** bounded retries, then DLQ; park only that order as NEEDS_ATTENTION.

**Trade-offs chosen:**
- **Orchestration over choreography for the core flow:** explicit state, timers and per-order timeline; cost is a highly available orchestrator.
- **Reserve at checkout with TTL over at payment or at add-to-cart:** after payment forces refunds for race losers; add-to-cart blocks too much stock.
- **Synchronous reservation:** users need an instant out-of-stock answer; Inventory must hit p99 under 50 ms.
- **CDC over polling relay:** lower latency, commit order, no load on hot shards.
- **Capture now for UPI, auth-capture for cards:** UPI has no hold; for cards a void is cheaper than a refund.

**What to measure:** checkout success and p99 by failure reason; oversell count (target 0); orphan payments (0 after T+1); PSP success by method; saga count by state and age; consumer, outbox and read model lag; DLQ depth; reconciliation exceptions per day.

## Page 5. Say it in the interview

> "An order spans inventory, payments and fulfilment, each with its own database, so I cannot use one ACID transaction. I will protect three invariants: never oversell, never take money without an order or a refund, and never lose an order. Assume ten million orders a day and a sale burst of 25 thousand a second on a few hot SKUs. Checkout synchronously reserves stock with a 15-minute TTL and writes the order plus an OrderCreated event in one local transaction, the outbox pattern. An orchestrated saga then drives a state machine: wait for capture, confirm the reservation, create shipments, notify. On failure it compensates in reverse: refund, release, cancel. Every consumer is idempotent, events are keyed by order id, and reconciliation is the final safety net."

**Key points to land:**
- Three invariants: no oversell, no money without an order, no lost acknowledged order.
- No 2PC: an orchestrated saga with idempotent compensations.
- Outbox plus CDC to publish; inbox to consume; key everything by order_id.
- Reserve synchronously with a TTL; confirm on payment; release on failure.
- Hot SKUs: sharded Redis counters, durable log, waiting room.
- A payment timeout is unknown: PENDING, query the PSP, never guess.
- Reconciliation auto-refunds orphans and releases stale reservations.
- CQRS read models with a read-your-writes fallback.
- Bulkhead checkout from post-order processing.

**Likely follow-ups:**
1. **Why not event sourcing?** It adds snapshots and event schema evolution; the outbox already gives a reliable stream and audit timeline.
2. **What breaks first at Big Billion Day scale?** Hot-SKU inventory and PSP capacity; then event lag after checkout, which is acceptable.
3. **Temporal or your own state machine?** Temporal gives durable timers, retries and visibility; a DB machine has fewer moving parts. Either works if the machine is explicit and tested.
4. **How do you test compensations?** Unit-test every (state, event) pair, chaos-test PSP timeouts and duplicate webhooks, and run synthetic canary orders in production.
5. **How do you migrate from the monolith?** Strangler: add an outbox first, build read models, extract Inventory, then Payment, then orchestration, each behind a flag with reconciliation.

**Director layer:**
- **Cost drivers:** Kafka at 375 MB/s peak writes, 16-32 order shards, Redis for hero SKUs, a Temporal or orchestrator cluster, multiple PSP contracts.
- **Phasing:** strangler migration: outbox and read models first, then Inventory, Payment, orchestration.
- **Team ownership:** Order and saga, Inventory, Payments, Fulfilment, platform (Kafka, CDC), finance reconciliation.
- **Top risks:** hot-SKU timeouts, lost or duplicate events, unknown payment outcomes, saga debugging complexity, badly tuned reservation TTLs.
