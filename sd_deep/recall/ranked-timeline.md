# Ranked home timeline (ranking and freshness): recall card

> **Hook:** Push ids to followers → Pull celebrities at read → Light ranker prunes → GPU scores 500 → Decay and diversity → Freeze page per session

**P · Problem:** It's really a candidate-retrieval plus ranking-funnel problem under a tight latency and GPU budget.

**N · Numbers:**
1. About 100k first pages/s at peak, so candidates must be precomputed.
2. 500M posts x 200 followers = 100B fanout inserts/day, up to 4M/s, so skip celebrities and dormant users.
3. 100k/s x 500 items = 50M scores/s, about 1,000 GPUs, so prune hard before the GPU.

**H · Hard part:** Ranking about 1,500 fresh candidates per request in under 400 ms without celebrity fanout or GPU cost blowing up.

**B · Boxes:** `Client → Timeline Mixer → Candidate cache → Hydration → Light ranker → Heavy ranker → Ranked-page cache`

Side path: `Post service → Kafka → Fanout workers → Redis candidate lists`.

**D · Decisions:**
1. Hybrid fanout over pure push or pull, because reads stay cheap for 99.9% of authors with no 60M-way celebrity writes.
2. Rank at read time over a precomputed order, because scores need fresh engagement and precomputing wastes work on unread feeds.
3. Frozen session order over live re-rank, because scrolling must not show duplicates or jumps.

**F · Failures:**
1. GPU pool down → the Mixer times out at 120 ms and serves light-ranker order flagged degraded.
2. Kafka lag spike → feeds go stale; autoscale fanout workers and page on lag over 30 s.

**C · Close:** "Fanout workers push new post ids into per-user Redis lists, except celebrities, whom I pull at read time. On read, a mixer gathers about 1,500 candidates, hydrates and filters them, prunes to 500 with a cheap ranker, scores those on GPU, then applies freshness decay, diversity and ads. I cache the order for the session so pagination is stable. Every stage has a deadline with a fallback, down to chronological."

**Quiz yourself:**
1. How does freshness work? → Score times 2^(-age/8 h) for followed posts, plus a fanout lag SLO under 5 s.
2. Where do diversity and ad rules live? → In the re-rank stage, not the model.
3. What happens to a user back after 30 days? → A single-flight job rebuilds their list from top followees while recommendations fill in.
