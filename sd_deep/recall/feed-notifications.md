# Notifications for a feed action (like, comment, follow, mention): recall card

> **Hook:** Outbox with the like → Kafka by recipient → Dedupe and filter → Aggregate into one group → Rate-limit, then push

**P · Problem:** It's really an idempotent event pipeline whose real enemy is spam, not throughput.

**N · Numbers:**
1. About 23K candidates/s, 93K/s at peak, so the pipeline must be asynchronous and partitioned.
2. Aggregation collapses 4x to 700M rows/day, about 100K writes/s at peak, so use a write-optimised store (Cassandra).
3. Badge checks reach 200K/s, so the badge lives in Redis, never Cassandra.

**H · Hard part:** Telling users once and quickly without spamming them, even when a celebrity post gets thousands of likes a second.

**B · Boxes:** `Feed service → Outbox and CDC → Kafka → Notification Processor → Delivery Router → APNs/FCM senders`

Side path: `Processor → Cassandra inbox and Redis badge → Read API` for the in-app inbox.

**D · Decisions:**
1. Aggregate in the processor over at read, because read-time grouping cannot reduce pushes.
2. Priority lanes over one topic, because a like storm must not delay mentions.
3. Expire stale pushes over delivering late, because a burst of late pushes is spam and the inbox keeps the information.

**F · Failures:**
1. APNs outage for 40 minutes → its breaker opens and its queue buffers; stale like-pushes expire on recovery.
2. Consumer lag above 60 s → like-pushes shed to in-app only; the high lane is unaffected.

**C · Close:** "So this is an event pipeline. The feed writes an outbox row in the same transaction, and CDC puts it on Kafka keyed by recipient. Stateless processors dedupe, apply blocks and preferences, and aggregate by recipient, post and type, so forty likes become one updating notification. They upsert a Cassandra inbox, bump a Redis badge, and hand jobs to a router that applies quiet hours and rate limits. Next I would add ML ranking."

**Quiz yourself:**
1. Why an outbox? → The like and the event commit together, so a notification outage never fails a like.
2. How do you get effectively-once? → At-least-once plus idempotency keys plus push collapse ids.
3. Is a rate-limited push lost? → No, it stays in the in-app inbox.
