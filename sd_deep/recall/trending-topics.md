# trending topics: recall card

> **Hook:** Extract terms → Pre-aggregate and salt → Sketch counts → Score vs baseline → Publish per geo → Edge cache

**P · Problem:** It's really a streaming heavy-hitters problem, judged by velocity against a seasonal baseline rather than raw volume.

**N · Numbers:**
1. 2B term events/day, about 120k/s at peak, so a stream processor with spikes absorbed by Kafka.
2. Exact counts are about 10 GB per hour before the 500-geo split, so use approximate sketches.
3. 200k QPS at the edge with about 99% hits leaves about 2k QPS at origin, so precompute and cache.

**H · Hard part:** Spotting what is newly surging in bounded memory, despite hot keys, late events and bots.

**B · Boxes:** `Kafka posts → Extractor → Flink counter tier → Trend scorer → Redis trends:{geo} → CDN`

Side path: `Hourly baseline job → Baseline store` for hour-of-week medians.

**D · Decisions:**
1. Velocity vs hour-of-week baseline over raw volume, because it surfaces what is new, not what is always popular.
2. Event time with a 20 s watermark over processing time, because counts stay correct after backlogs.
3. Precompute every 30 s over per-read computation, because results are identical per geo and reads are cheap.

**F · Failures:**
1. Flink job crashes → restore from the 30 s checkpoint and replay offsets; the API serves the last list.
2. Spam surge → raise breadth thresholds; moderators freeze a geo's list.

**C · Close:** "Trending means discussed unusually more than normal, per country and city, visible within about two minutes. I extract and normalise terms, pre-aggregate for a second, then count in Flink with event-time minute buckets, Space-Saving for candidates, Count-Min for the tail and HyperLogLog for unique authors. Every 30 seconds a scorer compares each candidate with its hour-of-week baseline, weights by trust and breadth, merges variants, applies policy and publishes per-geo lists served from edge caches."

**Quiz yourself:**
1. How do you handle one term at 20k events/s? → Combine per second and salt the key 8 ways, then merge.
2. How do you stop flapping? → Hysteresis with a lower exit score and about 10 minutes minimum display.
3. Why event time? → Replayed backlog lands in the right minutes, so no fake spike.
