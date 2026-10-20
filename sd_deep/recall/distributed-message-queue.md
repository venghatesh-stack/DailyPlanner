# Distributed Message Queue (Kafka): recall card

> **Hook:** Hash key to partition → Append to leader log → Followers pull → Advance high watermark → Consumers read by offset

**P · Problem:** It's really a replicated, partitioned, append-only log where consumers read by offset and retention, not consumption, deletes.

**N · Numbers:**
1. About 950 TB of disk for 7 days at RF 3, so disk, not CPU, sets the size at about 24 brokers.
2. 1 GB/s at about 10 MB/s per partition, so at least 100 partitions, the unit of parallelism.
3. About 7.5 GB of recent data per broker fits in 64 GB RAM, so caught-up consumers read from page cache.

**H · Hard part:** Keeping per-key order and zero acked loss through broker and AZ failures while staying fast.

**B · Boxes:** `Producer → Partition leader → ISR followers → High watermark → Consumer group`

Side path: `KRaft controller quorum` for metadata and leader election.

**D · Decisions:**
1. ISR with RF=3, min ISR 2 and acks=all over majority Raft for data, because it survives one failure without waiting on slow replicas.
2. Pull over push, because consumers set their own pace and get natural backpressure.
3. Retain for time over delete on ack, because it allows replay and many independent consumers.

**F · Failures:**
1. Broker crash → controller elects new leaders from the ISR; produce p99 spikes briefly; no acked loss.
2. Controller quorum lost → leaders keep serving but no elections happen; page immediately.

**C · Close:** "So this is a durable log, not a delete-on-ack queue. Each topic splits into partitions, each a segmented append-only log replicated three ways across AZs. Producers hash the key and batch; with acks all and min in-sync replicas two, an ack means two copies. Consumers read only below the high watermark and commit offsets to a compacted topic. Raft holds metadata. Next I would add retry and dead-letter topics."

**Quiz yourself:**
1. What decides ordering? → The key, because order is only per partition.
2. Is exactly-once real? → It is an effect: idempotent producer plus transactions plus idempotent sinks.
3. Why is unclean leader election off? → An out-of-sync replica would silently lose acked data.
