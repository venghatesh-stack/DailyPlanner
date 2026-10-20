# Incident response workflow with runbooks: recall card

> **Hook:** Idempotent ingest → Correlate storm into one incident → Page with durable timers → War room with IC → Guarded runbook action → Timeline to postmortem

**P · Problem:** It's really a human coordination problem wrapped in a system that must be up when everything else is down.

**N · Numbers:**
1. An alert storm of 10k events/minute is only about 170 events/s, so Kafka absorbs it and the real job is collapsing it into 1-5 incidents.
2. Timelines grow about 2.6 GB/year, so a single replicated Postgres is enough.
3. 40 incidents/week over 120 rotations, but tier-0 rotations see 3-5, so budget 2 pages per shift and act when exceeded.

**H · Hard part:** Turning thousands of alerts into one incident with the right people, and letting stressed humans run production actions safely.

**B · Boxes:** `Alerts → Ingest API → Kafka → Incident engine → Escalation scheduler → Notifier`

Side path: `Runbook (Git) → Action executor (approval, lock, verify) → Timeline`.

**D · Decisions:**
1. Buy paging over building it, because paging is a commodity and lives in an independent failure domain.
2. Human approval for high-risk actions over full automation, because a minute of approval prevents compounding outages.
3. Runbooks as code over wiki pages, because they get review, versioning and CI validation.

**F · Failures:**
1. Pager vendor down → route through the second vendor and an SMS gateway.
2. Executor bug repeats rollbacks → locks and rate limits cap damage; the global kill switch trips; fall back to manual.

**C · Close:** "I treat this as a process and a system: detect, triage, declare, mobilise, mitigate, resolve, learn. Signals hit an idempotent ingest API, an engine correlates them using the service catalog, durable timers escalate pages, and a war room opens with an incident commander. Runbooks are code, and actions run through an audited executor with approvals, locks and verification. Everything lands on an append-only timeline that seeds a blameless postmortem."

**Quiz yourself:**
1. How do 2,000 alerts become one incident? → Dedup keys plus correlation within 2 hops in the catalog over 10 minutes.
2. Why durable escalation timers? → In-memory sleeps die on a deploy; a duplicate page beats a missed one.
3. What does the IC never do? → Touch production; the ops lead alone changes it.
