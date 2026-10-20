# "suggested friends" (People You May Know): recall card

> **Hook:** Batch two-hop → Top 500 → Nearline deltas → Filter → Rank → Fail closed

**P · Problem:** It's really link prediction on a graph of billions, where the best signal is two hops away.

**N · Numbers:**
1. 1.8 x 10^14 raw two-hop pairs, so two-hop is a batch job with hub sampling, never online.
2. 2B users x 500 candidates = 20 TB, so serve it from a read-only, bulk-loaded KV store.
3. 35M scores/s at 50k QPS, so a cheap GBDT ranker on 35-50 cores per region fits.

**H · Hard part:** Mutual friends are too expensive per request, yet suggestions must feel fresh and never be creepy or unsafe.

**B · Boxes:** `Client → Suggestion service → Candidate KV + delta store → Graph service filters → GBDT ranker`

Side path: `friend_added → Kafka → Flink → Redis delta store` for freshness within a minute.

**D · Decisions:**
1. Batch plus nearline deltas over online two-hop, because online is 90k edge reads for a typical user.
2. Send-and-accept label over clicks or sends, because it aligns both sides and reduces spam.
3. Hard filters that fail closed over model-learned safety, because they are deterministic and auditable.

**F · Failures:**
1. Block or policy lookup fails → return an empty list, never a risky one.
2. Ranker times out → order by Adamic-Adar and flag the response as degraded.

**C · Close:** "This is link prediction. A daily Spark job joins edges on the middle person, weights mutual friends by Adamic-Adar, samples hubs, and bulk-loads the top 500 per user as a versioned dataset. A Flink job writes two-hop deltas the moment someone adds a friend. Online, I merge both, filter with live one-hop lookups, rank on send and accept, diversify and cap impressions. Safety filters fail closed."

**Quiz yourself:**
1. Why Adamic-Adar? → A mutual friend with 300 friends is a stronger hint than one with 5 million.
2. How do blocks apply immediately? → They are checked at read time on every request.
3. What stops hubs blowing up the batch? → Sampling hubs down to 5,000 friends and pruning to top 500.
