# Design retries, timeouts and circuit breakers (resilient service client): the 5-page summary

This is a shared resilience layer that every service uses for its outbound calls: deadlines, budgeted retries with jitter, circuit breakers, bulkheads and fallbacks. The single most important idea: the danger is not the failing call but how a whole fleet of callers reacts to it, so retries must be scarce and bounded and a partial outage must stay partial.

## Page 1. The problem, scope and numbers

**Pitch:** checkout depends on 4-8 internal services. In the last sale event a 2-minute Pricing slowdown filled Order service thread pools, retries from three layers tripled Pricing load, and checkout failed for 14 minutes after Pricing had recovered. We build one standard layer so that cannot happen again.

**Who uses it:** service developers (simple policy, typed errors), on-call SREs (dashboards, live knobs), dependency owners (callers that back off), payments (zero duplicate captures).

**In scope:**
- **Deadlines:** set at the edge, propagated hop by hop; each hop fails fast if too little time remains.
- **Retries:** only retryable errors, exponential backoff with full jitter, honour Retry-After, capped by a token-bucket budget.
- **Circuit breakers:** closed, open, half-open on failure rate and slow-call rate over a sliding window.
- **Bulkheads:** a concurrency limit per dependency with fast rejection when full.
- **Fallbacks, idempotency, runtime policy:** cached or default answers; keyed write retries; config live in 30 s with rollback.

**Out of scope:** cross-region failover, queue retries and dead-letter queues, edge rate limiting, autoscaling.

**Non-functional targets:**
- **Overhead and reaction:** under 1 ms p99 per call; breaker opens within 10 s of 50% failures.
- **Amplification and recovery:** retries add at most 10% load; checkout back within 60 s of a heal.
- **Availability and correctness:** 99.5% for paths with a fallback; zero duplicate side effects.

**Capacity math (Order service: 20k RPS peak, 400 pods, 4 downstream calls each):**
- **Retry amplification:** 3 attempts at each of 3 layers = 27x, so 20k RPS can become 540k RPS on a failing Pricing. One retrying layer with 2 retries is 3x (60k); with a 10% budget it is 22k. So retry at one layer only, under a budget.
- **Bulkheads (Little's law, in-flight = RPS x latency):** 50 RPS per pod x 0.04 s = 2 in flight healthy; at 2 s latency, 100. So a bulkhead of 20 per dependency per pod is the right scale.
- **Threads:** 200 workers per pod; a 30 s default timeout fills them in 200 / 50 = 4 s. With a 150 ms per-try timeout the pod never saturates. So every call needs a short timeout.
- **Deadline:** 800 ms total = Inventory 100 ms and Pricing 150 ms in parallel, then Payment 500 ms, plus 50 ms own work, about 700 ms. Only 100 ms is left for one fast retry. So retries are scarce.
- **Idempotency store:** 20k x 30% = 6k writes/s, 518M keys/day x 200 B = about 100 GB/day. So a sharded KV with a 24 h TTL.

## Page 2. The architecture

```
 Client -> API Gateway (sets deadline 800 ms, request-id)
             |
             v
 Order Service pod
   Handler -> ResilientClient [deadline | bulkhead | breaker | retry]
                |          |              |              ^
                |    Fallback cache  Metrics, traces  Policy cache <- Registry
                | gRPC + grpc-timeout + idempotency-key
                v
 Inventory     Pricing       Payment          Promotions
 (admission    (admission    (admission       (admission
  + shedding)   + shedding)   + idem. check)   + shedding)
                                 |
                                 v
                          Idempotency KV (24 h TTL)
```

- **ResilientClient:** wraps every outbound call; library for business calls, Envoy sidecar for defaults.
- **Policy Registry:** versioned per-dependency policies, validated, staged rollout, pushed within 30 s.
- **Deadline propagator:** reads remaining time, writes it on outgoing calls, refuses hopeless work.
- **Retry budget:** token bucket; success adds 0.1 token, retry costs 1, so retries stay under 10%.
- **Circuit breaker:** in-process sliding window, closed/open/half-open per dependency or endpoint.
- **Bulkhead:** semaphore per dependency; rejects instantly when full.
- **Fallback providers:** last-good cache, static defaults, or a typed degraded result.
- **Server admission control:** concurrency limits, shedding by priority, 429/503 with Retry-After.
- **Idempotency store:** key to stored result for 24 h, so a retried write returns the original.

**Flow A: read with one transient failure**
1. Gateway sets deadline T+800 ms; budget = min(per-try 150 ms, remaining 790 - 20 ms margin) = 150 ms.
2. Bulkhead has room (3/20), breaker CLOSED; attempt 1 gets a connection reset after 5 ms.
3. Budget has tokens; full-jitter backoff picks 31 ms; attempt 2 on another host succeeds in 35 ms.

**Flow B: outage and recovery**
1. Pricing fails 70% of calls; the 10 s window (min 20 calls) crosses 50%; breaker OPENS.
2. Calls fail fast in microseconds; the fallback serves a cached price (60 s TTL) flagged stale.
3. After 30 s, HALF-OPEN admits 5 probes; 4 of 5 succeed and it CLOSES, else it reopens with the wait doubled, up to 2 minutes.

## Page 3. The core deep dives

### 1. Retries that do not cause a storm
Retry only retryable signals: connect failure, 503, UNAVAILABLE, 429 with Retry-After, or a per-try timeout on an idempotent call. Never retry a 4xx. Max 3 attempts, backoff base 50 ms, cap 1 s, with full jitter: the delay is random between 0 and the ceiling, so clients that failed together spread out instead of returning in waves. Retry-After wins, but never past the deadline. Then the retry budget: each request deposits 0.1 token (cap 100), each retry spends 1. In steady state retries cannot exceed 10%; in an outage the bucket empties and retries stop. Retry at exactly one layer; the others set max attempts to 1.

### 2. Deadlines, not just timeouts
The edge sets an 800 ms deadline and each hop passes the remaining duration (grpc-timeout style), not a wall-clock time, so clock skew does not matter. Each attempt uses min(per-try timeout, remaining minus a margin). If the remaining time is below the minimum useful time, the hop returns DEADLINE_EXCEEDED at once instead of doing work nobody will read. Per-try timeouts come from p99.9 plus headroom (Pricing p99.9 is 90 ms, so 150 ms): about 0.1% false timeouts with bounded thread holding.

### 3. Circuit breaker and bulkhead
Ten 1-second buckets live in process memory. The breaker opens when there were at least 20 calls and the failure rate is 50% or more, or the slow-call rate is 80% or more. Open lasts 30 s plus or minus 20% jitter, so 400 pods do not probe at once. Before the dependency-wide breaker, outlier ejection removes a bad host (5 consecutive 5xx, ejected 30 s, at most 10-20% of hosts). The bulkhead caps in-flight calls per dependency so a slow Promotions cannot eat the threads Payment needs.

### 4. Safe retries on payment writes
Order creates key = hash(order_id, attempt_group) once. A capture times out and the outcome is unknown, so the client retries once with the same key. Payment claims the key with insert-if-absent: if the first attempt finished, it returns the stored result; if still running, 409 and the client polls. The same key with a different body gets 422. If the idempotency store is down, Payment rejects keyed writes with 503 rather than risk a double charge.

**Data model:**
- **ResiliencePolicy** (registry, cached in memory): PK (service, dependency, method_glob); timeouts, attempts, backoff, budget ratio, breaker and bulkhead settings, fallback, version.
- **IdempotencyRecord** (sharded KV): PK key, shard by hash(key), 24 h TTL; request_hash, status, response.
- **BreakerWindow** (in-process only): ring of buckets, state, opened_at, probes. Local by design.

**Key APIs:**
- `client.call(dep, method, req, ctx)`: one entry point; returns a result or typed error (Timeout, CircuitOpen, BulkheadFull, BudgetExhausted, DeadlineExceeded).
- `PUT /v1/policies/{service}/{dependency}`: validated, audited, rolled out 1% -> 10% -> 100%.
- `POST /v1/payments/capture`: Idempotency-Key header; 200, 409 in progress, or 429/503 with Retry-After.
- `POST /v1/resilience/override`: force open, force closed or disable retries, with an auto-expiring TTL.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x (sale-day peak):**
- **The sick dependency:** extra load from us is capped at 10% by the budget and drops near zero once the breaker opens.
- **Caller threads:** short per-try timeouts plus bulkheads sized by Little's law keep pods responsive.
- **Tail latency on fan-out reads:** hedge idempotent reads after the p95 delay, capped at 5% extra load, off when the breaker is not closed.
- **Writes:** retried only with idempotency keys, stored server-side in a sharded KV.
- **Servers:** shed by priority and drop requests whose deadline already passed; do not trust clients to be polite.

**Failure modes:**
- **Dependency hard down:** attempts fail in milliseconds, breaker opens within 10 s, fallback served, probes detect recovery.
- **Dependency slow (p99 40 ms to 3 s):** 150 ms per-try timeout cuts each call; slow-call rate trips the breaker; bulkhead keeps in-flight at 20.
- **Policy registry down:** clients keep the last good policy in memory and on disk, with compiled-in defaults; no traffic impact.
- **Bad policy pushed (10 ms timeouts):** the 1% cohort shows an error spike and rolls back automatically.
- **Idempotency store down:** Payment returns 503 for keyed writes; checkout shows "retry later".
- **Retry storm after a partition heals:** jitter spreads, budget caps, servers shed, amplification alert pages on-call.
- **Breaker flapping:** open time doubles up to 2 minutes; alert on transitions per minute.

**Trade-offs chosen:**
- **Both sidecar and library, retries in only one:** the mesh is language-agnostic; the library knows idempotency and fallbacks.
- **Timeout at p99.9 plus headroom over tight p99:** tight ones cause false failures and retries at peak.
- **Local breaker state over shared Redis:** no new hot-path dependency; local breakers converge within seconds.
- **Max attempts plus a 10% budget over attempts alone:** attempts bound one request, the budget bounds the fleet.
- **Per-host ejection plus per-dependency breaker:** bad nodes are removed without cutting off a healthy service.
- **Fail payment fast over fake success:** money correctness beats availability.

**What to measure:** success rate and p50/p99/p99.9 latency per dependency; retry ratio and budget exhaustion; amplification factor (downstream calls per upstream request, target 1.1x or less); breaker state and transitions; bulkhead rejections; deadline-exceeded per hop; fallback rate and stale age; server shed rate; idempotency replays and 409s; checkout SLO burn rate.

## Page 5. Say it in the interview

> "Say an Order service at 20k RPS calls Inventory, Pricing, Payment and Promotions with an 800 ms checkout SLO. The classic melt-down is not the failure itself but the callers: three retrying layers give 27x load, and a 30 s timeout fills 200 threads in 4 seconds. So every outbound call goes through one resilience layer. The edge sets a deadline and each hop passes the remaining time. Per-try timeouts come from p99.9. We retry only retryable errors, at one layer, at most twice, with full jitter and a 10% retry budget. Each dependency has a circuit breaker on failure and slow-call rate, plus a bulkhead so a slow Promotions cannot starve Payment. Every call site declares a fallback, and payment retries reuse an idempotency key. Then I prove it with fault injection."

**Key points to land:**
- The risk is how callers react: retries and missing timeouts turn partial failures into total ones.
- Every call has a connect timeout, a per-try timeout from p99.9, and a propagated deadline.
- Retry only retryable errors on idempotent or keyed calls; max 3 attempts; full jitter.
- One retrying layer plus a 10% budget; watch the amplification factor.
- Breakers need minimum volume; open means fail fast and use the fallback.
- Bulkheads sized by Little's law contain one slow dependency.
- Idempotency keys: client generates once, server claims atomically.
- Servers must shed by priority and send Retry-After; client politeness is not enough.
- Prove it with fault injection and game days, not by reading config.

**Likely follow-ups:**
1. **Why not long timeouts and 5 retries?** Each waiting call holds a thread and each retry adds load; under a real outage that exhausts the caller and multiplies load on the dependency.
2. **Local breakers on 400 pods, isn't recovery noisy?** At most 5 probes per pod, 2,000 over a jittered window, tiny next to 20k RPS; a central override can force all breakers if needed.
3. **How do you stop the mesh and the library both retrying?** Library-owned calls set mesh retries to zero, a linter checks both configs, and an attempt header exposes double retries in traces.
4. **Hedging versus retrying?** Retry waits for failure; hedging sends a second copy after p95 and takes the first answer. Only idempotent reads, capped, off when unhealthy.
5. **A dependency returns 200 with empty data?** The breaker misses it by default; add response validation that counts semantic failures and alert on content metrics.

**Director layer:**
- **Phasing:** ship sidecar defaults first (connect timeouts, outlier ejection, no code change), then onboard tier-1 services with explicit policies; target 100% of tier-1 in 2 quarters; CI blocks new services without a policy.
- **Team ownership:** the platform team owns the library, sidecar config and Policy Registry; product teams own fallbacks; dependency owners own admission control; SRE runs game days before sale events.
- **Cost drivers:** a 100 GB/day idempotency KV, metrics series per pod, and engineering time for fallbacks.
- **Top risks:** breakers tripping on a few bad hosts, timeouts too tight at peak, untested fallbacks, and teams bypassing the library (fixed by a lint rule and mesh egress policy).
