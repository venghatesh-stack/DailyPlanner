# Graceful degradation when a dependency fails: recall card

> **Hook:** Tier every dependency → Parallel fan-out with deadlines → Breaker opens → Local static fallback → Brownout sheds tiers → Re-price at checkout

**P · Problem:** It's really a product policy problem: deciding in advance what is essential, what can be stale and what can disappear.

**N · Numbers:**
1. 50k page RPS x 12 dependencies = 600k calls/s, and dropping the 8 T2 calls saves 400k/s, so shedding optional work is the cheapest crisis capacity.
2. Bestseller lists are only 100 MB, so ship them to every pod hourly as a local fallback.
3. A 30-minute fulfillment outage queues about 11 GB of orders, so one Kafka topic absorbs it easily.

**H · Hard part:** Stopping a soft dependency from acting like a hard one, and never letting stale data move money.

**B · Boxes:** `Client → CDN → API gateway (priority shed) → Page assembly BFF → Catalog / Pricing / Cart`

Side path: `Checkout guard → Payment → Kafka orders topic → Fulfillment workers` when fulfillment is down.

**D · Decisions:**
1. Precomputed local fallbacks over on-demand ones, because they add no new dependency at failure time.
2. Stale display price validated at checkout over blocking the page, because browsing lives and money is still checked.
3. Accept and queue orders over rejecting checkout, because it keeps revenue and rare cancellations are compensated.

**F · Failures:**
1. Recommendations down → breaker opens and local bestsellers fill the slot; no latency or checkout impact.
2. Pricing down → stale display prices with a note, checkout blocked, T0 incident.

**C · Close:** "I start by separating what the user must do from what makes the page nicer. Every dependency gets a tier and a declared degraded mode. The page layer fans out in parallel with tight deadlines and breakers, so optional widgets drop out. Fallbacks are static, precomputed and local, because a fallback that calls another service is a new failure. Brownout levels shed whole tiers, orders queue when fulfillment is down, and we never charge a stale price."

**Quiz yourself:**
1. Why did recos take the page down for 9 minutes? → A synchronous 5 s timeout made a soft dependency hard.
2. How does brownout avoid flapping? → Up after 30 s of hot signals, down one step only after 5 minutes healthy.
3. Dependency returns price 0 with a 200? → Validation treats implausible data as a failure.
