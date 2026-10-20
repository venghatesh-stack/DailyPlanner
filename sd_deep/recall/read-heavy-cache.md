# Caching strategy for a read-heavy API (product catalog scale): recall card

> **Hook:** CDN → In-process L1 → Redis → Single-flight loader → MySQL; delete on write

**P · Problem:** It's really a load-shedding problem: the database is sized for misses, so each cache layer must cut traffic about 10x.

**N · Numbers:**
1. 500k reads/s shrink to 7.5k/s at MySQL through CDN, L1 and Redis, so the database is sized for misses, not traffic.
2. Top 20M items cost 45 GB, 90 GB with replicas, so size Redis from the hot set, not the dataset.
3. A cold cache sends 300k/s at a database rated for 30k/s, so refill must be throttled and warmed.

**H · Hard part:** Hot keys, stampedes on expiry and a cold cache, each of which can melt the database during a sale.

**B · Boxes:** `Client → CDN → API pod L1 → Redis Cluster → MySQL replica`

Side path: `MySQL binlog → CDC consumer → Kafka → second delete, L1 evictions, CDN purge`.

**D · Decisions:**
1. Delete over update on write, because deletes are idempotent and immune to out-of-order writers.
2. A 10-minute TTL plus event invalidation over no TTL, because a lost invalidation then self-heals.
3. Serve stale and shed over full fall-through, because fall-through overloads MySQL 10x.

**F · Failures:**
1. Whole Redis cluster down → breaker opens; L1 serves stale up to 5 minutes; misses reach MySQL only through a 200-connection bulkhead.
2. CDC consumer lags 10 minutes → app deletes still work; out-of-band writes stay stale until TTL.

**C · Close:** "Traffic is 500k reads a second against 5k writes, with heavy skew. Plain cache-aside on Redis breaks on hot keys, stampedes and a cold start. So I use four layers: a CDN, an in-process cache, Redis Cluster, and MySQL behind a single-flight loader and a bulkhead. That turns 500k reads into about 7.5k database reads. Writes delete the key, with CDC as a second delete. When Redis fails I serve stale and shed load."

**Quiz yourself:**
1. What is the stale-set race? → A slow loader writes an old row after the delete; fix with a delayed CDC delete and a version-guarded set.
2. One product suddenly gets 200k QPS? → L1 absorbs it, then 8 suffixed copies spread it across shards.
3. Should checkout trust the cached price? → No, it re-reads the authoritative price.
