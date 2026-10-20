# Authentication and session management (web app login, tokens, sessions): recall card

> **Hook:** Verify argon2id password → Risk-based OTP → Create session → 10-min JWT verified locally → Rotate refresh token → Broadcast revoked sids

**P · Problem:** It's really a trade-off between stateless verification on every request and fast revocation.

**N · Numbers:**
1. argon2id at 50 ms per verify and 5k logins/s needs about 250 cores, so rate limits must reject before hashing.
2. ES256 verify at 100 us for 200k rps is about 20 cores, so verification can be local everywhere.
3. The revocation set is about 10 MB per gateway, so it fits in memory because it covers only one token lifetime.

**H · Hard part:** Keeping identity proof cheap on every request while making logout everywhere work within a minute.

**B · Boxes:** `Browser / App → API Gateway → Auth Service → Redis Cluster → Postgres`

Side path: `Auth Service → Kafka auth.revocations → every gateway's revoked-sid set`.

**D · Decisions:**
1. Hybrid tokens over pure JWT or pure sessions, because the 200k rps path stays stateless and revocation stays fast.
2. A 10-minute TTL over 1 minute, because 1 minute is 10x the refresh load for little gain.
3. ES256 over HS256, because verifiers cannot mint tokens and signatures verify fast.

**F · Failures:**
1. Redis shard down → refresh on that shard returns 503; access tokens keep working for 10 minutes.
2. Kafka lagging → fall back to refresh-time revocation, at most 10 minutes of exposure; security is paged.

**C · Close:** "I use a hybrid. Login verifies an argon2id password, adds an OTP when risk is high and creates a session. It issues a 10-minute JWT that any gateway verifies locally, and an opaque refresh token rotated on every use. Revocation deletes the session so the next refresh fails, and revoked session ids go out on Kafka for the gap. Hashing is the CPU bottleneck, so login gets its own pool."

**Quiz yourself:**
1. What happens when an old refresh token is reused? → Outside the 30 s grace, the whole family and session are revoked.
2. Why no hard account lockout? → Attackers would use it to lock out victims.
3. How do you rotate signing keys? → Publish the new key in JWKS, wait one cache TTL, sign with it, keep the old one for a token TTL.
