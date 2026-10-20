# Backpressure for a write-heavy pipeline: recall card

> **Hook:** Admit by tenant and class → Append to Kafka, then ack → Consumers pull at the DB's pace → AIMD finds the limit → Shed low priority first

**P · Problem:** It's really a flow-control problem: making the fastest stage respect the slowest one without losing acknowledged writes.

**N · Numbers:**
1. 500k writes/s at peak against a sink of 80k/s builds a 378 GB backlog in 15 minutes, so a durable log must absorb it.
2. Draining that backlog at 30k/s spare takes 3.5 hours, so we shed or sample clickstream in red.
3. 80k rows/s in 500-row batches at 25 ms needs only 4 batches in flight, so the limiter settles low.

**H · Hard part:** Absorbing 10x bursts without unbounded queues, retry storms or dropping a write that already got a 2xx.

**B · Boxes:** `Producer SDK → Gateway → Ingest pods → Kafka → Consumers → Sink DB`

Side path: `Lag, buffer and sink p99 → Pressure Controller → gateway admit rates`.

**D · Decisions:**
1. Kafka between producers and the DB over synchronous writes, because it decouples rates at the cost of eventual consistency.
2. Reject with 429 over blocking producers, because blocking hides overload and ties up threads.
3. Spilling bulk over dropping it, because spill is cheap and can be backfilled.

**F · Failures:**
1. Sink DB degraded → AIMD halves, the breaker opens, consumers pause, lag grows in Kafka and bulk spills.
2. Retry storm from an old SDK → retries are shed first and per-tenant buckets cap the tenant.

**C · Close:** "The design is a pipeline of bounded queues. A gateway applies per-tenant token buckets, ingest appends to Kafka with acks all and returns 202, and consumers pull at the rate the database can take with an adaptive limiter and batched idempotent upserts. A pressure controller watches lag and database latency and tightens admission at the edge, shedding low priority first. Retries use jitter and a budget, and I alert on lag in seconds, not CPU."

**Quiz yourself:**
1. What are the only three things you can do with excess load? → Buffer it, slow it or drop it, chosen per class.
2. How does AIMD work? → Add one in-flight write when latency is fine; halve it on a spike or error.
3. Why scale consumers on lag, not CPU? → CPU stays low while waiting on a slow database.
