# Design a Distributed Message Queue (Kafka): the 5-page summary

A Kafka-style queue is really a replicated, partitioned, append-only log: producers append, consumers read by offset, and messages stay for a retention period instead of being deleted on consume. The single most important idea: throughput comes from batching, sequential disk and many partitions, while every guarantee (per-key order, no loss after ack, exactly-once) hangs on the replication rules (ISR, high watermark, leader epochs) and on how consumers commit offsets.

## Page 1. The problem, scope and numbers

**Pitch:** one shared, durable event backbone so hundreds of services (orders, payments, inventory, clickstream) can exchange events without calling each other, absorb sale-day spikes, and let new consumers replay history.

**Who uses it:** producer teams (clear ack meaning), consumer teams (per-key order, replay, visible lag), platform SRE (capacity, quotas), security (ACLs, deletion) and finance (cost per GB).

**In scope:**
- **Topics:** partition count, replication factor, retention by time and size, delete or compact.
- **Produce:** key, value, headers; route by key hash; batch and compress; acks=0, 1 or all.
- **Idempotent and transactional producers:** no duplicates on retry; atomic writes plus offset commit.
- **Consumer groups:** assignment, rebalancing, offset commit, seek by offset or timestamp.
- **Retention, compaction and operations:** latest value per key; reassignment, quotas, ACLs, DR mirroring.

**Out of scope:** per-message priorities and delays (a job queue on top), global total ordering, querying by content, synchronous RPC, schema design (a schema registry).

**Non-functional targets:**
- **Latency:** publish p99 under 50 ms with acks=all (p50 under 10 ms); end-to-end p99 under 100 ms for caught-up consumers.
- **Availability:** 99.95% for produce and consume; leader failover under 10 s.
- **Ordering:** strict within a partition, so per key when keyed.
- **Durability:** RF=3 across 3 AZs, acks=all, min.insync.replicas=2; zero acked loss on a broker or AZ failure (RPO 0 in region).

**Capacity math (peak 1M messages/s x 1 KB = 1 GB/s; 3 consumer groups; 7-day retention):**
- **Daily ingest:** 1 GB/s x 0.4 average x 86,400 = about 35 TB/day.
- **Disk:** x3 replicas = 104 TB/day; x7 days = 730 TB; +30% headroom = about 950 TB. At 40 TB usable per broker, about 24 brokers. So disk, not CPU, sets the size, and tiered storage cuts it.
- **Network per broker:** 42 MB/s in + 84 MB/s replication out + 125 MB/s consumer out = about 250 MB/s, 2 Gbps on a 25 Gbps NIC. Fine even at 3x burst.
- **Partitions:** at about 10 MB/s each, 1 GB/s needs at least 100 partitions. So partitions are the unit of parallelism, sized at 2-3x consumer parallelism.
- **Page cache:** 42 MB/s x 60 s x 3 = about 7.5 GB per broker, inside 64 GB RAM. So caught-up consumers read from memory, not disk.

## Page 2. The architecture

```
 Producers (batch, compress, idempotent)    Consumers (groups, pull by offset)
       | produce(topic, partition, batch)          ^ fetch(offset) / commit
       v                                           |
 Broker cluster (3 AZs)
   Broker 1 (AZ-a)       Broker 2 (AZ-b)        Broker 3 (AZ-c)
   P0 leader  [seg]  <-- P0 follower fetches   P0 follower fetches
   P1 follower           P1 leader              P1 follower
   page cache, sendfile  group coordinator      txn coordinator
       ^ metadata push, heartbeats              | old segments
       |                                        v
 KRaft controller quorum (3, Raft)        Tiered storage (S3/GCS)
 metadata log, leader election, ISR       MirrorMaker -> DR region cluster
```

- **Producer client:** hashes key to partition, batches (linger.ms, batch.size), compresses, numbers batches.
- **Broker:** appends batches to segments, serves fetches with zero-copy, leader or follower per partition.
- **Partition log:** 1 GB segment files with a sparse offset index and a time index.
- **Replication manager:** followers pull; leader tracks the ISR (in-sync replicas) and high watermark.
- **KRaft controller:** 3-5 nodes running Raft over metadata; elects leaders, records ISR changes.
- **Group coordinator:** membership, rebalances and committed offsets in the internal consumer_offsets topic.
- **Transaction coordinator:** producer ids and epochs; writes commit or abort markers.
- **Log cleaner and tiered storage:** compaction; old segments moved to object storage.

**Flow A: produce with acks=all**
1. Producer sends a batch to the leader of hash(key) mod N with producer id and sequence.
2. Leader checks ACL, quota and sequence, appends to the page cache (no fsync per message).
3. Followers fetch the batch; their next fetch offset tells the leader how far they are.
4. When every ISR member has it (and ISR is at least 2), the high watermark advances and the producer gets the offset.
5. If ISR falls below 2, NOT_ENOUGH_REPLICAS; the producer retries with backoff.

**Flow B: consume in a group**
1. JoinGroup and SyncGroup give each member its partitions (cooperative sticky).
2. Long-poll Fetch from the committed offset; data up to the high watermark via sendfile.
3. Process, then commit offsets (at-least-once); missed heartbeats reassign partitions.

## Page 3. The core deep dives

### 1. ISR, high watermark and leader epochs
The leader only exposes offsets that every ISR member has: the high watermark is the minimum log end offset across the ISR. A follower that has not caught up for 30 s is dropped from the ISR, so one slow disk does not block all writes. min.insync.replicas=2 stops the ISR shrinking to a single copy that still takes writes. If the leader dies after appending a batch no follower fetched, that batch was never below the high watermark, so it was never acked; the new leader lacks it and the old leader truncates it on return, using the leader epoch checkpoint. Unclean leader election stays off: if only an out-of-sync replica survives, the partition goes offline rather than silently losing acked data.

### 2. Exactly-once is an effect, not delivery
Idempotent producer: each producer has an id and a sequence per partition; the leader remembers the last 5 batch sequences. Example: Shreya's order service sends batch seq 7, the ack times out, and it retries; the leader sees seq 7 again and returns the original offset instead of appending twice. Transactions extend this to read-process-write: the processor reads input, writes outputs to several partitions and adds its input offsets to the same transaction; commit writes markers to every partition. Consumers with read_committed skip aborted records. A paused zombie is fenced by the epoch bump (PRODUCER_FENCED). Sinks outside Kafka still need idempotent writes.

### 3. Throughput and consumer groups
Batching and compression cut requests; appends are sequential; caught-up reads come from page cache; sendfile copies file to socket without user space. Finding an offset: pick the segment by base offset, binary-search the sparse index (one entry per 4 KB), scan forward. In a group each partition has one owner. Cooperative sticky assignment revokes only partitions that must move, and static membership (group.instance.id) lets Sethu's 200 pods restart in a deploy without any rebalance.

**Data model:**
- **Record batch** (.log segment): base_offset, leader epoch, CRC, producer id, epoch, base sequence, records with delta offsets.
- **Offset index and time index:** sparse, memory-mapped; seek by offset or timestamp.
- **Committed offset:** key (group, topic, partition) in the consumer_offsets topic, 50 partitions by hash(group_id), compacted.
- **Partition metadata** (KRaft log): topic_id, partition, replicas, ISR, leader, leader epoch.
- **Producer state:** per partition, producer id, epoch and last 5 sequences, for dedup.

**Key APIs:**
- `Produce`: leader only; acks=all waits for the ISR; dedup by producer id and sequence.
- `Fetch`: used by followers and consumers; long polling; zero-copy.
- `JoinGroup / SyncGroup / Heartbeat`: group membership and rebalances.
- `OffsetCommit / OffsetFetch`: stored in the compacted offsets topic.
- `InitProducerId / AddPartitionsToTxn / EndTxn`: transactions, zombie fencing by epoch.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Disk:** tiered storage for topics over 2 days of retention; size-based caps; alerts at 70% and 85%.
- **Hot partition:** a mega-seller with 30% of traffic gets a finer key (seller plus order) or its own topic.
- **Partition count:** KRaft for metadata; a few thousand per broker, as failover time grows with them.
- **Adding partitions to a keyed topic:** hash mod N changes and breaks order, so over-provision up front or migrate to a new topic.
- **Moving partitions:** throttled reassignment; new replica joins the ISR before leadership moves.

**Failure modes:**
- **Broker crash:** controller fences it in seconds, elects new leaders from the ISR; produce p99 spikes briefly; no acked loss.
- **AZ lost:** each partition keeps 2 replicas, min ISR holds, controllers keep 2 of 3; capacity drops a third.
- **Controller quorum lost:** existing leaders keep serving, but no elections; a broker failure now means offline partitions. Page immediately.
- **Slow disk:** its followers drop from the ISR; move its leaders away.
- **Rebalance loop:** handler exceeds max.poll.interval.ms (5 min); fix the handler, use static membership.
- **Lag beyond retention:** OFFSET_OUT_OF_RANGE, reset per policy; alert on lag in seconds near retention.
- **Region lost:** fail over to the DR cluster with translated offsets; last few seconds may be missing.

**Trade-offs chosen:**
- **ISR with RF=3, min ISR 2, acks=all over majority Raft for data:** survives one failure with no acked loss and does not wait on slow replicas; Raft only for metadata.
- **Pull over push:** consumers set their own pace; natural backpressure.
- **Retain for time over delete on ack:** replay and many independent consumers; per-message acks go to a job queue on top.
- **Replicate across AZs over fsync per write:** orders of magnitude more throughput.
- **Async mirroring over a stretched cluster:** no WAN latency on every produce; a few seconds of RPO on region loss.

**What to measure:** under-replicated and under-min-ISR partitions (must be 0); offline partitions; exactly one active controller; ISR shrink rate; produce and fetch p99 per broker; consumer lag in seconds; bytes per partition (skew); disk use; quota throttle time; rebalance count and transaction abort rate.

## Page 5. Say it in the interview

> "I will treat this as a Kafka-style durable log, not a delete-on-ack queue: producers append, and many consumer groups read independently and can replay. Assume a million 1 KB messages a second, per-key ordering, at-least-once by default, and no loss after ack even if an AZ fails. I split each topic into partitions, each a segmented append-only log, replicated three ways across AZs with one leader. Producers hash the key to a partition and batch; with acks all and min in-sync replicas two, an ack means at least two copies. Followers pull, the leader tracks the in-sync set and a high watermark, and consumers read only committed data. A Raft controller quorum holds metadata and elects leaders. Consumer groups split partitions and commit offsets to a compacted topic."

**Key points to land:**
- A replicated, partitioned log: consuming does not delete, retention does.
- Order is per partition, so the key decides what is ordered; partitions are the unit of parallelism.
- Durability contract: RF=3 across AZs, acks=all, min ISR 2, unclean election off.
- Commit when all in-sync replicas have it; consumers read below the high watermark.
- Raft (KRaft) for metadata, ISR pull replication for data.
- Throughput: batching, compression, sequential I/O, page cache, sendfile.
- Exactly-once is an effect: idempotent producer plus transactions, idempotent sinks.
- Cooperative rebalancing and static membership avoid pauses.
- Watch under-replicated partitions and lag in seconds.

**Likely follow-ups:**
1. **No loss end to end?** acks=all with idempotence, RF=3 and min ISR 2, unclean election off, commit after processing, idempotent sinks, plus an audit of produced versus consumed counts.
2. **Delayed or retry queue?** Retry topics with fixed delays (retry-1m, retry-10m), then a dead-letter topic after N attempts.
3. **Strict global order?** A single partition, accepting tens of MB/s; usually per-entity order is what is really needed.
4. **Versus RabbitMQ or SQS?** Those are queues with per-message acks, delays and routing but little replay; Kafka is a log with replay, many groups and very high throughput.
5. **Why lag in seconds?** 1M messages can be 2 seconds or 3 hours; seconds map to the SLO and the retention deadline.

**Director layer:**
- **Cost drivers:** about 950 TB of disk (24-30 brokers), cross-AZ replication bytes that are billed, and tiered storage to shrink local disk.
- **Platform defaults:** acks=all and idempotence on, config linting in the client, partition budgets per tenant.
- **Team ownership:** the platform team runs clusters, quotas and ACLs; producer teams own keys and schemas; consumer teams own lag and idempotent processing.
- **Top risks:** hot partitions, data loss from acks=1, rebalance storms in deploys, full disks, too many partitions slowing failover.
