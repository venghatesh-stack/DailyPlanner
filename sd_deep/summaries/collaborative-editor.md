# Design a collaborative document editor (Google Docs): the 5-page summary

Many people type into one document at once over flaky networks; each must see their own keystrokes instantly, and all copies must converge to exactly the same text. The key idea: apply edits locally first, then give each document exactly one owner that acts as its sequencer (operational transformation with a central server), fenced by a lease epoch and backed by a durable op log.

## Page 1. The problem, scope and numbers

**Pitch:** a browser and mobile editor where many people work on one living document, see each other's changes and cursors in real time, never lose work and can restore any earlier version.

**Who uses it:** authors (zero lag, autosave), reviewers (suggestions, comments), meeting note-takers (10-30 people typing into one agenda), mobile commuters (patchy connectivity), and enterprise admins (sharing, residency, audit).

**In scope:**
- **Real-time co-editing** of rich text: insert, delete, formatting, lists, tables, images.
- **Presence:** active collaborators, cursors and selections.
- **Comments and suggestions** anchored to text that survive concurrent edits.
- **Version history:** automatic and named versions, diff, restore.
- **Sharing:** owner, editor, commenter, viewer for users, groups and links.
- **Offline editing** with merge on reconnect, and visible autosave state.

**Out of scope:** spreadsheet formulas and slide layout, search ranking, every office import format, end-to-end encryption (it breaks server-side transform and search), Git-style branches.

**Non-functional targets:**
- **Latency:** keystroke to screen under 16 ms (no network in the path); remote edits p95 under 200 ms in-region, p99 under 500 ms; 50-page doc opens p95 under 1.5 s.
- **Availability:** 99.95% for edit; viewers degrade to read-only rather than fail.
- **Durability:** acknowledged ops on 3 replicas before the ACK; RPO 0, RTO under 30 s per doc.
- **Consistency:** strong eventual convergence: all clients identical after edits stop.
- **Scale per doc:** 100 concurrent editors and 1,000+ viewers.

**Capacity math (50M DAU, 5M docs open at peak):**
- **Typists:** 5M docs x 0.4 active x 1.3 typists = 2.6M at peak.
- **Ops:** 2.6M x 3 ops/s = 7.8M ops/s globally. But one doc peaks at 100 x 5 = 500 ops/s, which one core handles. So build many small per-doc sequencers, not one big one.
- **Op log:** 7.8M x 200 B = 1.56 GB/s at peak, about 45 TB/day raw. So compact with snapshots and TTL old ops.
- **Fan-out:** 2.5 sessions per doc gives 1.5 recipients per op: 12M messages/s, 1.2 GB/s egress. So route all sockets of a doc to one node to keep fan-out local.
- **Sockets:** 5M x 2.5 = 12.5M; at 50k per node, 250 session servers; plan 400 for headroom and failover.
- **Storage:** snapshots 500M docs x 50 KB = 25 TB; 20 versions x 10 KB each = 100 TB. Cheap blob storage.

## Page 2. The architecture

```
  Web / iOS / Android (local replica + pending buffer)
     | WebSocket (ops, acks, presence)       | HTTPS (open, share, history)
     v                                       v
  Edge / WS gateway --lookup docId--> Doc Router (etcd leases, epoch)
     | sticky by docId                Metadata + ACL (Spanner/Postgres)
     v
  Session server (owner of doc D) -----> Presence (Redis pub/sub, TTL 30 s)
   sequencer, in-memory doc, OT
     | append(docId#rev, epoch)    | read snapshot
     v                             v
  Op log (Bigtable/Cassandra)   Snapshot store (S3/GCS, every 500 ops)
     | CDC stream (Kafka)
     v
  Snapshotter, Version history, Search indexer, Notifications
```

- **Client editor engine:** local model, instant apply, one in-flight op, offline queue in IndexedDB.
- **Edge gateway:** TLS, auth, proxies each socket to the doc's current owner.
- **Doc Router:** docId to owner via etcd leases (TTL 10 s) with a rising epoch.
- **Session server:** per-doc sequencer: ACL, dedupe, transform, assign rev, append, broadcast.
- **Op log:** append-only, keyed (docId, rev), conditional put, 3 replicas; the source of truth.
- **Snapshot store:** full doc state every 500 ops or 5 minutes; bounds open-time replay.
- **Presence:** cursors and who-is-here on a lossy channel, shed first under load.
- **Metadata, ACL and comments:** strong reads; revoke events reach live sessions.
- **Async consumers:** version history, search and mentions read the log stream.

**Flow A: edit and propagate**
1. Client applies the insert locally and sends SUBMIT_OP {clientId, clientSeq 42, baseRev 1007}.
2. Owner dedupes on (clientId, 42), transforms against revs 1008-1009, appends as rev 1010 with its epoch.
3. After the durable append: ACK {rev 1010} to the author, REMOTE_OP to others.
4. Receivers transform it against their own pending ops and apply.

**Flow B: owner failover**
1. Session server S1 crashes; its lease on doc D expires after 10 s.
2. Router grants D to S2 with epoch+1; S2 loads the snapshot plus log tail.
3. A late write from zombie S1 carries the old epoch and is rejected; clients reconnect and resubmit unacked ops, which dedupe.

## Page 3. The core deep dives

### 1. OT with a central sequencer
Every op carries the revision it was based on. The server keeps recent history and transforms an incoming op against every op committed after its baseRev, a simple linear walk because the server has a total order. This only needs TP1, the rule that applying a then b' equals applying b then a'. It avoids TP2, the hard multi-site property, because transforms only happen between a client and the one server. Example: at rev 1007 the text is "Hello". Shreya inserts "!" at position 5; Sethu inserts "Hi " at 0 and commits first as rev 1008. Shreya's op is transformed to position 8 and committed as rev 1009: "Hi Hello!". Ties at the same position break deterministically (committed op first, or lower clientId). The client keeps one in-flight op plus one composed buffer of later edits.

### 2. Single owner, lease and fencing
The router grants each doc a lease with an epoch. The log append is conditional on "rev not already present" AND "epoch is current". A session server paused 20 s by garbage collection wakes up after ownership moved; its writes carry the old epoch and are rejected, so it closes its sockets. A lease limits dual ownership; storage, not the owner, enforces safety.

### 3. Durability, idempotency and reconnect
Ack only after the op is durably appended; typing never waits for the ack anyway. Each op carries (clientId, clientSeq); the last committed seq per client is rebuilt from the log on failover. If the log write succeeds but the ACK is lost, the retry finds it committed and returns the original rev. Offline clients send RESUME {lastRev, unacked seq}, receive the missed ops and rebase their queue; past 10k ops the server sends a fresh snapshot. Reconnects back off from 500 ms to 30 s with full jitter.

### 4. Why not a CRDT?
A CRDT (conflict-free replicated data type, such as Yjs) gives each character a unique id so ops commute without a server. It wins for long offline sessions, peer-to-peer or a dumb-relay backend, but pays in metadata and tombstones. We need a server for ACLs and history anyway, so OT is more compact.

**Data model:**
- **Document** (Spanner/Postgres, by docId): owner, title, region, lastRev, lastSnapshotRev.
- **Operation** (Bigtable/Cassandra): row key docId#rev zero-padded; clientId, clientSeq, epoch, ops.
- **Snapshot** (S3/GCS): snapshots/{docId}/{rev}, immutable, with a checksum.
- **Permission**: PK (docId, principalType, principalId); index on principal for "shared with me".
- **Comment**: anchored to stable element ids that move with the text.

**Key APIs:**
- `GET /v1/docs/{id}/open`: checks the ACL; returns snapshot URL, rev and a 5-minute session token.
- `WS /v1/collab`: SUBMIT_OP, ACK, REMOTE_OP, ERROR (STALE_BASE, FORBIDDEN, RESYNC).
- `POST /v1/docs/{id}/permissions`: share; a downgrade pushes revoke to live sessions.
- `GET /v1/docs/{id}/revisions`: served from the version-history index, not the raw log.
- `POST /v1/docs/{id}/restore`: a new forward op, so history stays append-only.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Per-doc sequencer:** deliberate serialisation point; coalesce keystrokes every 50-100 ms to stay at a few hundred ops/s.
- **Hot docs (5,000 people on an all-hands agenda):** cap editors near 100; viewers join a separate fan-out tier tailing the log; presence shows "4,900 viewers".
- **500 people typing:** 1,500 ops/s is fine for CPU, but fan-out is 750k messages/s; batch broadcasts every 50 ms or split into sections.
- **Writes overall:** shard docs across session servers; no cross-doc coordination, so capacity grows linearly.
- **Open time:** snapshot plus short tail, snapshots served from a CDN-backed blob store.

**Failure modes:**
- **Session server crash:** lease expires in about 10 s, a new owner rebuilds; clients see "reconnecting", nothing lost.
- **Op log loses quorum:** appends fail, owner stops acking; clients keep editing locally and show "trying to save".
- **etcd down:** owners keep serving until their leases lapse; new opens fall back to read-only snapshots.
- **Transform bug:** checksum mismatch makes the client reload the snapshot and rebase; alert, flag off the op type.
- **Region outage:** docs become read-only from replicated snapshots; residency-pinned tenants wait, others fail over.
- **ACL revoked mid-session:** further ops get FORBIDDEN and the socket closes within seconds.

**Trade-offs chosen:**
- **OT with a central sequencer over CRDTs or paragraph locks:** compact ops, proven at Google Docs scale; locks feel terrible and fail offline.
- **Stateful owner over stateless servers:** transform needs recent history in memory; stateless means a DB read per keystroke and races on rev.
- **Ack after durable append over ack after in-memory apply:** a few ms more, but RPO 0.
- **Separate lossy presence channel over the op log:** cursors are worthless after a second.
- **Wide-column log keyed docId#rev over Kafka partitions:** hundreds of millions of tiny logs fit row ranges; conditional inserts give one op per rev.

**What to measure:** op submit-to-ack p50/p95/p99 per region, remote propagation latency, divergence and resync rate, reconnect rate and duration, ops/s and editors per hottest docs, ops since last snapshot, open time p95, conditional-write conflicts (spikes mean dual owners), socket buffer depth, lost-ack incidents (must be zero).

## Page 5. Say it in the interview

> "I assume a Google Docs style rich-text editor: usually a handful of editors per document with a cap near 100, 50 million daily users, keystrokes that render instantly, remote edits visible within about 200 milliseconds, short offline periods and zero loss of acknowledged edits. Everyone edits optimistically, so all copies must converge. My design gives each document one authoritative session: clients send ops tagged with their base revision, the server transforms them against anything committed since, assigns the next revision, appends to a durable op log and broadcasts. That is OT with a central sequencer, and I will contrast it with CRDTs. To scale, a lease-based router shards documents across session servers so each has exactly one writer; an append-only log plus snapshots stores them; presence runs on a separate best-effort channel."

**Key points to land:**
- Apply locally first, converge later: typing never waits on the network.
- One owner per document is the sequencer, so OT only needs TP1.
- Ack only after the durable append: RPO 0 for acknowledged edits.
- Fence the owner with a lease epoch so a zombie can never commit.
- (clientId, clientSeq) makes retries safe on mobile.
- The op log is the truth; snapshots every 500 ops bound open time.
- Presence is a separate lossy channel, shed first.
- Scale is many small sequencers sharded by docId; viewers of hot docs use a fan-out tier.
- Know when CRDT wins: long offline, peer-to-peer, dumb relay.

**Likely follow-ups:**
1. **Why not lock paragraphs?** Locks add latency (you click and cannot type) and fail offline; keep them only for objects that cannot merge, like a chart's settings.
2. **Version history without keeping every op?** Consumers fold the stream into delta-compressed checkpoints; raw ops older than 30 days are TTL'd; restore reads checkpoints.
3. **How do comments stay on the right text?** Anchor to stable element ids transformed like cursors; if the text is deleted, show "original text deleted".
4. **Browser crash with unsaved changes?** The pending buffer is written to IndexedDB on every local op and resumes from the stored baseRev.
5. **How would Figma differ?** It edits a tree of object properties with server-ordered last-writer-wins, which works because concurrent edits to one property are rare; character text needs OT or a sequence CRDT.

**Director layer:**
- **Cost drivers:** about 400 session servers for 12.5M sockets, a 1.5 GB/s op log, about 125 TB of snapshots and versions, and egress for fan-out.
- **Phasing:** real-time editing with snapshots first; then history, comments and offline; then hot-doc viewer tier and residency.
- **Ownership:** editor engine (client), collaboration backend (router, session, log), sharing and ACL, history and search consumers.
- **Top risks:** silent divergence from transform bugs (fuzz tests, checksums), viral docs overloading one owner, lost ops on failover (ack after durable append, fencing), revocation not reaching live sessions.
