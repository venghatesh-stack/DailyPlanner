# Design a file storage and sharing system (Dropbox / Google Drive): the 5-page summary

Users expect to drop a file on one device, see it everywhere within seconds, share it with a link, and never lose it. The single most important idea: split a small, strongly consistent metadata plane (namespace tree, versions, permissions, a per-namespace change journal) from a huge data plane of immutable, content-addressed blocks that clients move directly with signed URLs.

## Page 1. The problem, scope and numbers

**Pitch:** keep every file safe and identical across devices, make sharing a folder or link trivial, and keep storage cost low enough for generous free tiers.

**Who uses it:** freelancers (laptop and phone, links for clients), team members (shared folders), photographers (tens of GB of RAW files over hotel Wi-Fi), IT admins (sharing policy, audit, recovery), plus finance and SRE.

**In scope:**
- **Upload and download** up to 50 GB per file, chunked and resumable.
- **Folders:** create, rename, move, delete to trash, restore.
- **Desktop sync client** with local change detection and delta sync; mobile and web with previews.
- **Sharing** with users and groups (viewer, editor, owner), inherited down the tree; links with role, expiry and password.
- **Version history and trash** for 30-180 days.
- **Conflicts** produce conflicted copies, never silent overwrites.

**Out of scope:** real-time co-editing, an S3-style developer API, video transcoding, full-machine backup.

**Non-functional targets:**
- **Durability:** eleven nines (99.999999999%) a year, checksums end to end.
- **Availability:** 99.95% metadata, 99.9% upload and download.
- **Latency:** sync between online devices p95 under 10 s; list folder p95 under 200 ms; commit p95 under 300 ms.
- **Consistency:** linearizable commits per namespace; read-your-writes for the author.
- **Security:** TLS, AES-256 at rest with per-block keys wrapped by KMS, ACL checked on every authorisation.

**Capacity math (500M users, 100M DAU, 10 GB each = 5 EB logical, 1B changes/day):**
- **Upload bytes:** 1B x 1 MB x 40% new after dedup = 400 TB/day, about 4.6 GB/s, 15 GB/s peak. So bytes go straight to storage, never through app servers.
- **Download bytes:** 3x upload, about 14 GB/s, 45 GB/s peak. So serve via CDN and signed URLs.
- **Commits:** 1B / 86,400 = 11.6k/s, 40k/s peak. So shard metadata so each commit is a single-shard transaction.
- **Delta and list reads:** 100M x 20 an hour x 8 hours / 86,400 = 185k/s. So use long-poll, which idles without touching the database.
- **Raw disk:** 5 EB x 0.75 (25% dedup) x 1.5 (erasure coding) = 5.6 EB, about 280k drives of 20 TB. So dedup and erasure coding are first-class.
- **Metadata:** 100B file entries x about 1 KB = 100 TB; block index 1.25 trillion entries x 100 B, over 100 TB. Small next to the data, but the hot, consistent part, so it is the bottleneck.

## Page 2. The architecture

```
   Desktop sync client / Mobile / Web
     | (1) list, commit, delta              | (2) PUT/GET blocks, signed URL
     v                                      v
  API Gateway (auth, quotas)          Block Service (sign URLs, verify
     |          |                     hashes, block index, refcounts)
     |          v                           |                ^
     |    Sharing / ACL svc                 v                |
     v                                Block Storage          CDN
  Metadata Service                    (content-addressed,
  (namespaces, versions,               RS 6+3 over 3 zones,
   journal per namespace)              scrubbing)
     |               |
     v               v
  Metadata DB     Notification svc     Async via Kafka: thumbnails,
  (MySQL/Vitess   (long-poll,          AV scan, search index,
   by namespace)   WebSocket)          GC of orphan blocks
```

- **Client sync engine:** chunks, hashes, uploads missing blocks, commits, pulls deltas.
- **API Gateway:** OAuth, per-user rate limits, quota checks, routing.
- **Metadata Service:** namespace tree, versions as block lists, conditional commits, journal.
- **Block Service:** "which hashes are missing", signed URLs, hash verification, refcounts.
- **Block Storage:** immutable blocks, erasure coded across zones, background repair.
- **Sharing and ACL:** grants, inheritance, links with expiry and password, audit.
- **Notification service:** holds long-polls; wakes devices when a journal advances.
- **CDN and async workers:** cache hot blocks; thumbnails, malware scan, search, GC.

**Flow A: upload a modified file**
1. Shreya edits plan.pptx; the client splits it into 12 blocks of 4 MB and hashes each (SHA-256).
2. `upload_session` with the 12 hashes; Block service says 2 are missing and returns signed PUT URLs (15 minutes).
3. Client uploads the 2 blocks in parallel; storage checks each hash equals its key.
4. Commit with parentRev 41; in one transaction: version 42, block references, journal append.
5. Notification service wakes her other devices.

**Flow B: sync to another device**
1. Device holds a long-poll on cursor ns123@9001; it returns "changes" when seq advances.
2. `GET /delta` returns entries 9002-9010; the device fetches only blocks it lacks.
3. It writes a temp file, verifies hashes and renames atomically; a local unsynced edit becomes a conflicted copy.

## Page 3. The core deep dives

### 1. Content-addressed blocks and dedup
A block's key is SHA-256 of its content, so dedup, immutability and integrity come for free, and uploads are idempotent. A file version is an ordered list of block hashes, so restore and copy are metadata-only. Fixed 4 MB blocks are simple, but inserting one byte at the start shifts every boundary and changes every hash. Content-defined chunking puts boundaries where a rolling hash of the last 48 bytes matches a pattern, so only one or two blocks re-upload; use it for large, frequently edited files. Dedup is global only with proof of possession, and per tenant for business, because global dedup can leak that a file exists.

### 2. Conditional commit and conflicts
The commit carries parentRev, the revision the client edited. The server commits only if the current rev still equals it; otherwise it returns 409. Example: Shreya and Sethu both edit rev 41 offline. Shreya commits rev 42 first; Sethu's commit fails, so his client keeps the server version at the path and uploads his as "plan (Sethu's conflicted copy).pptx". Binary files cannot be merged, and last-writer-wins by client clock would lose work. Edit beats delete, and the server rejects moves that create cycles. With a central server, a revision counter replaces vector clocks. On the client, three trees (Remote, Local, Synced) make decisions deterministic: Local vs Synced gives local changes, Remote vs Synced gives remote ones, and both changed means conflict.

### 3. Journal, cursors and long-poll sync
Each namespace (a user root, shared folder or team space) has a journal with strictly increasing seq, appended in the same transaction as the change. Clients hold opaque cursors ("ns123@9001"); delta returns what follows. A shared folder is a mounted namespace with its own cursor. A folder move of 100,000 files is one journal entry, since children reference parentId. After 90 days the journal is compacted and old cursors reset to a full sync.

### 4. Erasure coding and garbage collection
Reed-Solomon 6+3 splits a block into 6 data and 3 parity fragments; any 6 rebuild it. Three per zone across 3 zones survives a zone loss at 1.5x overhead versus 3x for replication; fresh hot blocks start replicated, then convert. Repair speed drives durability as much as parity count. GC is the riskiest part: a block at refcount zero is deleted only after a 7-day window and re-verification, and a monthly audit reconciles counts with version block lists.

**Data model:**
- **Namespace / FileEntry / FileVersion / JournalEntry** (MySQL on Vitess, shard key namespaceId): unique (namespaceId, parentFolderId, nameLower); version PK (namespaceId, fileId, rev); journal PK (namespaceId, seq).
- **BlockIndex** (sharded KV, key hash, by hash prefix): locator, refCount, zeroRefSince, key id.
- **Grant / Link:** PK (itemId, principal), index on principal for "shared with me".

**Key APIs:**
- `POST /v1/upload_session`: block hashes in, missing hashes with signed PUT URLs out; resumable 48 h.
- `POST /v1/files/commit`: conditional on parentRev; 409 with currentRev on conflict.
- `GET /v1/delta?cursor=ns123@9001`: entries after the cursor, a new cursor, hasMore.
- `POST /v1/longpoll_delta`: changes true or false within 90 s; no database hit while idle.
- `GET /v1/files/{id}/download`: ACL check, block URLs valid 5 minutes.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Metadata, not bytes:** shard by namespace so commits stay single-shard; a directory service maps namespaces to shards, so hot team namespaces can be moved (copy, verify, cutover).
- **Giant team namespaces:** split or isolate them on their own shards.
- **Cross-namespace moves:** rare; a two-step saga (copy references, then delete) with idempotent steps.
- **Viral shared link:** CDN caches blocks by immutable hash, validates signed URLs at the edge, per-link bandwidth limits.
- **Huge files (1 TB):** 250,000 blocks; make the block list itself a tree of hash lists.

**Failure modes:**
- **Disk or node lost:** reads decode from other fragments; repair rebuilds within hours; no user impact.
- **Zone lost:** 6 of 9 fragments remain; reads continue at decode cost; metadata fails over to another zone.
- **Metadata primary fails:** a semi-sync replica is promoted in about 30 s; commits get retryable errors meanwhile; block uploads continue.
- **Notification tier down:** clients poll delta every 60 s with jitter; slower, still correct.
- **Client bug mass-deletes:** anomaly detection pauses sync, deletes go to trash, a kill switch disables that client version.
- **Ransomware:** high-entropy mass changes trigger an alert and a point-in-time restore from versions.
- **Bit rot:** per-fragment checksums, continuous scrubbing, reconstruction.

**Trade-offs chosen:**
- **Hybrid durability over pure 3x replication:** fast access for fresh data, 1.5x for the long tail, about half the disks.
- **Sharded MySQL over Cassandra:** commits need transactional CAS across rows of one namespace; Spanner if cross-namespace transactions become common.
- **Conflicted copies over last-writer-wins or locks:** never loses data and works offline.
- **Long-poll or WebSocket over polling:** seconds-level sync at low cost; mobile uses push since the OS restricts background sockets.
- **Start on S3, own the store later:** cloud is cheaper to start; at exabytes owning hardware saves large sums, as Dropbox's Magic Pocket showed.

**What to measure:** commit-to-visible sync latency p50/p95; upload and download success by platform and network; commit and list p99 per shard and the hottest namespaces; dedup ratio and storage overhead (target under 1.6x); conflict copies per 1,000 commits; under-replicated fragments, repair backlog and scrubber failures; GC deletions and audit mismatches; long-poll count and wake-to-delta latency.

## Page 5. Say it in the interview

> "I will design a Dropbox-style system: upload, download, folders, sync, sharing and version history, for about 100 million daily users, exabytes of data, eleven nines durability, and changes visible on other devices within seconds. The key is two planes. The metadata plane holds the namespace tree, versions, permissions and a per-namespace change journal in a sharded, strongly consistent database. The data plane holds immutable 4 megabyte blocks named by their SHA-256 hash in an erasure-coded store. Clients chunk and hash a file, upload only the blocks the server lacks, straight to storage, then commit a version as a list of hashes with a parent revision for conflict detection. Other devices long-poll and pull a delta from their cursor. Metadata, not bytes, is the bottleneck."

**Key points to land:**
- Split a consistent metadata plane, sharded by namespace, from an immutable data plane.
- A file is a list of SHA-256 block hashes: dedup, integrity and idempotent uploads for free.
- Upload only missing blocks, directly to storage, via signed URLs.
- Commit is a compare-and-set on parentRev; conflicts become conflicted copies.
- Journal plus cursors plus long-poll gives sync in seconds.
- Erasure coding 6+3 across 3 zones: 1.5x overhead, survives a zone loss.
- GC is the riskiest component: refcounts, safety windows, audits.
- Permissions are checked at metadata time and carried to storage as short-lived URLs.
- Version history and trash defend against client bugs and ransomware.

**Likely follow-ups:**
1. **Revoke a share when signed URLs are already out?** They expire in minutes; for instant cut-off, put a key version in the signature and bump it, or check a token at the edge.
2. **End-to-end encrypted folders?** Clients encrypt with keys the server never sees; you lose cross-user dedup, previews, search and virus scanning, so make it an opt-in tier.
3. **Data residency?** A namespace has a region; its shard and block placement pin there, and the CDN avoids caching outside allowed regions.
4. **LAN sync?** Peers fetch missing blocks from each other and verify hashes against the server's block list; metadata stays server-authoritative.
5. **Test a sync engine on millions of machines?** Deterministic simulation of disk, network and server with fault injection, asserting no data loss and convergence, as Dropbox did for Nucleus.

**Director layer:**
- **Cost drivers:** about 5.6 EB of raw disk (280k drives) dominates; dedup, compression and erasure coding are the levers, then download egress, cut by the CDN.
- **Phasing:** start on cloud object storage; build an owned erasure-coded store once at exabyte scale.
- **Team ownership:** sync client, metadata platform, block storage, sharing and security, and storage SRE (durability, repair).
- **Top risks:** a sync bug deleting files on every device, leaked shared links, ransomware, and dedup leaking that a file exists.
