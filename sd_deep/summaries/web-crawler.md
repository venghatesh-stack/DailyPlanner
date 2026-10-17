# Design a Web Crawler (search-engine scale): the 5-page summary

A crawler looks like a BFS over links, but at billions of pages it becomes a scheduling problem: keep thousands of fetchers busy without ever hammering one host, never fetch the same thing twice, and spend the crawl budget on the pages that matter. The single most important idea: the URL frontier is the brain, with priority queues in front, one-host-per-queue politeness queues behind, and everything partitioned by host so politeness and dedup stay local to one node.

## Page 1. The problem, scope and numbers

**Pitch:** discover and refresh billions of pages efficiently for the search indexer, while being a good citizen to every site owner.

**Who uses it:** the indexer pipeline (fetched documents and outlinks), crawl operators (pause hosts, set priorities, inject seeds) and webmasters (rate control via robots.txt).

**In scope:**
- **Discover:** seeds and sitemaps; new URLs from fetched pages.
- **Robots.txt:** fetched per host, cached 24 h, every URL filtered before fetch.
- **Politeness:** one connection per host, at least 1 s between requests, honour crawl-delay, back off on 429/503.
- **Normalise and dedup:** canonical URLs (strip fragments and session IDs); skip seen URLs and seen content (exact and near-duplicate).
- **Prioritise and re-crawl** by importance and change rate.
- **Store and emit:** compressed raw pages plus a document event for indexers.

**Out of scope:** indexing and ranking, login-gated pages, image and video analysis, universal JavaScript rendering, sub-minute freshness.

**Non-functional targets:**
- **Throughput:** about 400 pages/s at launch, 2,000/s at target, peak 2x; linear scale by adding nodes, no global lock.
- **Politeness:** never more than 1 in-flight request per host; zero robots.txt violations.
- **Freshness:** tier-1 pages (news, popular home pages) p90 under 4 hours.
- **Robustness:** a node loss costs under 10 minutes of work; tolerant of malformed HTML and slow servers.
- **Durability:** raw content 3x replicated or erasure coded. Duplicates under 5% of stored pages.

**Capacity math (1B pages/month at launch, 5B at target, 500 KB per page, 100 KB compressed):**
- **QPS:** 1e9 / 2.6M s = about 385 pages/s, peak about 800; at 5B, about 1,930/s.
- **Bandwidth:** 385 x 500 KB = about 190 MB/s, 1.5 Gbps at launch; 7.7 Gbps at target. Real, but not the limit.
- **Storage:** 1e9 x 100 KB = 100 TB/month; 5 cycles of retention = 500 TB before replication. So a blob store with large segment files.
- **URL-seen set:** 10B URLs x 8 B = 80 GB exact; a Bloom filter at 1% false positives needs 9.6 bits each = 12 GB. So shard it and keep the filter in RAM.
- **Links:** 385 x 50 outlinks = 19,000 URLs/s into dedup, about 3,800/s new into the frontier. So the frontier must live mostly on disk.
- **Concurrency:** 1.5 s per fetch means about 600 fetches in flight: 20 nodes with async I/O. So the limit is per-host politeness, not bandwidth or CPU.

## Page 2. The architecture

```
 Seeds / sitemaps / re-crawl scheduler
        |
        v
 +--------------- Crawler node (owns hosts by hash(host)) ---------------+
 | Prioritizer -> front queues F1..Fk -> biased selector                 |
 |   -> back queues B1..Bn (one host each) + min-heap(next_fetch_time)   |
 |   -> async fetchers -> DNS cache -> robots cache                      |
 |   -> content-seen (SHA-256, SimHash) -> parser -> URL filter          |
 +-----------|---------------------------------------------|-------------+
             v                                             v
   Blob store (WARC segments)            URL-seen (Bloom + KV) -> route new
             |                           URLs by hash(host) to owner node
             v                                             |
   Kafka crawl.documents -> indexers     URL metadata DB (Bigtable/HBase)
 Coordinator (ZooKeeper/etcd): membership, host ranges, operator controls
```

- **URL frontier:** front queues hold priority; back queues hold one host each; a heap picks the next ready host.
- **Fetchers:** async HTTP; connect 5 s, total 30 s, max 10 MB, at most 5 redirects.
- **DNS cache:** caching resolver; each lookup costs 10-100 ms, a classic crawler bottleneck.
- **Robots cache:** parsed rules and crawl-delay per host, 24 h TTL.
- **Content-seen service:** SHA-256 for exact copies, 64-bit SimHash for near copies.
- **Parser and URL filter:** extracts and normalises links; drops traps, blocked domains, seen URLs.
- **Blob store:** compressed raw pages in WARC-like segments of about 1 GB.
- **URL metadata DB:** last fetch, status, hashes, change history, priority; drives re-crawl.
- **Re-crawl scheduler and coordinator:** freshness scheduling; membership and host assignment.

**Flow A: fetch and expand**
1. Pop host H from the heap when next_fetch_time is due; take the head URL of B(H); check robots.
2. Resolve via the DNS cache and fetch. Set next_fetch_time(H) = now + max(crawl_delay, k x response time).
3. Checksum and SimHash: a duplicate is recorded as an alias and stops here.
4. Store the body, update metadata, publish to Kafka; route new links by hash(host) to their owner.

**Flow B: re-crawl**
1. Scan metadata for due URLs; priority = importance x probability changed.
2. Fetch with If-Modified-Since / If-None-Match. A 304 lengthens the interval; a change shortens it.

## Page 3. The core deep dives

### 1. The frontier and politeness (Mercator)
Front queues F1..Fk sort URLs by priority. Each back queue holds URLs of exactly one host. A min-heap keyed by each back queue's next allowed fetch time lets a fetcher block until the soonest host is ready. When a back queue empties, the selector pulls from front queues (biased to high priority) until it finds a URL whose host has no back queue, and assigns it. Keep about 3x as many back queues as fetcher threads. Crawl-delay, 429/503 backoff and operator throttles all feed the same next_fetch_time, so politeness is enforced in exactly one place. Only queue heads and tails are in memory; the middle lives on disk.

### 2. Two dedup layers
URL-seen: each node keeps a Bloom filter (a compact bit array that says "definitely new" or "probably seen") for URLs of its hosts, backed by an exact fingerprint store in RocksDB. It cuts 19,000 extracted links/s to about 3,800 new ones. A 1% false positive skips a genuinely new URL, which sitemaps and re-discovery usually recover. Content-seen: SimHash hashes weighted shingles to 64 bits, adds or subtracts each feature's weight per bit, and keeps the sign. Similar pages differ in few bits; within 3 bits counts as a near-duplicate. Four permuted tables of 16-bit blocks find neighbours fast, because any match within 3 bits shares at least one exact block. A near-duplicate is stored as an alias, not a copy.

### 3. Freshness as scheduling
Page changes are modelled as a Poisson process with rate lambda from history. The chance a page changed since the last fetch is 1 - exp(-lambda x t). Multiply by importance (link score, traffic) and spend the budget on the highest values. Example: Shreya's news home page changes hourly and matters a lot, so it is checked within hours; Sethu's static blog is checked rarely, and most checks return a cheap 304.

### 4. Spider traps
Infinite calendars (/cal?month=2026-11, 2026-12...) and loops (/a/b/a/b) are inevitable. Cap depth and pages per host per cycle (for example 100k), cap URL length at 2,048, detect repeating path segments, strip session params (sid, jsessionid, utm_*).

**Data model:**
- **UrlMeta** (Bigtable/HBase): row key reversed host + path (com.example.www/path) so a site's URLs are contiguous; url_hash, last fetch, status, content hash, SimHash, change count, importance, next_due_ts.
- **Frontier segments** (local append-only files): url, priority, enqueue time, depth.
- **RobotsEntry** (Redis or in-process LRU): compiled rules, crawl-delay, 24 h TTL.
- **Raw page** (S3/GCS/HDFS, WARC segments): index (url_hash, fetch_ts) to segment offset.
- **ContentFingerprint** (RocksDB per node): fingerprint, first url_hash, seen count.

**Key APIs:**
- `POST /v1/seeds`: normalised and routed to the owning node.
- `PUT /v1/hosts/{host}/policy`: throttle or pause a host instantly.
- `DELETE /v1/urls/{url_hash}`: purge copies and block the URL for good.
- `RPC Frontier.EnqueueBatch`: node-to-node URL handoff, every 100 ms or 1,000 URLs.
- `kafka crawl.documents`: keyed by url_hash, consumed by indexers.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Politeness, not bandwidth:** keep many hosts in flight; throughput comes from parallelism across hosts, never from one host harder.
- **Nodes:** shared-nothing by host partition, so add nodes; the frontier is per node and scales linearly.
- **DNS:** caching resolver with a 5-minute TTL floor and serve-stale.
- **Shared IPs and wildcard subdomains:** add per-IP and per-domain caps on top of per-host limits.
- **Huge hosts (wikipedia.org):** per-host queue caps, prioritise inside the host; others keep fetchers busy.
- **Watch:** cross-node handoff bandwidth, and grow the metadata and blob clusters.

**Failure modes:**
- **Crawler node dies:** coordinator reassigns its ring ranges in about 10 s; neighbours load its frontier checkpoint; a few minutes of URLs are re-fetched and deduped.
- **Blob store slow:** fetchers buffer to local disk and pause new fetches at 80% full: backpressure, not data loss.
- **Kafka down:** events buffer locally with the blob reference; crawling continues; indexers catch up.
- **DNS failure:** serve stale entries; failed lookups go to a retry queue; alert under 98% success.
- **Bug hammers a host:** a hard per-host ceiling in the fetcher, independent of the frontier, plus kill switches.
- **Coordinator loses quorum:** nodes keep current assignments and keep crawling; no rebalancing.
- **robots.txt returns 5xx:** treat as full disallow and retry later; never crawl on a robots error.

**Trade-offs chosen:**
- **Priority-driven over plain BFS:** BFS wastes budget on junk; explicit priority spends it where it matters.
- **Partition by hash(host):** keeps politeness node-local; per-domain and per-IP caps stop subdomain abuse.
- **Bloom filter plus exact store:** memory-efficient negative check; a rare false positive costs little.
- **Raw compressed HTML, 5 cycles:** indexers and ML reprocess without re-crawling; 100 KB/page is affordable.
- **JS rendering only for an allowlist:** rendering costs 10-100x more CPU per page.
- **Continuous over batch (Nutch-style):** batch cycles add hours to freshness.
- **At-least-once everywhere:** indexers upsert by (url_hash, content_hash), so a re-fetch is harmless.

**What to measure:** pages and bytes/s per node; status mix per tier; robots violations (must be 0); frontier size, per-host queue depth and fetcher idle time; duplicate rate; freshness lag p50/p90 per tier and 304 share; DNS hit rate; indexer Kafka lag.

## Page 5. Say it in the interview

> "I assume a search-engine crawler doing about a billion pages a month, HTML first, obeying robots.txt. The naive design is a BFS loop with a queue and a visited set, and it fails three ways: it hammers individual hosts, the visited set does not fit in memory, and it spends effort on junk. So the heart of my design is the URL frontier: front queues ordered by priority, back queues that each hold one host, and a heap of next-allowed fetch times, so we stay polite while thousands of hosts are in flight. Around it: async fetchers with a DNS cache, a blob store for raw pages, a Bloom filter for seen URLs and a fingerprint check for seen content. I partition everything by host hash so politeness and dedup are node-local. Then I defend traps, near-duplicates, freshness and node failure, with robots violations as a hard zero."

**Key points to land:**
- The frontier is the brain: priority front queues, one-host back queues, a heap of next-allowed times.
- Throughput comes from parallelism across hosts, never from hitting one host harder.
- Partition by host so politeness and dedup are local; consistent hashing for membership.
- Two dedup layers: URL-seen (Bloom filter) and content-seen (checksum plus SimHash).
- About 400 pages/s and 1.5 Gbps per billion pages a month; 100 TB compressed a month.
- Traps are inevitable: cap depth, URL length, pages per host; strip session params.
- Freshness is scheduling: importance x probability changed; conditional GETs make re-checks cheap.
- At-least-once with idempotent consumers; re-fetching a page is cheap.
- Robots violations are a hard zero; a robots fetch error means do not crawl.

**Likely follow-ups:**
1. **JavaScript-heavy apps?** A separate headless Chromium tier for an allowlist of hosts at a lower rate, caching shared JS and CSS; promote hosts whose HTML lacks content.
2. **Geo-distributed?** Crawler pools in several regions, each host assigned to the nearest region, still one owner per host for politeness.
3. **A webmaster says we took their site down?** Check per-host logs: likely many subdomains on one IP or an ignored crawl-delay. Add per-IP caps, adaptive delay on rising latency and a self-serve rate control.
4. **Priority for a brand-new URL?** Use discovery signals: the linking page's importance, number of linking hosts, sitemap presence, URL depth and the host's quality.
5. **Legal takedowns?** Purge blob copies and metadata, add the pattern to the URL filter's block list, emit a delete event for indexers.

**Director layer:**
- **Cost drivers:** 500 TB of retained raw pages (before replication), 1.5-7.7 Gbps of paid bandwidth, and the rendering tier; cost per million pages is tracked and must trend down.
- **Phasing:** launch at 1B pages/month on about 20 nodes, scale linearly to 5B by adding nodes; JS rendering stays an allowlist.
- **Ownership:** frontier and fetch, dedup and content, freshness scheduling, storage and indexer feed, webmaster relations.
- **Top risks:** overloading a small site, spider traps burning budget, unbounded storage cost, crawler IPs blocklisted.
