# Design a real-time gaming leaderboard: the 5-page summary

A leaderboard is a ranking problem disguised as a storage problem: "what is my rank among 100 million players" is a full scan in SQL but O(log n) in a sorted structure like a Redis sorted set. The single most important idea: keep scores durable in Kafka and a score store, and treat Redis as a fast, rebuildable ranking projection that only server-validated scores can reach.

## Page 1. The problem, scope and numbers

**Pitch:** show every player their updated rank within about a second of a match ending, with top-N, my-rank and around-me answered in under 50 ms, and boards players trust (no slow, wrong or cheater-dominated ranks).

**Who uses it:** competitive players (exact rank, top 100, the players just above to chase), casual players (friends board, "top 12 percent"), and live-ops managers (spin up a weekend event board with custom scoring).

**In scope:**
- **Score ingest:** idempotent events from game servers (match_id, user_id, points, ts).
- **Boards:** all-time, monthly, weekly, daily, regional and event boards.
- **Queries:** top N (N up to 100), my score and rank, K neighbours above and below.
- **Friends board:** up to 500 friends.
- **Admin:** create and close boards, ban or shadow-ban, recompute from source.
- **Season close and push:** snapshot final standings; push top-N and rank changes.

**Out of scope:** skill rating (Elo, TrueSkill) and matchmaking, reward fulfilment, client-side anti-cheat (we consume its signals), the social graph (we read friend lists).

**Non-functional targets:**
- **Freshness:** a new score visible in rank within 1 s p99.
- **Read latency:** p99 under 50 ms for top-N, my-rank, around-me.
- **Write throughput:** 30k score events/s peak, 3x headroom.
- **Availability:** 99.9%; degraded mode serves cached top-N.
- **Durability:** no score event lost; ranking index rebuildable in under 30 minutes.
- **Correctness:** deterministic tie-break; exact rank for the top 10k; scores server-authoritative.

**Capacity math (50M DAU, 10 matches each, 100M players on the monthly board):**
- **Matches:** 50M x 10 = 500M/day = 5.8k/s; peak 3x = 17k/s; plan 30k/s for events.
- **Redis writes:** 5 boards per match x 17k = 87k sorted-set updates/s. Spread across boards on different shards, each board stays well under 100k ops/s, so shard by board first.
- **Reads:** about 87k QPS at peak (5:1 read to write per match). So top-N comes from a 1 s cache and rank queries from replicas.
- **Memory:** about 100 B per entry; 100M x 100 B = 10 GB per board. So one board fits one node, roughly 30-35 GB for the set of boards plus replicas.
- **Durable events:** 500M x 100 B = 50 GB/day in Kafka; 7 days x 3 replicas = about 1 TB.
- **Rebuild:** 100M rows pipelined at about 1M ZADD/s per shard = about 2 minutes per board. So Redis can safely be a projection.

## Page 2. The architecture

```
 Game servers (authoritative) -- signed match result --> Kafka (matches)
                                                            |
                                                            v
 Durable score store <-- ledger + totals -- Score validator (dedup,
 (DynamoDB/Cassandra)                       plausibility, anti-cheat)
        |                                       | accepted deltas (Kafka)
        | rebuild                               v
        +------------------------------> LB updaters (per board shard)
                                                | ZADD / Lua
                                                v
 Snapshot job <-- period close --- Redis sorted sets: lb:all, lb:m:2026-10,
 (S3 / warehouse)                  lb:d:2026-10-11, lb:reg:IN (+ replicas)
                                        ^ ZREVRANK        | top-N diff
                                        |                 v
 Clients -> API GW -> Leaderboard API --+       Push svc -> WebSocket
                       | profile cache, social svc (friend ids)
```

- **Game servers:** the only writers; emit signed results with match_id, scores, timestamps.
- **Kafka:** durable buffer and replay log for results and accepted deltas.
- **Score validator:** checks signature, dedups by match_id, caps points per minute, applies anti-cheat signals.
- **Durable score store:** source of truth; match ledger plus per-user per-period totals.
- **Leaderboard updaters:** apply validated scores to each board key, idempotently.
- **Redis sorted sets:** one key per board and period; O(log n) update and rank.
- **Leaderboard API:** top-N, my-rank, around-me, friends; profile join; caching and request collapsing.
- **Push service:** WebSocket fan-out of top-N diffs and "you were overtaken".
- **Snapshot job:** freezes and archives final standings at period close, then TTLs the key.

**Flow A: match end to visible rank**
1. Game server publishes {match_id, user_id, points, ended_at, sig} to Kafka.
2. Validator does a conditional put on match_id; a duplicate is dropped. Suspicious events are held.
3. Validator increments durable totals and emits a delta.
4. Updater writes lb:all, lb:m:2026-10, lb:d:2026-10-11, lb:reg:IN in one pipeline.
5. Client calls GET rank: ZREVRANK plus ZSCORE on a replica; returns rank + 1. Under 1 s end to end.

**Flow B: around-me**
1. r = ZREVRANK lb:m:2026-10 user.
2. ZREVRANGE from max(0, r-5) to r+5 WITHSCORES.
3. Batch-fetch 11 profiles, strip tie-break bits, return ranks r-5 to r+5.

## Page 3. The core deep dives

### 1. Why a sorted set, not SQL
"My rank" is an order-statistic query: SQL must count every higher score, so the cost grows with rank. At 100M rows and thousands of rank queries per second that is too slow. A Redis sorted set is a hash (member to score) plus a skip list with spans; spans let it count positions while descending. ZREVRANK and updates are O(log n); ZREVRANGE is O(log n + m). Top-N in SQL is fine; rank is what breaks it.

### 2. Tie-breaks inside one double
Redis orders by a 64-bit double, then by member name, which is arbitrary for players. To let the earlier achiever win, pack points into the high bits and an inverted timestamp into the low bits. A double holds integers exactly up to 2^53, so points under 2^21 (about 2 million) plus a 32-bit inverted seconds timestamp stay exact. Example: Shreya and Sethu both reach 1,500 points; Shreya got there first, so her inverted timestamp is larger and she ranks higher. Because a plain increment would also add the timestamp bits, the updater writes the absolute encoded value with ZADD from durable totals (or a Lua script that decodes, adds and re-encodes). That also makes replays idempotent.

### 3. Sharding a structure whose point is global order
Shard by board first: each board is about 10 GB and fits a node. If one board outgrows a node, shard it by score range: shard 0 holds the highest scores. Global rank = cached member counts of all higher shards + local rank, still about O(log n). A user crossing a boundary moves (ZREM, ZADD); boundaries rebalance offline. With hash sharding instead, top N is a scatter-gather (each shard's top N, merged with a heap), but an arbitrary user's rank needs a count on every shard.

### 4. Periods and season close
Key names come from the event's ended_at, not the updater's clock. Late results get a 10-minute grace window. The snapshot job pages the old board in 10k chunks to S3, checks count and checksum against the durable store, then sets a 7-day TTL.

**Data model:**
- **Leaderboard sorted set** (Redis Cluster): one key per board+period; hash tags keep a board in one slot.
- **Score ledger** (DynamoDB/Cassandra): PK match_id (conditional put for dedup); GSI user_id + ended_at.
- **Period totals**: PK (board_id, user_id); the rebuild source.
- **Profile cache**: profile:{user_id}, 1 h TTL.
- **Archived standings** (S3 Parquet): partitioned by board_id, immutable.

**Key APIs:**
- `POST /v1/scores` (internal): game servers only, mTLS; idempotent by matchId.
- `GET /v1/leaderboards/{boardId}/top?n=10`: cached 1 s, request collapsing.
- `GET /v1/leaderboards/{boardId}/users/{userId}`: exact rank; percentile = rank / ZCARD.
- `GET .../users/{userId}/around?k=5`: ZREVRANK then ZREVRANGE.
- `GET /v1/leaderboards/{boardId}/friends`: ZMSCORE for up to 500 ids, sorted in memory.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Writes on one board:** batch increments; split the board by score range.
- **Hot top-10 at event start:** cache 1 s, collapse identical requests, push diffs instead of millions of polls.
- **Celebrity rank page (1M views/minute):** cache per-user rank for 1 s and collapse requests.
- **A billion players:** score-range shards with cached sizes; exact ranks for top shards, percentiles from histograms for the long tail.
- **Global players:** one writer region per board, read replicas per region; ranks under 1 s stale away from home.

**Failure modes:**
- **Redis primary fails:** replica promoted in seconds; updater replays recent deltas from Kafka as absolute values to close the replication gap.
- **Whole Redis cluster lost:** serve cached top-N and "rank temporarily unavailable"; rebuild from durable totals, top boards first (about 2 minutes per 100M).
- **Updater lag:** ranks go stale, API shows "updating"; autoscale consumers; alert when lag exceeds 5 s.
- **Durable store throttling:** validator backs off with jitter; Kafka buffers; slower, no loss.
- **Cheat wave:** tighten plausibility caps, hold events, shadow-ban, recompute affected boards from the ledger.
- **Push gateway overload:** update every 5 s, drop intermediate diffs, clients poll slowly.

**Trade-offs chosen:**
- **Redis sorted sets over SQL:** O(log n) rank out of the box; SQL rank is linear in rank.
- **Durable store plus Kafka as truth, Redis as projection:** failover cannot lose scores; rebuild in minutes.
- **Tie-break in the double over app-side ordering:** ranking stays inside Redis; exact under 2^53.
- **Shard by board now, score-range later:** boards fit a node today.
- **Hybrid exact and approximate rank:** precision where players care, percentiles in the long tail.
- **Push top-N, pull personal rank:** shared views compute once; personal views are cheap to pull.

**What to measure:** match end to rank visible (p50, p99); Kafka lag for validator and updaters; Redis ops, memory and replication lag per shard; API p99 per query and top-N cache hit ratio; duplicate, rejected and held events; Redis versus durable totals mismatches; rebuild time (tested regularly); WebSocket fan-out and dropped updates.

## Page 5. Say it in the interview

> "I will assume a mobile game with 50 million daily players and boards for all-time, this month, today, region and friends. Players want top 10, their own rank and the players around them, within a second. Scores come only from game servers, never the client. The heart of it is that rank needs an ordered index: a Redis sorted set updates and ranks in log n, where SQL would count rows. Match results go to Kafka and a durable score store first, after dedup by match id and cheat checks; then updaters write one sorted set per board and period, with the tie-break encoded into the score. Reads hit replicas, top 10 is cached and pushed. At about 100 bytes per entry, 100 million players is 10 gigabytes per board, and the whole board rebuilds from durable totals in about two minutes."

**Key points to land:**
- Rank is an order-statistic query: linear in SQL, O(log n) in a sorted set.
- Sorted set = hash plus skip list with spans.
- Memory: about 100 B per entry, 10 GB per 100M-player board.
- Server-authoritative scores; validator dedups by match_id and filters cheats.
- Kafka and the durable store are truth; Redis is a rebuildable projection.
- Encode the earliest-achiever tie-break into the double, under 2^53.
- One key per board per period; snapshot to S3 at close, TTL old keys.
- Shard by board first, then by score range within a board.
- Exact rank for the top, percentile for the long tail at extreme scale.
- Push top-N diffs once a second instead of millions of polls.

**Likely follow-ups:**
1. **Why not Postgres with an index on score?** Top-N is fine, but my-rank counts every higher score; at 100M rows and thousands of queries a second it is too slow.
2. **Best single score instead of cumulative?** ZADD with the GT flag, tie-break still encoded, so equal bests rank by earliest achievement.
3. **Weekly boards without double writes?** Write each period key per event (a pipeline of 4-5 commands) for freshness; ZUNIONSTORE of dailies only works for small sets.
4. **Remove a cheater retroactively?** Mark banned in the durable store, ZREM from all boards, recompute any snapshot that already rewarded them, log for audit.
5. **How do you test correctness?** Replay a day of production events into staging, compare boards with warehouse totals, and check rank uniqueness and monotonic order.

**Director layer:**
- **Cost drivers:** Redis memory (about 10 GB per large board, times replicas and regions), Kafka retention, WebSocket fan-out capacity for live events.
- **Phasing:** single Redis primary per board with durable store and validator first; then push, regional replicas, and score-range sharding only when a board outgrows a node.
- **Ownership:** game server team owns signed results; leaderboard platform owns validator, Redis and API; trust and safety owns cheat review and bans.
- **Top risks:** a single Redis node bottlenecked during events, data loss on failover, cheaters eroding trust, hot top-10 reads at event start.
