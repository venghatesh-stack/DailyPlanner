# Design a likes and reactions counter at scale: the 5-page summary

A like button looks trivial until a viral post takes 100K reactions per second on one key. The single most important idea: separate the exact fact (did user U react to post P, and how) from the derived aggregate (how many reactions of each type), make the fact idempotent and let the count be a few seconds stale.

## Page 1. The problem, scope and numbers

**Pitch:** fast, idempotent reaction writes and cheap batched count reads on every feed impression, with counts that are eventually exact and never break on a hot post.

**Why now:** today a counter column on the post row is incremented in place. During live events, viral posts cause lock contention, timeouts and lost likes, and retries inflate counts that creators notice.

**Who uses it:** viewers (instant feedback, credible counts), creators (accurate counts, reactor lists), feed and ranking teams (batched reads, a delta stream), the integrity team (void bot reactions) and SRE (no hot-row incidents).

**In scope:**
- **Set, change or remove** a reaction per (user, object), idempotently; six types (like, love, haha, wow, sad, angry).
- **Per-object counts** per type plus a total; batch read of up to 100 objects.
- **Viewer's own reaction** for a batch of objects, and a paginated reactor list.
- **Delta stream** for ranking, notifications and analytics.
- **Voiding** reactions from banned actors, with a recount.

**Out of scope:** ranking by reactions, live WebSocket push of counts to every viewer, custom emoji, creator analytics UI.

**Non-functional targets:**
- **Latency:** write p99 under 50 ms; batch read of 50 objects p99 under 10 ms.
- **Freshness:** others see a change within 5 s p99; the actor sees it immediately.
- **Availability:** 99.99% for writes and reads.
- **Consistency:** per-user state linearizable per (user, object); counts eventually consistent.
- **Durability:** no acknowledged reaction lost (RF 3, quorum writes); 100K/s on one object without errors.

**Capacity math (500M DAU, 20 reactions and 100 impressions per user per day):**
- **Writes:** 10B / 86,400 = about 115K/s, 580K/s at a 5x peak. So the write path cannot touch a shared row.
- **Count reads:** 50B / 86,400 = about 580K objects/s, up to 3M/s at peak; batched by 30, about 20K requests/s. So reads come from memory, in batches.
- **Reaction rows:** 10B x 65 B = 650 GB/day, about 240 TB/year logical, 720 TB with RF 3. So a wide-column store, with tiering of old partitions.
- **Counters:** 2B objects x 64 B = 128 GB. It fits in a Redis cluster of about 20 shards, so serve counts from RAM with a durable copy behind.
- **Coalescing:** with a 1 s window, a 100K/s object becomes 6 increments per second (one per type). So skew, not total volume, is the hard part.
- **Deltas:** 580K msgs/s x 60 B = about 35 MB/s on 256 Kafka partitions.

## Page 2. The architecture

```
 Client (optimistic UI)
   | PUT reaction                               GET feed
   v                                               |
 Reaction Svc --LWT upsert--> Reaction Store       v
   |  (delta only if changed)  (Cassandra)    Feed / Count Read API
   v                                          (near cache, 1 s TTL)
 Kafka: reaction-deltas --> ranking, notifs,      |  MGET     ^
   | (key = object_id)       analytics            v           |
   v                                          Redis counters  |
 Counter Aggregator --HINCRBY batched-------> cnt:{obj}       |
   | (coalesce 1 s / 1,000)                   hot: 16 shards  |
   v                                                          |
 Snapshotter --> Count Store (counts + Kafka offset) ---------+
 Reconciler and Void job --> compensating deltas into Kafka
```

- **Reaction Service:** idempotent compare-and-set per (object, user); computes the delta.
- **Reaction Store (Cassandra):** source of truth, partitioned by object, clustered by user.
- **User Reaction Index:** (user, object) table plus Bloom filter for viewer-state lookups.
- **Kafka reaction-deltas:** durable ordered deltas keyed by object; feeds every consumer.
- **Counter Aggregator:** coalesces deltas, applies batched increments, detects hot keys.
- **Redis counters:** hot serving copy, a hash per object with a field per type.
- **Snapshotter and Count Store:** every 30 s persist changed counts with their Kafka offset.
- **Count Read API:** batch MGET, 1 s near cache, Count Store fallback.
- **Reconciler and Void job:** recount from truth; emit negative deltas for bans.

**Flow A: react or change reaction**
1. Client shows "love" at once and sends PUT with a request id.
2. Service reads row (P, U) at LOCAL_QUORUM: old = like, version 3.
3. Conditional write type=love IF ver = 3; on conflict re-read; if new equals old, return with no delta.
4. Delta {like -1, love +1, total 0} goes to Kafka keyed by P (outbox or acks=all).
5. Respond 200 with the new state.

**Flow B: aggregate and read**
1. Aggregator sums a poll of 5,000 deltas per (object, type) and flushes every 1 s.
2. HINCRBY to Redis, then commit the Kafka offset; snapshots every 30 s.
3. Feed hydrates 30 posts: near cache, then Redis MGET, then Count Store; viewer state via Bloom filter.

## Page 3. The core deep dives

### 1. Idempotent state, deltas only on real change
The API expresses desired state ("my reaction is love"), not an action ("add one"). The service reads the row, and if the new type equals the old, it returns without emitting anything, so a client retry after a timeout changes nothing. Otherwise it writes with a version compare-and-set (Cassandra LWT, a Paxos-backed conditional write). Example: Shreya taps like, then love, then unlike within 300 ms from two devices. Each successful CAS emits its own delta (+like; -like +love; -love), and the deltas sum to her final state: nothing. Counts can only change through a delta derived from a real transition.

### 2. The hot key: coalesce, then shard, then cache
A live India vs Pakistan post gets 100K reactions/s. Step one, coalescing: the aggregator sums deltas in memory per (object, type) for 1 s or 1,000 events, so Redis sees about 6 increments per second, not 100K. Step two, adaptive sharding: when a key exceeds 5,000 deltas/s it switches to 16 sub-counters cnt:{P}:s0..s15; readers sum all 16 in one pipelined call. After 10 quiet minutes they fold back. Step three, a 1 s in-process near cache on feed servers absorbs the read storm. The Cassandra partition for a huge object is bucketed by hash(user) mod 64 to spread writes.

### 3. Exactly-once effect on counters
Kafka delivers at least once. If the aggregator crashes after HINCRBY but before committing the offset, the batch would be applied twice. Fix: each flush writes the batch's last offset per partition into Redis inside the same MULTI transaction (an offset fence); on restart, records at or below the fence are skipped. All deltas for an object sit on one partition, so they stay ordered.

### 4. Rebuild and reconcile
Counts are derived, so losing Redis is recoverable: load the snapshot (it records Kafka offset O), replay deltas from O (sums commute, so order in the window does not matter). Kafka keeps 7 days. A reconciler recounts sampled or flagged objects from the truth store and fixes drift.

**Data model:**
- **reaction** (Cassandra): PK ((object_id, bucket), user_id); type, ver, updated_at.
- **reactor_by_time**: ((object_id, type, day), reacted_at DESC, user_id) for newest-first lists.
- **user_reaction**: PK ((user_id), object_id); one partition read per feed page.
- **counter** (Redis): cnt:{object_id} hash; snapshot row with kafka_partition and offset.
- **delta event** (Kafka): event_id, object_id, user_id, old_type, new_type, source.

**Key APIs:**
- `PUT /v1/objects/{id}/reaction`: set desired type; same final state on retries.
- `DELETE /v1/objects/{id}/reaction`: idempotent; deleting nothing returns 200, no delta.
- `GET /v1/objects/counts?ids=...&viewer=me`: batch counts plus own reaction.
- `GET /v1/objects/{id}/reactors?type=&cursor=`: paginated reactor list.
- `POST /internal/v1/void`: integrity only; async negative deltas.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot keys:** coalescing gives a 10-100x cut in counter writes; shard only keys above 5K/s.
- **Count reads:** batch MGET plus a near cache; single-flight loads so 10K readers of a cold, suddenly viral post trigger one Count Store read.
- **Reaction Store:** partition by object, bucket huge objects, tier old partitions to cheaper storage.
- **Aggregator:** scale consumers with the 256 partitions; autoscale on lag.

**Failure modes:**
- **Aggregator lag or poison message:** counts stale, writes and own-state unaffected; DLQ after 3 tries; alert at 30 s lag.
- **Redis shard lost:** reads fall back to snapshots (up to 30 s stale); rebuild from snapshot plus replay.
- **Cassandra node down:** RF 3 with LOCAL_QUORUM, and LWT still works with 2 of 3.
- **Kafka down:** truth plus outbox rows are written; the relay publishes later; counts stale meanwhile.
- **Bug double-applies deltas:** reconciler detects drift; recount or rebuild from a pre-bug snapshot.
- **Surge beyond capacity:** rate-limit 10 writes/s per user, degrade reactor lists first, keep serving counts.

**Trade-offs chosen:**
- **Async aggregation over synchronous increments:** 1-5 s of staleness instead of write latency tied to hot rows.
- **Exact-eventually over HyperLogLog:** per-user facts already exist; HLL cannot handle unlikes.
- **Adaptive over always-on sharding:** 99.9% of objects are cold; sharding all multiplies reads.
- **Redis plus snapshots over Cassandra counters:** Cassandra counters are not idempotent on retry.
- **Custom aggregator first, Flink later:** small and clear now; Flink when more windows are needed.
- **Keep rows, tier storage:** rows are needed for uniqueness and voiding.

**Multi-region:** per-region counter slots (a CRDT-style PN counter) summed on read; each user's rows written in their home region, so one writer per user.

**What to measure:** write p99 and CAS conflict rate, delta-to-visible lag (p95 under 2 s, p99 under 5 s), consumer lag per partition, top hot keys, Redis and near-cache hit rate, drift from the recount sample (under 0.01% of objects off by more than 0.1%), void backlog.

## Page 5. Say it in the interview

> "I will assume six reaction types, one changeable reaction per user per object, 10 billion writes a day and 50 billion count reads. Others can see a count a few seconds stale, but the person who reacted must see it instantly. The naive design, likes = likes + 1 on the post row, serialises every like on a viral post behind one row lock and double counts on retries. So I separate the fact from the aggregate. The fact is an idempotent upsert in a reaction store partitioned by object. Only if state actually changed do we emit a delta to Kafka keyed by object. An aggregator coalesces for a second and applies one increment per object and type to Redis, with durable snapshots behind it. Hot keys get sharded sub-counters and a near cache. If anything downstream fails, counts get stale, never wrong for long."

**Key points to land:**
- Separate the fact (U reacted T to P) from the aggregate (counts per type).
- The API expresses desired state, so retries are no-ops; deltas only on real change.
- Hot keys are the real problem: coalesce first, shard adaptively second, near cache third.
- Counts eventually consistent in seconds; the actor's own state is read-your-writes.
- Offset fence written atomically with increments: no double apply after a crash.
- Snapshot plus Kafka offset makes every counter rebuildable.
- Correctness is proven by recounting from facts.
- Multi-region: per-region counter slots and a home region per user.
- Show compact counts (1.2K) truncated, never rounded up, so a count never appears to drop.

**Likely follow-ups:**
1. **Why not HyperLogLog?** It estimates distinct counts with about 0.8% error but cannot remove elements, so it fails on unlikes; it suits unique-viewer counts.
2. **"Shreya and 3 friends reacted"?** Intersect the viewer's friend list with reactors: batch-check user_reaction for small lists, a per-object Bloom filter for large ones; cache briefly.
3. **Live counts during a match?** For hot posts only, a broadcaster reads the summed counter once a second and fans out deltas over WebSocket through a pub/sub tree.
4. **Creators want exact counts now?** Recount that one object from the truth store, or read Redis plus the unflushed buffer; don't change the global design.
5. **How do you test correctness?** Property tests on the delta function, chaos tests killing aggregators mid-flush, and a continuous reconciler alerting on drift.

**Director layer:**
- **Cost drivers:** about 720 TB/year of replicated reaction rows (managed by tiering), a 128 GB Redis tier of about 20 shards, Kafka at 35 MB/s peak.
- **Phasing:** start with the custom aggregator and adaptive sharding; add Flink, live push and friend snippets as features grow.
- **Team ownership:** reactions platform owns truth and counters; integrity owns voids; ranking and notifications consume the delta stream.
- **Top risks:** hot-key overload in live events, double counting from retries, drift after partial failures, like farming, counter store loss.
