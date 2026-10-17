# Design a Distributed Key-Value Store (Dynamo-style): the 5-page summary

A Dynamo-style store chooses availability over consistency: writes must succeed even during partitions and node failures, so replicas may diverge and the system needs tools to detect and repair that. The single most important idea: it is a toolkit (consistent hashing, N/R/W quorums, sloppy quorum with hinted handoff, vector clocks, read repair, Merkle trees, gossip), and the interview is about knowing why each piece exists and what it does not guarantee.

## Page 1. The problem, scope and numbers

**Pitch:** a store for carts, sessions, preferences, feature flags and device state that never rejects a write, answers in single-digit milliseconds at p99.9, and scales by adding nodes. A relational primary with failover rejects writes during failover and cannot grow past one machine's write capacity.

**Who uses it:** product teams (simple API, low latency, clear conflict rules), SRE (automatic rebalancing, safe upgrades), finance (cost per GB on commodity hardware) and compliance (deletes that really delete).

**In scope:**
- **get(key):** one value, or several sibling values plus an opaque context (the vector clock).
- **put(key, value, context):** writes a version that descends from the context; delete writes a tombstone.
- **Tunable consistency:** N, R, W per table, overridable per request.
- **TTL per key**, for sessions.
- **Self-managing:** automatic partitioning, replication and rebalancing on membership change.
- **Conflict policy per table:** return siblings, last-writer-wins, or a CRDT type (counter, set).

**Out of scope:** multi-key transactions, secondary indexes and range scans, strong compare-and-set by default, values over 1 MB (object storage).

**Non-functional targets:**
- **Latency:** p99.9 under 10 ms for get and put; p50 under 2 ms.
- **Availability:** 99.99% of puts succeed; writes accepted during a single-AZ loss.
- **Consistency:** eventual by default; read-your-writes when R + W > N and no stand-in nodes were used. Sibling rate under 0.1% of reads.
- **Durability:** acknowledged on at least W replicas; WAL fsync batched every 10 ms, or per write for strict tables. Zero acknowledged writes lost.
- **Convergence:** within minutes after transient failures; within 24 h via full anti-entropy.

**Capacity math (100 TB logical, N=3, 1M gets/s, 500k puts/s, 2 KB values):**
- **Storage:** 100 TB x 3 = 300 TB; at 2 TB usable per node (50% of 4 TB NVMe) = 150 nodes. Storage, not CPU, sizes the cluster; the 50% leaves room for compaction and rebalancing.
- **Keys:** 100 TB / 2 KB = about 50 billion.
- **Reads:** 1M x 3 replicas = 3M replica reads/s, about 20k per node. Comfortable.
- **Writes:** 500k x 3 = 1.5M replica writes/s, about 10k per node, 20 MB/s; with about 10x compaction amplification, 200 MB/s of disk writes. So pick an LSM engine on NVMe; compaction is the hidden cost.
- **Network:** 1.5M x 2 KB = 3 GB/s of replication traffic, about 20 MB/s per node.
- **Bloom filters:** about 1 billion keys per node x 10 bits = 1.25 GB per node. Fits in 256 GB RAM, so point reads skip most files.

## Page 2. The architecture

```
        Clients (ring-aware library, or any node via LB)
                       |
                       v
   Coordinator (any node): hash(key) -> preference list [A, B, C]
   send to N=3, wait for W acks (put) or R replies (get)
          |                  |                  |
          v                  v                  v
   Node A (AZ1)       Node B (AZ2)       Node D (AZ3)  <- hint for C (down)
   WAL, memtable      WAL, memtable      hinted store
   SSTables + Bloom   SSTables + Bloom
          ^                                     ^
          +------ gossip every 1 s -------------+
   Anti-entropy: Merkle tree per key range, compared between replicas
   Ring of virtual nodes: A1 . C1 . B1 . D1 . A2 . B2 ... (2^64 space)
```

- **Client library:** holds the ring, routes to a replica, retries with jitter, carries contexts.
- **Coordinator:** any node; fans out to N replicas, waits for W or R, does read repair.
- **Partitioner:** Murmur3 64-bit token; about 256 virtual nodes per server; AZ-aware placement.
- **LSM storage engine:** WAL, memtable, SSTables with Bloom filters; compaction; tombstones and TTL.
- **Gossip and failure detector:** 1-3 random peers per second; phi-accrual marks nodes suspect.
- **Hinted handoff:** keeps writes for a down replica and replays them; 3-hour window.
- **Anti-entropy:** Merkle trees per token range; streams only differing ranges.
- **Admin and rebalancer:** adds and removes nodes, streams ranges, tracks repair status.

**Flow A: put**
1. Coordinator increments its own entry in the vector clock from the client's context.
2. Writes locally (WAL plus memtable) and sends to the other replicas in parallel.
3. A down replica's write goes to the next healthy node with a hint naming the owner (sloppy quorum).
4. Success after W acks; otherwise a retryable error, and the client retries with the same context.

**Flow B: get**
1. Coordinator asks the replicas and waits for R answers.
2. If one version descends from all others, return it; else return all concurrent versions as siblings.
3. Push the newest version to stale replicas in the background (read repair).

## Page 3. The core deep dives

### 1. Quorums, and what sloppy quorum breaks
With N=3, W=2, R=2, any read set overlaps any write set in at least one node, because 2 + 2 > 3, and latency is set by the fastest replicas. If node C is down, the write goes to D with a hint "this belongs to C", so writes never fail. The catch: if both acks came from stand-ins, a later R=2 read on the true owners can miss the write. R + W > N only guarantees overlap on the same node set. Tables that need it opt in to strict quorum, which fails the write instead. Quorum is also not linearizable: read repair is asynchronous, so two concurrent reads during a write can see new then old.

### 2. Vector clocks and siblings
A vector clock maps node id to a counter. A descends from B if every counter in A is at least B's; otherwise they are concurrent. Example: Shreya's cart is at {A:1}. During a partition, Shreya adds a book via A, giving {A:2}, while Sethu, on a shared account, adds a pen via B, giving {A:1, B:1}. Neither descends from the other, so both are kept as siblings. The next reader merges them (cart union) and writes back with the merged context. Union merges can resurrect deleted items, so use an OR-Set CRDT, which tags removes so they win. Clocks are pruned beyond 10 entries, accepting rare false conflicts. Last-writer-wins by wall clock can silently drop a newer write, so it is used only for caches.

### 3. Three layers of convergence
Hinted handoff fixes short outages: when C returns, D replays its hints and deletes them. Read repair fixes keys that are read. Merkle-tree anti-entropy fixes the rest: each replica hashes a token range into a binary tree (depth 15, 32k leaves); equal roots mean done, otherwise recurse and stream only mismatched leaves, so cost follows the differences, not the data. Tombstones are kept for gc_grace (10 days), longer than the repair interval, or a returning node resurrects deleted data. Phi-accrual detection marks a node down when phi exceeds 8, adapting to jitter instead of using a fixed timeout.

**Data model:**
- **Record** (LSM SSTable): key, value or tombstone, vector clock, write_ts, ttl_expiry; sorted by token then key; partitioned by token range; siblings stored as versions.
- **Ring state** (gossiped): node_id, AZ, 256 tokens, status (joining, normal, leaving, down), heartbeat generation.
- **Hint**: (target_node_id, created_ts), key, value, clock; dropped after 3 hours, then Merkle repair takes over.

**Key APIs:**
- `GET /v1/{table}/{key}?r=2`: several values means siblings; merge and write back with the context.
- `PUT /v1/{table}/{key}?w=2`: the context makes the write descend; omitting it may create a sibling.
- `DELETE /v1/{table}/{key}`: tombstone, purged after gc_grace once repair has run.
- `RPC Replica.Write`: hint_for set when a node stands in for a down replica.
- `RPC AntiEntropy.CompareTree`: walk Merkle trees; only mismatched leaves stream.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Storage:** add nodes; virtual nodes mean only about 1/N of keys move, from many sources at once.
- **Rebalance traffic:** add one node at a time and throttle streaming (for example 200 Mbps per node).
- **Compaction:** keep disks at 50%; alert on pending compaction bytes; apply write backpressure.
- **Hot keys:** client cache with short TTL, R=1 across replicas, counters split into sub-keys summed on read.
- **Tail latency:** speculative retry to another replica after p99; route away from slow nodes.

**Failure modes:**
- **Node crash:** marked down in about 10 s; sloppy quorum keeps writes going; hints replay; no client errors at W=2.
- **AZ outage:** each key still has 2 replicas in other AZs; W=2 and R=2 continue; repair after recovery.
- **Partition between AZs:** both sides accept writes; vector clocks reconcile after heal; strict tables fail on the minority side.
- **Disk failure or corruption:** block checksums; read from other replicas; a new node streams its ranges.
- **Node down longer than gc_grace:** blocked from rejoining without a full rebuild, to avoid resurrection.
- **Read-repair storm after a long outage:** Merkle repair first, node stays "joining" until caught up.

**Trade-offs chosen:**
- **AP with tunable quorums over CP:** always-writable carts and sessions; CP needs go to strict quorum or another store.
- **Siblings by default, LWW for caches, CRDTs for counters and sets:** LWW alone loses data silently.
- **Sloppy quorum by default, strict opt-in:** availability first for the common case.
- **Gossip over ZooKeeper:** no central dependency in the data path; permanent changes are explicit.
- **LSM (RocksDB) over B-tree:** replication triples writes; Bloom filters keep point reads fast.
- **Ring-aware client over load balancer:** saves a hop; Dynamo measured lower tail latency.

**What to measure:** get and put p50/p99/p99.9 per table; unavailable and timeout errors by consistency level; sibling rate; hint backlog size and age; read repair and Merkle mismatch counts; pending compaction bytes and SSTables per read; tombstones per read; ring balance; clock skew (alert over 50 ms).

## Page 5. Say it in the interview

> "I will confirm this is a simple get and put store with small values where availability beats strict consistency, the Dynamo shopping-cart model, at around a million reads a second and 100 TB. I partition with a consistent hash ring using virtual nodes and replicate each key to the next three distinct nodes. Any node can coordinate; with N=3, W=2, R=2 the read and write sets overlap. When a replica is down, I write to the next healthy node with a hint and hand it back later, so writes never fail. Concurrent writes can happen, so every value carries a vector clock and divergent versions come back as siblings to merge. Each node runs an LSM tree. Then I defend convergence with read repair and Merkle trees, gossip membership, hot keys, and what R and W do not buy you."

**Key points to land:**
- The Dynamo shopping cart: always writable beats always consistent.
- Consistent hashing with virtual nodes: only about 1/N of keys move; recovery spreads across peers.
- N=3, W=2, R=2: overlapping quorums, latency set by the fastest replicas.
- Sloppy quorum and hinted handoff keep writes flowing but break the overlap guarantee.
- Vector clocks detect concurrency; siblings merged by the client or by CRDTs.
- Three convergence layers: hinted handoff, read repair, Merkle trees.
- Gossip plus phi-accrual for membership; permanent changes are explicit.
- LSM storage because replication multiplies writes.
- Size by storage: 100 TB x 3 at 50% disk is about 150 nodes.
- Know where not to use it: balances, inventory, uniqueness constraints.

**Likely follow-ups:**
1. **Strong compare-and-set for some keys?** A Paxos round among the key's replicas, like Cassandra lightweight transactions: about four round trips and unavailable without a majority, so only for small critical tables.
2. **Multi-region?** N=3 per region with LOCAL_QUORUM, async shipping across regions, conflicts via vector clocks or CRDTs; global quorum adds 100 ms or more.
3. **Why is quorum not linearizable?** Writes land on replicas at different times and read repair is async, so concurrent reads can see new then old.
4. **How does DynamoDB differ?** It uses Multi-Paxos leaders per partition with strongly consistent reads available: closer to CP per partition than original Dynamo.
5. **Backups?** Per-node SSTable snapshots via hard links (files are immutable) shipped to object storage, plus commit-log archiving for point-in-time recovery.

**Director layer:**
- **Cost drivers:** about 150 NVMe nodes at 50% disk use, 3x replication, and about 10x compaction write amplification.
- **Team ownership:** a small platform team runs the store; product teams own their tables' N, R, W and conflict policy.
- **Adoption rule:** default conflict policies per table, docs and sibling-rate dashboards, because teams wrongly assume strong consistency.
- **Top risks:** misused consistency, hot keys, correlated failures in one rack or AZ, tombstone resurrection after long partitions.
