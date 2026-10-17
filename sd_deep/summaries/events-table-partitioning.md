# Design a partitioning strategy for a large events table: the 5-page summary

An append-heavy order events table has reached 120 billion rows and grows by 3 billion a day, so inserts, vacuum, retention deletes and lookups are all degrading together. The single most important idea: the partition key follows the queries and the data lifecycle, so partition by time first (daily ranges, retention by dropping a partition) and by entity hash second, shard by entity across nodes, and tier anything older than 90 days to Parquet.

## Page 1. The problem, scope and numbers

**Pitch:** turn one huge, slowly dying PostgreSQL table into a partitioned, sharded store that ingests 100,000 events a second, answers "show me order X's history" in under 50 ms, and deletes old data instantly instead of with hours-long DELETE jobs.

**Who uses it:** support agents (order timelines), analysts (time-range counts), producers (writes that never block checkout), DBAs, and compliance (2-year audit trail).

**In scope:**
- **Batched ingest** from Kafka with dedupe on event_id; late events accepted up to 7 days.
- **Composite partitioning:** daily RANGE on event_ts, HASH on entity_id within each day.
- **Entity timelines** with a required time window (default last 30 days).
- **Lifecycle automation:** pre-create 7 days ahead; archive to Parquet and drop after 90 days.

**Out of scope:** 2-year analytics on the OLTP store, updating events (except legal erasure), stream processing, cross-region active-active writes.

**Non-functional targets:**
- **Ingest:** 100,000 rows/s for 2 h, insert p99 under 20 ms; queryable within 5 s p99.
- **Queries:** entity timeline p99 under 50 ms; daily aggregate under 5 s; under 10 partitions scanned.
- **Durability and operations:** synchronous standby, RPO under 1 minute; no manual partition work; retention under 1 s per day.
- **Cost:** hot storage under 150 TB; archive under 10% of hot cost per GB.

**Capacity math (3B events/day, 500 B per row with 2 indexes):**
- **Rate:** 3B / 86,400 = about 35,000/s average, 100,000/s peak.
- **Daily volume:** 3B x 500 B = 1.5 TB/day. Hot 90 days = 135 TB, far above a comfortable 5-10 TB per node, so shard across 16 nodes (the plan allows 16-24).
- **Leaf size:** 1.5 TB / 16 nodes = 94 GB per node per day; / 16 hash leaves = about 6 GB each. So vacuum and index builds stay small.
- **Partition count:** 90 days x 16 = 1,440 leaves, plus 7 future days = 1,552 per node, under 2,000. So daily, not hourly.
- **Per-node peak:** 100,000 / 16 = 6,250 rows/s, easy with COPY batches of 5,000.
- **Archive:** 3B x 300 B / 8 (Parquet compression) = about 110 GB/day; 2 years = about 80 TB on object storage.

## Page 2. The architecture

```
 Producers -> Kafka (64 partitions, key entity_id) -> Ingest workers
                                  (batch 5k / 200 ms, dedupe, route by entity)
                     +------------------+--------------------+
                     v                  v                    v
               Shard 1 (PG 16)     Shard 2 (PG 16)  ...  Shard 16
          events: RANGE by day on event_ts
            +-- events_2026_10_11 -> HASH(entity_id) leaves p0 .. p15
            |     each leaf: btree (entity_id, event_ts), BRIN (event_ts)
            +-- future days pre-created (+7), events_default (alert if used)
                     |
 Partition Manager: create +7d | detach >90d | export | verify | drop
                     v
 Object storage (Parquet, dt=YYYY-MM-DD/bucket=NN) -> Warehouse / Trino

 Query API -> entity_span lookup -> prune to shard + days + one bucket
```

- **Kafka topic:** durable buffer so checkout never waits on the database; keyed for per-entity order.
- **Ingest workers:** batch, dedupe, route by entity hash, COPY, commit offsets after the DB commit.
- **Partitioned events table:** per shard, daily ranges with 16 hash leaves and local indexes.
- **entity_span table:** first and last event time per entity, to bound timeline queries.
- **Partition Manager (pg_partman plus jobs):** creates future days, watches the default partition, archives.
- **Archiver:** exports to Parquet sorted by entity, verifies counts and checksums, registers in a catalog.
- **Query API:** requires a time window, routes by entity, falls back to the archive for old ranges.
- **Warehouse / Trino:** cross-entity analytics and history beyond 90 days.

**Flow A: ingest**
1. Producer publishes {event_id (UUIDv7), entity_id, event_ts, type, payload}.
2. Worker takes up to 5,000 records or 200 ms, drops ids already in Redis (SET NX, 24 h TTL).
3. Groups by shard, runs COPY per shard; PostgreSQL routes each row to its day and leaf.
4. Offsets commit only after all shards commit; a replay hits ON CONFLICT DO NOTHING.

**Flow B: support looks up order ORD123**
1. API clamps the window using entity_span, routes to shard hash(ORD123) % 16.
2. Query on entity_id and event_ts range prunes to those days and one leaf per day: about 10 ms.

## Page 3. The core deep dives

### 1. Composite partitioning: time first, hash second
Range by day matches the lifecycle: retention is "drop yesterday-minus-90", and time-range queries prune to a few days. Hash on entity_id inside each day spreads today's hot writes over 16 leaves and shrinks each entity lookup to one small leaf per day. Example: Shreya opens order ORD123 for the last 30 days; the planner touches 30 leaves of about 6 GB, each with a btree on (entity_id, event_ts), instead of one 135 TB table. A bonus: changing 16 hash leaves to 32 applies only to future days, and queries still work because pruning is per day.

### 2. Pruning only works if every query names the time
The optimiser skips partitions only when the predicate constrains event_ts. A dashboard query with no time filter scans all 1,552 leaves. So the API rejects queries without a window, entity_span bounds the range, direct SQL hits a 30 s statement_timeout, and queries that scan more than 20 partitions are flagged from pg_stat_statements. Prepared statements use runtime pruning to keep planning time down.

### 3. Retention by DETACH and DROP, never DELETE
A DELETE in an MVCC database marks every row dead, writes WAL for each (replication lag) and leaves vacuum work. Instead, nightly: DETACH PARTITION CONCURRENTLY for day D-91 (no long lock on inserts), export the 16 leaves to Parquet, verify row counts and checksums, keep the detached table 3 days, then DROP. Space comes back instantly with no WAL storm.

### 4. Idempotent ingest within partition rules
PostgreSQL requires unique constraints on a partitioned table to include the partition keys, so a global unique event_id is impossible. The PK is (event_ts, entity_id, event_id): ON CONFLICT catches a retry even after the 24 h Redis TTL, as long as producers stamp event_ts once and keep it on retry (UUIDv7 embeds creation time, so a re-stamp is detectable).

**Data model:**
- **events** (per shard): RANGE (event_ts) daily, then HASH (entity_id) modulus 16; PK (event_ts, entity_id, event_id).
- **entity_span:** PK entity_id; first_ts, last_ts via batched GREATEST/LEAST upserts.
- **partition_catalog** (control DB): PK (shard, day); drives lifecycle and archive routing.
- **Archived events:** Parquet at dt=YYYY-MM-DD/bucket=NN; row-group stats skip by entity_id.

**Key APIs:**
- `GET /v1/entities/{entity_id}/events?from&to`: keyset pagination on (event_ts, event_id).
- `GET /v1/events/aggregate?type&from&to&bucket=1h`: rollups or warehouse beyond 7 days.
- `POST /internal/partitions/ensure`: idempotent, run hourly.
- `POST /internal/partitions/{day}/archive`: detach, export, verify, drop state machine.
- `POST /internal/erasure`: hot deletes plus targeted Parquet rewrites.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Write rate:** add shards by entity; scale ingest workers up to the 64 Kafka partitions; bigger COPY batches.
- **Sale-day leaf growth:** at 5x, one shard's day reaches 500 GB, but hash leaves keep each at about 30 GB; insert-triggered autovacuum keeps visibility maps current.
- **Planner time:** keep leaves under 2,000 per table; merge older days into weekly partitions or archive sooner.
- **Hot entities:** a system account producing 20% of events gets a composite key (entity_id plus minute bucket) or its own table.
- **Analytics load:** rollup tables or ClickHouse, never heavy GROUP BYs over 45 TB of OLTP partitions.

**Failure modes:**
- **Future partitions missing at midnight:** rows land in events_default, an alert fires, operators create partitions and move rows; producers see no errors.
- **Shard primary fails:** synchronous standby promoted in about 30 s; that shard's workers back off with jitter; Kafka buffers; other shards unaffected.
- **Archive fails halfway:** catalog stays "detaching", nothing is dropped, the job retries and overwrites partial files.
- **Kafka lag in a sale:** producers unaffected; add workers; defer non-critical index builds.
- **Event 10 days late:** goes to events_late, merged weekly, so nothing writes into a partition being archived.
- **Producer clock 3 h ahead:** reject or clamp events over 1 h in the future; record ingested_at.

**Trade-offs chosen:**
- **Time over entity as the top key:** retention and time pruning are the biggest wins.
- **Daily over hourly or monthly:** about 6 GB leaves and under 2,000 partitions.
- **Shard by entity over shard by time:** entity queries stay on one shard; time sharding makes one hot shard.
- **Parquet over keeping data in PostgreSQL:** about 8x smaller and still queryable.
- **Composite PK plus Redis over a global unique index:** fits PostgreSQL's partition rules.
- **PostgreSQL with Citus-style sharding over Cassandra or ClickHouse:** team skills and SQL; TimescaleDB is a close alternative.

**What to measure:** insert p99 and COPY duration per shard, Kafka lag, partitions scanned and planning time, rows and bytes per leaf with skew, future partitions available (alert below 3), rows in default (alert above 0), autovacuum duration and transaction ID age, archive lag past 90 days and verification failures, hot and cold storage cost.

## Page 5. Say it in the interview

> "I start by asking how the events are queried, because the access pattern decides the partition key. I assume 3 billion events a day, append-only, 90 days hot and 2 years archived, with two query shapes: all events for one order in a time window, and time-range scans for dashboards. A single table works until vacuum, index size and delete-based retention fall over. So I partition by time first, daily ranges, because retention becomes a partition drop and time queries prune; then hash by entity inside each day, so hot writes spread and an order lookup touches one small leaf per day. Across nodes I shard by entity, 16 shards. Every query must carry a time window. After 90 days, partitions are detached, exported to Parquet, verified and dropped."

**Key points to land:**
- The partition key follows the queries and the lifecycle: time first, entity hash second.
- Retention by DETACH and DROP, never DELETE.
- Every query must constrain event_ts so pruning works; enforce it in the API.
- Hash leaves spread today's writes and shrink entity lookups.
- Shard by entity across nodes, partition by time within each node.
- Keep leaves 1-50 GB and partition counts in the low thousands.
- Tier to Parquet after 90 days, verify before drop.
- Idempotent ingest: event_id, PK with the partition keys, offsets after commit.

**Likely follow-ups:**
1. **Why not Cassandra keyed by (entity_id, day)?** It scales writes well, but time-range analytics and ad-hoc SQL get hard and TTL deletes create tombstones; valid at 10x the write rate.
2. **Would TimescaleDB simplify this?** Yes: hypertables automate chunk creation, retention and columnar compression; the concepts stay the same.
3. **GDPR erasure across archives?** Prefer crypto-shredding with per-user keys; otherwise rewrite only the Parquet files whose row-group stats include that entity.
4. **Lookups by payment_id, not the shard key?** Put order_id on payment events, or keep a small payment_id -> (order_id, ts) index table to route and prune.
5. **How do you migrate 120 billion rows?** Replay a day into staging and check pruning with EXPLAIN; then dual-write new events and backfill history day by day, newest first.

**Director layer:**
- **Cost drivers:** 135 TB of hot SSD across 16 nodes with standbys, versus about 80 TB of Parquet on cheap object storage.
- **Phasing:** partition and automate lifecycle first, then shard by entity, then archive and warehouse access.
- **Team ownership:** the existing PostgreSQL team owns shards and lifecycle; data platform owns archive and warehouse; producers own event schemas.
- **Top risks:** queries without a time predicate, a failed pre-creation job at midnight, hash skew from huge entities, and dropping a partition before its archive copy is verified.
