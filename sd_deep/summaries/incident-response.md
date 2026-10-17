# Design an incident response workflow with runbooks: the 5-page summary

This is half system, half people process: detect, declare, mobilise the right people, mitigate fast, communicate and learn. The single most important idea: the bottleneck is human coordination, not QPS, so the platform must be more available than anything it manages and make runbook actions safe to run under stress.

## Page 1. The problem, scope and numbers

**Pitch:** turn ad hoc firefighting (asking around in chat, parallel uncoordinated fixes, stale wiki runbooks, about 2 hours to mitigate a SEV1) into a fast, safe, repeatable workflow that also learns from every incident.

**Who uses it:** on-call engineers, incident commanders, support and business teams, leadership and compliance (audit trail).

**In scope:**
- **Ingest and correlate:** alerts, probes, support and manual declaration, grouped into incidents.
- **Severity and paging:** rule-based severity with override; escalation by push, SMS, voice.
- **Mobilisation:** auto war room, bridge and record; IC, ops, comms and scribe roles.
- **Runbooks:** versioned, linked from every alert, actions run by a guarded executor.
- **Timeline and comms:** append-only timeline; templated updates and status page.
- **Postmortems:** prefilled drafts, action items synced to Jira.

**Out of scope:** replacing monitoring, autonomous high-risk remediation, security forensics, IT helpdesk, ML root cause.

**Non-functional targets:**
- **Availability:** 99.99% for paging and incident creation, independent of production regions.
- **Latency:** event to first notification p99 under 30 s; incident page under 1.5 s on mobile.
- **Throughput:** 10k events/minute sustained during alert storms, no loss.
- **Durability:** no loss of acknowledged events (RPO 0 in region, under 5 s cross-region); records kept 3 years.
- **Safety:** 100% of production actions audited; destructive actions need a second approver.
- **Business goals:** SEV1 mitigation under 45 minutes, ack under 5 minutes, IC within 10 minutes, repeat incidents down 50%.

**Capacity math (300 services, 80 teams, 120 rotations, about 1,500 engineers):**
- **Ingest:** normally 5,000 events/day (0.06/s); storms 10k/minute is about 170 events/s; x 2 KB = 340 KB/s. Easy for Kafka, so the real job is collapsing the storm: dedup and correlation turn 10k events into 1-5 incidents, a 1,000x cut in human-facing items.
- **Timeline:** 40 incidents/week x about 200 events x 1 KB = 8 MB/week; with chat transcripts about 50 MB/week, 2.6 GB/year. So a single replicated Postgres is enough.
- **On-call load:** 40 incidents/week over 120 rotations is 0.33 per rotation, but tier-0 rotations see 3-5. So budget 2 pages per shift and act when exceeded.

## Page 2. The architecture

```
 Alertmanager, probes, support, manual declare
      | events (dedup_key)
      v
 Ingest API (idempotent) -> Event log (Kafka, partition by service)
                                 |
                                 v
 Service catalog <--lookup-- Incident engine (correlate, severity,
 (owners, deps, tier)        state machine) -> Postgres + Timeline
            +--------------------+         |              ^
            v                              v              | every event
 Scheduler + escalation          Runbook svc (Git) -> Action executor
 (durable timers)                     (RBAC, approval, lock, verify)
            |                              |
            v                              v
 Notifier (2 vendors: push/SMS/voice)  Comms svc: war room, bridge,
                                       status page; Postmortem -> Jira
```

- **Ingest API:** validates events, dedups by dedup_key, writes to Kafka and returns fast.
- **Event log (Kafka):** absorbs bursts, keeps per-service order, replayable for recovery.
- **Incident engine:** correlates events into incidents, applies severity rules, runs the state machine.
- **Service catalog:** owners, tier, dependencies, runbook links, rotation mapping.
- **Scheduler and escalation:** who is on call now; escalation chains on durable timers.
- **Notifier:** push, SMS, voice and chat through two vendors with delivery receipts.
- **Runbook service:** runbooks as versioned code in Git; tracks step progress per incident.
- **Action executor:** rollback, failover, scale, flag toggle with RBAC, approvals, rate limits, verification, audit.
- **Comms service:** war room, templates, cadence reminders, status page.
- **Timeline store:** append-only record of every event, message, decision and action.

**Flow A: alert to mobilised SEV1**
1. Checkout burn-rate alert fires (dedup_key checkout-availability); ingest writes it.
2. No open incident for checkout or its dependencies in 10 minutes, so engine opens one at tentative SEV2.
3. Scheduler finds primary on-call; notifier pushes and calls; 5-minute escalation timer set.
4. Ravi acks in 2 minutes, sees the 13:58 deploy, upgrades to SEV1 (orders down 40%).
5. SEV1 auto-creates war room, bridge, IC and comms pages, status page draft.

**Flow B: runbook-driven mitigation**
1. Runbook step 1 diffs error rates by version: new 9%, old 0.1%.
2. Ravi requests rollback; tier-0 production change, so the IC approves.
3. Executor checks preconditions, rolls back, verifies errors under 0.5% within 5 minutes.
4. Timeline records request, approval, run, verification; state moves to mitigated.

## Page 3. The core deep dives

### 1. Taming alert storms: dedup plus topology-aware correlation
Monitoring delivers events at least once, so ingest is idempotent on (source, dedup_key, status, time bucket). Exact dedup stops repeats. Correlation then groups different alerts with a likely shared cause: same service, or a dependency or dependent within 2 hops in the service catalog, within a 10-minute window. Example: a core database failover fires 2,000 alerts across 60 services in 3 minutes. Kafka absorbs it, dependents attach to the database incident, and only the DB owner and IC are paged; others get an FYI. Over-merging is fixed by IC split and merge commands.

### 2. Escalation that never silently drops
Escalation is a time-based promise: no ack in 5 minutes, page the next person. In-memory sleeps die on a deploy. So each policy step is a timer row with fire_at; a leader-elected ticker scans due timers every 10 s (or instances claim rows with SELECT ... FOR UPDATE SKIP LOCKED). An ack cancels pending steps. Primary to secondary after 5 minutes, then the engineering manager after 5 more, with a voice call on the second attempt. Prefer a duplicate page over a missed escalation.

### 3. Safe runbook actions
Runbooks live in Git with an owner and last-reviewed date; CI validates action names against the executor registry and alerts on staleness after 180 days. Each action declares params, risk (low or high), preconditions and a verify query. The executor: idempotent on run_id; checks policy (tier, change freeze, kill switch); needs a second approver for high-risk actions (approval expires in 10 minutes); takes a per-service lock (15-minute TTL) so a rollback and a scale-out never collide; rate limits (1 rollback per service per 10 minutes, 3 concurrent failovers globally); runs; then verifies the metric within 5 minutes.

### 4. Roles and the timeline as single source of truth
Incident Command System roles: the IC coordinates and never touches production, the ops lead alone changes production, the comms lead shields responders. Every chat command, UI action and executor result comes back as an event on an append-only timeline with a server-assigned seq, so ordering is exact despite clock skew, and it prefills the postmortem.

**Data model:**
- **incident** (Postgres): PK id; index (service_id, state); unique open incident per correlation_key; version for optimistic locking; timestamps for MTTx.
- **timeline_event** (append-only, partitioned by month): PK (incident_id, seq); unique (incident_id, client_event_id); never updated.
- **runbook** (Git): id + commit sha; steps, actions with risk and verify.
- **action_run**: PK run_id; pending_approval -> running -> verifying -> succeeded, failed or rolled_back.
- **escalation timers and schedules**: rotation_id, policy steps; synced to the pager vendor as backup.

**Key APIs:**
- `POST /v1/events`: idempotent ingest; resolve events never auto-close SEV1/SEV2.
- `POST /v1/incidents`: anyone can declare; Idempotency-Key stops double clicks.
- `PATCH /v1/incidents/{id}`: version check; transitions validated by the state machine.
- `POST /v1/runbooks/{rb}/actions/{action}/runs`: run_id is the executor idempotency key.
- `POST /v1/action-runs/{run_id}/approve`: approver must differ from requester.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Ingest storms:** Kafka partitioned by service absorbs bursts; scale engine consumers; dedup before anything pages.
- **Human load:** the real limit. Correlation keeps one incident per cause; one IC with workstream leads, not five parallel incidents.
- **On-call fairness:** tier-0 teams get dedicated 24x7 rotations of 6+; lower tiers share; central SRE IC rotation for SEV1.
- **Long incidents:** rotate IC and ops roles every 4 hours past 12 hours; pin a running summary.

**Failure modes:**
- **Platform region outage:** active-active; Postgres promotes the cross-region replica (RPO under 5 s); paging continues via the vendor.
- **Pager vendor down:** route through the second vendor and an SMS gateway.
- **Chat down:** incident UI has its own timeline and notes; phone bridge; bot buffers and replays.
- **Executor bug (repeated rollbacks):** locks and rate limits cap damage; abnormal action rate trips the global kill switch; fall back to manual.
- **Kafka lag in a storm:** ingest still acks after the Kafka write; the vendor's direct alert integration is a parallel paging path for tier-0.
- **SSO down:** break-glass accounts with hardware keys, alerted and reviewed.
- **Out-of-order resolve:** per-dedup_key state by event time; an early resolve suppresses an older late trigger.

**Trade-offs chosen:**
- **Buy paging, build the workflow:** paging is a commodity and gives failure-domain independence; runbooks and catalog are company-specific.
- **Human approval for high-risk over full automation:** approval adds about a minute but prevents compounding outages; auto only for low-risk reversible actions.
- **Dedup plus topology window over per-alert incidents:** collapses storms to the root.
- **Runbooks as code over wiki pages:** review, versioning, CI validation.
- **4 severity levels (SEV0-SEV3):** enough distinction without borderline arguments.
- **Own event store over chat as record:** chat is lossy and can be down.

**What to measure:** MTTD, MTTA, time to IC, MTTM, MTTR by severity; pages per shift and night pages; escalation rate; runbook coverage and action verification failures; postmortems within 5 days; action items on time; repeat incidents in 90 days; platform health (ingest latency, notification p99).

## Page 5. Say it in the interview

> "I treat this as a process and a system. Assume 300 services and 5,000 alerts a day collapsing into about 40 incidents a week, with a 5-minute ack and SEV1 mitigated in under 45 minutes. The workflow is detect, triage, declare, mobilise, mitigate, resolve, learn. Signals hit an idempotent ingest API with dedup keys; an incident engine correlates them using the service catalog, resolves on-call with durable escalation timers, and opens a war room with an incident commander, ops lead and comms lead. Runbooks are code, and actions like rollback run through an audited executor with approvals, locks and verification. Everything lands on an append-only timeline that seeds a blameless postmortem. Throughput is tiny; the hard parts are coordination and being up when everything else is down."

**Key points to land:**
- The workflow: detect, triage, declare, mobilise, mitigate, resolve, learn.
- Mitigate first, root-cause later; rollback is the default first move for change-induced incidents.
- ICS roles: IC coordinates, ops changes production, comms shields responders.
- Severity by impact; declare early and high.
- Idempotent ingest plus topology-aware correlation tames storms (10k events to 1-5 incidents).
- Durable escalation timers; a duplicate page beats a missed one.
- Runbooks as code; actions guarded, audited, idempotent, with a kill switch.
- More available than what it manages: separate failure domain, external pager, offline fallbacks.
- Blameless postmortems with tracked actions; measure repeat incidents.
- Measure MTTA, time to IC, MTTM and on-call load, not just counts.

**Likely follow-ups:**
1. **An incident spanning five teams?** One IC, one incident, workstreams each with a lead reporting to the IC; one war room plus sub-channels; comms lead aggregates.
2. **What would you automate first?** Rollback of the last deploy, gated by canary metrics, since many incidents are change-induced; prove it with dry runs, game days and a quarter in approval mode.
3. **How do you know it works?** Trend MTTA, time to IC, MTTM, repeat rate, action closure and on-call surveys; sample incidents monthly for role and cadence compliance.
4. **Where do LLMs fit?** Summarise timelines for late joiners, draft updates and postmortems, suggest runbooks; humans approve, the model never executes changes.
5. **Security incidents?** Same platform in restricted mode, a security IC rotation, legal roles, evidence steps and regulatory notification timers.

**Director layer:**
- **Cost drivers:** pager vendor seats (two vendors), a second active region, and mostly people time: on-call load and postmortem effort.
- **Phasing:** buy paging and wire alerts first; then war room automation, runbooks as code, executor in approval mode; auto mode only after tracked verification success.
- **Ownership:** central SRE owns the platform and IC rotation; service teams own runbooks, rotations and action items.
- **Top risks:** automation worsening an outage, process seen as bureaucracy, blame culture, the tool sharing fate with production, on-call burnout.
