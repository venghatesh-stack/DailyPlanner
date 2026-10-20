# Geo search for nearby locations (Yelp / Google Maps nearby): recall card

> **Hook:** Lat/lng → Pick cell size ≥ radius → 9 cell lookups → Haversine filter → Rank → Hydrate details

**P · Problem:** It's really a two-dimensional range query mapped onto one-dimensional cell keys over a small, read-heavy index.

**N · Numbers:**
1. 29k QPS at peak against about 100 edits/s, so it is read-heavy and async CDC is enough for writes.
2. 200M places x 40 B = 8 GB index, so replicate all of it in memory on every node; no sharding, no fan-out.
3. About 10k QPS per 16-core node, so 3 nodes cover peak and we run 6 per region for N+2.

**H · Hard part:** Never missing a place across cell borders, and keeping dense city cells cheap.

**B · Boxes:** `Client → API gateway → Location Query Service → In-memory geo index → Details cache (Redis)`

Side path: `Place DB → Debezium CDC → Kafka → Index builder → index replicas` for edits.

**D · Decisions:**
1. Full replica over sharding, because 8 GB fits in RAM, failover is trivial and writes are only 100/s.
2. In-process index over Redis GEO or Elasticsearch, because there is no network hop and no hot shards.
3. Async CDC over synchronous index writes, because writes stay simple and users tolerate seconds of lag.

**F · Failures:**
1. Index builder stuck → search serves the last applied state; alert at 60 s lag; owners still read edits from the DB.
2. Query node replaced → it loads the S3 snapshot in 2-3 minutes, replays Kafka from the snapshot offset, then joins.

**C · Close:** "A B-tree narrows only one dimension, so I map the earth into geohash or S2 cells. A radius query becomes nine cell lookups, then an exact haversine filter and ranking. The index is only 8 gigabytes, so every query node holds all of it in memory and I scale by adding replicas. Edits flow through CDC and Kafka, and hot city cells get adaptive splits and caps."

**Quiz yourself:**
1. Why query 9 cells, not a prefix match? → A place 50 m away can sit in a neighbour cell with a different prefix.
2. How do you handle 20k places in one cell? → Rank-sorted lists capped at 500, adaptive splits, 30 s caches.
3. What if POIs grow to 5 billion? → About 200 GB: shard by coarse S2 cell, scatter-gather to 1-4 shards.
