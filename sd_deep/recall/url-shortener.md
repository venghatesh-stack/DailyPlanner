# URL Shortener (TinyURL / Bitly): recall card

> **Hook:** Counter → Shuffle → Base62 → Cache → 302

**P · Problem:** It's really a read-heavy key-value lookup with a hard uniqueness rule on short keys.

**N · Numbers:**
1. 40K redirects/s at peak against 400 creates/s, so design the cache first.
2. 62^7 = 3.5 trillion keys, so 7 characters last for centuries.
3. 10 GB hot set, so it fits in a small Redis cluster.

**H · Hard part:** Handing out short, unique, unguessable keys without a central bottleneck, and redirecting in milliseconds.

**B · Boxes:** `Client → CDN → Redirect service → Redis → DynamoDB`

Side path: `Redirect service → Kafka → Flink → ClickHouse` for click analytics.

**D · Decisions:**
1. Range counter plus shuffle over hashing, because there are no collisions and keys stay at 7 characters.
2. 302 over 301, because analytics and takedowns need every click to reach us.
3. Async Kafka analytics over synchronous counting, because a redirect must never wait for analytics.

**F · Failures:**
1. Redis node dies → replica is promoted; misses go to the database with singleflight.
2. Kafka is down → click events spool to disk; redirects carry on, analytics lags.

**C · Close:** "So this is a read-heavy lookup service. Keys come from range-allocated counters, shuffled and Base62-encoded, so they are unique and short. Redirects are served from a CDN, a local cache and Redis, and analytics flows asynchronously through Kafka, so a slow pipeline never slows a click. Next I would add custom domains and abuse scanning."

**Quiz yourself:**
1. Why not hash the long URL? → Collisions, and the same URL would always get the same key.
2. Why 302 and not 301? → Browsers cache a 301, so we lose clicks and cannot take a link down.
3. What absorbs a viral link? → The CDN and every node's in-process cache.
