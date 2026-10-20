# time-range query store (time-series and event history): recall card

> **Hook:** Kafka buffer → Hash entity, bucket time → LSM blocks → Roll up → Tier to object store → Prune and merge

**P · Problem:** It's really an append-heavy sorted-range problem where time-ordered keys create one hot partition.

**N · Numbers:**
1. 43.2 billion points a day, so appends must be sequential in an LSM engine, not B-tree updates.
2. 7 hot days x 500 GB x RF=3 = 10.5 TB SSD, so tier older blocks to object storage.
3. 1.5M points/s peak at about 50k/s per shard, so 30 shards x 3 replicas = 90 nodes.

**H · Hard part:** Spreading writes without breaking contiguous range scans, and keeping wide or old queries cheap and correct when late data arrives.

**B · Boxes:** `Ingest API → Kafka → Ingest workers → LSM shards → Query planner`

Side path: `Shards → sealed 2h blocks → Object store + block index` with 1-minute and 1-hour rollups.

**D · Decisions:**
1. (entity, time bucket) hashed on entity over time-first keys, because it spreads writes and keeps per-entity scans sorted.
2. Server-side rollups over raw scans, because wide queries become sub-second at small storage cost.
3. Partial results with a flag over failing, because a partial dashboard in an incident beats a blank one.

**F · Failures:**
1. Shard replica crashes → W=2 of 3 still succeeds; it rebuilds from peers and replays Kafka.
2. Object storage slow → cold legs time out at 1 s; fall back to rollups and mark results partial.

**C · Close:** "Most queries are one entity's history over a recent window, at about 500k writes a second. The key is series id plus a day bucket, hashed across shards, with timestamp as the sort key, so a range is a contiguous scan but writes spread out. Writes go through Kafka into LSM shards that seal compressed two-hour blocks. Old blocks move to object storage with min and max time in an index. The planner prunes blocks, picks the coarsest resolution that answers, fans out and merges."

**Quiz yourself:**
1. Why never lead the key with time? → Every write would hit today's partition.
2. How does Gorilla compression work? → Delta-of-delta timestamps and XOR of values, about 1.4 bytes per point.
3. What is the one metric to watch? → Watermark age, which captures ingest, shard and rollup health.
