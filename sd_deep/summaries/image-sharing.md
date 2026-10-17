# Design Instagram-style image sharing: the 5-page summary

An image sharing service is a read-heavy media pipeline glued to a social graph: uploads are rare and large, views are constant and must be fast. The single most important idea: this is an egress problem (about 3 PB a day of image reads), so bytes never touch the app tier and the CDN hit ratio is the number you protect.

## Page 1. The problem, scope and numbers

**Pitch:** let people share photos with followers instantly and reliably, even on flaky Indian 3G/4G, at a storage and bandwidth cost per user below ad revenue per user, while keeping abusive content off the platform.

**Who uses it:** posters (fast, resumable upload, see their own post at once), scrollers (smooth feed, instant images), moderators and legal (fast takedowns), and finance (cost per DAU).

**In scope:**
- **Upload:** presigned, resumable URLs valid 15 minutes; JPEG/HEIC/PNG up to 20 MB; EXIF GPS stripped.
- **Variants:** 150, 320, 640 and 1080 px in WebP and AVIF; the original is kept.
- **Posts:** 1-10 photos plus caption, idempotent on a client key; profile grid.
- **Home feed:** cursor pages of 20 posts, newest-first candidates for the ranker.
- **Social:** follow, private accounts, likes and comments with counters.
- **Delete and moderation:** hide at once, purge CDN, delete blobs after 30 days; hash match on upload, async ML.

**Out of scope:** video, Reels and Stories, ranking model training, ads, direct messages, search (follow-up only).

**Non-functional targets:**
- **Availability:** 99.95% for feed and image reads; 99.9% for uploads.
- **Latency:** feed p50 80 ms, p99 300 ms server side; CDN time to first byte p95 under 100 ms in-region.
- **Durability:** originals 11 nines (erasure coded, multi-AZ); metadata RPO under 1 minute.
- **Consistency:** read-your-writes for the author; followers see a post within 5 s p95.
- **Privacy:** private media via signed URLs with 1 h expiry.

**Capacity math (500M DAU, 100M uploads/day):**
- **Uploads:** 100M / 86,400 = about 1,160/s, 3,500/s peak. Modest, so keep multi-MB bodies off the app tier rather than scaling it.
- **New storage:** 100M x 2 MB = 200 TB/day plus 30 TB of variants = 230 TB/day, 84 PB/year; x 1.4 erasure coding = about 118 PB/year of disk. So tier originals to cold storage after 90 days (about 60% cheaper).
- **Image views:** 500M x 100 = 50B/day = 580k/s, 1.5M/s peak; 500 views per upload.
- **Egress:** 50B x 60 KB = 3 PB/day = 280 Gbps average, 700 Gbps peak. At a 95% hit ratio the origin sees about 35 Gbps. So egress dominates cost: codecs and CDN matter more than database tuning.
- **Feed:** 500M x 10 opens = 5B/day = 58k QPS, 150k peak.
- **Fan-out:** 100M posts x 200 followers = 20B timeline inserts/day, about 230k/s. So cap celebrity fan-out.
- **Feed cache:** 500 post IDs x 8 B x 500M = 2 TB, about 6 TB of Redis with sorted-set overhead.

## Page 2. The architecture

```
 Mobile / Web
   | 1. POST /uploads -> presigned URL       5. GET feed, GET image
   v                                            |
 API GW (auth, rate limit) -> Upload svc        v
   |   | 2. PUT bytes (multipart)          CDN edge -> origin shield
   |   v                                        | miss -> image proxy
   |  Object store (raw/, derived/) <-----------+
   |   | 3. object-created event          ^ writes variants
   |   v                                  |
   |  Kafka media.* -> Resize workers ----+   Moderation (pHash, ML)
   |                        | 4. mark READY
   v                        v
 Post / Feed / Graph svc -> Metadata (sharded Postgres, Cassandra)
   | post.created (outbox)
   v
 Fan-out workers -> Feed cache (Redis sorted sets per user)
```

- **API gateway:** TLS, auth, per-user token-bucket rate limits.
- **Upload service:** media row PENDING, presigned resumable URLs; never handles bytes.
- **Object store:** erasure-coded originals and variants; cold tier after 90 days.
- **Media pipeline:** Kafka workers strip EXIF, resize to 4 sizes, encode, mark READY.
- **Moderation:** inline perceptual-hash match, async ML, takedown with CDN purge.
- **Post service:** posts referencing READY media; outbox emits post.created.
- **Graph service:** follow edges both directions, follower counts, private approvals.
- **Fan-out workers and feed service:** push IDs to timelines; merge, rank, hydrate.
- **CDN, origin shield, image proxy:** 1-year cache; shield collapses misses; proxy resizes as fallback.

**Flow A: upload and publish**
1. POST /v1/uploads with size, type, sha256; get a presigned URL.
2. PUT bytes in 5 MB parts straight to object storage; resume failed parts.
3. The event triggers a worker: checksum, pHash check, strip EXIF, 4 variants, mark READY if still PENDING.
4. POST /v1/posts with an idempotency key; post and outbox row commit together; the author's profile cache updates at once.

**Flow B: home feed and image**
1. Read up to 200 IDs from timeline:{uid}; pull recent posts of followed celebrities.
2. Rank (50 ms timeout, else chronological); hydrate top 20 from the post cache.
3. Return CDN URLs sized for the device; an edge hit serves in about 20 ms.

## Page 3. The core deep dives

### 1. Hybrid fan-out
Authors with up to 10k followers are pushed: post.created pages through followers and adds the post ID to each timeline in pipelined batches of 1,000, trimmed to 500 entries. Above 10k, the post goes only into the author's recent-posts list, and followers' feeds pull it at read time. A celebrity with 50M followers therefore costs one write, not 50M. Followers inactive for 30 days are skipped; their timeline is rebuilt at next login. Unfollows are filtered at read time.

### 2. Immutable, content-addressed URLs and the CDN
Variants live at /m/{content_hash}_{width}.{format}, cached for a year. The content never changes under a URL, so the normal path needs no invalidation, and a meme uploaded by millions is stored and cached once. The feed API picks width and format, so the CDN does not fragment its cache on Accept headers. A regional origin shield collapses misses: a viral image costs one origin fetch per region. Takedowns stop returning the URL and purge by surrogate key.

### 3. Time-sortable IDs and sharding
Data is sharded by owner id into 4,096 logical shards on fewer hosts, so rebalancing moves a shard instead of rehashing. IDs are 64 bits: 41 bits of milliseconds (about 69 years), 13 bits of shard, 10 bits of sequence (1,024 per ms per shard). They sort by time, double as feed cursors and timeline scores, and reveal their shard with no lookup.

### 4. Idempotent async pipeline
Kafka delivers at least once. Workers write variants to deterministic keys and set READY only WHERE status = PENDING, so reprocessing rewrites identical bytes and the update is a no-op. Poison images go to a dead-letter queue after 5 attempts. Images are decoded in a sandbox with a 100 MP pixel cap and always re-encoded, so no original bytes are served.

**Data model:**
- **media** (sharded Postgres, by owner_id): media_id, status PENDING/READY/BLOCKED/DELETED, content_hash, variants.
- **post** (sharded Postgres, by author_id): post_id (time-sortable), caption, media_ids; index (author_id, post_id desc).
- **follow** (Cassandra): followers_by_user and following_by_user; celebrity partitions bucketed.
- **timeline** (Redis sorted set, Cassandra backup): timeline:{user_id}, member and score = post_id, 500 entries.
- **like** (Cassandra): PK post_id, CK user_id; counters in sharded Redis, reconciled hourly.

**Key APIs:**
- `POST /v1/uploads`: 60 per hour per user, over 20 MB rejected, dedup on sha256 per user.
- `POST /v1/posts`: media not owned or not READY gets 409, retry after 1 s.
- `GET /v1/feed?cursor=&limit=20`: cursor is the last post_id.
- `POST /v1/posts/{id}/likes`: idempotent set membership (user_id, post_id).
- `DELETE /v1/posts/{id}`: soft delete, post.deleted event, CDN purge.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Egress:** AVIF (30-50% smaller than JPEG), sizes matched to screen density, multi-CDN with committed pricing, origin shield.
- **Storage:** erasure coding at 1.4x instead of 3x replication; cold tier after 90 days.
- **Fan-out:** the 10k threshold bounds write amplification; skipping inactive users trims it further.
- **Hot metadata shards from viral accounts:** cache posts and counters, shard counters, read replicas.
- **Object store throttling:** hash-prefixed keys spread partitions; clients retry parts with jitter.

**Failure modes:**
- **Resize backlog:** posts still publish; the image proxy resizes on demand; autoscale on consumer lag; alert if time to ready p95 exceeds 10 s.
- **CDN outage in a region:** DNS multi-CDN steering shifts traffic in minutes; shield sized for 2x normal misses.
- **Redis timeline loss:** affected users get a pull-built feed with fewer candidates; timelines rebuild lazily.
- **Metadata primary fails:** failover to a sync replica in about 30 s; writes get 503 with retry-after; reads from replicas.
- **Ranker times out:** 50 ms timeout, chronological fallback, breaker after 50% errors in 10 s.
- **Region loss:** objects replicated async; metadata standby with RPO under 1 minute; the CDN keeps serving cached images.

**Trade-offs chosen:**
- **Presigned direct upload over proxying bytes:** the app tier scales with metadata, not megabytes; costs a more complex client.
- **Hybrid fan-out at 10k over pure push or pull:** fast reads for most users, bounded writes for celebrities.
- **Pre-generate 4 sizes, resize on the fly as fallback:** predictable hits; new device sizes without reprocessing billions.
- **Postgres for posts and users, Cassandra for likes and edges:** transactions where needed, write throughput where data is append-only.
- **AVIF with WebP and JPEG fallback:** encode CPU is paid once; egress savings every view.
- **Inline hash match, async ML:** hashing is cheap and catches known illegal content; ML would slow every upload.

**What to measure:** upload success by network type (99.5% overall, 98% on 3G), time to ready p95 under 3 s and Kafka lag, CDN and shield hit ratio (95% of bytes) and origin Gbps, feed p99 and ranker timeouts, fan-out lag, Redis memory and hot keys, moderation queue age and takedown time (under 15 minutes), storage growth and cost per DAU.

## Page 5. Say it in the interview

> "Users upload photos, follow people and scroll a feed, at about 500 million daily users and 100 million uploads a day, so views outnumber uploads 500 to 1. This is a delivery problem first. Targets: feed p99 under 300 milliseconds, images from the edge under 100, originals never lost, and you always see your own post at once while followers can lag a few seconds. Clients upload straight to object storage with a presigned URL; an event triggers workers that make four resized variants under content-addressed keys, so URLs are immutable and cacheable for a year. Metadata is sharded by user ID with time-sortable post IDs. Feeds use hybrid fan-out: push into Redis timelines for normal authors, pull for celebrities. The real bottleneck is egress, about 3 petabytes a day, so I live and die by CDN hit ratio and an origin shield."

**Key points to land:**
- An egress problem: about 3 PB/day of reads; protect the CDN hit ratio.
- Bytes never touch the app tier: presigned uploads, async processing via Kafka.
- Immutable, content-addressed variant URLs cached for a year; no routine invalidation.
- Metadata sharded by user id; 64-bit time-sortable IDs double as cursors.
- Hybrid fan-out: push under 10k followers, pull for celebrities, skip inactive users.
- At-least-once everywhere, idempotent consumers, transactional outbox.
- Read-your-writes for the author; followers within about 5 s.
- Degrade gracefully: on-the-fly resize, chronological feed, pull feed.
- Cost levers: AVIF, tiering after 90 days, erasure coding at 1.4x.

**Likely follow-ups:**
1. **How do you count likes on a viral post?** Like edges in Cassandra are the truth; Redis keeps N sub-counters per hot post, summed on read and reconciled from the edges.
2. **How do you cut storage cost by 30%?** Tier originals after 90 days, erasure code instead of replicating, drop rarely used variants and generate them on demand, switch to AVIF.
3. **A new 2160 px tablet variant?** Do not reprocess the archive; the on-the-fly resizer serves it and the CDN caches it; generate it eagerly only for new uploads.
4. **Remove a known illegal image everywhere?** Match perceptual hashes on upload and backfill-scan stored hashes when a new one is added; mark BLOCKED, remove from feeds, purge the CDN, log for legal.
5. **Multi-region active-active?** Each user writes to a home region; media replicates async; feeds build in the reader's region; IDs carry the shard, so no global sequencer.

**Director layer:**
- **Cost drivers:** CDN egress first (3 PB/day), then about 118 PB/year of erasure-coded disk, about 6 TB of Redis for timelines, and AVIF encode CPU.
- **Phasing:** presigned upload, variants and CDN plus sharded metadata first; then hybrid fan-out and ranking hooks; then multi-region and on-demand variants.
- **Team ownership:** media platform (upload, pipeline, CDN), feed and graph, trust and safety (moderation), storage and SRE.
- **Top risks:** CDN cost growing with users, celebrity fan-out storms, illegal content going viral before detection, hot metadata shards; plus in-country data residency for Indian user data.
