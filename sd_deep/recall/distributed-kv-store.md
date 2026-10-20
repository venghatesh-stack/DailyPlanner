# Distributed Key-Value Store (Dynamo-style): recall card

> **Hook:** Hash onto a ring → Write to N=3 → Hint for the down node → Version with vector clocks → Repair with Merkle trees

**P · Problem:** It's really an always-writable replicated store that trades consistency for availability and must detect and repair divergence.

**N · Numbers:**
1. 100 TB x 3 at 2 TB usable per node is 150 nodes, so storage, not CPU, sizes the cluster.
2. 1.5M replica writes/s become 200 MB/s of disk writes with compaction, so pick an LSM engine on NVMe.
3. About 1 billion keys per node x 10 bits is 1.25 GB of Bloom filters, so point reads skip most files.

**H · Hard part:** Never rejecting a write while replicas diverge, then knowing exactly what R and W do and do not guarantee.

**B · Boxes:** `Ring-aware client → Coordinator → N=3 replicas → WAL and memtable → SSTables with Bloom filters`

Side path: `Gossip → hinted handoff → read repair → Merkle anti-entropy` for convergence.

**D · Decisions:**
1. AP with tunable quorums over CP, because carts and sessions must always be writable.
2. Siblings by default over last-writer-wins, because LWW alone loses data silently.
3. Gossip over ZooKeeper, because there is no central dependency in the data path.

**F · Failures:**
1. Node crash → marked down in about 10 s; sloppy quorum keeps writes going and hints replay later.
2. Node down longer than gc_grace → blocked from rejoining without a full rebuild, to avoid resurrecting deletes.

**C · Close:** "So this is the Dynamo shopping-cart model: always writable beats always consistent. I partition with a consistent hash ring of virtual nodes and replicate to three nodes, with W=2 and R=2 so read and write sets overlap. A down replica's writes go to a stand-in with a hint. Vector clocks detect concurrent writes, which come back as siblings to merge. Read repair and Merkle trees converge the rest. Next I would add opt-in compare-and-set via Paxos."

**Quiz yourself:**
1. What does sloppy quorum break? → The overlap guarantee, if acks came from stand-in nodes.
2. How do two concurrent cart writes resolve? → Kept as siblings; the reader merges and writes back.
3. Why keep tombstones for 10 days? → Longer than repair, or a returning node resurrects deleted data.
