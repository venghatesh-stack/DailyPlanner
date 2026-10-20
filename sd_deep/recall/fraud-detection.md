# Fraud detection pipeline (real-time risk scoring for suspicious actions): recall card

> **Hook:** Event → One batched feature read → Rules + GBDT → Score bands → Async labels retrain

**P · Problem:** It's really a low-latency classification problem fed by streaming aggregates, with labels that arrive months late.

**N · Numbers:**
1. 30k scored events/s at peak, each needing about 10 entity keys, so 300k key reads/s as one batched multi-get per decision.
2. 5M counter increments/s from 1M raw events/s, so Flink pre-aggregates and flushes each key every second, about 300k writes/s.
3. 1.3 TB of online features, so an SSD-backed Aerospike store, not RAM.

**H · Hard part:** Deciding in 100 ms with features identical to training, and learning from chargebacks that come 30-90 days late and are biased by our own blocks.

**B · Boxes:** `Checkout → Risk Decision API → Online feature store (Aerospike) → Rules + Model server → Decision`

Side path: `Events → Kafka → Flink → Aerospike`, and `Chargebacks → Label service → Lakehouse → Training`.

**D · Decisions:**
1. Streaming precompute over raw queries or nightly batch, because raw queries miss 10 ms and nightly misses minute-long attacks.
2. GBDT over logistic regression or deep models, because it gives the best accuracy per millisecond on tabular data and handles missing values.
3. Tiered fallback over failing open or closed, because it protects revenue and limits attacks that induce timeouts.

**F · Failures:**
1. Feature store shard down → features are missing; partial decisions can only challenge or review, never block.
2. Bad model triples the block rate → canary guardrail rolls back to the champion within minutes.

**C · Close:** "I split two paths. The synchronous path is a stateless decision API that pulls a few hundred precomputed features in one read, runs rules and a gradient-boosted model, and maps the score to allow, challenge, review or block. The asynchronous path computes velocity features in Flink, links accounts in a graph, runs review queues and retrains on logged feature snapshots. Failures degrade to safe defaults, and I measure loss in basis points against false positives."

**Quiz yourself:**
1. How do you avoid training-serving skew? → Log the exact feature snapshot with each decision and train on it.
2. Why not fail closed? → It turns a risk incident into a checkout outage.
3. How do you catch fraud rings? → Graph features: component size and fraud neighbours over shared devices and cards.
