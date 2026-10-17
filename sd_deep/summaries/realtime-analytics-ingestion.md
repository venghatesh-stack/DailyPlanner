# Design a real-time analytics ingestion pipeline: the 5-page summary

This pipeline turns 5 billion small, messy events a day into dashboards that are queryable within 10 seconds and still correct when events arrive late, duplicated or out of order. The single most important idea: a stream-first path for freshness (Kafka, Flink, a real-time OLAP store) plus a batch correction path from the lake for truth, joined by event-time windows, client-generated event ids and idempotent upserts.

## Page 1. The problem, scope and numbers

**Pitch:** during flash sales and festive campaigns, teams must see GMV, conversion and payment failures minute by minute, not from a nightly batch, with one governed pipeline instead of many ad-hoc ones.

**Who uses it:** sale-event managers (live GMV, stock-outs by city), analysts (trusted events, replay), teams emitting events (simple SDK), SRE (business health signals), finance and compliance (reconciled numbers, PII deletion).

**In scope:** batched HTTPS collection validated against registered schemas, with PII tokenised at ingest; events durable in Kafka before the ack and archived to the lake; dedup on event_id over 24 h, enrichment and event-time windowed aggregates (1 min, 5 min, 1 h); a real-time OLAP store behind a SQL query API with quotas and a certified metrics catalog; anomaly alerts; replay from Kafka (3 days) or the lake (13 months).

**Out of scope:** the BI front end, an online ML feature store, the finance ledger as system of record, ad attribution.

**Non-functional targets:**
- **Freshness:** event-to-queryable p95 under 10 s (p99 under 30 s); aggregates final within window plus 5 minutes.
- **Query latency:** dashboards p95 under 1 s on 30 days of data, p99 under 3 s.
- **Availability:** collectors 99.95%, query layer 99.9%.
- **Correctness:** exactly-once aggregates; daily stream vs batch delta under 0.5%; accepted-event loss under 0.01%.
- **Durability:** accepted events survive a broker or AZ loss; lake copy within 1 h.

**Capacity math (5B events/day, 1 KB raw JSON, about 300 B after Avro and compression):**
- **Rate:** 5e9 / 86,400 = 58k/s; peak about 4x, design for 250k/s; batches of 20-50 mean about 10k requests/s. So collectors stay stateless.
- **Bandwidth:** 250 MB/s into collectors; 75 MB/s compressed in Kafka; x3 replication = 225 MB/s.
- **Kafka storage:** 1.5 TB/day x 3 replicas x 3 days = 13.5 TB. So Kafka short, lake long (about 300 TB over 13 months).
- **OLAP detail:** about 0.5 TB/day; 30 days x 2 replicas = 30 TB; rollups only about 50M rows/day. So tiles hit rollups.
- **Partitions:** 75 MB/s at 2 MB/s each needs 40; use 256 so parallelism can grow.
- **Dedup state:** 5e9 ids x 40 B = 200 GB of RocksDB, 1.6 GB per task over 128 slots; a Bloom filter cuts it about 5x.

## Page 2. The architecture

```
 SDKs (batch 50 ev / 10 s)   Backend services    CDC (orders, inventory)
        |                          |                     |
        v                          v                     |
 Collector fleet: auth, schema check, PII token, 202     |
        | produce, key = user_token, acks=all            v
 Kafka: raw.events (256 partitions, RF3, 3 days) + cdc.* topics
        |                                      |
        v                                      v
 Flink: dedup, enrich, event-time        Kafka Connect -> Iceberg lake
 windows, watermarks, late data                |
        | enriched.events, agg.minute          v
        v                                Spark batch -> offline segments
 Real-time OLAP (Pinot / Druid) <--------------+
        | SQL, p95 < 1 s
        v
 Query API + cache -> dashboards, anomaly alerts
```

- **Client SDK:** makes event_id (UUIDv7), batches, keeps unsent batches on device, retries.
- **Collector fleet:** stateless; validates, stamps server_ts, tokenises PII, produces to Kafka.
- **Schema registry:** schemas with backward compatibility; invalid events go to quarantine.
- **Kafka:** durable, replayable log; buffers, fans out to Flink, lake and ML.
- **Flink:** dedup, enrichment, windowed aggregates; RocksDB state, checkpoints every 30 s.
- **CDC (Debezium):** order and payment changes, so GMV comes from the source of truth.
- **Real-time OLAP (Pinot):** hybrid tables merging realtime and offline segments.
- **Iceberg lake and Spark:** raw archive, replay and hourly/daily batch correction.
- **Query API:** quotas, timeouts, 5-10 s result cache; heavy queries go to Trino.

**Flow A: event to live dashboard**
1. Shreya adds an item to her cart; the SDK records event_id and client_ts.
2. After 10 s or 50 events the SDK POSTs a gzipped batch; the collector validates and produces to Kafka, then returns 202.
3. Flink drops duplicates, enriches with category and campaign, emits downstream.
4. Pinot ingests the row in 1-2 s; a GMV tile cached 5 s sees it about 5-8 s after the tap.

**Flow B: late event**
1. Sethu's phone was offline in a tunnel and sends events 40 minutes late.
2. Flink puts them in their event-time window and fires an updated result.
3. The aggregate sink upserts by (window_start, dims), correcting the OLAP row; events later than 24 h go to the lake for the nightly rebuild.

## Page 3. The core deep dives

### 1. Event time, watermarks and late data
Mobile events arrive out of order, so windows use event time (client_ts, sanity-checked against server_ts), not arrival time. A watermark is the processor's claim that no older events are expected: max event time seen minus 2 minutes, taken as the minimum across partitions. The window [10:00, 10:01) fires when the watermark passes 10:01, which captures about 99% of events, so first results are nearly final. Late events re-fire the window as upserts; state is kept for 24 h of allowed lateness; anything later goes to a side output that the nightly batch absorbs. An idle partition would freeze the minimum watermark, so partitions idle for 1 minute are excluded.

### 2. Exactly-once in practice
Collectors are at-least-once: an SDK retries after a POST that timed out but succeeded. Dedup on the client's event_id (24 h TTL state, Bloom filter first, about 9.6 bits per id at 1% false positives) makes it effectively-once. Flink checkpoints every 30 s and writes shared topics with transactional two-phase-commit sinks; Pinot reads only committed data. Aggregates are upserts keyed by window and dimensions, so a replay just overwrites. Because committed output appears once per checkpoint, alert-critical metrics use an at-least-once fast path with upserts to stay under 10 s.

### 3. Stream-first, batch-corrected (kappa plus correction)
One logic definition runs in Flink; the lake keeps everything. Spark rebuilds hourly and daily offline segments from Iceberg, which replace realtime segments in Pinot's hybrid tables, and a reconciliation job alerts if stream and batch differ by more than 0.5%. GMV and orders come from CDC on the order database, because client events can be lost, blocked or forged; client events drive the funnel.

### 4. Serving: columnar, pre-aggregated, sketched
Detail rows sit in hourly segments with inverted indexes on city, category and platform. Minute aggregates sit in a small upsert table with a star-tree index (a pre-aggregation index), so war-room tiles never scan detail. Unique users use HyperLogLog sketches: about 12 KB each, under 1% error, merged by register-wise max across minutes and cities.

**Data model:**
- **Raw event:** Kafka key user_token; Iceberg partitioned by day, hour and bucket(64, user_token).
- **Enriched event:** Pinot hybrid table, time column event_ts, hourly segments.
- **Minute aggregate:** primary key (window_start, category_l1, city, platform), upserted.
- **Dedup state:** Flink keyed state by event_id, 24 h TTL.
- **Reconciliation record:** Postgres, PK (date, metric_id).

**Key APIs:**
- `POST /v1/collect`: 202 with accepted and rejected counts; 429/503 with retry_after_ms; max 1 MB.
- `POST /v1/query`: returns rows plus freshness_ts and is_reconciled.
- `PUT /v1/schemas/{event_name}`: 409 on an incompatible change.
- `POST /v1/backfills`: isolated compute; swaps segments atomically.
- `POST /v1/privacy/erasure`: crypto-shreds the token at once; lake deletes within 30 days.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Sale surge:** pre-scale collectors and Flink from the forecast; autoscale on lag; 256 partitions leave room.
- **Hot products:** keying by user_token spreads load; aggregates use two-phase aggregation (combine locally per task, then by dims).
- **Shedding:** sample low-value events (scrolls, impressions) via SDK remote config before touching purchase events.
- **Dedup state:** Bloom pre-filter and TTL keep 200 GB manageable; incremental checkpoints.
- **OLAP:** tiles hit rollups; separate tenants for dashboards and ad-hoc; quotas and timeouts.
- **Backfills:** separate compute writing offline segments, never through realtime ingestion.

**Failure modes:**
- **Flink job fails or a bad deploy:** restart from the last checkpoint; Kafka holds 3 days; lag drains; dashboards show "stale since"; roll back via savepoint.
- **Kafka degraded:** collector buffers fill and return 503 with Retry-After; SDKs keep batches on device; no acknowledged event is lost.
- **Pinot server lost:** segments have 2-3 replicas; consumption resumes from committed offsets.
- **Schema registry down:** cached schemas keep traffic flowing; only new versions are blocked.
- **CDC dimension stream stalls:** enrich with last known values; new products show "unknown" until batch fixes them.
- **Reconciliation gap of 3%:** tiles marked "unreconciled"; compare quarantine, dedup and late counts to find the leak.
- **Collector region outage:** GeoDNS failover; SDKs hold and retry.

**Trade-offs chosen:**
- **Stream-first hybrid over full lambda:** one logic definition avoids drift; batch only corrects.
- **Pinot over ClickHouse for the war room:** native Kafka realtime segments, upserts, star-tree, high QPS; ClickHouse may serve analysts.
- **2PC for shared topics, upserts in OLAP:** no duplicates for many consumers; a fast at-least-once path for alerts.
- **HLL live, exact in batch:** exact uniques per dimension are unaffordable and do not merge.
- **CDC for revenue, client events for funnel:** the order database is the truth.
- **2-minute watermark plus 24 h lateness:** nearly final results without delaying tiles by 10 minutes.
- **Kafka between collectors and OLAP:** buffering, replay and fan-out.

**What to measure:** event-to-queryable p50/p95/p99 from canary events injected every second, consumer lag in seconds, collector accept/reject/503 rates, quarantine rate per producer team, duplicate and late rates, checkpoint duration and backpressure, OLAP p95/p99, stream vs batch delta per metric, cost per billion events.

## Page 5. Say it in the interview

> "I will assume 5 billion events a day, 250 thousand a second at sale peak, 10-second freshness, and exact numbers reconciled from batch by morning. SDKs batch events with a client-generated id to stateless collectors, which validate schemas, tokenise PII and write to Kafka before acking. Flink reads in event time: it dedups on event id, enriches, and computes windowed aggregates with watermarks and allowed lateness, writing exactly-once. Pinot makes them queryable in seconds. Everything also lands in an Iceberg lake for replay and batch correction, and revenue comes from CDC on the order database."

**Key points to land:**
- Collection, log, stream processing, serving and lake each scale and fail independently.
- Client event_id, dedup in the stream, upserts in sinks.
- Event-time windows with watermarks; late data via upserts and batch correction.
- Real-time OLAP for fresh, sub-second queries; the lake for history and replay.
- One logic definition, stream-first, batch-corrected into hybrid tables.
- CDC for revenue, client events for funnels.
- HLL and t-digest sketches live; exact numbers in batch.
- Prove freshness with canaries; publish the stream vs batch delta.
- Govern schemas with a registry and quarantine.

**Likely follow-ups:**
1. **How do you prove completeness?** Canaries end to end, counts reconciled per hop, and daily stream vs batch against CDC orders.
2. **Orders drop 40% in one city: real or pipeline?** Check lag and canaries, then compare client order events with CDC: CDC normal means instrumentation; CDC down means a real incident.
3. **Reprocess 30 days with a new definition?** Same logic in batch over Iceberg, a new table version, reconcile, swap atomically.
4. **DPDP deletion when Kafka is immutable?** Delete the token key (crypto-shredding); Kafka ages out in 3 days; Iceberg row deletes; OLAP rebuilt.
5. **Why not write straight into Pinot?** It ties ingest availability to the OLAP store and loses replay and fan-out.

**Director layer:**
- **Cost drivers:** streaming compute for 250k events/s, 30 TB OLAP detail, 300 TB lake; rollups and tiering cut cost.
- **Phasing:** collectors, Kafka, Flink and GMV tiles first; then CDC revenue, reconciliation, alerts, backfills.
- **Ownership:** SDK and collectors, streaming platform, OLAP and query API, lake; producers own schemas.
- **Top risks:** schema drift, numbers disagreeing with finance, freshness collapse at peak, runaway queries.
