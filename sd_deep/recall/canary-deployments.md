# Canary deployment and rollback strategy: recall card

> **Hook:** Start canary and fresh baseline → Route 1% → Compare statistically → Promote 5, 25, 50, 100 → Flip weight to zero on fail

**P · Problem:** It's really a statistical decision problem: is the new version worse, judged on a small slice of real traffic?

**N · Numbers:**
1. Catching 0.1% to 0.2% errors needs about 24k requests per arm, about 8 minutes at 50 RPS, so the 1% step bakes 10 minutes.
2. 5% for 10 minutes exposes about 0.035% of the day's requests, so blast radius is about 30x smaller than a full bad deploy.
3. 2 canary plus 2 baseline pods on a 100-pod service is 4% extra, so it fits the 10% headroom.

**H · Hard part:** Getting enough statistical power on small traffic, and keeping versions N and N-1 compatible so rollback works.

**B · Boxes:** `CI → Artifact registry → Rollout controller → Envoy mesh weights → Canary analysis → Prometheus`

Side path: `Policy engine → freezes and error budget checked before every step`.

**D · Decisions:**
1. A fresh baseline over comparing with the fleet, because the long-running fleet has warm caches and always looks better.
2. A weight flip during rollout over redeploying, because stable pods stay warm and traffic moves in seconds.
3. Full automation with auto-abort over human approval per step, because humans read graphs slowly and inconsistently.

**F · Failures:**
1. Metrics store down → NODATA verdict, the rollout pauses at current weights, never promotes.
2. Controller crash → traffic keeps its weights; a new leader takes the lease in about 15 s and reconciles from the mesh.

**C · Close:** "Since most incidents come from changes, I design deployment as a safety net. A controller shifts traffic in steps of 1, 5, 25, 50 and 100 percent in the first region, then the others after a bake. Each step compares the canary with a fresh baseline using a nonparametric test. Fail flips the canary weight to zero in seconds. Rollback only works if changes are backward compatible, so schemas use expand and contract."

**Quiz yourself:**
1. Which test compares canary and baseline? → Mann-Whitney U plus a practical effect-size threshold.
2. Low-traffic internal service? → Bigger first steps, longer bakes, synthetic traffic and fast rollback.
3. How do you change a schema safely? → Expand, deploy readers with fallback, then contract weeks later.
