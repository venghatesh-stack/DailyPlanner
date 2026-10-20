# Web Crawler (search-engine scale): recall card

> **Hook:** Prioritise → One host per back queue → Wait for next fetch time → Fetch → Dedup URL and content → Route links by host

**P · Problem:** It's really a scheduling problem: keep thousands of fetches busy without ever hammering one host or fetching anything twice.

**N · Numbers:**
1. About 385 pages/s at 1.5 s per fetch is about 600 in flight, so the limit is per-host politeness, not bandwidth or CPU.
2. 10B URLs exact is 80 GB, a 1% Bloom filter is 12 GB, so shard it and keep the filter in RAM.
3. 19,000 extracted links/s become about 3,800 new URLs/s, so the frontier lives mostly on disk.

**H · Hard part:** Staying polite while thousands of hosts are in flight, and spending the crawl budget on pages that matter rather than traps and duplicates.

**B · Boxes:** `Prioritizer → Front queues → Back queues + heap → Async fetchers → Content-seen → Parser`

Side path: `Fetched page → Blob store (WARC) → Kafka crawl.documents → indexers`.

**D · Decisions:**
1. Priority-driven over plain BFS, because BFS wastes budget on junk.
2. Partition by hash(host) over a shared frontier, because politeness and dedup stay node-local.
3. Bloom filter plus exact store over exact sets in RAM, because it is memory-efficient and a rare false positive costs little.

**F · Failures:**
1. Crawler node dies → coordinator reassigns its ranges in about 10 s; neighbours load its frontier checkpoint.
2. robots.txt returns 5xx → treat it as full disallow and retry later; never crawl on a robots error.

**C · Close:** "The naive BFS loop hammers hosts, outgrows memory and wastes effort on junk. So the heart is the URL frontier: priority front queues, back queues that each hold one host, and a heap of next-allowed fetch times. Around it are async fetchers with a DNS cache, a blob store, a Bloom filter for seen URLs and SimHash for seen content. Everything is partitioned by host hash, and robots violations are a hard zero."

**Quiz yourself:**
1. How do you decide what to re-crawl? → Importance times the chance it changed, 1 - exp(-lambda x t).
2. How do you catch near-duplicates? → 64-bit SimHash; within 3 bits is a near-duplicate.
3. How do you escape spider traps? → Cap depth, URL length and pages per host; strip session params.
