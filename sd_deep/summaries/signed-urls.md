# Design signed URLs (secure media access): the 5-page summary

Signed URLs let a CDN serve private media (invoices, KYC documents, paid video, chat photos) at public-media speed without calling an auth service on every request. The single most important idea: decide authorization once, at issuance, and encode it as a short-lived, tamper-proof capability that the edge verifies locally in microseconds.

## Page 1. The problem, scope and numbers

**Pitch:** billions of media objects, many private or entitlement-gated. Proxying them through app servers is slow and costly; a public bucket leaks data. We need CDN-speed delivery where only authorised users can fetch, access expires on its own, and a leaked link does bounded damage.

**Who uses it:** buyers (invoice, chat photo), sellers (direct, secure KYC upload), video subscribers (no re-auth per segment), support agents (temporary, audited access). The adversary tries to enumerate keys, reuse leaked links and tamper with expiry.

**In scope:**
- **Signed GET URLs:** one object, expiry, optional binding (user hash, IP prefix), content-disposition.
- **Streaming tokens:** prefix-scoped signed cookies or path tokens for manifests and segments.
- **Direct uploads:** presigned PUT or POST policies with fixed key, content-type, max size, expiry.
- **Edge verification:** constant-time compare, clock-skew tolerance, multiple keys by key id (kid).
- **Revocation and audit:** by user, object or epoch, pushed to edges; audit log for sensitive classes.

**Out of scope:** DRM for premium video, watermarking, login and sessions, image resizing, malware-scan internals. Public catalogue images stay unsigned.

**Non-functional targets:**
- **Latency:** signing p99 under 20 ms including entitlement (pure signing under 50 microseconds); edge verify under 0.5 ms CPU; p95 TTFB from cache under 100 ms.
- **Availability:** 99.99% for media delivery, 99.95% for signing.
- **Security:** HMAC-SHA256 or Ed25519; keys rotated every 90 days; no public origin.
- **Revocation:** under 60 s to all edges. **Cache:** hit ratio unchanged versus public media.

**Capacity math (peak = 4x average):**
- **Image fetches:** 1B / 86,400 = 11.6k/s, 46k/s peak verifications. Egress 1B x 150 KB = 150 TB/day, about 14 Gbps.
- **Video:** 15 min x 1.5 Mbps = about 169 MB per play x 20M plays = 3.4 PB/day, about 310 Gbps. So almost all video must come from cache.
- **Segments:** 150 per play x 20M = 3B/day, 35k/s, 140k/s peak. So no per-segment signing; use prefix tokens.
- **Signing:** 130M page views x 20 URLs = 2.6B/day, 120k/s peak; HMAC at 1 microsecond = 0.12 cores. Crypto is trivial; entitlement lookups dominate, so batch per page.
- **Revocation list:** 100k revoked epochs x 16 B = 1.6 MB. So it fits in the edge KV store.

## Page 2. The architecture

```
 Client app / player
   | 1. need media X
   v
 API Gateway -> Media Access Service -> Entitlement DB + Redis cache
   ^               | sign(path, exp, kid, claims)
   | 2. signed URL |<-- signing keys -- Key Mgmt (KMS/HSM)
   |                                       | publish verify keys
 Client -3. GET /m/X?exp&kid&sig-> CDN edge function <- Edge KV store
                     | verify sig, exp, epoch    (keys, epochs)
                     | cache key = path only            ^
                     v                                  |
           Edge cache -miss-> Origin shield -> Private bucket
                                                  ^
 Uploads: client -- presigned PUT ----------------+
          bucket event -> Scan + promote worker -> object READY
 Revocation service -- push epochs (< 60 s) --> Edge KV store
```

- **Media Access Service:** checks entitlement, picks the policy by media class, signs, audits.
- **Entitlement store:** who may see each object; Redis cache with a 60 s TTL.
- **Key management (KMS/HSM):** creates keys; tracks kid states active, verify-only, retired.
- **CDN edge verifier:** checks signature, expiry and epoch, then strips token params from the cache key.
- **Edge KV store:** verification keys by kid and revocation epochs, replicated in seconds.
- **Origin shield and private bucket:** shield collapses misses; only the CDN identity can read.
- **Upload and scan pipeline:** presigned PUTs, then malware and type checks before READY.
- **Revocation service:** bumps user or object epochs and pushes them to edges.

**Flow A: download a private invoice**
1. App calls access-url; service checks invoice.owner_id == user; class "document": TTL 300 s, user-bound.
2. It signs a canonical string (method, host, path, exp, uid hash, epoch) with HMAC-SHA256 and the current kid.
3. Edge finds the key by kid, compares in constant time, checks exp + 30 s skew and the user's epoch.
4. Edge serves from cache by path; on a miss, origin shield then bucket. Response is Cache-Control private, Referrer-Policy no-referrer.

**Flow B: stream a video**
1. Session call checks subscription; returns the manifest plus a cookie scoped to /v/{video_id}/* for 2 hours.
2. Player fetches segments with the cookie; the app refreshes every 10 minutes, which re-checks entitlement.

## Page 3. The core deep dives

### 1. Sign and verify a canonical string
Both sides must build byte-identical input: method, lowercase host, normalised path (or a prefix ending in "/"), exp, kid and sorted claims. Anything not signed can be tampered with. Changing /inv/A to /inv/B breaks the signature; a prefix must end at "/" so /inv/A does not match /inv/AB. The edge rejects "..", double encoding and stray params instead of quietly normalising. HMAC-SHA256 is used on our own edge; Ed25519 on third-party CDNs, so a leaked edge config can verify but not mint URLs. Never use hash(key + message): use HMAC and compare in constant time.

### 2. Expiry, revocation and the bearer problem
A signed URL is a bearer token: whoever holds it gets in. Short TTL is the main defence, by class: KYC and invoices 5 minutes, chat 1 hour, video 2 hours with 10-minute refresh, embargoed images not issued before launch. Only servers judge expiry (phones can be hours off); the edge allows 30 s skew and rejects exp too far in the future. For fast revocation, sensitive tokens carry a user hash and an epoch. Example: Shreya's account is taken over; we bump her epoch from 7 to 8 in the edge KV and every URL carrying ep=7 fails within 60 s. Expiry bucketing (round exp to a 5-minute boundary) keeps URLs identical so app caches still hit.

### 3. Cache key and streaming
The edge authorizes first, then strips exp, kid, sig, ep and uid, so all authorised users share one cached copy. If the signature were in the cache key, every user would miss and the origin would melt in a sale. For HLS, a prefix cookie or a path token (/v/tok/{token}/vid/...) lets 150 relative segment URLs inherit one token.

### 4. Key rotation and uploads
Each token carries a kid. Order: publish the new key to edges, wait for acknowledgement, start signing, keep the old kid verify-only for max TTL (2 h) plus 5 minutes, then retire. Emergency rotation retires a kid at once; its URLs fail and clients re-request. Uploads get a random 128-bit key, a 10-minute presigned PUT with fixed type and size; objects become immutable after scanning.

**Data model:**
- **MediaObject:** PK object_id, index owner_id; random storage_key, media_class, state.
- **Entitlement** (Redis): ent:{user_id}:{resource}, 60 s TTL.
- **SigningKey** (KMS + table): kid; algorithm, state, not_after.
- **RevocationEpoch** (edge KV): u:{user_hash} or o:{object_id}; missing means epoch 0.

**Key APIs:**
- `POST /v1/media/{id}/access-url`: server enforces max TTL by class; a client hint can only shorten.
- `POST /v1/media/access-urls:batch`: up to 100 ids, one entitlement query.
- `POST /v1/playback/{video_id}/session`: manifest URL plus prefix cookie, refresh after 600 s.
- `POST /v1/media/uploads`: presigned PUT with a random key and size range.
- `POST /internal/v1/revocations`: bumps an epoch and pushes it to edges.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Entitlement checks, not crypto:** cache entitlements in Redis and batch-sign a whole page in one call.
- **Origin egress:** token-free cache keys, origin shield and request coalescing keep hit ratio above 90% for images and 95% for video.
- **Segment requests (140k/s peak today):** prefix tokens verified at the edge, never a call back.
- **Revocation list:** only non-zero epochs are replicated, so it stays megabytes.

**Failure modes:**
- **Media Access Service down:** existing URLs keep working until expiry; new issuance fails and clients retry with jittered backoff; multi-region limits impact.
- **Edge KV propagation slow:** new keys are not activated until acknowledged, so no bad_kid outage; revocations may lag, so alert on lag.
- **Origin region outage:** the cache keeps serving; misses fail over to a cross-region replica bucket.
- **403 spike after a deploy:** 403s are tagged (bad_sig, expired, bad_kid, revoked); bad_sig means a canonicalization mismatch, so roll back signer and edge together.
- **Stale entitlement after cancellation:** bounded by the 60 s cache plus refresh interval; bump the epoch for an instant cut-off.
- **Signing key compromise:** emergency rotation retires the kid at all edges in under a minute.

**Trade-offs chosen:**
- **HMAC on our edge, Ed25519 on third-party CDNs:** HMAC is fastest, but anyone who can verify can sign.
- **URLs for single objects, cookies or path tokens for streaming:** URLs work everywhere; cookies avoid signing hundreds of segments.
- **TTL per class, 5 minutes to 2 hours:** short bounds leak damage; bucketing recovers caching.
- **Epoch check only for sensitive classes:** a sub-ms local KV read buys 60 s revocation.
- **CDN with signed URLs over proxying:** proxying 3 PB/day through app servers is slow and costly.
- **Bind to session, not IP:** mobile IPs change and carrier NAT shares them.

**What to measure:** edge 403 rate by reason; cache hit ratio and origin egress; signing QPS, p99 latency and entitlement cache hit ratio; revocation lag via a synthetic probe; key age and edge KV lag; direct origin access attempts (must be zero) and bucket policy drift; upload and scan failures; enumeration anomalies (thousands of denied URL requests).

## Page 5. Say it in the interview

> "We are protecting invoices, KYC documents, paid video and chat attachments, served from a CDN at about a billion fetches a day. We do not want the CDN to call our auth service on every request, so we move the decision into a short-lived capability in the URL. The Media Access Service checks the user may see the object, then signs the path, an expiry and a few claims with a key id. The edge verifies the signature and expiry locally in microseconds, strips the token from the cache key so everyone shares one cached copy, and reads from a private bucket only the CDN can access. For video I sign a path prefix in a cookie so 150 segments use one token. Uploads use presigned PUTs with size and type locked. Then I defend rotation, revocation, clock skew and leaks."

**Key points to land:**
- Authorization moves to issuance time; the edge verifies with no callback.
- Sign a canonical string: method, host, path or prefix, expiry, claims, plus kid.
- HMAC is fast but symmetric; Ed25519 lets untrusted edges verify without signing.
- Authorize before cache lookup and keep token params out of the cache key.
- Streaming uses prefix cookies or path tokens, not per-segment signing.
- A signed URL is a bearer token: short TTL, narrow scope, optional binding, epochs.
- Only servers judge expiry; allow small skew, cap future exp.
- Private bucket readable only by the CDN; uploads locked down and scanned.
- Rotate keys in the order publish, activate, retire after max TTL.
- Measure 403 reasons, hit ratio and revocation lag.

**Likely follow-ups:**
1. **Why not an auth check at the CDN?** Tens of thousands of auth calls per second with cross-region latency, and media availability would depend on the auth service.
2. **A user shares a video link?** Prefix tokens are short-lived and session-bound, so the friend fails; real sharing gets its own capability with limits and audit.
3. **Why not JWTs?** They work, but are verbose in URLs and have pitfalls (alg none, algorithm confusion); a minimal format with one algorithm per kid is shorter and safer.
4. **Embargoed sale images?** Do not issue URLs before launch (not_before), use random keys, pre-warm the CDN with an internal token.
5. **How do you test it?** Fuzz signer and verifier for agreement on encodings, negative tests for tampering and expiry, and canary edge functions on mirrored traffic.

**Director layer:**
- **Cost drivers:** CDN egress (about 3.4 PB/day of video) and origin misses; hit ratio is a cost metric.
- **Team ownership:** media platform (signing, uploads), CDN and edge, security (KMS, rotation, audit), entitlement owners (orders, subscriptions).
- **Rollout:** an edge-function bug has global blast radius, so deploy by region with automatic rollback on 403 rate change.
- **Top risks:** signing key leak, long TTLs making links public, signatures in the cache key, URLs leaking via Referer or logs.
