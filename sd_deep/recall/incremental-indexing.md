# Indexing pipeline that handles frequent updates (near-real-time search indexing): recall card

> **Hook:** CDC into Kafka by product → Flink merges and coalesces → Split hot fields → Versioned bulk writes → Alias swap for rebuilds

**P · Problem:** It's really an ordered change-stream problem feeding an inverted index that hates updates.

**N · Numbers:**
1. 85% of 150k updates/s are price and stock, only 25 GB in total, so they get their own small availability index.
2. Content writes drop to about 13.5k docs/s after coalescing, so the 1 TB text index sees 11x less churn.
3. A 7-day Kafka retention is about 36 TB, so replaying a week is affordable.

**H · Hard part:** Every update is a delete plus re-insert in Lucene, and an older version must never overwrite a newer one.

**B · Boxes:** `Source services → CDC / outbox → Kafka → Flink assembler → Lane topics → Bulk indexers → Elasticsearch`

Side path: `Lakehouse snapshot → Spark build → new index → validate → alias swap`.

**D · Decisions:**
1. Per-key order plus versions over global order, because it scales and is replay-safe.
2. Separate availability index over updating the text index, because it removes 85% of rewrites.
3. Snapshot plus replay with alias swap over in-place reindex, because it supports mapping changes and instant rollback.

**F · Failures:**
1. Elasticsearch rejects writes at peak → AIMD backs off and content lag grows first while price and stock keep their SLO.
2. Bad mapping in a new index → validation blocks the swap; if found later, swap back to the retained version in seconds.

**C · Close:** "Services writing straight to Elasticsearch would lose and reorder updates. So I capture changes with CDC or an outbox into Kafka keyed by product id, assemble and coalesce them in Flink, and bulk-write with external versions so duplicates and replays are harmless. Inverted indexes hate updates, so price and stock go to a small fast index and only content touches the full-text index. Rebuilds load a snapshot, replay Kafka and swap an alias."

**Quiz yourself:**
1. How does a stale price never win? → Source versions in Flink state, then ES external versioning returns 409.
2. Why not order by wall clock? → Clocks skew; use the source log position.
3. Price under 100 ms? → Not via Lucene refresh; keep an in-memory map in the query service.
