# Netflix / YouTube-style video streaming: recall card

> **Hook:** Chunk the master → Encode a per-title ladder → Package 4 s segments → Pre-fill ISP caches → Steer → Client ABR

**P · Problem:** It's really a bandwidth-delivery problem bolted onto a batch encoding pipeline.

**N · Numbers:**
1. 30M streams x 3 Mbps = 90 Tbps at peak, so ISP-embedded caches are the design, not an optimisation.
2. 30M / 4 s = 7.5M segment GETs/s, so segments must be static, immutable files any cache can serve.
3. One edge box serves about 100 Gbps, so 90 Tbps needs 2,000-3,000 boxes with headroom.

**H · Hard part:** Serving 95%+ of bytes from the edge while starting in under 2 s and never stalling on patchy networks.

**B · Boxes:** `Client → Playback API → Steering → ISP edge cache → Regional tier → Origin`

Side path: `Upload → Chunker → Parallel encoders → Packager + DRM → Origin`.

**D · Decisions:**
1. Own appliances over a commercial CDN only, because at 90 Tbps the per-GB savings and fill control justify it.
2. Client-side ABR over server-side, because the client sees the real network and servers stay stateless.
3. CMAF with CENC over separate HLS and DASH files, because one set of segments halves storage and cache footprint.

**F · Failures:**
1. Edge cache down → steering drops it within 10 s; clients fail over to their next URL and ABR lowers quality.
2. DRM licence service degraded → sessions continue on leased keys; new plays retry another region.

**C · Close:** "Two halves. Ingest: the master is chunked, encoded in parallel across a per-title ladder and codecs, and packaged into 4-second HLS and DASH segments. Delivery: segments are pushed ahead of time to cache boxes inside ISPs, the playback API returns a steered list of caches, and the client's adaptive bitrate logic picks a rendition per segment. Peak is about 90 terabits a second, so the bottleneck is bandwidth and the answer is edge offload above 95 percent."

**Quiz yourself:**
1. Why per-title encoding? → A cartoon needs fewer bits; it saves 20-40% bandwidth at the same quality.
2. How does a cache site place files? → Consistent hashing, about 100 virtual nodes per box; hot files get 3 replicas.
3. What happens in a tunnel? → The buffer falls under 10 s and the player drops to the lowest rung.
