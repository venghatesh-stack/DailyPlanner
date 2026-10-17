# Design geo search for nearby locations (Yelp / Google Maps nearby): the 5-page summary

Given a latitude, longitude and radius, return the best nearby places in under 100 ms. The single most important idea: two-dimensional proximity does not fit a one-dimensional B-tree, so map the earth onto cells (geohash or S2), turn a circle into about 9 cell lookups, filter by exact distance and rank; and because the index is small and changes slowly, replicate all of it into memory on every node instead of sharding.

## Page 1. The problem, scope and numbers

**Pitch:** "near me" that is instant, accurate and relevant, with a merchant's new outlet searchable within minutes, offered as one reusable service for many product teams.

**Who uses it:** shoppers on flaky 4G (fast, relevant results), merchants (new places appear quickly), product teams such as food, grocery and ads (one geo API with filters and pluggable ranking), trust and safety (hide fraud in minutes) and SRE.

**In scope:**
- **Radius search:** lat, lng, radius from 100 m to 50 km; top N places by score.
- **Viewport search:** a bounding box and zoom, clustered when dense.
- **K-nearest:** expand rings until K are found or a 50 km cap.
- **Filters:** category, open now (time-zone aware), rating, price, tags.
- **Ranking:** distance decay blended with rating, popularity and boosts.
- **Place edits and moderation** propagated to the index within 2 minutes; stable cursor paging.

**Out of scope:** moving objects such as drivers, routing and isochrones, full-text search over reviews, indoor positioning, map tiles.

**Non-functional targets:**
- **Latency:** /nearby p50 under 30 ms, p99 under 100 ms server side; index lookup under 5 ms.
- **Availability:** 99.99% per region; survive an AZ loss with no user impact.
- **Freshness:** edits searchable in 60 s at p95, 2 minutes at p99.9.
- **Consistency:** eventual from DB to index; read-your-writes for the owner via the DB.
- **Accuracy:** never miss a place inside the radius because of cell borders (100% recall before caps).

**Capacity math (200M places, 100M DAU x 5 queries, 5x peak):**
- **Queries:** 500M / 86,400 = about 5,800 QPS average, 29,000 at peak. Read-heavy.
- **Index:** 200M x 40 B (id, cell, lat/lng, rank and flags) = 8 GB. It fits in RAM, so replicate it whole on each node; no fan-out.
- **Details:** 200M x 1 KB = 200 GB; shard it, and cache the hot 10% (20 GB) in Redis.
- **Edits:** 1% a day = 2M / 86,400 = about 23 writes/s, 100/s peak. Trivial, so async CDC is enough.
- **Per node:** 9 cells and 200 distance checks is about 50 microseconds; with ranking about 1 ms CPU, so a 16-core node does about 10,000 QPS. 29k QPS needs 3 nodes; run 6 per region for N+2 and AZ spread.
- **Egress:** 29k x 20 results x 200 B = about 116 MB/s at peak.

## Page 2. The architecture

```
 Mobile / Web
     |
 CDN / API gateway: auth, rate limit, route to nearest region
     |
 Location Query Service x N (stateless)
     | 1. cover(lat, lng, r) -> cells
     | 2. look up cells ---------> Geo index replica (in memory, 8 GB)
     | 3. haversine + filters + rank          ^ deltas      ^ snapshot
     | 4. hydrate top k -> Details cache (Redis)    |             |
     |                        | miss         Index builder    S3 snapshots
     |                        v                     ^
     |                  Place DB (Postgres,         |
     |                  sharded by place_id)        |
     |                        | CDC (Debezium)      |
 Merchant / moderation -> Place service -> Kafka place-changes
```

- **API gateway:** TLS, auth, per-client rate limits, routes users to the nearest region.
- **Location Query Service:** stateless; cell cover, lookup, exact filter, rank, page, hydrate.
- **Geo index:** in-memory map from cell id to places sorted by static rank; on every node.
- **Place service and DB:** source of truth; Postgres sharded by place_id.
- **CDC and Kafka:** every committed change, keyed by place_id to keep per-place order.
- **Index builder:** turns changes into cell deltas; writes nightly snapshots to S3.
- **Details cache:** Redis by place_id, 10-minute TTL, invalidated on change.
- **Ranking module:** blended score with per-caller profiles.

**Flow A: nearby search (read)**
1. GET /v1/nearby?lat=19.07&lng=72.87&radius_m=2000&category=grocery reaches the India region.
2. Pick a precision whose cell side is at least the radius; take the centre cell plus 8 neighbours.
3. Read the 9 cell lists (sorted by static rank, capped at 500); keep places within 2,000 m that match filters.
4. Rank, take the top 20, build a cursor, batch-get details from Redis. About 15 ms typical.

**Flow B: place edit (write)**
1. The merchant moves an outlet; the row commits in the Place DB.
2. Debezium publishes it to Kafka keyed by place_id.
3. The builder emits remove(old cell) and add(new cell); every replica applies it, copy-on-write.
4. The details cache entry is invalidated. Lag is 5-30 s; alert past 60 s.

## Page 3. The core deep dives

### 1. Cells: geohash cover without missing places
Geohash interleaves the bits of longitude and latitude, found by repeatedly halving each range, then base32-encodes them; each extra character adds 5 bits and shrinks the cell. Nearby points usually share a prefix, so a cell is a key lookup. But Shreya can stand 50 m from a cafe in the next cell with a completely different prefix. So never rely on prefix match: choose the precision where a cell is at least as large as the radius, query the 3x3 block around the centre, then filter with haversine (great-circle distance, about 0.5% accurate). Longitude wraps at the antimeridian; S2 handles poles natively.

### 2. Hot cells in dense cores
A cell over Connaught Place may hold 20k places. Each cell list is sorted by static rank and capped at 500 candidates, cells split adaptively like a quadtree (a cell divided into four when it is too full) at 500 entries, and popular (cell, category) results are cached for 30 s with single-flight, so one miss fills the cache.

### 3. K-nearest in empty areas
Start at a fine level; if fewer than K hits, go one level coarser and query only new cells. Stop when K are found and the K-th distance is less than the distance to the nearest unvisited cell edge, which proves nothing closer was skipped. Cap at 50 km.

### 4. Ranking and stable paging
Score = 0.5 x exp(-distance / radius) + 0.3 x rating/5 + 0.2 x popularity + boosts. With a 2 km radius and equal popularity, a 4.8-star place at 600 m (0.66) beats a 3.1-star place at 300 m (0.62). Paging uses a keyset cursor (last score, place_id), so page 2 never repeats page 1 while the index changes.

**Data model:**
- **Place** (Postgres, 64 logical shards by place_id): lat, lng, geohash, categories, hours, tz, rating, status, version.
- **CellEntry** (in memory): cell_id -> array sorted by static_rank of place_id, float32 lat/lng, category mask, open bitmap; geohash levels 4 to 7.
- **PlaceDetailsCache** (Redis): place:{id}, TTL 600 s.
- **IndexSnapshot** (S3): cell files, per-cell checksums and the Kafka offsets it covers.

**Key APIs:**
- `GET /v1/nearby`: lat, lng, radius_m, filters, limit up to 50, cursor; cacheable 30 s by geohash-7.
- `GET /v1/viewport`: bounding box and zoom; returns places or clusters.
- `POST /v1/places`: owner create with Idempotency-Key, kept 24 h.
- `PATCH /v1/places/{id}`: partial update with If-Match version.
- `POST /v1/places/{id}/hide`: moderation, via a high-priority topic.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Read QPS:** 290k peak QPS is about 30 nodes per region at 10k QPS each; reads scale linearly with replicas.
- **Hot cells:** adaptive splits, rank-sorted caps and short-TTL caching bound the CPU per query.
- **Index size:** if POIs grow to 5 billion (about 200 GB), shard by coarse S2 cell with a mapping table, 3 replicas each, scatter-gather to the 1-4 shards a query touches.
- **Details store:** sharded Postgres plus a Redis hot set; add shards as it grows.
- **Caching:** quantise cache keys to geohash-7 (about 150 m); raw coordinates never hit.

**Failure modes:**
- **Index builder stuck:** search serves the last applied state; alert at 60 s lag; owners still see edits via the DB.
- **Query node replaced:** bootstraps from the S3 snapshot in 2-3 minutes, replays Kafka from the snapshot offset, then joins.
- **Redis down:** return minimal fields from the index entry; rate-limited DB reads for top results.
- **Bad snapshot:** nodes check checksums and counts before loading and keep the previous one.
- **Duplicate or reordered CDC events:** apply only if the row version is newer, so apply is idempotent.
- **Region down:** GeoDNS shifts to the next region, which holds a full global replica; slower but correct.
- **Festival traffic spike:** single-flight caching, candidate caps, and shedding to cached results above 85% CPU.

**Trade-offs chosen:**
- **Full replica over sharding:** 8 GB fits in RAM, no fan-out, trivial failover, and only 100 writes/s.
- **In-process index over Redis GEO or Elasticsearch:** no network hop; Redis GEO shards go hot, Elasticsearch costs latency and ops.
- **Async CDC over synchronous index writes:** simpler, reliable writes; users tolerate seconds of lag.
- **Haversine retrieval, optional ETA re-rank of the top 20:** routing thousands of candidates is too costly.
- **Geohash or S2 with adaptive splits over fixed H3 or pure quadtree:** simple keys to serialise, cache and replicate.

**What to measure:** p50/p95/p99 per region and radius bucket, candidates scanned and max cell size, index apply lag, empty-result rate and ring depth, result and details cache hit rates, degraded-response rate, top-3 click-through and conversion, nightly checksum mismatches per cell.

## Page 5. Say it in the interview

> "I am assuming static places like restaurants and stores, about 200 million worldwide, searched by radius or by map viewport with filters like category and open now. Peak is about 29 thousand QPS, p99 under 100 milliseconds, and edits visible within a minute or two. Indexing latitude and longitude separately fails because a B-tree narrows only one dimension, so I map the earth into cells with geohash or S2 and keep a cell-to-places index. A radius query becomes nine cell lookups, the centre plus its neighbours, then an exact haversine filter and ranking. The index is only 8 gigabytes, so I replicate it into memory on every query node and scale by adding replicas. Writes flow from the place database through CDC and Kafka into the index. Dense cities create hot cells, which I handle with adaptive splits and per-cell caps, and I watch index lag, p99 and the empty-result rate."

**Key points to land:**
- Map lat/lng to cells; a circle becomes about 9 key lookups.
- Cells give candidates; haversine gives correctness; always include the 8 neighbours.
- 29k peak QPS over an 8 GB index with 100 writes/s: replicate in memory, scale by replicas.
- Hot cells are the real bottleneck: adaptive splits, caps by static rank, short-TTL caches.
- Writes via CDC and Kafka keyed by place_id, versioned idempotent apply.
- Snapshots in S3 for fast bootstrap and nightly drift checks.
- Owners get read-your-writes from the DB; everyone else accepts seconds of lag.
- Quantise cache keys to geohash-7 to make location caching work.
- Degrade gracefully: stale snapshot over no answer, minimal fields over timeouts, another region over an outage.

**Likely follow-ups:**
1. **Moving drivers every 4 seconds?** Writes jump from 100/s to hundreds of thousands, so keep positions in memory sharded by city or H3 cell with a TTL and no durable write per ping: a different, Uber-style design.
2. **5 billion POIs?** About 200 GB: shard by coarse S2 cell with a mapping table, replicate 3x, scatter-gather to 1-4 shards.
3. **Why not Elasticsearch?** Fine if you also need full-text with geo filters; for proximity plus filters at 30k QPS, an in-memory index is faster and cheaper.
4. **Order by travel time?** Retrieve by straight-line distance, batch-call routing for the top 50, re-rank, and cache ETAs per (origin cell, place) for minutes.
5. **How do you prove you never miss a place?** Property tests with random points on cell borders, the antimeridian and poles, compared against a brute-force scan.

**Director layer:**
- **Cost drivers:** query nodes (6 per region at today's peak, linear in QPS), the 200 GB details store and Redis hot set, and cross-region global replicas.
- **Phasing:** Redis GEO is a fine MVP; move to the in-process replicated index, CDC pipeline and snapshots as QPS grows.
- **Team ownership:** geo platform (index, query service), place data (Place service, CDC), ranking with product teams, trust and safety for moderation.
- **Top risks:** hot urban cells, index drift from missed CDC events (nightly rebuild and checksums), spam places, and privacy of user locations (log coarsened to geohash-5, enforce retention).
