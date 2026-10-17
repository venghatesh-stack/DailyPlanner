# Design Netflix / YouTube-style video streaming: the 5-page summary

Video streaming is two systems welded together: a batch encoding pipeline that turns one master file into hundreds of segment files, and a delivery network that pushes about 90 Tbps as close to the viewer as possible. The single most important idea: the bottleneck is bandwidth, so serve 95%+ of bytes from caches inside ISPs, let the client pick quality per segment (adaptive bitrate), and keep the cloud control plane small and highly available.

## Page 1. The problem, scope and numbers

**Pitch:** instant, high-quality playback on any screen and any network, at the best quality per bit, honouring studio DRM and country licences, scaled for evening peaks.

**Who uses it:** 4K TV viewers (quality, fast start), commuters on 1-3 Mbps mobile data (no stalls, downloads), and content ops (ingest, encode and QC tracking).

**In scope:**
- **Ingest:** resumable upload of 100-500 GB studio masters with checksums.
- **Encode:** a per-title bitrate ladder (235 kbps 320x240 up to 16 Mbps 4K) in H.264, HEVC and AV1.
- **Package:** 4 s CMAF segments with HLS and DASH manifests, CENC encryption.
- **Playback API:** entitlement, geo check, device capability, steering to caches, manifest and licence URLs.
- **DRM licences, client ABR, continue watching, downloads and QoE telemetry.**

**Out of scope:** live streaming, recommendation algorithms, billing and signup, social features, ad insertion (a follow-up only).

**Non-functional targets:**
- **Latency:** click to first frame p90 under 2 s (3 s on mobile); /play API p99 under 250 ms.
- **Smoothness:** rebuffer under 0.5% of play time; play-start failures under 0.2%.
- **Availability:** 99.99% control plane; playback rides out blips on cached licences.
- **Consistency:** entitlement checked strongly at play; resume position eventually consistent within 30 s.
- **Durability:** masters and encodes in 11-nines object storage with a cross-region copy.

**Capacity math (100M daily viewers, 2 h a day, 30M concurrent streams at peak, 3 Mbps average):**
- **Peak egress:** 30M x 3 Mbps = 90 Tbps. At 95% edge offload, the regional tier and origin still serve 4.5 Tbps. So ISP-embedded caches are the design, not an optimisation.
- **Daily bytes:** 100M x 7,200 s x 3 Mbps / 8 = 270 PB/day. So cost per GB delivered dominates the business case.
- **Segment requests:** 30M / 4 s = 7.5M GETs/s across caches. So segments must be static, immutable files any cache can serve.
- **Edge boxes:** one box (about 300 TB of flash and disk) serves about 100 Gbps; 90 Tbps needs 1,000+ boxes, 2,000-3,000 with 2x headroom.
- **Control plane:** 400M play starts/day = about 5k/s, 25k/s at peak; heartbeats 30M / 30 s = 1M/s. So it is modest, but heartbeats need a write-optimised store.
- **Storage and encoding:** 200k assets x 0.75 h x 40 GB/h = 6 PB encoded plus about 10 PB of masters; an AV1 title takes thousands of core-hours, under 2 h across 500 workers. So encoding is bursty, parallel compute.

## Page 2. The architecture

```
 CONTROL PLANE (cloud, multi-region)
 Client -> API Gateway -> Playback API -> Steering (ISP, health, load)
 (TV,          |             | entitlement, geo, manifest, token
  mobile)      v             v
          Catalog/rights  DRM License svc    Viewing history (Cassandra)
   |  ^
   |  | 4 s segments over HTTPS (3 ranked cache URLs)
   v  |
 ISP edge cache (OCA) --miss--> IXP / regional tier --fill--> Origin (S3)
                                                                 ^
 INGEST / ENCODING PIPELINE                                      |
 Studio upload -> Mezzanine store -> Chunker -> N parallel       |
                                    encoders (ladder x codec) -> Packager
                                                   (HLS/DASH + CENC DRM)
 Clients -> heartbeats, QoE events -> Kafka -> Flink -> dashboards, alerts
```

- **Ingest service:** resumable master upload, checksum, registers the asset, starts the workflow.
- **Encoding orchestrator:** per-asset DAG: analyse, chunk, encode, assemble, QC, package; retries.
- **Encoder workers (spot fleet):** stateless encodes of chunk ranges; idempotent outputs.
- **Packager + DRM:** CMAF segments, manifests, CENC encryption with per-title keys in a KMS.
- **Origin storage:** object store of all renditions; the source for cache fill.
- **Fill / popularity service:** predicts regional demand, fills edge caches nightly.
- **Edge caches (Open Connect-like):** serve segments from flash; report health to steering.
- **Steering service:** ranks caches by ISP proximity, health, load and content; returns 2-3 URLs.
- **Playback API:** rights and device checks; returns manifest, licence URL and signed token.
- **DRM licence, viewing history (Cassandra), telemetry (Kafka + Flink).**

**Flow A: play start**
1. POST /v1/play; the API checks subscription, profile maturity and geo licence.
2. Steering returns 3 ranked cache URLs; the API adds a signed token (6 h TTL).
3. Client fetches the manifest and a DRM licence, starts on a conservative rung, ramps up via ABR.
4. Heartbeat every 30 s plus QoE events (startup time, rebuffers, switches).

**Flow B: ingest and encode**
1. Complexity analysis (trial encodes, VMAF) builds the per-title ladder.
2. Split at scene cuts into about 3-minute chunks; one task per (chunk, rung, codec).
3. Assemble, QC (VMAF, A/V sync, black frames), package, publish to origin.

## Page 3. The core deep dives

### 1. Adaptive bitrate on the client
The client measures throughput (an average of the last 3 segments) and its buffer, and picks a rendition per 4 s segment. At start it takes the highest rung under 0.6 x estimated throughput to start fast. In steady state the buffer level maps to a rung: below 10 s it plays safe, above 30 s it may climb. It never picks a bitrate above 0.8 x the harmonic mean throughput, and only switches up after 2 qualifying segments, to avoid flicker. Example: Sethu's train enters a tunnel; the buffer falls under 10 s and the player drops to the lowest rung instead of stalling. ABR lives in the client because the client sees the real network, and it keeps servers stateless and cacheable.

### 2. Per-title encoding and the ladder
A cartoon needs far fewer bits than a rain-soaked action scene. Trial encodes on sampled scenes plot VMAF (a perceptual quality score) against bitrate; the convex hull picks 8-14 rungs, always including a 235 kbps rung for poor networks, capped by device class. This saves 20-40% bandwidth at the same quality: encode once, save on every view. Chunked encoding makes it fast: each roughly 3-minute chunk starts with a keyframe, workers on preemptible VMs lease tasks for 15 minutes, and outputs go to deterministic keys, so a preempted task simply retries (up to 3 times, with jittered backoff).

### 3. Edge fill, steering and consistent hashing
Each night, the fill service forecasts per-region demand and pushes encrypted segments into ISP caches during off-peak windows. Within a site, each file hashes onto a ring with about 100 virtual nodes per box, so adding a box moves only about 1/N of files; steering uses the same ring to send Shreya to the box that holds her file. Hot files get k=3 replicas. On a miss, the cache fetches from a sibling or the regional tier with request collapsing (many misses, one fetch) and serves while filling.

**Data model:**
- **asset / rendition** (sharded catalog DB + origin): PK (asset_id, rendition_id); codec, size, bitrate, VMAF; segment keys /v/{asset}/{rendition}/seg_{n}.m4s are immutable.
- **title_availability:** PK (title_id, country); window and max resolution; cached in memory, refreshed every 60 s.
- **bookmark** (Cassandra, RF=3, LOCAL_QUORUM): partition profile_id, cluster updated_at desc; last write wins.
- **cache_health** (steering memory, via Kafka): load, egress, health, content bloom filter; every 10 s.
- **encode_task** (workflow DB): idempotent by (asset, chunk, rendition).

**Key APIs:**
- `POST /v1/play`: p99 under 250 ms; 451 for geo-blocked titles.
- `GET /{cache}/v/{asset}/{rendition}/master.m3u8?token=`: HMAC token checked at the edge.
- `POST /v1/license`: security level gates resolution (L3 limited to 540p).
- `POST /v1/heartbeat`: every 30 s, batched to Kafka then Cassandra.
- `GET /v1/profiles/{id}/continue-watching`: Cassandra behind a cache.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Bandwidth:** more ISP-embedded boxes, capacity planned per ISP; commercial CDN as overflow.
- **Hit-title launch:** pre-position days ahead (encrypted, not yet licensed), flip the catalog window at release, replicate hot files.
- **Long-tail misses:** regional tier with request collapsing shields origin.
- **Encoding backlog:** scale the spot fleet; launches gate on H.264 only; delay AV1 re-encodes.
- **/play:** a 250 ms budget (entitlement 60 ms, steering 40 ms, catalog from local cache) with bulkheads per dependency.

**Failure modes:**
- **Edge cache down:** steering drops it within 10 s; clients fail over to their next URL after 2 segment timeouts; ABR lowers quality meanwhile.
- **DRM licence service degraded:** sessions continue on leased keys (8 h); new plays retry another region.
- **Control-plane region lost:** active-active in 3 regions with DNS failover; streams in progress are unaffected.
- **Bad manifest published:** versioned manifests roll back instantly; new assets canary to 1% of plays.
- **Telemetry down:** clients buffer then drop heartbeats; playback unaffected; bookmarks lag.
- **Spot encoder preempted:** the lease expires and the chunk retries; deterministic output keys make partial output harmless.

**Trade-offs chosen:**
- **Own appliances over a commercial CDN only:** at 90 Tbps the per-GB savings and fill control justify capex and ISP deals.
- **4 s segments:** balance startup and adaptivity against request overhead and compression.
- **H.264 for reach, HEVC/AV1 where supported:** AV1 saves about 30% of bits but costs much more compute.
- **CMAF with CENC:** one set of segments serves HLS and DASH, halving storage and cache footprint.
- **Client-side ABR over server-side:** the client has the real signal; servers stay stateless.
- **Cassandra last-write-wins for bookmarks:** about 1M writes/s and multi-region availability beat perfect ordering.

**What to measure:** play start time p50/p90 by device, ISP and country; rebuffer ratio; delivered bitrate, VMAF and switch rate; edge offload and hit ratio per site; play-start failures by error code; /play latency and breaker opens; encoding backlog and cost per encoded hour; egress per ISP versus link capacity.

## Page 5. Say it in the interview

> "I assume a Netflix-style on-demand service: 100 million daily viewers, 30 million concurrent streams at peak, from 4K TVs to phones on patchy 4G, with DRM and country licensing. Success is video starting in under 2 seconds and rebuffering under half a percent of watch time. Two halves. Ingest: the master is chunked, encoded in parallel across a per-title ladder and codecs, and packaged into 4-second HLS and DASH segments. Delivery: segments are pushed ahead of time to cache boxes inside ISPs, the playback API returns a steered list of caches, and the client's adaptive bitrate logic picks a rendition per segment. Peak is about 90 terabits a second, so the real bottleneck is bandwidth and the answer is edge offload above 95 percent."

**Key points to land:**
- Two systems: a batch encoding pipeline and a delivery network; a small, highly available control plane.
- 30M x 3 Mbps = 90 Tbps: the design is 95%+ offload from ISP-embedded caches.
- Proactive off-peak fill of predicted-popular titles; consistent hashing in a site; hot files replicated.
- Client-side ABR over HTTP; 4 s CMAF segments serve both HLS and DASH.
- Per-title convex-hull ladders: encode once, save bandwidth on every view.
- Chunked, idempotent encode tasks on spot capacity with jittered retries.
- Playback survives control-plane blips: 3 cache URLs, leased DRM keys, cached catalog.
- /play: tight timeouts, breakers, bulkheads, fallbacks for non-core features.
- Measure what users feel: startup time, rebuffer ratio, delivered quality, per ISP.

**Likely follow-ups:**
1. **Add live streaming?** Real-time ladder encoding, 1-2 s segments, short-TTL manifests, 3-10 s latency; no pre-positioning, so origin shielding and request collapsing matter.
2. **Offline downloads?** One rendition per the user's quality setting, a persistent licence that expires (for example 7 days, or 48 h after first play), and a per-account download limit.
3. **YouTube-style UGC at 500 h/min?** Fast H.264 first so video is watchable in minutes, better codecs only for popular videos, pull-through CDN, moderation.
4. **Concurrent stream limit across regions?** A session registry per account with 90 s heartbeat leases in a strongly consistent store or a home region; slight over-allowance in a partition is acceptable.
5. **Faster startup?** Prefetch the likely next title's first segments, TLS resumption, QUIC, a lower first rung.

**Director layer:**
- **Cost drivers:** delivery (270 PB/day) dwarfs all else; then 2,000-3,000 edge boxes, AV1 compute, 16 PB of storage.
- **Phasing:** commercial CDN and an H.264 ladder first; then per-title encoding, own edge appliances with proactive fill, then AV1.
- **Ownership:** encoding, edge and fill, playback and steering, DRM, client player, QoE telemetry.
- **Top risks:** ISP peak congestion, an unfilled hit title flooding origin, a DRM licence outage stopping all plays, corrupted renditions shipping.
