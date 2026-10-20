# Collaborative document editor (Google Docs): recall card

> **Hook:** Apply locally first → Send op with base revision → Owner transforms and sequences → Durable append, then ack → Broadcast to the doc

**P · Problem:** It's really a convergence problem: many optimistic replicas of one document must end up identical.

**N · Numbers:**
1. 7.8M ops/s globally but one doc peaks at 500 ops/s, so build many small per-doc sequencers, not one big one.
2. The op log is 1.56 GB/s at peak, about 45 TB/day, so compact with snapshots and TTL old ops.
3. 12.5M sockets at 50k per node needs 250 session servers, so plan 400 for headroom and failover.

**H · Hard part:** Converging concurrent edits with instant local typing, and never letting two owners commit to one doc.

**B · Boxes:** `Client editor → Edge gateway → Doc Router → Session server → Op log`

Side path: `Op log → Kafka CDC → Snapshotter, version history and search`.

**D · Decisions:**
1. OT with a central sequencer over CRDTs, because we need a server for ACLs and history anyway and ops stay compact.
2. A stateful owner over stateless servers, because transform needs recent history in memory.
3. Ack after durable append over ack after in-memory apply, because a few ms more buys RPO 0.

**F · Failures:**
1. Session server crash → lease expires in about 10 s, a new owner rebuilds from snapshot plus log; nothing lost.
2. Zombie owner wakes from a GC pause → its writes carry the old epoch and are rejected.

**C · Close:** "I give each document one authoritative session. Clients apply edits locally and send ops tagged with their base revision. The server transforms them against anything committed since, assigns the next revision, appends to a durable op log and broadcasts. A lease-based router shards documents so each has exactly one writer, fenced by an epoch. Snapshots bound open time, and presence runs on a separate lossy channel."

**Quiz yourself:**
1. Why does a central server make OT easier? → Transforms happen only between a client and one server, so only TP1 is needed.
2. How are mobile retries made safe? → Each op carries clientId and clientSeq, so a resubmit dedupes to the original rev.
3. When does a CRDT win? → Long offline sessions, peer-to-peer or a dumb-relay backend.
