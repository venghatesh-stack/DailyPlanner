# Cache invalidation for frequently updated content: recall card

> **Hook:** Split by change rate → Tail the binlog → Coalesce per entity → Version-aware delete → Soft-purge CDN by tag → Relay after replication

**P · Problem:** It's really an ordered change-propagation problem across many cache layers and regions.

**N · Numbers:**
1. 20k updates/s fan out to 100k invalidations/s, and coalescing leaves 60k/s, so coalesce before fan-out.
2. 60k purges/s at 256 tags per call is about 235 calls/s, so batch purges under the 1,000/s CDN limit.
3. Refills can reach 18k misses/s, so stay under 50k only with single-flight fills and stale-while-revalidate.

**H · Hard part:** Never letting a stale value overwrite a new one, and purging fast without melting the origin.

**B · Boxes:** `MySQL binlog → Debezium → Kafka changes → Invalidator → Redis, L1 and CDN purger`

Side path: `Invalidator → Region relay → region B purge after its replica reaches the GTID`.

**D · Decisions:**
1. Binlog CDC over app deletes, because only CDC sees every committed change, including manual SQL fixes.
2. Soft over hard purge, because serving stale while one request refreshes prevents miss storms.
3. Invalidate over pushing new values, because pushing to every layer and region is costly and order-sensitive.

**F · Failures:**
1. Debezium stops → heartbeats stop and we alert within 30 s; edge TTLs shorten; restart from the stored binlog position.
2. CDN purge API throttled → backoff with jitter, queue in the purger, short max-age on affected paths.

**C · Close:** "First I split data by change rate: stable fields get long-lived entries invalidated by events, and stock is micro-cached for a second. Invalidation comes from binlog CDC into Kafka partitioned by entity id. An invalidator deletes Redis keys, evicts in-process caches and soft-purges the CDN by surrogate tags, so one product change reaches every page. Every fill is version-aware, and I watch commit-to-purge latency at p99."

**Quiz yourself:**
1. What is the stale-set race? → A slow reader writes v104 into the cache after v105 was committed and the key deleted.
2. How do you stop it? → Tombstones with SET-IF-NEWER, leases revoked by any delete, and a delayed second delete.
3. Why not short TTLs everywhere? → At 1M reads/s the long tail would hit origin; events let stable content stay cached.
