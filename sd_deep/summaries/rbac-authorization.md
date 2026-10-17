# Design role-based access control (centralized authorization service): the 5-page summary

Authentication says who the caller is; authorization decides, on every request, whether that caller may do this action on this resource. The single most important idea: keep the whole permission graph in memory on replicated check servers fed by an ordered changelog, so checks take microseconds, and use revision tokens so a caller can demand fresh data only when it matters (the "new enemy" problem).

## Page 1. The problem, scope and numbers

**Pitch:** one authoritative service that answers "can this user do this action on this resource?" for every service, in under 5 ms, and makes revocations stick within 10 seconds.

**Why:** today authorization is scattered across hundreds of services. Role names are hard-coded, roles are baked into long-lived tokens, removed seller staff keep access for hours, and auditors cannot answer "who can refund orders for seller X".

**Who uses it:** seller owners (create staff, assign roles scoped to their stores), service developers (call check and get an answer with a reason), compliance auditors (quarterly exports of who has finance permissions) and support agents (temporary elevated access that expires).

**In scope:**
- **Model:** permissions (resource_type.action), roles with inheritance, groups of principals.
- **Scoped assignments:** a role on global, tenant or sub-resource scope (warehouse, store); scopes form a tree.
- **Check:** with conditions from context (region, time window, amount); BatchCheck up to 100; ListResources.
- **Least privilege:** time-bound grants, approvals for privileged roles, separation-of-duties checks on write.
- **Consistency and audit:** revision tokens for read-your-writes; full audit and an Explain API.

**Out of scope:** authentication and MFA, row-level security inside databases, network access control, consumer link sharing, a rich policy UI in phase 1.

**Non-functional targets:**
- **Latency:** Check p99 under 5 ms server side; sidecar cache hit under 0.2 ms.
- **Throughput:** 500k checks/s peak, headroom to 1M.
- **Availability:** 99.995% for Check, 99.9% for admin writes.
- **Freshness:** bounded staleness 10 s; read-your-writes on request.
- **Durability and audit:** RPO 0 with multi-zone synchronous replication; 100% of writes audited.

**Capacity math (20M principals, 400M tuples):**
- **Memory:** 400M tuples x 40 B = 16 GB; with forward and reverse indexes about 32-40 GB. It fits on a 64 GB machine, so checks are pure in-memory work that scale by replication.
- **Checks:** 500k/s x 40% cache misses = 200k/s to servers. At 20k checks per core per second (50 us each), that is 10 cores; with 3x headroom over 3 zones, about 30 replicas of 4 cores.
- **Writes:** 200/s x 200 B = 40 KB/s, bursts of 1 MB/s. Tiny, so every replica can tail the full changelog.
- **Audit:** 1% of 500k = 5k decisions/s x 300 B = 1.5 MB/s, about 130 GB/day.
- **Bootstrap:** a 16 GB snapshot at 500 MB/s loads in about 35 s, then the replica tails the log. So recovery is fast.

## Page 2. The architecture

```
 Admin UI / Seller console
     v
 Policy Admin API --txn--> Tuple store (Spanner/Cockroach)
 (validate SoD,            tuples + changelog with revisions
  approvals, schema)              | CDC, revision ordered
                                  v
                         Kafka authz.changes ----> S3 snapshots
                            |               |
                 tail+apply |               | tail
                            v               v
 Service A + SDK --gRPC--> Check replicas    List / reverse index
 (cache 5 s)  <---------- (in-memory graph   (per tenant)
     |                     @ revision R)
     v sampled decisions
 Audit / SIEM
```

- **Policy Admin API:** CRUD for roles and assignments; validates SoD and approvals; returns a revision.
- **Tuple store:** strongly consistent source of truth plus the ordered changelog.
- **Changelog (Kafka):** revision-ordered changes, partitioned by tenant.
- **Snapshotter:** every 15 minutes writes the graph at revision R to object storage.
- **Check replicas (PDP):** in-memory graph; evaluate Check with conditions; report revision.
- **List / reverse index:** subject to accessible resources, for list pages.
- **SDK / sidecar (PEP):** cache with max TTL, deadlines, retries, fail mode per action.
- **Policy-as-code repo:** roles in reviewed YAML, deployed with dry-run diffs.
- **Audit pipeline:** all writes, sampled decisions, all sensitive denies.

**Flow A: check on the hot path**
1. Order service builds Check(u42, order.refund, order:987, amount 12,000, seller s7).
2. SDK cache hit returns at once; on a miss, gRPC to the nearest replica, 20 ms deadline.
3. Replica walks order:987 -> seller:s7 -> global, unions direct and group roles.
4. Refund Agent allows up to 10,000, so 12,000 is denied with a reason and revision R.

**Flow B: revoke with read-your-writes**
1. Owner deletes (u42, Catalog Manager, seller:s7); the Admin API first checks role.manage.
2. Tuple deleted and changelog row R+1 appended in one transaction; R+1 returned.
3. Replicas apply in 1-2 s; SDK caches expire within 5 s.
4. A check with at_least_revision R+1 on a lagging replica waits 50 ms, else is forwarded.

## Page 3. The core deep dives

### 1. Scoped RBAC as tuples
An assignment is a Zanzibar-style tuple: seller:s7#catalog_manager@user:u42 means "u42 is catalog manager on seller s7". Groups nest via subject_relation (group:g1#member). A check walks the scope chain from the resource up to global; at each scope it unions roles held directly and through groups. Role permissions are pre-flattened with inheritance into bitsets (about 500 roles, 5,000 permissions), so the final test is a bit test. Conditions (CEL expressions such as amount <= 10000) run only on roles that grant the permission. RBAC is a special case of relationship-based access (ReBAC), so the tuple format leaves room for ownership and sharing later.

### 2. The new enemy problem and revision tokens
Example: Shreya removes Sethu from her store, then uploads a confidential price file. A lagging replica still thinks Sethu has access and lets him read the new file. Fix: every write gets a totally ordered revision (Spanner commit time or a sequence). The content write records its revision, and reads of that content pass at_least_revision, so the check cannot run on a snapshot older than the revocation (Zanzibar's "zookie"). Everyone else accepts bounded staleness of 10 s, which is far cheaper.

### 3. Replicas from snapshot plus changelog
A replica loads the latest snapshot (about 35 s), then tails Kafka from that revision. Changes apply strictly in revision order per tenant into copy-on-write segments that are swapped atomically, so readers never lock. Within a batch, deletes apply before inserts, so a racing grant and revoke never leave extra privilege. Bulk onboarding (5M tuples) goes to a separate low-priority topic so it cannot delay revocations.

### 4. Revocation budget and fail modes
The 10 s SLO is split across publish, apply (1-2 s) and a 5 s maximum SDK cache TTL. Denies are cached shorter than allows, and a TTL never outlives a grant's expires_at. If the PDP is unreachable, the fail mode is per permission and closed by default: viewing your own orders can use a stale allow; refunds, payouts and admin actions fail closed.

**Data model:**
- **tuples** (Spanner/CockroachDB): PK (tenant_id, object_type, object_id, relation, subject_type, subject_id); index (tenant_id, subject_id); optional expires_at.
- **changelog:** PK revision; to Kafka keyed by tenant_id; op, tuple, actor.
- **role_definitions:** permissions, inherits, CEL conditions, privileged flag, SoD conflicts.
- **in-memory graph:** interned ids; (subject, scope) -> role bitset; scope -> parent; applied revision.
- **reverse index** (RocksDB per shard): tenant|permission|subject -> sorted resource ids.

**Key APIs:**
- `AuthZ.Check`: subject, permission, resource, scope hint, context, optional at_least_revision; returns allowed, reason, revision.
- `AuthZ.BatchCheck`: up to 100 items sharing scope and role resolution.
- `AuthZ.ListResources`: paginated accessible ids from the reverse index.
- `POST /v1/assignments`: SoD and approval checks, optional expiry; returns a revision.
- `GET /v1/explain`: the path subject -> group -> role -> scope, for "why".

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Check reads:** add replicas; shard by tenant when the graph outgrows RAM.
- **Graph expansion:** keep it shallow, precompute effective roles per scope, stop at the first allow.
- **Huge tenants (50k staff, 20k stores):** own shard group; ListResources returns a wildcard "all stores" grant instead of enumerating.
- **Global roles checked everywhere:** small, replicated to every replica, cached per subject.
- **Role change hitting 2M principals:** one flattened change per replica; reverse-index rebuild throttled per tenant.

**Failure modes:**
- **Replicas in one zone down:** SDK goes cross-zone, about 1 ms extra; N+1 zone capacity.
- **Changelog lag:** alert at 3 s; replicas over 30 s mark themselves unready; token checks are forwarded.
- **Tuple store down:** checks continue from memory; writes return 503; emergency revokes use a replica override channel, reconciled later.
- **Bad role definition grants admin:** allow-rate anomaly alert; policy-as-code rollback in minutes; audit finds affected decisions.
- **Cold caches after an outage:** jittered backoff, one in-flight check per key in the sidecar, per-caller limits.
- **Corrupt snapshot:** checksum fails; load the previous snapshot and replay a longer log.

**Trade-offs chosen:**
- **Central PDP replicas with a sidecar cache over roles in tokens or in-service graphs:** tokens go stale and bloat; a 16 GB graph in every service is waste.
- **Scoped RBAC as tuples over pure ABAC:** matches how sellers think, and "who can" stays answerable.
- **Consistency per request over always strong:** strong only for causal cases; bounded staleness for the rest.
- **5 s SDK TTL:** fits the 10 s revocation SLO with about 60% hit rate.
- **Fail closed by default over fail open:** a wrong refund costs more than a retry.
- **Build on SpiceDB/OpenFGA ideas over buying:** control of conditions, latency and Indian data residency.

**What to measure:** Check p50/p99/p999 server and client side; SDK hit rate and entry age; replica revision lag; revocation time from commit to first deny via synthetic probes; allow/deny ratio per permission and caller with anomaly detection; token wait and forward rate; fail-open events; CEL errors; snapshot age; outstanding privileged and JIT grants.

## Page 5. Say it in the interview

> "I will pin the model first: scoped RBAC, where roles are granted on a scope such as a seller account or a warehouse, with inheritance and a few conditions like refund amount. Scale is about 400 million tuples and 500 thousand checks a second at 5 milliseconds p99, and when a seller removes an employee, access must end within 10 seconds. A Policy Admin API writes tuples to a strongly consistent store and stamps each change with a revision. A changelog streams changes to stateless check servers that hold the whole 16 GB graph in memory, so a check is a few hash lookups. Services enforce through a sidecar SDK with a short cache. Reads scale by replicas and tenant sharding. The subtle problem is staleness: writes return a revision token for read-your-writes; everyone else tolerates 10 seconds. Sensitive actions fail closed."

**Key points to land:**
- Separate enforcement (SDK), decision (replicas) and administration (API plus policy-as-code).
- Scoped RBAC as Zanzibar-style tuples, inherited down the scope tree.
- The graph is about 16 GB: in memory, microsecond checks, scale by replication.
- Ordered changelog with revisions; snapshots bound bootstrap time.
- New enemy problem: revision tokens on demand, bounded staleness by default.
- 10 s revocation budget includes a 5 s maximum cache TTL.
- Fail closed by default; fail open only for marked low-risk reads; bulkheads per caller.
- Least privilege: SoD on write, expiring just-in-time grants, access reviews.
- List pages use ListResources plus a query filter, not 10k checks.

**Likely follow-ups:**
1. **"Only orders I can see" on a 10k-order list?** Get accessible scopes with ListResources (say 3 stores), filter the query by store_id, and BatchCheck only the visible page.
2. **Service-to-service calls?** Calls carry the service identity (mTLS) and the end user; policy can require both, which stops confused-deputy bugs.
3. **Custom roles per tenant?** Tenant-scoped roles built from the global permission catalog, capped at about 50 per tenant to bound memory.
4. **Multi-region?** Spanner-style globally ordered revisions, Kafka mirrored per region, local checks; Indian tenants pinned to India regions.
5. **Test a policy change?** Unit tables of expected allow and deny, a dry-run on a snapshot counting principals who gain or lose access, then a shadow-mode canary.

**Director layer:**
- **Cost drivers:** about 30 small check replicas across 3 zones, the strongly consistent tuple store, and 130 GB/day of audit data.
- **Phasing:** shadow mode alongside legacy token role claims, comparing decisions; then enforce per service, targeting 90% of services off hard-coded checks in 3 quarters.
- **Team ownership:** authorization platform (PDP, SDK, changelog), security and compliance (SoD, reviews), and product teams for their own permissions in policy-as-code.
- **Top risks:** an outage blocking every service, stale replicas granting access after revocation, a policy mistake granting admin widely, and teams bypassing the SDK with caches that never expire.
