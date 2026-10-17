# Design "suggested friends" (People You May Know): the 5-page summary

Suggested friends is link prediction on a graph of billions of people: find who a user probably knows and will connect with. The single most important idea: the best signal (mutual friends, two hops away) is far too expensive to compute per request, so precompute candidates offline, patch them with nearline deltas within a minute, and keep the online path to one-hop lookups, a ranker and hard safety filters that fail closed.

## Page 1. The problem, scope and numbers

**Pitch:** help users find people they actually know, so the graph grows and they stay, without ever being creepy or unsafe.

**Who uses it:** new users (reach 10 friends fast), established users (reconnect after a life change such as a new job or city), trust and safety (no unsafe suggestions), growth and ML teams (acceptance, retention).

**In scope:**
- **Suggestions:** up to 20 ranked people, each with a reason such as "12 mutual friends".
- **Exclusions:** never show friends, pending requests, dismissed, blocked or opted-out users.
- **Dismiss:** permanent suppression for that pair.
- **Contact upload:** opt-in, hashed, matchable and deletable.
- **Freshness:** candidates updated within a minute of a new friendship or signup.
- **Impression caps and logging** for rotation, training and analytics.

**Out of scope:** group and page recommendations, notifications for suggestions, spam classifier internals, client UI.

**Non-functional targets:**
- **Latency:** p99 under 200 ms, p50 under 60 ms.
- **Availability:** 99.9%; failure means fewer suggestions, never unsafe ones.
- **Freshness:** batch daily, nearline deltas under 60 s; the daily pipeline finishes within 6 hours.
- **Consistency:** blocks and dismissals take effect immediately, checked at read time.
- **Privacy:** contact data hashed, deletable within 30 days, consent logged.

**Capacity math (2B users, 1B MAU, 300 friends on average, 50k QPS peak):**
- **Edges:** 2B x 300 / 2 = 300B undirected edges, about 2.4 TB per direction at 8 bytes. So the graph lives in a sharded store, not one machine.
- **Two-hop pairs:** 300 x 300 = 90k pairs per middle node; 2B x 90k = 1.8 x 10^14 raw pairs. So two-hop is a batch job with hub sampling and top-500 pruning, never online.
- **Candidate store:** 2B x 500 candidates x 20 B = 20 TB (about 10 KB per user). So serve it from a read-only, bulk-loaded KV store.
- **Online reads:** 50k QPS x about 5 KV operations = about 250k KV ops/s. Modest, so the online path stays one hop only.
- **Ranking:** 50k QPS x about 700 candidates = 35M scores/s; GBDT at about 1M scores/s per core is 35-50 cores per region. So a cheap tree model fits the budget.
- **Nearline:** 100M new friendships/day = about 1.2k/s; up to 300 deltas each = about 350k delta writes/s. So deltas go to a fast store with a short TTL.

## Page 2. The architecture

```
 OFFLINE (daily)
 Graph snapshot + contacts + profiles -> Spark: FoF join, Adamic-Adar,
   PPR walks, org/school matches -> top 500 per user -> bulk load
                                                          |
                                                          v
 NEARLINE (seconds)                              Candidate KV (versioned)
 friend_added -> Kafka -> Flink 2-hop deltas -> Delta store (Redis, 48h)
                                                          |
 ONLINE (p99 < 200 ms)                                    v
 Client -> API GW -> Suggestion service: merge batch + delta candidates
                         |  -> Graph service: friends, pending, blocks
                         |  -> filters + policy (fail closed)
                         |  -> Ranker (GBDT, p(send and accept))
                         v
                 diversify + impression caps -> 20 suggestions + reasons
 impressions / sends / accepts -> Kafka -> training data + counters
```

- **Graph service:** one-hop friends, pending and blocks; TAO-like cache over MySQL, sharded by user_id.
- **Batch pipeline (Spark):** mutual-friend join, Adamic-Adar, PPR walks, profile matches; top 500 per user.
- **Candidate KV:** read-only, versioned dataset with atomic swap and rollback.
- **Nearline processor (Flink):** turns new friendships, signups, contact matches into fresh candidates.
- **Delta store (Redis):** recent candidates with a 48-hour TTL.
- **Contact matching:** keyed-hash contact index with consent and deletion.
- **Suggestion service:** merge, filter, rank, diversify, explain, cap impressions.
- **Ranker:** GBDT on about 150 features predicting send and accept.
- **Event log (Kafka):** impressions and outcomes for training and caps.

**Flow A: serve suggestions**
1. Check the per-user response cache (10 minutes).
2. Read batch and delta candidates in parallel.
3. Fetch friends, pending, blocks and dismissals; filter.
4. Rank with GBDT; on timeout, order by Adamic-Adar.
5. Policy filters, diversify, cap; return 20 and log impressions.

**Flow B: new friendship freshness**
1. Shreya accepts Sethu's request; friend_added goes to Kafka.
2. Flink reads Sethu's friends and writes them as candidates for Shreya (and the reverse).
3. Shreya's cache is invalidated; her next request shows them.

## Page 3. The core deep dives

### 1. Two-hop candidates in batch, with hub sampling
Self-join edges on the middle node: for each person m, every pair (a, b) of m's friends who are not yet friends is a candidate pair. Weight each shared friend by 1 / log(degree of m); this is Adamic-Adar, which says a mutual friend with 300 friends is a stronger hint than one with 5 million. Hubs with more than 5,000 friends are sampled down to 5,000, which stops the quadratic blow-up. Sum per pair, keep the top 500 per user, validate row counts and score distributions against yesterday, then bulk-load and swap the version atomically.

### 2. Freshness with nearline deltas
A daily batch alone feels stale the day you add a friend. When Shreya and Sethu connect, Flink reads Sethu's one-hop friends and writes them as candidates for Shreya with mutual = 1, and the reverse. Deltas live 48 hours; once the next snapshot covers them they expire. If Flink lags, freshness falls back to batch cadence but correctness is unaffected.

### 3. Many candidate sources, one ranker
Mutual friends is the strongest signal (triadic closure: friends of friends tend to become friends). Other sources add recall: personalised PageRank (PPR) by random walks (2,000 short walks of up to 3 steps, restarting at the user with probability 0.3, top 200 visited), consented contacts, and same school, employer or city. The ranker predicts send-and-accept, not clicks or sends, so spammy one-sided requests are not rewarded. Diversify so no source is over 60% of the list.

### 4. Safety and privacy, fail closed
Hard filters run on every request: blocks either way, dismissals, opt-outs, no adult-to-minor suggestions. If the block or policy lookup fails, return an empty list, not a risky one. Reasons never reveal private signals (never "in your contacts"). Unfriending creates a long two-way suppression.

**Data model:**
- **Friendship edge** (MySQL + cache): user_id, friend_id, created_at, state; shard by user_id, stored both directions.
- **CandidateList** (read-only KV): user_id -> 500 candidates with mutual, Adamic-Adar, PPR and sources.
- **DeltaCandidates** (Redis hash): key dc:{user_id}, TTL 48 hours.
- **Suppression** (Cassandra): partition user_id; candidate, reason, until.
- **ContactIndex** (sharded KV): keyed hash of contact -> owners and uploaders.

**Key APIs:**
- `GET /v1/suggestions`: 20 suggestions with reasons and a request_id for outcome logging.
- `POST /v1/suggestions/{user_id}/dismiss`: permanent suppression for the pair.
- `POST /v1/friend-requests`: idempotent per pair, rate-limited.
- `POST /v1/contacts/upload`: keyed hash on the client, async matching.
- `PUT /v1/settings/discoverability`: removes the user from others' candidates at read time.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Batch two-hop:** the heavy part; hub sampling, salted joins on skewed keys, pruning to top 500, job SLAs with alerts.
- **Candidate store:** read-only and bulk-loaded, so online writes never contend with it.
- **Online graph lookups:** one hop only, cached and sharded by user_id.
- **Ranking:** GBDT on CPU scales linearly; a 40 ms budget with an Adamic-Adar fallback.
- **Popular users flooded with requests:** global per-candidate impression caps and exposure tracking.

**Failure modes:**
- **Candidate KV down:** serve delta, org/school and contact candidates; fewer results, alert.
- **Ranker timeout:** order by Adamic-Adar and flag the response as degraded.
- **Block or policy lookup fails:** fail closed, return empty suggestions.
- **Bad batch output:** validation blocks the swap, or roll back within minutes.
- **Batch misses its window:** yesterday's version is still valid plus deltas; alert on staleness over 36 hours.
- **Flink lag:** freshness degrades to batch cadence only.
- **Contact index corruption:** disable the contact source by flag; rebuild from consented uploads.

**Trade-offs chosen:**
- **Batch plus nearline over online two-hop:** online is 90k edge reads for a typical user and millions for a hub; deltas buy freshness cheaply.
- **Send-and-accept label over clicks or sends:** it aligns sender and recipient and reduces spam.
- **Versioned bulk load over online writes:** protects the serving store, gives atomic swap and rollback.
- **Sample and weight hubs over dropping them:** keeps some signal, avoids quadratic cost.
- **Hard filters that fail closed over model-learned safety:** deterministic and auditable.
- **GBDT now, DNN with embeddings later:** a cheap strong baseline on graph features.

**What to measure:** accepted requests per 1,000 impressions by surface and source; send, accept, dismiss and report rates; recall@20 and ranker AUC on time-split data; new-user time to 10 friends; p50/p99 latency and degraded or fail-closed response rates; batch duration and data age; delay from friend_added to visible.

## Page 5. Say it in the interview

> "This is link prediction on a huge graph. Assume 2 billion users with 300 friends each, about 50k requests a second, p99 under 200 ms, and the goal is accepted requests, not clicks. Counting friends of friends per request means 90,000 edge reads for a typical user and millions for a well-connected one, so I precompute. A daily Spark job joins edges on the middle person, weights mutual friends by Adamic-Adar, samples hubs, adds random-walk and profile candidates, and bulk-loads the top 500 per user as a versioned dataset. A Flink job writes two-hop deltas the moment someone adds a friend, so the page feels fresh. Online, I merge both sources, filter with live one-hop lookups, rank with a model that predicts send and accept, diversify and cap impressions. Safety filters fail closed."

**Key points to land:**
- Frame it as link prediction; mutual friends (triadic closure) is the strongest signal.
- Two-hop is too expensive online: precompute in batch, patch with nearline deltas.
- Adamic-Adar and hub sampling tame celebrity skew.
- Several candidate sources (mutual friends, PPR walks, contacts, org) feed one ranker.
- Optimise send-and-accept, not clicks or sends.
- Blocks and dismissals are checked at read time, so they apply immediately.
- Hard policy filters fail closed; reasons never reveal private signals.
- Versioned bulk loads with validation and rollback protect against bad batches.
- Measure acceptance per impression, dismiss and report rate, recall@k and freshness.

**Likely follow-ups:**
1. **How would you use embeddings?** Train node2vec or GraphSAGE embeddings, index them in an ANN store as another candidate source, and use similarity as a ranker feature.
2. **How do you avoid suggesting an ex someone unfriended?** Unfriending writes a long suppression in both directions; removed connections never resurface.
3. **What if the model favours popular users?** Calibrate degree as a feature, cap per-candidate impressions globally and track the exposure distribution.
4. **How do you handle a 100M-user market launch?** Lean on consented contacts, location, onboarding interests and invite graphs, plus region-local candidates.
5. **How do you measure long-term impact?** Long-running holdouts, tracking friend growth, retention and messages between suggested connections over months.

**Director layer:**
- **Cost drivers:** the daily two-hop batch (hundreds of trillions of raw pairs before pruning), the 20 TB candidate store and ranker cores across regions.
- **Phasing:** start with batch mutual friends and a GBDT ranker; add nearline deltas, PPR and contacts, then embedding candidates.
- **Team ownership:** graph platform, offline candidate pipelines, ranking and ML, trust and safety with privacy review of every new signal.
- **Top risks:** creepy suggestions revealing private relationships, spammers abusing suggestions, a failed batch serving stale lists, and hub skew blowing the batch window.
