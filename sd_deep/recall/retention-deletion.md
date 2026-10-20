# Enforceable data retention and deletion policy: recall card

> **Hook:** Policy as code → Catalog finds every copy → Expire by partition drop → Erase by idempotent saga → Crypto-shred the rest → Prove it in a ledger

**P · Problem:** It's really a distributed workflow and data-discovery problem: find every copy, delete it safely, and prove it.

**N · Numbers:**
1. 5,500 erasures/day x 40 stores = 220k tasks/day, so batch per store into jobs of about 1,000 ids.
2. 30 TB/day of clickstream kept 180 days is 5.4 PB, so expiry must be partition drops, never row deletes.
3. 35-day backups plus a 30-day SLA let a copy live 65 days, so crypto-shred to make backups unreadable at once.

**H · Hard part:** Finding every copy across hundreds of stores and backups, and deleting it within 30 days without ever touching data under legal hold.

**B · Boxes:** `Erasure request → Orchestrator → Catalog and lineage → Store agents → Key service → Deletion ledger`

Side path: `Policy registry → Bulk expiry engine → TTLs and partition drops`.

**D · Decisions:**
1. Orchestration over choreography, because pure events cannot say when deletion is complete or produce evidence.
2. Method per data class over one method everywhere, because each store has a different cheapest correct mechanism.
3. A 14-day grace period over instant deletion, because it protects against account takeover and regret.

**F · Failures:**
1. Policy bug triggers mass deletion → a per-dataset breaker trips at 3x expected volume; partitions sit in quarantine for 7 days.
2. Kafka replay or restore brings an erased user back → the hashed denylist drops them on ingest, restore and replay.

**C · Close:** "I separate policy, which Legal decides, from enforcement, which is an engineering system. A catalog classifies every column, CI blocks unclassified PII, and lineage reaches every copy. Bulk expiry uses TTLs and partition drops. Each erasure is a durable workflow fanning out idempotent delete tasks to every store. Backups and immutable logs are crypto-shredded. I prove it with canaries, residual scans and an append-only deletion ledger."

**Quiz yourself:**
1. What is the precedence order? → Legal hold, then statutory minimum, then erasure or max retention.
2. When are bytes really gone in Iceberg? → After compaction plus snapshot expiry, or time travel still reads them.
3. Is pseudonymisation enough? → No; the mapping can re-link it, so it is still personal data.
