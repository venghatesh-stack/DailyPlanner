# Real-time gaming leaderboard: recall card

> **Hook:** Signed match result → Kafka → Validator dedups → Durable totals → Redis sorted set per board → ZREVRANK

**P · Problem:** It's really an order-statistic query: rank among 100M players, which SQL scans and a sorted set answers in log n.

**N · Numbers:**
1. 100M players x 100 B = 10 GB per board, so one board fits one node and we shard by board first.
2. 5 boards per match x 17k matches/s = 87k sorted-set updates/s, so spread boards across shards.
3. A rebuild runs at about 1M ZADD/s, about 2 minutes per board, so Redis can safely be a projection.

**H · Hard part:** Exact, fresh ranks for millions with fair tie-breaks, without losing scores or trusting cheaters.

**B · Boxes:** `Game servers → Kafka → Score validator → Durable score store → LB updaters → Redis sorted sets → Leaderboard API`

**D · Decisions:**
1. Redis sorted sets over SQL, because rank is O(log n) instead of linear in rank.
2. Durable store plus Kafka as truth over Redis alone, because failover cannot lose scores and rebuild takes minutes.
3. Tie-break encoded in the double over app-side ordering, because ranking stays inside Redis and is exact under 2^53.

**F · Failures:**
1. Redis primary fails → a replica is promoted; updaters replay recent deltas as absolute values.
2. Whole Redis cluster lost → serve cached top-N and "rank unavailable"; rebuild from durable totals, top boards first.

**C · Close:** "Rank needs an ordered index: a Redis sorted set updates and ranks in log n, where SQL would count rows. Scores come only from game servers, go through Kafka, dedup by match id and cheat checks, and land in a durable store first. Updaters then write one sorted set per board and period, with the tie-break inside the score. Top 10 is cached and pushed, and a 10 gigabyte board rebuilds in about two minutes."

**Quiz yourself:**
1. Why not Postgres with a score index? → Top-N is fine, but my-rank counts every higher score.
2. How does the earlier achiever win a tie? → Pack an inverted timestamp into the low bits of the score.
3. One board outgrows a node? → Shard by score range; rank = higher shards' counts + local rank.
