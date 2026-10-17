# Design Uber (ride-hailing): the 5-page summary

Uber is a real-time two-sided marketplace: drivers stream GPS every 4 seconds, riders expect a car offer in under 2 seconds, and money must move with zero loss. The single most important idea: split the system into an AP, in-memory real-time plane (locations, candidates) and a CP, durable transactional plane (driver lease, trip, money), and keep each side failing safely.

## Page 1. The problem, scope and numbers

**Pitch:** match a rider to a nearby driver within seconds at a predictable price, then move money correctly between rider, driver and platform, in hundreds of cities.

**Who uses it:** riders (fast pickup, fair price), drivers (steady nearby trips, clear earnings), city ops (surge, airport queues), finance (exact ledger) and trust and safety.

**In scope:**
- **Location streaming:** online drivers ping every 4 s (2 s on a trip).
- **Quote:** upfront fare, surge and pickup ETA in a signed quote valid 5 minutes.
- **Dispatch:** rank candidates, offer to one driver for 15 s, re-dispatch on decline.
- **Trip lifecycle:** arrived, start with PIN, end, cancel, live tracking.
- **Payments:** authorise at request, capture at completion, refunds, payouts.
- **Surge pricing** per hex cell per minute, with city caps.

**Out of scope:** UberEats, UberPool, driver onboarding, building base maps, promotions.

**Non-functional targets:**
- **Latency:** request-to-offer p95 under 2 s, p99 under 4 s; quote p99 under 150 ms; ping visible to dispatch within 1 s p99.
- **Availability:** 99.99% per region for dispatch; 99.95% for capture (delayed, never lost).
- **Consistency:** linearizable per driver (zero double assignments); exactly-once effect per charge.
- **Durability:** RPO 0 in a region (Raft quorum), under 1 s cross-region; failover RTO under 5 minutes.

**Capacity math (25M trips/day, 5M drivers online at peak):**
- **Location writes:** 5M / 4 s = 1.25M pings/s; x 100 B = 125 MB/s, about 1 Gbps. So the write path never waits on a disk.
- **Live state:** 5M x 200 B = 1 GB. It fits in RAM, so shard for write throughput and blast radius, not size.
- **Nearby-car reads:** 3M sessions / 5 s = 600k reads/s. So serve them from geo index replicas.
- **Requests:** 25M / 86,400 = about 290/s, 900/s daily peak, 3,000/s on New Year's Eve. Modest, so spend it on correctness (consensus, idempotency).
- **ETA calls:** 3,000/s x 20 candidates = 60k/s, plus 15k/s for quotes; at 1 ms each, about 75 cores. So routing must take milliseconds (contraction hierarchies), provisioned at 10x.
- **Connections:** 8M sockets / 50k per gateway = 160 nodes; run about 400 for headroom.
- **Storage:** trips 25M x 5 KB = 125 GB/day, 45 TB/year; ledger 100M rows/day. Small enough for a strongly consistent store; trails (150 GB/day) go to the data lake.

## Page 2. The architecture

```
 Rider app (quote, request, track)        Driver app (ping 4 s, accept)
      |  HTTPS + WebSocket                      |  WebSocket / MQTT
      v                                         v
 Edge gateways: TLS, auth, rate limit, connection registry, push fan-out
      |                 |                      |                 ^ push
      v                 v                      v                 |
 Quote / Pricing    Demand svc           Location svc        Notify svc
      ^                 |                      | latest position
      | surge KV        v                      v
 Flink surge job    DISCO matcher <------ Geo index (H3 cells in RAM,
      ^                 |   |  -> ETA svc  Ringpop ring, SWIM gossip)
      |                 |   +--> Driver state store (CAS lease + token)
      |                 v
      |             Trip svc (state machine) -> Docstore (Raft) + outbox
      |                 | events
      +------------ Kafka -> Payments saga -> PSP + ledger, Fraud, Data lake
```

- **Edge gateways:** 8M persistent connections, auth, rate limits, and a registry (user -> node) so any service can push to a phone.
- **Location service:** validates pings (order, speed, spoofing), snaps to roads, updates the geo index, copies to Kafka.
- **Geo index:** in-memory map from H3 cell (Uber's hexagonal map grid) to drivers, sharded on a Ringpop ring (consistent hashing plus SWIM gossip); queries under 5 ms.
- **Driver state store:** linearizable; the only place that decides "is this driver free".
- **DISCO matcher:** per city; ranks candidates by road ETA, reserves one, offers.
- **ETA service:** contraction hierarchies with live traffic, plus ML correction.
- **Flink surge job:** per-cell supply and demand each minute, into a KV store.
- **Trip service:** trip state machine in Docstore (Raft over MySQL) with an outbox.
- **Payments:** saga for authorise, capture, void, refund; double-entry ledger.
- **Kafka:** joins the planes; feeds surge, payments, fraud, data lake.

**Flow A: request to match**
1. Request with idempotency key K; Demand service inserts trip T as REQUESTED (if absent on K) and starts payment auth.
2. Matcher gets AVAILABLE drivers in kRing k=2, widening to k=4, k=6 until 5 candidates.
3. One ETA call ranks up to 20 candidates (about 10 ms).
4. CAS AVAILABLE -> OFFERED (15 s lease) on the top driver; on failure, the next.
5. Accept: driver EN_ROUTE, trip MATCHED (version check). Decline: re-dispatch; after 3 rounds or 60 s, "no cars".

**Flow B: trip completion and payment**
1. Driver taps End; trip COMPLETED, fare from the server-side map-matched trail.
2. Transition and TripCompleted outbox event commit together; a relay publishes to Kafka.
3. Payments saga captures with key capture:T and writes the ledger.

## Page 3. The core deep dives

### 1. Geospatial index and the 1.25M/s write path
A ping is converted to an H3 resolution-9 cell (about 174 m edge). If the cell changed, the driver is removed from the old cell's set and added to the new one, as two idempotent ops keyed by driver id and timestamp. Nearby search takes kRing(cell, k), all cells within k hex steps; k=2 covers about a 0.9 km radius. Hexagons have six equidistant neighbours, so a ring approximates a circle. Entries expire after 30 s without a ping. Nothing durable sits here: if a node dies, the next pings rebuild it within 4 s.

### 2. No double-assigned driver: lease plus fencing token
Routing via the ring makes two matchers touching one driver rare, but not impossible during gossip churn. Correctness comes from the driver state store: CAS AVAILABLE -> OFFERED succeeds for only one matcher and returns a fencing token, a number that rises on every reservation. Example: matcher 1 holds token 41, stalls and its lease expires; matcher 2 reserves with token 42. When matcher 1 wakes and sends "accept with 41", the store rejects it. Leases are checked by the store's clock only.

### 3. Matching: greedy versus batched
Greedy gives the nearest driver to whoever asked first. Shreya is 1 minute from driver X and 2 from Y; Sethu asks 200 ms later and is 1 minute from X but 10 from Y. Greedy: Shreya gets X, Sethu gets Y, total 11 minutes. Batching every 1-2 s solves a min-cost assignment (Hungarian, O(n^3), fine for a few hundred per zone): Shreya gets Y, Sethu gets X, total 3 minutes. Use batching in dense zones and airports, greedy in sparse areas.

### 4. Payments with exactly-once effect
Authorise the estimate at request, capture the final fare at completion, void on cancel. Every call carries a deterministic key (auth:T, capture:T) stored with the request hash. A PSP timeout leaves the payment PENDING, resolved by querying the PSP with the same key, never a new one. The ledger is double entry: rider escrow -20, driver +18, platform +2 sums to zero.

**Data model:**
- **DriverLiveLocation** (RAM): driver_id -> entry, h3_cell -> set of driver_ids; shard key city_id + H3 res-6 parent.
- **DriverState** (strongly consistent KV): driver_id; state, version, fencing_token, lease expiry.
- **Trip** (Docstore): partition by hash(trip_id); indexes on (rider_id, requested_at) and (driver_id, requested_at).
- **IdempotencyRecord / PaymentIntent**: unique idem_key, partition by hash(rider_id), 90-day TTL.
- **LedgerEntry** (append-only): partition by account_id; order_id groups entries that sum to zero.

**Key APIs:**
- `POST /v1/quotes`: returns a fare, multiplier, ETA and HMAC-signed quote_id.
- `POST /v1/trips`: idempotent on (rider_id, idem_key); one active trip per rider.
- `POST /v1/offers/{id}/accept`: CAS on driver state with the token; a stale token loses.
- `POST /v1/trips/{id}/events`: arrived, start, end, cancel with an expected version.
- `WS /v1/driver/stream`: location pings with seq numbers to drop duplicates.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Location writes:** keep only the latest position in memory, shard by city then cell, batch at the gateway, send history to Kafka asynchronously.
- **Nearby-car reads:** serve from read replicas of each cell shard, cached per cell for 2 s, so they never contend with dispatch.
- **Hot cells (stadiums, airports):** split to a finer H3 resolution, run airports as dedicated FIFO queues, batch-match there.
- **ETA:** bulkheaded pools; dispatch ETAs get priority over quotes and map refresh.
- **Trip writes:** hash on trip_id so one big city is not one hot shard.

**Failure modes:**
- **Geo index node dies:** SWIM marks it faulty within seconds, neighbours take its cells, the next pings refill them in 4 s.
- **Matcher down in a city:** requests wait up to 30 s; a flag enables a greedy fallback on the same lease store. Active trips are unaffected.
- **Partition between matcher and lease store:** matching stops in that partition. This is deliberate: lose availability rather than double-assign.
- **Region lost:** the city moves to its standby region; pings rebuild the index; a trip the standby missed is rebuilt from an encrypted digest on the driver's phone; payments replay idempotently.
- **PSP outage:** circuit breaker, captures queue and retry with the same keys, a secondary PSP for new auths.
- **Kafka degraded:** the hot path does not wait on Kafka; the outbox keeps events in the DB, surge uses last known values.
- **Bad surge multiplier:** city caps, max change per minute, kill switch to 1.0x; riders pay the price in their signed quote.

**Degradation ladder:** slow nearby-car refresh first, then batched to greedy matching, then cached surge, then haversine ETAs. Never degrade the driver lock or the ledger.

**Trade-offs chosen:**
- **AP for locations, CP for leases, trips and money:** a stale location costs metres; a double charge costs trust.
- **H3 over quadtree or R-tree:** O(1) updates at 1.25M writes/s and uniform neighbours; quadtrees rebalance badly under constant movement.
- **Custom in-memory index over a database:** the latest position is overwrite-only and rebuildable in 4 s, so durability there is wasted cost.
- **Saga over 2PC:** a PSP cannot join 2PC, and locks across a 3 s card call kill throughput.
- **City homed in one region over global active-active writes:** dispatch is local, so homing avoids cross-region conflicts and limits blast radius.
- **At-least-once Kafka plus idempotent consumers over end-to-end exactly-once:** exactly-once across a PSP is impossible.

**What to measure:** request-to-offer p95 per city (alert on error-budget burn), match rate per cell, ingest lag (p99 under 1 s), ETA error, double-assignment count (page on 1), ledger imbalance (must be 0), PENDING payment age, Kafka lag for payments and surge.

## Page 5. Say it in the interview

> "I will design the full ride flow but go deepest on location, geo indexing and dispatch, where the scale is. Assume 25 million trips a day and 5 million drivers online, each pinging every 4 seconds: 1.25 million writes a second. The hard rules are an offer in 2 seconds, never one driver for two riders, and never a double charge. Locations can be a few seconds stale; trips and money cannot. So I split two worlds. The real-time world is in memory: pings update a geo index keyed by H3 hexagons, sharded by city with consistent hashing, and the matcher ranks candidates by road ETA and locks one driver with a lease before the offer. The durable world is the trip state machine in a Raft store and a payment saga with idempotency keys and a ledger. Kafka joins them and feeds surge pricing."

**Key points to land:**
- Say the AP/CP split in the first two minutes.
- 1.25M writes/s but only about 1 GB of live state: memory, sharded for throughput.
- H3 hexagons: equidistant neighbours, clean kRing search and smoothing.
- Shard the real-time plane by city then cell, with Ringpop and SWIM.
- No double assignment: a CAS lease with a fencing token, not routing.
- Greedy in sparse areas, batched every 1-2 s in dense zones; rank on road ETA.
- ETA from contraction hierarchies in about 1 ms, plus an ML correction.
- Surge: Flink per cell per minute, smoothed, capped, locked into a signed quote.
- Payments: auth then capture, saga, idempotency keys, double-entry ledger.
- The geo index rebuilds from pings in seconds; trips survive region loss.

**Likely follow-ups:**
1. **Why not Redis GEO?** Fine for a one-city MVP, but at 1.25M writes/s you shard it yourself and a city key goes hot.
2. **CP or AP?** Both, by component: the geo plane keeps serving stale positions in a partition; leases, trips and the ledger refuse writes rather than diverge.
3. **Why not 2PC for trip and payment?** The PSP will not join it, and it blocks if the coordinator dies; a saga with void and refund compensations matches how cards work.
4. **How is a payment exactly-once?** The effect is, not delivery: a deterministic key per operation, stored results, unknown outcomes resolved by asking the PSP.
5. **Matcher down in Mumbai at 9 am?** Active trips continue; new requests wait up to 30 s, then a greedy fallback runs on the same lease store, so it stays safe.

**Director layer:**
- **Cost drivers:** about 400 gateway nodes for 8M sockets, ETA compute provisioned at 10x, Kafka at about 1.2 GB/s cluster write, and in-country standby regions for data residency.
- **Phasing:** MVP with Redis GEO per city and greedy matching; then the sharded H3 index, batched matching, Flink surge, multi-region failover.
- **Team ownership:** real-time dispatch (location, geo, matcher), maps and ETA, marketplace pricing, trips platform, payments and ledger, edge and SRE.
- **Top risks:** double assignment in a partition, duplicate charges after PSP timeouts, losing trips in a region outage, GPS spoofing, and surge seen as gouging.
