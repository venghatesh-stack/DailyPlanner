# File storage and sharing system (Dropbox / Google Drive): recall card

> **Hook:** Chunk and hash → Upload missing blocks → Commit on parentRev → Append to journal → Long-poll and pull delta

**P · Problem:** It's really two planes: a small, strongly consistent metadata store and a huge store of immutable, content-addressed blocks.

**N · Numbers:**
1. 400 TB/day of new upload bytes, 15 GB/s peak, so bytes go straight to storage, never through app servers.
2. 40k commits/s at peak, so shard metadata by namespace so each commit is a single-shard transaction.
3. 5.6 EB of raw disk, about 280k drives, so dedup and erasure coding are first-class.

**H · Hard part:** Syncing every device within seconds without losing work to conflicts, while keeping exabytes durable and cheap.

**B · Boxes:** `Sync client → API Gateway → Metadata Service → Metadata DB → Notification service`

Side path: `Client → Block Service signed URL → Block Storage` for the bytes.

**D · Decisions:**
1. Conflicted copies over last-writer-wins or locks, because it never loses data and works offline.
2. Sharded MySQL over Cassandra, because commits need a transactional compare-and-set within a namespace.
3. Hybrid durability over pure 3x replication, because fresh data stays fast and the long tail costs 1.5x.

**F · Failures:**
1. Zone lost → 6 of 9 fragments remain, reads decode; metadata fails over to another zone.
2. Client bug mass-deletes → anomaly detection pauses sync, deletes go to trash, a kill switch disables that version.

**C · Close:** "So the key is two planes. Metadata holds the namespace tree, versions, permissions and a per-namespace journal in a sharded, consistent database. Data is immutable 4 MB blocks named by SHA-256 in an erasure-coded store. Clients upload only missing blocks via signed URLs, then commit a list of hashes with a parent revision. Other devices long-poll and pull a delta from their cursor. Metadata, not bytes, is the bottleneck."

**Quiz yourself:**
1. What happens when two people edit rev 41 offline? → The second commit gets 409 and becomes a conflicted copy.
2. Why content-defined chunking? → A one-byte insert re-uploads only one or two blocks.
3. What is the riskiest component? → Garbage collection: refcounts, a 7-day window and audits.
