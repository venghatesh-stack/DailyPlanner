# Design a comment system with sorting and pagination: the 5-page summary

Comments look like simple rows under a post, but the hard part is reading them: several sort orders whose scores keep changing, infinite scroll that must never duplicate or skip, and viral posts with a million comments. The single most important idea: never use OFFSET; serve every order from a keyset cursor (last score plus id plus a snapshot time) over a precomputed per-post ranked index.

## Page 1. The problem, scope and numbers

**Pitch:** load the first page of comments for any post in under 200 ms, in a meaningful order, and let people scroll endlessly without seeing the same comment twice.

**Who uses it:** readers (scan the best comments), commenters (post fast, see it instantly), creators (pin, hide, restrict), trust and safety (spam, takedowns, audit), and feed and notification teams (events and cheap counts).

**In scope:**
- **Create, edit, delete:** edit within 15 minutes; a deleted parent with replies stays as a tombstone.
- **Sorted lists:** top-level comments in best, top, newest or oldest, with cursor pagination.
- **Replies:** two levels only; oldest first; first 2 replies inline plus "View 34 more replies".
- **Likes, pins, counts:** likes via the existing reaction system; one pinned comment; comment_count and reply_count.
- **Moderation:** auto-hide spam, creator hide, keyword filters, restrict to followers, reports.

**Out of scope:** arbitrary-depth (Reddit-style) trees, end-user search over comments, translation (a hook only), livestream chat.

**Non-functional targets:**
- **Latency:** first page p99 under 200 ms (p50 under 60 ms); next pages p99 under 250 ms; writes p99 under 150 ms.
- **Availability:** 99.95% for reads, 99.9% for writes.
- **Consistency:** read-your-writes for the author; others see new comments within 5 s; counts eventually consistent; no duplicates within a session.
- **Durability:** no acknowledged comment lost (RF 3, quorum writes). Legal takedowns reach every cache within 1 hour.

**Capacity math (500M DAU, 2 comments and 20 page reads each per day):**
- **Writes:** 1B / 86,400 = about 11.6K/s, 58K/s at 5x peak. Modest, so spend effort on the read path.
- **Page reads:** 20B / 86,400 = about 230K pages/s, 1.2M/s at peak. A 20:1 read-heavy load, so precompute orders and cache pages.
- **Hydration:** 230K pages x 20 comments = 4.6M comment fetches/s if uncached. So batch multi-gets and caches must cut store reads by over 90%.
- **Storage:** 1B x 350 B = 350 GB/day, about 128 TB/year, 384 TB with RF 3. Append-heavy with key access, so a wide-column store fits.
- **Ranking index:** 10M active posts x 5,000 ids x 30 B = 1.5 TB. Too much, so keep sorted sets only for posts with over 50 comments in 7 days (about 2M posts, 300 GB) and build the rest on demand.
- **Bandwidth:** 1.2M pages/s x 8 KB = about 9.6 GB/s at peak. So keep pages small and serve through regional edges.

## Page 2. The architecture

```
 Client (sheet, cursor, seen-set)
    v
 API Gateway: auth, rate limit, routing
    | write                               | read
    v                                     v
 Comment Service                       Comment Read API
 (validate, spam, id)                  (cursor -> index page -> batch hydrate)
    |            | outbox                 |        |          |
    v            v                        v        v          v
 Comment Store   Kafka comment-events    Redis    Comment    Profiles,
 (Cassandra)       |        |            zsets    cache      Reactions
    ^              v        v              ^      (Memcached)
    |       Ranking Worker  Counters,      |         |
    |              |        notify, spam   |         |
    |              +-----------------------+         |
    +------------------------------------------------+ (misses)
```

- **API Gateway:** auth, per-user rate limits, routing, compression.
- **Comment Service:** checks permissions and blocks, fast spam model (under 20 ms), Snowflake id, store plus outbox.
- **Comment Store (Cassandra):** comments by (post, bucket), ordered by time-sortable id.
- **Kafka comment-events:** created, edited, liked, hidden events keyed by post_id.
- **Ranking Worker:** computes top and best scores; keeps per-post sorted sets trimmed to 5,000.
- **Ranking index (Redis):** best and top sorted sets per post; first-page cache with 5 s TTL.
- **Comment cache (Memcached):** bodies by id; leases stop thundering herds.
- **Comment Read API:** decodes cursors, pages the index, hydrates in batch, filters hidden and blocked.
- **Counter service and moderation pipeline:** coalesced counts; deep spam models, reports, takedowns.

**Flow A: open the sheet (best sort)**
1. GET comments?sort=best&limit=20; check the first-page cache (5 s TTL).
2. On a miss, read the top 20 from the best sorted set; a cold post loads 500 recent comments, scores them, builds a set with 1 h TTL.
3. Put the pin first; drop ids hidden for this viewer.
4. Batch-get bodies, authors, like state and 2 reply previews in parallel.
5. Return items and next_cursor = (sort, last_score, last_id, snapshot_ts).

**Flow B: post a comment**
1. Client sends text plus a client_id and shows it at the top at once (optimistic).
2. Service checks restrictions, rate limit (for example 10/min) and the fast spam model.
3. Write the row with INSERT IF NOT EXISTS on (author, client_id), plus an outbox event.
4. Async: counters, ranking insert, notifications, deep spam model.

## Page 3. The core deep dives

### 1. Keyset pagination with a snapshot
OFFSET re-counts every earlier row, so deep pages get slower, and an insert shifts everything by one, causing duplicates. A keyset cursor remembers the last (score, id) and asks for items strictly after it; the id breaks ties so the order is total. The cursor also carries snapshot_ts from page one: comments created later are skipped and shown through an "N new comments" pill instead. If scores change and a comment moves up, it may be skipped this session; the client's seen-set drops any repeat. The cursor is HMAC-signed, so a tampered one returns 400.

### 2. The best score: Wilson lower bound
Raw likes favour old comments; average ratings favour tiny samples. The Wilson lower bound asks "with 95% confidence, approval is at least this". Example: Shreya's comment has 9 likes out of 10 votes, Sethu's 900 out of 1,000. Both are 90%, but Sethu's bound is much higher because the sample is larger. Negatives are reports, hides and sampled scroll-past impressions. The score is multiplied by a gentle time decay, 1 / sqrt(1 + age_h / 24), so new good comments can surface. A friend boost is added per viewer at read time, by reranking the shared top 100 on the first page only.

### 3. Hot posts and batch hydration
A page needs bodies, authors, like state and reply previews. Per-comment calls would be N+1, so the Read API gathers all ids and sends one multi-get per dependency in parallel, each with a 50 ms budget and a fallback (default avatar, no like state). Single-flight on cache misses means 100K readers of one viral post cause one store read per id. A shared first-page id list per (post, sort) lives for 5 s; viewer filtering happens after. A post with a huge partition moves to day buckets for new writes.

**Data model:**
- **comment** (Cassandra): PRIMARY KEY ((post_id, bucket), comment_id DESC); bucket 0 normally, day number for high-volume posts; comment_by_id lookup table.
- **reply** (Cassandra): PRIMARY KEY ((parent_id), comment_id ASC); replies to replies sit under the top-level parent with reply_to_user_id.
- **Ranking index** (Redis): best:{post} and top:{post} sorted sets, page:{post}:{sort} for 5 s, pin:{post}; hash tag keeps a post on one shard.
- **comment dedupe**: PRIMARY KEY ((author_id), client_id), 1-day TTL.
- **Counters**: cnt:comments:{post} in Redis plus a durable store, shown as hints.

**Key APIs:**
- `GET /v1/posts/{id}/comments?sort=&cursor=&limit=20`: signed cursor, never OFFSET.
- `GET /v1/comments/{id}/replies?cursor=`: oldest-first keyset within the parent.
- `POST /v1/posts/{id}/comments`: idempotent on (author, client_id); 429 rate limited, 403 restricted.
- `PATCH /v1/comments/{id}`: within 15 minutes, version check, edit history kept.
- `POST /v1/posts/{id}/comments/{cid}/pin`: owner only, one pin per post.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hydration fan-out:** batch multi-gets, single-flight, strict timeouts with fallbacks.
- **Viral post reads:** shared 5 s first-page cache; most of the order is shared across viewers.
- **Ranking memory:** sorted sets only for active posts, trimmed to 5,000; beyond that the cursor switches to newest order.
- **Hot partitions:** bucket high-volume posts by day; reads span buckets.
- **Spam waves:** per-user and per-post limits, MinHash near-duplicate checks, new accounts held as pending.

**Failure modes:**
- **Redis ranking cluster down:** best and top fall back to newest from the store; writes continue; sets rebuild lazily.
- **Comment cache cold:** single-flight and leases throttle store load; hot first pages rewarm in seconds.
- **Profile service slow:** 50 ms timeout, minimal cached profile; never fail the page.
- **Spam model down:** new or low-trust accounts go pending (visible only to the author); trusted accounts pass.
- **Ranking consumer lag:** new comments miss best order for longer; newest unaffected; alert over 30 s.
- **Takedown:** event fans out to all regions; caches dropped by id; hydration refuses a flagged row even from a stale list.

**Trade-offs chosen:**
- **Two-level threading over arbitrary depth:** readable on mobile, simple pagination per parent.
- **Keyset over offset:** constant cost per page and stable under inserts; no random page jumps needed.
- **Precomputed ranking for active posts, on demand for cold:** reads are 20x writes and concentrated.
- **Shared cache plus per-viewer filtering over fully personal pages:** 100K readers per second on one post.
- **Fast sync spam check, deep async:** keeps write p99 under 150 ms; async can hide later.
- **Cassandra over sharded MySQL:** append-heavy, key-based access, no joins on the read path.

**What to measure:** first-page and next-page p50/p99 by sort and post size; cache hit rates and single-flight collapse ratio; write p99 and rejection reasons; ranking worker lag; client duplicates per session and empty-page rate; spam prevalence and false positives; partition size warnings.

## Page 5. Say it in the interview

> "I will assume two visible levels, top-level comments and replies, sorts of newest, top and best, and infinite scroll. At a billion comments written and twenty billion page reads a day, this is read-heavy and very skewed. The naive table with ORDER BY and OFFSET breaks twice: OFFSET slows down deep, and changing scores make pages duplicate or skip. So I partition comments by post with time-sortable ids, which makes newest a range scan. For ranked sorts I keep a per-post sorted set, updated by a worker reading comment and like events, and page it with a cursor of score, id and snapshot time. Each page is twenty ids hydrated in one batch. Viral posts get a five-second shared first page, counts are async, and if ranking fails we fall back to newest."

**Key points to land:**
- Never OFFSET: keyset cursors with a unique tie-breaker, opaque and signed.
- Comments by (post, bucket) with time-ordered ids: newest and oldest are range scans.
- Precomputed sorted sets for active posts; cold posts built on demand.
- Best = Wilson lower bound with gentle decay, plus read-time personal boosts.
- Snapshot time in the cursor stops new comments shifting pages; the seen-set kills duplicates.
- Two-level threading: replies paged per parent, first two inlined.
- Batch hydration with timeouts and single-flight; shared first page for viral posts.
- Idempotent creates with client keys; read-your-writes for the author.

**Likely follow-ups:**
1. **Reddit-style depth?** Store a materialized path per comment, fetch a subtree to depth 5 by path prefix, show "continue this thread" beyond it.
2. **Live "N new comments"?** Hot posts only: a WebSocket channel sends count deltas once per second; tapping fetches newest since snapshot_ts.
3. **Personal ranking without killing the cache?** Shared top 200 per post, then a cheap per-viewer rerank (friends, language).
4. **Counts on feed cards?** From the coalesced counter service, rounded; never by counting rows.
5. **Testing pagination?** Property tests with random inserts, deletes and score changes: no duplicates, every stable item exactly once.

**Director layer:**
- **Cost drivers:** hydration fan-out (cache hit rate is the lever), about 300 GB of Redis sorted sets, 384 TB/year of replicated storage, 9.6 GB/s peak egress.
- **Phasing:** newest-order keyset first; then best sort with Wilson scoring; then personal reranking and live pills.
- **Team ownership:** comments platform, ranking, trust and safety, feed and notification consumers, SRE.
- **Top risks:** duplicates as scores change, viral posts overloading a partition, like rings gaming best sort, spam false positives silencing real users.
