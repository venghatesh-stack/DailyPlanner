# event-driven order processing workflow (e-commerce): recall card

> **Hook:** Reserve stock with TTL → Order plus outbox in one transaction → Saga waits for payment → Confirm and ship → Compensate in reverse → Reconcile

**P · Problem:** It's really a distributed transaction problem across services with separate databases, solved with a saga instead of 2PC.

**N · Numbers:**
1. The 25k orders/s peak is about 215x the 116/s average, so size for bursts, not averages.
2. One blockbuster SKU can see 5k+ reservations/s, above a row lock's 1-2k/s, so shard hot stock in Redis.
3. 375 MB/s of broker writes at peak, so at least 25 partitions per topic; use 64-128.

**H · Hard part:** Never overselling a hot SKU, and never keeping money without an order when payment outcomes are unknown or late.

**B · Boxes:** `Gateway → Order service → Inventory service → Outbox relay → Kafka → Saga orchestrator → Payment service`

Side path: `Saga orchestrator → Fulfilment and Notification`.

**D · Decisions:**
1. Orchestration over choreography for the core flow, because it gives explicit state, timers and a per-order timeline.
2. Reserve at checkout with a TTL over reserve at payment, because reserving after payment forces refunds for race losers.
3. CDC over a polling relay, because it is lower latency, keeps commit order and puts no load on hot shards.

**F · Failures:**
1. PSP times out → the attempt is PENDING, not failed; poll the PSP, and a capture after cancel is auto-refunded.
2. Kafka down briefly → services keep committing outbox rows; the relay catches up; nothing is lost.

**C · Close:** "I cannot use one ACID transaction, so I protect three invariants: never oversell, never take money without an order or a refund, never lose an order. Checkout synchronously reserves stock with a 15-minute TTL and writes the order plus an OrderCreated event in one local transaction. An orchestrated saga waits for capture, confirms the reservation, ships and notifies, or compensates in reverse. Every consumer is idempotent, and reconciliation is the final safety net."

**Quiz yourself:**
1. How are CDC replays made harmless? → An inbox row (consumer, event_id) in the same transaction as the change.
2. How do you handle a late AUTHORIZED webhook after CAPTURED? → Apply only forward state moves, so it is ignored.
3. What breaks first at sale scale? → Hot-SKU inventory and PSP capacity.
