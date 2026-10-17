# Design an API Gateway Rate Limiter: the 5-page summary

A rate limiter sits on the hot path of every API call, so it must add well under a millisecond while enforcing quotas that are global across hundreds of gateway nodes. The single most important idea: layer a cheap local check, an atomic shared counter in a regional Redis, and load shedding, and fail open when the limiter itself is sick.

## Page 1. The problem, scope and numbers

**Pitch:** stop any one client, retry storm or scraper from eating backend capacity, with fair plan-based quotas across the whole gateway fleet and no noticeable latency.

**Who uses it:** the API platform team (reliable, low latency, operable), backend owners (capacity never exceeded), sellers and partners (predictable limits, clear headers), product (plan tiers to monetise), SRE and security (kill switches, per-IP limits in attacks).

**In scope:**
- **Rules:** keyed on any mix of API key, tenant, user, IP, endpoint class and method.
- **Algorithms:** token bucket (rate plus burst), sliding window counter, in-flight concurrency limits.
- **Feedback:** 429 with Retry-After and X-RateLimit headers; 503 for load shedding.
- **Rules service:** plans, per-customer overrides, versioning, rollback, shadow (dry-run) mode, emergency blocks with TTLs.
- **Priority classes** so load shedding drops low-priority traffic first; sampled decisions to Kafka.

**Out of scope:** L3/L4 DDoS and bot fingerprinting, billing and invoicing, limits inside downstream services, queueing rejected requests.

**Non-functional targets:**
- **Latency:** adds p50 under 0.3 ms, p99 under 1 ms, p999 under 5 ms (bounded by the timeout).
- **Availability:** gateway 99.99%; a limiter failure degrades to fail-open, never to failed requests.
- **Accuracy:** within 10% of the limit over any 60 s window; monthly quotas exact, reconciled offline.
- **Config freshness:** rule changes on 99% of nodes within 30 s.
- **Durability:** counters are ephemeral and may be lost on failover; rules are durable in Postgres (RPO 0).

**Capacity math (1M requests/s peak per region, 400 gateway nodes, 10M keys/day):**
- **Redis ops:** 1M x 2 rules = 2M ops/s; pipelining both rules keeps it to 1M round trips/s.
- **Shards:** 2M / 100k Lua calls per shard = 20 primaries; provision 30 for 50% headroom, plus replicas = 60 nodes. Every check is a write, so replicas do not help; shard.
- **Memory:** 10M keys x 3 buckets x 100 B = 3 GB, about 100 MB per shard. So CPU, not memory, is the constraint.
- **Network:** 1M/s x 250 B = 250 MB/s, about 8 MB/s per shard. Comfortable.
- **Hot keys:** the top 1% of keys send 60% of traffic; leasing 50 tokens at a time cuts their calls 50x and total Redis ops roughly in half.
- **Decision events:** 1% sampled = 10k/s x 300 B = 3 MB/s, about 260 GB/day into Kafka.

## Page 2. The architecture

```
 Clients -> CDN / L4 LB (per-IP edge limits)
               |
 Region        v
 Gateway node x400: auth -> RateLimitFilter -> LoadShedder -> Backend APIs
                     (rules cache | deny cache | lease pool)
                           |                         |
                           | Lua, pipelined          | 1% sampled decisions
                           v                         v
                 Redis Cluster, 30 shards     Kafka -> analytics, abuse,
                 (primary + replica)                   usage for billing
                           ^
                 Quota coordinator <- regional usage every 5 s

 Rules service + Postgres --versioned snapshot (push / long-poll)--> gateways
```

- **RateLimitFilter:** in the gateway; matches rules, checks caches and leases, calls Redis, sets headers.
- **Redis Cluster:** token buckets and window counters, sharded by hash slot; atomic Lua scripts.
- **Rules service:** CRUD for plans, overrides, blocks, shadow rules; publishes versioned snapshots.
- **Config distribution:** etcd watch or long-poll; nodes report the version they run.
- **Concurrency limiter:** in-flight requests per key for expensive endpoints, as a sorted set.
- **Load shedder:** drops low-priority traffic with 503 when the fleet or backends are hot.
- **Quota coordinator:** splits global quotas into regional shares, rebalanced every 5 s.
- **Decision pipeline:** Kafka plus stream jobs for dashboards, abuse detection and billing.

**Flow A: request admission**
1. Auth resolves the API key to tenant, plan and priority class.
2. The filter matches rules from the in-memory snapshot (key, endpoint class, IP).
3. In the local deny cache: return 429 with no Redis call. Holding a lease: consume locally.
4. Otherwise one pipelined Lua call per rule: refill by elapsed time, take 1 token.
5. Any deny: Retry-After from the deficit and refill rate, cache the deny, return 429.
6. All allow: set headers, pass to the load shedder, sample 1% to Kafka.

**Flow B: rule change**
1. Operator edits a rule; the service validates it (no zero limit on a paid plan without approval).
2. Written to Postgres as version v+1, optionally in shadow mode.
3. Gateways swap the snapshot atomically within seconds and report their version.

## Page 3. The core deep dives

### 1. Algorithms: token bucket and sliding window counter
A token bucket stores two numbers: tokens and last refill time. Rate R refills it, capacity B allows bursts. Example: R = 100/s, B = 200; Shreya's client idles, then sends 200 at once and is admitted, then is held to 100/s. A fixed window allows 2x the limit at a boundary (100 at 0.99 s, 100 at 1.01 s). The sliding window counter fixes that with two integers: estimate = previous count x the fraction of the previous window still inside the last W seconds + current count. Cloudflare measured about 0.003% wrong decisions over 400M requests. Token bucket is the default per key; sliding window serves IP and abuse rules; fixed windows only for monthly quotas.

### 2. Atomic checks in Redis
Clients never GET then SET: two nodes would both see the last token. Each check is one EVALSHA of a short Lua script that refills, decrements and writes back. Redis runs one shard's commands on one thread, so the script is atomic. It uses Redis TIME, not the gateway clock, so skew of a few hundred milliseconds between nodes cannot cause drift. Scripts stay O(1), or they block the shard.

### 3. Hot keys, leasing and regional shares
Sharding spreads keys, not load per key: one tenant at 50k RPS lands on one shard. Fixes: split it into K sub-buckets each with limit/K, or let each gateway lease a batch (for example 50 tokens) and serve them locally; unused tokens expire after 1 s so idle nodes cannot hoard. Across regions, a 60-150 ms round trip per request is unacceptable, so a global quota is split into regional shares rebalanced every 5 s. The error is bounded: about 5 s of one region's surplus.

### 4. Fail open, safely
Each Redis call has a 5 ms timeout and a per-shard circuit breaker (opens at 50% errors over 2 s, skips the shard for 10 s). On failure the node uses a local bucket of limit / active nodes, so the fleet still enforces roughly the right total. Emergency blocks are the exception: held in gateway memory, they fail closed.

**Data model:**
- **TokenBucket** (Redis): rl:{tenant}:{rule_id}:{key}; tokens, ts_ms; TTL 2 x refill time.
- **WindowCounter** (Redis): rlw:{rule_id}:{key}:{window_start}; INCR; TTL 2 windows.
- **InFlight** (Redis sorted set): rlc:{key}; member request_id, score expiry; 60 s safety expiry.
- **Rule** (Postgres): PK rule_id; scope, algorithm, rate, burst, priority, shadow, version; audit row per change.
- **UsageAggregate** (ClickHouse): allowed, denied, shadow_denied per api_key and minute.

**Key APIs:**
- `RateLimitFilter.check(ctx)`: in-process; allowed, remaining, retry_after_ms, rule_id; never blocks over 5 ms.
- `POST /v1/ratelimit/rules`: validated; approval for limits below 10% of plan default.
- `PUT /v1/ratelimit/blocks/{key_or_cidr}`: emergency block, propagated first.
- `GET /v1/usage/{api_key}`: customer usage from aggregates, not hot counters.
- `GET /v1/ratelimit/snapshot?since_version=v`: long-poll fallback for gateways.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Redis CPU:** add shards (hash slots move few keys); pipeline rules; lease tokens for hot keys.
- **Hot tenants:** detect from sampled decisions before a shard passes about 60% CPU; split or lease.
- **Retry storms:** the deny cache absorbs repeats with no Redis call; repeat offenders get temporary blocks.
- **Many rules per tenant:** compile into an index by scope so a request matches 2-4 rules; rule count costs memory, not Redis load.

**Failure modes:**
- **Redis shard primary crashes:** calls time out at 5 ms and fail open; replica promoted in 10-15 s; counters restart full, allowing one extra burst.
- **Whole Redis cluster unreachable:** all gateways enforce limit / fleet size locally; the load shedder protects backends; no customer-visible errors.
- **Rules service or Postgres down:** gateways keep the last snapshot; emergency blocks via a break-glass etcd key.
- **Bad rule shipped:** a 429 spike alert within a minute; one-click rollback to the previous version.
- **Backend overloaded with all clients in limits:** the shedder drops batch then normal traffic with 503; critical calls keep reserved capacity.
- **Kafka down:** decision events drop from a bounded buffer; enforcement unaffected.

**Trade-offs chosen:**
- **Regional Redis over in-process or global counters:** in-process allows N x the limit; global costs 60-150 ms; regional is about 0.3 ms.
- **Fail open over fail closed:** a limiter outage must not become an API outage; local limits keep most protection.
- **Latency over consistency across regions (PACELC):** shares plus 5 s rebalancing, safe under partition.
- **Filter in the gateway over a separate service:** one less hop and service to run.
- **Soft monthly quotas plus offline reconciliation:** a small overage is cheaper than global coordination.
- **Rate limits plus load shedding:** limits protect from one client, shedding from everyone at once; 20% capacity reserved for checkout and payment.

**What to measure:** added latency p50/p99/p999 per node, Redis errors and fail-open decisions, 429 rate by key, endpoint and plan, 503 shed rate by priority, per-shard CPU and top hot keys, snapshot version skew and propagation time, shadow would-deny counts, clients ignoring Retry-After, backend p99.

## Page 5. Say it in the interview

> "First I pin down what the limiter protects and how exact it must be. Assume 1M requests a second per region across about 400 gateway nodes, limits by API key and endpoint class, under a millisecond at p99, and that a few percent over for a few seconds is fine but billing quotas are exact. A token bucket in each gateway's memory is fast but gives a client N times its limit across N nodes. So the bucket lives in a sharded Redis cluster per region, updated by one atomic Lua script per check, with rules pushed to gateways and cached. On top I add a concurrency limiter and a fleet load shedder that reserves capacity for critical calls. Redis CPU is the bottleneck, so I shard and lease tokens for hot tenants, and the limiter fails open with a 5 ms timeout."

**Key points to land:**
- On every request: under 1 ms p99, and it must fail open.
- Token bucket = rate plus burst in two numbers; sliding window counter fixes the 2x edge.
- One atomic Lua script per check; Redis TIME avoids clock skew.
- Redis CPU is the bottleneck: 2M ops/s needs 20-30 shards; memory is only 3 GB.
- Sharding does not fix a hot key: split it or lease tokens.
- Global quotas as regional shares rebalanced every 5 s: bounded error, no cross-region hop.
- Layers: per-key rate, concurrency limit, load shedder with reserved critical capacity.
- 429 with Retry-After; clients back off with jitter and use idempotency keys.
- Rules pushed, versioned, shadow-tested and instantly reversible.

**Likely follow-ups:**
1. **Is the limiter a single point of failure?** No: it is a library in every gateway, Redis is sharded with replicas, calls time out at 5 ms, and failure means looser limits, never failed requests.
2. **Limit by cost, not count?** Give each endpoint a token cost (a bulk update of 100 items costs 100) and take n tokens in the same script.
3. **A customer says they are limited below plan?** Check their snapshot version, the decision events for the denying rule, a shared IP limit, and hot-key splitting; rule IDs in the 429 make it fast.
4. **Roll out a tighter limit safely?** Shadow mode first, review would-be denials, tell affected customers, enforce on a share of nodes, then all, with a kill switch.
5. **What if limits must be exact?** Route that key to one strongly consistent authority, accept the latency for that product, and fail closed; or sell prepaid credits with durable, idempotent decrements.

**Director layer:**
- **Cost drivers:** Redis CPU (60 nodes per region), kept under 3% of gateway infrastructure; Kafka and ClickHouse for decision analytics.
- **Phasing:** start with regional Redis token buckets and pushed rules; add leasing, shadow mode, regional quota shares and priority shedding as traffic grows.
- **Team ownership:** API platform owns the filter, Redis and rules; service owners set endpoint costs and priorities; SRE owns shedding and kill switches.
- **Top risks:** a Redis outage slowing every call, a bad rule blocking a big customer, hot tenants overloading a shard, clients retrying immediately on 429.
