# Design authentication and session management (web app login, tokens, sessions): the 5-page summary

Login is easy; the hard part is keeping identity proof cheap on every request yet revocable fast. The key idea: a 10-minute signed access token verified locally, plus a rotating refresh token tied to a server-side session.

## Page 1. The problem, scope and numbers

**Pitch:** let users log in once and stay securely logged in on web and mobile, stop account takeover (ATO) from credential stuffing, phishing and stolen devices, and make "log out of all devices" work everywhere within a minute.

**Who uses it:** returning shoppers (never retype a password), new users, sellers and admins (mandatory MFA), security analysts (login history, bulk session kills).

**In scope:**
- **Login:** email/phone plus password hashed with argon2id; legacy bcrypt rehashed on next login.
- **Risk-based MFA:** SMS/email OTP or TOTP; TOTP or WebAuthn mandatory for sellers and admins.
- **Social login:** Google/Apple via OpenID Connect (OIDC) code flow with PKCE.
- **Tokens:** JWT access token (10 min), rotating opaque refresh token (30 days sliding, 90 days absolute).
- **Revocation:** logout one, logout all, admin revoke; device list; password reset revokes all sessions.
- **Step-up auth:** sensitive endpoints need auth_time within the last 5 minutes.

**Out of scope:** authorization (RBAC/ABAC), SAML and SCIM, payment fraud scoring, KYC.

**Non-functional targets:**
- **Latency:** gateway verify p99 under 1 ms with no network call; login p50 150 ms, p99 400 ms; refresh p99 under 50 ms.
- **Availability:** 99.99% for refresh and verify, 99.95% for login.
- **Consistency:** revocation effective everywhere within 60 s (p99 5 s).
- **Durability:** sessions and credentials RPO 0 (synchronous Postgres replication).

**Capacity math (50M users, 10M DAU, 2.5 devices each):**
- **Sessions:** 125M x 400 B = 50 GB in Postgres; hot 25M in Redis is about 10 GB, about 20 GB with overhead on 6 shards. Small, so the store is not the problem.
- **Refresh:** 3M concurrently active / 600 s = 5k/s steady; budget 20k/s for retries. So refresh is the write hot path and needs an atomic, sub-millisecond store.
- **Hashing:** argon2id about 50 ms per core; 5k logins/s x 0.05 = 250 cores. An attack of 50k/s would need 2,500 cores, so rate limits must reject before hashing.
- **Verify:** ES256 verify about 100 us; 200k rps x 100 us = 20 cores across the fleet. So verification can be local everywhere.
- **Revocation set:** 1k revocations/s x 600 s x 16 B = about 10 MB per gateway. It fits in memory because it only covers one token lifetime.
- **Audit:** 30k events/s x 500 B = 15 MB/s, about 200 GB/day compressed, so stream it to a lake.

## Page 2. The architecture

```
 Browser / App
      | HTTPS (cookie or Bearer)
      v
 API Gateway (Envoy) -- verify JWT locally, revoked-sid set
      |        ^  ^ JWKS (cached 5 min)
      |        |  +-------------------- Auth Service -> KMS (ES256 sign)
      |        | Kafka auth.revocations   |     |
      v        +--------------------------+     v
 Product services (trusted identity headers)   Risk Service (rate limits,
                                                 device, IP reputation)
                       Auth -> Redis Cluster (sessions, refresh families)
                                   | write-through
                                   v
                              Postgres (users, creds, sessions)
                       Auth -> Kafka -> Audit / SIEM, fraud lake
```

- **API Gateway:** checks signature, expiry, audience with cached JWKS; strips client identity headers.
- **Auth Service:** login, MFA, OIDC callback, issue and rotate tokens, logout, sessions.
- **Credential store (Postgres):** users, hashes with algorithm and params, encrypted MFA secrets.
- **Session store:** Redis for fast rotation, Postgres for durability and session listing.
- **Risk Service:** sliding-window limits, IP reputation, impossible travel; allow, challenge or deny.
- **KMS:** holds ES256 keys, rotated every 30 days, public keys published by kid.
- **Revocation bus (Kafka):** gateways keep revoked sids for one access-token lifetime.
- **OTP service and audit pipeline:** OTP and alerts with limits; events to SIEM, 1-year retention.

**Flow A: password login with risk-based MFA**
1. POST /v1/login; gateway limits 10 logins/min per IP; Risk pre-check returns allow, CAPTCHA or deny.
2. Auth loads the user (dummy argon2id verify if unknown, for constant timing) and verifies the hash.
3. New device, new country or high score: return mfa_required and send an OTP (5 min, 5 tries).
4. On success: create session row, create refresh family, sign JWT, set Host-prefixed secure cookies; emit audit event.

**Flow B: token refresh with rotation**
1. Client sends the refresh token; Auth hashes it (SHA-256) and looks up its family in Redis.
2. Current: a Lua script marks it used, stores generation+1, returns new access and refresh tokens.
3. Used within 30 s on the same device: return the same successor. Otherwise: theft, revoke the family.

## Page 3. The core deep dives

### 1. Stateless tokens versus sessions: the hybrid
Server-side sessions give instant revocation but cost a lookup on every request. Stateless JWTs need no lookup but cannot be revoked before expiry. The hybrid keeps the 200k rps path stateless: the gateway verifies a 10-minute ES256 JWT locally. The refresh token is opaque, stored hashed and tied to a session id (sid), so deleting the session stops the next refresh. For the 10-minute gap, Auth publishes the sid to Kafka; each gateway adds it to an in-memory set with a 10-minute TTL. The access-token TTL is the revocation budget, and it is why the denylist stays tiny.

### 2. Refresh token rotation with reuse detection
Each session has one refresh family. Only the newest generation is valid. Example: Shreya's phone refreshes with generation 3 and gets generation 4. If an attacker who copied generation 3 presents it later, the family sees "used" outside the grace window: you cannot tell which holder is real, so the whole family and session are revoked and Shreya is alerted. Mobile networks drop responses, so a same-device retry within 30 s gets the already-minted generation 4. Both Redis keys share the hash tag {family_id}, so one Lua script updates them atomically; two browser tabs refreshing together get one winner.

### 3. Credential stuffing and password hashing
argon2id (64 MB, t=3) costs about 50 ms per verify; memory hardness blunts GPU cracking of a leaked DB. That cost makes login a CPU target, so login runs on its own autoscaled pool with a bounded queue (429 before hashing). Per-IP limits fail against 200k proxy IPs trying 2 passwords each, so limits are multi-dimensional: per account (5 failures in 15 min before CAPTCHA), per ASN, per device, plus a global failure ratio against the 7-day baseline and a breached-password check. No hard lockout, since attackers would use it to lock out victims.

### 4. Key rotation without downtime
Tokens carry kid. Publish the new public key in JWKS, wait one cache TTL (5 min), start signing with it, keep the old key for one token TTL. Gateways pin alg=ES256, iss and aud, allow 30 s clock leeway, and refetch JWKS on unknown kid at most once per 30 s.

**Data model:**
- **users** (Postgres, 16 logical shards by user_id): hash, algo, params, status; lookup tables email -> user_id, phone -> user_id.
- **sessions** (Postgres by user_id plus Redis): PK (user_id, sid); revoke-all is a single-shard update.
- **refresh_families** (Redis, hash tag family_id): rt:{sha256} -> generation, status, successor; TTL = sliding expiry.
- **rate_counters** (Redis): per IP, account, OTP destination and window; TTL 2x window.
- **auth_events** (Kafka, key user_id): immutable, to SIEM.

**Key APIs:**
- `POST /v1/login`: same error for unknown user and wrong password; may return mfa_required.
- `POST /v1/mfa/verify`: single-use challenge bound to the login device_id.
- `POST /v1/token/refresh`: rotates every call; reuse outside 30 s revokes the family.
- `POST /v1/logout`: scope current or all; publishes revocation.
- `GET /.well-known/jwks.json`: current and previous keys, max-age 300.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Password hashing:** isolated, autoscaled login pool; reject abuse before hashing.
- **Verification:** stateless, so it scales linearly with gateway nodes.
- **Refresh writes:** shard refresh state in Redis Cluster; one compare-and-set per refresh.
- **OTP cost:** SMS is 0.15-0.25 INR each, so MFA stays risk-based.

**Failure modes:**
- **Redis shard down:** refresh on that shard returns 503; clients back off (1, 2, 4 s, cap 30 s); access tokens work for 10 min; replica promoted in about 15 s.
- **Postgres failover:** logins fail for about 30 s; refresh keeps working from Redis.
- **KMS down:** sign with an in-memory data key leased up to 1 hour, then fail closed; verify never needs KMS.
- **Kafka lagging:** fall back to refresh-time revocation (max 10 min exposure); gateways over 30 s lag fail readiness; security is paged.
- **Gateway restart:** replay 15 minutes of revocations before taking traffic.
- **Stuffing overload:** bounded login queue returns 429; refresh and verify run on separate pools.
- **SMS provider outage:** second provider, email OTP or TOTP, or a shorter session for low risk.
- **Bad deploy rejects tokens:** 1% canary with a verify-failure guardrail auto-rolls back.

**Trade-offs chosen:**
- **Hybrid over pure JWT or pure sessions:** stateless hot path at 200k rps plus fast revocation.
- **10-minute TTL over 1 minute:** 1 minute is 10x the refresh load for little gain; the denylist covers urgent cases.
- **ES256 over HS256 or RS256:** verifiers cannot mint tokens; signatures are small and verify fast.
- **Risk-based MFA over always-on:** SMS cost and friction; sellers and admins get phishing-resistant factors.
- **Kafka push with replay over per-request lookup:** seconds of lag, no hot dependency, survives restarts.
- **Redis for rotation, Postgres for truth:** losing Redis state only forces re-login.

**What to measure:** login success and failure by reason, global failure ratio versus baseline, MFA challenge and completion rate, login and refresh p99, argon2 queue depth, refresh reuse detections per hour, revocation lag p99 and consumer lag per gateway, JWT failures by reason, SMS spend per hour, ATO cases per million users.

## Page 5. Say it in the interview

> "Assume web and mobile, 10 million daily users, 5k logins a second at a sale peak, and 200k authenticated requests a second. The hard rule is that logout-everywhere takes effect within a minute. I do not want the auth service on every request, so I use a hybrid. Login verifies an argon2id password, adds an OTP when risk is high, and creates a session. It issues a 10-minute JWT that any gateway verifies locally with a public key, and an opaque refresh token, stored hashed and rotated on every use. Revocation deletes the session so the next refresh fails, and for the 10-minute gap we broadcast revoked session ids on Kafka to every gateway. Hashing is the CPU bottleneck, so login gets its own pool. If the session store dies, logged-in users keep working while new refreshes fail."

**Key points to land:**
- Hybrid: 10-minute stateless JWT plus an opaque rotating refresh token tied to a session.
- Gateways verify with cached JWKS; Auth is never on the 200k rps path.
- Revocation: delete the session, broadcast the sid on Kafka for one TTL window.
- Rotation with reuse detection revokes the whole family; 30 s same-device grace.
- argon2id costs about 250 cores at 5k logins/s, so isolate the login pool.
- Stuffing defence is multi-dimensional limits, breached-password checks and CAPTCHA, not lockout.
- ES256 in KMS, rotated by kid: publish, wait, sign, keep the old key.
- Browser: refresh token in an HttpOnly Host-prefixed cookie on the refresh path, access token in memory, CSRF header.
- Degrade gracefully: session store down means existing users keep working.

**Likely follow-ups:**
1. **SSO across shop and seller subdomains?** A central accounts domain acts as an OIDC provider; each app does code plus PKCE and holds its own tokens, so no shared cookie.
2. **Why not roles in the JWT?** Fine-grained permissions bloat it and go stale for 10 minutes; keep coarse scopes and ask a policy service.
3. **Step-up for changing a bank account?** The service requires auth_time within 5 minutes and amr including mfa; otherwise 401, an MFA challenge and a fresh token.
4. **User randomly logged out on mobile?** Check refresh 401 reasons for the sid; grace misses often come from backgrounding, fixed by saving the new token before acknowledging.
5. **Multi-region active-active?** Verification is already local; home sessions to the user's region and mirror the revocation topic globally.

**Director layer:**
- **Cost drivers:** about 250 cores of argon2id for peak logins, SMS OTP spend, and 200 GB/day of audit logs.
- **Phasing:** password, OTP and Google login first; passkeys as the primary credential later; SAML out of phase 1.
- **Team ownership:** identity (Auth, keys), edge gateway, risk and fraud signals, security operations.
- **Top risks:** a stuffing wave during a sale, a silently stolen refresh token, signing key compromise, and a session store outage logging everyone out.
