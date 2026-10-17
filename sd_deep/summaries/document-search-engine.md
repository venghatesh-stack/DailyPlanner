# Design a Document Search Engine (full-text search): the 5-page summary

A document search engine turns a billion documents into an inverted index and answers keyword queries in tens of milliseconds by scatter-gathering over 256 shards and ranking with BM25. The single most important idea: writes flow asynchronously into immutable, compressed index segments that are cheap to read but expensive to change, so the design is really about the indexing pipeline, segment merging and the tail latency of a fan-out query.

## Page 1. The problem, scope and numbers

**Pitch:** documents are scattered across wikis, file shares and ticket systems, and today's database LIKE search takes seconds, has no ranking and times out on big tenants. Build one search API that returns the most relevant permitted documents in under 300 ms.

**Who uses it:** knowledge workers (right doc in one query), support agents (exact error-message search on a call), relevance engineers (synonyms, boosts, A/B tests), tenant admins (restricted docs never leak).

**In scope:**
- **Indexing:** create, update, delete via API and change events; extract text from HTML, PDF, DOCX.
- **Search:** keywords, boolean operators, "phrase" queries, field boosts (title over body).
- **Filters and facets:** author, type, tags, date ranges; facet counts on type and author.
- **Ranking:** BM25 plus recency and popularity, with a pluggable rescoring phase.
- **Snippets and paging:** highlighted terms, stable page tokens.
- **Per-document ACLs at query time**, spell correction and fuzzy match up to edit distance 2.

**Out of scope:** web crawling and PageRank, semantic/vector retrieval (phase 2), OCR beyond normal extraction, cross-tenant search, generative answers.

**Non-functional targets:**
- **Latency:** search p50 under 80 ms, p99 under 300 ms; get-document p99 under 50 ms.
- **Freshness:** p95 under 5 s from write to searchable; ACL changes under 1 s.
- **Availability:** 99.95% for search; indexing may degrade but never loses writes.
- **Durability:** source of truth in the object store (11 nines); the index is always rebuildable.
- **Consistency:** eventual for content; read-your-writes for the author on request.
- **Security:** zero ACL leaks, tenant isolation in every query.

**Capacity math (1B docs, 5M changes/day, 50M searches/day):**
- **Text:** 1B x 20 KB = 20 TB. Index with positions is about half that: 10 TB per copy, 30 TB with 2 replicas.
- **Shards:** 10 TB / 40 GB per shard = 250, so 256 primaries (a power of two allows clean splits), about 4M docs each.
- **Search:** 50M / 86,400 = 580 QPS average, x5 = 3,000 QPS peak. Each query hits all 256 shards: 768,000 shard-queries/s. So fan-out, not data size, drives node count and tail latency (plan: about 150 nodes).
- **Indexing:** 5M / 86,400 = 58 docs/s, about 400/s at a 7x peak, only 8 MB/s. Light, but merges rewrite data 5-10x, so throttle merges.
- **Memory:** 64 GB nodes, 31 GB heap, the rest for the OS page cache that holds term dictionaries and hot postings.

## Page 2. The architecture

```
 Clients
    |
    v
 API Gateway --auth--> Identity/ACL svc (user -> groups, cached 60 s)
    |  search                        | write
    v                                v
 Query svc (parse, ACL filter,    Document svc --tx--> Metadata DB + Outbox
  synonyms, Redis result cache)      |                       |
    |                                v                       v
    v                          Object store (raw)    Outbox relay -> Kafka
 Coordinator --scatter--> Shard 0 .. Shard 255             |
  merge top-k, fetch       (primary + 2 replicas) <-- Indexer workers
  snippets                         ^                (extract, analyze, bulk)
                     Cluster manager (shard map, health, alias)
 Click logs -> Analytics / relevance training -> ranking config
```

- **API Gateway:** TLS, auth, per-tenant rate limits, routing.
- **Document service:** CRUD; metadata row and outbox row in one transaction.
- **Outbox relay + Kafka:** change events keyed by doc_id, at-least-once, 7-day replay.
- **Indexer workers:** extract, analyze, bulk index with external versions; DLQ for poison docs.
- **Index cluster:** Lucene-style segments per shard; primary replicates to 2 replicas.
- **Cluster manager:** elected master (quorum of 3) owns shard map and index aliases.
- **Query service and coordinator:** rewrite, ACL filter, scatter-gather with hedging, merge, rescore.
- **Identity/ACL service:** resolves a user to group ids for the query filter.
- **Result cache:** Redis, first page only, key includes ACL hash, TTL 30 s.

**Flow A: index a document**
1. Document service stores the file, writes metadata (version 1) and an outbox row in one transaction.
2. Relay publishes {doc_id, version, upsert} to Kafka partition hash(doc_id).
3. Indexer extracts text, builds the index doc with acl_principals, sends it to shard hash(doc_id) mod 256 with external version 1.
4. Primary writes buffer plus translog, replicates, acks; a refresh within 1 s makes it searchable.

**Flow B: search**
1. Check cache, resolve groups, build query: match title^2 and body, filter tenant, type, acl_principals.
2. Scatter to one copy of each shard (150 ms timeout, hedge at about 60 ms); each returns its top 20 by BM25.
3. Merge 256 x 20 with a heap, rescore the top 200, fetch snippets for the 10 shown.

## Page 3. The core deep dives

### 1. Inverted index, BM25 and fast intersection
For each term the index stores a posting list: sorted doc ids with positions, compressed in blocks. An AND query walks the rarest list first and uses skip pointers (about every 128 docs) to jump in the longer lists, so cost tracks the rarest term. WAND and block-max skip blocks that cannot beat the current top 20. BM25 scores each term by IDF (rare terms matter more) times a saturating term frequency (k1 = 1.2) normalised by document length (b = 0.75): writing "revenue" 50 times does not give 50x the score.

### 2. Near-real-time writes: buffer, translog, segments, merges
New docs go to an in-memory buffer plus a translog for durability. Every 1 s a refresh writes a small immutable segment and opens a new searcher: that is why search is "near real time". Updates and deletes never edit a segment; they mark the old doc in a live-docs bitset and add a new version. Tiered merging combines small segments and purges deletes, at the cost of IO. Refresh is 1 s live and 30 s during backfills.

### 3. Exactly-once effect on an at-least-once pipeline
The outbox fixes the dual-write problem: DB row and event commit together. Kafka can redeliver, so each index write carries the source version and the shard rejects version <= current. Example: Shreya deletes doc D (version 3); a replayed upsert of version 2 arrives later and is skipped, so D is not resurrected.

### 4. Permissions without leaks
ACLs are indexed as acl_principals and applied as a filter inside the shard query, never a post-filter (which breaks pagination and counts). Revokes go on a separate high-priority topic and force a refresh. Defence in depth: cache keys include the ACL hash, and the 10 shown docs are rechecked against the source of truth.

**Data model:**
- **Document metadata** (PostgreSQL, sharded by tenant_id): PK (tenant_id, doc_id); version, acl_principals.
- **Outbox** (same DB): id, doc_id, version, op, priority; deleted after 24 h.
- **Raw file** (object store): key tenant/doc_id/version, immutable for replays.
- **Index document:** routed by hash(doc_id) to 256 shards; alias docs_current -> docs_v7.
- **Query log** (Kafka -> data lake): partitioned by date, user hashed.

**Key APIs:**
- `POST /v1/documents`: Idempotency-Key header; files over 5 MB via presigned URL.
- `PUT /v1/documents/{doc_id}`: optimistic concurrency, bumps version.
- `DELETE /v1/documents/{doc_id}`: soft delete plus versioned tombstone.
- `GET /v1/search`: page token = point-in-time id + search_after; capped at 1,000 results.
- `POST /v1/admin/synonyms`: search-time synonyms, no reindex.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Fan-out tail:** with a 100 ms shard p99 and 100 shards, 63% of queries hit a slow one. Fix with hedging (about 5% extra load), adaptive replica selection, per-hop deadlines and partial results.
- **Big tenants:** a 200M-doc tenant gets a dedicated index; small tenants share one filtered by tenant_id.
- **Merges and backfills:** throttle merges; run bulk reindex on a separate low-priority topic with 30 s refresh.
- **Cost:** hot-warm tiers, drop positions on fields rarely phrase-searched, best_compression for stored fields.

**Failure modes:**
- **Data node crash:** reads go to replicas; an in-sync replica is promoted; translog means no acked write is lost.
- **Zone lost:** zone-aware allocation keeps 2 of 3 copies; shed load and lean on cache while replicas rebuild.
- **Kafka or indexers down:** writes still land in DB and outbox; search is slightly stale; indexers catch up from offsets.
- **Master quorum lost:** no allocation or mapping changes, but shards keep serving.
- **Bad analyzer or mapping:** only via a new index version and alias swap; roll back by moving the alias (old version kept 7 days).
- **Merge storm or GC pause:** hedging routes around it; partial=true if deadlines pass.
- **Redis down:** bypass the cache; capacity is planned assuming a 0% hit rate at peak.
- **Poison doc or zip bomb:** sandboxed extraction, 1 MB text cap, bounded retries, then DLQ.

**Trade-offs chosen:**
- **Elasticsearch/OpenSearch over custom Lucene:** sharding, replication and NRT come free.
- **Document partitioning over term partitioning:** even load and local intersections; fan-out is managed with replicas and hedging.
- **ACL pre-filter over post-filter:** correct pages and counts, cheap with cached filters.
- **Async outbox over indexing inside the request:** writes stay up when search is degraded, and replay enables rebuilds.
- **search_after + PIT over offset paging:** constant cost per page, stable across refreshes.

**What to measure:** p50/p95/p99 end to end and per shard, partial-result rate, indexing lag p95 and Kafka lag, zero-result rate (under 8%), top-3 click-through (over 45%), NDCG@10 per release, merge backlog and GC, DLQ size, sampled ACL audit (must be 0 mismatches).

## Page 5. Say it in the interview

> "I will assume internal document search: a billion documents of about 20 KB, five million changes a day, 3,000 QPS at peak, p99 under 300 ms, new content searchable in seconds, and strict per-document permissions. The heart is an inverted index, term to a compressed posting list, scored with BM25. Writes go to the document store with an outbox event in the same transaction; Kafka feeds indexers that extract, analyze and write into 256 shards hashed by document id, each with two replicas and a one-second refresh. Queries get a tenant and ACL filter, scatter to one copy of every shard, merge the local top-k, rescore and fetch snippets. Tail latency is the main enemy, so I use hedging, deadlines and partial results, and every schema change is a new index plus an alias swap."

**Key points to land:**
- Inverted index: term to sorted, compressed posting list with positions.
- BM25 with field boosts for recall; rescore the top 200 with richer signals.
- Document-partitioned shards, hash(doc_id), query-then-fetch.
- Near real time: buffer plus translog, 1 s refresh, immutable segments, background merges.
- Async write path: outbox, Kafka keyed by doc_id, versioned idempotent writes.
- The index is rebuildable: new version plus alias swap.
- Fan-out tail latency: replicas, hedging, deadlines, partial results.
- ACLs are filters inside the query; cache keys include the ACL hash.
- 20 TB text, 10 TB index per copy, 256 shards, about 150 nodes.
- Measure relevance (NDCG, CTR, zero-result rate) as seriously as latency.

**Likely follow-ups:**
1. **How do you add semantic search?** Embed document chunks into an HNSW index, run BM25 and vector retrieval in parallel, fuse with reciprocal rank fusion, then rescore; BM25 still wins on error codes.
2. **Strict read-after-write for everyone?** Refreshing on every write destroys throughput; give the author refresh=wait_for and keep eventual consistency for others.
3. **Autocomplete on titles?** A separate in-memory completion index (edge n-grams or FST) with p99 under 50 ms, off the BM25 path.
4. **GDPR right to delete?** Highest-version delete event, tombstone, purge via merges within the SLA, delete from object store and logs, verify by audit query.
5. **Ship a ranking change safely?** Offline NDCG on judged queries, then interleaving or A/B on a small slice with latency and zero-result guardrails, then ramp.

**Director layer:**
- **Cost drivers:** roughly 150 search nodes in year one, set by fan-out QPS rather than storage; replicas triple the index; caching and hot-warm tiers are the levers.
- **Phasing:** keyword search with ACLs first; vector hybrid retrieval and learning-to-rank in phase 2.
- **Constraints:** reuse the existing object store and metadata DB as the source of truth; Indian tenants' indexes stay in Indian regions.
- **Top risks:** permission leaks via caches or snippets, poor relevance driving users away, multi-day billion-doc reindexes (parallel backfill, alias swap, throttling), and hot tenants overloading shared shards.
