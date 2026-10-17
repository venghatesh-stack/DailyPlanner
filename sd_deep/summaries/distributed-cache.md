# Design a Distributed Cache (Redis / Memcached cluster): the 5-page summary

A distributed cache is an in-memory key-value tier that absorbs most reads so the databases survive, which makes it both a speed system and a reliability dependency. The single most important idea: the cache's real job is shielding the database, so design for the moment the hit ratio drops (node loss, expiry storms, hot keys, stale fills), not only for the happy path.

## Page 1. The problem, scope and numbers

**Pitch:** a shared, reliable caching platform that serves product, pricing, catalog and session reads in about a millisecond, absorbs at least 95% of read traffic, and fails without melting the database.

**Who uses it:** service developers (simple fast API, safe defaults), DBAs (no stampedes), platform SRE (provisioning, failover, resharding), finance (memory cost and chargeback) and security (TLS, ACLs).

**In scope:**
- **Key-value ops:** GET, SET with TTL and NX/XX, DEL, MGET per shard, INCR, EXPIRE; Redis types optionally.
- **Partitioning:** 16,384 hash slots with online slot migration.
- **Replication and failover:** primary plus 1-2 replicas in other AZs; automatic failover with epochs.
- **Memory management:** maxmemory per node, LFU or LRU eviction, TTL expiry.
- **Client library:** smart routing, pooling, pipelining, timeouts, circuit breaker, near cache, single-flight fills.
- **Invalidation:** database change stream (CDC) to cache deletes, in every region.

**Out of scope:** being the system of record (orders, payments), cross-shard transactions, full-page CDN caching, synchronous cross-region replication, a new storage engine.

**Non-functional targets:**
- **Latency:** p50 under 0.3 ms, p99 under 1 ms server-side; client p99 under 3 ms in the same AZ.
- **Availability:** 99.99%; failover under 15 s; no outage from one AZ loss.
- **Consistency:** eventual; invalidation lag p99 under 1 s in-region, under 5 s cross-region; TTL as backstop.
- **Durability:** not needed for pure cache keyspaces; sessions use replicas plus optional AOF every second.

**Capacity math (5M ops/s peak: 4.5M reads, 0.5M writes; 20 TB of data):**
- **Throughput:** 5M / 80k ops/s per shard = about 63 shards.
- **Memory:** 20 TB / 64 GB per shard = about 320 shards, plus 320 replicas = 640 processes on 128 GB hosts. Memory, not CPU, sets the size.
- **Bandwidth:** 4.5M x 1 KB = 4.5 GB/s overall, only 14 MB/s per primary. But one 100 KB hot key at 50k/s is 5 GB/s, which no node can serve, so near caching is required.
- **Database exposure:** at 95% hits the DB sees 225k reads/s; at 80% it sees 900k/s, four times more. So failover speed and herd control matter more than raw cache speed.
- **Node loss:** one of 320 shards gone = about 14k extra DB reads/s, manageable; an AZ without replicas = 1.5M/s, catastrophic. So replicas in other AZs are mandatory.
- **Connections:** 20k pods x 320 shards = 6.4M connections. Too many, so use a proxy tier or per-host sharing to get about 50k.

## Page 2. The architecture

```
 App pods (catalog, pricing, sessions)
   cache client: slot map, pools, pipelining, near cache 1-5 s, leases
      | GET/SET by slot                | miss -> load
      v                                v
 Optional proxy tier (mcrouter)    Primary DB (MySQL) -> CDC binlog -> Kafka
      |                                                      | deletes
      v                                                      v
 Cache cluster: 16,384 slots over N shards  <----------------+
   Shard 1: P(AZ-a) -> R(AZ-b)    Shard 2: P(AZ-b) -> R(AZ-c)  ...
      ^ slot map, failover, migration       ^ fallback when a shard is down
      |                                     |
 Cluster manager (quorum, epochs)       Gutter pool (spares, short TTL)
 Invalidation relay -> other regions' cache clusters (async)
```

- **Smart client:** hashes keys to slots, follows MOVED/ASK, pools, retries, near cache, single-flight.
- **Proxy tier:** optional; multiplexes connections for huge pod counts or thin clients.
- **Shard primary:** in-memory engine; enforces maxmemory, eviction and TTLs; replicates.
- **Replicas:** asynchronous copies in other AZs; promotion candidates; optional reads.
- **Cluster manager:** health checks, majority-based failover with config epochs, publishes the slot map.
- **Rebalancer:** moves slots online to balance memory and ops.
- **Invalidation pipeline:** binlog via Kafka, maps rows to keys, deletes in every region.
- **Gutter pool:** spare servers take a failed shard's traffic with short TTLs.
- **Hot-key detector:** samples access counts, turns on near caching or key replication.

**Flow A: cache-aside read with herd protection**
1. getOrLoad("product:123"): slot = CRC16(key) mod 16384, GET from the owning primary.
2. Hit: return (p99 under 1 ms).
3. Miss: take a lease with SET NX PX 3000. Only the holder reads the DB; others wait 20 ms and retry, or get stale data.
4. Holder sets the value with TTL 300 s plus 0-30 s jitter, only if its lease still exists.

**Flow B: write and invalidation**
1. Service commits the new price in MySQL and may delete the key at once.
2. CDC publishes the row change; the consumer deletes the key in each region.
3. The delete also clears any lease, so an in-flight filler cannot write the old price back.

## Page 3. The core deep dives

### 1. The stale-set race and leases
The race: reader Shreya misses and reads price 999 from the DB; then Sethu updates the price to 899 and deletes the key; then Shreya's slow request sets 999. The cache now holds a stale price until TTL. The fix is the Facebook Memcache lease idea: a miss takes a lease token, and the fill is a compare-and-set that only writes if the lease still matches. Every delete also deletes the lease, so Shreya's fill is rejected. The same lease is single-flight: when a popular key expires, one request rebuilds it and the rest wait 10-50 ms or get stale data. TTL jitter stops many keys expiring together; very hot keys refresh early.

### 2. Partitioning, failover and split brain
Hash slots: slot = CRC16(key) mod 16,384; hash tags like {user:42} put related keys in one slot for multi-key ops. Slots move online: the source is MIGRATING, the target IMPORTING, keys move in batches, and a missing key gets an ASK redirect; at the end a new epoch makes clients take MOVED. Only moved slots are affected. Failover: a primary silent for node-timeout (for example 5 s) is marked PFAIL; a majority agrees it is FAIL; the replica with the highest replication offset is promoted and bumps the config epoch. A primary isolated in a minority stops taking writes (min-replicas-to-write), and clients follow the higher epoch. Unreplicated writes are lost, which for a cache only means misses.

### 3. Memory and hot keys
Exact LRU needs a list update per access. Redis samples 5-10 keys and evicts the worst from a pool; LFU uses an 8-bit logarithmic counter that decays. LFU resists scan pollution, so it suits shared caches; LRU suits sessions. Hot keys: a flash-sale product at 500k reads/s gets a near cache in each pod (1-2 s TTL), and known hot keys are copied as key#0 to key#7 across shards and read at random.

**Data model:**
- **Cache entry:** key keyspace:entity:id, value (compressed over 1 KB), expire_at, LFU counter, optional version; slot = CRC16(key or hashtag) mod 16384.
- **Slot map:** slot range, primary, replicas, config_epoch; cached in clients, refreshed on MOVED.
- **Lease:** lock:{key} with a token, PX 3000, same hash tag so it lives on the key's shard.
- **Invalidation event:** Kafka, keyed by cache key; table, primary_key, cache_keys, commit_ts.
- **Keyspace config:** team, memory quota, eviction policy, default TTL, replicas, ACL.

**Key APIs:**
- `GET key`: O(1), routed by slot; a replica can serve in READONLY mode.
- `SET key value EX 300 NX`: NX for leases; TTL required by policy.
- `UNLINK key`: frees big values asynchronously.
- `client.getOrLoad(key, loader, ttl)`: lease, compare-and-set fill, jitter.
- `POST /v1/keyspaces`: self-service provisioning and quotas.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Memory:** add shards by migrating slots in small, throttled batches; pre-scale before sales.
- **Single-thread CPU per shard:** keep under 60% CPU; spread hot keys with near cache and replication.
- **Connections:** proxy tier or per-host sharing.
- **Big keys:** 1 MB value cap, UNLINK, split into chunks, big-key scanner.
- **Database on misses:** coalescing, gutter pool and DB-side concurrency limits.

**Failure modes:**
- **Primary fails:** replica promoted in about 10-15 s; breakers open; misses go to gutter or DB with coalescing.
- **AZ lost:** primaries there fail over to other AZs; the fleet is sized to run on two AZs.
- **Partition:** the majority promotes; the isolated primary stops writing; clients converge on the higher epoch.
- **CDC lag:** stale values last longer; TTL limits damage; critical reads such as checkout bypass the cache.
- **Mass expiry or cold start:** leases, jitter, warm-up from access logs and gradual ramp keep the DB alive.
- **Runaway keyspace:** evictions hit neighbours; per-keyspace quotas or a separate cluster contain it.
- **Retry storm:** short timeouts, one jittered retry for reads, none for INCR.

**Trade-offs chosen:**
- **Redis cluster for most, Memcached for huge plain KV pools:** rich types versus multi-threaded efficiency.
- **Hash slots over mod N:** explicit, movable ownership; only moved slots lose locality.
- **Smart clients over proxy by default:** no extra hop; proxy only for connection counts.
- **Delete on write over update on write:** no out-of-order stale updates; leases stop stale fills.
- **Async replication over sync:** sub-millisecond writes; losing recent sets only causes misses.
- **Near cache for hot keys:** biggest relief at the cost of 1-2 s staleness.

**What to measure:** hit ratio per keyspace and the absolute miss QPS reaching the DB; p99 per shard and client timeouts; CPU per shard; memory, fragmentation and evictions; replication lag; failovers and uncovered slots; hot and big keys; invalidation lag per region; DB QPS for cache-backed queries.

## Page 5. Say it in the interview

> "This is a look-aside, in-memory cache in front of databases: about 5 million ops a second, 20 TB of hot data, sub-millisecond p99, eventual consistency with bounded staleness, and it must survive a node or AZ loss without hurting the database. One Redis node runs out of memory and is a single point of failure. So I split the key space into 16,384 hash slots over a few hundred shards, route by slot from smart clients, and give each shard a primary plus a replica in another AZ with automatic failover. Memory is bounded with LFU eviction and jittered TTLs. Apps use cache-aside: on a miss load and set; on a write update the database and delete the key, driven by the change stream. Then I defend hot keys, herds, the stale-set race, and the real risk: the database melting when the hit rate drops."

**Key points to land:**
- The cache's job is shielding the database; plan for the hit-ratio drop.
- Hash slots (16,384, CRC16) or consistent hashing: scaling moves only about 1/N of keys.
- Primary plus async replica in another AZ; majority failover with epochs in 10-15 s.
- Delete on write, CDC invalidation, and leases against the stale-set race.
- Herds: single-flight, stale-while-revalidate, TTL jitter, DB concurrency limits.
- Hot keys: near cache with 1-2 s TTL, key replication, continuous detection.
- Memory: sampled LFU or LRU, TTL on everything, headroom for fragmentation and fork.
- Isolation: 50 ms timeouts, one jittered retry, circuit breakers, gutter pool.
- Sizing is memory-bound: 20 TB / 64 GB is about 320 shards.

**Likely follow-ups:**
1. **Consistency across regions?** Each region has its own cache; CDC events delete keys in every region; reads needing read-your-writes go to the home region.
2. **When not to cache?** When data changes as often as it is read, when strong consistency is needed (inventory at checkout), or the working set is nearly the whole data set.
3. **Resize during a sale?** Pre-scale; otherwise move slots in small throttled batches while watching per-shard latency.
4. **Which persistence?** None for pure caches; for sessions, AOF every second on replicas only, accepting up to 1 s of loss.
5. **One team evicting another?** Per-keyspace memory quotas, prefixes and ACLs; noisy keyspaces get their own cluster.

**Director layer:**
- **Cost drivers:** RAM is 10-30x the cost of SSD per GB, so 640 processes on 128 GB hosts, 60-80% memory utilisation, chargeback per team, curated TTL-bound data.
- **Phasing:** standard client library and cache-aside first; then CDC invalidation, hot-key tooling and self-service keyspaces.
- **Team ownership:** platform SRE owns clusters, failover and resharding; service teams own keyspaces, TTLs and loaders; DBAs own admission control.
- **Top risks:** miss storms melting the database, stale data from fill races, hot keys saturating a shard, big keys, split brain.
