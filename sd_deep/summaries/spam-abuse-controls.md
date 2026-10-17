# Design spam and abuse controls (user-generated content): the 5-page summary

This is a trust and safety platform in front of every review, Q&A answer, comment, chat message and listing. It decides allow, challenge, hold, shadow or block in under 50 ms, while a slower async tier clusters accounts, catches campaigns and feeds human moderators. The single most important idea: spam is adversarial and economic, so the goal is to raise attacker cost with layered, precise, fast-to-change defences, not to build one perfect classifier.

## Page 1. The problem, scope and numbers

**Pitch:** reviews, ratings and Q&A drive conversion, and they are under constant attack: paid fake reviews, competitor review-bombing, scam phone numbers and links, harassment, and account farms. Every spam item erodes trust; every genuine post wrongly blocked angers a real customer.

**Who uses it:** buyers (trustworthy reviews, safe chat), sellers (protection from review-bombing, fair appeals), T and S analysts (ship a rule in minutes), moderators (prioritised queue with context), legal (audit trail, takedown SLAs), surface teams (one API call, a clear verdict).

**In scope:**
- **Sync decision API:** verdict, reason codes and a decision id within 50 ms.
- **Rate limits and trust:** limits by IP, device, account and target; account trust score.
- **Content checks:** blocklists, URL and phone extraction, near-duplicates, text and image classifiers.
- **Rule engine:** versioned DSL rules with shadow mode, percentage rollout, kill switch.
- **Async tier:** heavy models, campaign clustering, retroactive enforcement.
- **Humans:** reports, moderator queue, appeals, an enforcement ladder from warning to ban.

**Out of scope:** payment fraud (shared signals only), recommendation and ranking, copyright workflows, KYC, building in-house multimodal models.

**Non-functional targets:**
- **Latency:** sync decision p50 under 15 ms, p99 under 50 ms; never add more than 50 ms to a write.
- **Availability:** 99.95% for the decision API, with graceful degradation below that.
- **Freshness:** counters reflect events within 1 s; blocklists propagate within 60 s.
- **Durability:** decisions and audit log kept 1 year, no loss (Kafka RF=3, acks=all).
- **Quality:** auto-block rules show over 99% precision in shadow; false positives under 0.1%; every action has a reason code.

**Capacity math (50M DAU, 20M UGC writes and 100M chat messages a day):**
- **UGC:** 20M / 86,400 = 230/s, 1,200/s at 5x peak. **Chat:** 1,150/s, 5,800/s peak, using a cheaper rule subset.
- **Counters:** about 7,000 decisions/s x 30 Redis ops = 210k ops/s. So a 12-shard Redis cluster at about 20k ops/s per shard.
- **Decision log:** 120M x 1 KB = 120 GB/day, about 10 TB/year compressed. So Kafka to object storage.
- **SimHash index:** 20M/day x 30 days x 16 B = about 10 GB. So it fits in memory on 4 nodes.
- **Human review:** 0.5% x 20M = 100k items/day / 400 per shift = 250 shifts, about 90 moderators per shift. So humans see only what machines cannot decide.
- **Model:** 1,200/s x 3 ms on CPU = a handful of cores. Throughput is modest; the hard parts are tail latency, hot counter keys and precision.

## Page 2. The architecture

```
 Client -> CDN + WAF + bot mgmt (per-IP and device limits, CAPTCHA)
             v
 API Gateway -> UGC Service (reviews, Q&A, chat, listings)
                    | sync call, 50 ms timeout
                    v
           Decision Service  <---> Redis (counters, rate limits)
           (rules, light model, <-> Online feature store (trust)
            blocklists, SimHash)
                    v verdict + decision event
           Kafka: ugc-events, decisions, reports
             |              |               |              |
             v              v               v              v
       Heavy ML       Campaign         Report svc     Decision log
       (text, image)  clustering           |          -> data lake
             |              |               v
             +-------> Enforcement svc <- Moderation queue -> labels
```

- **Edge (CDN, WAF, bot management):** drops floods and bots; TLS and device fingerprints, CAPTCHA.
- **Decision Service:** stateless; fetches features, runs rules and a light model, returns a verdict.
- **Redis counters:** sliding-window counts by actor, IP, device, target and content hash.
- **Online feature store:** account age, verified phone, orders, strikes, served under 5 ms.
- **Rule engine:** DSL rules compiled and hot-loaded every 30 s.
- **Content analyzers:** Aho-Corasick blocklists, URL and phone reputation, SimHash, image hashes.
- **Async scorers and clustering:** heavy models and account graphs on Kafka events.
- **Enforcement Service:** idempotent hide, strike, suspend; audit log; user notified with a reason.
- **Moderation platform:** priority queues, SLAs, double review, appeals.

**Flow A: synchronous write decision**
1. UGC service sends actor, device hash, IP, target, text and media ids.
2. One pipelined Redis round trip checks rate limits; trust features come from the feature store.
3. Analyzers run: normalised blocklist, URL and phone extraction, SimHash lookup over 24 h.
4. Enforced rules and the model run; shadow rules only log. The most severe verdict wins.
5. The post is stored as public, author_only, pending or rejected; the event goes to Kafka.

**Flow B: campaign detection**
1. Consumers link accounts by shared device, IP /24, payment instrument and SimHash cluster.
2. Every 5 minutes a job finds dense clusters (20 accounts, 80% of reviews on one seller in 2 hours).
3. High-confidence clusters are enforced as a group, ratings recomputed, signals pushed to blocklists.

## Page 3. The core deep dives

### 1. Layered sync decision in 50 ms
Features are fetched in parallel with a deadline. Before matching, text is normalised: Unicode NFKC, confusable letters mapped, zero-width characters stripped, spacing collapsed, number words and Devanagari numerals turned into digits. So "w h a t s a p p 9 8 7 6" becomes a phone number the extractor sees. Rate limits are multi-dimensional and trust-aware: a new account posting a phone number to more than 5 products in 10 minutes is held; a verified buyer with 50 orders is not. Counters are 60 one-minute buckets per key with a 2 h TTL, approximate within a few percent and constant memory. A retried request carries an idempotency key, so it gets the same verdict and is not counted twice.

### 2. Near-duplicates and campaigns
SimHash turns text into a 64-bit fingerprint where similar texts differ in few bits. Split it into 4 blocks of 16 bits: by the pigeonhole principle, two fingerprints within 3 bits share at least one identical block, so 4 exact-match tables find candidates fast. This catches "low and slow" attacks: 5,000 fresh accounts each posting once never trip per-account limits, but they share devices, IP ranges and near-identical text. Union-find over those links forms clusters that are enforced together and retroactively.

### 3. Rules that ship fast but safely
An analyst writes a DSL rule, declares an expected hit rate, and runs it in shadow. It is backtested on the last 24 h and must show over 99% precision before enforcing, then rolls out by percentage, all in under 15 minutes. A kill switch auto-disables a rule whose hit rate exceeds 3x the expected rate over 5 minutes; its decisions are replayed and content restored.

### 4. Shadow-hide and trust-aware degradation
Suspected spammers are shadow-hidden: the post is visible only to its author, so attackers cannot learn thresholds. Hard blocks are kept for illegal content. If the feature store is down, trusted accounts are allowed and new accounts' posts go author_only and are rescored when it recovers.

**Data model:**
- **Counter** (Redis): cnt:post:actor:{id}:{minute}; hash slot on the id so an actor's buckets co-locate.
- **AccountTrust** (feature store): account_id; age, phone_verified, orders_90d, strikes, device_accounts_count.
- **Decision** (Kafka to Parquet, 30 days in Elasticsearch): decision_id; partitioned by date and surface.
- **Case** (PostgreSQL): index (queue, status, priority); leased with SKIP LOCKED.
- **Enforcement** (append-only audit): action_id, subject, reason_code, source; reversals are new rows.

**Key APIs:**
- `POST /v1/decisions`: 50 ms timeout; returns verdict and reason codes; idempotent on surface, actor and content.
- `POST /v1/reports`: deduped per reporter and content; rate limited to stop report-bombing.
- `GET /v1/review-queue`: cases leased for 10 minutes so two moderators never collide.
- `PUT /v1/rules/{rule_id}`: mode shadow or enforce, rollout percent, expected hit rate; backtested first.
- `POST /v1/appeals`: routed to a different moderator.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot counter keys:** a viral product gets 50k reviews an hour; shard the key (key:0..15) and sum on read.
- **Feature fetch tail latency:** 1 s in-process cache for read-mostly trust features; deadline-based partial results.
- **Moderator capacity:** cluster-level cases collapse thousands of items into one decision.
- **Heavy models:** async on GPUs, separate Kafka topics so high-reach surfaces go first.

**Failure modes:**
- **Redis shard fails:** replica promoted in seconds; local conservative limits meanwhile; low-trust posts author-only.
- **Feature store slow (over 20 ms):** partial features with conservative defaults; breaker trips at 50% timeouts in 10 s.
- **Kafka lag:** autoscale consumers, alert at 30 s lag; author-only content waits but is not exposed.
- **Broken model (scores everything 0.99):** score-drift monitor, automatic rollback, no model-only blocks of trusted users.
- **Bad rule matches 30% of reviews:** kill switch at 3x expected rate; replay and restore.
- **Region outage:** stateless multi-region decisions; regional counters undercount slightly; rules replicated globally.

**Trade-offs chosen:**
- **Shadow-hide over hard block:** hard blocks teach attackers the threshold instantly.
- **Trust-aware degradation over fail open or closed:** closed punishes everyone; open invites attackers to cause outages.
- **Rules plus ML over either alone:** rules ship in minutes with clear reasons; models generalise.
- **Bucketed counters over exact logs:** a few percent error, constant memory even on hot keys.
- **One platform over per-surface filters:** attackers move across surfaces; shared signals catch them.
- **Automated gate plus reactive review over pre-moderation:** 20M items a day cannot be human-reviewed first.

**What to measure:** prevalence of violating content per 10k views from labelled random samples (target under 5); sync p99 and timeout rate; verdict mix per surface (alert on shifts); per-rule hit rate, precision and appeal overturns; model drift per language; async lag; report-to-action time against legal SLAs; moderator agreement; CAPTCHA solve rate.

## Page 5. Say it in the interview

> "I treat spam as an adversarial, economic problem: the goal is to raise attacker cost while keeping genuine users frictionless. There are two tiers. A synchronous Decision Service sits in every write path with a 50 ms budget: multi-dimensional, trust-aware rate limits in Redis, account trust features, normalised blocklists, URL and phone reputation, SimHash near-duplicates and a small model, orchestrated by a rule engine that analysts update in minutes with shadow mode and kill switches. Every decision goes to Kafka, where heavy models and account clustering catch campaigns and enforce retroactively. Moderators handle the uncertain middle, and their labels feed back into models and rules. Suspected spam is shadow-hidden, and if the platform degrades, trusted users keep posting."

**Key points to land:**
- Raise attacker cost; there is no perfect classifier.
- Layered defence: edge, account trust, content, behaviour aggregation, humans.
- Sync under 50 ms for cheap precise signals; async for heavy models and campaigns.
- Rate limit on many dimensions, trust-aware, not only per account.
- SimHash and account clustering catch campaigns that look innocent one post at a time.
- Rules for speed and explainability, models for generalisation; shadow mode and kill switches.
- Degrade trust-aware: trusted users allowed, new accounts author-only.
- Shadow-hide to deny attackers feedback.
- Measure prevalence and false positives, not block counts.
- Close the loop: labels feed models, rules and blocklists.

**Likely follow-ups:**
1. **How do you know it works if attackers just get quieter?** Measure prevalence on labelled random samples of what users see; block counts can fall because you are missing them.
2. **A brand-new attack at sale peak?** Spot it on anomaly dashboards, push an emergency hold rule, shadow an auto-block version, and let cluster jobs clean up what got through.
3. **Where does an LLM fit?** Async, for nuanced scams and code-mixed harassment, and to summarise context for moderators; too slow and costly for thousands of sync decisions per second.
4. **Paid reviews from real purchasers?** Verified purchase is not enough: look at reviewer-seller graphs, refunded low-value orders, timing and templates; enforce on the seller too.
5. **Bias against a language?** Per-language evaluation sets and false-positive targets as launch gates; normalising transliteration cuts both bias and evasion.

**Director layer:**
- **Cost drivers:** about 90 moderators per shift, GPUs for async image models, a 12-shard Redis cluster and about 10 TB/year of decision logs.
- **Team ownership:** T and S platform (decision service, rules), ML (models, clustering), moderation operations, policy and legal, and surface teams that integrate the API.
- **Phasing:** start with edge limits, blocklists and the rule engine in shadow; add async models, clustering and retroactive enforcement next.
- **Top risks:** a bad rule blocking genuine users during a sale, attackers probing thresholds, model drift, moderator burnout, and language bias.
