# Design a URL Shortener (TinyURL / Bitly): the 5-page summary

A URL shortener maps a 7-character key to a long URL. It looks trivial, but it is a read-heavy key-value system (100 reads per write) with a hard uniqueness rule on keys and a redirect that must answer in milliseconds. The single most important idea: keep the redirect path tiny and cache-first, generate keys from pre-allocated ID ranges so there is no global lock, and push click analytics off the hot path through Kafka.

## Page 1. The problem, scope and numbers

**Pitch:** a branded short-link service that is fast, always up, safe for end users, and turns every click into attribution data for campaigns.

**Who uses it:** marketers creating hundreds of campaign links by API, casual users pasting one link with no signup, trust and safety analysts disabling malicious links, and enterprise admins running a branded domain like go.company.com.

**In scope:**
- **Create:** long URL (http/https, max 2,048 characters) to a short link, with optional alias, expiry and tags.
- **Redirect:** GET /{key} returns 302; 404 if unknown, 410 if expired or disabled.
- **Custom aliases:** 3-30 characters, unique per domain, reserved words blocked.
- **Update and delete:** paid tier can change the destination; a key is never reused.
- **Analytics:** clicks over time, countries, referrers, devices; CSV export.
- **Abuse:** Safe Browsing check at create, rescans, user reports, takedown; create rate limits.

**Out of scope:** link-in-bio pages and QR designer, billing, full-text search over links, proxying destination content, exactly-once click counts (plus or minus 0.1% is fine).

**Non-functional targets:**
- **Latency:** redirect p99 under 20 ms at origin, under 50 ms at the user; create p99 under 200 ms including the malware check.
- **Availability:** 99.99% for redirects (a printed poster cannot be fixed); 99.9% for create and analytics.
- **Consistency:** read-your-writes for the creator; other regions within about 1 s.
- **Durability:** no mapping ever lost (RF=3 plus backups). Takedown global in under 60 s; analytics fresh within 5 minutes p95.

**Capacity math (100M links/month, 10B redirects/month, peak 10x average):**
- **Writes:** 100M / 2.6M s = about 40/s, 400/s peak. So writes are trivial; the only write risk is the ID generator.
- **Reads:** 10B / 2.6M s = about 3,900/s, about 40K/s peak. So design the cache first.
- **Link storage:** 100M x 500 B = 50 GB/month, 600 GB/year, 6 TB over 10 years (18 TB at RF=3). So a partitioned key-value store, not a single SQL box.
- **Key space:** 62^7 = 3.52 trillion; 1.2B links/year uses 0.03% per year. So 7 characters are enough for centuries.
- **Cache:** 20M daily active keys x 500 B = 10 GB. So the hot set fits in a 3-shard Redis cluster.
- **Clicks:** 10B x 200 B = 2 TB/month raw, the largest data volume. So analytics gets its own pipeline and store.
- **Bandwidth:** 40K/s x 500 B = 20 MB/s peak egress. Trivial.

## Page 2. The architecture

```
 creator -> API GW (auth, rate limit) -> Link API -> Safe Browsing check
                                           |  ID block (1M) <- etcd/ZooKeeper
                                           v  conditional put
                                     DynamoDB links (global tables)
                                           ^ miss
 clicker -> CDN edge -> LB -> Redirect svc -> in-proc LRU -> Redis cluster
            (hot 302s)          |
                                v async buffer, never blocks
                             Kafka -> Flink -> ClickHouse -> Analytics API
                                |
                                +-> S3 raw events (90 days)
 T&S console -> Admin svc -> status=DISABLED -> pub/sub invalidate + CDN purge
```

- **API Gateway:** TLS, API keys, per-tenant token-bucket rate limits.
- **Link API:** validates and scans URLs, allocates an ID, encodes Base62, conditional write.
- **ID range allocator (etcd):** hands each node a disjoint 1M-ID block, per region.
- **Links store (DynamoDB global tables):** source of truth for key to URL, RF=3, multi-region.
- **Redirect service:** separate, minimal deployable: lookup, status check, 302, async click.
- **Redis cluster:** read-through cache of key to URL, status and expiry, plus 404 tombstones.
- **CDN edge:** caches 302s for the hottest keys for 60 s; absorbs viral spikes and DDoS.
- **Kafka + Flink + ClickHouse:** durable click stream, enrichment, per-minute aggregates, fast dashboards.
- **Trust and Safety service:** rescans, reports, blocklists, takedown with cache invalidation.

**Flow A: create**
1. POST /v1/links with an Idempotency-Key; a repeat key returns the stored response.
2. Normalise the URL; reject non-http(s) and our own domain. Safe Browsing with a 100 ms timeout.
3. Take the next local ID, permute it, Base62-encode to 7 characters.
4. Put if the key does not exist (409 on an alias clash); write through to Redis; return 201.

**Flow B: redirect**
1. CDN serves hot keys; else in-process LRU (top 100K, 5 s), then Redis, then DynamoDB.
2. Unknown key: 60 s tombstone and 404. Expired or disabled: 410. Else 302 Location.
3. Click event to a ring buffer, batched to Kafka every 50 ms or 500 events.

## Page 3. The core deep dives

### 1. Key generation: range counter plus a keyed shuffle
Seven Base62 characters hold about 41.6 bits, so a 64-bit Snowflake ID (11 characters) is too long. Instead, each API node does one atomic increment in etcd to reserve a block of 1M integers, then hands them out locally. Blocks never overlap, so keys cannot collide, and the coordinator is touched once per million links. Sequential keys would be guessable (aZ3kQ9x, aZ3kQ9y...), so each integer goes through a bijection on [0, 62^7): a small Feistel network keyed by a secret. A bijection never maps two inputs to one output, so uniqueness holds while consecutive IDs scatter. If a node crashes with half a block left, those IDs are simply skipped. A key that spells a rude word is skipped too.

### 2. The redirect read path and its caches
Three cache tiers with falling hit rates and rising cost: the in-process LRU absorbs viral keys with no network hop, Redis holds the daily working set (target hit ratio 95% or more), and the database sees only cold keys as single-partition point reads. Unknown keys get a 60 s tombstone so scanners do not hammer the database. Singleflight collapses many concurrent misses for one key into one DB read (stampede protection). New links are written through to Redis because creators often click their own link at once. expires_at travels with the cached value, so a cached entry never outlives expiry.

### 3. 302, analytics and takedown
302 (temporary) instead of 301 (permanent), because browsers cache a 301 indefinitely: clicks would stop reaching us and a disabled phishing link would keep working. Click events never block a redirect: buffer, batch to Kafka with acks=all, spill to local disk if Kafka is down, drop and count only if the disk budget is full. Flink dedupes by event_id within a 10-minute lateness window. Takedown marks the row DISABLED, publishes invalidate(key) over Redis pub/sub and purges the CDN; the next request returns 410 with a warning page.

### 4. Custom alias races
Shreya and Sethu both ask for go/sale at once. Aliases are written in one home region with a strongly consistent conditional put (attribute_not_exists), so exactly one wins and the other gets 409 with suggestions.

**Data model:**
- **Link** (DynamoDB): partition key domain#short_key; long_url, owner_id, status, expires_at (TTL), url_hash; GSIs on owner_id + created_at and url_hash. Never hard-deleted.
- **IdempotencyRecord:** tenant_id#idempotency_key; request_hash and response; 24 h TTL.
- **IdBlock** (etcd): one counter per region, compare-and-set increment of 1M.
- **ClickEvent** (Kafka, 48 partitions, keyed by short_key, then S3 parquet 90 days); IP truncated to /24.
- **ClickAgg** (ClickHouse): ORDER BY (short_key, minute); rolled up hourly after 30 days.

**Key APIs:**
- `POST /v1/links`: 201 with short URL; 409 alias taken, 422 blocked URL, 429 rate limited.
- `GET /{key}`: redirect service only; HEAD answered cheaply for preview bots.
- `GET /v1/links/{key}/stats`: reads ClickHouse rollups; owner only.
- `PATCH /v1/links/{key}`: new destination is rescanned and caches invalidated.
- `POST /admin/v1/takedowns`: bulk disable, audited.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Redirect reads (400K/s peak):** more redirect pods, more Redis shards (slots migrate), more CDN caching; DynamoDB on-demand absorbs cold reads.
- **Writes (4K/s peak):** still trivial; the ID allocator is untouched.
- **Viral key, 200K clicks/s:** edge caches the 302 for 60 s and every node's LRU holds it, so the Redis shard sees almost nothing.
- **Analytics:** add Kafka partitions and Flink parallelism ahead of time, since repartitioning remaps keys.
- **Scanners:** tombstones, per-IP 404 limits (for example over 50 a minute), WAF at the edge.

**Failure modes:**
- **Redis node fails:** replica promoted in about 10-15 s; misses go to the DB with singleflight and concurrency limits.
- **Primary store throttled or region down:** cached keys keep working; cold keys 503 after a 50 ms timeout and one retry; DNS shifts traffic to another region.
- **ID coordinator down:** no impact for hours; nodes refill at 10% remaining, so about 100K IDs spare.
- **Kafka down:** events spool to disk, redirects unaffected, analytics lag shown on dashboards.
- **Safe Browsing slow:** link created as PENDING_SCAN behind a warning interstitial until the async scan clears it.
- **Bad redirect deploy:** 1% canary with automatic rollback on 5xx or p99 regression.

**Trade-offs chosen:**
- **Range counter plus permutation over hashing or random keys:** no collisions by construction, 7 characters, not guessable.
- **302 over 301:** analytics and takedowns need every click; costs one origin hit per click.
- **DynamoDB global tables over SQL or Redis-only:** point lookups only, auto-partitioning, multi-region; Redis alone risks durability.
- **New key per create over dedupe:** separate analytics per campaign; dedupe would leak who shortened what.
- **Async Kafka analytics over synchronous counting:** redirect latency independent of analytics, with replay.
- **Edge caching hot keys for 60 s:** absorbs spikes while bounding takedown staleness; slight undercount, merged from edge logs.

**What to measure:** redirect p50/p99 per region (p99 under 20 ms at origin), hit ratio per cache tier and DB read QPS, status mix (302/404/410/5xx) and 404 rate per IP prefix, create errors and Safe Browsing timeouts, ID blocks remaining, click buffer and dropped events, Kafka lag and analytics freshness, takedown propagation time.

## Page 5. Say it in the interview

> "I assume 100 million new links a month and 100 reads per write: about 40 thousand redirects a second at peak against 400 creates. So this is a read-heavy key-value problem and the redirect must come from cache. I use 302 redirects because click analytics is part of the product, and 7-character Base62 keys, 3.5 trillion combinations. Three paths. Create: validate, scan for malware, take an ID from a pre-allocated range, shuffle it so keys are not guessable, Base62-encode, conditional write. Redirect: edge, then Redis, then the database, answering in a few milliseconds. Analytics: an async click event to Kafka, aggregated by a stream job, never on the hot path. Then I defend key generation without a global lock, cache sizing, cache or Kafka failure, and global takedown in under a minute."

**Key points to land:**
- Read-heavy: 100:1, 40K redirects/s peak, so design the cache first.
- 7 Base62 characters = 3.5 trillion keys; we use 0.03% per year.
- Range-allocated counters: collision-free, one coordinator call per million; permute to stop enumeration.
- 302 not 301: analytics and takedowns need every click to reach us.
- The redirect service is separate, tiny and boring.
- Analytics is async through Kafka and never blocks a redirect.
- Three cache tiers plus negative caching and singleflight handle viral keys and scanners.
- Conditional writes arbitrate custom alias races.
- Abuse is first class: scan on create, rescan, global takedown in under 60 s.
- Active-active reads in every region; region-partitioned ID ranges avoid write conflicts.

**Likely follow-ups:**
1. **Without any coordinator?** Give each node a static worker id plus a local counter, or use random keys with a conditional put and retry; at 0.03% fill a year, retries are negligible.
2. **Why not run redirects at the edge?** A valid next step (edge workers with KV), at the cost of seconds of propagation, lock-in and edge-log analytics; start at origin plus CDN.
3. **Analytics for a link with 1B clicks?** Dashboards read per-minute and per-hour rollups, so a billion clicks is a few hundred thousand rows.
4. **Owner changes the destination?** Update the row, rescan, invalidate every cache tier, keep version history; with 302 browsers see it immediately.
5. **Phishing that Safe Browsing misses?** Score signals (new account, newly registered domains, lookalike brands, sudden email-referrer spikes), send suspects to an interstitial, accept user reports.

**Director layer:**
- **Cost drivers:** the 2 TB/month click stream and its OLAP store dominate; the target is under 0.05 USD of infra per million redirects so a free tier stays sustainable.
- **Phasing:** core create and redirect with cache first; then analytics, then custom domains and vanity aliases for paying customers.
- **Ownership:** redirect and edge, link platform and IDs, analytics pipeline, trust and safety.
- **Top risks:** our domain blocklisted for spam, enumeration of private links, analytics loss undermining the paid tier, a viral hot key, EU data residency for analytics.
