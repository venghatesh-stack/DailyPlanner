# Design Swiggy / DoorDash-style food delivery ordering: the 5-page summary

Food delivery is a three-sided real-time marketplace (customer, restaurant, rider) built around a perishable product. The single most important idea: order writes are small, so spend them on correctness (a state machine, a saga, idempotency keys), while the real load is rider location ingest, tracking pushes and per-zone dispatch compute, which live in memory and are partitioned by city.

## Page 1. The problem, scope and numbers

**Pitch:** let a hungry customer find restaurants that can deliver fast, pay safely, and get hot food on time, while restaurants get orders without chaos and riders get steady, fair earnings.

**Who uses it:** customers (accurate ETAs, UPI, live tracking, quick refunds), restaurants (alerts, prep-time control), riders (fair nearby offers), city ops (surge, pause zones in rain) and finance (reconciliation).

**In scope:**
- **Discovery:** open restaurants within radius, with ETA and fee.
- **Order:** signed price quote, idempotent placement, UPI, cards, wallets or COD.
- **Restaurant workflow:** accept or reject with prep time, mark ready, escalation on no response.
- **Dispatch:** offers with a 30 s accept window, batching up to 2 orders, reassignment.
- **Tracking and closure:** live WebSocket tracking, delivery OTP, refunds by state.

**Out of scope:** quick commerce, restaurant onboarding, rider payroll, personalised ranking, building ETA models.

**Non-functional targets:**
- **Latency:** order placement p99 under 1 s server side; listing p99 under 300 ms; rider position on the customer map under 10 s old at p95.
- **Availability:** 99.95% for ordering, 99.9% for tracking.
- **Consistency:** order state and payments strongly consistent per order; menus and availability eventual within 30 s.
- **Durability:** no acknowledged order lost (synchronous replication, RPO 0 in region).
- **Business:** zero double charges or assignments; ETA within 5 min for 80% of orders.

**Capacity math (3M orders/day, 20% in the dinner hour, festivals 5x):**
- **Orders:** 3M x 0.2 / 3,600 = about 170/s; 850/s at festival peak. Times 8 transitions = 1.4k writes/s. Modest, so a sharded Postgres fleet is enough; spend it on correctness.
- **Listing and menu reads:** 15M DAU x 6 = 90M/day, about 5k/s peak, 25k/s at festivals. So cache per H3 cell.
- **Location ingest:** 300k riders / 4 s = 75k updates/s; x 200 B = 15 MB/s, 1.3 TB/day raw. So keep only the latest position in Redis and send history to Kafka.
- **Tracking fan-out:** 170/s x 30 min = about 300k live orders, each pushed every 4-5 s = about 70k WebSocket messages/s. So a dedicated push gateway.
- **Dispatch:** a large city has about 5k open orders and 30k riders at peak; about 50 candidates each gives a 250k-entry cost matrix per batch. So dispatch is partitioned per city and zone.
- **Storage:** 3M x 5 KB = 15 GB/day, 5.5 TB/year. Small; compute and fan-out dominate.

## Page 2. The architecture

```
 Customer app          Restaurant tablet / POS         Rider app (GPS 4 s)
      v                         v                            v
 API gateway (auth, rate limit) + WebSocket / push gateway
   |           |            |               |                 |
   v           v            v               v                 v
 Discovery  Cart/Pricing  Order service   Dispatch        Location ingest
 (geo, ETA) (signed quote) (state machine, (per-zone       (validate, H3)
   |                       saga)           batching) <---+    |
   v                        |   |   |        |  -> ETA svc |    v
 Elasticsearch              |   |   |        |             +- Redis: latest
 + menu cache (Redis)       |   |   +-> Payment svc          position, cells
                            v   |        (UPI, cards, PSPs)
               Orders DB (sharded Postgres + outbox)
                            |
                            v
 Kafka: order.*, rider.* -> dispatch, tracking/notify, Flink, data lake
```

- **API and WebSocket gateway:** auth, rate limits, persistent sockets for riders, restaurants and trackers.
- **Discovery:** geo query in Elasticsearch, filtered to open restaurants, plus ETA and fee.
- **Cart and pricing:** taxes, fees, surge, promos; returns a signed quote valid 5 minutes.
- **Order service:** the source of truth; state machine, saga orchestrator, durable timers, outbox.
- **Payment service:** PSP adapters with idempotency keys, webhooks, daily reconciliation.
- **Restaurant gateway:** pushes orders to tablets or POS; IVR call when nobody responds.
- **Location service:** validates pings, keeps latest position per rider and H3 cell in Redis.
- **Dispatch service:** per-zone micro-batch matching, offers, reassignment.
- **ETA service:** ML prep time plus road travel with live traffic.
- **Kafka and Flink:** events drive dispatch, tracking, zone metrics and analytics.

**Flow A: place an order (saga)**
1. POST /v1/orders with quote_id and an Idempotency-Key; the quote signature and expiry are checked.
2. Order CREATED plus its outbox event commit in one transaction.
3. Payment authorises with order_id as the PSP key; UPI may stay PENDING until a webhook.
4. AUTHORIZED: order PLACED, pushed to the restaurant, 3-minute durable acceptance timer starts.
5. Accept with prep time: ACCEPTED. Reject or timeout: CANCELLED and payment voided. Capture on DELIVERED.

**Flow B: dispatch and tracking**
1. Dispatch consumes order.accepted into the zone pool; food ready = accept time + prep.
2. Every 5-10 s it pulls riders from an H3 k-ring around each restaurant and solves an assignment.
3. Offer for 30 s; accept applies RIDER_ASSIGNED by CAS on order and rider versions.
4. Rider pings every 4 s; tracking pushes position and ETA every ~5 s, polling every 10 s as fallback.

## Page 3. The core deep dives

### 1. Order state machine with optimistic concurrency
States run CREATED -> PAYMENT_PENDING -> PLACED -> ACCEPTED -> RIDER_ASSIGNED -> PICKED_UP -> DELIVERED, with CANCELLED and FAILED exits. Every transition checks that the move is legal and runs UPDATE ... WHERE version = expected, inserting the event row in the same transaction (the outbox). Example: Shreya cancels at the same moment the restaurant accepts. Both read version 4; only one update matches, the loser gets a conflict, re-reads, and policy decides (if accepted first, the cancel may carry a fee).

### 2. The placement saga and payments
An orchestrator owns the long waits and compensations: authorise, wait up to 3 minutes for the restaurant (re-notify and IVR call at 90 s), dispatch, capture on delivery. Compensations are void or refund. Idempotency is chained end to end: the client key maps to one order, and order_id is the PSP key. On a PSP timeout, never blind-retry: query status with the same key and retry only if the PSP says not found. UPI often has no auth-capture, so it debits at order and auto-refunds on cancel; a PENDING UPI payment gets a 10-minute timer, and a late debit after FAILED is refunded by reconciliation.

### 3. Micro-batch dispatch with order batching
Greedy "nearest rider on accept" is simple but wastes riders at peak. Every 5-10 s per zone the engine takes open orders, gathers IDLE or nearly finished riders from H3 cells (H3 is Uber's hexagonal grid) within k=2-3 rings of each restaurant, and scores each pair: time to pickup plus drop time, plus penalties for food waiting (0.5) and rider waiting (1.0), minus an age bonus, plus fairness. Pairs of orders are added as one job if pickups are within about 1 km and the first order is delayed under 8 minutes. A min-cost assignment picks the plan; leftovers wait one tick with higher priority. Riders are timed to arrive near food-ready time, not at acceptance.

### 4. Location ingest at 75k/s
Each ping is dropped if its seq is old, or flagged if it implies over 80 km/h for a two-wheeler. On a cell change the rider moves between Redis sets cell:{h3_r9}; the rider hash has a 60 s TTL so silent riders leave matching. The ping is copied to Kafka keyed by rider_id.

**Data model:**
- **orders** (sharded Postgres, hash of order_id, which embeds city and time): status, version, items, amounts, payment_id, eta_promised.
- **order_events** (same shard, PK order_id + seq): audit trail and the outbox.
- **payments** (separate Postgres): unique idempotency_key and (psp, psp_ref); state AUTH_PENDING to REFUNDED.
- **rider_state** (Redis per city): rider:{id} with status, position, version; cell:{h3} -> rider set.
- **restaurants** (Elasticsearch): geo_point, is_open, avg_prep_min, serviceable polygon.

**Key APIs:**
- `POST /v1/carts/{id}/quote`: signed total and ETA, valid 5 minutes.
- `POST /v1/orders`: Idempotency-Key; same key returns the same order; 409 if the quote expired.
- `POST /v1/restaurant/orders/{id}/accept`: prep_time_min; 409 if already cancelled.
- `POST /v1/rider/offers/{id}/accept`: versioned; 410 if expired or reassigned.
- `WS /v1/orders/{id}/track`: status, rider position and ETA every ~5 s.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Location ingest:** latest position only in Redis per city, history to Kafka; add Redis shards per city.
- **Tracking pushes:** scale the stateless WebSocket gateways horizontally; clients fall back to polling.
- **Dispatch compute:** partition by city and zone with one owner per zone; k-ring filtering bounds the matrix; greedy fallback when the solver is slow.
- **Listing reads:** cache by H3 res-8 cell and 30 s time bucket; cache harder at festivals.
- **Festival peaks:** pre-scale gateways and Redis, add Kafka partitions early, load test the solver at 5x, freeze deploys, throttle new orders per zone.

**Failure modes:**
- **Primary PSP degraded:** route to a secondary PSP by rolling success rate; resolve pending by webhook and polling; suggest another method.
- **Dispatch worker crashes:** its zone lease expires in 10 s, another worker rebuilds from Redis and open orders; at most one batch delayed.
- **Redis location cluster fails:** a replica promotes; if lost, pings refill it in 4 s; dispatch pauses a tick or two.
- **Orders DB shard failover:** synchronous replica promoted in about 30 s; writes get 503 with retry-after and retry on the same key.
- **Kafka lag:** dispatch also polls for ACCEPTED orders older than 30 s; notifications are late but orders flow.
- **ETA service down:** distance-based ETAs with a conservative buffer; alert on the ETA SLO.
- **Heavy rain:** surge fees, longer ETAs, smaller radius, order throttling rather than orders that will fail.

**Trade-offs chosen:**
- **Orchestrated saga over choreography:** long timers and many compensation branches need one owner and visibility.
- **Micro-batch over greedy:** less total travel and enables batching; greedy stays as the fallback.
- **Dispatch timed to food-ready over at placement:** early riders wait, late ones let food go cold.
- **Authorise then capture on delivery:** avoids card refunds on cancels; UPI debits and auto-refunds.
- **Redis plus Kafka over PostGIS for locations:** 75k/s of ephemeral data where only the latest matters.
- **H3 over geohash or quadtree:** uniform neighbours for k-ring search and clean per-cell metrics.

**What to measure:** time to restaurant accept, time to assign, total delivery time, ETA error distribution, payment success by method and PSP, pending UPI age, refund latency, solver time and unassigned order age, rider utilisation, ping freshness and spoofing rate, WebSocket reconnects, zone supply-demand ratio.

## Page 5. Say it in the interview

> "I will design a Swiggy-like flow: browse nearby restaurants, order and pay, the restaurant accepts, a rider is assigned and the customer tracks delivery live. Assume 3 million orders a day, a dinner peak near 170 orders a second, and 300 thousand riders pinging every 4 seconds. The non-negotiables are no double charge and no double assignment; menus can lag. The order is an explicit state machine in sharded Postgres, and placement is an orchestrated saga: authorise payment, wait for the restaurant with a timeout, dispatch, capture on delivery, with void and refund as compensations. Dispatch runs per zone every few seconds, pulls riders from H3 cells around the restaurant, and solves an assignment that also batches orders. The hot paths are location ingest at 75 thousand writes a second and dispatch compute, so I partition by city, keep only latest positions in Redis, and degrade by widening ETAs before failing orders."

**Key points to land:**
- Three-sided marketplace: strong consistency on money and assignment, eventual on menus.
- Order writes are only about 1.4k/s; ingest (75k/s), pushes (70k/s) and dispatch are the load.
- The order is a state machine with version checks and an event table.
- Placement is an orchestrated saga with durable timers and void or refund compensations.
- Idempotency keys chained end to end; on an unknown PSP outcome, query status first.
- H3 k-rings for candidate riders; Redis latest position with a 60 s TTL.
- Per-zone micro-batch assignment, timed to food-ready, batching at most 2 orders.
- Zone ownership by lease; RIDER_ASSIGNED protected by CAS.
- Outbox to Kafka feeds dispatch, tracking and analytics.
- Degrade gracefully: surge, wider ETAs, smaller radius, PSP failover, heuristic ETAs.

**Likely follow-ups:**
1. **How do you get a reliable ETA?** Split it into prep (ML on restaurant, items and load), rider-to-restaurant and drop travel with live traffic; calibrate on actuals and buffer for the 80% within 5 min target.
2. **New Year's Eve at 5x?** Pre-scale gateways and Redis, add Kafka partitions, load test the solver at 5x, turn on surge and per-zone throttling, cache listings harder, freeze deploys.
3. **Batching without cold food?** Pickups within about 1 km, under 8 minutes added to the first drop, cap at 2, and penalise food types like ice cream.
4. **Two workers assign one order?** One worker per zone by lease, and the assignment is a CAS on order and rider versions, so the second write fails and its offer is withdrawn.
5. **Multi-region?** Cities are natural partitions: home each in one region with a warm standby, replicate global services, and fail over a city by promoting its DB and moving its zones.

**Director layer:**
- **Cost drivers:** WebSocket gateways for about 70k pushes/s, Redis per city for live state, dispatch solver compute at peak, and multiple PSPs.
- **Phasing:** start with the order state machine, saga and greedy dispatch; then micro-batch matching, order batching and ML ETAs.
- **Team ownership:** discovery and menus, orders and payments, dispatch and location, restaurant platform, tracking and notifications, data platform.
- **Top risks:** demand spikes beyond rider supply, PSP outages, restaurants that accept then fail to prepare, and GPS spoofing.
