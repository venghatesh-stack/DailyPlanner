# Partitioning strategy for a large events table: recall card

> **Hook:** Buffer in Kafka → COPY in batches → Range by day → Hash by entity → Detach, archive and drop after 90 days

**P · Problem:** It's really a data-lifecycle problem: the partition key must follow the queries and how data ages out.

**N · Numbers:**
1. 1.5 TB/day gives 135 TB hot for 90 days, so shard across 16 nodes.
2. 1.5 TB / 16 nodes / 16 hash leaves is about 6 GB per leaf, so vacuum and index builds stay small.
3. 90 days x 16 leaves plus 7 future days is 1,552 partitions per node, so daily, not hourly.

**H · Hard part:** Making pruning actually happen, since every query must name a time window, and deleting old data without a WAL storm.

**B · Boxes:** `Producers → Kafka → Ingest workers → PostgreSQL shard → Daily range → Hash leaf`

Side path: `Partition Manager → Parquet on object storage → Trino` for history beyond 90 days.

**D · Decisions:**
1. Time over entity as the top partition key, because retention and time pruning are the biggest wins.
2. Shard by entity over shard by time, because entity queries stay on one shard and time sharding makes one hot shard.
3. Parquet over keeping old data in PostgreSQL, because it is about 8x smaller and still queryable.

**F · Failures:**
1. Future partitions missing at midnight → rows land in events_default, an alert fires; producers see no errors.
2. Archive fails halfway → the catalog stays "detaching", nothing is dropped, and the job retries.

**C · Close:** "So I start from how the events are queried. I partition by day first, because retention becomes a partition drop and time queries prune, then hash by entity inside each day so hot writes spread and an order lookup touches one small leaf per day. Across nodes I shard by entity, 16 shards. Every query must carry a time window. After 90 days, partitions are detached, exported to Parquet, verified and dropped."

**Quiz yourself:**
1. Why not DELETE old rows? → MVCC marks every row dead, floods WAL and leaves vacuum work.
2. Why can't event_id be globally unique? → PostgreSQL unique keys must include the partition keys.
3. What happens to a query with no time filter? → It scans all 1,552 leaves, so the API rejects it.
