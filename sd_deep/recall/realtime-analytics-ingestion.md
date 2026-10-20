# Real-time analytics ingestion pipeline: recall card

> **Hook:** SDK batches with event_id → Collector writes Kafka → Flink dedups in event time → Pinot serves in seconds → Lake corrects by morning

**P · Problem:** It's really a streaming aggregation problem where freshness and correctness pull in opposite directions.

**N · Numbers:**
1. 5B events/day peaks at about 250k/s, so collectors stay stateless and batch.
2. 1.5 TB/day x 3 replicas x 3 days = 13.5 TB, so Kafka is kept short and the lake keeps 13 months.
3. 5B event ids x 40 B = 200 GB of dedup state, so use a Bloom filter first and a 24 h TTL.

**H · Hard part:** Making numbers queryable within 10 seconds while events arrive late, duplicated and out of order.

**B · Boxes:** `SDK → Collector → Kafka → Flink → Pinot → Query API`

Side path: `Kafka → Iceberg lake → Spark batch → offline segments in Pinot`.

**D · Decisions:**
1. Stream-first hybrid over full lambda, because one logic definition avoids drift and batch only corrects.
2. CDC for revenue over client events, because client events can be lost, blocked or forged.
3. HLL sketches live over exact uniques, because exact uniques per dimension are unaffordable and do not merge.

**F · Failures:**
1. Flink job fails → restart from the last checkpoint; Kafka holds 3 days; dashboards show "stale since".
2. Kafka degraded → collectors return 503 with Retry-After; SDKs keep batches on device; no accepted event is lost.

**C · Close:** "SDKs batch events with a client-generated id to stateless collectors, which validate schemas, tokenise PII and write to Kafka before acking. Flink works in event time: it dedups on event id, enriches, and computes windowed aggregates with watermarks and allowed lateness. Pinot makes them queryable in seconds. Everything also lands in an Iceberg lake for replay and batch correction, and revenue comes from CDC on the order database."

**Quiz yourself:**
1. What is a watermark? → The claim that no older events are expected: max event time seen minus 2 minutes.
2. What happens to an event 40 minutes late? → Its window re-fires and the aggregate is upserted.
3. Why not write straight into Pinot? → You lose buffering, replay and fan-out.
