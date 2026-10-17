# Design fanout for a follower graph: the 5-page summary

When an account posts, every follower should see it quickly, but follower counts follow a power law, so one post can mean ten deliveries or fifty million. The single most important idea: bound write amplification by tiering authors (push for normal authors, batched low-priority push for large ones, pull at read time for celebrities), on top of reliable capture with an outbox and idempotent delivery so retries are safe.

## Page 1. The problem, scope and numbers

**Pitch:** deliver each new post into followers' home inboxes within seconds, never lose one, and keep cost tied to what is actually read.

**Who uses it:** readers (fresh, fast feed), celebrity authors (reach everyone in a live moment), returning dormant users (a correct feed anyway), the ranking team, SRE, trust and safety.

**In scope:**
- **Publish** reliably and **deliver** post ids to inboxes by author tier policy; merge pulled celebrity posts at read time.
- **Filter** unfollowed, blocked, muted and deleted posts at read time.
- **Bound inboxes** to 500 entries; rebuild stale ones on demand; replay events by time range.

**Out of scope:** feed ranking, ads and recommendations, push notifications, search indexing, media upload, follow suggestions.

**Non-functional targets:**
- **Freshness:** p99 under 5 s for followers active in the last 24 h; under 60 s for those active 1-30 days.
- **Read latency:** feed p99 under 100 ms, usually one cache lookup.
- **Durability:** posts RF 3; zero loss of fanout intent via the outbox; inboxes are rebuildable caches.
- **Availability and consistency:** 99.95% reads, posts accepted even if fanout lags; eventual for followers, read-your-writes for the author.
- **Throughput:** 4M inbox inserts/s sustained at peak; high-priority lag under 30 s in peak events.

**Capacity math (300M DAU, 500M posts/day, median 100 followers, peak 3x):**
- **Posts:** 500M / 86,400 = 5.8k/s, 17k/s peak; the cost is in multiplying them.
- **Inserts:** about 200 effective push followers per post (after skipping inactive users and celebrities) = 100B/day, 1.2M/s, 3.5M/s peak. Without tiering the tail (top accounts at 100M followers) makes it trillions, so celebrities are pulled.
- **Inbox memory:** 300M x 500 x 16 B = 2.4 TB raw, about 7 TB with Redis overhead, 14 TB with a replica. So memory, not CPU, sizes the fleet: about 40 primaries for writes, but about 200 nodes of 64 GB for memory; hence the 500 cap.
- **Graph reads:** 100B follower ids/day in pages of 1,000 = 1.2k page reads/s. So page with cursors, never one giant scan.
- **Feed reads:** 300M x 20 opens = 6B/day, 70k/s, 200k/s peak. So reads must be one sorted-set range plus a few cached outboxes.

## Page 2. The architecture

```
 Author -> Post svc --(tx: post row + outbox row)--> Post DB (Vitess)
                                                        | CDC (Debezium)
                                                        v
                             Kafka post-events (key author_id, 256 parts)
                                                        v
 Graph store (Cassandra) <--- pages of 1,000 ---- Fanout planner
 followers by (author, bucket)                   tier: normal/large/celeb
                                          batches |             | celeb only
                                                  v             v
                     Kafka fanout-hi / fanout-lo (by batch_id)  Author outbox
                                                  v             (recent 100)
                     Fanout workers: pipelined ZADD + trim 500      |
                                                  v                 | pull
 Reader -> Feed read svc --------------> Redis inbox:{user} <-------+ merge
```

- **Post service:** persists post and outbox row in one transaction; idempotent on a client key.
- **CDC relay:** tails the binlog; publishes outbox rows in commit order.
- **Fanout planner:** tiers the author, pages followers, routes 1,000-id batches by activity.
- **Fanout workers:** stateless; idempotent pipelined ZADD and trim; retries, then a DLQ.
- **Graph store:** edges both directions; follower lists bucketed at 100k rows.
- **Inbox store:** Redis sorted set per user, capped at 500, with a completeness watermark.
- **Author outbox:** latest 100 posts per celebrity; tiny, hot, heavily cached.
- **Feed read service:** merges inbox and outboxes, filters, paginates, triggers rebuilds.
- **Rebuild service:** rebuilds an inbox by pulling followees' recent posts; single-flight per user.

**Flow A: a normal author posts**
1. Sethu posts; the post and outbox row commit together; CDC publishes to post-events.
2. Planner sees 2,300 followers: normal tier, 3 batches; active-24h followers go to fanout-hi, 1-30 days to fanout-lo, over 30 days skipped.
3. Workers ZADD inbox:{f} with score ts and trim to 500, then commit offsets.

**Flow B: a reader opens the feed**
1. Shreya's feed reads inbox:{Shreya} top 50, plus top 20 from each followed celebrity's outbox (1 s in-process cache).
2. K-way merge, dedupe by post_id, filter against her followee set, blocks and tombstones.
3. Missing inbox or stale watermark: trigger a rebuild and serve pulled results meanwhile; return 20 with cursor (ts, post_id).

## Page 3. The core deep dives

### 1. The fanout cost model and author tiers
Fanout work is the sum of the follower counts of everyone who posts, and the power-law tail dominates. Push wins on average because reads outnumber writes, but not in the worst case, so bound the worst case per post. Tiers: normal (under 10k followers) pushed; large (10k to 1M) pushed in batches on a lower-priority lane; celebrity (over 1M, about 50k accounts) not pushed at all. Inactive followers (no session in 30 days) are skipped. This caps one post at about 1M batched inserts and keeps the day near 100B inserts. Hysteresis stops flapping: enter the celebrity tier at 1M, leave at 800k; during a switch readers merge both sources and dedupe.

### 2. Hybrid push and pull with a read-time merge
Feed = pushed inbox plus the outboxes of pulled authors. Each user has a cached list of followed celebrities, refreshed on follow and unfollow. The read takes the inbox range up to the cursor and each celebrity outbox, merges with a min-heap, dedupes by post_id and returns 20 with a composite (ts, post_id) cursor for stable paging. Keep pulled authors per reader to tens (merge capped at 100). A hot outbox read by millions a second sits in an in-process cache for 1 s with request coalescing and many replicas.

### 3. Batching, priority lanes and backpressure
The planner pages followers 1,000 at a time and emits one message per page, keyed by batch_id over 512 partitions so one big author spreads out; order is restored by the timestamp score. Workers group ids by Redis slot and send one pipeline per node. Example: an 800k-follower post finishes in about 2-4 s with 200 workers (wall time is followers / (batch x parallelism)). Under a 10x spike, lag sits safely on disk; if the hi lane lags over 60 s, capacity moves from lo to hi. Shed only work that can be rebuilt: degraded means slower for inactive users, never lost.

### 4. Outbox, idempotency and follow changes
The post and outbox row share one transaction on the author's shard, so the event exists if and only if the row committed. Delivery is at-least-once, so ZADD by post_id makes duplicates harmless; the planner also dedupes event_id for 1 h to avoid re-paging huge lists. Unread counts are ZCOUNT since last read, never blind increments. A new follow backfills the author's last 20 posts; an unfollow is hidden by the read filter at once, with an async purge.

**Data model:**
- **Post + Outbox** (MySQL on Vitess): PK post_id, shard key author_id, so the outbox is a same-shard transaction.
- **Followers edge** (Cassandra): partition (author_id, bucket of 100k), clustering follower_id; reverse table followees.
- **Inbox** (Redis sorted set): inbox:{user_id}, member post_id, score created_at_ms, cap 500; watermark wm:{user_id}.
- **Author outbox** (replicated Redis sorted set): outbox:{author_id}, celebrities only, cap 100.
- **FollowerCount / Tier** (Redis plus Cassandra counters): recomputed hourly with hysteresis.

**Key APIs:**
- `POST /v1/posts`: idempotency key; returns after the DB commit, fanout is async.
- `GET /v1/feed?cursor=(ts,post_id)&limit=20`: merges inbox and pulled outboxes.
- `POST /v1/follow`: writes the edge, updates caches, backfills the last 20 posts.
- `DELETE /v1/follow/{id}`: read-time filter now, background inbox purge.
- `POST /internal/fanout/replay`: replay by time range or authors; idempotent.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Write amplification:** tighten tier thresholds; pick the celebrity cut where push breaches the 5 s SLO at peak.
- **Inbox memory:** the 500 cap and skipping inactive users; rebuild on demand instead of storing everything.
- **Hot celebrity outboxes:** 1 s local cache, coalescing, read replicas.
- **Graph scans:** buckets of 100k and cursor paging; counts kept separately and approximately.
- **Spam fanout storms:** per-account limits (for example 300 posts per 3 hours) and reputation-based fanout caps.

**Failure modes:**
- **CDC relay down:** posts still commit; fanout pauses; outbox-age alert; catches up in order.
- **Kafka broker lost:** RF 3, min.insync 2 keeps writes up; leaders re-elect in seconds.
- **Redis shard lost:** replica promoted; the watermark marks gaps and reads pull to fill them.
- **Graph store slow:** planner backs off with jitter; lag grows on disk; hi lane first on recovery.
- **Worker bug writes wrong ids:** stop, fix, replay from an offset; idempotent ZADD makes replay safe.
- **Poison batch:** 5 retries with full jitter, then DLQ and alert; offsets keep moving.
- **Clock skew:** server-side snowflake ids give timestamps, clamped to now.

**Trade-offs chosen:**
- **Hybrid push/pull over pure push or pull:** push keeps reads cheap; pull caps worst-case writes.
- **Outbox with CDC over dual write or polling:** no loss, low latency, low DB load.
- **Key batches by batch_id over author_id:** a big author spreads over many partitions.
- **Capped Redis sorted set over a list or DB table:** idempotent inserts, ordered reads, bounded memory. Cassandra is cheaper per GB, but read latency and tombstone-heavy trimming hurt.
- **Skip followers inactive 30+ days and rebuild lazily over pushing anyway:** most of those writes are never read.
- **Read filter plus async purge over synchronous purge:** correct at once without a big write.

**What to measure:** post-to-inbox latency p50/p99 by tier and lane; consumer lag per topic; oldest outbox row age; inbox inserts/s and Redis memory per node; DLQ and retry rates; rebuild rate and latency; feed p99 and outbox cache hit ratio; and a reconciliation sample of followers missing a recent post (target 0 lost).

## Page 5. Say it in the interview

> "I will scope this as delivering new posts into followers' home inboxes for about 300 million daily users, with active followers seeing a post within 5 seconds and nothing ever lost. The naive design loops over followers on post, which breaks at once because followers follow a power law: one celebrity post is 50 million writes. So first I capture posts reliably with a transactional outbox and CDC into Kafka. A planner tiers each author: normal authors are pushed, large authors are pushed in batches of a thousand on a lower-priority lane, and celebrities are not pushed at all; readers pull their recent posts and merge at read time. Workers do idempotent ZADDs into capped Redis sorted sets, so retries are harmless. Write amplification is the bottleneck, and tiering bounds it."

**Key points to land:**
- Fanout cost is the sum of follower counts; the power-law tail dominates.
- Transactional outbox plus CDC so no post is lost.
- Tier authors: push normal, batch large, pull celebrities, with hysteresis.
- Batches of 1,000 ids keyed by batch_id to spread load.
- Idempotent ZADD into sorted sets capped at 500 makes at-least-once safe.
- Priority lanes protect active users; inactive users are skipped and rebuilt lazily.
- Read-time filtering makes unfollow, block and delete immediate.
- Memory, not CPU, sizes the Redis fleet.
- Measure latency by tier, lag, outbox age and a reconciliation miss rate.

**Likely follow-ups:**
1. **How do you prove no post is lost?** Continuous reconciliation: sample posts and active followers, check the post is in the merged feed within SLO, alert on misses; replay fixes gaps.
2. **How do you pick the celebrity threshold?** Plot fanout latency and cost by follower count, cut where push breaches 5 s at peak, keep pulled authors per reader small, add hysteresis.
3. **Multi-region?** Each region consumes replicated post-events and fans out to users homed there; after failover, inboxes rebuild lazily.
4. **Ranking needs more than 500 candidates?** Raise the cap only for heavy readers, or pull more from top-affinity authors; ranking also adds out-of-network sources.
5. **Private accounts?** Fan out only to approved followers; the read filter and celebrity pull check visibility per reader.

**Director layer:**
- **Cost drivers:** Redis memory (7-14 TB, about 200 nodes) dominates; the 500 cap, inactive-user skipping and the celebrity tier are the levers. Target flat or falling cost per 1M posts.
- **Team ownership:** posts and outbox, graph store, fanout pipeline, feed read service, with ranking as a downstream consumer.
- **Top risks:** a celebrity post or live event saturating fanout, a dual-write bug losing posts, spam fanout storms, and a Redis outage emptying inboxes (mitigated by replicas and pull rebuild).
