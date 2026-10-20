# Job Queue (background task processing): recall card

> **Hook:** Enqueue to Kafka → Relay moves due jobs to Redis → Worker leases with timeout → Heartbeat and ack → Retry with jitter → DLQ

**P · Problem:** It's really at-least-once work distribution with leases, where handlers must be idempotent.

**N · Numbers:**
1. 15k jobs/s planned peak is past Postgres SKIP LOCKED at about 2k/s, so we need a real broker.
2. By Little's law, 15k/s x 0.5 s = 7,500 concurrent slots, so about 150 worker pods.
3. Five minutes of backlog is about 11 GB, so Redis holds only a bounded hot window and Kafka holds the backlog.

**H · Hard part:** Never losing or double-running a job when workers crash or pause, while one noisy queue cannot starve the rest.

**B · Boxes:** `Producer → Enqueue API → Kafka → Relay → Redis ready sets → Worker pools`

Side path: `Reaper and Retry → delay set or DLQ` with a redrive console.

**D · Decisions:**
1. At-least-once plus idempotency over exactly-once, because exactly-once across external side effects is not achievable.
2. Kafka plus Redis over one broker, because we get durable replay and per-job leases together.
3. Pull with long polling over push, because workers take only what they can process.

**F · Failures:**
1. Worker crashes mid-job → the lease expires within 30 s and the job is retried; idempotency absorbs partial effects.
2. Redis primary fails → a replica is promoted in 10-20 s and the Relay replays Kafka; duplicates possible, no loss.

**C · Close:** "I start with Postgres and SKIP LOCKED and show where it breaks. The scaled design writes jobs to Kafka with acks all as the durable buffer, and a relay moves due jobs into Redis sorted sets. Workers lease with a 30-second timeout, heartbeat and ack. Failures retry with jittered backoff and land in a dead letter queue after five attempts. Every queue has limits, and I alert on the age of the oldest ready job."

**Quiz yourself:**
1. A zombie worker wakes and acks? → Its lease token is stale, so it gets 409.
2. Why not Kafka consumer groups alone? → One slow job blocks its partition, and there is no per-job retry or delay.
3. What is the SLO signal? → Age of the oldest ready job.
