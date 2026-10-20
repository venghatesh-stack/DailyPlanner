# Retries, timeouts and circuit breakers (resilient service client): recall card

> **Hook:** Edge sets deadline → Per-try timeout from p99.9 → Retry once with jitter under a budget → Breaker opens → Fallback

**P · Problem:** It's really a fleet-wide feedback-control problem: how callers react to a failure decides whether it stays partial.

**N · Numbers:**
1. 3 attempts at each of 3 layers is 27x, turning 20k RPS into 540k RPS, so retry at one layer only, under a 10% budget.
2. A 30 s timeout fills 200 worker threads in 4 s, so every call needs a short per-try timeout.
3. An 800 ms deadline leaves only 100 ms after the call chain, so retries are scarce.

**H · Hard part:** Stopping retries and missing timeouts from turning one slow dependency into a fleet-wide outage, without double-charging payments.

**B · Boxes:** `API Gateway → Handler → ResilientClient → Bulkhead → Breaker → Dependency`

Side path: `Payment → Idempotency KV (24 h TTL)` for safe write retries.

**D · Decisions:**
1. Max attempts plus a 10% retry budget over attempts alone, because attempts bound one request and the budget bounds the fleet.
2. Local breaker state over shared Redis, because it adds no hot-path dependency and local breakers converge in seconds.
3. Timeouts at p99.9 plus headroom over tight p99, because tight ones cause false failures and retries at peak.

**F · Failures:**
1. Dependency slow, p99 from 40 ms to 3 s → 150 ms per-try timeouts cut calls; slow-call rate trips the breaker; the bulkhead holds 20 in flight.
2. Idempotency store down → Payment returns 503 for keyed writes rather than risk a double charge.

**C · Close:** "The classic meltdown is the callers, not the failure: three retrying layers give 27x load, and a 30-second timeout fills every thread. So every outbound call goes through one resilience layer. The edge sets a deadline and each hop passes the remaining time. We retry only retryable errors, at one layer, with full jitter and a 10% budget. Each dependency gets a breaker and a bulkhead, every call declares a fallback, and payment retries reuse an idempotency key."

**Quiz yourself:**
1. Why full jitter? → Clients that failed together spread out instead of returning in waves.
2. How is a bulkhead sized? → Little's law: in-flight equals RPS times latency.
3. Why pass remaining time, not a wall-clock deadline? → Clock skew between hosts does not matter.
