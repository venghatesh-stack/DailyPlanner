# Design Real-Time Collaboration for a Shared Document (sync layer): the 5-page summary

This is the sync layer under a collaborative editor: how concurrent edits from many clients, some offline for hours, converge to the same document without losing anyone's intent. The single most important idea: use a sequence CRDT so merges work in any order and offline, but still route each document to one session server that checks permissions, persists an operation log, acks and fans out, with cursors kept as separate ephemeral state.

## Page 1. The problem, scope and numbers

**Pitch:** many people type in the same document at once, see each other's edits and cursors within 200 ms, keep editing offline, and never lose an acknowledged edit.

**Who uses it:** authors (instant typing, nothing lost), the editor team (a clean sync API), SRE (scalable sessions, clear failover), security (permission check on every op, audit, deletion).

**In scope:** optimistic local edits that emit ops with client id, sequence number and causal dependencies; a session server that checks permissions, orders, persists, broadcasts and acks after a durable append; load as snapshot plus tail, and reconnect by exchanging state vectors; awareness (cursors, selections, names) coalesced to 10-20 Hz and never persisted; version history, restore as new ops, and per-user undo.

**Out of scope:** the editor UI, comments, end-to-end encryption, spreadsheets and binary files, search.

**Non-functional targets:**
- **Latency:** local apply 0 ms; remote edit p95 under 200 ms in-region (p99 under 500 ms); ack p95 under 150 ms.
- **Durability:** acknowledged ops are never lost: quorum append before the ack.
- **Consistency:** strong eventual consistency: replicas that have seen the same ops are identical; zero divergence.
- **Availability:** 99.95% for sync; offline editing always works; failover under 15 s.
- **Load time:** open p95 under 1 s for documents under 1 MB.

**Capacity math (10M DAU, 1M open docs, 5M connected clients at peak):**
- **Ops:** 1M docs x 30% active x 2 editors x 50% typing = 300k typists x 5 ops/s = 1.5M ops/s, about 600k messages/s after 50 ms batching. So batch on the client.
- **Fan-out:** about 2.5 recipients per op = 1.5M outbound messages/s, plus similar cursor traffic. So coalesce cursors.
- **Session tier:** 5M clients / 20k connections per node = 250 nodes; ops are well under node capacity. So connections, not ops, size the tier.
- **Op log:** 1.5M ops/s x 80 B = 120 MB/s, about 10 TB/day raw. So compact into snapshots and tier old logs to object storage.
- **Snapshots:** 1M open docs x 200 KB = 200 GB hot; 2B docs x 100 KB = 200 TB in object storage.
- **Hot doc:** 100 editors x 5 ops/s to 1,100 participants = 550k messages/s unbatched, about 22k frames/s with 50 ms batching. So viewers need a relay tier.

## Page 2. The architecture

```
 Clients (web, mobile, desktop): CRDT doc + local store + unacked outbox
      | WebSocket
      v
 Edge LB -> Router: doc_id -> owner (hash ring + lease in etcd)
      |
      v
 Collab session servers: one actor per open doc
   ACL check, dedupe, integrate into CRDT, server_seq, awareness relay
      | quorum append (fencing token)     | broadcast
      v                                   v
 Op log (Cassandra/Bigtable,         Viewer relay tier -> read-only viewers
 partitioned by doc_id)
      | compaction worker (every 1,000 ops or 60 s)
      v
 Snapshot store (S3/GCS) + doc metadata DB (Postgres/Spanner)
      ^ open / failover: load snapshot + tail ops
```

- **Client sync SDK:** holds the CRDT, applies edits instantly, persists locally, resends unacked ops.
- **Router:** maps doc_id to its owner with a hash ring and per-doc leases.
- **Session server:** one actor per doc: ACL, dedupe, order, append, broadcast, ack.
- **Op log store:** durable append-only ops per doc, RF 3, quorum writes.
- **Compaction worker:** snapshots every 1,000 ops or 60 s; garbage-collects tombstones.
- **Viewer relay tier:** fans the ordered stream out to viewers, shielding the owner.
- **etcd:** session leases with fencing tokens and ring membership.
- **ACL cache:** permissions cached with invalidation, so every op is checked cheaply.

**Flow A: live edit**
1. Shreya types; her SDK applies it locally and records {client_id, seq, deps, payload}.
2. The SDK batches 50 ms of ops and sends them to the doc's session server.
3. The server checks the ACL, drops seen (client_id, seq), integrates, assigns server_seq.
4. Quorum append to the op log, then ack to Shreya with server_seq.
5. Broadcast to Sethu and the relay; each integrates into its local CRDT and re-renders.

**Flow B: session failover**
1. The owner crashes and stops renewing; its 10 s lease expires.
2. A new owner takes the lease with a higher fencing token and loads snapshot plus tail.
3. The log rejects appends with the older token; clients reconnect and resend unacked ops, deduped by (client_id, seq).

## Page 3. The core deep dives

### 1. OT versus CRDT
Operational Transformation (OT) needs a server to order ops; a client op based on an old revision is transformed against ops it missed (shift an insert position if an earlier insert is at or before it). It keeps no per-character metadata, but transforms for every rich-text op pair are hard, and hours of offline editing make transform chains long and fragile. A CRDT (conflict-free replicated data type) merges in any order because merge is commutative, associative and idempotent. Offline for hours is a requirement, so choose a Yjs-style YATA CRDT, with a server in the loop for auth, durability, history and fan-out. Convergence does not depend on the server.

### 2. How the sequence CRDT merges
Every character gets a unique id (client_id, clock), where the clock is a per-client logical counter, never wall time. An insert references the ids of its left and right neighbours. If Shreya and Sethu insert at the same spot at the same moment, every replica orders the two by comparing ids, so both texts survive in the same order everywhere. A delete leaves a tombstone, so a concurrent insert inside a deleted paragraph still has a neighbour to attach to and survives. Tombstones are garbage-collected once every known state vector covers them; a client older than the GC horizon does a full reload. Cursors are stored as positions anchored to item ids, so they stay on the right character.

### 3. Sync, durability and fencing
A state vector maps each client_id to the highest clock seen from it. On reconnect both sides exchange vectors and send only what the other lacks, so a client offline for 6 hours sends only its new ops. The SDK resends unacked ops (at-least-once); the server dedupes by (client_id, seq) and CRDT integration is idempotent, giving an exactly-once effect. Acks go out only after the quorum append. Each lease acquisition raises a fencing token; the log stores the highest token per doc and rejects lower ones, so a paused old owner that wakes cannot corrupt the log.

**Data model:**
- **OpLogEntry** (Cassandra/Bigtable): partition doc_id (bucketed by seq/100k for huge docs), clustering server_seq.
- **Snapshot** (S3/GCS): {doc_id}/{server_seq}.bin; named versions kept forever.
- **DocMeta** (Postgres/Spanner): PK doc_id, updated by the compaction worker, not per op.
- **SessionLease** (etcd): /leases/docs/{doc_id}, TTL 10 s, renewed every 3 s.

**Key APIs:**
- `WS /v1/docs/{id}/sync`: sync_step1 sends a state vector; sync_step2 returns the missing ops.
- `WS update`: {client_id, seq range, ops} returns an ack with server_seq.
- `WS awareness`: {cursor, selection, user, color}; dropped after 30 s silent.
- `POST /v1/docs/{id}/restore`: new ops to reach an old server_seq; history never rewritten.
- `OpLog.append(doc_id, fencing_token, ops)`: ok or stale_token.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Connections:** they size the session tier; add nodes on the ring, about 20k connections each.
- **Hot document:** a viral doc with 5,000 viewers and 100 editors puts viewers on the relay tier, caps editors (overflow joins as viewers), batches 50 ms and shows only the 20 most recent cursors.
- **Op log growth:** snapshots every 1,000 ops, tombstone GC, binary encoding, tiering old ops to object storage.
- **Large pastes:** a 5 MB paste is split into chunked ops with size limits and an immediate snapshot.
- **Fan-out with 1,000 editors:** it grows quadratically; cap editors and shard by section if the product allows.

**Failure modes:**
- **Session server crash:** the lease expires in 10 s; a new owner loads snapshot plus tail; clients resend; local typing never stops.
- **Partition isolates the old owner:** it cannot renew and fencing rejects its appends; clients on its side keep editing offline.
- **Op log slow:** acks are delayed and the server applies backpressure; clients buffer; nothing acked is lost.
- **Snapshot worker behind:** opens slow as the tail grows; alert on snapshot lag; the owner can snapshot inline.
- **Client diverges from a bug:** a periodic hash check at the same state vector detects it; the client reloads the snapshot and reapplies its unacked ops.
- **Region outage:** docs re-home using the replicated op log; offline editing bridges the gap.
- **Access revoked while offline:** the server rejects the ops; the SDK offers to copy them to a new document.

**Trade-offs chosen:**
- **CRDT over OT:** offline for hours and order-free merge, at the cost of metadata and tombstones.
- **One owner per doc over peer-to-peer:** P2P cannot enforce permissions or durability; one owner simplifies dedupe, server_seq and snapshots.
- **Cassandra/Bigtable over Kafka for the log:** high appends plus random per-doc reads for load and history.
- **50 ms batching:** cuts messages about 3x while staying inside the 200 ms budget.
- **Ephemeral cursors:** high-frequency and worthless once stale; persisting them multiplies writes.
- **Relay tier for viewers:** the owner's work stays proportional to editors.

**What to measure:** remote edit latency p50/p95/p99 (local apply to remote render), ack and append latency p99, ops/s per doc and the hottest docs, reconnect rate and resync size, offline merge success (over 99.9%), divergence detections (target zero), snapshot lag and open time p95, tombstone ratio, failovers per hour and their duration.

## Page 5. Say it in the interview

> "I will scope this as the sync layer, not the editor. Assume a handful of editors usually, up to 100 plus 1,000 viewers, hours of offline editing on mobile, remote edits visible within 200 ms, and a million documents open at peak. Locking or last-writer-wins loses work, so the real choice is OT versus CRDT. OT needs a central server to transform ops and is fragile offline; a CRDT merges in any order. So I use a CRDT, but route every document to one session server for auth, ordering, persistence and fan-out. Clients apply edits instantly and send ops with a client id and sequence number; the server appends to a per-document log with a quorum, acks, broadcasts and snapshots every thousand ops. Cursors travel on a separate ephemeral channel. Failover uses leases and fencing tokens with idempotent resend."

**Key points to land:**
- Scope it: merge algorithm, sessions, persistence, awareness, offline.
- OT needs a central order and complex transforms; CRDTs merge in any order.
- A sequence CRDT plus one server owner per doc for auth, durability, history and fan-out.
- Unique character ids, inserts reference neighbours, deletes are tombstones to GC.
- (client_id, seq) plus idempotent integration gives an exactly-once effect.
- Ack only after a quorum append; snapshot every 1,000 ops or 60 s.
- Leases for failover; fencing tokens stop a zombie owner.
- State vectors make reconnect send only what is missing.
- Cursors are ephemeral, coalesced and anchored to item ids.
- About 1.5M ops/s and 5M connections at peak; connections size the tier.

**Likely follow-ups:**
1. **When would you pick OT?** When clients are almost always online, the server is authoritative anyway, metadata overhead matters, or a mature OT engine exists; Google Docs is the example.
2. **Per-user undo?** Track each user's own inserted and deleted items; undo deletes what they inserted and restores what they deleted as new ops, so others' edits stay.
3. **Permissions with offline edits?** The server checks the ACL on every op at integration; revoked users' ops are rejected and kept locally for them to copy.
4. **How do you detect divergence?** Clients send a hash plus their state vector; the server compares at the same vector; a mismatch triggers resync and an alert.
5. **How is Figma different?** It is server-authoritative with last-writer-wins per property, fine for design trees; text needs character-level merge.

**Director layer:**
- **Cost drivers:** about 250 session nodes sized by connections, 10 TB/day of raw op log before compaction, and 200 TB of snapshots in object storage.
- **Phasing:** start online-only with a well-tested CRDT library, one owner per doc and snapshots; add offline sync, relay tier, version history and tombstone GC next.
- **Team ownership:** client SDK, collab session platform, storage (op log and snapshots), and security for ACL integration.
- **Top risks:** silent divergence from merge bugs, unbounded tombstone growth, a viral doc overwhelming one server, and huge divergent offline histories.
