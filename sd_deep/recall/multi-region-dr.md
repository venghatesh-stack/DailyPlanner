# multi-region failover and disaster recovery: recall card

> **Hook:** RPO/RTO per tier → Home region per user → Quorum ledger, async orders → Probes from a third region → Fence with epoch → Promote and shift

**P · Problem:** It's really a negotiation between RPO, RTO, cost and consistency, solved per data tier.

**N · Numbers:**
1. 10k writes/s per region x 1 s lag = up to 10k order writes lost, so reconciliation from the ledger is a must-have.
2. Ledger quorum p99 is 60-120 ms versus 10 ms local, so only the ledger pays cross-region latency.
3. DNS failover takes 1-3 min with checks, TTL and resolver caching, so an anycast edge is primary.

**H · Hard part:** Failing over within 5 minutes without two regions ever writing the same data, and without losing a payment.

**B · Boxes:** `Users → Anycast edge → Home-region cell → Orders DB primary → Async replica in peer region`

Side path: `Ledger nodes in A, B and C → Raft quorum (2 of 3)` for RPO 0 payments.

**D · Decisions:**
1. Active-active over active-passive, because the standby is exercised by real traffic every day.
2. Async orders plus reconciliation over sync replication, because writes stay local and the tail is recoverable from the ledger.
3. Automatic reads, approved writes over full auto failover, because a false write failover risks data loss and split brain.

**F · Failures:**
1. Region A lost → reads move in under 1 min, writes in about 5 min with fencing; up to 1 s of orders is reconciled.
2. Bad migration or corruption → replication copies it everywhere, so PITR or the 1-hour delayed replica restores.

**C · Close:** "I start with RPO and RTO per tier, because they decide every choice and its cost. Two Indian regions run active-active, with every user homed in one region, so writes stay local. The ledger uses a three-region quorum, so losing one region loses nothing. Orders replicate asynchronously and the lost second is rebuilt from the ledger. A controller across three regions detects with independent probes, fences with an epoch, promotes and shifts traffic. Backups cover logical disasters, and we drill quarterly."

**Quiz yourself:**
1. How do you stop a zombie primary writing? → Failover bumps the epoch and storage rejects stale-epoch writes.
2. How does the survivor fit all traffic? → Shed tier-3, about 20% of load.
3. Why fail back slowly? → A rushed failback often causes a second outage.
