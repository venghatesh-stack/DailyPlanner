# Role-based access control (centralized authorization service): recall card

> **Hook:** Roles as scoped tuples → Changelog with revisions → Whole graph in memory → Sidecar cache 5 s → Revision token when it matters

**P · Problem:** It's really a low-latency graph lookup over a small, slowly changing dataset where staleness after a revoke is the danger.

**N · Numbers:**
1. 400M tuples x 40 B = 16 GB, about 40 GB with indexes, so the whole graph fits in memory and checks scale by replication.
2. 500k checks/s with 40% cache misses is 200k/s at 50 us each, so about 30 small replicas across 3 zones.
3. Only 200 writes/s, so every replica can tail the full changelog.

**H · Hard part:** Answering checks in under 5 ms while revocations stick within 10 seconds.

**B · Boxes:** `Service + SDK cache → Check replica → In-memory graph → Allow or deny with revision`

Side path: `Policy Admin API → Tuple store → Kafka changelog → Check replicas`, with snapshots to S3.

**D · Decisions:**
1. Central check replicas with a sidecar cache over roles in tokens, because tokens go stale and bloat.
2. Consistency per request over always strong, because only causal cases need fresh data and the rest can take 10 s staleness.
3. Fail closed by default over fail open, because a wrong refund costs more than a retry.

**F · Failures:**
1. Tuple store down → checks continue from memory; writes return 503; emergency revokes use a replica override channel.
2. Changelog lag → alert at 3 s; replicas over 30 s mark themselves unready and token checks are forwarded.

**C · Close:** "I model scoped RBAC as tuples, and a check walks up the scope tree. Writes go to a strongly consistent store and get a revision. A changelog feeds check servers holding the 16 GB graph in memory, so checks take microseconds. Services enforce through an SDK with a 5-second cache. Revision tokens give read-your-writes; everyone else tolerates 10 seconds. Sensitive actions fail closed."

**Quiz yourself:**
1. What is the new enemy problem? → A lagging replica lets a just-removed user read content created after the removal.
2. How is the 10 s revocation budget spent? → Publish, 1-2 s apply, and at most a 5 s SDK cache TTL.
3. How do you show only orders a user can see? → ListResources for scopes, filter the query, BatchCheck the visible page.
