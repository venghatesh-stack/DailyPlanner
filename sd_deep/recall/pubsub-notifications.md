# Pub-Sub System for Event Notifications: recall card

> **Hook:** Publish once → Append to replicated log → Cursor per subscription → Ack out of order → Retry, then dead-letter

**P · Problem:** It's really a durable fan-out problem where each subscription is its own independent work queue over one shared log.

**N · Numbers:**
1. 2B events/day peaks at about 115k publishes/s, so topics must be partitioned.
2. 115k/s x 4 subscriptions = 460k deliveries/s, about 1 GB/s egress, so never copy events per subscription.
3. 2 TB/day x 3 replicas x 7 days = 42 TB, so keep 24 h on SSD and tier the rest to object storage.

**H · Hard part:** Delivering at least once to thousands of subscribers without one slow or dead subscriber slowing the publisher or anyone else.

**B · Boxes:** `Publisher → Publish Front-end → Topic Log → Subscription Dispatcher → Ack Tracker → Subscriber`

Side path: `Dispatcher → Push Workers → Webhooks`, with a dead-letter topic per subscription.

**D · Decisions:**
1. Shared log over per-subscription copies, because publish cost stays flat as fan-out grows and replay is free.
2. Per-message acks over consumer offsets, because one slow message must not block the partition.
3. Per-key ordering over global order, because global order caps throughput at one partition.

**F · Failures:**
1. Dispatcher dies → its lease expires in about 10 s; the new owner reloads the checkpoint and redelivers, so duplicates but no gaps.
2. Webhook endpoint down for hours → breaker opens, backlog is just a cursor gap, dead-letter after 24 h, seller replays.

**C · Close:** "I store each event once in a partitioned log with three replicas and ack the publisher after two. Each subscription keeps only a cursor and acked ranges, so acks can arrive out of order without head-of-line blocking. Pull consumers lease messages with a deadline; push workers give every endpoint its own queue, backoff and breaker, and dead-letter after five attempts. The log is the buffer under overload, and I watch oldest unacked age per subscription."

**Quiz yourself:**
1. Can you give exactly-once to subscribers? → No; dedupe publishes and have subscribers dedupe by message_id.
2. How do the order write and the publish both happen? → Transactional outbox, then a relay or CDC publishes.
3. What is the key health signal? → Oldest unacked message age per subscription.
