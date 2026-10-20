# likes and reactions counter at scale: recall card

> **Hook:** Desired state → CAS upsert → Delta to Kafka → Coalesce 1 s → Redis hash → Snapshot

**P · Problem:** It's really a write-hot-spot aggregation problem: an exact per-user fact plus a derived count that may be a few seconds stale.

**N · Numbers:**
1. About 115K writes/s, 580K/s at a 5x peak, so the write path cannot touch a shared row.
2. 2B objects x 64 B = 128 GB of counters, so counts are served from a Redis cluster of about 20 shards.
3. A 1 s coalescing window turns a 100K/s object into about 6 increments per second, so skew, not volume, is the hard part.

**H · Hard part:** A viral post taking 100K reactions per second on one key, while retries must never double count.

**B · Boxes:** `Client → Reaction Service → Cassandra → Kafka → Counter Aggregator → Redis counters`

Side path: `Feed → near cache → Redis MGET → Count Store` for batched reads.

**D · Decisions:**
1. Async aggregation over synchronous increments, because 1-5 s of staleness beats write latency tied to hot rows.
2. Adaptive over always-on sharding, because 99.9% of objects are cold and sharding all multiplies reads.
3. Redis plus snapshots over Cassandra counters, because Cassandra counters are not idempotent on retry.

**F · Failures:**
1. Aggregator crashes after HINCRBY → the offset fence in the same MULTI skips already-applied records on restart.
2. Redis shard lost → reads fall back to snapshots, then rebuild from snapshot plus Kafka replay.

**C · Close:** "So I separate the fact from the aggregate. The fact is an idempotent upsert, partitioned by object, and a delta goes to Kafka only when state really changed. An aggregator coalesces for a second and applies one increment per object and type to Redis, with snapshots behind it. Hot keys get sharded sub-counters and a near cache. If anything downstream fails, counts get stale, never wrong for long."

**Quiz yourself:**
1. Why does a retry not double count? → The API sets desired state, so an unchanged state emits no delta.
2. Why not HyperLogLog? → It cannot remove elements, so it fails on unlikes.
3. How do you prove counts are right? → A reconciler recounts sampled objects from the truth store.
