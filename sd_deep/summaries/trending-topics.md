# Design trending topics: the 5-page summary

Trending topics spots, within about two minutes, which terms are being discussed unusually more than normal in each country and city, from up to 120k term events a second. The single most important idea: trending means velocity against a seasonal baseline, not raw volume, and it is computed in a stream with bounded-memory sketches, event-time windows and trust checks, then precomputed per geo every 30 seconds and served from edge caches.

## Page 1. The problem, scope and numbers

**Pitch:** show people what is happening right now around them, quickly and fairly, without being stale, dominated by always-popular terms or manipulated by bots.

**Who uses it:** users (what is happening near me), trust and safety and moderators (keep spam and illegal terms off), legal (takedowns by country), product and growth (discovery and engagement).

**In scope:**
- **Extraction:** hashtags, entities and n-grams from posts, with language and geo.
- **Counting:** windowed counts and unique-author counts per term per geo.
- **Scoring** against seasonal baselines every 30 seconds.
- **Clustering** of variants (#IPL, #ipl, IPL 2026) with one display name.
- **Policy:** denylist, classifier and moderator actions before publishing.
- **Serving:** top 30 per geo with post counts ("25.3K posts"); audited moderation API.

**Out of scope:** personalised trends (phase 2), editorial summaries, the trend search results page, historical analytics, ads.

**Non-functional targets:**
- **Freshness:** list refresh every 30 s; a surge visible within 2 minutes p90.
- **Read latency:** p99 under 50 ms at the edge.
- **Availability:** reads 99.95%; a list up to 10 minutes stale is acceptable.
- **Accuracy:** count error under 2% for terms above trending thresholds.
- **Scalability:** 5x peak, about 120k term events/s, without lag growth.
- **Moderation:** a removal takes effect in under 60 s.

**Capacity math (500M posts/day, 4 terms per post, 500 geos):**
- **Term events:** 2B/day = about 23k/s average, about 120k/s at 5x peak. So a stream processor, with spikes absorbed by Kafka.
- **Exact counts:** 20M distinct terms an hour x 60 minute buckets x 8 B = about 10 GB per hour before the geo split; times 500 geos it explodes. So approximate sketches.
- **Count-Min Sketch:** 32k x 5 x 4 B = 640 KB per geo per minute; 500 geos x 60 buckets = about 19 GB worst case, 2-4 GB in practice since only active geos allocate.
- **Candidates:** 500 geos x 10k terms x (60 x 4 B + 3 KB HyperLogLog) = about 16 GB across the cluster. So state is a few tens of GB.
- **Scoring:** 500 x 10k candidates every 30 s = about 170k scores/s. Trivial CPU.
- **Serving:** 200k QPS at the edge with about 99% hits leaves about 2k QPS at origin. So precompute and cache.

## Page 2. The architecture

```
 Post svc -> Kafka posts (512 partitions)
                v
 Extractor (stateless): normalise, language, geo, trust, SimHash,
                |       1 s pre-aggregation
                v  Kafka term-events (key = hash(term), salted if hot)
 Counter tier (Flink): event-time minute buckets, CMS tail, HLL authors
                |
                v
 Per-geo candidates (Space-Saving, k = 10k)    Baseline store (hourly)
                |                                     |
                v                                     v
 Trend scorer (every 30 s): velocity vs baseline, trust, breadth,
   variant clustering, denylist + policy  <- Moderation console
                |
                v
 Redis trends:{geo} (versioned) -> Trends API -> CDN / edge (TTL 30 s)
```

- **Extractor:** tokenise, normalise case, Unicode and transliteration, find entities, resolve geo, tag trust.
- **Kafka term-events:** shuffles by term, salted for hot terms; buffers spikes and allows replay.
- **Counter tier (Flink):** event-time minute buckets, Space-Saving, CMS and HLL in checkpointed state.
- **Baseline service:** hourly job storing hour-of-week medians per (term, geo); EWMA fallback.
- **Trend scorer:** every 30 s per geo: velocity score, gates, clustering, policy, publish.
- **Trends store (Redis):** a ranked, versioned list per geo with an atomic pointer swap.
- **Trends API and CDN:** per-geo lists with a 30 s TTL and parent-geo fallback.
- **Moderation console:** denylist, remove and pin, with an audit log.

**Flow A: event to count**
1. A post is created; the extractor emits terms with geo, author trust and server timestamp.
2. It pre-aggregates (term, geo) per second; hot terms are salted 8 ways.
3. Flink adds to the minute bucket, HLL, Space-Saving and CMS.
4. A watermark at max_ts - 20 s closes buckets; events up to 2 minutes late still update them.

**Flow B: score and publish**
1. Every 30 s, pull merged candidates per geo; compute 5- and 60-minute counts and unique authors.
2. Score against the baseline, apply gates, cluster variants, apply policy, keep the top 30.
3. Write trends:{geo}:v{n}, swap the pointer; the CDN picks it up within 30 s.

## Page 3. The core deep dives

### 1. Velocity against a seasonal baseline
Raw volume always shows "good morning" and "cricket". Instead compare the last 5 minutes with the same hour of the week: ratio = (c5 / 5) / (baseline / 60 + 0.2), where the 0.2 smooths brand-new terms with no baseline. Score = log(1 + ratio) x log(1 + unique authors in 60 minutes) x (1 + 0.3 x acceleration). Terms below a minimum volume or author count for the geo score 0. A 5-minute window detects fast; the 60-minute gates keep it stable. Hysteresis (enter above one score, leave below a lower one, show for at least 10 minutes) stops flapping.

### 2. Bounded memory with sketches
Space-Saving keeps k = 10k counters per geo: a new term evicts the smallest and inherits its count as an error bound, so true heavy hitters are never lost. Candidates get exact minute counts in a 60-slot ring buffer: on each minute close, subtract the expiring slot and add the new one, so the sliding window costs O(1). The long tail goes to a Count-Min Sketch per geo-minute. HyperLogLog counts unique authors in about 3 KB per term.

### 3. Hot keys and event time
During breaking news one term can hit 20k events/s, and one key cannot be split by adding partitions. So pre-aggregate per second in the extractor (a combiner), salt the key into 8 sub-keys and merge downstream. Windows use event time from the server ingest timestamp, not client clocks. After an outage, replayed backlog lands in the right minutes, so there is no fake spike, and the scorer holds publishing while the watermark lags over 2 minutes.

### 4. Manipulation resistance
Weight counts by author trust; require breadth (minimum unique authors); drop a term if one author is over 2% of its volume; collapse copy-paste text with SimHash within 10 minutes. The denylist and policy classifier run before publishing; moderators can freeze a geo's list.

**Data model:**
- **TermEvent** (Kafka): term_id, display, geo, author_id, trust, simhash, ts, count; partition by term_id (salted).
- **CounterState** (Flink, RocksDB): key (term_id, geo); 60-slot rings of counts, weighted counts and HLLs.
- **Baseline** (Cassandra or Redis): partition (term_id, geo); hour_of_week, median, MAD, EWMA; 90-day TTL.
- **TrendList** (Redis): trends:{geo}:v{n} plus a pointer trends:{geo}.
- **Denylist / ModAction** (MySQL): pattern, scope, reason, actor, expiry; the audit trail.

**Key APIs:**
- `GET /v1/trends`: the top list for a geo; edge-cached 30 s, parent-geo fallback.
- `GET /v1/trends/{term}/posts`: posts for a trend, backed by search.
- `POST /internal/moderation/trends/remove`: audited; next cycle plus CDN purge.
- `PUT /internal/moderation/denylist`: patterns normalised like the extractor.
- `GET /internal/trends/debug`: explains why something trended.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot terms:** combiners and salting, not more partitions; watch per-task load skew.
- **Ingest spikes:** Kafka buffers; autoscale stateless extractors.
- **Stream state:** sketches and candidate pruning keep it at tens of GB; only active geos allocate.
- **Reads:** precomputed lists behind the CDN; reads never touch stream state.
- **Sparse cities:** scaled thresholds, and fall back to the state or country list when too few trends qualify.

**Failure modes:**
- **Flink job crash:** restore from the latest checkpoint (every 30 s) and replay offsets; the API serves the last list.
- **Scorer down:** last lists remain; after 10 minutes, mark stale and fall back to a slower batch list.
- **Kafka lag at peak:** autoscale; suppress publishing while watermark lag exceeds 2 minutes.
- **Redis lost:** the scorer republishes within 30 s; the CDN serves cached lists meanwhile.
- **Bad normalisation deploy merges terms:** canary on one geo, compare overlap, roll back and replay from Kafka.
- **Spam surge:** raise breadth thresholds dynamically; moderators freeze a geo's list.

**Trade-offs chosen:**
- **Sketches for the tail, exact counts for candidates:** bounded memory, exact numbers where shown.
- **Velocity vs hour-of-week baseline over raw volume:** surfaces what is new, not what is always popular.
- **Event time with a 20 s watermark over processing time:** correct after backlogs, small latency cost.
- **Both windows (5 minutes for velocity, 60 for gates):** fast detection with stability.
- **Precompute every 30 s over per-read computation:** identical results per geo and cheap reads.
- **Streaming over a 5-minute batch job:** batch is fine for v1 but detects in 5-10 minutes.

**What to measure:** detection latency against labelled events; moderator removals and spam among trends; Kafka lag and watermark delay; Flink checkpoint time, state size and backpressure; hot-key skew; API hit ratio and p99; click-through and geo coverage (geos with at least 10 trends).

## Page 5. Say it in the interview

> "Trending means discussed unusually more than normal, not just a lot, per country and city, refreshed every 30 seconds and visible within about two minutes. Input is 500 million posts a day, about 23 thousand term events a second and five times that at peak. A hashmap of exact counts fails on memory, on popularity bias and on hot keys. So I extract and normalise terms, pre-aggregate for a second, then count in Flink with event-time minute buckets, a Space-Saving top-k for candidates, Count-Min Sketches for the tail and HyperLogLogs for unique authors. Every 30 seconds a scorer compares each candidate's rate with its same hour-of-week baseline, weights by trust and breadth, merges variants, applies policy and publishes per-geo lists served from edge caches."

**Key points to land:**
- Trending = unusual velocity vs a seasonal baseline, not raw volume.
- Sketches bound memory: Space-Saving for candidates, CMS for the tail, HLL for authors.
- Event time with watermarks avoids fake spikes after outages.
- Minute buckets in ring buffers make sliding windows O(1).
- Hot keys need combiners and salting, not more partitions.
- Breadth and trust (unique authors, author-share cap, near-dup collapse) resist bots.
- Normalise and cluster variants across scripts (Tamil, Hindi, English, code-mixed).
- Precompute per-geo lists every 30 s and serve from the edge.
- Measure detection latency, precision (removals), lag and click-through.

**Likely follow-ups:**
1. **How would you personalise trends?** Keep geo candidates, then re-rank per user by interest affinity at read time; policy and breadth still apply globally.
2. **How do you evaluate detection?** Label known events from news wires, measure time-to-trend and recall, sample shown trends for relevance and spam, and A/B test click-through.
3. **Why not a batch job every 5 minutes?** Fine for v1, but detection becomes 5-10 minutes and spikes are diluted; streaming costs about the same.
4. **How do you stop flapping?** Hysteresis with a lower exit score and a minimum display time of about 10 minutes.
5. **Trending in your network?** Count terms within the user's followees; far more expensive, so only for active users.

**Director layer:**
- **Cost drivers:** a Flink cluster holding tens of GB of state, Kafka for 120k events/s peaks, NER and language models in the extractor, and human moderation.
- **Phasing:** v1 can be a 5-minute batch; then streaming counts, seasonal baselines and trust scoring; personalised trends in phase 2.
- **Team ownership:** stream platform, trends relevance (scoring, clustering), trust and safety with moderators, legal for country takedowns.
- **Top risks:** bot campaigns pushing propaganda, hot keys stalling the pipeline during big news, offensive terms trending, fake spikes after outage recovery.
