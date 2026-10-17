# Design a ranked home timeline (ranking and freshness): the 5-page summary

A ranked home timeline merges posts from hundreds of followed accounts plus recommended content, scores them with an ML model, and returns the first page in a few hundred milliseconds. The single most important idea: precompute candidates with a hybrid fanout (push for most authors, pull for celebrities), but rank at read time through a funnel that spends GPU only on a pruned set, with a deadline and fallback at every stage.

## Page 1. The problem, scope and numbers

**Pitch:** show each user the posts they care about most, fresh enough to feel live, at a compute cost that scales with traffic.

**Why:** a chronological feed buries the best posts for people who follow hundreds of accounts and shows almost nothing to people who follow few, so engagement plateaus. The goal is +5 to 10% time spent per daily active user versus chronological.

**Who uses it:** heavy followers (1,000+ accounts, want signal over noise), new users (under 10 follows, need a non-empty feed), creators (want reliable reach) and lapsed users (want the best of what they missed).

**In scope:**
- **Ranked page:** 20 posts plus an opaque cursor; a "latest" mode from the same candidates.
- **Sources:** in-network (followed) and out-of-network (recommended) posts, with attribution.
- **"N new posts" banner:** via a cheap count endpoint.
- **Serve-time filters:** blocked, muted, deleted and unsafe posts; author diversity; ad slots.
- **Feedback loop:** impressions and engagements logged; hide or "show less" applied within the session.

**Out of scope:** model architecture and training infrastructure, ads auction, notifications, media and CDN, search ranking.

**Non-functional targets:**
- **Latency:** first page p99 under 400 ms server side; next pages p99 under 100 ms.
- **Freshness:** a new post in followers' candidates within 5 s p99.
- **Availability:** 99.95% for reads, degraded modes counted as available.
- **Consistency and durability:** eventual for followers, read-your-own-writes for the author; posts never lost (RF=3); caches rebuildable.
- **Cost:** heavy ranker scores at most 500 items per request.

**Capacity math (200M DAU, 15 opens a day, about 2 pages per open):**
- **First pages:** 200M x 15 = 3B/day, 35k/s average, about 100k/s peak. So the read path must be cheap: precompute candidates.
- **All page fetches:** about 6B/day, 200k/s peak. So later pages come from a page cache, not a re-rank.
- **Posts:** 500M/day = 6k/s, 20k/s peak.
- **Fanout:** 500M x 200 followers = 100B inserts/day, 1.2M/s average, 4M/s peak. So skip celebrities and dormant users.
- **Heavy ranking:** 100k/s x 500 items = 50M scores/s; at 50k per GPU, about 1,000 GPUs. So prune hard before the GPU.
- **Candidate cache:** 200M x 800 ids x 8 B = 1.3 TB, about 3 TB with overhead and a replica, in Redis.
- **Post store:** 500M x 1 KB = 500 GB/day, about 180 TB/year before replication.

## Page 2. The architecture

```
 Client --GET /timeline?cursor--> API gateway --> Timeline Mixer
                                                (orchestrator, deadlines)
                                                       |
     Candidate sources: in-network cache (Redis lists),|
     out-of-network ANN, celebrity pull store  --------+
                                                       v
            Hydration (post store, author, counters, safety labels)
                                                       v
   Light ranker (GBDT) -> Heavy ranker (GPU) -> Mixing (diversity, ads)
                               ^                        v
                        Feature store            Ranked-page cache + cursor
                               ^
 Write:  Post svc -> Kafka(posts) -> Fanout workers -> in-network cache
 Events: Client -> Kafka(engagements) -> Flink -> features, counters, logs
```

- **Post service and store:** wide-column KV keyed by post_id; emits post_created.
- **Fanout workers:** push post ids to active followers; skip celebrities and dormant users.
- **Candidate cache:** Redis sorted set per user of recent post ids, trimmed to 800.
- **Out-of-network retrieval:** embedding nearest-neighbour search (HNSW) plus graph sources.
- **Timeline Mixer:** runs fetch, hydrate, features, rank, mix; enforces deadlines.
- **Feature store:** online user, author and post features; Flink updates counters in seconds.
- **Ranking service:** GBDT pruning on CPU, multi-task neural scoring on GPU.
- **Ranked-page cache:** the session's ordered id list, 15-minute TTL.
- **Event pipeline:** Kafka and Flink to counters, features and training logs.

**Flow A: publish a post**
1. POST with an idempotency key; write to the post store and the author's own list.
2. Emit post_created to Kafka keyed by author_id.
3. Celebrity: append only to the author's recent store. Otherwise page followers 5,000 at a time, keep those active in 30 days, ZADD the id, trim to 800.

**Flow B: load the first page**
1. Mixer reads the 800-id list, celebrity recents and about 700 recommended ids in parallel (50 ms).
2. Dedupe, drop seen ids (bloom filter of the last 2,000), hydrate, drop deleted, blocked or unsafe.
3. Features (30 ms), light ranker to 500, heavy ranker on GPU (120 ms).
4. Decay, diversity, ad slots, exploration; cache the list; return 20 items and a cursor.

## Page 3. The core deep dives

### 1. Hybrid fanout: push for most, pull for celebrities
The timeline is read far more than written, so push (fanout on write) makes reads cheap. But a celebrity with 60M followers would mean 60M writes per post. So authors above about 100k followers (roughly 50k accounts) are pulled: their last 100 posts sit in a per-author store, and the Mixer takes the 20 newest from each followed celebrity at read time. Push also skips users inactive for 30 days; when they return, a single-flight job rebuilds their list from their top 200 followees by affinity while recommended posts fill the feed. Push only produces candidates; order is decided at read time.

### 2. The ranking funnel
Thousands of candidates, hundreds scored deeply, tens shown. About 1,500 candidates (roughly half in-network) go to a GBDT light ranker on 40 features, which keeps 500. A multi-task neural model on GPU scores those in batches of 128, predicting several actions (like, reply, long dwell); a weighted sum is the score. Business rules live in a re-rank stage, not the model: at most 2 consecutive posts from one author, an ad every 6 items, safety filters, and 2% of slots for exploration. Recall is won early, precision late.

### 3. Freshness: decay plus pipeline lag
Freshness has two meanings, each with a target. Score decay: final = model_score x 2^(-age_hours / 8) for in-network and a 4-hour half-life for recommended posts, with age also a model feature. Example: Shreya's post scores 0.8 and is 8 hours old, so 0.4; Sethu's post scores 0.6 and is 1 hour old, so about 0.55, and it ranks first. Age uses server snowflake-id time, never client clocks. Pipeline lag: fanout must land within 5 s p99, measured as Kafka consumer lag.

### 4. Stable pagination and degradation
Scores change every second, so re-ranking on scroll would cause duplicates and jumps. The ordered list is frozen per session for 15 minutes; the cursor (signed session id plus offset) reads the next 20 ids, so a retried request returns the same page. New posts show as a banner and are ranked on pull-to-refresh. Each stage has a deadline (candidates 50 ms, features 30 ms, ranker 120 ms); on timeout the Mixer uses the previous stage's order, down to chronological, and sets degraded=true.

**Data model:**
- **Post** (Cassandra-style KV): partition post_id (time-sortable snowflake); author_id + created_at table for author timelines.
- **CandidateList** (Redis sorted set): key tl:{user_id}; member post_id, score created_at; 800 cap.
- **AuthorRecent** (Redis): ar:{author_id}, last 100 posts, many read replicas.
- **Features** (Aerospike/Redis): u:{user}, a:{author}, p:{post}; embeddings, affinities, counters.
- **RankedPage** (Redis): rp:{session_id}; **ImpressionLog** (Kafka to Parquet) with served feature vectors.

**Key APIs:**
- `GET /v1/timeline`: cursor, mode ranked or latest, limit 20; returns items, next_cursor, degraded.
- `POST /v1/posts`: idempotent on key for 24 h; returns before fanout.
- `GET /v1/timeline/new-count`: cheap ZCOUNT on the list, cached 30 s.
- `POST /v1/events`: batched impressions and engagements, deduped by event_id.
- `POST /v1/feedback`: hide or show less; applied to the session at once.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **GPU ranking:** prune to 300, distil the heavy model, cache scores per (user, post) for 10 minutes, skip heavy ranking for low-engagement users.
- **Fanout writes:** more Kafka partitions (256 by author), more workers, skip dormant users, prioritise recently active followers.
- **Celebrity reads:** the author-recent key is hot, so use many replicas plus a 1 s in-process cache.
- **Hot Redis shards:** hash by user_id, watch per-shard ops, rebalance slots.

**Failure modes:**
- **GPU pool down:** the Mixer times out at 120 ms and serves light-ranker order flagged degraded.
- **GPU overloaded at peak:** shed load by cutting heavy-ranker k from 500 to 200, then light ranker only.
- **Redis shard lost:** replica promoted in seconds; meanwhile a pull rebuild from the top 100 followees.
- **Kafka lag spike:** feeds go stale; autoscale fanout workers; page on lag over 30 s.
- **Feature store slow:** default features; breaker opens after 50% timeouts for 10 s.
- **Bad model:** 1% canary with automatic rollback on engagement or report-rate guardrails.
- **Region outage:** traffic shifts; caches there rebuild lazily for new users.

**Trade-offs chosen:**
- **Hybrid fanout over pure push or pull:** cheap reads for 99.9% of authors, no pathological celebrity writes.
- **Rank at read time over precomputed order:** scores need fresh engagement and context; precomputing wastes work on unread feeds.
- **Frozen session order over live re-rank:** no duplicates or jumps; new content goes to a banner.
- **Explicit half-life plus age feature:** stable, tunable, explainable across retrains.
- **800-id lists:** a couple of days for most users within about 3 TB; ranking needs only the freshest.
- **Degrade to light ranker, then chronological:** some feed beats a perfect feed that is late.

**What to measure:** p50/p99 latency per stage; fanout lag p99 and consumer lag; degraded-mode rate (target under 0.5%) and ranker timeouts; time spent per DAU and long-dwell rate; guardrails (hide, report, unfollow per 1,000 impressions); cache hit rates; GPU cost per 1,000 loads; duplicate impressions per session.

## Page 5. Say it in the interview

> "A home timeline for about 200 million daily users, mixing followed accounts and recommended posts, ranked by a model, with new posts visible in about 5 seconds and the first page under 400 milliseconds. My baseline is chronological push into per-user Redis lists; then I add ranking. Posts go to Kafka and fanout workers push ids to active followers, except celebrities, whom we pull at read time to avoid 50-million-way writes. On read, a mixer gathers about 1,500 candidates, hydrates them, prunes with a cheap ranker, scores 500 with a neural ranker on GPU, applies diversity and freshness decay, and caches the order for the session so pagination is stable. The bottlenecks are GPU ranking and celebrity fanout; every stage has a deadline with a fallback down to chronological."

**Key points to land:**
- Clarify scale, the in-network and recommended mix, freshness SLO and latency budget first.
- Hybrid fanout: push for most, pull for celebrities, skip dormant users.
- Precompute candidates, rank at read time.
- Funnel: about 1,500 candidates, light ranker to 500, heavy ranker, re-rank.
- Diversity, ads and safety live in the re-rank stage, not the model.
- Freshness is half-life decay plus a fanout-lag SLO under 5 s.
- Freeze order per session; new posts via a banner.
- Per-stage deadlines with fallback to chronological.
- Log served feature vectors to avoid training-serving skew.
- Ship ranker changes only through A/B tests with guardrails, 14 days minimum.

**Likely follow-ups:**
1. **A cheap "Latest" mode?** Same candidates plus celebrity pulls, sorted by time, no ranking; it shares hydration and doubles as the fallback.
2. **Cut GPU cost by 30%?** Better pruning to 300, distil the model, cache scores for 10 minutes, skip heavy ranking where it barely changes order.
3. **Safety demotions within a minute?** Labels go to a fast label cache read at hydration on every request, and the page cache re-filters on each cursor read.
4. **User follows nobody?** Cold start with recommended posts from popular and locale sources, onboarding interest picks and inline follow suggestions.
5. **Evaluate a ranker offline?** Replay logged impressions with counterfactual metrics (NDCG, inverse propensity weighting for position bias), check feature parity, then canary.

**Director layer:**
- **Cost drivers:** about 1,000 GPUs for heavy ranking at peak, about 3 TB of Redis, and 1-4M fanout writes per second.
- **Phasing:** chronological push baseline, then hybrid fanout, then the ranking funnel with deadlines and fallbacks, then exploration.
- **Team ownership:** feed infrastructure (fanout, caches, Mixer), ranking and ML platform (features, models), integrity, and experimentation.
- **Top risks:** ranking that amplifies outrage (guardrails, negative feedback), celebrity bursts delaying everyone, a ranking outage blanking the feed, and filter bubbles (exploration and diversity).
