# E-commerce Catalog Search (product search): recall card

> **Hook:** Understand the query → Retrieve BM25 plus vectors → Fuse with RRF → Rank top 500 → Overlay live stock and rules

**P · Problem:** It's really a multi-stage ranking funnel that optimises conversion, with fast-changing price and stock kept outside the index.

**N · Numbers:**
1. About 20,000 QPS on sale days, so pre-provision, because stateful search tiers cannot autoscale in seconds.
2. Every search hits all 48 shards, so 7 copies per shard on about 170 nodes: replicas, not data size, set the bill.
3. 20K price and stock updates/s, so keep them in an in-memory KV store, not the inverted index.

**H · Hard part:** Turning short, misspelt, Hinglish queries into the right filters, and keeping stock fresh without merge storms.

**B · Boxes:** `API Gateway → Search orchestrator → Query understanding → Lexical and vector index → Ranker → Availability store`

Side path: `Pricing/Inventory → Kafka → Fast Updater → availability store` for stock.

**D · Decisions:**
1. Hybrid retrieval with RRF over lexical-only, because BM25 nails brands while embeddings catch vague and Hinglish queries.
2. KV store for price and stock over in-index updates, because it gives freshness without merge storms.
3. Confidence-based filters over always-filter, because a wrong hard filter gives an empty page.

**F · Failures:**
1. Ranker or features time out → serve L1 ordering and alert on the fallback rate.
2. Vector index down → lexical-only, with a small recall loss on vague queries.

**C · Close:** "So the goal is conversion, not text match, so I built a funnel. Query understanding turns text into category, brand and price filters. Retrieval is BM25 on 48 shards plus embedding search, fused into about 1,200 candidates. A LambdaMART model trained on purchases ranks the top 500. Then I overlay live stock and deliverability from an in-memory store, the buy-box and capped rules. Every stage has a deadline and a fallback. Next I would add personalisation."

**Quiz yourself:**
1. How are BM25 and vector scores combined? → Reciprocal rank fusion: each list adds 1/(60 + rank).
2. Why not update stock in the index? → Segments are immutable, so 20K updates/s cause merge storms.
3. What are the ranking labels? → Purchase 3, add-to-cart 2, click 1, skip 0.
