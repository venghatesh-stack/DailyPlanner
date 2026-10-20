# API Gateway Rate Limiter: recall card

> **Hook:** Match rules locally → Check deny cache or lease → One Lua call to Redis → 429 with Retry-After → Shed load → Fail open

**P · Problem:** It's really a distributed counter on the hot path that must be fast, roughly global and never an outage.

**N · Numbers:**
1. 1M requests/s with 2 rules is 2M Redis ops/s, so we need about 30 sharded primaries, not replicas.
2. 10M keys need only 3 GB, so CPU, not memory, is the constraint.
3. The top 1% of keys send 60% of traffic, so leasing 50 tokens cuts their calls 50x.

**H · Hard part:** Enforcing one quota across 400 gateway nodes in under a millisecond, while hot keys and a sick Redis threaten the hot path.

**B · Boxes:** `Client → Gateway auth → RateLimitFilter → Redis Cluster → Load shedder → Backend APIs`

Side path: `Rules service + Postgres → versioned snapshot → gateways`.

**D · Decisions:**
1. Regional Redis over in-process or global counters, because in-process allows N times the limit and global costs 60-150 ms.
2. Fail open over fail closed, because a limiter outage must not become an API outage.
3. Regional shares over cross-region checks, because a 5 s rebalance bounds the error without a remote hop.

**F · Failures:**
1. Redis shard primary crashes → calls time out at 5 ms and fail open; replica promoted in 10-15 s.
2. Whole Redis cluster unreachable → each gateway enforces limit divided by fleet size locally; the shedder protects backends.

**C · Close:** "So the limiter is a filter inside every gateway. A token bucket per key lives in a sharded regional Redis, updated by one atomic Lua script that uses Redis time. Rules are pushed, versioned and shadow-tested. Redis CPU is the bottleneck, so I shard, cache denies and lease tokens for hot tenants. A load shedder reserves capacity for critical calls, and with a 5 ms timeout the limiter fails open."

**Quiz yourself:**
1. Why not GET then SET? → Two nodes would both see the last token; the Lua script is atomic.
2. What does a sliding window counter fix? → The fixed window allowing 2x the limit at a boundary.
3. Does sharding fix a hot key? → No; split it into sub-buckets or lease tokens to gateways.
