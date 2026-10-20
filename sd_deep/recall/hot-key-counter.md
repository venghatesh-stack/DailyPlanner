# Counter service that avoids hot keys (likes, views, inventory-style counts): recall card

> **Hook:** Like edge insert-if-absent → Aggregate in memory → Flush every 1 s → Split hot keys into sub-counters → Roll up total → Cache reads

**P · Problem:** It's really a write-skew problem: partitioning spreads keys, not the load on one key.

**N · Numbers:**
1. One viral key at 500,000 writes/s against about 100,000 ops/s per Redis shard, so one key cannot live in one place.
2. 100 ingest nodes each see about 5,000/s and flush once a second, so the store sees about 100 writes/s for that key, 5,000x fewer.
3. 1B keys is only about 60 GB, so this is a throughput problem, not a size problem.

**H · Hard part:** Absorbing one key's write storm without hurting its shard neighbours, while never double counting a like.

**B · Boxes:** `Client → Ingest node (aggregator) → Kafka counter-deltas → Counter writers → Cassandra sub-counters → Rollup → Redis totals`

Side path: `Count-min sketch → Hot Key Detector → etcd (N shards per hot key)`.

**D · Decisions:**
1. Aggregate on ingest nodes over clients or after Kafka, because it is the biggest cut before any shared resource.
2. Adaptive N over a fixed large N, because most keys are cold and a big N multiplies read and storage cost.
3. Materialised total over sum-on-read, because a few seconds of staleness is fine and fanning out 5M reads is not.

**F · Failures:**
1. Ingest node crash → up to 1 s of its view deltas lost; likes are safe in the edge table.
2. Rollup lag → totals go stale but nothing is lost; alert over 10 s.

**C · Close:** "Views can be approximate and a few seconds stale; likes must be exact per user. A naive INCR breaks because one Redis shard does about 100 thousand operations a second. So the like edge is the truth and the count is derived, ingest nodes aggregate in memory and flush every second, and hot keys split into sub-counters whose total is rolled up and cached. A count-min sketch finds the hot keys."

**Quiz yourself:**
1. Why not Redis INCR on a cluster? → One hot key still sits on one single-threaded shard.
2. How do Kafka replays not double count? → Writers checkpoint offsets atomically with the update.
3. How does the liker see it instantly? → The response returns cached total + 1.
