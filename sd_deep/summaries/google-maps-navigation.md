# Design Google Maps (routing, ETA and navigation): the 5-page summary

Maps is three different systems glued together: a mostly static tile and place layer behind a CDN, a routing engine answering shortest paths on a huge road graph in milliseconds, and a live traffic pipeline turning a GPS firehose into per-segment speeds and ML-corrected ETAs. The single most important idea: fast routing needs heavy precomputation while traffic changes weights every minute, so separate topology (preprocessed in hours) from weights (customized in seconds).

## Page 1. The problem, scope and numbers

**Pitch:** tell people where things are, how to get there and how long it takes, with live traffic, on cheap phones and flaky networks, and sell the same answers as APIs to delivery and ride-hailing companies.

**Who uses it:** commuters (fastest route, accurate arrival, proactive reroute), two-wheeler riders (bike-allowed lanes, low data), delivery platforms (high-QPS matrix and ETA APIs), pedestrians (walking, offline maps), map data teams and privacy and legal.

**In scope:**
- **Tiles:** vector tiles at all zoom levels, day and night styles.
- **Search:** geocoding, reverse geocoding, autocomplete biased to viewport and location.
- **Routing:** waypoints, modes (car, two-wheeler, walk, cycle), avoid tolls, up to 3 alternatives.
- **ETA:** now or for a future departure; a distance matrix API.
- **Navigation:** turn-by-turn, lane guidance, voice, off-route detection and reroute.
- **Live traffic and incidents**, plus offline region downloads.

**Out of scope:** transit routing, indoor and AR, Street View, building map data from scratch, fleet optimisation (customers use the matrix API).

**Non-functional targets:**
- **Latency:** route compute p50 under 50 ms, p99 under 200 ms server side; under 500 ms end to end. Tiles p95 under 200 ms with over 95% CDN hits.
- **Accuracy:** 90% of trips within 10% of the ETA.
- **Freshness:** segment speeds updated every 1-2 minutes.
- **Availability:** 99.99% for routing and tiles; navigation keeps working offline.
- **Privacy:** raw traces kept at most 30 days; aggregates need at least 5 devices per segment window.

**Capacity math (100M DAU, 20M concurrent navigations at peak, 15k route requests/s):**
- **GPS ingest:** 20M x 1 fix/s x 50 B = 1 GB/s at peak; at 30% average, 26 TB/day, 780 TB for 30 days. So partition the firehose by geography and aggregate early.
- **Fresh traffic state:** about 100M covered segments x 16 B = 1.6 GB per minute. Small, so keep it in memory and push it to routing.
- **Routing memory:** India is 50M nodes, 120M edges, about 2x with shortcuts, x 32 B = about 8 GB. A 64 GB replica holds a country, so replicate per region, no graph sharding.
- **Routing CPU:** about 20 ms per request with unpacking and alternatives; 15k/s x 20 ms = 300 cores, about 1,000 with 3x headroom.
- **Tiles:** 100M x 50 tiles x 20 KB = 100 TB/day egress; origin under 5%. A CDN problem.
- **Sessions:** 20M x 5 KB = 100 GB of in-memory session state.

## Page 2. The architecture

```
 Clients: tiles     search      route / nav (WS)     GPS batches  Enterprise
    |                 |              |                    |          |
    v                 v              v                    v          v
   CDN          Search/Geocoder  API gateway          Ingestion   Matrix/ETA
    |           (text + S2)      |         |          (edge PoPs)    |
    v                            v         v              v          |
 Tile store <-+          Routing servers  Navigation    Kafka (S2 cell)
              |          (CCH/CRP, RAM) <-+ session svc     |
 Map data pipeline ----> graph + hierarchy|                 v
 (graph, tiles,                ^  |   ETA model (GNN)  Flink: map match
  partition, CH prep)          |  +-> refined ETA      + speed per minute
                               |                            |
                  weights every 60 s <-- Traffic state <----+
                                         store <-- Historical profiles
```

- **Map data pipeline:** merges sources and edits into a versioned, validated road graph, tiles and place index.
- **Tile service and CDN:** immutable versioned vector tiles, 30-day TTL, no invalidation.
- **Search and geocoding:** inverted text index plus S2 cell filtering, ranked by distance and popularity.
- **Routing servers:** a region's graph and hierarchy in RAM; route, alternatives and matrix queries.
- **GPS ingestion:** validates points, rotates anonymous ids, writes to Kafka by S2 cell.
- **Map matching and aggregation (Flink):** snaps traces to roads, speeds per segment per minute.
- **Traffic state and historical profiles:** live speed with confidence; typical speed per 15-minute slot of the week.
- **ETA model:** a GNN (graph neural network) over supersegments that corrects path-sum ETAs.
- **Navigation session service:** tracks active trips, pushes ETA updates and reroutes.

**Flow A: route request**
1. Origin and destination are snapped to graph edges with a spatial index.
2. A regional replica runs a bidirectional CH query on weights version v123; up to 2 alternatives.
3. The ETA model refines the path's time; the reply has polyline, maneuvers, ETA and traffic version.

**Flow B: GPS to live traffic**
1. Clients buffer 1 Hz fixes, upload every 5 s; ingestion drops points worse than 30 m accuracy.
2. Flink map-matches each trace and computes a robust median speed per segment per minute, needing 5 devices.
3. Blend with historical by confidence; incidents override. Every 60 s, changed weights go to routing, which customizes and swaps.

## Page 3. The core deep dives

### 1. Contraction hierarchies and customization
Dijkstra is correct but takes seconds per query on a country. A contraction hierarchy (CH) ranks nodes by importance and, offline, removes them in order, adding shortcut edges that preserve shortest paths. A query searches only upward from both source and target and meets at the best top node, settling a few thousand nodes instead of millions: about 1-5 ms. Plain CH needs hours to absorb new weights. Customizable CH (CCH) or CRP keeps the topology and contraction order fixed and only recomputes shortcut weights bottom-up (each shortcut = min over its lower triangles), in parallel per cell: a few seconds for India, so every 60 s is feasible. Queries pin a weights version; customization writes a new buffer and swaps a pointer, so no query sees mixed weights. Each travel mode is a separate metric on the same topology.

### 2. HMM map matching
Raw GPS is noisy, and under a flyover a point can snap to the road below. Each point gets candidate road positions nearby. An HMM (hidden Markov model) scores them: emission probability falls with distance (Gaussian, sigma 5-10 m); transition probability favours pairs whose route distance matches the straight-line distance. Viterbi picks the most likely road sequence, giving traversal times per segment.

### 3. ETA as a prediction
ETA = path sum of time-dependent speeds (live where fresh, historical slot otherwise) plus an ML correction for junction delays and congestion spread. For a 9 am departure tomorrow, use historical profiles at the time the car reaches each segment, not today's live speeds.

### 4. Navigation and rerouting
Guidance runs on the device from the cached route, so it survives tunnels. Off-route needs over 50 m from the route for 3 consecutive fixes plus heading mismatch, to avoid flapping. Every 1-2 minutes the server recomputes and suggests a switch only if it saves over 3 minutes and 10%.

**Data model:**
- **Road graph** (versioned files to RAM): CSR arrays of nodes and edges with length, class, per-mode access, turn restrictions.
- **Hierarchy:** contraction order, shortcuts with middle node for unpacking; rebuilt only on map changes.
- **Traffic speed** (in-memory per region): (region, segment_id) -> speed, samples, confidence, source.
- **Historical profile** (Bigtable): segment_id x 672 weekly 15-minute slots.
- **GPS point** (Kafka, then 30-day cold storage): anonymous id, keyed by S2 level-12 cell.

**Key APIs:**
- `POST /v1/routes:compute`: modes, waypoints, avoid, alternatives; returns routes and traffic_version.
- `POST /v1/distanceMatrix`: up to 50 x 50, via many-to-many CH, not N x M queries.
- `GET /v1/tiles/{style}/{z}/{x}/{y}.mvt?v=...`: immutable, CDN TTL 30 days.
- `POST /v1/locations:batch`: GPS every 5 s; anonymous id rotates every 24 h.
- `WS /v1/navigation/{session_id}`: progress up; ETA, reroute and incident pushes down.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **GPS firehose:** partition Kafka by S2 cell so aggregation is local; add edge PoPs and Flink parallelism.
- **Routing CPU:** add replicas per region (each holds the full country graph); cache popular routes for 60 s by rounded coordinates and traffic version.
- **Matrix APIs:** many-to-many CH costs S + T searches instead of S x T; rate-limit by matrix size.
- **Tiles:** versioned immutable URLs keep the CDN hit rate above 95%.
- **Flash crowds (200k requests after a cricket match):** route caching, autoscaling, API rate limits.

**Failure modes:**
- **Traffic pipeline lags:** keep the last weights; after about 10 minutes fall back to historical profiles; alert on freshness.
- **Routing overload:** shed to other replicas, serve cached routes, disable alternatives first.
- **Bad map release (wrong one-way):** off-route and reroute spikes reveal it; roll back the graph version in minutes.
- **Client offline:** on-device guidance with cached route and tiles, dead reckoning, resync by sequence.
- **ETA model down:** return the path-sum ETA with lower confidence; routing unaffected.
- **Region lost:** global load balancing moves users to a region with the same graphs; sessions rebuild from client state.
- **Spoofed jam:** device diversity, plausibility checks, discount drops with no neighbouring effect.

**Trade-offs chosen:**
- **CCH or CRP over A* or plain CH:** millisecond queries with minute-level traffic.
- **On-device guidance over server-driven:** survives network loss, saves bandwidth and server load.
- **1-minute windows over 10 s:** enough samples for robust speeds and k-anonymity, still fresh.
- **Path sum plus ML over pure ML:** explainable and fast, with ML fixing systematic errors.
- **Vector over raster tiles:** smaller, restylable, multilingual, better caching.
- **Reroute threshold over always-fastest:** avoids flapping; small gains are within ETA error.

**What to measure:** route latency by request type, ETA error (% within 10%, MAPE, large underestimates) by city, traffic freshness and coverage, unmatched GPS rate, off-route and reroute rates, tile hit rate, Kafka lag, session drops, customization time per region.

## Page 5. Say it in the interview

> "Maps is really three systems: map display with tiles and places, routing with ETA, and live navigation fed by traffic. Assume 100 million daily users, 15 thousand route requests a second and 20 million concurrent navigations sending a GPS point every second, with route p99 under half a second and ETAs within 10% for 90% of trips. Dijkstra on the whole graph is correct but takes seconds and ignores traffic. So an offline pipeline builds a versioned graph and vector tiles served from a CDN. Routing uses customizable contraction hierarchies: topology is preprocessed once, live weights are re-applied every minute, and queries take milliseconds. Traffic comes from GPS map-matched with an HMM, aggregated per segment per minute, blended with historical speeds, and an ML model corrects the ETA. Navigation runs on the device and the server pushes reroutes. I would measure ETA error, not just latency."

**Key points to land:**
- Three systems: tiles and places (CDN), routing and ETA (CPU in RAM), live traffic (GPS firehose).
- Contraction hierarchies search only upward, so country queries take milliseconds.
- CCH or CRP split topology (hours) from weights (seconds); that is what makes live traffic possible.
- Traffic: Kafka by S2 cell, HMM map matching, 1-minute aggregates, blend, push every 60 s.
- ETA is a prediction: time-dependent live and historical speeds plus an ML correction.
- Navigation on device; reroutes with hysteresis and a savings threshold.
- A country graph is about 8 GB: replicate per region instead of sharding.
- Immutable versioned tiles need no cache invalidation.
- Degrade: stale traffic to historical, overload to cached routes, offline to on-device.
- Privacy by design: rotating ids, trimmed trip ends, k-anonymous aggregates, 30-day raw retention.

**Likely follow-ups:**
1. **A 100 x 100 matrix?** Many-to-many CH: backward searches from targets leave buckets, forward searches from sources scan them; S + T searches, not S x T.
2. **Future departure?** Time-dependent profiles evaluated at the predicted arrival time at each segment, or a time-dependent CH.
3. **Two-wheeler routing in India?** Per-mode access flags for bike lanes, speed models from two-wheeler traces, a separate metric on the same topology.
4. **Everyone sent to the same side road?** Penalise low-capacity roads, spread users across alternatives when gains are small, update weights fast.
5. **Sudden closure not yet in GPS speeds?** Verified user or authority incidents become closures or penalties, picked up by the next customization within a minute.

**Director layer:**
- **Cost drivers:** about 1,000 routing cores, 100 TB/day of CDN egress, 1 GB/s GPS ingest with 780 TB of raw retention, and 100 GB of session memory.
- **Phasing:** start with tiles, search and historical-speed routing; add live traffic, ML ETA and enterprise APIs next.
- **Team ownership:** map data pipeline, routing engine, traffic and ETA ML, navigation clients, tiles and CDN, privacy.
- **Top risks:** a bad map edit sending drivers into danger, traffic poisoning, ETAs wrong in a city, location privacy breaches, routing overload at events.
