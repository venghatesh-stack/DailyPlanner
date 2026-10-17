# Design a canary deployment and rollback strategy: the 5-page summary

Most outages are caused by changes, so the deploy pipeline is a reliability system: expose each change to a small slice of real traffic, judge it statistically against a fresh baseline, and back out automatically. The key idea: rollback is a weight flip in seconds because stable pods stay warm, and it only works if versions N and N-1 are compatible.

## Page 1. The problem, scope and numbers

**Pitch:** catch bad builds on a few percent of traffic and roll back within a minute without humans, so teams ship more often with less risk. Today a deploy hits 100% of a cluster in minutes and rollback is a 10-15 minute redeploy.

**Who uses it:** service engineers (self-serve deploys, clear failure reports), SRE and platform (fewer change incidents, guardrails, audit), release managers in sale events (freezes, emergency path), leadership (DORA metrics) and compliance.

**In scope:**
- **Strategy per service:** weighted steps, bake time, analysis template, region order, approvals.
- **Canary plus fresh baseline:** equal pod counts, weighted or sticky user-hash routing.
- **Automated analysis:** score each step; promote, hold, extend or abort.
- **Policy gates:** freezes, error budget, concurrency, approvals, deploy windows.
- **Manual controls and audit:** pause, resume, promote, abort, rollback; every action logged.
- **Config and flags** rolled out the same progressive way.

**Out of scope:** mobile binary rollouts, batch and pipeline releases, building the service mesh, A/B experiment statistics, database and Kubernetes upgrades.

**Non-functional targets:**
- **Rollback:** traffic off the canary within 30 s of abort, p99 under 60 s.
- **Detection:** a 10x error regression caught within 5 minutes at the 1-5% step on tier-0.
- **Blast radius:** at most 5% of a region's traffic before the first full analysis passes.
- **Availability:** controller 99.9%; its outage pauses rollouts, never serving traffic.
- **Overhead and audit:** under 10% extra pods; 100% of changes logged with actor, sha, approvals.

**Capacity math (400 services, 150 deploys/day growing to 300, tier-0 at 5k RPS per region):**
- **Concurrency:** 300 deploys in 10 hours = 30/hour x 0.75 h = about 23 rollouts at once. Small, so one controller tier suffices.
- **Analysis load:** 23 x 20 queries/min = 460/min, about 8/s. Trivial with recording rules.
- **Signal at 1%:** 50 RPS = 3,000 requests/min; 0.1% errors is 3/min, a bad 1% is 30/min; 30 vs 300 in 10 minutes is clearly significant.
- **Small regressions:** 0.1% to 0.2% needs about 16 x p(1-p) / delta^2 = 24k requests per arm, about 8 minutes at 50 RPS. So the 1% step bakes 10 minutes. Statistics, not infrastructure, is the binding constraint.
- **Pods:** 2 canary plus 2 baseline on a 100-pod service = 4% extra. Fits the 10% headroom.
- **Exposure:** 5% for 10 minutes = 0.05 x 10/1440 = about 0.035% of the day's requests, versus about 1% for a full 15-minute bad deploy: about 30x less.

## Page 2. The architecture

```
 Merge -> CI build -> signed image (sha) -> artifact registry
                               |
 Release API/UI --plan--> Rollout controller <--gate-- Policy engine
   (start, pause,          (per-service state       (freeze, error
    promote, abort)         machine, leader lease)   budget, hours)
                           |                 |
                set weights| (xDS)           | analyse every minute
                           v                 v
 Traffic layer (Envoy mesh)          Canary analysis svc --> Prometheus
   stable v1 : baseline v1 : canary v2 = 98 : 1 : 1  -> 5 -> 25 -> ...
      |              |            |
      v              v            v
 stable v1 (N)  baseline v1 (k)  canary v2 (k)    Feature flag service
 Migrations: expand -> deploy -> contract     Deploy log -> dashboards
```

- **Artifact registry:** immutable images by digest; signature checked at deploy.
- **Rollout controller:** per-service state machine; reconciles weights, schedules analysis, acts.
- **Traffic layer:** Envoy mesh weighted subsets; sticky hashing; weight changes in seconds.
- **Canary analysis service:** compares canary vs baseline metrics, returns a score 0-100.
- **Policy engine:** freezes, error budget, hours, approvals, checked before every step.
- **Metrics store:** Prometheus with version and subset labels on every metric.
- **Feature flag service:** percentage rollouts and kill switches, evaluated in-process.
- **Migration orchestrator:** schema changes as separate expand and contract releases.
- **Deploy event log:** audit trail and annotations for dashboards and incidents.

**Flow A: happy-path tier-0 rollout**
1. Image sha256:ab12 merges; policy passes (no freeze, 70% error budget left, approval present).
2. Lowest-traffic region: 2 canary and 2 baseline pods; weights 98/1/1.
3. Bake 10 minutes, analysis every minute; score 94 (pass at 85) -> 5%, 25%, 50%, 100%.
4. Old ReplicaSet kept at 0 for 24 hours; bake 30 minutes, then the next regions.

**Flow B: automatic abort**
1. At 5%, canary p99 is 650 ms vs 280 ms and errors 1.4% vs 0.1%.
2. Error rate is critical, so the score is 0: FAIL.
3. Canary weight to 0 via xDS in 5-10 s, canary scaled to 0, release FAILED, author gets the report.

## Page 3. The core deep dives

### 1. The canary judge
Compare against a fresh baseline: old-version pods started at the same time with the same pod count. The long-running fleet has warm caches and JIT, so a new canary would always look worse against it. For each metric, collect per-minute samples for both arms, drop outliers and run Mann-Whitney U, a test that compares distributions without assuming a normal shape, which fits heavy-tailed latency. A metric fails only if the difference is significant (p under 0.01) AND larger than a practical effect size in the bad direction. Score is the weighted share of passing metrics: 85 or more passes, 60-85 extends the bake once, under 60 fails. Critical metrics (error rate, payment success) fail the run on their own. No data means pause, never promote.

### 2. Step sizing, blast radius and bake time
Steps of 1, 5, 25, 50, 100% in the smallest region first, then a 30-minute bake before each next region. Sizes come from the sample-size math: a 1% canary of a 5k RPS service catches a 10x error jump in minutes but needs about 8 minutes for a 2x jump. A 5 RPS internal service gets 3 requests a minute at 1%, so it uses a 25-50% first step, longer bakes, synthetic traffic and fast rollback. Bake time also catches slow failures; a 6-hour memory leak is caught by 24 hours of post-promotion SLO-burn monitoring.

### 3. Rollback that actually works
During a rollout, rollback is a weight flip because stable pods never stopped. It only works if N and N-1 coexist. Schema changes use expand-contract: release A adds a nullable column and writes both, a backfill fills it, release B reads the new column with fallback, and weeks later release C stops writing the old column. Queues use tolerant readers deployed before writers change format. Sticky routing hashes the user id into 10,000 buckets, so Shreya stays on one version and raising the weight only adds buckets.

### 4. A controller that fails safe
Desired state lives in Postgres; the controller holds a lease, applies idempotently and resyncs every 30 s. If it crashes after setting 25% but before recording it, the new leader reads the real weights from the mesh and converges. Version checks make a manual abort win over a concurrent promote.

**Data model:**
- **release** (Postgres): PK release_id; state, step, weights, lease_owner, version; one active release per service via a partial unique index.
- **strategy** (Git YAML): regions order, steps (weight, bake, template), stickiness, approvals.
- **analysis_template** (Git YAML): metrics with query, direction, critical, weight, effect size; pass 85, marginal 60.
- **analysis_run**: PK run_id, index (release_id, step); kept 1 year to tune false aborts.
- **deploy_event** (Kafka): partitioned by service; feeds annotations and incidents.

**Key APIs:**
- `POST /v1/releases`: idempotent on (service, image_digest); emergency needs an approver.
- `POST /v1/releases/{id}/actions`: pause, resume, promote, abort; overriding a failed canary needs two approvers.
- `POST /v1/services/{svc}/rollback`: to last known good; weight flip if old pods exist.
- `POST /v1/analysis`: pure function of metrics and template, re-runnable.
- `PUT /v1/freeze`: global, org or service scope; checked at every step.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Statistical power:** the real limit; low-traffic services get bigger steps, longer bakes, pooled windows or synthetic traffic.
- **Capacity headroom:** only about 10% spare; canary scales up as stable scales down, keeping the total near +5%.
- **Shared dependencies:** a canary sending 10x DB queries harms everyone; add per-caller dependency metrics and per-pod connection limits.
- **Coupled rollouts:** contract tests and a concurrency limit per tier-0 dependency chain.
- **Long-lived connections:** max connection age 5 minutes and GOAWAY so streams rebalance.

**Failure modes:**
- **Metrics store down or lagging:** NODATA verdict, rollout pauses at current weights, platform alert.
- **Controller crash:** traffic keeps its weights; a new leader takes the lease in about 15 s and reconciles.
- **Mesh control plane down:** proxies keep last config; abort falls back to scaling canary pods to 0.
- **Bad build passes canary:** post-promotion SLO-burn alerts, one-click rollback, add the missing metric.
- **Canary corrupts shared data:** abort stops further writes; repair from audit log or backups; prevent with validation, dark writes and flags.
- **False abort:** report shown, re-run or retry; track the rate and tune thresholds.
- **Unrelated regional incident:** shared noise cancels in canary vs baseline; declared incidents pause all rollouts there.

**Trade-offs chosen:**
- **Canary with analysis over blue-green or plain rolling:** smaller blast radius and overhead; blue-green only where versions cannot coexist.
- **Fresh baseline plus absolute SLO guardrails over fixed thresholds or the fleet:** removes warm-up bias; guardrails catch failures hitting both arms.
- **Gradual steps for tier-0, compressed for low risk:** blast radius versus lead time.
- **Weight flip during rollout, fast redeploy after:** seconds versus the cost of warm old pods forever.
- **Sticky by user for user-facing, per-request for internal:** consistent experience versus statistical independence.
- **Fully automated with auto-abort over human approval per step:** humans read graphs slowly and inconsistently.

**What to measure:** change failure rate, bad builds caught per step, time to abort and abort to weight 0, false-abort and marginal rates, deploy frequency and lead time by tier, canary vs baseline errors, latency and business metrics, policy pauses, NODATA verdicts, time to restore.

## Page 5. Say it in the interview

> "Since most incidents are triggered by changes, I will design deployment as a safety net. Assume about 400 Kubernetes services, 150 deploys a day, and tier-0 services like checkout at 5k RPS. Every release is an immutable image. A rollout controller shifts traffic in steps of 1, 5, 25, 50 and 100 percent in the first region, then the others after a bake. At each step an analysis service compares the canary against a freshly started baseline of the old version, not the long-running fleet, with a nonparametric test on errors, latency and business metrics. Pass promotes; fail flips the canary weight to zero in seconds because stable pods never stopped. A policy engine blocks rollouts during freezes or when the error budget is spent. Rollback only works if changes are backward compatible, so schemas use expand-and-contract and risky features hide behind flags."

**Key points to land:**
- Most outages are change-induced, so the pipeline is a reliability system.
- Canary small, compare to a fresh baseline, decide statistically, expand by step and region.
- Mann-Whitney plus effect-size thresholds; critical metrics fail alone.
- Rollback is a weight flip in seconds because stable pods stay warm.
- Size steps and bakes from sample-size math; low traffic needs bigger or longer steps.
- Never all regions at once; bake between regions.
- N and N-1 must coexist: expand-contract and tolerant readers.
- Flags decouple deploy from release and give second-level kill switches.
- Fail safe: missing data pauses, controller outage freezes weights, incidents pause rollouts.

**Likely follow-ups:**
1. **Low-traffic internal service?** Tests have little power, so use bigger steps, longer bakes, synthetic or replayed traffic, and fast rollback on SLO alerts.
2. **Canary a database or cache?** By node: one replica serving reads, then one shard primary, with cross-version replication; never a majority quorum at once.
3. **Passes at 5%, breaks at 100%?** Load-dependent bugs (locks, connection limits): watch saturation, bake at 50%, auto-rollback on SLO burn for 24 hours.
4. **Roll back a mobile app?** You cannot; use server-side flags and kill switches, staged store rollouts (1, 5, 20%) and a server compatible with old versions.
5. **Stop teams turning analysis off?** Keep it fast and accurate, explain failures, track false aborts, and make bypass need two approvals with audit.

**Director layer:**
- **Business case:** DORA metrics: change failure rate from about 15% to under 5%, deploys from 150 to 300 a day, revenue protected in sales.
- **Cost drivers:** under 10% extra pods during rollouts; metrics queries are trivial.
- **Phasing:** adopt Argo Rollouts or Flagger with Kayenta-style analysis on tier-0 first, then all services with tier templates, then flags and config.
- **Ownership:** platform owns controller, policy and templates; service teams own their metric configs; SRE owns freezes.
- **Top risks:** false confidence from small canaries, false aborts driving bypass, irreversible migrations, a controller bug rolling out everywhere.
