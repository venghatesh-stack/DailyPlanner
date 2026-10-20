# Signed URLs (secure media access): recall card

> **Hook:** Check entitlement once → Sign path and expiry with kid → Edge verifies locally → Strip token from cache key → Serve from private bucket

**P · Problem:** It's really a capability-token problem: move the authorization decision to issuance so the edge can verify without a callback.

**N · Numbers:**
1. Video is about 3.4 PB/day, around 310 Gbps, so almost all of it must come from cache.
2. 3B segment fetches/day, 140k/s at peak, so no per-segment signing; use prefix tokens.
3. 120k signs/s at 1 microsecond each is 0.12 cores, so crypto is trivial and entitlement lookups dominate.

**H · Hard part:** A signed URL is a bearer token, so a leaked link must do bounded damage while caching still works at public-media speed.

**B · Boxes:** `Client → Media Access Service → Signed URL → CDN edge verifier → Edge cache → Private bucket`

Side path: `Revocation service → Edge KV store` pushes epochs to edges in under 60 s.

**D · Decisions:**
1. CDN with signed URLs over proxying through app servers, because proxying 3 PB/day is slow and costly.
2. Ed25519 on third-party CDNs over HMAC, because with HMAC anyone who can verify can also sign.
3. Binding to session over binding to IP, because mobile IPs change and carrier NAT shares them.

**F · Failures:**
1. Media Access Service down → existing URLs work until expiry; new issuance fails and clients retry with backoff.
2. 403 spike after a deploy → tagged reasons show bad_sig, a canonicalization mismatch, so roll back signer and edge together.

**C · Close:** "We do not want the CDN calling our auth service on every request, so the decision moves into a short-lived capability in the URL. The Media Access Service checks entitlement, then signs the path, an expiry and a few claims with a key id. The edge verifies locally, strips the token from the cache key so everyone shares one copy, and reads from a private bucket. Video uses a prefix cookie, and uploads use presigned PUTs."

**Quiz yourself:**
1. Why keep the signature out of the cache key? → Every user would miss and the origin would melt.
2. How do you revoke a leaked link fast? → Bump the user's epoch in the edge KV; old tokens fail within 60 s.
3. How do you rotate keys safely? → Publish to edges, activate, keep old kid verify-only for max TTL, then retire.
