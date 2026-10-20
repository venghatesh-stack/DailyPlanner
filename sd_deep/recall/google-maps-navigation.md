# Google Maps (routing, ETA and navigation): recall card

> **Hook:** GPS firehose → HMM map matching → Speeds per segment per minute → Customize weights every 60 s → CCH query in milliseconds → On-device guidance

**P · Problem:** It's really shortest paths on a huge, mostly static graph whose edge weights change every minute.

**N · Numbers:**
1. India's graph with shortcuts is about 8 GB, so a 64 GB replica holds a country and we replicate per region instead of sharding.
2. 20M concurrent navigations sending 1 fix/s is 1 GB/s of GPS, so partition the firehose by S2 cell and aggregate early.
3. 15k routes/s x 20 ms = 300 cores, so about 1,000 routing cores with 3x headroom.

**H · Hard part:** Fast routing needs hours of preprocessing, but traffic changes the weights every minute.

**B · Boxes:** `Client → API gateway → Routing servers (CCH in RAM) → ETA model → Navigation session`

Side path: `GPS batches → Kafka (S2 cell) → Flink map matching → Traffic state → weights every 60 s`.

**D · Decisions:**
1. CCH or CRP over A* or plain CH, because we get millisecond queries with minute-level traffic.
2. On-device guidance over server-driven, because it survives network loss and saves bandwidth.
3. Path sum plus ML over pure ML, because it stays explainable and fast while ML fixes systematic errors.

**F · Failures:**
1. Traffic pipeline lags → keep the last weights; after about 10 minutes fall back to historical profiles.
2. Bad map release with a wrong one-way → off-route spikes reveal it; roll back the graph version in minutes.

**C · Close:** "Maps is really three systems: tiles from a CDN, routing with ETA, and live traffic. Dijkstra takes seconds, so I use customizable contraction hierarchies: topology is preprocessed once and live weights are re-applied every minute, so queries take milliseconds. Traffic comes from GPS, map-matched with an HMM and aggregated per segment per minute, blended with historical speeds, and an ML model corrects the ETA. Navigation runs on the device, and I measure ETA error, not just latency."

**Quiz yourself:**
1. Why does a CH query take milliseconds? → It searches only upward from both ends and settles a few thousand nodes.
2. How do you serve a 100 x 100 matrix? → Many-to-many CH: S + T searches, not S x T.
3. When do you suggest a reroute? → Only if it saves over 3 minutes and 10%.
