# Design a fraud detection pipeline (real-time risk scoring for suspicious actions): the 5-page summary

A fraud system decides in about 100 ms, inline on checkout, login or payout, whether an action is legitimate, using behaviour summarised over minutes to months, while the true labels (chargebacks) arrive 30-90 days late. The single most important idea: split a fast synchronous decision path (precomputed features, rules, model, thresholds) from an asynchronous platform (streaming features, graph, case review, labels and retraining), and keep online features identical to the ones the model was trained on.

## Page 1. The problem, scope and numbers

**Pitch:** stop chargebacks, account takeovers, coupon abuse, fake returns and payout fraud without blocking good customers; today's static rules block good buyers and take days to change.

**Who uses it:** shoppers (an OTP, not a block), analysts (a prioritised queue), risk strategists (backtested rules), ML engineers, support (reason codes) and finance.

**In scope:**
- **Evaluate API** for checkout, login, sign-up, refund and payout: decision, score, reason codes.
- **Rules engine:** block and allow lists, versioned rules with backtest and staged rollout.
- **ML scoring:** a GBDT (gradient-boosted trees) per event type, champion and challenger in shadow.
- **Streaming features:** velocity counts and sums over 5m to 30d windows, distinct counts, first-seen times.
- **Graph, cases and labels:** entity links for rings; analyst and chargeback outcomes become labels.

**Out of scope:** AML, KYC, card disputes, edge bot mitigation, listing and review fraud.

**Non-functional targets:**
- **Latency:** p99 under 100 ms end to end (p50 under 30 ms); feature fetch under 10 ms; model under 5 ms.
- **Availability:** 99.99% for the evaluate API, with a caller fallback.
- **Freshness and durability:** feature lag p99 under 5 s; events and decisions kept 2 years.
- **Business:** loss from 18 to under 8 bps of GMV; under 0.3% of good orders blocked or challenged; emergency rule in 15 minutes.

**Capacity math (50M scored events/day, 30k/s at sale peak; 1B raw events/day, 1M/s peak):**
- **Online store:** 200M entities x 100 values x 16 B = 320 GB; x 2 key overhead x 2 replicas = about 1.3 TB. So an SSD-backed store (Aerospike), not RAM.
- **Feature reads:** 30k/s x about 10 entities = 300k key reads/s, as one batched multi-get per decision.
- **Feature writes:** 1M events/s x 5 counters = 5M increments/s. So Flink pre-aggregates in state and flushes each key every 1 s, about 300k writes/s.
- **Scoring:** 500 trees of depth 6 = 0.5 ms per event per core; 30k/s needs 15 cores, plus 3x headroom. Scoring is cheap.
- **Storage:** 1 TB/day raw, 150 GB/day compressed; 2 years is about 110 TB in the lakehouse.
- **Review:** 0.1% of 5M orders/day = 5k cases x 3 min = 250 analyst-hours/day, about 35 analysts. Human capacity drives the thresholds.

## Page 2. The architecture

```
 Checkout / Login / Refund / Payout       Clickstream / device SDK
        | sync evaluate (100 ms)                  | events
        v                                         v
 Risk Decision API ---- decisions ----------> Kafka (risk.events,
 (rules, model,                                risk.decisions)
  thresholds)                                 |          |
   |  mget         | score                    v          v
   v               v                    Flink stream   Graph svc
 Online feature  Model server           (windows, HLL) (entity links)
 store (Aerospike) <------ upserts every 1 s -+----------+ ring feats
   ^                                          |
   | backfill                                 v
 Lakehouse (point-in-time) <-- labels -- Label svc <- chargebacks
   |                                          ^
   +-> training -> shadow -> canary      Case mgmt (analysts)
```

- **Kafka:** durable streams for events, decisions and labels, keyed by the primary entity.
- **Risk Decision API:** stateless; fetch features, rules, model, thresholds, reasons, within a 100 ms deadline.
- **Rules engine:** versioned rules and lists in priority order; backtest and shadow modes.
- **Model server:** GBDT per event type plus shadow challengers; returns score and top contributors.
- **Flink feature engine:** event-time windowed counts, sums and HyperLogLog distinct counts.
- **Online feature store:** one record per entity; batched multi-get under 10 ms.
- **Graph service:** account-device-card-address links; component size, fraud-neighbour counts.
- **Case management:** queues prioritised by score x order value; outcomes become labels.
- **Label service and training:** joins chargebacks and reviews to decisions; trains weekly.

**Flow A: inline checkout evaluation**
1. Checkout calls evaluate with user, device, card fingerprint, IP and amount; deadline 100 ms.
2. One multi-get of about 10 keys and 300 features, 10 ms budget; missing values stay missing.
3. Add request-time features (amount vs 90-day average, account age); hard lists short-circuit.
4. Model scores in about 1 ms; segment thresholds map score to allow, challenge, review or block.
5. Return decision and reasons; publish the decision with its feature snapshot to Kafka asynchronously.

**Flow B: label feedback**
1. A chargeback arrives 45 days later; the label service maps it to the decision_id.
2. Weekly training uses the logged feature snapshots; shadow for a week, canary at 5%, then champion.

## Page 3. The core deep dives

### 1. Streaming velocity features without skew
Exact sliding windows per event are costly. Each key keeps a ring of 1-minute buckets for the 1-hour window and 1-hour buckets for 7 days; the window value is the sum of buckets newer than now minus the window. Distinct counts (accounts per device) use HyperLogLog, about 1.5 KB at 2% error. Windows run on event time with watermarks and 30 s allowed lateness, so an offline phone's late events land in the right bucket; counters dedupe by event_id so retries never inflate velocity. To avoid training-serving skew, the decision logs its exact feature snapshot (log-and-wait), and features are defined once for online and batch backfill.

### 2. Deadline-bounded decisions and safe fallbacks
Each stage gets a slice of the 100 ms. If the feature fetch overruns, the model scores with missing values (GBDTs handle them natively) and the decision is flagged partial; a partial decision can never block, only challenge or review. If the whole call times out, the caller's pre-agreed fallback applies: allow under 2,000 INR, hold above, and re-score every fallback asynchronously with cancellation before shipment. Failing closed would turn an incident into a checkout outage; failing fully open would invite attackers to induce timeouts. Evaluate is idempotent on event_id for 24 h.

### 3. Thresholds, bands and delayed labels
Score bands: under 0.2 allow, 0.2-0.6 challenge (OTP or 3DS), 0.6-0.85 hold for review, over 0.85 block, tuned per segment. Thresholds maximise prevented loss while keeping the good-user block rate in budget and the review band within analyst capacity. Labels are late and biased: blocked orders never get labels. So use early proxies (review outcomes, complaints, issuer alerts), and allow a small exploration slice (0.5% of medium scores, with step-up) for unbiased labels.

### 4. Graph features for rings
A ring of 2,000 accounts sharing 30 devices and 5 addresses looks normal one event at a time. Edges like user-device feed component size and fraud-neighbour counts, with nightly connected components plus incremental union-find. Super-nodes (a buggy SDK's device id 000000) are capped or excluded.

**Data model:**
- **Online features** (Aerospike, RF=2, key hash): key card:fp123; bins cnt_1h, sum_amt_24h, distinct_users_7d_hll, first_seen; 90-day TTL.
- **Decisions** (Kafka to Iceberg/Delta, partitioned by date and event type): decision_id, features_snapshot, score, model and rules version.
- **Labels** (Postgres plus lakehouse): PK (decision_id, source); chargeback beats review beats heuristic.
- **Cases** (Postgres): priority = score x amount; analysts dequeue with SKIP LOCKED.

**Key APIs:**
- `POST /v1/risk/evaluate`: decision, score, reasons, decision_id; idempotent on event_id.
- `POST /v1/risk/feedback`: a fraud or legit label; deduped by (decision_id, source).
- `POST /v1/rules`: shadow or active; active needs a backtest id, except emergency list adds.
- `POST /v1/rules/{id}/backtest`: hits, precision and loss prevented on matured labels.
- `POST /v1/cases/{id}/decision`: approve, cancel, ban or freeze payout; emits a label.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Feature writes:** pre-aggregate in Flink keyed state and flush per key every second.
- **Feature reads:** one record per entity, one batched read per decision, SSD-backed shards.
- **Hot keys:** a corporate NAT IP shared by 50,000 users; normalise against its own baseline, cap IP weight, cache super-hot keys in the API.
- **Load isolation:** separate deployments for checkout, login and refund; shed shadow models first.
- **Human review:** review capacity is fixed, so thresholds and segment bands absorb volume.

**Failure modes:**
- **Decision API p99 hits 300 ms:** callers apply tiered fallbacks; fallbacks re-scored async; shadow models shed; page on fallback rate.
- **Feature store shard down:** affected features missing; partial decisions only challenge or review; replica promoted.
- **Flink lag or restart:** features stale; stricter request-time checks on high-value orders; restore from checkpoint and catch up.
- **Bad model (block rate triples):** canary guardrail rolls back to the champion within minutes; blocks become challenges.
- **Over-broad emergency rule:** auto-disables if hits exceed 5x the backtest estimate.
- **Kafka degraded:** decisions still return; emission buffers locally and audit is back-filled.
- **Label pipeline broken:** pause training rather than train on missing labels; keep serving.
- **Sale-day shift:** per-segment block-rate guardrails raise thresholds or convert blocks to challenges.

**Trade-offs chosen:**
- **Streaming precompute over raw queries or nightly batch:** raw queries miss 10 ms; nightly misses attacks that unfold in minutes.
- **GBDT over logistic regression or deep models:** best accuracy per millisecond on tabular data, missing-value handling, explanations.
- **Aerospike on SSD over Redis in RAM:** 1.3 TB at sub-2 ms p99 for a fraction of the RAM cost.
- **Bands over blocking:** friction recovers good customers; blocks only for high-precision cases.
- **Tiered fallback over fail open or closed:** protects revenue and limits induced-failure attacks.

**What to measure:** loss in bps of GMV, false-positive rate and challenge pass rate, decision mix per segment, precision and value-weighted recall on matured labels, latency and partial-decision rate, Flink lag, drift (PSI), review queue SLA, rule hit rate versus backtest, chargeback rate against network thresholds.

## Page 5. Say it in the interview

> "We score checkouts, logins, sign-ups, refunds and payouts. Checkout and payout are inline with a 100 millisecond p99 budget at up to 30 thousand events a second, and the answer is allow, challenge, review or block. Ground truth, the chargeback, arrives up to 90 days later. So I split two paths. The synchronous path is a stateless decision API that pulls a few hundred precomputed features in one batched read, runs hard rules and a gradient-boosted model, and maps the score to an action with per-segment thresholds and reason codes. The asynchronous path is a Flink pipeline computing velocity features, a graph linking accounts through shared devices and cards, a review queue, and a label loop that retrains on point-in-time-correct features. Feature fetch is the bottleneck, failures degrade to safe defaults, never blocks, and I measure loss in basis points against false positives on good customers."

**Key points to land:**
- Two paths: a 100 ms synchronous decision and an asynchronous learning platform.
- Precompute features in event-time Flink into a sharded store; one batched read per decision.
- Rules for known patterns and emergencies, GBDT to generalise, segment thresholds to act.
- Accuracy is meaningless with rare fraud: measure loss in bps against false positives.
- Logged feature snapshots and point-in-time joins prevent skew and leakage.
- Labels are 30-90 days late and biased by our blocks: proxies plus exploration.
- Graph features catch rings; cap super-nodes.
- Deadlines, tiered fallbacks, idempotent event_ids, bulkheads; never hard-block on missing data.

**Likely follow-ups:**
1. **A brand-new attack?** Watch feature shifts, new-account cohorts sharing attributes, graph growth and heavy hitters on BINs and IPs; analysts write a rule within the hour.
2. **How do you explain a decision?** Rule reasons and top model contributors map to readable categories; customers see a generic message, support sees details.
3. **Card testing with 5,000 stolen cards?** Velocity on decline rate, per-device and per-BIN attempts, distinct cards per device; an emergency rule plus CAPTCHA or 3DS.
4. **Why not fail closed?** It turns a risk incident into a checkout outage; allow small orders, hold large ones and re-score asynchronously.
5. **First build with a small team?** Event logging with snapshots, a rules engine with lists and backtests, a few velocity features; then a GBDT; graph later.

**Director layer:**
- **Cost drivers:** the 1.3 TB online store, Flink at 1M events/s, 110 TB of lakehouse, about 35 analysts.
- **Phasing:** logging and rules first, then ML on logged data, then graph and exploration once the feedback loop is solid.
- **Team ownership:** risk platform, data science, trust and safety (rules, cases), checkout (fallbacks).
- **Top risks:** false positives during a sale, training-serving skew, fraudsters probing rules, and a risk outage blocking checkout.
