# Design a counter service that avoids hot keys (likes, views, inventory-style counts): the 5-page summary

A counter service for likes and views must survive one viral post taking 500,000 increments a second, all aimed at the same shard, row lock or Redis thread. The single most important idea: partitioning spreads keys, not load per key, so a hot key needs in-memory aggregation and sub-counters, which trade a few seconds of freshness for scale.

## Page 1. The problem, scope and numbers

**Pitch:** show likes, views and shares on every post, scaling with virality without hurting other keys on the same shard, never double counting a like.

**Who uses it:** viewers and likers (see counts, see their own like at once), feed and post services (batch-read 50 counts per page), creators (payouts from view counts, so auditable), ops (see the hot keys).

**In scope:**
- **Increment and decrement** named counters (post:{id}:likes, post:{id}:views), optional idempotency key.
- **Likes as idempotent edges:** the count is derived only from real edge inserts and deletes.
- **In-memory aggregation:** sum deltas per key, flush every 1 s.
- **Hot-key splitting:** adaptive N sub-counters, merged into a materialised total.
- **Batch read** of up to 100 counters; **daily reconciliation** against source events.

**Out of scope:** inventory and quota counters that must never overshoot (a follow-up only), bot and fraud filtering of views, long-term time series of counts.

**Non-functional targets:**
- **Throughput:** 2M increments/s global, 500,000/s on a single key, no errors.
- **Read latency:** p99 under 10 ms for a batch of 50.
- **Freshness:** under 5 s p99 from increment to visible count.
- **Accuracy:** likes exact after reconciliation; views within 0.1% intra-day.
- **Availability:** 99.99% for reads; writes degrade to buffering, not errors.
- **Durability:** no lost likes; views may lose one flush window per failed node.

**Capacity math (1B keys, 200k increments/s average, 2M/s peak):**
- **Storage:** 1B x (24 B key + 8 B value + about 30 B overhead) = about 60 GB, 180 GB with 3 replicas. Tiny, so this is a throughput problem, not a size problem.
- **Hot key, naive:** 500,000 writes/s on one partition. A Redis shard does about 100,000 ops/s, a SQL row a few thousand. So one key cannot live in one place.
- **Hot key, aggregated:** spread over 100 ingest nodes, each sees about 5,000/s and flushes once a second, so the store sees about 100 writes/s for that key: 5,000x fewer.
- **Global flushes:** each node flushes at most the distinct keys it saw; Zipf skew (a few keys get most traffic) cuts the 2M/s worst case to about 300,000 deltas/s.
- **Reads:** 5M counters/s at 100,000 ops/s per Redis shard is about 50 shards plus replicas. So hot read keys also get an in-process cache with 1 s TTL.

## Page 2. The architecture

```
 Clients -> API / LB -> Ingest node (x100)
                         | 1. like? -> Edge store insert-if-absent
                         | 2. delta -> in-memory aggregator, flush every 1 s
                         | 3. count-min sketch -> Hot Key Detector -> etcd
                         v
              Kafka counter-deltas (partition = hash(key, sub_shard))
                         |
              Counter writers: UPSERT counter_shard(key, s) += delta
                         v
              Counter store (Cassandra, RF=3) <-- daily reconciliation
                         |
              Rollup: total(key) = sum(shards), every 1-2 s, active keys only
                         v
              Read cache (Redis total:{key}, TTL 5 s) + in-process hot cache
                         ^
 Feed / Post service -- batchGet(keys) --+   (etcd: N shards per hot key)
```

- **Ingest nodes:** validate, dedupe likes via edges, aggregate deltas, flush to Kafka.
- **Edge store:** source of truth for likes; insert-if-absent per (post, user).
- **Aggregator:** per-node map of key to pending delta; swapped and flushed each second.
- **Hot Key Detector:** count-min sketch plus top-1,000 heap; promotes keys above 1,000/s.
- **Kafka:** durable, replayable delta buffer; a hot key's sub-shards span partitions.
- **Counter writers:** apply deltas, checkpointing Kafka offsets for idempotency.
- **Rollup:** sums sub-counters of recently changed keys into a total.
- **Read cache:** Redis totals, in-process LRU, single-flight on miss.

**Flow A: like on a viral post**
1. POST like with an idempotency key; any ingest node inserts edge (P, U) IF NOT EXISTS.
2. Edge existed: return the count, no delta. New: +1 into the aggregator.
3. Each second the node flushes {post:P:likes: +4,812} to a random sub-shard of N (say 32).
4. Writer adds 4,812 to that row; rollup sums 32 shards and writes the total to Redis.
5. The liker gets cached total + 1, so their screen updates at once.

**Flow B: feed reads counts**
1. Feed calls batchGet for 50 keys; in-process cache first, then Redis MGET.
2. On a miss, one single-flight read per key fills Redis with TTL 5 s; p99 under 10 ms.

## Page 3. The core deep dives

### 1. Swap-and-flush aggregation
Increments go into a concurrent map. Every second the map is atomically swapped for an empty one and the old map is sent as one batch. Increments are commutative, so they merge without loss: 5,000 likes on one node become one +5,000 record. This bounds both memory and the loss window to one interval. Likes are safe even if a node crashes, because their truth is the edge table; only view deltas risk that 1 s window, which product accepts.

### 2. Adaptive sub-counters and hot-key detection
A count-min sketch estimates each key's frequency in fixed memory (4 hash rows x 65,536 counters); it never underestimates. With a top-K heap it finds heavy hitters each second, and counts decay by half each window. A coordinator sums node reports: 300,000/s at no more than 5,000 writes/s per shard gives N = 64 (a power of two, capped at 256). N is versioned in etcd and reaches nodes within 1 s. No migration: the old row becomes shard 0, new shards start at 0, and rollup sums every shard ever used (max N). After 10 minutes cold, a compaction folds shards back into shard 0.

### 3. Exactly-once effect for likes
Mobile clients retry. Shreya taps like, times out, and the app retries three times; insert-if-absent applies only the first, so one +1. If she likes on her phone and unlikes on her tablet, only real state transitions emit deltas, so the net matches the final state. Kafka is at-least-once, so writers store the last applied offset per partition atomically with the update; a replayed batch is skipped.

### 4. Reads never fan out
5M reads/s cannot each sum 64 shards. Rollup materialises a total for active keys only, so cost tracks activity, not key count. A celebrity post read by millions hits an in-process cache on each API node, so its Redis shard sees one fetch per node per second.

**Data model:**
- **like_edge** (Cassandra): partition (post_id, bucket = hash(user_id) % 16 for hot posts), clustering user_id.
- **counter_shard:** partition (key, shard), so sub-counters land on different nodes.
- **counter_total** (store + Redis): key, total, as_of, shard_count; Redis TTL 5 s.
- **hot_key_config** (etcd): key, N shards, version, expires_at; a few thousand rows.
- **writer_checkpoint:** partition -> last applied offset.

**Key APIs:**
- `POST /v1/posts/{post_id}/like`: edge insert-if-absent; a delta only if new.
- `DELETE /v1/posts/{post_id}/like`: -1 only if a row was actually deleted.
- `POST /v1/counters/{key}:increment`: views path; returns cached total + delta.
- `POST /v1/counters:batchGet`: from caches; as_of tells clients the staleness.
- `GET /internal/hotkeys?limit=100`: ops visibility.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Single-key writes:** more ingest nodes raise aggregation; N grows to 256 sub-counters at 5,000 writes/s each.
- **Hot edge partitions:** viral posts spread like edges over 16 buckets.
- **Hot reads:** in-process caches on every API node absorb them.
- **Multiple regions:** region id is part of the sub-counter id, so each region writes only its own rows and totals sum regions (a CRDT counter, conflict-free).
- **Bots:** per-client and per-IP limits at the edge; views counted from deduped sessions.

**Failure modes:**
- **Ingest node crash:** up to 1 s of its view deltas lost; likes unaffected; the LB routes elsewhere.
- **Kafka leader failover:** idempotent producers retry; aggregators keep buffering, then flush early.
- **Counter store slow:** writers back off with jitter; Kafka absorbs backlog; reads serve last totals with a growing as_of.
- **Redis shard fails:** replica promoted; misses go to the store with single-flight.
- **Detector misses a spike:** aggregation still caps the store at about 100 writes/s per node for that key; promotion follows in seconds.
- **Rollup lag:** totals go stale, nothing is lost (sub-counters hold truth); alert over 10 s.
- **Count dips on refresh:** clients keep max(local, server); increment-only totals never go down.

**Trade-offs chosen:**
- **Aggregate on ingest nodes over clients or after Kafka:** the biggest cut before any shared resource; clients cannot be trusted.
- **Adaptive N over a fixed large N:** most keys are cold, and a big fixed N multiplies read and storage cost.
- **Materialised total over sum-on-read:** 2-5 s staleness is fine; fanning out 5M reads is not.
- **Edge table as like truth over a bare counter:** idempotent, auditable, answers "did I like this".
- **Accept a 1 s view loss over logging every view:** logging costs 100x more writes; payouts use the raw event pipeline.
- **Cassandra plus Redis over Redis alone:** Redis is single-threaded per shard and can lose acknowledged writes on failover.

**What to measure:** top-K keys by write and read rate, partition skew ratio in the store and Kafka, aggregator flush size and latency, writer consumer lag, rollup lag and staleness p99 (now - as_of), drift between reconciled and live values, edge conflict rate (detected retries), batch read p99 and hit rate per cache tier.

## Page 5. Say it in the interview

> "First I clarify the kind of count. Views can be approximate and a few seconds stale; likes must be exact and idempotent per user; inventory I treat separately. I assume 2 million increments a second at peak, one viral key at 500,000 a second, and 5 million reads a second. A naive INCR breaks: one Redis shard does about 100,000 operations a second. So three moves. The like edge is the source of truth and the count is derived, so retries never double count. Ingest nodes aggregate increments in memory and flush every second, which shrinks 500,000 writes to about a hundred. Hot keys split into sub-counters whose total is rolled up and cached. Then I defend detection with a count-min sketch, reads that never fan out, what a crash loses, and reconciliation."

**Key points to land:**
- Partitioning distributes keys, not load per key.
- Aggregate in memory, flush every second: 5,000x fewer writes on a viral key.
- Adaptive N sub-counters, merged into a materialised total for reads.
- Likes are idempotent edges; the count is derived and reconcilable.
- At-least-once delivery plus offset-checkpointed apply gives exactly-once effect.
- Count-min sketch plus top-K finds hot keys in fixed memory.
- Write-hot: aggregate and split. Read-hot: cache and replicate.
- Per-region slots make multi-region counters conflict-free.
- Approximate for display; exact for payouts and inventory, by other mechanisms.

**Likely follow-ups:**
1. **Flash-sale inventory that must not oversell?** Use reservations, not a display counter: split stock into buckets, each decremented atomically only if above 0 (a Redis Lua script), and rebalance when one empties.
2. **Why not Redis INCR on Redis Cluster?** It shards by key, so one hot key still sits on one single-threaded shard, and async replication can lose acknowledged increments.
3. **How does the liker see the like instantly?** The response returns cached total + 1 and the client keeps an optimistic adjustment until the server catches up.
4. **How do you reconcile?** A daily batch counts edges and fraud-filtered raw views per post and writes corrections as deltas to shard 0.
5. **What if counts had to be exact and real time?** Drop the buffer, log every increment to Kafka with pre-sharded keys, and use Flink with exactly-once checkpoints and 100 ms windows, at higher cost.

**Director layer:**
- **Cost drivers:** about 50 Redis shards plus replicas for reads, the Kafka delta stream, Cassandra at RF=3. Storage (about 180 GB) is not the cost; throughput is.
- **Phasing:** edge-based likes and aggregation first; then adaptive sub-counters and rollup; then multi-region slots and Flink if needed.
- **Team ownership:** a counters platform team owns ingest, Kafka, store and rollup; feed teams consume batchGet; payouts own the reconciled pipeline.
- **Top risks:** approximate counts used for payouts, detection lagging a spike, unlike races making counts negative, aggregator crashes losing buffered views.
