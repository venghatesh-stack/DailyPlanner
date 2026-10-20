# Ad click event aggregation system: recall card

> **Hook:** Redirect logs click → Kafka by ad → Flink dedups → 1-min event-time windows → Upsert by window_id → Batch bills

**P · Problem:** It's really an exactly-once streaming count where every click is money.

**N · Numbers:**
1. 10B clicks/day peaking near 1M/s, so a database counter per click is out and we stream it.
2. 2 TB raw/day, 400 GB as Parquet, so archive it cheaply in S3 and keep it for replay.
3. 200 GB of 24 h click_id dedup state, so it lives in RocksDB-backed Flink state, not the heap.

**H · Hard part:** Counting each valid click exactly once despite retries, replays and late events, while hot ads skew one key.

**B · Boxes:** `Click redirect → Kafka raw-clicks → Flink → Kafka aggregates → Pinot → Query service`

Side path: `Kafka → Archiver → S3 Parquet → Spark daily recompute` for billing.

**D · Decisions:**
1. Exact dedup over Bloom filters, because 200 GB of state is affordable and a dropped billable click is not.
2. Batch as billing truth over stream only, because it has final fraud labels and very late data.
3. Correctness over freshness, because 60 s checkpoints still meet the 1-2 minute target.

**F · Failures:**
1. Flink TaskManager dies → restart from the last checkpoint, replay offsets, abort open transactions; no double counting.
2. Whole Kafka down → redirects still succeed; events spool to local disk and replay later.

**C · Close:** "So this is a pipeline that turns raw clicks into per-ad, per-minute counts. The redirect logs to Kafka and never fails the user. Flink dedups by click id, filters invalid traffic and counts in one-minute event-time windows, writing transactionally with deterministic window ids so Pinot upserts idempotently. A daily Spark job recomputes from the archive as the billing record, and we alert if the two drift over 0.1%."

**Quiz yourself:**
1. Why not increment a Redis counter per click? → Hot rows contend, there is no dedup or event time, and a retry double counts.
2. What makes it exactly-once? → Replayable Kafka source, checkpointed state and a transactional sink read with read_committed.
3. How do you handle a viral ad? → Flag heavy hitters, salt into 16 sub-keys, then merge in two stages.
