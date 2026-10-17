# Design multi-region failover and disaster recovery: the 5-page summary

Multi-region disaster recovery (DR) is a negotiation between RPO (how much data you may lose), RTO (how long you may be down), cost and consistency. The single most important idea: pick a replication strategy per data tier (quorum for the payment ledger, async for orders, backups for logical disasters), keep each region statically stable with pre-provisioned capacity, and treat failover as a rehearsed runbook with fencing so two regions never write the same data.

## Page 1. The problem, scope and numbers

**Pitch:** survive the loss of a whole cloud region with at most 5 minutes of downtime and 1 second of order data loss, zero payment loss, for under 60% extra infrastructure cost.

**Why now:** one region with three availability zones (AZs); a region-wide event would stop ordering for hours, a large GMV loss on sale days, and regulators expect a tested continuity plan.

**Who cares:** customers (no lost or duplicate orders), leadership (drill evidence), payments and regulators (RPO 0 ledger), SRE (runbooks), security (isolated backups).

**In scope:**
- **DR tier registry:** RPO, RTO, strategy and owner per service and datastore.
- **Traffic management:** anycast edge and GeoDNS with health checks, weighted shift and drain.
- **Home region per user**, in a directory replicated to every region.
- **Replication per store**, a **failover controller**, failback, backups with point-in-time recovery (PITR), drills.

**Out of scope:** multi-cloud, office IT DR, third-party SaaS outages, regions outside India.

**Non-functional targets:**
- **RTO (tier-1):** at most 5 min for writes, 1 min for reads; detect a bad region in under 60 s.
- **RPO:** 0 for the ledger, at most 1 s for orders, 5 min for catalog.
- **Write latency:** orders p99 under 50 ms (local); ledger p99 under 120 ms (cross-region quorum).
- **Headroom:** each region can carry 100% of tier-1 traffic, with tier-3 shed.
- **Backups:** PITR within 7 days; 35-day snapshots. **Residency:** all PII in India.

**Capacity math (200k read and 20k write RPS peak, 1 KB writes, Mumbai-Hyderabad RTT about 15 ms):**
- **Replication bandwidth:** 20k x 1 KB x 3 (indexes, logs) = 480 Mbps, plus 5 TB/day of objects = 460 Mbps: about 1 Gbps, so provision 2 x 10 Gbps links.
- **Async loss window:** 10k writes/s per region x 1 s lag = up to 10k order writes lost. So reconciliation from the ledger is a must-have.
- **Ledger latency:** quorum needs another region: p99 60-120 ms versus 10 ms local. So only the ledger pays it.
- **Survivor capacity:** at 60% utilisation each, the survivor would need 120%; shedding tier-3 (about 20% of load) makes it fit.
- **Cost:** two regions at 50% versus one region capped at about 67% for AZ headroom is about 1.35x compute, inside the 60% budget.
- **DNS failover:** 10 s checks x 3 = 30 s, plus 60 s TTL and resolver caching = 1-3 min. So an anycast edge is primary.

## Page 2. The architecture

```
                 Users (mobile / web)
                         |
      Anycast edge / CDN + GeoDNS (TTL 60 s, health checks 10 s)
             |                                      |
 Region A (Mumbai)                       Region B (Hyderabad)
  cells (stateless services)              cells (stateless services)
  user directory replica                  user directory replica
  Orders DB: primary for A users <-async-> Orders DB: primary for B users
  Kafka <------ MirrorMaker 2 ----------> Kafka
  Object store <--- cross-region copy --> Object store
  Ledger node <------ Raft quorum ------> Ledger node
             |                                      |
             +---------- Region C (witness) --------+
                 ledger voting node, health probes,
                 failover controller (3-node quorum),
                 immutable backup vault (separate account)
```

- **Anycast edge / CDN:** TLS near users; moves origin to a healthy region in seconds.
- **GeoDNS:** second, coarser routing layer with 60 s TTL.
- **Home-region directory:** user_id -> home region and epoch, replicated everywhere.
- **Regional cells:** independent stacks of about 5% of users each; limit blast radius.
- **Orders DB:** primary per partition in its home region, async replica in the peer.
- **Payment ledger:** Raft/Paxos across A, B, C; commit on 2 of 3, so RPO 0.
- **Failover controller:** quorum state machine: detect, decide, fence, promote, shift, verify.
- **Health probe mesh:** synthetic checkouts from region C and external vantage points.
- **Backup vault:** snapshots plus continuous WAL archive, retention-locked.
- **Reconciliation service:** replays or flags the unreplicated tail after failover.

**Flow A: steady-state order write**
1. Shreya (home A) orders; the edge routes to A from the cached directory.
2. Order commits locally in A (about 5 ms); payment commits to the ledger on A plus C or B (about 60 ms).
3. Order replicates async to B (lag p99 under 1 s); events mirrored to B's Kafka.

**Flow B: region A fails**
1. Probes from C and outside fail A's synthetic checkout 3 times in a row (30 s).
2. Controller nodes in B and C agree A is down; reads move at once (edge marks A down).
3. On-call approves write failover (or auto after 3 min); the epoch for A's partitions is bumped and fenced.
4. B promotes its replicas; the directory moves A users to B; tier-3 is shed; synthetic checks verify.

## Page 3. The core deep dives

### 1. RPO and RTO tiers drive everything
Tier-1 (checkout, orders, ledger) runs active-active with home-region writes: RTO 5 min, RPO 0-1 s. Tier-2 (catalog, search) is active-active for reads, RPO 5 min. Tier-3 (recommendations, analytics, batch) is warm standby or backup and restore, and is shed during failover. Every service is registered with its tier and owner, so cost follows business value rather than being uniform.

### 2. Replication per data type
The ledger uses a 3-region quorum: a write commits when 2 of A, B and C acknowledge, so losing any one region loses nothing (RPO 0), at a cost of 60-120 ms p99. Orders replicate asynchronously with lag under 1 s, keeping writes local at 20k/s. The lost tail is recoverable because payments are RPO 0: paid orders missing in the new primary are replayed idempotently, unpaid ones voided, and clients retry with idempotency keys. Objects use async cross-region copy with a 15-minute SLA. In PACELC terms (consistency vs availability in a partition, else consistency vs latency): ledger PC/EC, orders consistent at home and EL to the peer, catalog PA/EL.

### 3. Split brain prevention: quorum plus epoch fencing
Each partition's owner and epoch live in the controller's consensus store across three regions. Failover bumps the epoch (say 7 to 8), writes min_epoch=8 to storage, promotes B, and updates the directory. If A's old primary comes back as a zombie and writes with epoch 7, storage rejects it. A two-way A-B partition cannot elect two primaries, because the decision needs a quorum that includes C and external probes, not peer-to-peer signals.

### 4. Static stability and backups
Each region runs at 50-60% of tier-1 capacity with secrets, KMS keys and partner allowlists already present, so failover needs no new resources or the provider's control plane. Replication faithfully copies a bad migration everywhere, so logical disasters need different tools: continuous WAL archive for 7-day PITR, a 1-hour delayed order replica, and immutable backups in a separate account, with monthly 1 TB restore tests against a 4 h target.

**Data model:**
- **PartitionOwnership** (controller consensus): partition_id; primary_region, epoch, lease expiry.
- **UserHome** (global KV): user_id -> home_region, partition_id, epoch; written only by the controller.
- **Order** (MySQL/Postgres per partition): order_id (ULID with region prefix), idempotency_key, written_epoch.
- **LedgerEntry** (Spanner/CockroachDB-style): range-partitioned by account_id; leaseholders in A or B, C votes.
- **RegionState** and **BackupCatalog**: health per region; snapshots, WAL range, last restore test.

**Key APIs:**
- `GET /v1/dr/status`: served from every region's controller replica.
- `POST /v1/dr/failover`: idempotent on failover_id; write scope needs approval.
- `POST /v1/dr/failover/{id}/approve`: two-person rule for production writes.
- `POST /v1/dr/failback`: drain, wait for lag 0, flip epoch, shift traffic in steps.
- `POST /v1/dr/drill`: gradual evacuation with automatic abort on SLO breach.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Replication lag at peaks:** monitor lag per partition; throttle bulk writers when lag exceeds 1 s.
- **Writes:** home-region writes scale by adding cells and regions; only the ledger pays quorum latency.
- **Reads:** served locally from replicas; cross-region only right after a home-region move.
- **Cold caches after failover:** pre-warm by replicating hot keys; size the DB for cold-start reads.

**Failure modes:**
- **Full loss of A:** reads move in under 1 min, writes in about 5 min with fencing; ledger unaffected; up to 1 s of orders reconciled.
- **A-B partition, both alive:** each serves its own home users; ledger available on the side with C; no failover without external probes.
- **A degraded, not down:** marked DEGRADED; reads shift gradually; evacuate only bad cells; writes fail over only if SLO burn persists.
- **Bad global config push:** failover does not help; staged per-region, per-cell rollouts and rollback do.
- **Logical corruption:** PITR or the delayed replica; replication does not help.
- **Controller loses quorum:** no automatic actions; offline break-glass runbook; the data plane keeps serving.
- **Ledger loses 2 of 3 regions:** writes stop (a CP choice); checkout blocks payments with a clear message.

**Trade-offs chosen:**
- **Active-active over active-passive:** the standby is exercised by real traffic every day, so failover is less risky.
- **Async orders plus reconciliation over sync:** local write latency; the tail is recoverable from the ledger.
- **Quorum ledger:** RPO 0 without blocking on one region, at 60-120 ms.
- **Automatic reads, approved writes:** a false write failover causes data loss and split-brain risk.
- **Anycast primary, DNS fallback:** DNS caches ignore TTLs.
- **Shed tier-3 over full 2x capacity:** tier-3 is about 20% of load and safe to drop briefly.
- **Slow, planned failback:** a rushed failback is a common cause of a second outage.

**What to measure:** replication lag p99 against RPO, ledger commit latency and quorum health, probe disagreement count, headroom per region, drill RTO and RPO and manual steps, time to drain a region, reconciliation outcomes, backup freshness and restore time, and stale-epoch rejections as a split-brain signal.

## Page 5. Say it in the interview

> "I start with RPO and RTO per tier, because they decide every choice and its cost. Orders and payments need RTO 5 minutes, with zero loss for payments and at most a second for orders; browse can be read-only for a minute. I run two Indian regions, Mumbai and Hyderabad, active-active, with every user homed in one region, so writes stay local and never conflict. The ledger is replicated by quorum across three regions, so losing one loses nothing. Orders replicate asynchronously, and the lost second is rebuilt from the ledger and idempotency keys. A failover controller across three regions detects with independent probes, fences the old region with an epoch, promotes the replicas and moves traffic through an anycast edge. Backups and PITR cover logical disasters, and we drill every quarter."

**Key points to land:**
- RPO and RTO per tier first; they set every choice and its cost.
- Region failover covers infrastructure loss; PITR and backups cover logical disasters.
- Quorum for the ledger (RPO 0), async plus reconciliation for orders.
- Home-region ownership gives local writes with no multi-writer conflicts.
- A 3-region quorum and epoch fencing at storage prevent split brain.
- Anycast edge for steering; DNS TTL alone is too slow and leaky.
- Statically stable: capacity, secrets and keys pre-staged in both regions.
- Automate read failover, gate write failover, fail back slowly.
- Drill quarterly; only measured RTO and RPO count.

**Likely follow-ups:**
1. **How do you prevent split brain?** One writer per partition from a 3-region consensus store, epoch fencing at storage, and failover needing a quorum that includes the third region.
2. **How do you handle the lost second of orders?** The ledger has every payment; paid orders missing in B are replayed idempotently, unpaid ones voided, clients retry with idempotency keys.
3. **The provider's global control plane fails?** The data plane is statically stable and the controller runs on our own infrastructure, so we need no new resources to fail over.
4. **Why not multi-cloud?** It doubles platform work, loses managed features and adds egress cost; most outages are regional. Keep backups exportable and revisit.
5. **How do you test safely?** Gradual evacuations (1% to 100%) off-peak with automatic abort, game days failing single stores, synthetic transactions in both regions.

**Director layer:**
- **Cost drivers:** about 1.35x compute, replication links (2 x 10 Gbps), a third region for quorum and backups; within the +60% ceiling.
- **Phasing:** single-cloud multi-region in v1; tier-1 active-active first, then tier-2, with multi-cloud revisited later.
- **Team ownership:** SRE owns the controller, traffic and drills; each service owner owns its DR tier and runbook; payments owns the ledger.
- **Top risks:** split brain, a false failover from a monitoring partition, survivor short of capacity, corruption replicated everywhere, runbooks rotting; drift between regions is the biggest.
