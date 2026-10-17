# Design E-commerce Catalog Search (product search): the 5-page summary

Product search is not document search: queries are short and ambiguous ("red shoes under 1000"), the catalog is structured, price and stock change thousands of times a second, and the goal is conversion, not text match. The single most important idea: a multi-stage funnel (understand the query, retrieve with lexical plus semantic search, rank with a learned model, then overlay live stock and rules), with fast-changing price and stock kept outside the inverted index.

## Page 1. The problem, scope and numbers

**Pitch:** shoppers type short, misspelt, Hinglish queries into a huge, noisy catalog. Return relevant, in-stock, deliverable products in under 250 ms, even when sale-day traffic jumps 10x.

**Who uses it:** shoppers on 4G (including Hinglish: "ladies kurti cotton sasta"), sellers, category managers and relevance scientists.

**In scope:**
- **Query understanding:** spelling, synonyms, transliteration, category and price intent.
- **Retrieval and ranking:** BM25 plus embeddings, then learning-to-rank on behaviour.
- **Filters, facets and sorts:** category-specific facets with counts; price, rating, newest.
- **Pincode deliverability**, variant grouping with a buy-box offer, capped merchandising boosts.
- **Event logging** with feature snapshots for training.

**Out of scope:** ads auction, autocomplete, home-page recommendations, cart and checkout, visual and voice search, seller onboarding.

**Non-functional targets:**
- **Latency and availability:** p50 under 100 ms, p99 under 250 ms; 99.95%, 99.99% in sales with degraded modes.
- **Freshness:** price and stock p95 under 60 s; new listings under 15 minutes.
- **Consistency:** eventual; cart and checkout re-verify against the source of truth.
- **Quality:** zero results under 3%; out-of-stock in top 10 under 0.5%.

**Capacity math (200M products, 1B offers, 100M searches/day):**
- **QPS:** 100M x 1.5 requests per search / 86,400 = about 1,700 QPS; sale peak 10x = 17,000-20,000. So pre-provision for sale days; stateful search tiers cannot autoscale in seconds.
- **Lexical index:** 200M x 4 KB = 800 GB raw, about 1 TB with doc values; 1 TB / 30 GB gives 32-40, so 48 primary shards of about 4M products.
- **Replicas:** every search hits all 48 shards, so each shard sees the full 20K QPS; at about 3,000 shard-queries/s per copy that needs 7 copies: 336 shard copies on about 170 nodes. So replicas, not data size, set the sale-day bill.
- **Vectors:** 200M x 256 dims x 1 byte = 51 GB, plus 26 GB of HNSW links: about 80 GB.
- **Ranking:** 20K QPS x 500 candidates = 10M scorings/s; at 5 microseconds each = 50 cores; provision 200.
- **Price and stock:** 20K updates/s x 50 B = 1 MB/s. Tiny, but frequent, so keep it in an in-memory KV store, not the index.

## Page 2. The architecture

```
 Client (app/web, pincode)
   |
 API Gateway -> Search Orchestrator --cache--> Redis query cache
                 | 1. understand
                 +--> Query Understanding (spell, translit, NER, category)
                 | 2. retrieve in parallel
                 +--> Lexical index (48 shards x 7 copies, BM25 + filters)
                 +--> Vector index (HNSW, 8 partitions)
                 | 3. features + rank
                 +--> Feature store -> Ranker (LTR GBDT)
                 | 4. stock, buy-box, rules, facets
                 +--> Availability store (sku x pincode) + Merch rules
 Events -> Kafka -> Lake -> training
 Catalog DB -CDC-> Kafka -> Doc Indexer -> lexical + vector (embed svc)
 Pricing/Inventory -> Kafka -> Fast Updater -> availability store
                                    \-> partial index update (in_stock, price)
```

- **Search orchestrator:** owns the 220 ms budget; per-stage timeouts and fallbacks.
- **Query understanding:** turns text into filters, boosts and a category prior.
- **Lexical index:** OpenSearch-style BM25, structured filters, facet aggregations.
- **Vector index:** HNSW embeddings for vague, synonym and cross-language queries.
- **Feature store and ranker:** online features; LambdaMART scores the top 500 in about 30 ms.
- **Availability store:** in-memory stock and serviceability per sku and pincode cluster.
- **Buy-box and rules engine:** best offer per product; capped pins and boosts, all logged.
- **Indexing pipeline:** catalog CDC, document builder, bulk indexer, alias rebuilds.

**Flow A: search "red nike shoes under 2000", pincode 600042**
1. Cache miss; QU returns category sports shoes, brand Nike, color red, price <= 2000, text "shoes".
2. In parallel: lexical query with those filters on all 48 shards (top 1,000) and vector ANN (top 500).
3. Merge to about 1,200, fetch features (10 ms), rank the top 500, drop undeliverable SKUs, pick offers.
4. Apply boosts (max 3 per seller in top 10), compute facets, return 24 products; cache 60 s.

**Flow B: price or stock change**
1. Fast Updater consumes Kafka keyed by sku; updates the availability store in 1-2 s.
2. Only if in_stock flips or price crosses a bucket: partial index update (5 s refresh).

## Page 3. The core deep dives

### 1. Query understanding: filter or boost?
Normalise ("1tb" = "1 tb"), spell-correct against a log-weighted vocabulary ("samsang"), transliterate Hinglish, classify category ("apple": 60% phones, 25% fruit, 15% accessories), tag spans as brand, colour or price ("under 2000" -> price <= 2000). The key choice: a wrong hard filter gives zero or wrong results, a soft boost is forgiving but imprecise. So confidence thresholds decide, and the interpretation is shown as chips the shopper can undo. If a query would return nothing, drop the least important term.

### 2. Hybrid retrieval and multi-stage ranking
BM25 nails brands and model numbers ("SM-S918B"); embeddings catch vague and Hinglish intent. Scores are on different scales, so reciprocal rank fusion mixes ranks: each list adds 1/(60 + rank). L1 is a cheap linear score on all candidates; L2 is LambdaMART on the top 500, trained on graded labels (purchase 3, add-to-cart 2, click 1, skip 0) with position-bias correction; L3 applies rules. If L2 misses its deadline, L1 order is served. Features are logged at serve time, so training matches serving.

### 3. Fast fields versus slow fields (CQRS read models)
Lucene segments are immutable: an update is delete plus re-add plus merge. Pushing 20K stock changes/s into the index causes merge storms. So the availability store is authoritative and joined at query time for a few hundred candidates; the index is touched only when a filterable state changes. Cart always reads the source of truth.

### 4. Facets
Count values per field over matching docs using doc values (columnar storage). Cost is hits x facets, so broad queries ("shoes", 5M hits) use approximate counts; narrow ones are exact. Multi-select uses post_filter: selecting Nike still shows other brands' counts.

**Data model:**
- **Product search doc** (lexical): _id product_id, routing hash(product_id) over 48 shards; brand, attributes, price_bucket, in_stock; variants collapsed.
- **Product embedding:** int8[256], hash(product_id) into 8 partitions.
- **Availability** (Aerospike/Redis): key sku; stock by warehouse, pincode-cluster bitmap, price, version.
- **Online features:** key product_id, plus (query_hash, product_id) pair features.
- **Search event log:** Kafka to lake, partitioned by date, joined on request_id.

**Key APIs:**
- `GET /v1/search`: returns request_id; page_token pins the candidate set across pages.
- `POST /v1/search/events`: async, batched impression and click logging.
- `PATCH /internal/availability/{sku}`: fast path, idempotent by version.
- `PUT /internal/products/{product_id}`: indexer write with external catalog version.
- `POST /v1/admin/merch-rules`: needs approval; caps enforce fairness.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Shard fan-out on sale day:** add replicas ahead of time (1 primary + 6 replicas), load-test at 1.5x forecast.
- **Head queries:** cache the ranked candidate list per (query, filters, sort, bucket), apply the pincode and stock overlay per request, TTL 30-60 s, coalesce misses at sale start.
- **Ranking CPU:** 10M scorings/s, cut by the L1 stage and provisioned at 4x.
- **Broad facets:** approximate counts, lazy-loaded facets on mobile.
- **Catalog growth to 500M:** build a new index version with more shards and swap the alias.

**Failure modes:**
- **Ranker or features time out:** fall back to L1 ordering; alert on fallback rate.
- **Vector index down:** lexical-only; small recall loss on vague queries.
- **Availability store lags:** last-known stock, more cart re-checks, demote low-stock items.
- **QU down:** raw text and default boosts; filters only from explicit UI picks.
- **Bad model shipped:** canary with automatic rollback; previous model kept warm.
- **CDC stalled:** existing index serves; replay from Kafka offsets.
- **Traffic 2x forecast:** longer cache TTL, no semantic on head queries, shallower ranking, lazy facets, then shed bot traffic first.

**Trade-offs chosen:**
- **Hybrid with RRF over lexical-only:** precision for brands plus recall for vague and Hinglish queries.
- **KV store for price and stock over in-index updates:** freshness without merge storms.
- **GBDT now, neural later:** strong on tabular features, CPU-cheap, explainable.
- **Confidence-based filters over always-filter:** wrong filters cause empty pages.
- **Pre-provision plus degradation over autoscaling:** stateful tiers cannot scale in seconds.
- **Approximate facets on broad queries:** exact counts on millions of hits are costly.

**What to measure:** conversion and revenue per search, CTR@4, zero-result and reformulation rate, out-of-stock and undeliverable in top 10, per-stage p99 (QU, lexical, vector, features, ranker, facets), ranker fallback rate, cache hit ratio, CDC and availability lag, NDCG@10 per release, training/serving skew.

## Page 5. Say it in the interview

> "Scope first: about 200 million products and a billion offers, 100 million searches a day with 10x sale peaks, filters, facets, pincode-aware delivery, p99 under 250 ms, and price and stock fresh within a minute. The goal is conversion, not just text match, so I design a funnel. Query understanding turns 'red nike shoes under 2000' into category, brand, colour and price filters plus text. Retrieval is hybrid: BM25 on 48 shards plus embedding search, fused into about 1,200 candidates. A learning-to-rank model trained on purchases scores the top 500. Then live stock and deliverability from an in-memory store, the buy-box, capped merchandising rules and facets. Every stage has a deadline and a fallback, and sale capacity is pre-provisioned."

**Key points to land:**
- Optimise conversion, not text relevance; frame the metrics that way.
- Funnel: understand, retrieve, rank, then availability, rules and facets.
- Confidence thresholds decide filter versus boost; show chips the shopper can undo.
- Hybrid retrieval: BM25 for exactness, HNSW for semantics, fused with RRF.
- LambdaMART on purchase-graded labels with position-bias correction; log features at serve time.
- Price and stock in a KV store; the index changes only on state flips.
- Facets from doc values; approximate on broad queries; multi-select via post_filter.
- Sale peaks: 7 copies per shard, pre-provisioned, plus degradation levers.
- Every stage has a deadline and a fallback.

**Likely follow-ups:**
1. **Where do sponsored products go?** The ads system runs its own auction on the same QU output; a page composer blends ads into labelled slots with relevance floors.
2. **How do you personalise?** User features (brand affinity, price band, size history) in the ranker or a light re-rank of the top 50, keeping the shared cache.
3. **New category with no data?** Content features, priors from similar categories, human judgments and exploration slots.
4. **Where does an LLM fit?** Offline for labels, attribute enrichment and query rewrites; online only as cached rewrites for tail queries.
5. **How do you stop sellers gaming it?** Outcome-based features (conversion, returns, verified ratings), click-fraud detection, stuffing penalties and audits of sudden jumps.

**Director layer:**
- **Cost drivers:** sale-day replicas (about 170 search nodes), the ranking tier (200 cores), vector memory, and the logging pipeline.
- **Phasing:** lexical search with QU and a GBDT ranker first; neural ranking, personalisation and LLM enrichment later.
- **Team ownership:** query understanding, retrieval platform, ranking and ML, catalog indexing, availability, and the experimentation platform.
- **Top risks:** sale-day overload, ranking that optimises clickbait over purchases, stale stock driving cancellations, poor catalog attributes breaking filters, and fairness rules on self-preferencing.
