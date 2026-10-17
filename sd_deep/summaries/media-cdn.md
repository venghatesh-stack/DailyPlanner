# Design a CDN strategy for media delivery (video, images, live events): the 5-page summary

Media delivery is a bandwidth problem before it is a latency problem: one live cricket final needs about 40 Tbps, more than any origin or single CDN can carry. The single most important idea: make every byte immutable and cacheable, push it as close to viewers as possible (ISP caches and CDN edges), collapse misses so origin load does not grow with the audience, and steer each viewer to the best healthy cache using real user measurements.

## Page 1. The problem, scope and numbers

**Pitch:** deliver video, live events and images with start under 2 s and almost no stalls, survive any single CDN failing, and cut cost per GB by 40%.

**Why now:** one CDN is costly per GB, struggles at live peaks, is one outage from dark screens, and is poor in Tier-2/3 cities. **Users:** mobile viewers on 3-5 Mbps 4G, smart-TV viewers, app users scrolling thumbnails, and live-event ops engineers.

**In scope:**
- **Playback API:** returns primary and fallback CDN manifest URLs, a session token and a DRM licence URL.
- **Steering:** picks the CDN and cache per session from real user data, health, capacity and cost.
- **Cache hierarchy:** ISP-embedded caches and CDN edges, a regional shield, origin.
- **Fill service:** pushes predicted-popular VOD into ISP caches off-peak.
- **Live packaging** (2 s segments), edge image resizing, ops controls.

**Out of scope:** encoding ladder design, DRM licence server internals, the popularity model, peer-to-peer delivery, ultra-low-latency WebRTC live, and a global CDN outside India in phase 1.

**Non-functional targets:**
- **Throughput:** about 40 Tbps peak egress across CDNs and ISP caches, plus 20% headroom.
- **Start latency:** video start under 2 s p90; manifest plus first segment TTFB under 300 ms p90.
- **Availability:** 99.99% playback; no single CDN or region is a single point of failure.
- **Offload:** at least 98% of VOD bytes from cache; live origin egress independent of viewers.
- **Live latency:** 15-30 s glass-to-glass. **Images:** p95 under 200 ms on hit. **Tokens:** 6 h, session-bound.

**Capacity math (15M concurrent at a live peak, 2.5 Mbps average):**
- **Peak egress:** 15M x 2.5 Mbps = 37.5 Tbps, about 45 Tbps with headroom. So bytes must be spread over ISP caches and 2-3 CDNs, reserved weeks ahead.
- **ISP caches at 60%:** 27 Tbps / 100 Gbps per appliance = 270 minimum; deploy about 350 for N+1.
- **Live requests:** 15M / 2 s = 7.5M segment requests/s plus 7.5M manifest refreshes/s. So collapsing is mandatory.
- **Live origin load:** 6 renditions x 1 fetch per 2 s x 10 shield nodes = 30 requests/s, whatever the audience.
- **Daily VOD:** 3M x 3 Mbps x 6 peak-equivalent hours = about 24 PB/day. At Rs 0.25 per GB that is about Rs 60 lakh/day, so moving 60% to owned caches drives the business case.
- **ISP cache storage:** top 5% of a 2 PB catalogue = 100 TB; fits a 300 TB appliance.

## Page 2. The architecture

```
 CONTROL PLANE:  Playback API -> Steering svc    Fill svc     Ops controls
                 (token, DRM)    (RUM, health,   (predict,    (shift %,
                                  cost, capacity) push VOD)    cap bitrate)
       | manifest URLs (primary + fallback)  ^ QoE      | off-peak fill
       v                                     |          v
 Players (ABR, failover) ---segments---> ISP-embedded caches (60% of bytes)
       |                                     | miss
       +------------segments---------------> Commercial CDN A / B (anycast)
                                             | miss
                                             v
                          Regional shield / mid-tier (request collapsing,
                          consistent hashing, 2 regions)
                                             | miss
                             v                              v
               Object storage origin (VOD)       Live encoder + packager
               2 regions, content-hash keys      (2 s CMAF, 2 regions)
```

- **Playback API:** authorises, signs tokens, returns steered manifest URLs.
- **Steering service:** ranks caches and CDNs per (region, ISP, device) on RUM, capacity, cost.
- **ISP-embedded caches:** our appliances inside partner ISPs; most bytes, filled overnight.
- **Commercial CDNs:** burst capacity for live and coverage where we have no cache.
- **Regional shield:** collapses many edge misses into one origin fetch per object.
- **Origin and packager:** immutable VOD renditions; live segments and rolling manifests.
- **Fill service:** forecasts per-ISP popularity and schedules off-peak pushes.
- **Player SDK:** buffer-based ABR, fallback CDN switch, QoE telemetry.
- **Image edge service:** resizes to width buckets with normalised cache keys.

**Flow A: VOD playback start**
1. Player calls POST /v1/playback; the API checks entitlement and asks steering.
2. Response: ISP cache cluster as primary, CDN A as fallback, a 6 h token, DRM URL.
3. Player picks a starting rendition from measured throughput; the pre-positioned title hits on flash, start in about 1 s.
4. Player reports start time and throughput; steering learns.

**Flow B: live segment at peak**
1. Packager writes segment 1042 for every rendition, then updates the manifest.
2. Millions refresh the manifest (1 s edge TTL) and request 1042.
3. Each edge collapses misses into one shield fetch; each shield node into one origin fetch.
4. The segment is cached as immutable; every later request is a hit.

## Page 3. The core deep dives

### 1. Make everything cacheable
Media is cut into CMAF segments: 4 s for VOD, 2 s for live, 6 renditions in the ladder (CMAF is a common fragmented-MP4 format for HLS and DASH). Segment URLs carry the content hash, v/{hash}/{rendition}/seg_n.m4s, so an object never changes and can live at the edge with a year-long TTL. A re-encode creates a new hash and new URLs, so there is never a purge storm and never mixed old and new segments in one session. Only live manifests are short-lived (1 s TTL). The signed token is validated at the edge and then stripped from the cache key, otherwise every viewer would fragment the cache.

### 2. Tiered caching and request collapsing
When 15M viewers ask for segment 1042 in the same second, the first miss on a node starts one upstream fetch; every concurrent request attaches to that in-flight response and streams bytes as they arrive. This runs at ISP caches, CDN edges and the shield. The shield cluster uses consistent hashing with bounded loads, so each segment has one owner node; the hottest live segments are replicated into every node's RAM tier. The packager publishes a segment before the manifest references it, and a 404 is negative-cached for 1 s, so players never herd onto origin. Result: about 30 origin requests/s for 15M viewers.

### 3. Steering and multi-CDN failover
Steering scores each candidate per (region, ISP, device) on 1-minute RUM (real user measurement) aggregates of throughput and errors, capacity headroom and cost. Scores become probabilities, so traffic shifts smoothly and keeps exploring. Inside each CDN, its own DNS or anycast picks the PoP. Example: Shreya in Coimbatore gets her ISP's cache as primary and CDN A as fallback in the manifest. If CDN A degrades mid-match, steering lowers its weight within 30-60 s for new sessions, and Sethu's player, already on CDN A, switches to the fallback after 2 failed or very slow segments.

### 4. Push the head, pull the tail
The fill planner ranks titles by forecast hours per ISP cluster and pushes them between 02:00 and 08:00 at up to 70% of the fill link. The long tail is pulled through the shield. Second-hit admission keeps tail objects from churning disks, and the first 30 s of the top 20k titles are always kept, so starts are fast.

**Data model:**
- **Media object** (object storage, 2 regions): key v/{content_hash}/{rendition}/seg_{n}.m4s.
- **Steering weights** (Redis plus etcd): steer:{region}:{isp}:{device}, recomputed every 30-60 s.
- **QoE events** (Kafka to ClickHouse/Druid): partitioned by session; 1-minute rollups.
- **Cache placement** (PostgreSQL): (isp_cluster, content_hash); what is pre-positioned where.
- **Session token** (stateless HMAC): session, path scope, expiry, geo, signature.

**Key APIs:**
- `POST /v1/playback`: steering decision, 6 h session-bound token, DRM URL.
- `GET /{cdn}/v/{hash}/{rendition}/seg_{n}.m4s?tok=`: immutable segment; token not in key.
- `GET /{cdn}/live/{event}/{rendition}/index.m3u8?tok=`: the only short-TTL live object.
- `POST /v1/qoe`: batched every 30 s; feeds steering and dashboards.
- `GET /img/{asset}_{version}?w=360`: width snapped to 180/360/720/1080.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Edge egress:** grow the ISP cache share toward 60%+, add CDN reservations; cap the ABR ceiling regionally before anything stalls.
- **Hot live segments:** collapsing at every tier plus RAM replication of the hottest objects.
- **Interconnects:** place appliances where bytes per ISP and QoE gaps are worst.
- **Images:** request-rate bound, not bandwidth bound; width buckets stop variant explosion.

**Failure modes:**
- **CDN regional outage:** players fail over after 2 strikes; steering re-weights within 60 s; ops drains the region.
- **ISP cache cluster down:** marked unhealthy by heartbeats; sessions move to CDNs; watch peering capacity.
- **Shield node down:** only its 1/N of keys move; neighbours refetch once, with collapsing.
- **Origin or packager region down:** a redundant packager pair with identical segment numbering in the second region; VOD storage is replicated; stale-if-error for manifests.
- **Steering down:** Playback API uses last-known weights cached locally.
- **Signing key leak:** rotate immediately; short expiry limits exposure.
- **Demand beyond capacity:** regional ABR caps (for example 720p), then a waiting room for new sessions only.

**Trade-offs chosen:**
- **Multi-CDN plus own ISP caches over one CDN:** cheaper at 24 PB/day, better last mile, no single vendor; the cost is steering complexity.
- **Push head, pull tail:** pre-positioning pays only for predictable demand.
- **2 s live segments:** meets 15-30 s latency with half the requests of 1 s; 6 s is too slow for sports.
- **App-level steering over DNS alone:** uses RUM and cost and allows instant client failover.
- **Immutable versioned URLs over purges:** no purge storms, trivial rollback.
- **Lower quality for all over stalls for many:** cap bitrate first, admission control last.
- **Signed tokens at the edge over central auth calls:** nothing central can keep up with segment rates.

**What to measure:** start time p50/p90 by ISP, CDN and device; rebuffer ratio (target under 0.5%); delivered bitrate; playback failures; hit ratio and offload per tier; origin egress and shield collapse ratio; per-CDN RUM throughput; live headroom per ISP; live latency; cost per GB and commit use.

## Page 5. Say it in the interview

> "Media delivery is a bandwidth problem first. I will assume 3 million normal streams and 15 million in a cricket final, at about 2.5 megabits average: close to 40 terabits per second, which no origin and no single CDN can carry. The design has four parts. First, make everything cacheable: short CMAF segments with immutable, content-hash URLs; only live manifests are short-lived. Second, a cache hierarchy, ISP-embedded caches and CDN edges, a regional shield, then origin, with request collapsing so origin load does not grow with viewers. Third, steering: a control plane picks the CDN and cache per session from real user throughput, health and cost, with a fallback CDN in the manifest. Fourth, pre-position popular VOD into ISP caches overnight. If capacity runs short, I cap bitrate before anyone stalls."

**Key points to land:**
- Do the egress math first: 15M x 2.5 Mbps = 37.5 Tbps.
- Immutable content-hash URLs: no purges, year-long TTLs; only manifests short-TTL.
- Tiered caching plus collapsing: about 30 origin requests/s for 15M viewers.
- Consistent hashing with bounded loads makes a cluster one big cache.
- Push the predictable head off-peak; pull the long tail through the shield.
- Steer per session on RUM, capacity and cost; fallback CDN in every manifest.
- Strip tokens from the cache key; DRM and watermarking for premium.
- Cap the ABR ceiling regionally before anything stalls.
- Measure QoE (start time, rebuffer, bitrate) next to offload and cost per GB.

**Likely follow-ups:**
1. **Why not one big CDN contract?** One vendor outage would kill every stream, no vendor has unlimited capacity in every Indian ISP at peak, and competition keeps prices down.
2. **How do you prepare for a record event?** Forecast concurrency and bitrate mix, reserve capacity weeks ahead, check ISP headroom, load-test packager to shield, pre-agree bitrate caps, run failover drills, staff a war room.
3. **Where do you place your own caches?** By bytes per ISP, QoE gaps and interconnect cost; an appliance pays back when offloaded bytes times the CDN price exceeds its amortised cost.
4. **Live under 5 s?** Low-latency HLS/DASH with chunked CMAF transfer and shorter player buffers, accepting more requests and less jitter protection.
5. **Is steering actually helping?** Keep a small random holdout on static weights and compare start time, rebuffer and bitrate.

**Director layer:**
- **Cost drivers:** about Rs 60 lakh/day of delivery at blended rates; about 350 appliances of capex; commit-based CDN contracts. Route by cost when QoE is equal.
- **Phasing:** commercial CDNs abroad; in India start with the top 5 ISPs, then expand the cache share toward 60% by year end.
- **Team ownership:** playback and steering, cache fleet and ISP partnerships, live packaging, player SDK, and a live-event ops war room.
- **Top risks:** peak beyond total capacity, a CDN outage mid-match, origin overload on a cold release, piracy via leaked URLs, and CDN overage costs.
