# Design a Social News Feed (Facebook / Twitter / Instagram home timeline): the 5-page summary

A news feed merges posts from hundreds of followed accounts into one ranked, personal list that loads in under 200 ms. The single most important idea: decide where to pay the merge cost. Push post IDs into precomputed timelines for normal authors (cheap reads), pull celebrity posts at read time (no write storms), then rank, hydrate and paginate on top, degrading to chronological rather than ever failing.

## Page 1. The problem, scope and numbers

**Pitch:** show each user the most relevant fresh posts from the accounts they follow, instantly, for 500 million daily users, while giving creators fast reach and ads a reliable surface.

**Who uses it:** daily scrollers (open the app 15 times a day on mid-range phones), users following thousands of accounts (want close friends to float up), celebrities and creators (reach millions fast), integrity analysts (remove harmful posts from every feed in seconds).

**In scope:**
- **Posts:** create (5,000 chars, 10 media items), edit, delete.
- **Graph:** follow, unfollow, mute, block.
- **Home feed:** GET /feed with a cursor returns 20 ranked, hydrated items; a chronological toggle.
- **New-post indicator:** a cheap count of items newer than the top of the feed.
- **Engagement:** like, comment, share counts on items; impression logging for ranking.
- **Ads slots:** e.g. every 5th item, filled by the ads service.

**Out of scope:** stories, reels and live video, comment ranking, the ad auction, search and hashtags, notifications and DMs.

**Non-functional targets:**
- **Latency:** first page p99 under 200 ms server, p50 under 80 ms; payload under 50 KB.
- **Freshness:** post visible to followers p95 under 5 s (under 60 s for celebrities).
- **Availability:** 99.95% feed reads, 99.9% post writes; degraded beats an error.
- **Consistency:** eventual for feeds, read-your-writes for an author's own post; deletes and blocks within 10 s.
- **Durability:** an acknowledged post is never lost (RF=3 across zones).

**Capacity math (500M DAU, 10 loads a day, 100M posts a day, 3x peak):**
- **Feed reads:** 500M x 10 / 86,400 = about 58K/s, 175K/s peak. So reads must be a cache lookup, not a query.
- **Post writes:** 100M / 86,400 = about 1.2K/s, 3.5K/s peak. Small.
- **Fan-out writes:** 1.2K/s x 200 average followers = 240K timeline inserts/s, 700K/s peak. So writes are amplified 200x, and a 100M-follower celebrity cannot be pushed.
- **Timeline cache:** 500M x 800 IDs x 32 B (id, score, overhead) = about 12.8 TB; plan 10-15 TB of Redis RAM. So store IDs only, cap lists, skip inactive users.
- **Hydration:** 175K/s x 20 posts = 3.5M object reads/s. So the object cache is the biggest QPS consumer.
- **Post storage:** 100M x 1 KB = 100 GB/day, about 36 TB/year before replication; media lives in object storage.

## Page 2. The architecture

```
 Mobile / Web
   | POST /posts                        GET /feed?cursor
   v                                         v
 API GW -> Post svc -> Post DB          Feed svc -> Ranking (2-stage, 50 ms)
            | (sharded by post_id)        |   |  hydrate
            | outbox: PostCreated         |   +-> Object cache (posts, users,
            v                             |        counts) -> stores on miss
          Kafka (by author_id)            | timeline ids + celeb lists
            v                             v
       Fan-out workers --ZADD--> Timeline cache (Redis zset per user, 800)
            | followers?     ^
            +--> Graph svc   |
            +--celeb post--> Author recent-posts cache (celebs, last 200)
```

- **Post service:** stores posts with Snowflake (time-ordered) IDs; events via an outbox.
- **Post store:** sharded by post_id; author_id index of recent post IDs.
- **Graph service:** follow edges stored both ways; follower pages for fan-out; blocks, mutes.
- **Fan-out service:** push or pull per post by follower count; ZADD into active followers.
- **Timeline cache:** Redis sorted set per user, post IDs only, capped at 800.
- **Author recent-posts cache:** last post IDs per celebrity, merged at read time.
- **Feed service:** merge, filter, hydrate, rank, paginate, insert ads, degrade.
- **Ranking service:** light model on about 500 candidates, neural model on the top 100.
- **Object cache:** posts, profiles, counters in Memcached or Redis with leases.

**Flow A: publish (normal author)**
1. Media goes to object storage by pre-signed URL; POST /posts with media IDs.
2. Post row and outbox row commit together; 201 returned; relay publishes to Kafka.
3. Under 100K followers: page followers 5K at a time, skip users inactive 30+ days, pipeline ZADD and trim to 800.
4. The author's own timeline updates synchronously (read-your-writes).

**Flow B: read the feed**
1. Read the top 500 IDs of timeline:{uid}; merge followed celebrities' recent lists by ID.
2. Filter deleted (tombstones), blocked or muted, already seen (Bloom filter).
3. Multiget hydrate; rank within 50 ms or fall back to time order; snapshot the ranked list; return 20 plus a cursor.

## Page 3. The core deep dives

### 1. Hybrid fan-out
Pure push is cheap to read but a 100M-follower post is 100M cache writes. Pure pull is cheap to write but every feed load scatter-gathers hundreds of authors. The hybrid: authors under 100K followers (all but about 0.01% of accounts) push to active followers; celebrity posts go only to author_recent:{author_id}, and their followers merge those lists at read time. A user following 20 celebrities adds 20 small cache reads. Hysteresis stops flapping: promote at 100K, demote at 80K. ZADD is idempotent, so Kafka redelivery is harmless. A user returning after 6 months has no timeline; the feed service pulls from followees' author indexes (100 ms budget), writes the list back and marks the user active.

### 2. Snowflake IDs as sort key, merge key and cursor
post_id embeds time, so it is the sorted-set score, the key for a k-way merge of timeline and celebrity lists, and the keyset cursor in chronological mode. Shard bits inside the ID let the hydrator route without a lookup. Workers refuse IDs if the clock goes backwards.

### 3. Ranking with a deadline and stable pagination
Candidate generation gives about 500 items. A GBDT first pass scores them in a few ms; a neural second pass predicts like, comment and dwell for the top 100, combined into one value score. Rules cap consecutive posts per author and insert ads. If the 50 ms deadline expires, use the first pass or time order. The ranked 500 are snapshotted in a feed session (TTL 30 min), and the cursor is {session_id, offset}, so page 2 never repeats page 1 even as new posts arrive. If the snapshot expires, rebuild below the last post_id shown and exclude seen IDs.

### 4. Deletes, blocks and edits
Timelines hold IDs, not copies. A delete writes a tombstone checked on every read, so it vanishes at once even after fan-out to 5M timelines; cleanup is lazy. An edit invalidates one object-cache entry and every feed shows the new version.

**Data model:**
- **Post** (sharded MySQL or Cassandra): PK post_id (Snowflake); author_id, text, media_ids, visibility, deleted_at.
- **AuthorPostIndex** (Cassandra): partition author_id, clustering post_id descending.
- **FollowEdge**: followers_by_user (followee_id, follower_id) and following_by_user (follower_id, followee_id).
- **Timeline** (Redis Cluster): timeline:{user_id}, member and score post_id; cap 800, TTL 30 days idle.
- **FeedSession** (Redis, 30 min): session_id to 500 ranked post IDs.

**Key APIs:**
- `POST /v1/posts`: returns quickly; fan-out is async.
- `GET /v1/feed?cursor=&limit=20&mode=ranked|chrono`: first call creates the session snapshot.
- `GET /v1/feed/new_count?since_id=`: cheap ZCOUNT, polled every 60 s or pushed.
- `DELETE /v1/posts/{post_id}`: tombstone now, timeline cleanup later.
- `PUT /v1/follows/{target_id}`: backfills the target's last 20 posts.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Fan-out writes:** Kafka partitioned by author, horizontal workers, pipelined ZADD in batches of 1K, active users only.
- **Celebrity hot keys:** replicate each celebrity's recent list into every feed node's local cache with a 1-2 s TTL.
- **Hydration:** one multiget per shard, 99% object cache hit rate, replicas for misses.
- **Redis cost:** 150-300 primaries plus replicas; shrink with smaller caps (e.g. 300) for low-activity users.
- **Viral like counters (100K increments/s):** sharded sub-counters summed on read, cached 1-2 s.
- **Users following 300 celebrities:** merge the 50 most engaged at read time; a periodic job pushes the rest in bulk.

**Failure modes:**
- **Ranking timeout or outage:** serve first-pass or chronological order, marked degraded.
- **Timeline shard down:** replica takes over in seconds; if lost, users rebuild by pull under a global rebuild limiter.
- **Fan-out backlog in a spike:** prioritise active users and close friends, autoscale workers, alert on the freshness SLO.
- **Cold object cache after region failover:** shift traffic 10%, 50%, 100%; leases throttle DB fills; return partial items.
- **Graph service slow:** use the cached followee list (5 min TTL), skip the celebrity merge.
- **Bad ranking model:** shadow and canary with engagement guardrails, automatic rollback.

**Degradation ladder:** drop second-pass ranking, then serve a stale cached page, then chronological from cache only, then a trending fallback. Never a blank screen.

**Trade-offs chosen:**
- **Hybrid fan-out over pure push or pull:** bounds write amplification, keeps reads to one lookup plus a few lists.
- **IDs only in timelines over full posts:** 50-100x less memory; one invalidation per edit or delete.
- **Redis capped at 800 over unbounded history:** sub-ms reads at 175K/s; older posts come from author indexes.
- **Ranked by default with a chronological toggle:** engagement plus user control and regulatory expectations.
- **Snapshot cursors for ranked, keyset for chronological:** stable pages, bounded memory.
- **Tombstone plus async cleanup for deletes:** instant for users, O(1) write.

**What to measure:** feed p50/p99 per stage (candidates, hydrate, rank), fan-out lag p95 and Kafka consumer lag, timeline and object cache hit ratios (target 98% or more), hot keys, ranking deadline-exceeded rate, short-feed rate, delete propagation (under 10 s p99), and engagement guardrails (session length, hides per 1K impressions).

## Page 5. Say it in the interview

> "Assume 500 million daily users loading the feed 10 times a day: about 60 thousand reads a second, 175 thousand at peak, against about 1,200 posts a second. Reads dominate, so I precompute timelines. But follower counts follow a power law, and one celebrity post could mean 100 million cache writes, so I use a hybrid: fan-out on write for normal authors into each active follower's Redis timeline of post IDs, and fan-out on read for celebrities, merged when you open the app. A post service writes posts with time-ordered IDs and emits an event through an outbox; fan-out workers push IDs; the feed service merges, filters, hydrates from caches, ranks with a two-stage model in 50 milliseconds and paginates with a snapshot cursor. If ranking or a cache fails, we degrade to chronological, never to a blank screen."

**Key points to land:**
- Reads dominate (175K/s vs 3.5K posts/s), but fan-out multiplies writes 200x.
- Hybrid: push for normal authors to active followers, pull for celebrities.
- Timelines hold IDs only, in Redis sorted sets capped at 800; hydrate from a shared cache.
- Snowflake IDs give time order for free: sort key, merge key and cursor.
- Ranking is a funnel with a deadline; degrade to chronological, never an error.
- Session snapshot cursors keep ranked pagination stable.
- Outbox plus idempotent ZADD and ZREM make at-least-once delivery safe.
- Deletes and blocks are enforced at read time immediately; cleanup is async.
- Measure fan-out lag, feed p99 per stage and engagement guardrails.

**Likely follow-ups:**
1. **Recommended posts from accounts you don't follow?** Add a candidate source (embedding nearest neighbours, local trending) of about 100 items; the same ranker scores all; rules cap the unconnected share.
2. **Multi-region?** Users are homed to a region; posts replicate; fan-out runs per region for followers homed there; a few seconds of extra lag is fine for feeds.
3. **New posts while scrolling?** Send a "new posts" signal or poll new_count; never reorder the visible list, prepend only on user action.
4. **How do you test a new ranking model?** Offline AUC and calibration, shadow traffic, 1% A/B with guardrails, ramp, and a long-term holdout for retention.
5. **Post changes from public to followers-only?** Update visibility, filter on read by the viewer's follow edge, remove from recommendations by event, invalidate by post ID.

**Director layer:**
- **Cost drivers:** timeline cache RAM (10-15 TB, the largest infra line item), object cache serving 3.5M reads/s, ranking inference under 50 ms, and 3-5x headroom for elections and cricket finals.
- **Phasing:** start with push timelines and chronological order; add the celebrity pull path, two-stage ranking, ads slots and recommendations.
- **Team ownership:** posts and graph, feed infrastructure (fan-out, timelines, caches), ranking and ML, integrity, ads integration.
- **Top risks:** celebrity fan-out storms, ranking that optimises clickbait, mass rebuilds after cache loss overloading the DB, filter bubbles and regulatory scrutiny.
