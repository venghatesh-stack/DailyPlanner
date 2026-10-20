# Uber (ride-hailing): recall card

> **Hook:** Ping every 4 s → H3 geo index → Rank by ETA → Lease one driver → Trip in Raft → Payment saga

**P · Problem:** It's really a real-time two-sided marketplace that splits into an AP location plane and a CP plane for leases, trips and money.

**N · Numbers:**
1. 5M drivers / 4 s = 1.25M pings/s, so the write path never waits on a disk.
2. 5M x 200 B = 1 GB of live state, so it fits in RAM and is sharded for throughput, not size.
3. About 290 requests/s, 3,000/s on New Year's Eve, so spend the budget on consensus and idempotency.

**H · Hard part:** Absorbing 1.25M location writes a second while never giving one driver to two riders and never charging twice.

**B · Boxes:** `Edge gateway → Location service → H3 geo index → DISCO matcher → Driver state store → Trip service`

Side path: `Trip outbox → Kafka → Payments saga, Flink surge, data lake`.

**D · Decisions:**
1. AP for locations over one consistency model, because a stale location costs metres but a double charge costs trust.
2. H3 over quadtree or R-tree, because updates are O(1) at 1.25M writes/s with uniform neighbours.
3. Saga over 2PC, because a PSP cannot join 2PC and locks across a card call kill throughput.

**F · Failures:**
1. Geo index node dies → SWIM marks it faulty; neighbours take its cells and pings refill them in 4 s.
2. Partition between matcher and lease store → matching stops there, rather than risk a double assignment.

**C · Close:** "I split two worlds. The real-time world is in memory: pings update a geo index keyed by H3 hexagons, sharded by city with consistent hashing, and the matcher ranks candidates by road ETA and locks one driver with a lease before the offer. The durable world is the trip state machine in a Raft store and a payment saga with idempotency keys and a double-entry ledger. Kafka joins them and feeds surge pricing."

**Quiz yourself:**
1. What stops a stalled matcher accepting late? → The fencing token; the store rejects the stale number.
2. Greedy or batched matching? → Batched every 1-2 s in dense zones, greedy in sparse areas.
3. How is a payment exactly-once? → Deterministic keys like capture:T; unknown outcomes are resolved by asking the PSP.
