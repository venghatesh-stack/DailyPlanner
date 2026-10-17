# Design cache invalidation for frequently updated content: the 5-page summary

When prices, stock and banners change thousands of times a second, a cache is only useful if invalidation is fast, complete and correct in every layer. The key idea: split data by change rate, drive invalidation from the database log (CDC), and make every cache write version-aware so an old value can never overwrite a new one.

## Page 1. The problem, scope and numbers

**Pitch:** during a sale, show the right price and stock within 2 seconds in every cache layer and region, keep hit ratios high, and never melt the origin with purge storms.

**Who uses it:** deal hunters (flash price on time, "sold out" fast), the inventory system (pushes stock without knowing the caches), CMS editors, platform engineers (tag responses, get invalidation free).

**In scope:**
- **Capture:** every committed change to product, price, inventory and CMS tables via change data capture (CDC), ordered per entity.
- **Dependency mapping:** each change maps to cache keys and surrogate tags (product, brand, listings).
- **Fan-out:** version-aware Redis invalidation, in-process (L1) evictions, CDN soft purge by tag.
- **Cross-region:** relay to the secondary region only after replication applied the change.
- **Scheduled and manual:** synthetic changes at publish_at; audited purge APIs; a reconciler.

**Out of scope:** live price push, search indexing, checkout correctness, personalized pages.

**Non-functional targets:**
- **Latency:** commit to invisible-stale p99 under 2 s for price and stock, under 30 s for other content, including CDN.
- **Throughput:** 20k source updates/s, fanning out up to 200k tag invalidations/s.
- **Delivery and ordering:** at least once, idempotent deletes, no lost invalidation beyond the TTL bound; per-entity order only.
- **Availability:** pipeline 99.95%; reads unaffected by a pipeline outage (fall back to short TTLs).
- **Origin protection:** origin miss QPS under 50k during any purge burst; CDN hit ratio 90% or more.

**Capacity math (100M entities, 20k updates/s peak: 15k stock, 4k price, 1k other; 1M reads/s):**
- **Fan-out:** 20k x 5 targets (object, tile, about 3 listing tags) = 100k/s; 40% are repeats within 250 ms, so coalescing leaves 60k/s. So coalesce before fan-out.
- **CDN purge:** 60k / 256 tags per call = about 235 calls/s, under the 1,000/s API limit. So batch purges.
- **Kafka:** 20k x 300 B = 6 MB/s; 48 partitions at about 420 events/s each. The pipeline itself is cheap.
- **Refill:** if 30% of 60k purged objects/s are read in the next second, 18k misses/s. Under 50k only with single-flight fills and stale-while-revalidate.
- **Volatile split:** stock inside a 4 KB page means 15k page purges/s; a 100-byte stock endpoint with 1 s TTL cuts page purges by 75%.

## Page 2. The architecture

```
 Writers (services, batch jobs, sellers, manual SQL fixes)
    |
    v
 MySQL primary -- binlog --> Debezium --> Kafka 'changes' (key: entity id)
    | async replication                        |
    v                                          v
 Replicas <- miss <- Redis (versioned)   Invalidator: dependency resolver,
                       ^  DEL / lease <-  coalesce 250 ms, priority lanes
                       |                    |          |            |
 API / renderers ------+                    v          v            v
  (emit Surrogate-Key headers)      L1 pub/sub   CDN purger    Region relay
                                    to services  (soft purge   (waits for
                                                  by tag)       replica GTID)
 Reconciler (samples cache vs DB)   Scheduler (publish_at -> synthetic change)
```

- **Debezium CDC:** tails the MySQL binlog; catches every writer, including manual fixes.
- **Kafka changes topic:** replayable, ordered per entity id, 7-day retention.
- **Dependency resolver:** maps a row to keys and tags (product:42, brand:7, category:shoes).
- **Invalidator:** coalesces per id, routes to fast lane (price, stock) or bulk lane.
- **Redis sink:** version-aware delete with tombstones and leases.
- **L1 broadcast:** pub/sub telling every service instance to evict an id.
- **CDN purger:** batches 256 tags per call, soft purge, jittered retries.
- **Region relay:** purges region B only after its replica has the change.
- **Reconciler and scheduler:** catch stale entries; fire changes at publish_at.

**Flow A: price update to every layer**
1. Pricing commits product 42 at version 105 (GTID g1, the replication position); Debezium emits it to Kafka.
2. The Invalidator dedupes within 250 ms, routes to the fast lane; resolver returns keys and tag product:42.
3. Redis invalidates (lease-aware), L1 evicts id 42, the CDN soft-purges every page tagged product:42.
4. The next request gets the stale copy while the CDN shield revalidates once with origin.
5. The relay waits until region B replicas reach g1, then repeats steps 3-4 there.

**Flow B: read with lease after invalidation**
1. A renderer misses in Redis and gets lease token L; other callers wait or take the stale value.
2. It reads the DB and sets with L; if an invalidation came meanwhile, L is revoked and the set fails.

## Page 3. The core deep dives

### 1. CDC as the single source of invalidation
Deleting cache keys in application code misses batch ETL, manual SQL fixes and legacy writers, and a dual write (DB then cache) can fail halfway. Tailing the binlog captures every committed change. Events go to Kafka partitioned by entity id, so all changes to product 42 stay in order; the version increments in the same transaction. Consumers commit offsets only after Redis, L1 and CDN acknowledge, so delivery is at least once and deletes are idempotent. Services may also delete directly for speed, but correctness rests on CDC.

### 2. The stale-set race
Example: Sethu's request reads price v104 from a replica; pricing commits v105 and the cache entry is deleted; Sethu's request then writes v104 into the cache, which stays wrong for a full TTL. Three guards: a delete leaves a short tombstone holding v105, and a Lua SET-IF-NEWER rejects v104; leases (as in Facebook's memcache) are revoked by any delete, so the slow filler loses; a delayed second delete after max(observed lag, 1 s) covers the rest. Refills read a replica only if its GTID covers the last invalidation, else the primary.

### 3. Dependency fan-out with surrogate tags
One price appears on the product page, listings, search tiles and widgets. Renderers tag each response with every entity fetched through the data access layer (Surrogate-Key: product:42 brand:7), and the CDN purges by tag. Bulk changes collapse: a 200k-item repricing purges brand:7 rather than 200k tags, through a rate-capped bulk lane so stock never queues behind it.

### 4. Soft purge and split by change rate
Soft purge marks objects stale instead of deleting them; with stale-while-revalidate, the CDN serves the old copy while one request refreshes it. Stable content uses max-age 60 plus stale-while-revalidate 30; stock is a 1 s micro-cache merged late. Hard purge is only for legal takedowns.

**Data model:**
- **Change event** (Kafka, 48 partitions, RF 3): key entity_type:entity_id; version, GTID, changed fields.
- **Cache entry** (Redis): obj:{type}:{id}; value, version, soft expiry; lease tokens alongside.
- **Tag index** (Redis sets, Cassandra for large fan-out): tag -> set of keys.
- **Invalidation ledger** (compacted Kafka plus ClickHouse): request_id; per-layer ack times.
- **Row version** (MySQL): version BIGINT incremented in the same transaction.

**Key APIs:**
- `POST /internal/invalidate`: manual purge; audited, rate limited, uses the same Kafka topic.
- `GET /internal/invalidate/{request_id}`: confirms propagation, for example before a deal launch.
- `GET /v1/products/{id}`: emits every included entity as a tag.
- `GET /v1/stock/{id}`: tiny endpoint, max-age 1, merged client-side.
- `POST /internal/schedule`: synthetic change at a given time.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Fan-out:** one brand-wide change can touch 200k products and 50k listing pages; tag purges, batching, priority lanes.
- **Reads after purges:** stale-while-revalidate at CDN and Redis; request collapsing at the CDN shield.
- **Writes:** more Kafka partitions by entity id; invalidators scale per partition; coalesce repeats.
- **CDN purge limit:** token bucket with 256-tag batches, fast lane first, else short TTL headers.

**Failure modes:**
- **Debezium stops:** heartbeat events stop; alert within 30 s; edge TTLs shortened; restart from the stored binlog position.
- **Binlog position lost:** re-snapshot; bump a namespace version instead of millions of deletes.
- **CDN purge API throttled:** backoff with jitter, queue in the purger, short max-age on affected paths.
- **Redis failover:** retry the delete on the new primary; the version guard blocks stale fills.
- **Purge storm:** soft purge serves stale, the shield collapses requests, origin sheds low priority.
- **Pipeline down 10 minutes:** short max-age headers and Redis TTLs; replay from committed offsets.
- **Region failover:** replay from the last committed offset; flush keys changed in the lag window.

**Trade-offs chosen:**
- **Binlog CDC over app deletes:** only CDC sees every committed change; app deletes just add speed.
- **Invalidate over pushing new values:** pushing to every layer and region is costly and order-sensitive.
- **Field-group tags, coarser in bulk:** precision for hit ratio; purge-all is a last resort.
- **Separate micro-cached stock:** big pages stay cached long; purges hit tiny objects.
- **Soft over hard purge:** prevents miss storms; hard only when stale is unacceptable.
- **Version guards plus delayed delete over delayed delete alone:** precise and idempotent.
- **GTID-gated relay over immediate cross-region purge:** region B's DB has the change first.

**What to measure:** commit-to-purge latency p50/p99 per layer (Redis, CDN, region B), consumer lag per lane, coalescing ratio, CDN purge rate and throttles, stale-read rate from the reconciler, hit ratio around purge bursts, origin miss QPS, version-guard rejections, CDC heartbeat freshness.

## Page 5. Say it in the interview

> "For frequently updated content, the cache is only worth having if invalidation is fast and correct, so I start with how often each field changes and how stale it may be. Assume 20 thousand updates a second against a million reads, with stock and price visible within two seconds and other content within thirty. First, split data by change rate: stable fields get long-lived entries invalidated by events; volatile ones are cached for a second and merged late. Invalidation is driven by the database log: binlog CDC into Kafka partitioned by entity id, and an invalidator that deletes Redis keys, evicts in-process caches and purges the CDN by surrogate tags, so one product change reaches every page that embeds it. Every fill is version-aware, so an old value never overwrites a new one. The metric I watch above all is commit-to-purge latency at p99."

**Key points to land:**
- Split data by change rate; keep volatile fields out of large cached objects.
- Drive invalidation from CDC, not scattered application code.
- Partition by entity id and carry versions everywhere; ordering becomes a comparison.
- At-least-once plus idempotent deletes; commit offsets after sinks ack.
- Leases or version checks kill the stale-set race.
- Tag responses with every entity they include; purge by tag.
- Soft purge with stale-while-revalidate so purges never become miss storms.
- Coalesce and use priority lanes so stock never waits behind bulk CMS purges.
- Gate cross-region invalidation on replication position.
- TTL is only the safety net; watch commit-to-purge latency and stale-read rate.

**Likely follow-ups:**
1. **How do you know it works?** End-to-end latency from the ledger, a heartbeat row read through every layer as a freshness probe, and the reconciler's stale-read rate.
2. **Why not short TTLs everywhere?** A 2 s TTL across 100M objects at 1M reads/s pushes the long tail to origin; events let stable content stay cached for minutes.
3. **A cache you cannot invalidate (browser, third-party proxy)?** Short max-age with ETags for cheap revalidation, and content-hashed URLs for static assets.
4. **The hardest bug?** A stale fill from a lagging replica during a lag spike: intermittent, lasting a full TTL; hence GTID-gated reads and version guards.
5. **Teams forget to tag responses?** Tagging is automatic in the data access layer, a test fails untagged cacheable responses, and the reconciler catches the rest.

**Director layer:**
- **Cost drivers:** origin capacity for refills (kept under 50k misses/s), CDN purge API limits, Kafka and Debezium operations; the pipeline itself is single-digit MB/s.
- **Phasing:** CDC plus Redis and CDN tag purge first, then leases and version guards, the region relay and the reconciler.
- **Team ownership:** one shared invalidation platform team; product teams own tags through the shared data layer.
- **Top risks:** bulk purges overloading origin, lost or reordered invalidations, stale-set races, incomplete dependency maps, and a silent pipeline outage.
