# Design Fast Personalized Data Serving (personalized home page): the 5-page summary

Personalized data cannot sit behind a CDN, because every user's response is different, yet it must load in tens of milliseconds for 100M daily users and survive 10x sale-day spikes. The single most important idea: a hybrid. Precompute candidates offline into an in-memory key-value cache, re-rank a few hundred online with fresh session features, cache at several layers, and always have a non-personalized fallback.

## Page 1. The problem, scope and numbers

**Pitch:** return a personalized e-commerce home page (layout plus recommendation widgets) in under 100 ms p99 at 10x peak, reacting to what the user did seconds ago, at half the cost of running the model on every request.

**Who uses it:** returning shoppers (items related to past purchases and recent browsing, instantly), new or logged-out visitors (sensible content from location, device and session, never an empty page), merchandisers (pin and boost campaigns without breaking personalization).

**In scope:**
- **Page and widgets** for a user and context (device, location, page type).
- **Precomputed candidates** per user and widget, versioned.
- **Online re-rank** with session features and business rules (pins, boosts, filters, diversity).
- **Hydration** of item ids into cards: title, image, price, discount, stock.
- **Event ingest** (view, click, add to cart, purchase) updating features within seconds.
- **A/B experiments, fallbacks and opt-out** honoured with key deletion.

**Out of scope:** model training and offline evaluation, search personalization, email and push recommendations, client rendering beyond payload size, personalized pricing.

**Non-functional targets:**
- **Latency:** service p50 under 30 ms, p99 under 100 ms; candidate and feature fetch p99 under 10 ms each.
- **Availability:** 99.95% counting fallbacks; 99.9% for full user-level personalization.
- **Freshness:** session features within 2 s; candidates daily, hourly for active users.
- **Consistency:** eventual; price and stock on cards at most 60 s stale (checkout re-validates).
- **Payload:** under 50 KB compressed, for 3G and 4G users in tier-2 and tier-3 cities.

**Capacity math (100M DAU, 300M profiles, 20 loads per DAU per day):**
- **QPS:** 100M x 20 / 86,400 = about 23k average, 230-250k at sale peak. So stateless services and pre-scaling.
- **Candidates:** 500 ids x (8 B + 2 B score) = 5 KB, 3 KB compressed; 300M x 3 KB = 0.9 TB, 1.8 TB with 2 zone copies. Only 120M are active in 30 days: 0.36 TB per copy. So store only active users, in RAM.
- **Hydration:** 250k x 60 items = 15M lookups/s; a 90% L1 hit leaves 1.5M keys/s, batched into about 250k multi-gets/s. So hydration fan-out is the hidden bottleneck.
- **Item cache:** 5M active items x 2 KB = 10 GB. So replicate it fully in every zone.
- **Events:** 100M x 60 = 6B/day = 70k/s, 700k/s at peak, about 210 MB/s into Kafka.
- **Bandwidth:** 250k x 40 KB = 10 GB/s. So images go to the CDN and JSON stays compact.

## Page 2. The architecture

```
 Mobile / Web
     |
   CDN -- images, static, fallback popular lists (TTL 60 s)
     |
   Page / BFF service -- layout, experiment assignment, 80 ms deadline
     |
   Personalization service (stateless, L1 in-process cache)
     | parallel fetch            |                      |
     v                           v                      v
 Candidate KV cache       Online feature store     Item cache
 user -> ranked ids       session + user feats     id -> card, price/stock
 (EVCache/Redis, /zone)   (Redis/Aerospike)        keys
     ^ bulk load                 ^ stream update        ^ CDC invalidation
 Batch precompute (Spark)  Stream processor        Catalog / Pricing DBs
     ^                           ^
 Data lake: history, models <-- Kafka: user events <-- clients
```

- **Page / BFF:** layout, experiment variants, one call per widget, enforces the page deadline.
- **Personalization service:** stateless; fetch, re-rank, apply rules, hydrate, return widgets.
- **Candidate KV cache:** sharded, zone-replicated, versioned per-user and per-segment lists.
- **Online feature store:** recent views, cart, affinities; updated by the stream processor.
- **Item cache:** item cards plus separate short-TTL price and stock keys.
- **Batch precompute:** Spark candidate generation, daily for all active users, hourly for recent ones.
- **Stream processor:** session features within seconds; flags users for priority recompute.
- **Fallback lists:** segment and global popular lists every few minutes, served from the edge.

**Flow A: serve the home page**
1. BFF authenticates, assigns the variant, requests widgets with an 80 ms budget; consent is checked.
2. In parallel: candidates (10 ms budget) and user and session features (10 ms budget).
3. Re-rank the top 200 with a light model (boosted trees or small MLP), 5-15 ms.
4. Rules: drop purchased and out-of-stock, apply pins, boosts, brand and category diversity.
5. Hydrate the top 60 via batched multi-get, L1 then item cache (20 ms); log impressions async.

**Flow B: nightly precompute and load**
1. Spark reads 90 days of history and the current model for about 120M active users.
2. A loader bulk-writes keys user:{id}:v{date}, throttled to 30% of cluster capacity.
3. After coverage and quality checks, flip the version pointer; the old version expires in 3 days.

## Page 3. The core deep dives

### 1. Precompute plus online re-rank
Candidate generation is expensive and taste changes slowly, so it runs in batch. Session features change by the second, so they stream. Re-ranking 200 items costs about 10 ms, so it runs online. Example: Shreya views running shoes; the event reaches Kafka, the stream processor updates her last-viewed list and category affinity within about a second, and her next widget call re-ranks shoes higher. "Similar to what you just viewed" uses a precomputed item-to-item list keyed by item, shared and highly cacheable. Affinity uses exponential decay: on each event, multiply the old score by exp(-dt / half-life) and add the event weight, O(1) with no stored history.

### 2. Hydration fan-out and tail latency
60 items per page is 15M lookups/s at peak. Batch multi-gets per shard, keep hot items in an L1 in-process cache (5-30 s TTL), and keep price and stock in separate 60 s keys so a price change does not evict the card. Each call gets its own slice of the 80 ms deadline; reads are hedged to the other zone's replica after the p95; a late widget is dropped or served from fallback rather than delaying the page.

### 3. The cache is the primary store, and never stampedes
For derived candidates the cache is the database: they can be regenerated, and Cassandra's 5-15 ms per lookup would blow the budget. Writes are versioned and a pointer flips atomically, so old and new models never mix across shards. A candidate miss never recomputes inline; it falls back. For item cards: single flight (the first miss loads, others wait on the same future), TTL jitter of 20%, and stale-while-revalidate. Catalog changes stream through Debezium CDC to delete item:{id} and ps:{id} in every zone; TTLs are the backstop.

### 4. The fallback chain
User candidates with re-rank, then without re-rank, then segment lists (city x category x age band), then a global popular list at the CDN. Each widget declares if it is optional; operators can force segment mode on sale day. Sethu, a new user, gets segment lists until the stream processor builds his features.

**Data model:**
- **UserCandidates:** cand:{user_id}:{widget}:v{yyyymmdd} plus a pointer key; packed ids and scores, about 3 KB, TTL 3 days.
- **SessionFeatures:** feat:{user_id} and feat:{user_id}:{session_id}, partitioned by user_id; TTL 30 days and 2 h.
- **ItemCard and ItemPriceStock:** item:{id} (TTL 10 min) and ps:{id} (TTL 60 s), both CDC-invalidated.
- **SegmentList:** seg:{segment_id}:{widget}, recomputed every 5-15 minutes.

**Key APIs:**
- `GET /v1/home?user_id&device&city&session_id`: 80 ms deadline, partial widgets allowed, Cache-Control private.
- `GET /v1/widgets/{widget_id}?user_id&cursor`: lazy loading below the fold.
- `POST /v1/events`: batched every 5 s or on strong events; idempotent by (session_id, seq).
- `PUT /v1/users/{id}/personalization`: consent; triggers deletion of per-user keys.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hydration:** batched multi-gets per shard, L1 for hot items, the 10 GB item cache replicated in every zone.
- **Reads:** zone-replicated caches with client-side consistent hashing; local zone first.
- **Writes:** throttled bulk loads; events and features partitioned by user_id, so no global hot spot.
- **Sale-day spike:** pre-scale from the forecast, warm sale SKUs, raise L1 TTLs, disable hedging under high load, force segment lists below the fold if needed.
- **Hot item:** L1 with short TTL absorbs it; key replication with a random suffix if needed.

**Failure modes:**
- **Candidate cache zone outage:** read another zone's copy; if both slow, segment lists; no recompute storm.
- **Feature store slow (p99 50 ms):** time out at 10 ms, re-rank with defaults; quality dips, latency holds.
- **Nightly batch fails:** the pointer stays on the previous version; hourly job covers active users.
- **Kafka or stream lag:** recommendations stop reacting in-session but still serve; lag alert scales out.
- **Item cache stampede:** single flight, jitter and stale-while-revalidate protect the DB.
- **Bad model pushed:** canary guardrails (CTR, empty widgets) roll the version pointer back.

**Trade-offs chosen:**
- **Precompute plus online re-rank over per-request inference:** lookups plus a cheap re-rank, still reacting within seconds.
- **Precompute only 30-day active users:** cuts RAM and batch compute by about 60%; others get one segment page, then a priority recompute.
- **Full cache copy per zone:** faster in-zone reads, no cross-zone transfer cost, survives a zone loss.
- **Separate price and stock keys with CDC:** fast sale-time price changes without evicting card data.
- **Aerospike for features:** index in RAM, data on SSD, far cheaper than full RAM at hundreds of millions of records.
- **Fallback over recompute on a miss:** inline recompute at peak would stampede the model servers.

**What to measure:** p50/p99 per stage (candidates, features, re-rank, hydration, total); candidate hit ratio (98%+) and source mix (user, segment, global); L1 and L2 item hit ratio and DB QPS from misses; session feature lag p95; precompute completion and coverage; hedge and timeout rates; CTR and conversion per widget; payload size.

## Page 5. Say it in the interview

> "Assume an e-commerce home page with recommendation widgets, 100 million daily users, about 20 loads each a day, 10x spikes on sale days, and a p99 of 100 ms at the service. The naive design calls the model per request against the main database, which is too slow and too expensive. So I split the work: offline jobs precompute about 500 candidates per user into a sharded in-memory key-value cache; an online service fetches those plus fresh session features in parallel, re-ranks a couple of hundred items with a light model, and hydrates them from a shared item cache. Kafka keeps session features fresh within seconds. Hydration fan-out and tail latency are the bottlenecks, so I batch, replicate per zone, set per-call budgets and hedge reads, and fall back to segment and global lists so the page never fails."

**Key points to land:**
- No per-user CDN caching, so speed comes from precompute plus in-memory serving.
- Batch for candidates, streaming for session signals, cheap re-rank online.
- The cache is the primary store for derived candidates; a miss falls back, never recomputes.
- 23k QPS average, 250k peak; 0.36 TB of RAM per copy; item cache only 10 GB.
- Hydration fan-out is the hidden bottleneck: batch per shard, L1, separate price keys.
- Per-call budgets, hedged reads after p95, partial responses.
- Zone-replicated caches with client-side consistent hashing.
- Single flight, TTL jitter and stale-while-revalidate stop stampedes.
- Fallback chain: user, segment, global; fallback rate is a business metric.

**Likely follow-ups:**
1. **React to the item viewed one second ago?** The event updates features within about a second; the next call re-ranks, and an item-to-item neighbour list covers "similar to this".
2. **What if p99 must be 20 ms?** A tiny in-process model or none, same-zone caches, L1 for the user's own candidates, more precompute, maybe client-side re-ordering.
3. **How do you test a new ranking model?** As a re-ranker variant on a small percentage of users, logging impressions, with latency and empty-widget guardrails; ramp only on significant lift.
4. **Can a CDN cache personalized responses?** Not per user, but per segment key (city, language, new versus returning); that is how fallback lists are served.
5. **Why not store everything in Cassandra?** Its 5-15 ms per lookup across many keys blows the budget; derived data can be regenerated, so an in-memory cache is cheaper and faster.

**Director layer:**
- **Cost drivers:** RAM for candidates in every zone (cut 60% by active-user-only), the 10x sale-day cluster sizing, batch compute; target 50% lower cost per 1,000 responses than per-request inference.
- **Team ownership:** ML team owns models; this team owns serving, caches, streaming features and fallbacks; catalog owns CDC.
- **Top risks:** a failed precompute leaving stale lists, cache loss stampeding the backends, wrong prices or stock eroding trust, and feedback loops narrowing discovery (exploration slots, diversity, A/B guardrails).
- **Privacy:** opt-out deletes per-user keys; the lake is purged within 30 days.
