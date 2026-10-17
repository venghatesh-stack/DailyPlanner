# Design a caching strategy for a read-heavy API (product catalog scale): the 5-page summary

A product catalog API takes 500k reads/s at peak against only 5k writes/s, and it is cheap and fast only if almost every read is answered from memory. The single most important idea: the database is sized for misses, not for traffic, so design layered cache-aside with explicit staleness budgets, and treat stampedes, hot keys and a cold cache as outage triggers, not cache details.

## Page 1. The problem, scope and numbers

**Pitch:** serve product and catalog reads fast and cheaply through sale spikes of 10-20x, without customers seeing a wrong price or stock at the moment it matters.

**Who uses it:** shoppers on mobile (page in under a second on 4G), sellers editing prices (visible in seconds), on-call SRE (which layer is failing, levers to shed or warm), finance (lower DB and egress spend).

**In scope:**
- **Single read:** `GET /products/{id}` from the fastest layer holding a fresh-enough copy.
- **Batch read:** one MGET per Redis shard; misses filled with one DB query per shard.
- **Invalidation:** a write deletes the Redis key and broadcasts an L1 eviction to all API pods.
- **HTTP revalidation:** ETag and Cache-Control so clients and the CDN get 304s.
- **Negative caching:** a not-found id is cached for 30 s.
- **Admin and hot keys:** purge by key or tag, pre-warm before a sale, top-K hot keys every 5 s.

**Out of scope:** search result caching, personalised recommendations, multi-region active-active writes, inventory reservation at checkout. The cache is never a source of truth.

**Non-functional targets:**
- **Latency:** API p50 under 5 ms, p99 under 50 ms; Redis GET p99 under 2 ms.
- **Availability:** 99.99% for reads; reads continue, possibly stale, when Redis is down.
- **Freshness:** descriptive fields at most 60 s stale; price and stock at most 5 s stale p99; checkout always reads the authoritative price.
- **Origin protection:** DB read QPS under 15k, even after a full cache flush.
- **Durability:** not required; losing the cache must never lose data.

**Capacity math (50M products, 4 KB payload, 1.5 KB compressed; top 2M items take 90% of reads):**
- **Layer by layer:** the CDN absorbs 40%, so 500k x 0.6 = 300k/s reach pods. L1 hits half, so 150k/s reach Redis. Redis hits 95%, so 150k x 0.05 = 7.5k/s reach MySQL, well under its 30k/s safe capacity. So each layer must cut traffic by about 10x.
- **Redis memory:** caching the top 20M items = 30 GB, x1.5 overhead = 45 GB, 90 GB with replicas. The long tail adds little hit ratio, so size from the hot set, not the dataset.
- **Redis ops:** 150k/s at 100k ops/s per primary means 2 shards by ops; run 12 primaries plus replicas for headroom.
- **Bandwidth:** 150k/s x 1.5 KB = 225 MB/s, about 1.8 Gbps. So store compressed values.
- **L1 per pod:** 50k entries x 4 KB = 200 MB of heap. Cheap enough to run on every pod.
- **Cold cache:** 300k/s on a DB rated for 30k/s is a 10x overload. So refill must be throttled; this number drives the warm-up and load-shedding design.

## Page 2. The architecture

```
 Mobile / web clients  (ETag, Cache-Control)
      |
      v
 CDN (anonymous GETs, 30 s) --miss--> API pods: L1 near cache (5-10 s TTL),
                                       single-flight loader, cache client lib
                                         |  GET/MGET           |  miss
                                         v                     v (bulkhead)
                         Redis Cluster 12 x (P+R)      MySQL read replicas
                                         ^ DEL                 ^ replication
 Seller -> Catalog svc -> MySQL primary -+---- binlog ---------+
               |                          |
               +--- DEL key + publish     v
                                     CDC consumer -> Kafka "invalidations"
                                          |-> L1 pub/sub evictions
                                          +-> CDN purge (rate-limited)
 Hot-key detector (Count-Min + top-K) <- sampled GETs; hot list every 5 s
```

- **CDN:** caches anonymous GETs by URL; stale-while-revalidate; revalidates by ETag.
- **L1 near cache:** in-process W-TinyLFU (Caffeine) per pod; absorbs hot keys, zero hops.
- **Cache client library:** cache-aside, versioned keys, TTL jitter, single-flight, breaker.
- **Redis Cluster:** shared cache; 16,384 hash slots on 12 primaries; allkeys-lfu eviction.
- **MySQL:** source of truth; replicas serve misses behind a bounded connection pool.
- **CDC consumer:** tails the binlog (Debezium); second delete, L1 fan-out, CDN purge.
- **Hot-key detector:** samples GETs, publishes the top 1,000 keys for replication.
- **Warm-up job:** preloads top keys before sales and after a flush, at a DB-safe rate.

**Flow A: read with a miss**
1. GET /products/42; CDN misses (logged-in); pod checks L1: miss.
2. Library GETs `p:v3:42` from Redis with a 20 ms timeout: miss.
3. Single-flight makes one thread the loader; the rest wait on its result.
4. Across pods the loader takes `SET p:v3:42:lock NX PX 3000`; losers serve stale or poll.
5. Loader reads a replica, SETs with TTL 600 s plus 0-60 s jitter, fills L1 for 5 s.

**Flow B: write and invalidate**
1. Seller changes the price; the row commits to MySQL as version 18.
2. Catalog service deletes `p:v3:42` and publishes {id 42, ver 18}.
3. CDC re-deletes the key 500 ms later; all pods evict id 42 from L1; CDN purge is queued.

## Page 3. The core deep dives

### 1. Cache-aside with delete-on-write
The app owns loading and invalidation, so a cache failure costs latency, not correctness. On a write, delete the key rather than set it: deletes are idempotent and immune to out-of-order writers, and the next read loads the latest row. The TTL (10 minutes plus jitter in Redis) is the backstop that bounds every invalidation bug. Write-through and write-behind are rejected: writes are rare, and write-behind trades durability for latency, which is never acceptable for price or stock.

### 2. The stale-set race and double delete
Shreya's read misses and loads version 17 from a lagging replica. Sethu, a seller, commits version 18 and deletes the key. Shreya's loader then SETs version 17: the cache is now wrong until TTL. Three defences: the CDC consumer deletes again 500 ms after the binlog event; a Lua script sets only if the incoming version is at least the stored one; and the TTL is the final bound. For a writer's own reads, route that session to the primary for 2 s after a write.

### 3. Stampede protection
When a hot key expires during a sale, thousands of requests miss at once and all hit MySQL. Layer the fixes: single-flight per pod (cheap, in-process), a Redis lock with a 3 s lease across pods, and XFetch, a probabilistic early refresh where each reader refreshes early with a probability that rises as expiry nears, so the key rarely actually expires. L1 keeps a soft-expired copy to serve while one loader refreshes, and TTLs get plus or minus 10% jitter so keys loaded together do not expire together. Together these cap DB loads for any key to about one per refresh interval.

### 4. Hot keys
One key lives in one slot on one shard, so sharding cannot split it. A product at 200k QPS is absorbed mostly by L1: 200 pods each reloading every 5 s is about 40 Redis reads/s. The detector (a Count-Min Sketch plus a top-K heap) flags it within 5 s and the client writes it to 8 suffixed copies (`k#0` to `k#7`) on different slots; readers pick one at random. Invalidation deletes all 8.

**Data model:**
- **Product cache entry** (Redis): key `p:v3:{id}`, slot = CRC16(key) mod 16384; compressed protobuf with version and soft-expiry time. The v3 in the key makes a format change a namespace switch.
- **Loader lock** (Redis): `p:v3:{id}:lock`, owner token, hash tag {id} so it shares the value's slot.
- **Negative entry** (Redis): a NULL marker with 30 s TTL for ids that do not exist.
- **Product row** (MySQL): PK id, sharded by id; version increments on every update (ETag, set guards).
- **Invalidation event** (Kafka, 48 partitions): partitioned by id for per-id order.

**Key APIs:**
- `GET /v1/products/{id}`: 200 with ETag "v18" and max-age=30, or 304; price is advisory.
- `GET /v1/products?ids=`: up to 50 ids, one MGET per shard.
- `PUT /v1/products/{id}`: optimistic concurrency on expected_version; deletes the key on commit.
- `POST /internal/cache/warm`: preload ids at a capped rate, e.g. 2,000/s.
- `POST /internal/cache/purge`: by keys or by tag (e.g. a brand), rate-limited.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot shard:** L1 plus 8-way replication of the top 1,000 keys; more pods means more L1 capacity.
- **Reads:** push more anonymous traffic to the CDN, add shards (resharding moves slots), add replica reads only for the hottest shards.
- **Invalidations:** they are deletes keyed by id, so they shard naturally; batch L1 broadcasts and rate-limit CDN purges.
- **Big values:** a product with 300 variants (500 KB) blocks Redis's single thread; cap values near 100 KB, split core from variants, alert on big keys.
- **Cache penetration:** scrapers asking for missing ids get negative caching, a Bloom filter of valid ids and per-client rate limits.

**Failure modes:**
- **One Redis primary dies:** a replica is promoted in 1-2 s; the breaker and L1 cover the gap; unreplicated sets are lost, which is fine for a cache.
- **Whole Redis cluster down:** the breaker opens (50% errors over 5 s, for 10 s); L1 serves stale entries up to 5 minutes old; misses go to MySQL only through a 200-connection bulkhead and a token bucket; low-priority callers are shed first; the CDN serves stale-if-error.
- **Cold cache before a sale:** warm-up loads the top 2M keys at a capped rate; admission control limits DB loads per pod.
- **CDC consumer lags 10 minutes:** app deletes still work; out-of-band writes stay stale until TTL; page on lag and scale by partition.
- **MySQL replica lag of 30 s:** misses can repopulate old rows; read recently written ids from the primary or use the version-guarded set.
- **Bad deploy changes the payload format:** the versioned namespace isolates it; rollback lands on a still-warm namespace.

**Trade-offs chosen:**
- **Delete over update on write:** idempotent and order-insensitive.
- **CDN + L1 + Redis over a single tier:** each layer solves a different problem (geography, hot keys, shared working set), at the cost of more staleness windows to reason about.
- **10-minute TTL plus event invalidation over no TTL:** a lost invalidation self-heals.
- **Redis over Memcached:** replication, Lua version guards, NX locks and LFU eviction.
- **App delete plus CDC over either alone:** low lag plus a net for out-of-band writes.
- **Serve stale and shed over full fall-through:** fall-through overloads MySQL 10x.

**What to measure:** hit ratio per layer and combined (target 97% or more), origin QPS (under 15k) and pool saturation, p99 per layer, invalidation lag p99 under 2 s, CDC lag, evicted keys per second, top-K keys, stale serves and breaker state, and the price mismatch rate at add-to-cart (under 0.01% of orders).

## Page 5. Say it in the interview

> "I will start with the shape of the traffic: 500k reads a second at peak and 5k writes, with Zipf skew where 4% of items take 90% of reads. Descriptive fields can be a minute stale; price and stock must be within 5 seconds or verified at checkout. Plain cache-aside on Redis breaks three ways: hot keys, stampedes on expiry and a cold start. So I use four layers: a CDN for anonymous traffic, an in-process near cache for hot keys, Redis Cluster as the shared cache, and MySQL behind a single-flight loader and a bulkhead. That turns 500k reads into about 7.5k database reads. Writes go to MySQL and delete the key, with CDC as a second delete. When Redis fails I serve stale and shed load, because MySQL is sized for misses."

**Key points to land:**
- State read/write ratio, skew and staleness per field class before drawing.
- Each layer should cut traffic to the next by about 10x.
- Cache-aside, delete on write, TTL with jitter as the safety bound.
- Stampede protection is mandatory: single-flight, lock, early refresh, serve stale.
- One key lives on one shard: hot keys need L1 and key replication.
- The cache's failure plan is the database's survival plan: breakers, bulkheads, capped refill.
- CDC is the second invalidation path for out-of-band writes and the stale-set race.
- Never trust the cache at the point of commitment: re-read price at checkout.
- Measure hit ratio per layer, origin QPS and invalidation lag, not just latency.

**Likely follow-ups:**
1. **One product suddenly gets 200k QPS?** L1 absorbs it (200 pods at 5 s TTL is about 40 Redis reads/s); the CDN takes anonymous traffic; the detector flips it to 8-way replication within 5 s.
2. **How is a price change visible within 5 s?** Delete-on-write is sub-second; pub/sub evicts L1 with a 5 s TTL as the bound; price is cached at the CDN with max-age=5 or not at all; checkout re-reads anyway.
3. **The cache is empty at the start of a sale?** Warm the expected top 2M keys 30 minutes before at 5k/s; if it happens anyway, admission control, single-flight and shedding hold MySQL up.
4. **Why not cache whole pages?** Logged-in pages are personalised and page invalidation needs every page a product appears on; object caching shares one entry and keeps invalidation key-based.
5. **Multiple regions?** Each region has its own Redis and L1; writes stay in the home region and invalidations replicate via Kafka MirrorMaker, with that lag added to remote staleness budgets.

**Director layer:**
- **Cost drivers:** Redis RAM (budget about 1.5 TB across the cluster), CDN egress, and MySQL replicas, which this design cuts by at least 5x.
- **Phasing:** cache-aside on Redis with delete-on-write and TTL jitter first; then L1, stampede protection and breakers; then CDC invalidation, hot-key replication and pre-sale warm-up.
- **Team ownership:** platform/SRE own the cache tier, client library and runbooks (flush, warm-up, hot keys); catalog owns writes and invalidation events; checkout owns authoritative price reads.
- **Top risks:** stampede on a hot key during a sale, customers seeing an old price, a cache loss melting the database, and a hot key saturating one shard.
