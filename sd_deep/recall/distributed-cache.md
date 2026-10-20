# Distributed Cache (Redis / Memcached cluster): recall card

> **Hook:** Hash to 16,384 slots → Lease on miss → Fill with jittered TTL → Delete on write via CDC → Fail over to replica

**P · Problem:** It's really a database shield, an in-memory key-value tier whose job is to keep the hit ratio high when things go wrong.

**N · Numbers:**
1. 20 TB / 64 GB per shard is about 320 shards, so memory, not CPU, sets the size.
2. 95% hits send 225k reads/s to the DB but 80% sends 900k/s, so failover speed and herd control matter most.
3. One 100 KB hot key at 50k/s is 5 GB/s, so near caching is required.

**H · Hard part:** Surviving the hit-ratio drop from node loss, expiry storms, hot keys and stale fills without melting the database.

**B · Boxes:** `App pod → Smart client → Hash slot → Shard primary → Primary DB`

Side path: `MySQL binlog → Kafka → Invalidation relay → cache deletes` in every region.

**D · Decisions:**
1. Hash slots over mod N, because ownership is explicit and movable and only moved slots lose locality.
2. Delete on write over update on write, because out-of-order updates cannot leave stale values.
3. Async replication over sync, because writes stay sub-millisecond and losing recent sets only causes misses.

**F · Failures:**
1. Primary fails → replica promoted in about 10-15 s; misses go to the gutter pool or the DB with coalescing.
2. Mass expiry or cold start → leases, TTL jitter and gradual warm-up keep the DB alive.

**C · Close:** "So this is a look-aside cache whose real job is shielding the database. I split keys into 16,384 hash slots over about 320 shards, route from smart clients, and give each shard a replica in another AZ with majority failover. Writes delete keys, driven by the change stream, and leases stop stale fills and herds. Hot keys get a near cache. Next I would add self-service keyspaces with quotas."

**Quiz yourself:**
1. What is the stale-set race? → A slow fill writes an old value after a delete; leases reject it.
2. Why replicas in other AZs? → Losing an AZ without them sends 1.5M reads/s to the DB.
3. LFU or LRU for a shared cache? → LFU, because it resists scan pollution.
