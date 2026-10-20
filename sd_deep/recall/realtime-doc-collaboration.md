# Real-Time Collaboration for a Shared Document (sync layer): recall card

> **Hook:** Apply locally → Send CRDT ops → One session server per doc → Quorum append, then ack → Broadcast → Snapshot every 1,000 ops

**P · Problem:** It's really a replicated-state convergence problem where concurrent and offline edits must merge without losing intent.

**N · Numbers:**
1. 5M connected clients at 20k per node is 250 nodes, so connections, not ops, size the session tier.
2. 1.5M ops/s x 80 B = 10 TB/day of op log, so compact into snapshots and tier old logs.
3. A hot doc with 1,100 participants means 550k messages/s unbatched, so viewers go through a relay tier.

**H · Hard part:** Converging edits from clients offline for hours with zero divergence, while never losing an acknowledged edit.

**B · Boxes:** `Client CRDT → Router → Session server → Op log → Other clients`

Side path: `Op log → Compaction worker → Snapshot store`.

**D · Decisions:**
1. CRDT over OT, because hours of offline editing need merges that work in any order.
2. One owner per doc over peer-to-peer, because P2P cannot enforce permissions or durability.
3. Ephemeral cursors over persisted ones, because they are high-frequency and worthless once stale.

**F · Failures:**
1. Session server crashes → its 10 s lease expires; a new owner loads snapshot plus tail; clients resend unacked ops.
2. Network partition isolates the old owner → it cannot renew, and fencing tokens reject its appends.

**C · Close:** "Locking or last-writer-wins loses work, so the choice is OT versus CRDT. OT needs a central server and is fragile offline, so I use a CRDT, but route every document to one session server for permissions, ordering, persistence and fan-out. Clients apply edits instantly; the server appends to a per-document log with a quorum, acks, broadcasts and snapshots. Cursors use a separate ephemeral channel. Failover uses leases and fencing tokens with idempotent resend."

**Quiz yourself:**
1. How do two inserts at the same spot converge? → Every replica orders them by comparing their unique ids.
2. What makes reconnect cheap? → Exchanging state vectors, so only missing ops are sent.
3. Why keep tombstones? → A concurrent insert inside deleted text still needs a neighbour to attach to.
