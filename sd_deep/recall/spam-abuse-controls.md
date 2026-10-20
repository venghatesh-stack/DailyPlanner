# Spam and abuse controls (user-generated content): recall card

> **Hook:** Edge drops bots → Sync decision in 50 ms → Shadow-hide suspects → Kafka to async models → Cluster campaigns → Moderators label the middle

**P · Problem:** It's really an adversarial, economic classification problem: raise attacker cost without hurting genuine users.

**N · Numbers:**
1. About 7,000 decisions/s x 30 Redis ops = 210k ops/s, so a 12-shard Redis cluster holds the counters.
2. 0.5% of 20M items is 100k reviews/day, about 90 moderators per shift, so humans see only what machines cannot decide.
3. The SimHash index is about 10 GB, so it fits in memory on 4 nodes.

**H · Hard part:** Deciding in under 50 ms with high precision against attackers who probe thresholds and spread campaigns across thousands of fresh accounts.

**B · Boxes:** `Client → CDN + WAF → UGC Service → Decision Service → Redis counters + feature store → Verdict`

Side path: `Decisions → Kafka → Heavy ML and campaign clustering → Enforcement service`.

**D · Decisions:**
1. Shadow-hide over hard block, because hard blocks teach attackers the threshold instantly.
2. Trust-aware degradation over fail open or closed, because closed punishes everyone and open invites attackers to cause outages.
3. Rules plus ML over either alone, because rules ship in minutes with clear reasons and models generalise.

**F · Failures:**
1. Bad rule matches 30% of reviews → kill switch fires at 3x expected hit rate; decisions are replayed and content restored.
2. Feature store slow → partial features with conservative defaults; trusted users post, new accounts go author-only.

**C · Close:** "I treat spam as an economic problem: raise attacker cost while genuine users feel nothing. A synchronous Decision Service sits in every write path with a 50 ms budget: trust-aware rate limits, blocklists, SimHash near-duplicates and a small model, driven by rules analysts ship in minutes with shadow mode and kill switches. Decisions flow to Kafka, where heavy models and clustering catch campaigns. Moderators handle the uncertain middle, and suspects are shadow-hidden."

**Quiz yourself:**
1. How does SimHash find near-duplicates fast? → Split 64 bits into 4 blocks; within 3 bits, one block matches exactly.
2. How do you know it works? → Measure prevalence on labelled random samples, not block counts.
3. Why normalise text first? → Spaced-out or disguised phone numbers become visible to the extractor.
