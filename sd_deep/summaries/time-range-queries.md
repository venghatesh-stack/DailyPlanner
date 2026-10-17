# Design a time-range query store (time-series and event history): the 5-page summary

A shared platform that answers "what happened to X between t1 and t2" for order history, metrics, delivery timelines and price changes. The single most important idea: time always increases, so sorting by time makes range scans cheap but sends every new write to one hot partition; cluster by (entity, time bucket), spread writes by hashing the entity, prune reads with bucket and block min/max metadata, and keep old data cheap with compression, rollups and tiering.

## Page 1. The problem, scope and numbers

**Pitch:** one store with a stable API for time-range history, so teams stop building their own history tables that time out during sale events and cost more every month.

**Who uses it:** service teams (metrics, order and delivery histories), dashboards and alerting (fresh, complete windows), analysts (30-day and 13-month views), platform and finance (storage cost).

**In scope:**
- **Batched writes:** up to 5,000 points per request with an idempotency key.
- **Range reads** for one series: half-open [from, to), order, limit and cursor.
- **Aggregated reads** with a step (1 s to 1 day): sum, count, min, max, avg, percentiles via sketches.
- **Multi-series queries** by label filter with group-by, bounded by a series limit.
- **Automatic resolution:** raw up to 2 days, 1-minute rollups up to 60 days, 1-hour beyond.
- **Retention** per dataset; late data accepted up to 7 days back with rollup repair.

**Out of scope:** full-text search in payloads, cross-dataset joins, the alerting engine itself, multi-region active-active writes.

**Non-functional targets:**
- **Read latency:** p99 under 300 ms for 24 hours of one series; under 2 s for a 30-day aggregate.
- **Write latency:** p99 ack under 50 ms after Kafka acks=all.
- **Freshness:** queryable within 10 s p99 of the ack.
- **Availability:** reads 99.95%, writes 99.99% (Kafka buffered).
- **Durability:** zero loss of acknowledged writes; RF=3 hot, 11 nines in object storage.
- **Cost:** under 2 bytes per raw point on disk; scale out linearly to 2M points/s.

**Capacity math (500k points/s average, 1.5M/s peak, 10M active series):**
- **Points:** 500k x 86,400 = 43.2 billion a day. So appends must be sequential (an LSM engine), not B-tree index updates.
- **Ingest bandwidth:** 500k x 64 B = 32 MB/s, about 96 MB/s at peak. Easy for Kafka, which also absorbs bursts.
- **Storage:** 43.2B x 2 B = about 86 GB/day of metrics; about 500 GB/day with event payloads. 7 hot days x 500 GB x RF=3 = 10.5 TB SSD; the other 23 days of raw, about 11.5 TB, go to object storage. So tier by age.
- **Rollups:** 10M series x 1,440 minutes x 5 aggregates x 4 B = 288 GB/day raw, about 40 GB compressed, about 16 TB for 13 months. So long ranges read rollups, not raw.
- **Shards:** about 50k points/s per shard; 1.5M/s peak needs 30 shards x 3 replicas = 90 nodes.
- **Reads:** 24 hours at 10 s resolution is 8,640 points, about 17 KB; 20k QPS x 17 KB = 340 MB/s, mostly from page cache.

## Page 2. The architecture

```
 producers (services, devices, order events)
     | batched writes, 1-5k points per request
     v
 Ingest API -> Kafka (key series_id, 72h replay) -> Ingest workers
                                                   (dedupe, bucket, route)
                                                         |
                     +--------------+--------------------+
                     v              v                    v
                 Shard A        Shard B   ...        Shard N  (LSM, RF=3, W=2)
                     | seal 2h blocks, compact, roll up 1m / 1h, upload
                     v
             Object store (Parquet cold blocks) <--- Block index (min/max)
                     ^                                    ^
 dashboards -> Query API -> Query planner: pick tier and resolution,
                            prune, fan out, k-way merge  (+ result cache)
```

- **Ingest API:** auth, timestamp checks, tenant rate and cardinality limits, write to Kafka.
- **Kafka:** durable buffer keyed by series_id; absorbs bursts and lets shards replay for 72 hours.
- **Ingest workers:** dedupe, assign the time bucket, route to shard replicas, apply backpressure.
- **Storage shards:** WAL and memtable, sealed compressed 2-hour blocks, compaction and expiry.
- **Series index:** labels to series_ids, for multi-series queries.
- **Block index:** (series range, bucket) to block files with min and max time; enables pruning.
- **Rollup service:** 1-minute and 1-hour aggregates, recomputed when late data lands.
- **Tiering job:** moves sealed blocks to object storage, drops expired buckets whole.
- **Query planner:** aligns the range, picks resolution, prunes, fans out, merges, paginates.
- **Result cache:** results for sealed windows, which never change once complete.

**Flow A: write**
1. POST up to 5,000 points with an idempotency key; produce with acks=all; return 202.
2. A worker dedupes and sends to the shard owning hash(series_id); WAL group commit every 5 ms.
3. After 2 of 3 replicas ack, commit the Kafka offset; blocks seal 10 minutes after their window closes.

**Flow B: read**
1. Map [from, to) to buckets; pick raw, 1-minute or 1-hour.
2. Prune blocks whose min/max do not overlap; read hot and cold legs in parallel (250 ms timeout).
3. Merge sorted streams, aggregate per step, return a page and a cursor.

## Page 3. The core deep dives

### 1. The key: entity first, time second
Never lead the key with time: every write would hit today's partition. The partition key is (series_id, day bucket), hashed on the series across shards; the sort key inside is timestamp then seq. A seller's last 24 hours is then one or two contiguous sorted scans. A series writing over 5k points/s is switched to a salted key (series, day, salt 0..7), and reads fan out to the 8 salts and merge.

### 2. Prune before you scan
The planner turns [from, to) into bucket ids, asks the block index only for those buckets, then drops blocks whose [min_ts, max_ts] miss the range. Columnar files skip unread columns. Billions of rows become a handful of compressed blocks. Resolution is chosen by width: raw for 2 days or less, 1-minute rollups up to 60 days, 1-hour beyond, since scanning raw for a year is 3,000x more data.

### 3. Compression (Gorilla style)
Regular series have near-constant intervals, so the delta of the delta of timestamps is usually 0 and costs 1 bit. Consecutive values often share sign, exponent and high bits, so XOR with the previous value is mostly zeros. Result: about 1.4 bytes per point instead of 16.

### 4. Late data, corrections and pages
A device offline for 3 hours sends points into a sealed window. They go to a small delta block, the affected rollup windows are marked dirty and recomputed, and cached results are invalidated. The window's watermark (the newest complete point in time) stays provisional until then, so alerts do not fire on partial data. Corrections are new versions with a higher seq; the merge keeps the newest. Cursors are (ts, seq), not offsets, so pages never shift as data streams in.

**Data model:**
- **RawPoint:** partition (series_id, bucket_day), clustering (ts_ms, seq); value or payload.
- **Block** (etcd or Postgres): block_id, shard, series range, min_ts, max_ts, resolution, tier, uri.
- **Series:** series_id = hash(name + sorted labels); posting lists label=value -> series_ids; cardinality cap per tenant.
- **Rollup** (columnar, per resolution): partition (series_id, month); count, sum, min, max, sketch.

**Key APIs:**
- `POST /v1/points`: up to 5,000 points or 1 MB; rejects timestamps over 10 minutes ahead or 7 days old.
- `GET /v1/series/{series_id}/range`: from, to, step; returns points and next_cursor.
- `POST /v1/query`: label filter and group-by; rejects over 50k series or about 1B points.
- `PUT /v1/datasets/{dataset}/retention`: applied per bucket, audit-logged.
- `GET /v1/datasets/{dataset}/watermark`: lets reports avoid incomplete windows.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot "now" partition:** hash the entity, salt only series over 5k points/s, alert on shard skew above 2x mean.
- **Ingest bursts:** Kafka buffers; per-tenant 429s for low-priority datasets if lag passes 60 s.
- **Cardinality:** per-tenant series caps; model per-order history as events, not metric labels.
- **Cold reads:** block pruning, columnar files, a local SSD cache, rollups for wide ranges.
- **Runaway queries:** a cost estimator rejects them up front; 30 s timeout; dashboards and exports in separate pools.

**Failure modes:**
- **Shard replica crashes:** W=2 of 3 still succeeds; reads use other replicas; it rebuilds from peers and replays Kafka.
- **Kafka lag in a sale spike:** writes stay durable; freshness and the watermark lag.
- **Object storage slow:** cold legs time out at 1 s; fall back to rollups and mark results partial.
- **Block index down:** hot queries use a cached shard map (TTL 60 s); tiering and retention pause safely.
- **Rollups behind or wrong:** serve beyond the rollup watermark from raw; rebuild any window from raw.
- **Shard down mid-query:** retry another replica with jitter, then return partial=true with missing ranges.

**Trade-offs chosen:**
- **(entity, time bucket) hashed on entity over time-first keys:** spreads writes and keeps per-entity scans sorted.
- **LSM with time-window compaction over B-tree or memory only:** sequential writes at 500k/s and retention by dropping files.
- **Server-side rollups over raw scans:** wide queries become sub-second at small storage cost.
- **Late data for 7 days over unbounded:** unbounded keeps every window mutable and defeats caching.
- **Partial results with a flag over failing:** a partial dashboard in an incident beats a blank one.
- **Buy for metrics, build for entity history:** an open-source TSDB for metrics; a Cassandra-style service for event histories with payloads and corrections.

**What to measure:** ingest rate and skew per shard; ingest-to-queryable lag and watermark age; query p99 by range width; blocks scanned and prune ratio; cache hit ratio; compaction backlog; late-data rate and rollup queue; active series per tenant; bytes per point and cost per tier; partial-result rate.

## Page 5. Say it in the interview

> "First I pin down the query shape: mostly one entity's history over a recent window, like a seller's orders or a host's metrics for the last day, with about 500k writes a second, mostly appends, some late. I cluster by entity and time so a range is a contiguous scan, but time alone is never the partition key, or every write hits today's partition. The key is series id plus a day bucket, hashed across shards, with timestamp as the sort key. Writes go through Kafka into LSM shards that seal compressed two-hour blocks. After 7 days, blocks move to object storage as columnar files with min and max time in a block index, and a rollup job builds 1-minute and 1-hour aggregates. The planner turns a range into buckets and blocks, picks the coarsest resolution that answers, fans out and merges."

**Key points to land:**
- The entity you always filter by is the partition key; time is the sort key.
- Never lead with time: hash the entity, bucket the time, salt only hot keys.
- LSM with time-window compaction: sequential writes, sorted scans, drop files for retention.
- Gorilla compression gets regular series under 2 bytes per point.
- Prune before you scan: buckets, then block min/max, then columns.
- Rollups use mergeable aggregates (count, sum, min, max, sketches); never average averages.
- Event time plus watermarks; expose completeness so alerts skip partial windows.
- Tier by age: SSD for 7 days, object storage after, cached cold reads.
- Half-open intervals and (ts, seq) cursors: no duplicate or missing rows at boundaries.
- Fail partially and say so with partial=true.

**Likely follow-ups:**
1. **Why not Postgres with an index on (entity_id, ts)?** It is the right start and, with time partitioning, works to a few billion rows; it breaks on 500k inserts/s, vacuum bloat and months of raw data on SSD.
2. **Top 10 sellers between t1 and t2?** That aggregates across all entities, so serve it from the columnar tier or rollups grouped by seller, or precomputed hourly top-K.
3. **Multi-region?** Writes go to the tenant's home region; data copies asynchronously to a DR region with an RPO of a few minutes.
4. **Exact counts?** Counts in rollups are exact; only sketch percentiles and HyperLogLog distinct counts are approximate.
5. **The one metric to watch?** Watermark age: it captures ingest, shard and rollup health in one number users feel.

**Director layer:**
- **Cost drivers:** about 10.5 TB of replicated hot SSD, about 90 shard nodes at peak, object storage and cold-read cost; the target is 5x lower cost per point than today.
- **Phasing:** start teams on Postgres or TimescaleDB with time partitioning; move to the sharded LSM and tiering when ingest or size forces it; aim to migrate 80% of teams within 2 quarters.
- **Team ownership:** one platform team owns ingest, storage and query; product teams own their datasets, retention and cardinality budgets.
- **Top risks:** a hot current-time partition, label cardinality explosions, late data making rollups wrong, and slow, costly cold reads.
