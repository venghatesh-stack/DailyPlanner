# Document Search Engine (full-text search): recall card

> **Hook:** Outbox to Kafka → Index into 256 shards → Refresh every second → Scatter with ACL filter → Merge top-k and rescore

**P · Problem:** It's really an inverted-index scatter-gather problem, dominated by the indexing pipeline and fan-out tail latency.

**N · Numbers:**
1. 10 TB of index per copy / 40 GB per shard is 250, so 256 primary shards of about 4M docs each.
2. 3,000 QPS x 256 shards is 768,000 shard-queries/s, so fan-out, not data size, drives node count and tail latency.
3. Only about 400 docs/s at peak, but merges rewrite data 5-10x, so throttle merges.

**H · Hard part:** Keeping p99 under 300 ms when every query hits 256 shards, without ever leaking a document the user cannot see.

**B · Boxes:** `API Gateway → Query service → Coordinator → 256 shards → Merge and rescore`

Side path: `Document service → Outbox → Kafka → Indexer workers → shards` for writes.

**D · Decisions:**
1. Document partitioning over term partitioning, because load is even and intersections stay local.
2. ACL pre-filter over post-filter, because pages and counts stay correct.
3. Async outbox over indexing inside the request, because writes stay up when search degrades and replay enables rebuilds.

**F · Failures:**
1. Kafka or indexers down → writes still land in the DB and outbox; search is slightly stale and catches up from offsets.
2. Merge storm or GC pause on a shard → hedging routes around it; partial results if deadlines pass.

**C · Close:** "So this is an inverted index with BM25 over a billion documents. Writes go to the document store with an outbox event, and Kafka feeds indexers that write into 256 shards with two replicas and a one-second refresh. Queries carry a tenant and ACL filter, scatter to one copy of each shard, merge the top-k, rescore and fetch snippets. Tail latency is the enemy, so I hedge and use deadlines. Next I would add hybrid vector retrieval."

**Quiz yourself:**
1. Why is search only near real time? → A refresh writes a new immutable segment every second.
2. How is a replayed old upsert stopped? → Each write carries the source version; the shard rejects older ones.
3. How do you change an analyzer? → Build a new index version and swap the alias.
