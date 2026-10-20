# CDN strategy for media delivery (video, images, live events): recall card

> **Hook:** Immutable segments → ISP caches and CDN edges → Shield collapses misses → Steer on RUM → Fallback CDN → Cap bitrate

**P · Problem:** It's really a bandwidth distribution problem: push immutable bytes as close to viewers as possible and keep origin load flat.

**N · Numbers:**
1. 15M viewers x 2.5 Mbps = 37.5 Tbps at a live peak, so bytes are spread over ISP caches and 2-3 CDNs reserved weeks ahead.
2. 7.5M segment requests/s plus 7.5M manifest refreshes/s, so request collapsing is mandatory at every tier.
3. About 24 PB/day of VOD, about Rs 60 lakh/day, so moving 60% to owned ISP caches drives the business case.

**H · Hard part:** Carrying a 40 Tbps live peak that no origin or single CDN can, and surviving a CDN failing mid-match.

**B · Boxes:** `Player → ISP cache or CDN edge → Regional shield → Object storage origin or live packager`

Side path: `Playback API → Steering service` picks the primary and fallback CDN per session.

**D · Decisions:**
1. Multi-CDN plus own ISP caches over one CDN, because it is cheaper at 24 PB/day with no single vendor,.
2. Immutable versioned URLs over purges, because there are no purge storms and rollback is trivial.
3. 2 s live segments over 1 s, because they meet 15-30 s latency with half the requests.

**F · Failures:**
1. CDN regional outage → players switch to the fallback after 2 strikes; steering re-weights within 60 s.
2. Demand beyond capacity → regional ABR caps (for example 720p), then a waiting room for new sessions only.

**C · Close:** "Media delivery is a bandwidth problem first. I make everything cacheable with immutable content-hash segment URLs; only live manifests are short-lived. ISP caches and CDN edges sit in front of a regional shield, and collapsing keeps origin at about 30 requests a second for 15 million viewers. Steering picks the CDN per session from real user data, with a fallback in every manifest. If capacity runs short, I cap bitrate before anyone stalls."

**Quiz yourself:**
1. Why strip the token from the cache key? → Otherwise every viewer fragments the cache.
2. How is popular VOD placed? → Pushed into ISP caches between 02:00 and 08:00; the tail is pulled.
3. Why not one big CDN? → One outage kills every stream.
