# System Design in 5 Pages

What to say to the interviewer, distilled from the 128 entries in the System design bank and the 70 deep-dive designs. Read it the night before; say it out loud once.

## Page 1. Run the interview, don't just answer it

**The 45-minute shape.** Spend the first 5 minutes on scope and numbers, 10 on the high-level design, 20 going deep on the two or three hardest parts, and the last 5 on trade-offs and what you would do next. Say the plan out loud at the start; it shows you lead the conversation.

1. **Clarify (3-5 min).** Who uses it, the 3-5 core features, what is out of scope. Ask the questions that change the design: read/write ratio, latency target, consistency needs (is stale data OK?), scale, single or multi-region. State assumptions and move on.
2. **Estimate (2-3 min).** Requests per second, storage, bandwidth. Then say what the numbers force: "read-heavy, so cache and CDN", or "1M writes/s, so shard and stream".
3. **API and data model (5 min).** Three to five endpoints. The main entities and the one access pattern that dominates; that pattern decides the database and the partition key.
4. **High-level design (10 min).** Client → CDN → load balancer → stateless services → cache → database, plus a queue for anything slow. Draw both the write path and the read path.
5. **Deep dive (15-20 min).** Pick the hardest parts yourself: the hot path, the contention point, the failure that loses money or data. Go deep on those, not on everything.
6. **Wrap up (3-5 min).** Bottlenecks, failure modes, how you would monitor it, what changes at 10x.

**Rules of thumb for estimation**

- **Time:** 1 day ≈ 86,400 s ≈ 10⁵ s. So 1M requests/day ≈ 12/s; 100M/day ≈ 1,200/s; peak is about 2-3x average (10x for a sale).
- **Latency:** memory read ~100 ns; SSD read ~100 µs; same-datacentre round trip ~0.5 ms; cross-continent ~150 ms. Disk and network, not CPU, are what you design around.
- **Capacity (order of magnitude):** a stateless app server handles a few thousand requests/s; one Redis node ~100k ops/s; a well-tuned Postgres primary ~5-10k writes/s; one Kafka partition ~10 MB/s.
- **Storage:** records × size × retention × replication factor (usually 3). Then ask: does the hot set fit in memory? If yes, cache it.
- **Availability:** 99.9% ≈ 43 min down a month; 99.99% ≈ 4.3 min. Chained dependencies multiply: three 99.9% services in a row give ~99.7%.

**Director-level framing (say this early).** Name the business goal and the metric that proves success (orders/minute, p99 latency, cost per order). Name the riskiest assumption. Say you will build the simplest thing that meets the numbers and show where it evolves.

## Page 2. The building blocks: when, why and the catch

- **Load balancer.** Spreads traffic over stateless servers and removes unhealthy ones. L4 is fast; L7 can route by path or header. Algorithms: round robin, least connections, consistent hashing for sticky data. Catch: it can become the single point of failure, so run a pair.
- **Cache.** Cache-aside is the default: read cache, on a miss read the DB and fill. Write-through keeps them in sync at higher write cost; write-back is fast but can lose data. Always set a TTL. Catches: invalidation (delete on write), stampede on a hot key's expiry (single-flight or early refresh), and stale reads.
- **CDN.** Serves static files and media from the edge; also caches API responses that are the same for everyone. Version the URLs instead of purging. Catch: personalised or private data must not be cached at the edge.
- **Queue / stream.** A queue (SQS, RabbitMQ) hands out work and deletes it when done. A log stream (Kafka) keeps messages so many consumers can read and replay them. Use them to absorb spikes, decouple services and do slow work asynchronously. Catch: at-least-once delivery, so consumers must be idempotent; order is kept only per partition, by key.
- **SQL vs NoSQL vs NewSQL.** SQL for transactions, joins and money. Key-value or wide-column (DynamoDB, Cassandra) for huge scale with simple access by key. Document stores for flexible shapes. Distributed SQL (Spanner, CockroachDB, TiDB) when you need both scale and transactions. Choose by the access pattern, not by fashion.
- **Indexes.** B-tree for lookups and ranges; each index slows writes. Inverted index (Elasticsearch) for full-text search; geo index (geohash, H3, quadtree) for "nearby"; vector index (HNSW) for similarity search.
- **Replication.** Copies for reads and failover. Leader-follower is simplest, with replication lag (read-your-writes needs routing to the leader or a version check). Multi-leader and leaderless allow writes everywhere but create conflicts to resolve.
- **Sharding.** Split data by a partition key so it scales past one machine. Hash for even spread; range for range scans (but hot spots). Pick the key that keeps one request on one shard. Catches: cross-shard queries, hot keys, re-sharding (use consistent hashing or many virtual shards).
- **Consistency and CAP.** When the network splits you choose: refuse (consistent, CP) or answer with possibly stale data (available, AP). Money, inventory and locks are CP; feeds, likes and presence are AP. Quorums: with N copies, if writes need W and reads need R, then W + R > N gives strong reads.
- **Unique IDs.** Snowflake-style: time + machine + counter, sortable, no coordination. Or hand out ID ranges in blocks. Avoid one auto-increment column at scale.
- **Rate limiting and API gateway.** Token bucket per user, IP or key, counted in Redis. The gateway also does authentication, routing, quotas and request IDs, and must not become a bottleneck or a single point of failure.
- **Blob storage.** Put files and media in object storage (S3) and only metadata in the database; upload directly with pre-signed URLs; serve through the CDN.

## Page 3. The pattern behind each family of problems

Most classic questions are one of these shapes. Name the shape, then say the one insight.

- **Read-heavy lookup (URL shortener, product catalog, profile).** Cache plus CDN in front of a key-value store; reads 100:1 over writes. Insight: generate keys without coordination (ID → base62) and serve the hot set from memory.
- **Write-heavy ingest (metrics, logs, ad clicks, counters, analytics).** Append to Kafka, aggregate in a stream processor (Flink/Spark) in time windows, store rollups in a time-series or columnar store. Insight: never write each event to the main DB; pre-aggregate, and shard counters to avoid hot keys.
- **Fan-out (news feed, timeline, notifications).** Push to followers' inboxes on write for normal users; pull at read time for celebrities; merge the two. Insight: the hybrid avoids writing to 50M inboxes for one post.
- **Real-time connections (chat, presence, live updates, collaborative editing).** WebSocket gateways keep connections; a registry maps user to gateway; messages get per-conversation sequence numbers and are stored before delivery. Insight: ordering per conversation, offline catch-up from the last sequence, and client-generated IDs for de-duplication. Collaborative editing adds OT or CRDTs.
- **Geo and matching (Uber, food delivery, nearby search, maps).** Keep live locations in memory, indexed by geohash/H3 cells; search the cell and its neighbours. Maps use precomputed routing (contraction hierarchies) plus live traffic for ETAs. Insight: split the fast, approximate location plane (AP) from the transactional trip and payment plane (CP).
- **Contention and money (flash sale, ticket booking, inventory, wallet, payments, stock exchange).** Hold the scarce item with an atomic conditional update or a short reservation with expiry; take payment after the hold. Ledgers are double-entry and append-only; every request carries an idempotency key; reconcile with the bank daily. Insight: correctness first, then throughput (queue the crowd, gate with a counter in Redis, confirm in the database).
- **Search (autocomplete, product search, document search, web crawler).** Inverted index for text; a prefix trie or precomputed top-k per prefix for typeahead; ranking in stages (cheap recall, then a re-ranker). Crawlers need a URL frontier, politeness per host and de-duplication by content hash. Insight: build the index offline or near-real-time from a change stream, serve from replicas.
- **Infrastructure (key-value store, object storage, message queue, job scheduler, distributed lock, cache).** Partition with consistent hashing, replicate three ways, use quorums or a consensus log (Raft) for leaders and metadata. Locks need leases and fencing tokens. Schedulers claim jobs with leases and make jobs idempotent. Insight: say how it behaves when a node dies mid-operation.
- **Media (YouTube/Netflix, Instagram, Dropbox).** Upload to object storage, transcode asynchronously into renditions, serve chunked adaptive streaming (HLS/DASH) from the CDN. File sync splits files into content-hashed chunks so only changed chunks move. Insight: the database holds metadata only.
- **AI features (RAG, model serving, recommendations).** Retrieval (hybrid keyword + vector search) → re-rank → generate with citations; cache and route to small models to control cost; evaluate offline and monitor drift online. Recommendations: candidate generation, then ranking, then business rules.

## Page 4. Reliability, correctness, security, data

**Make it correct under failure**

- **Idempotency.** Every write that can be retried carries an idempotency key, stored with a unique constraint. This is what makes "exactly once" achievable in practice.
- **Timeouts, retries, circuit breakers.** Every call has a timeout; retry only idempotent calls, with exponential backoff and jitter, and a retry budget; open a circuit breaker when a dependency keeps failing; isolate pools (bulkheads) so one slow dependency can't drain everything.
- **Transactions across services.** Avoid 2PC. Use a saga (steps with compensating undo actions) and the transactional outbox (write the event in the same DB transaction, relay it to Kafka) so the database and the event never disagree.
- **Backpressure and graceful degradation.** Bound every queue; shed low-priority load first; serve cached or partial results (hide recommendations, keep checkout) instead of failing entirely.
- **Multi-region and disaster recovery.** State the RPO (how much data you can lose) and RTO (how long to recover). Active-passive is simpler; active-active needs conflict handling. Test failover, and keep backups you have restored at least once.

**Operate it**

- **Observability:** metrics (rate, errors, latency, saturation), structured logs with request IDs, distributed tracing across services.
- **SLOs and error budgets:** e.g. 99.9% of checkouts succeed within 500 ms; alert on burn rate, not on every blip.
- **Safe change:** feature flags, canary releases (1% → 10% → 100%) with automatic rollback on bad metrics, and backward-compatible schema changes (expand, migrate, contract).

**Secure it (one sentence each)**

- Authentication with OAuth2/OIDC and short-lived tokens; authorisation checked server-side on every request (RBAC or ABAC); least privilege everywhere.
- Encrypt in transit (TLS, mTLS inside) and at rest (KMS-managed keys); secrets in a vault, never in code.
- Rate limits, WAF and bot detection at the edge; validate input to stop injection; signed URLs for private media.
- Protect PII: minimise, mask in logs, honour deletion and retention rules, keep an audit log.

**The data platform behind the product**

- OLTP database for the app; change data capture (Debezium) streams changes to Kafka; a lake/lakehouse (Parquet + Iceberg/Delta) and a warehouse for analytics; batch for completeness, streaming for freshness.
- Model the warehouse with star schemas and slowly changing dimensions; put metric definitions in one semantic layer so dashboards agree.

## Page 5. Trade-offs, the leadership layer, and how to close

**Trade-offs to say out loud (and which way you lean)**

- **Consistency vs availability:** strong for money, inventory and identity; eventual for feeds, counts and search.
- **Latency vs freshness:** cache with a TTL and say how stale is acceptable.
- **Push vs pull:** push for most users, pull for heavy hitters.
- **SQL vs NoSQL:** start relational unless the access pattern or scale clearly says otherwise.
- **Sync vs async:** do only what the user must wait for synchronously; queue the rest.
- **Build vs buy:** buy commodity (queues, search, auth, observability); build what differentiates the business.
- **Precompute vs compute on read:** precompute when reads dominate and freshness can lag.
- **Monolith vs microservices:** split along team and scaling boundaries, not for fashion; a modular monolith is a fine start.

**What a Director adds that a senior engineer often doesn't**

- **Cost.** Estimate the big line items (compute, storage, egress, GPU, third-party fees) and name the levers: caching, tiered storage, right-sizing, smaller models.
- **Phasing.** An MVP that meets the core numbers, then the scale-out steps, each with the metric that triggers it.
- **Teams and ownership.** Which team owns which service and data; the APIs between teams are the contracts that matter most.
- **Risk.** The top three risks, how you would detect each early, and the rollback plan.
- **Migration.** For a live system: strangler-fig, dual writes with reconciliation, shadow traffic, then cut over.
- **Success metrics.** One business metric, one reliability SLO, one cost metric.

**Common mistakes to avoid**

- Drawing boxes before agreeing on scope and numbers.
- One database for everything, with no partition key in mind.
- No answer for "what happens when this node or region dies".
- Exactly-once claims without idempotency keys.
- Going deep on easy parts while skipping the hot path or the money path.
- Listing technologies without saying why each one fits these numbers.

**A 60-second closing you can adapt**

"To recap: we scoped it to X, Y and Z at about N requests per second. Reads are served from cache and the CDN; writes go through a queue into a store sharded by K. The hardest parts were A and B, which we solved with C and D. Under failure we rely on idempotency keys, retries with backoff and a multi-region failover with an RPO of R. I'd watch p99 latency, error rate and cost per request. At 10x, the first thing to change is E."

**Five questions to check yourself**

1. What is the read/write ratio, and what did it change in your design?
2. What is the partition key, and does it create a hot spot?
3. Which data must be strongly consistent, and why?
4. What happens if the request is retried, or the service dies halfway?
5. What would you monitor on day one, and what would you change at 10x?
