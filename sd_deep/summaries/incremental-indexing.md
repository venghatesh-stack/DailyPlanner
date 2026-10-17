# Design an indexing pipeline that handles frequent updates (near-real-time search indexing): the 5-page summary

A 500M-product catalog gets up to 150k price, stock and content updates per second, and search must show them within seconds without slowing queries. The single most important idea: inverted indexes hate updates (each one is a delete plus re-insert), so capture changes in order, coalesce them, split hot fields like price and stock away from the full-text index, and rebuild whole indexes offline with an atomic alias swap.

## Page 1. The problem, scope and numbers

**Pitch:** search must reflect price and stock within 5 s and content within a minute, even in flash sales (7-10x update spikes), with zero lost updates and zero-downtime reindexes. Today stale results cause failed checkouts.

**Who uses it:** shoppers, sellers running lightning deals, relevance engineers and on-call SREs.

**In scope:**
- **Change capture:** CDC or transactional outbox from each owning service into Kafka, keyed by product id.
- **Assembly:** merge partial updates from different owners into one versioned document.
- **Coalesce and apply:** collapse bursts; monotonic versions reject stale writes; deletes as tombstones.
- **Priority lanes:** availability (price, stock) ahead of content.
- **Rebuilds and replay:** new index from snapshot, catch-up replay, atomic alias swap; DLQ with re-drive.

**Out of scope:** ranking and query serving, query understanding, embeddings, cross-region active-active indexing, search analytics. Search is not strongly consistent with checkout: checkout re-validates.

**Non-functional targets:**
- **Freshness:** price and stock p50 under 2 s, p99 under 5 s; content p99 under 60 s.
- **Throughput:** 150k updates/s for 2 hours; burst 250k/s for 5 minutes, lag recovered in under 10 minutes.
- **Correctness:** zero lost updates (Kafka RF 3); the index version never goes backwards.
- **Query isolation:** search p99 under 150 ms while indexing at peak.
- **Rebuild:** all 500M docs in under 6 hours, zero downtime.

**Capacity math (500M docs, 20k updates/s average, 150k/s peak, 85% price/stock):**
- **Kafka ingress:** 150k/s x 1 KB = 150 MB/s; x RF 3 = 450 MB/s disk write. About 10 brokers.
- **Kafka retention:** 20k/s x 86,400 x 1 KB = 1.7 TB/day; 7 days x RF 3 = about 36 TB. So replay of a week is affordable.
- **Hot fields:** 85% x 150k = 127k/s of tiny 50-byte docs; 500M x 50 B = 25 GB total. So they get their own small store, even in memory.
- **Full-text writes:** 15% x 150k = 22.5k/s, minus 40% coalescing = 13.5k docs/s. So the 1 TB index sees 11x less churn.
- **Main index and rebuild:** 1 TB / 25 GB = 40 primary shards, 2 TB with a replica on about 20 nodes; a 6 h rebuild is 23k docs/s, under 600 per shard.

## Page 2. The architecture

```
 Catalog svc   Pricing svc   Inventory svc   Seller tools
   | outbox      | CDC         | CDC            | outbox
   v             v             v                v
 Kafka change topics (key = product_id, 256 partitions, RF 3, 7 days)
                       |
                       v
 Flink assembler: merge + version + coalesce (RocksDB, checkpoint 10 s)
        |                            |                        |
        v                            v                        v
 Kafka idx.avail             Kafka idx.content            DLQ topic
        |                            |
 Bulk indexer pool A         Bulk indexer pool B (external versions)
        v                            v
 ES availability index <- query-time join -> ES products_v42 (alias)
                                                  ^ alias swap
 Lakehouse snapshot -> Spark full build -> products_v43 -> validate
```

- **CDC / outbox:** turns committed changes into ordered events with a source version; no dual writes.
- **Kafka change topics:** durable, replayable, ordered per product.
- **Flink assembler:** per-product state; merges, versions, coalesces, routes to lanes, emits tombstones.
- **Lane topics:** decouple assembly from indexing; scale and replay each lane separately.
- **Bulk indexers:** 5-15 MB batches, external versions, adaptive concurrency on 429s, DLQ on failure.
- **Main index:** full-text, 40 primaries, 1 s refresh, segment replication for replicas.
- **Availability index:** tiny price, stock and flag docs at 100k+/s, joined at query time.
- **Rebuild orchestrator:** snapshot build, Kafka replay, validation, alias swap, keeps old version.
- **Reconciler:** samples docs, compares index and source versions, re-emits repairs.

**Flow A: price drop to searchable**
1. Pricing commits product P at version 1183; Debezium emits to price.changes keyed by P.
2. Flink sees only hot fields changed; emits {P, price, stock, 1183} to idx.avail after a 200 ms window.
3. Indexer A bulk-writes with version_type=external, version 1183.
4. 1 s refresh makes it visible; typical lag 1.5-3 s, p99 under 5 s.

**Flow B: zero-downtime full reindex**
1. Record time T0 and lane-topic offsets.
2. Spark loads the T0 snapshot into products_v43 with replicas 0 and refresh off.
3. Turn on replicas and refresh; a second consumer group replays lanes from T0 into v43.
4. When lag is under 5 s, validate counts, checksums and canary queries; swap the alias atomically; keep v42 for 48 h.

## Page 3. The core deep dives

### 1. Why updates hurt, and the hot-field split
Lucene stores immutable segments. An update marks the old doc deleted and writes a new one into a fresh segment; background merges later reclaim space. At 150k updates/s that means merge storms, a rising deleted-docs ratio (40% on hot shards slows queries) and higher search latency. Since 85% of updates are price and stock, they go to a separate 25 GB availability index (or an in-memory map in the query service). Volatile values are bucketed: stock shows as in stock, few left or out, so the index changes only when the bucket changes. Only content edits touch the 1 TB text index.

### 2. Ordering and effectively-once
Global order does not scale; per-key order does. Kafka keys by product id, so all events for P land in one partition. Each source owns some fields and stamps a monotonic version (its DB log position, never wall clock). Flink keeps the highest version per source and drops older ones; Elasticsearch enforces it again with external versioning and returns 409 for a stale write, which the indexer counts as success. Example: after a consumer rebalance, version 1183 lands before 1182; ES rejects 1182, so the newer price stands. Delivery is at-least-once, writes are idempotent, so duplicates and replays are harmless.

### 3. Coalescing and backpressure
Flink debounces per product: 10 edits in 300 ms become one write; a hot product with 1,000 stock updates/s collapses to about 5 writes/s. Bulk indexers size requests by bytes and use AIMD: halve concurrency on 429 rejections with jittered backoff, add one on success. Kafka offsets commit only after the whole batch is acknowledged. When ES is saturated, lag builds in the content lane first while the availability lane keeps its SLO.

### 4. Deletes and rebuilds
Deletes carry a version and leave a tombstone in Flink state, so a late upsert with a lower version cannot resurrect a delisted product. During a rebuild, the live indexer writes to the concrete v42 name, the replay consumer to v43; versions reconcile the overlap.

**Data model:**
- **ChangeEvent** (Kafka): key product_id, 256 partitions, Avro in a schema registry.
- **ProductState** (Flink RocksDB, checkpoint to S3 every 10 s): keyed by product_id; per-source versions plus a combined doc_version.
- **Product document** (ES products_vN): _id = product_id; external version = doc_version.
- **Availability doc**: _id = product_id; about 50 B each, 25 GB total.
- **IndexVersion registry** (Postgres): PK version; drives rebuild and rollback.

**Key APIs:**
- `POST /_bulk`: 409 counted as success, 429 triggers backoff.
- `POST /admin/v1/reindex`: idempotent by target_version.
- `POST /admin/v1/alias/swap`: fails unless validation passed; one atomic _aliases call.
- `POST /admin/v1/replay`: new consumer group; safe due to external versioning.
- `GET /admin/v1/freshness`: commit_ts in docs versus refresh time.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Text index churn:** hot-field split and coalescing; tune merge policy; force-merge cold indices off-peak only.
- **Hot-field rate:** move price to an in-memory map in the query service fed straight from the availability stream.
- **Bulk seller jobs:** per-seller rate limits at source plus a separate low-priority bulk lane, so 2M edits in a minute never starve price and stock.
- **Replica CPU:** segment replication roughly halves indexing CPU.
- **Mapping explosion:** dynamic: strict plus an attribute allowlist protects cluster state.

**Failure modes:**
- **ES rejects writes at peak:** AIMD backs off, content lag grows first; alert if projected drain time exceeds the SLO.
- **Flink crash:** restart from the 10 s checkpoint; re-emitted events are idempotent; lag spike under a minute.
- **CDC connector stalls on schema change:** per-source freshness alert; registry compatibility checks; resume from stored log position.
- **Bad mapping in a new index:** validation blocks the swap; if found later, swap back to the retained version in seconds.
- **Data node dies:** replicas promote; bulk retries with backoff.
- **Poison message:** 5 retries, then DLQ; the partition continues; fix and re-drive.
- **Indexer down beyond Kafka retention:** rebuild from snapshot plus archived changes in the lakehouse.

**Trade-offs chosen:**
- **CDC and outbox over dual writes:** no lost updates; outbox gives a clean contract where tables are messy.
- **Per-key order plus versions over global order:** scales and is replay-safe.
- **At-least-once plus idempotent writes over exactly-once:** ES is outside Kafka transactions; idempotency also covers replays.
- **Separate availability index over updating the text index:** removes 85% of rewrites; an in-memory map is faster but needs its own replication.
- **1 s refresh over faster:** balances freshness against segment count; the hot-field split handles the tight SLO.
- **Snapshot plus replay with alias swap over in-place reindex:** supports mapping changes and gives instant rollback.
- **Accept stale search over strong consistency:** checkout re-validates stock and price.

**What to measure:** freshness lag per lane, broken into stages (commit to Kafka, to Flink emit, to bulk ack, to refresh); consumer lag in records and seconds; bulk 429 and 409 counts; segment count and deleted-docs ratio; search p99 versus indexing rate; DLQ inflow and oldest age; reconciler mismatches; coalescing ratio.

## Page 5. Say it in the interview

> "I am indexing a 500 million product catalog, averaging 20 thousand updates a second and peaking at 150 thousand in sales. Price and stock must be searchable in 5 seconds, content in a minute, and indexing must not push search past 150 milliseconds p99. Services writing straight to Elasticsearch would lose and reorder updates. So I capture changes with CDC or an outbox into Kafka keyed by product id, assemble and coalesce them in Flink, and bulk-write with external versions so duplicates and replays are harmless. The key insight: inverted indexes hate updates, so I split price and stock into a small fast index and only content touches the full-text index. That cuts 150 thousand writes a second to about 13.5 thousand. Full rebuilds load a snapshot into a new index, replay Kafka, validate and swap an alias."

**Key points to land:**
- Every update is a delete plus add in immutable segments, so frequent updates mean merge pressure.
- Never dual write: CDC or outbox into Kafka keyed by document id.
- Effectively-once = at-least-once plus idempotent, externally versioned writes.
- Never order by wall clock; use source log positions or per-entity versions.
- Coalesce bursts per document in Flink keyed state.
- Split hot fields from full text; bucket volatile values.
- Backpressure: Kafka buffers, AIMD on 429s, priority lanes protect the money SLO.
- Rebuild from snapshot plus replay, validate, swap alias, keep the old index for rollback.
- Measure freshness per stage, not only consumer lag.
- Anchor: 150k/s shrinks to about 13.5k/s of full-text writes.

**Likely follow-ups:**
1. **How does an older price never overwrite a newer one?** Per-key ordering plus source versions, enforced in Flink state and again by ES external versioning: two layers.
2. **Freshness p99 jumps from 3 s to 40 s in a sale?** Split lag by stage timestamps; usually bulk 429s or merges; check whether a bulk seller job leaked into the availability lane.
3. **Price under 100 ms?** Not through a Lucene refresh: keep price in an in-memory map in the query service and apply it after retrieval.
4. **Source schema change?** Schema registry with backward compatibility; new fields ignored until mapping catches up; breaking changes get a new topic and dual publishing.
5. **Two regions?** Replicate Kafka (MirrorMaker 2) and index in each region; versions make both converge.

**Director layer:**
- **Cost drivers:** about 20 ES data nodes plus a rebuild cluster's worth of headroom, about 10 Kafka brokers and 36 TB of retention, Flink state.
- **Phasing:** CDC and versioned writes first, then the hot-field split and lanes, then automated rebuilds and the reconciler.
- **Ownership:** source teams own their CDC or outbox contracts; the search platform owns Flink, indexers and rebuilds; SRE owns freshness SLOs.
- **Top risks:** merge storms hurting query latency, stale overwrites, poison documents, rebuilds that run long or diverge.
