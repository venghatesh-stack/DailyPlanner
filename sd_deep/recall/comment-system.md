# Comment system with sorting and pagination: recall card

> **Hook:** Partition by post → Rank in sorted sets → Page by cursor → Batch hydrate → Share hot first page

**P · Problem:** It's really a read-heavy ranked-list pagination problem over lists whose scores keep changing.

**N · Numbers:**
1. 230K page reads/s against 11.6K writes/s, so precompute orders and spend effort on the read path.
2. 4.6M comment fetches/s if uncached, so batch multi-gets and caches must cut store reads by over 90%.
3. 1.5 TB to rank every active post, so keep sorted sets only for about 2M busy posts (300 GB) and build the rest on demand.

**H · Hard part:** Infinite scroll that never duplicates or skips while scores change, and viral posts with a million comments.

**B · Boxes:** `Client → API Gateway → Comment Read API → Redis ranking index → Memcached → Cassandra`

Side path: `Comment Service → Kafka → Ranking Worker → Redis` keeps best and top fresh.

**D · Decisions:**
1. Keyset cursor over OFFSET, because cost stays constant per page and inserts do not shift pages.
2. Two-level threading over arbitrary depth, because it reads well on mobile and pages simply per parent.
3. Cassandra over sharded MySQL, because writes are append-heavy with key access and no joins.

**F · Failures:**
1. Redis ranking cluster down → best and top fall back to newest from the store; sets rebuild lazily.
2. Spam model down → new or low-trust accounts go pending, visible only to the author.

**C · Close:** "So this is a read-heavy ranked list. Comments are partitioned by post with time-sortable ids, so newest is a range scan. Best and top live in per-post sorted sets kept fresh by a worker on Kafka events. Pages use a signed cursor of score, id and snapshot time, never OFFSET, and each page of twenty ids is hydrated in one batch. Viral posts share a five-second first page. Next I would add live new-comment pills."

**Quiz yourself:**
1. Why not OFFSET? → Deep pages get slower and inserts shift rows, causing duplicates.
2. How is best scored? → Wilson lower bound with a gentle time decay.
3. What stops new comments shifting pages? → The snapshot time in the cursor, plus the client seen-set.
