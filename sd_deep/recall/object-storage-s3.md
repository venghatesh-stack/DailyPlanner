# Object Storage Service (S3): recall card

> **Hook:** Chunk → Erasure-code RS(10,4) → Write 14 fragments across AZs → Commit metadata in Raft → Bump witness → Ack

**P · Problem:** It's really two systems: a strongly consistent, range-partitioned metadata index and a cheap, self-healing blob data plane.

**N · Numbers:**
1. 100 PB x 1.4 = 140 PB, about 8,750 drives, so erasure coding, not 3x replication.
2. About 130 drive failures a year, several a day at 10x, so repair is continuous background load.
3. 100B x 500 B = 50 TB of metadata in about 50,000 partitions, so the hot problem is request heat, not bytes.

**H · Hard part:** Eleven nines of durability on cheap disks, and strong read-after-write while still caching metadata.

**B · Boxes:** `Client → Load balancer → Front-end → Placement → Storage nodes → Metadata service (Raft)`

Side path: `Scrubber, repair and GC` run in the background.

**D · Decisions:**
1. RS(10,4) over 3x replication for bulk data, because it costs 1.4x and survives 4 lost fragments.
2. Range partitioning over hash, because LIST by prefix needs sorted keys and heat is handled by splits.
3. Async GC with a grace period over synchronous delete, because DELETE stays fast with no races against readers.

**F · Failures:**
1. Front-end crashes after fragments, before commit → the object is never visible; GC removes the orphans.
2. Hot partition → 503 SlowDown for that range only, then a split at the load median.

**C · Close:** "I split it into two systems. The data plane erasure-codes each stripe into 10 data plus 4 parity fragments across three AZs: 1.4x storage instead of 3x. The metadata plane is a range-partitioned, Raft-replicated index from bucket and key to version and chunk locations. A PUT writes fragments, commits metadata, then acks; that commit makes reads consistent. Hot ranges split automatically, and repair, scrubbing and GC run all the time."

**Quiz yourself:**
1. How do caches stay consistent? → The witness holds the latest write sequence per key; stale entries go to the leader.
2. Why spread a stripe over many servers? → A dead server costs each stripe one fragment, so repair is parallel.
3. How do you catch bit rot? → End-to-end checksums and a scrubber.
