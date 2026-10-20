# Fanout for a follower graph: recall card

> **Hook:** Outbox with the post → CDC to Kafka → Tier the author → Push batches of 1,000 → Pull celebrities and merge at read

**P · Problem:** It's really a write-amplification problem on a power-law graph, where one post can mean ten writes or fifty million.

**N · Numbers:**
1. About 200 effective push followers per post is 1.2M inserts/s, 3.5M/s peak, so celebrities must be pulled, not pushed.
2. 300M inboxes x 500 x 16 B is about 7 TB in Redis, so memory, not CPU, sizes the fleet, hence the 500 cap.
3. 200k feed reads/s at peak, so a read must be one sorted-set range plus a few cached outboxes.

**H · Hard part:** Bounding the worst-case cost of one post when the follower tail reaches 100M, without ever losing a post.

**B · Boxes:** `Post service → Outbox and CDC → Kafka → Fanout planner → Fanout workers → Redis inbox`

Side path: `Feed read service → inbox plus celebrity outboxes → merge` at read time.

**D · Decisions:**
1. Hybrid push/pull over pure push or pull, because push keeps reads cheap and pull caps worst-case writes.
2. Key batches by batch_id over author_id, because a big author spreads over many partitions.
3. Skip followers inactive 30+ days over pushing anyway, because most of those writes are never read.

**F · Failures:**
1. CDC relay down → posts still commit; fanout pauses and catches up in order.
2. Redis shard lost → replica promoted; the watermark marks gaps and reads pull to fill them.

**C · Close:** "So the naive loop over followers breaks on a celebrity post. I capture posts with a transactional outbox and CDC into Kafka. A planner tiers each author: normal authors are pushed, large ones in batches of a thousand on a lower-priority lane, and celebrities are not pushed; readers pull their recent posts and merge. Workers do idempotent ZADDs into capped Redis sorted sets, so retries are harmless. Tiering bounds write amplification."

**Quiz yourself:**
1. What are the tiers? → Under 10k pushed, 10k to 1M batched on a low lane, over 1M pulled.
2. Why does at-least-once not cause duplicates? → ZADD by post_id is idempotent.
3. How is unfollow immediate? → A read-time filter hides it now; an async purge cleans the inbox.
