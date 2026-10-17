# Design an enforceable data retention and deletion policy: the 5-page summary

Writing a retention policy is easy; making it true across hundreds of databases, caches, search indexes, Kafka topics, lake tables, ML features and backups is the hard part. The single most important idea: separate policy (Legal decides the periods) from enforcement (an engineering system that finds every copy, deletes it through idempotent workflows, crypto-shreds what it cannot edit, and proves the result).

## Page 1. The problem, scope and numbers

**Pitch:** turn retention rules into code attached to a data catalog, expire data automatically, complete user erasure requests across every store within 30 days, and show a regulator the evidence.

**Who uses it:** the Legal and Privacy office (enforced policies, evidence, legal holds), data and service owners (a clear delete contract and SLA), the data platform (lake deletes without daily full rewrites), Security (less data at rest), customers and sellers (a simple request and a confirmation).

**In scope:** a versioned policy registry with dry-run simulation; a data catalog with classes, subject-id columns, owners and lineage, enforced by CI and scanners; a bulk expiry engine (TTLs, partition drops, lifecycle rules); an erasure workflow fanning out to store agents; a per-subject key service for crypto-shredding; a denylist on ingest, restore and replay; verification with canaries, residual scans and evidence export.

**Out of scope:** choosing the legal periods, the consent UI, physical media destruction, re-identification research beyond standard anonymisation.

**Non-functional targets:**
- **Erasure SLA:** 99.5% within 30 days end to end; tier-1 online stores within 72 h.
- **Correctness:** zero residual personal data in covered stores, verified by scans.
- **Safety:** never delete data under legal hold or below a statutory minimum; dry-run every policy change.
- **Evidence:** an append-only deletion ledger kept 7 years, without the deleted personal data.
- **Production impact:** delete jobs add under 5% load, throttled per store.
- **Availability:** intake 99.9%; workflows survive restarts with no lost requests.

**Capacity math (2M erasure requests/year, 40 stores per subject, 5 PB lake):**
- **Erasure tasks:** 2M / 365 = 5,500 requests/day x 40 = 220k store tasks/day; a 50k/day burst means 2M tasks. So batch per store into jobs of about 1,000 ids: at most about 2,000 jobs per store per day.
- **Clickstream expiry:** 30 TB/day x 180 days = 5.4 PB steady state. Dropping one day-partition reclaims 30 TB as a metadata operation. So bulk expiry must be partition drops, never row deletes.
- **Lake row deletes:** if a subject touches 1 in 1,000 files, 5,500 subjects a day touch a large fraction of partitions. So use merge-on-read delete files plus weekly compaction.
- **Key service:** 300M users x 100 B wrapped key = 30 GB; 5,500 key destructions a day. Small enough for a replicated KV.
- **Backups:** 35-day backups plus a 30-day SLA means a copy can live 65 days. So state that window or crypto-shred so backup copies are unreadable at once.
- **Ledger:** 220k records/day x 300 B = 66 MB/day, about 170 GB over 7 years.

## Page 2. The architecture

```
 Legal / Privacy / data owners -> policy-as-code PRs (reviewed, versioned)
      |
      v
 Policy registry <-> Data catalog + lineage <- PII scanners, CI gate
      |                     |
      v                     v
 Orchestrator (Temporal workflows) <- triggers: erasure, account closure,
      |                                 TTL schedules; legal hold check
      | fan-out tasks, batched per store
      v
 Store agents: OLTP | Redis | Search | Kafka | Iceberg | SaaS APIs
      |                                   Key service: per-subject keys,
      |                                   crypto-shred backups and logs
      v                                         |
 Deletion ledger (append-only) <----------------+
      +-> Verifier: canaries, residual scans, coverage, auditor evidence
```

- **Policy registry:** versioned rules per data class: min and max retention, method, legal basis.
- **Data catalog and lineage:** every dataset and column with class, subject key, owner, copies.
- **Scanners and CI gate:** block unclassified PII columns; find undeclared buckets and tables.
- **Legal hold service:** holds by subject, dataset or case, checked before any deletion.
- **Bulk expiry engine:** sets native TTLs, partition drops, lifecycle rules; reconciles daily.
- **Erasure orchestrator:** one durable, resumable Temporal workflow per request.
- **Store agents:** idempotent delete(subject_ids, task_id) per technology, throttled.
- **Key service:** per-subject data keys wrapped by KMS; destroying one shreds all copies.
- **Denylist and ledger:** hashed erased ids block resurrection; ledger holds the evidence.

**Flow A: subject erasure**
1. Shreya asks to delete her account; identity is verified; the request stores a hashed id.
2. The account is soft-disabled at once; a 14-day cancellable grace period starts.
3. Check holds and statutory minimums; record exemptions with reason and review date.
4. The catalog plans tasks for every dataset holding her id, via lineage, grouped by store.
5. Agents delete or anonymise; her key is destroyed; her hash joins the denylist.
6. Residual scans find zero hits; the ledger records completion; she gets confirmation.

**Flow B: time-based expiry**
1. Policy: clickstream max 180 days; the catalog lists 14 such datasets.
2. The engine sets Iceberg partition drops, Kafka retention.ms, search index lifecycle.
3. A daily reconciler compares oldest record age with policy; drift tickets the owner.

## Page 3. The core deep dives

### 1. Find every copy: catalog, classification, lineage
You cannot delete what you cannot find. Each dataset has a catalog entry with a data class per column, the column holding the subject id, owner, store, tier and agent. Lineage edges reach derived copies: ETL outputs, ML training sets, search indexes. CI fails a migration that adds a phone or email column without a class. Daily scanners hunt for undeclared copies, such as an analyst's CSV export in S3, which is quarantined until classified. An identity graph links user id, phone, device ids and guest-checkout email at plan time.

### 2. Policy as code with deterministic precedence
Decisions must be repeatable and explainable, field by field. A legal hold blocks everything in its scope. A statutory minimum blocks only the fields it covers: invoices kept 8 years keep amount, tax ids and date, while phone and browsing history are deleted. Otherwise an erasure request or max retention triggers deletion by the class method: hard delete in OLTP and search, anonymise in analytics, crypto-shred for backups and logs. Every decision records its inputs and policy version.

### 3. The erasure saga
Each request is a Temporal workflow: disable, wait out the grace period, check holds, plan, fan out, shred, verify, close. Task ids are hash(request_id, dataset_id), so re-planning is idempotent; a retry after a timeout deletes only the remaining rows. Tasks retry with backoff up to 6-hour intervals; after 8 failures the owner is paged with the SLA clock running. The workflow closes only when every task is done or exempt.

### 4. What you cannot edit: crypto-shredding and real byte removal
PII in logs, long Kafka topics, archives and backups is encrypted with the subject's data key; deleting the key makes every copy unreadable, and key-store backups expire within 7 days. Bytes are not gone until storage catches up: Cassandra tombstones need compaction and repair, and Iceberg delete files need compaction plus snapshot expiry (7 days), or time travel still reads the rows.

**Data model:**
- **Policy:** PK (data_class, version), immutable versions.
- **DatasetCatalogEntry:** PK dataset_id; indexes on data_class and subject key columns.
- **ErasureRequest:** PK request_id; unique open request per subject_hash.
- **DeletionTask:** PK hash(request_id, dataset_id); index (dataset_id, status).
- **SubjectKey and denylist:** PK subject_hash; denylist as Postgres plus Redis, with a Bloom filter at ingest.

**Key APIs:**
- `POST /v1/erasure-requests`: 202 with status GRACE and expected completion date.
- `POST /v1/legal-holds`: Legal role only; creating and lifting a hold is audited.
- `PUT /v1/policies/{data_class}`: returns a version and a dry-run report.
- `POST /agent/v1/delete`: idempotent on task_id; returns rows and a completion token.
- `GET /v1/coverage`: per dataset, policy, enforced flag, oldest record age, drift.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Fan-out:** batch per store into 1,000-id jobs with bounded concurrency and per-store throttles under 5% load.
- **Bulk expiry:** day-partitioned tables so expiry is partition drops; lifecycle rules for objects.
- **Lake deletes:** daily batched DELETEs into delete files, weekly compaction, orphan file removal.
- **SaaS processors:** rate-limited deletion API agents; human tasks with evidence where no API exists.
- **Adoption across hundreds of teams:** tier-1 first with platform agents, CI gates, launch-review canaries, team scorecards.

**Failure modes:**
- **Store agent keeps failing:** backoff up to 6 h, page the owner after 8 failures; the SLA dashboard shows breach risk.
- **Catalog down at planning:** wait and retry; never run a partial plan, which would claim a false completion.
- **Key service outage:** shredding waits; reads fall back to cached keys that expire in 5 minutes; multi-AZ makes it rare.
- **Policy bug triggers mass deletion:** a per-dataset breaker trips at 3x expected volume; partitions are soft-dropped to quarantine for 7 days.
- **Restore without the denylist:** tooling refuses to promote the database until the denylist job runs; shredded PII is unreadable anyway.
- **Kafka replay brings an erased user back:** consumers drop matches via the Bloom filter; compacted topics get a tombstone.
- **Residual scan hit after close:** a privacy incident: reopen, delete, fix the lineage or agent gap, add a regression canary.

**Trade-offs chosen:**
- **Method per class over one method everywhere:** each store has a different cheapest correct mechanism.
- **Orchestration over choreography:** pure events cannot say when deletion is complete or produce evidence.
- **Soft-disable now, batched physical delete:** invisible at once, cheap in lake and LSM stores.
- **14-day grace over instant deletion:** protects against account takeover and regret; the 30-day clock includes it, leaving 16 days.
- **Platform agents plus owner hooks, one contract:** the platform covers 80% cheaply; owners know their invariants.

**What to measure:** catalog coverage by tier, erasure completion within 30 days and p95 time, overdue tasks by team, residual-scan hits and daily canary pass rate, oldest record age vs policy and bytes beyond max retention, expiry bytes removed and config drift, overdue hold reviews, denylist hits on ingest, restore and replay, delete load and breaker trips.

## Page 5. Say it in the interview

> "I want to separate the policy, which is a legal decision, from enforcement, which is an engineering system. The policy says, per class of data, how long we must keep it, how long we may keep it and how to get rid of it. Enforcement has four parts. First, know where data lives: a catalog that classifies every column, CI checks so no table appears unclassified, and lineage to every copy. Second, execute: bulk expiry through TTLs and dropping time partitions, and individual erasure requests as durable workflows that fan out idempotent delete tasks to every store. Third, crypto-shred what you cannot edit: backups, immutable logs, archives. Fourth, prove it with canary users, residual scans and an append-only deletion ledger. Then I will defend legal holds, resurrection from backups and a 30-day SLA across 40 systems."

**Key points to land:**
- Legal decides periods; engineering makes them true and provable.
- You cannot delete what you cannot find: catalog, classification, lineage, CI gates.
- Precedence: legal hold, then statutory minimum, then erasure or max retention.
- Two paths: bulk expiry by TTL and partition drops; erasure by idempotent sagas.
- Crypto-shred backups, immutable logs, archives and long Kafka topics.
- Bytes are gone only after compaction, snapshot expiry and backup rotation.
- A hashed denylist on ingest, restore and replay prevents resurrection.
- Prove it: ledger, residual scans, canaries, oldest record age per dataset.
- Safety rails: dry-run, delete-volume breakers, quarantine before hard drop.

**Likely follow-ups:**
1. **Third-party SaaS like the CRM?** Register it in the catalog with an agent calling its deletion API within rate limits; human tasks with evidence otherwise; contracts require deletion within the SLA.
2. **Logs with user ids and IPs?** Minimise first; application logs keep about 30 days so they expire inside the SLA; long-retention security logs encrypt PII with per-subject keys.
3. **Is pseudonymisation enough?** No: it can be re-linked via the mapping, so it is still personal data; erasure needs deletion, key destruction or true anonymisation.
4. **ML models trained on deleted users?** Lineage marks training sets; rows are removed and the next retrain excludes them; per-user embeddings are deleted directly from the feature store.
5. **How do you prove expiry is enforced, not just configured?** Oldest record age per dataset vs policy, reconciler drift reports, expiry runs in the ledger with bytes removed, plus sampled queries during the audit.

**Director layer:**
- **Cost drivers:** platform agents and orchestration, lake compaction compute, and the scanners; offset by reclaiming expired data, expected to cut hot storage 20-30%.
- **Phasing:** tier-1 stores first with standard agents and CI gates, then coverage burn-down to 95% of datasets in 2 quarters; no big-bang migration.
- **Team ownership:** Legal owns the values, the privacy platform owns registry, catalog, orchestrator and verifier, and data owners own their agents and SLA.
- **Top risks:** unknown copies missed, accidental mass deletion from a policy bug, resurrection by restores or replays, and teams never implementing delete hooks.
