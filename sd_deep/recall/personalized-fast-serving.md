# Fast Personalized Data Serving (personalized home page): recall card

> **Hook:** Precompute candidates nightly → Load into in-memory KV → Fetch with session features → Re-rank 200 → Hydrate in batches → Fall back

**P · Problem:** It's really a low-latency serving problem for data a CDN cannot cache, because every user's response is different.

**N · Numbers:**
1. About 23k QPS average and 230-250k at sale peak, so stateless services and pre-scaling.
2. 120M active users x 3 KB = 0.36 TB per copy, so store only active users' candidates, in RAM.
3. 250k x 60 items = 15M lookups/s, so hydration fan-out is the hidden bottleneck.

**H · Hard part:** Hitting 100 ms p99 at 10x peak while reacting to what the user did seconds ago.

**B · Boxes:** `Client → BFF → Personalization service → Candidate KV and feature store → Item cache`

Side path: `Kafka events → Stream processor → Online feature store` for session freshness.

**D · Decisions:**
1. Precompute plus online re-rank over per-request inference, because lookups plus a cheap re-rank still react within seconds at lower cost.
2. Fallback over recompute on a miss, because inline recompute at peak would stampede the model servers.
3. Separate price and stock keys over one item card, because sale-time price changes must not evict card data.

**F · Failures:**
1. Feature store slow → time out at 10 ms, re-rank with defaults; quality dips, latency holds.
2. Nightly batch fails → the version pointer stays on the previous version; the hourly job covers active users.

**C · Close:** "Calling the model per request against the main database is too slow and too expensive. So offline jobs precompute about 500 candidates per user into a sharded in-memory cache. An online service fetches those plus fresh session features in parallel, re-ranks a couple of hundred items with a light model and hydrates them from a shared item cache. I batch, replicate per zone, set per-call budgets, hedge reads, and fall back to segment and global lists so the page never fails."

**Quiz yourself:**
1. Why not Cassandra for candidates? → 5-15 ms per lookup blows the budget, and the data can be regenerated.
2. What is the fallback chain? → User candidates, then segment lists, then a global popular list at the CDN.
3. How do you stop an item cache stampede? → Single flight, TTL jitter and stale-while-revalidate.
