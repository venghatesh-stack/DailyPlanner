# Design an ad click event aggregation system: the 5-page summary

Ad click aggregation turns billions of raw clicks into per-ad, per-minute counts that drive billing, budget pacing and dashboards. The single most important idea: clicks are money, so build a Kafka plus Flink pipeline that is exactly-once in effect (dedup, event-time windows, transactional sinks, idempotent upserts), and keep a raw archive so a daily batch job can recompute the authoritative billing numbers.

## Page 1. The problem, scope and numbers

**Pitch:** count every valid ad click once, within 1-2 minutes, so budgets stop on time and advertisers are billed exactly what they owe.

**Who uses it:** advertisers (trustworthy reports, no paying for fraud), the pacing service (spend per campaign every minute), finance (final daily numbers that survive audits), the fraud team (raw events and labels) and SRE (bounded lag, cost control).

**In scope:**
- **Click capture:** the redirect assigns a unique click_id, logs to Kafka and returns a 302.
- **Clean:** validate, enrich, dedup and filter invalid traffic (IVT: bots, click farms, rapid repeat clicks).
- **Aggregate:** clicks and spend per (ad_id, minute) and per dimension; top-N ads per minute.
- **Serve:** a query API for dashboards and spend deltas for the budget service.
- **Correct:** late events within allowed lateness; a daily batch recompute and reconciliation for billing.

**Out of scope:** the ad auction and serving, conversion attribution, invoicing and payment collection, advertiser UI design.

**Non-functional targets:**
- **Freshness:** p95 under 2 minutes from click to queryable aggregate.
- **Latency:** redirect p99 under 50 ms; dashboard queries p99 under 1 s for 24 h of minute data.
- **Availability:** ingest 99.99% (a click must never fail the redirect); query 99.9%.
- **Correctness:** exactly-once effect; dedup window 24 h by click_id; real-time vs batch discrepancy under 0.1% per ad per day.
- **Durability:** zero loss after Kafka ack (RF=3, min.insync.replicas=2, acks=all); raw archive 11 nines.

**Capacity math (10B clicks/day, peak 8-10x average):**
- **Ingest rate:** 1e10 / 86,400 = about 116k events/s; peak about 1M/s. So a database counter per click is out; stream it.
- **Bandwidth:** 1M x 200 B = 200 MB/s; with RF=3, 600 MB/s of Kafka writes. At 5-10 MB/s per partition about 40 are needed; choose 512 for parallelism and skew headroom.
- **Raw storage:** 1e10 x 200 B = 2 TB/day; Parquet at about 5x gives 400 GB/day, 146 TB/year. So archive cheaply in object storage and keep it for replay.
- **Aggregates:** 2M ads x 30% active = 600k rows/min; with dimensions about 3M rows/min x 100 B = 430 GB/day before compression. Aggregation shrinks data about 100x, so an OLAP store can serve it.
- **Dedup state:** 24 h of click_ids = 1e10 x 20 B = about 200 GB. So keep it in RocksDB-backed Flink state, not the heap.

## Page 2. The architecture

```
 User click -> Click redirect (assign click_id, 302) -> Landing page
                   | produce acks=all (spool to disk if Kafka down)
                   v
 Kafka raw-clicks (512 partitions by ad_id) --> Archiver -> S3 Parquet
                   |                                        | daily
                   v                                        v
 Flink: validate -> enrich -> dedup -> IVT ->       Spark recompute +
        salted pre-agg -> 1-min event-time window   reconciliation
        (RocksDB, checkpoint 60 s)                          |
         | txn write          | late side output            v
         v                    +-> corrections topic   Billing tables
 Kafka aggregates topic (read_committed)
         |                    |
         v                    v
 Pinot (upsert on window_id)  Budget pacing service -> ad server
         +--> Query service + 15 s cache -> dashboards
```

- **Click redirect:** stateless edge; verifies the signed context, assigns click_id, logs, returns 302.
- **Kafka raw-clicks:** durable buffer keyed by ad_id, 7-day retention; the replay source.
- **Raw archiver:** writes Parquet to S3 by event hour for batch and audits.
- **Flink job:** validation, enrichment, dedup, IVT, event-time windows, exactly-once output.
- **Ad metadata service:** ad to campaign, advertiser, CPC price; broadcast into Flink.
- **IVT filter:** rate rules, bot lists and model scores; labels clicks rather than dropping them.
- **Pinot (OLAP):** upserts minute rows, fast group-by, slicing and top-N.
- **Budget pacing:** tracks campaign spend and throttles or stops delivery.
- **Spark batch:** daily recompute from raw; the billing source of record.

**Flow A: click to dashboard**
1. Redirect assigns click_id, produces keyed by ad_id (p99 under 10 ms), returns 302.
2. Flink sets watermark = max event time seen - 30 s per partition.
3. Validate, enrich, check click_id in dedup state, apply IVT rules.
4. Pre-aggregate on (ad_id, salt, minute), merge per (ad_id, minute).
5. When the watermark passes the window end, emit the row transactionally; it commits at the next checkpoint.
6. Pinot upserts by window_id; the minute is visible 1-2 minutes after it closes.

**Flow B: daily billing**
1. After the day closes plus 24 h grace, Spark reads the raw Parquet.
2. Dedup by click_id, join final IVT labels, aggregate per advertiser and ad.
3. Compare with real time; over 0.1% for a large advertiser, alert and hold invoicing.

## Page 3. The core deep dives

### 1. Event time, watermarks and late clicks
Windows use when the click happened, not when it arrived, so numbers do not depend on lag. The watermark is Flink's estimate that no earlier events will come; it lags the max event time by 30 s. Example: a mobile SDK flushes clicks from 7 minutes ago. Allowed lateness is 10 minutes, so the window fires again with the same window_id and Pinot overwrites the row. A click 3 hours late goes to a side output; the hourly correction job and daily batch include it. An idle partition has a 1-minute idleness timeout so it cannot stall all windows, and timestamps more than 5 minutes in the future are clamped to ingest time so they cannot push the watermark ahead.

### 2. Exactly-once as an effect
Three parts: a replayable source (Kafka offsets), a consistent state snapshot (checkpoint every 60 s to S3) and a transactional sink. If Flink crashes after emitting a window but before the checkpoint, the output sits in an uncommitted Kafka transaction that read_committed consumers never see; on restore Flink replays and re-emits. Beyond Kafka, every row carries window_id = hash(ad_id, minute, country, device) plus a version, so Pinot upserts and the budget service replaces that window's contribution (last_window_applied) instead of adding twice.

### 3. Dedup and invalid traffic
Technical dedup: the same click_id twice (a producer retry) is caught by Kafka idempotent producers and by Flink keyed state with a 24 h TTL. Exact state is chosen over Bloom filters because a false positive drops a billable click. Policy dedup is separate: Shreya double-clicks an ad within 1 second, two click_ids, one charge by an IVT rule. Click farms are caught by IP, device and ASN rate rules plus model scores, and batch re-labelling credits advertisers.

### 4. Hot ads and skew
A viral ad can send 100k clicks/s to one key and one Flink subtask. A count-min sketch flags heavy hitters each minute; those are salted into 16 sub-keys for a first partial count, then merged, so the final merge handles only 16 partials per window.

**Data model:**
- **Raw click** (Kafka Avro, S3 Parquet): click_id, ad_id, event_ts, ingest_ts, hashed IP and device; Kafka key ad_id, S3 by dt/hour.
- **Minute aggregate** (Pinot): PK window_id; clicks, invalid_clicks, spend_micros; partitioned by ad_id.
- **Dedup state** (Flink RocksDB): click_id -> first_seen_ts, TTL 24 h.
- **Campaign spend** (Redis + DB): PK (campaign_id, date), last_window_applied.
- **Billing daily** (warehouse): PK (date, ad_id); immutable after invoicing except credits.

**Key APIs:**
- `GET /c?ad={adId}&ctx={signed}`: 302 to the landing URL; never blocks on downstream.
- `GET /v1/ads/{adId}/clicks`: time range, granularity, filters; from Pinot, cached 15 s.
- `GET /v1/top-ads?window=1m&n=100`: precomputed top-N or a Pinot group-by.
- `GET /v1/campaigns/{id}/spend`: realtimeSpend, and finalSpend after reconciliation.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot keys:** local pre-aggregation before the shuffle plus salting and a two-stage merge.
- **Ingest:** add Kafka partitions and Flink parallelism; the redirect stays stateless.
- **Dedup state:** grows with volume; RocksDB with incremental checkpoints; for impressions (100x clicks), shorter TTLs or Bloom filters where exactness matters less.
- **Reads:** pre-aggregated minute rows, star-tree indexes on (advertiser_id, ad_id, minute_ts), hourly and daily rollups, 15 s query cache.

**Failure modes:**
- **Flink TaskManager dies:** restart from the last checkpoint (about 60 s old), replay offsets, abort open transactions; freshness dips, no double counting.
- **Kafka broker lost:** RF=3, min ISR 2 keep partitions writable; producers retry idempotently.
- **Whole Kafka down:** redirects still succeed; events spool to local disk and replay later.
- **Pinot ingestion lag:** dashboards show a freshness banner; budget pacing reads Kafka directly and is unaffected.
- **Checkpoints keep failing:** output stalls because transactions do not commit; alert after 3 failures, scale state, use unaligned checkpoints.
- **Bad aggregation logic shipped:** reconciliation catches it; roll back, replay from the archive into a new table version, swap.
- **Region outage:** per-region pipelines; clicks route to the healthy region; batch stays correct.

**Trade-offs chosen:**
- **Flink over micro-batch engines:** true event time, large RocksDB state, exactly-once Kafka sinks.
- **Correctness over freshness:** 60 s checkpoints bound freshness, but 1-2 minutes meets the target.
- **Exact dedup over Bloom filters:** 200 GB of state is affordable; dropped billable clicks are not.
- **Batch as billing truth over stream only:** it has final fraud labels and very late data, and is an independent audit trail.
- **1-minute tumbling windows:** match pacing and dashboards; smaller windows multiply rows and transactions.
- **Pinot over Druid or ClickHouse:** stronger upsert semantics on window_id.

**What to measure:** end-to-end freshness, Kafka lag per partition (skew), checkpoint duration and failures, backpressure, late event rate, dedup hit rate, IVT rate by rule, real-time vs batch discrepancy, budget overspend, redirect p99 and spool size.

## Page 5. Say it in the interview

> "I will treat this as the pipeline that turns raw ad clicks into per-ad, per-minute counts for billing, budget pacing and dashboards. Assume ten billion clicks a day, peaking near a million a second, and two million active ads. Freshness should be a minute or two, but because this is money there is no double counting and no loss. Clicks hit a redirect that logs to Kafka by ad and never fails the user. Kafka is archived to object storage. A Flink job dedups by click id, filters invalid traffic and counts in one-minute event-time windows with watermarks, writing transactionally with deterministic ids so the OLAP store upserts idempotently. The budget service consumes spend deltas, and a daily batch recomputes from the archive as the billing record."

**Key points to land:**
- Clicks are money: correctness first, freshness of 1-2 minutes second.
- Kafka with RF=3, acks=all, idempotent producers; the raw archive enables replay and audits.
- Event-time 1-minute windows, a 30 s watermark, 10 minutes of allowed lateness, side outputs.
- Exactly-once = replayable source + checkpointed state + transactional sink, read_committed.
- Deterministic window IDs and upserts make every downstream hop idempotent.
- Dedup by click_id in RocksDB (24 h, about 200 GB); IVT rules handle double clicks and bots.
- Hot ads: local combine, salt, two-stage merge.
- Daily batch is the billing source of truth; reconcile and alert on drift over 0.1%.
- 10B/day, 1M/s peak, 2 TB raw/day; aggregation shrinks it about 100x.

**Likely follow-ups:**
1. **Why not increment a counter per click in Redis?** 1M increments/s on hot rows contend, there is no dedup or event time, and a retry double counts.
2. **How do you choose allowed lateness?** From the delay distribution: if 99.9% arrive within 10 minutes, set 10; batch corrects the rest.
3. **Top 100 ads in the last 5 minutes?** A sliding top-N in Flink every minute, or a Pinot group-by over 5 minute rows with a limit, cheap on pre-aggregated data.
4. **An advertiser disputes the bill?** Raw events are kept 1-2 years; recompute their campaign from the archive and show the IVT labels.
5. **Count impressions too (100x clicks)?** Same pipeline with more partitions; dedup state becomes the main cost, so use shorter TTLs or Bloom filters there.

**Director layer:**
- **Cost drivers:** 600 MB/s of replicated Kafka writes, 200 GB of dedup state, 146 TB/year of raw archive, OLAP storage for minute rows.
- **Phasing:** start with a single Flink job and the batch billing path; add salting, IVT models and per-region pipelines as volume grows.
- **Team ownership:** edge and ingest, stream processing, ad quality and fraud, OLAP and query, finance data.
- **Top risks:** double counting after replay, click fraud inflating bills, hot ads overloading a partition, silent drift between real-time and billing numbers.
