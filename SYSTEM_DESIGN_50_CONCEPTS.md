# System design: the 50 core concepts

Every concept is in the same seven parts, so you can revise it the same way each time: **What it is, Why it matters, How it works, Trade-off, Remember, Say it, Seen in.**

How to study one: read it once, then cover it and say the **Say it** line aloud. Open one **Seen in** design to see the concept used for real.

## Scaling and traffic

### 1. Latency vs throughput

**What it is:** Latency is how long one request takes. Throughput is how many requests the system completes per second.

**Why it matters:** They pull against each other. Tuning for one without naming the other leads to designs that look fast in a demo but fall over under load, or the reverse.

**How it works:**
- Batching raises throughput but adds wait time: Kafka's `linger.ms` of 5-10 ms trades a little latency for far fewer, larger writes.
- Queueing theory: as utilisation passes about 70-80%, queue time and p99 latency climb steeply.
- Quote latency as percentiles (p50, p99), never averages; quote throughput at a stated latency target.

**Trade-off:** Batching, buffering and async pipelines win throughput but hurt tail latency. Do not batch on paths with tight budgets, such as an order-matching engine.

**Remember:** Throughput is the pipe's width; latency is its length.

**Say it:** "I'll state both targets up front, say 50k writes per second at p99 under 100 ms, then choose batching only where the latency budget allows it."

**Seen in:** [Message queue](/interview-prep/design/distributed-message-queue/summary), [Stock exchange](/interview-prep/design/stock-exchange/summary), [Backpressure pipeline](/interview-prep/design/backpressure-pipeline/summary)

### 2. Load balancing

**What it is:** Spreading incoming requests across a pool of servers so no single server is overloaded and failed ones are skipped.

**Why it matters:** It is what lets you add servers to add capacity, and it removes a single server as a point of failure.

**How it works:**
- L4 balancers route by IP and port (fast, connection-level); L7 balancers route by path, header or cookie.
- Algorithms: round robin, least connections, power of two random choices, or hashing for stickiness.
- Health checks (for example every 5 s, eject after 3 failures) take bad nodes out of rotation.
- Long-lived connections such as WebSockets need least-connections plus connection draining on deploy.

**Trade-off:** Sticky sessions keep state local but make load uneven and failover lossy. Prefer stateless servers; use affinity only when state must live in memory.

**Remember:** Balance requests, not servers; stateless backends make it trivial.

**Say it:** "I'll put an L7 load balancer in front of stateless app servers with least-connections routing and active health checks, so I can scale out and lose a node without users noticing."

**Seen in:** [WebSocket scaling](/interview-prep/design/websocket-scaling/summary), [Messaging app](/interview-prep/design/messaging-app/summary), [API monitoring](/interview-prep/design/api-monitoring-alerting/summary)

### 3. Horizontal vs vertical scaling

**What it is:** Vertical scaling means a bigger machine (more CPU, RAM, faster disk). Horizontal scaling means more machines sharing the work.

**Why it matters:** Vertical scaling hits a hardware and cost ceiling and keeps one point of failure. Horizontal scaling has no fixed ceiling but needs the work to be divisible.

**How it works:**
- Stateless tiers (API servers, workers) scale horizontally behind a load balancer and autoscaler.
- Stateful tiers scale horizontally only through sharding and replication, which adds coordination.
- Vertical is often the right first step: one large Postgres box can handle tens of thousands of simple queries per second.

**Trade-off:** Horizontal scaling brings distributed-systems problems: rebalancing, partial failure, consistency. Do not shard early if a bigger box covers the next two years.

**Remember:** Scale up until it hurts, then scale out.

**Say it:** "The API tier is stateless, so it scales out with an autoscaler. For the database I'll scale up first and shard only when the numbers say one primary can't hold the write load."

**Seen in:** [Food delivery](/interview-prep/design/food-delivery/summary), [Auth and sessions](/interview-prep/design/auth-sessions/summary), [Stock exchange](/interview-prep/design/stock-exchange/summary)

### 4. CDN

**What it is:** A content delivery network is a global set of edge caches that serve content from a location close to the user.

**Why it matters:** It cuts latency from hundreds of milliseconds to tens, and it absorbs most traffic so the origin sees only a few percent of requests.

**How it works:**
- Users reach the nearest edge through DNS steering or anycast.
- A miss goes to a regional tier or origin shield, so the origin sees one fetch per object, not one per edge.
- Immutable, versioned URLs (content hash in the path) allow year-long TTLs with no purges.
- Private content uses signed URLs or tokens checked at the edge.

**Trade-off:** Purges take seconds to minutes and personalised responses barely cache. Do not put per-user, rapidly changing data behind a CDN without careful cache keys.

**Remember:** Cache at the edge, version the URL, shield the origin.

**Say it:** "Static assets and media go through a CDN with content-hashed URLs and long TTLs, plus an origin shield, so origin traffic stays under a few percent."

**Seen in:** [Media CDN](/interview-prep/design/media-cdn/summary), [Image sharing](/interview-prep/design/image-sharing/summary), [Signed URLs](/interview-prep/design/signed-urls/summary)

## Caching

### 5. Caching

**What it is:** Keeping a copy of frequently read data in a faster layer, usually memory, so most reads skip the slower source of truth.

**Why it matters:** A good cache cuts database load by 10x or more and drops read latency to sub-millisecond.

**How it works:**
- Cache-aside is the default: read the cache, on a miss load from the database and set with a TTL.
- Write-through updates cache and database together; write-behind writes the cache first and flushes later.
- Layers: browser, CDN, in-process L1 (a few seconds), shared Redis or Memcached.
- Evict with LRU or LFU; aim for a hit ratio above 95%.

**Trade-off:** Every cache adds staleness and a second copy to keep correct. Do not cache data that must be exact on every read, such as balances, without strong invalidation.

**Remember:** A cache is a bet that reads repeat; check the hit ratio.

**Say it:** "I'll use cache-aside on Redis with a TTL of a few minutes plus jitter, and measure hit ratio, because the database is sized for misses, not for total traffic."

**Seen in:** [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Distributed cache](/interview-prep/design/distributed-cache/summary), [URL shortener](/interview-prep/design/url-shortener/summary)

### 6. Cache invalidation

**What it is:** Removing or updating cached copies when the underlying data changes, so readers stop seeing stale values.

**Why it matters:** Stale prices, permissions or inventory cause real bugs. Races between writes, refills and replica lag can pin an old value in the cache for a full TTL.

**How it works:**
- Delete on write, not update: after the database commit, DEL the key and let the next read refill it.
- A CDC stream (Debezium on the binlog) catches writes the application missed.
- Version-guarded sets or leases stop an old value overwriting a newer one.
- A TTL is the safety net: anything missed still expires.

**Trade-off:** Tighter freshness means more invalidation traffic and more misses. Where minutes of staleness are acceptable, a short TTL alone is simpler and safer.

**Remember:** Delete, don't update; TTL is the safety net.

**Say it:** "On write I commit, then delete the cache key; a CDC consumer deletes again as a backstop, and every key has a TTL so any miss heals itself."

**Seen in:** [Cache invalidation](/interview-prep/design/cache-invalidation/summary), [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Authorization (RBAC)](/interview-prep/design/rbac-authorization/summary)

### 7. Cache stampede

**What it is:** When a popular key expires or is deleted, many concurrent requests miss together and all hit the database to rebuild the same value.

**Why it matters:** A key serving 50k requests per second can send thousands of identical queries at once. Pools fill, latency spikes, and the overload can cascade into an outage.

**How it works:**
- Request coalescing (single-flight): one loader per process, others wait for its result.
- A distributed lock or lease (`SET key:lock NX PX 5000`) makes one loader cluster-wide.
- TTL jitter (for example 600 s plus 0-60 s) stops keys expiring together.
- Serve stale while one request revalidates, or refresh early probabilistically (XFetch).

**Trade-off:** Waiters add latency and serving stale data relaxes freshness. For cold, rarely read keys the extra machinery is not worth it.

**Remember:** One miss, one loader; everyone else waits or reads stale.

**Say it:** "For hot keys I'll coalesce misses with a short lock, add TTL jitter, and serve the stale value while one request refreshes it, so an expiry never hits the database a thousand times."

**Seen in:** [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Personalized serving](/interview-prep/design/personalized-fast-serving/summary), [Flash sale](/interview-prep/design/flash-sale/summary)

### 8. Hot keys

**What it is:** A single key, such as a viral post or a flash-sale product, that receives a large share of all traffic.

**Why it matters:** A key lives on one shard, so adding shards does not help. One hot key can saturate a shard's CPU or network while the rest of the cluster idles.

**How it works:**
- Detect with sampling plus a Count-Min Sketch and top-K list.
- Reads: an in-process L1 cache with a few seconds' TTL, or replicate the key across several shards.
- Writes: split a counter into N sub-keys (`likes:123:0..15`) and sum on read.
- Batch writes locally for a second, then flush one increment.

**Trade-off:** Sharded counters make reads costlier and totals briefly approximate. Apply this only to keys you have detected as hot, not to every key.

**Remember:** Sharding spreads keys, not load on one key.

**Say it:** "Traffic is Zipf-shaped, so I'll detect hot keys, serve hot reads from a local L1 cache, and split hot counters into 16 sub-counters summed on read."

**Seen in:** [Hot-key counter](/interview-prep/design/hot-key-counter/summary), [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Likes counter](/interview-prep/design/likes-counter/summary)

## Databases

### 9. Indexes

**What it is:** A separate sorted structure, usually a B-tree, that lets the database find rows by a column without scanning the whole table.

**Why it matters:** An index turns a full scan over millions of rows into a few page reads, the difference between seconds and milliseconds.

**How it works:**
- Composite indexes follow the leftmost-prefix rule: (tenant_id, status, updated_at) serves filters on tenant_id, or tenant_id plus status.
- A covering index holds every column the query needs, so the table is never read.
- Random keys like UUIDv4 scatter inserts across the B-tree; time-ordered IDs append at the right edge.
- Specialised indexes: inverted (full-text), geospatial (geohash, S2), partial and expression indexes.

**Trade-off:** Every index slows writes and uses storage and memory. Do not index low-selectivity columns or add indexes no query uses.

**Remember:** Index for your queries, not your columns.

**Say it:** "I'll design indexes from the top three queries, for example a composite index on tenant, status and updated time, and keep the count low because this table is write-heavy."

**Seen in:** [Multi-tenant schema](/interview-prep/design/multi-tenant-saas-schema/summary), [Unique ID generator](/interview-prep/design/unique-id-generator/summary), [Geo search](/interview-prep/design/geo-search-nearby/summary)

### 10. Query plans

**What it is:** The step-by-step strategy the database optimiser picks to run a query: which indexes, which join order, which partitions to read.

**Why it matters:** The same SQL can take 2 ms or 20 minutes depending on the plan. Most slow queries are a bad plan, not a slow database.

**How it works:**
- `EXPLAIN` shows the chosen plan; `EXPLAIN ANALYZE` runs it and shows real row counts and timings.
- Watch for sequential scans on big tables, bad row estimates, and sorts spilling to disk.
- The optimiser relies on table statistics; stale stats after bulk loads cause bad plans, so run `ANALYZE`.
- Partition pruning only happens if the query filters on the partition key.

**Trade-off:** Hints and forced plans fix one query but break when data shifts. Fix the index, statistics or query shape first.

**Remember:** Don't guess why a query is slow; read the plan.

**Say it:** "Before adding hardware I'd run EXPLAIN ANALYZE on the slow queries, check that partition pruning and the right index kick in, and require a time filter in the API."

**Seen in:** [Events table partitioning](/interview-prep/design/events-table-partitioning/summary), [Time-range queries](/interview-prep/design/time-range-queries/summary)

### 11. Transactions

**What it is:** A group of database operations that succeed or fail together, with ACID guarantees: atomic, consistent, isolated, durable.

**Why it matters:** Without them a crash or race leaves half-done work, such as money debited but not credited, or a seat sold twice.

**How it works:**
- Keep transactions short: no network calls or user think time inside them.
- Use conditional updates (`UPDATE ... WHERE status='AVAILABLE'`) or unique constraints so the database rejects conflicts.
- The transactional outbox writes the business row and the event in one local transaction.
- Across services there is no shared transaction; use sagas with compensating steps.

**Trade-off:** Long or cross-shard transactions hold locks and cut throughput. Avoid two-phase commit across services; prefer local transactions plus idempotent events.

**Remember:** One service, one local transaction; across services, a saga.

**Say it:** "The hold is a single short transaction with a conditional update, so a seat can never go to two people, and the event goes out through an outbox in the same commit."

**Seen in:** [Idempotent processing](/interview-prep/design/idempotent-processing/summary), [Ticket booking](/interview-prep/design/ticket-booking/summary), [Payment system](/interview-prep/design/payment-system/summary)

### 12. Isolation levels

**What it is:** Settings that decide how much concurrent transactions can see of each other's uncommitted or in-flight changes.

**Why it matters:** Weaker levels are faster but allow anomalies such as lost updates and write skew, which cause double bookings and oversold stock.

**How it works:**
- Read committed (Postgres default) avoids dirty reads but allows non-repeatable reads.
- Repeatable read (MySQL InnoDB default) and snapshot isolation give a stable view but still allow write skew.
- Serializable prevents all of these; Postgres uses SSI and aborts conflicting transactions, so callers must retry.
- Targeted fixes at lower levels: `SELECT ... FOR UPDATE`, unique or exclusion constraints, optimistic version checks.

**Trade-off:** Serializable adds aborts and retries under contention. Use it, or explicit locks and constraints, only on the few paths where anomalies cost money.

**Remember:** Snapshot isolation does not stop write skew.

**Say it:** "Most reads run at read committed; for room booking I turn the check-then-insert into a unique slot key, because snapshot isolation alone would let two bookings through."

**Seen in:** [Calendar scheduling](/interview-prep/design/calendar-scheduling/summary), [Payment system](/interview-prep/design/payment-system/summary), [Idempotent processing](/interview-prep/design/idempotent-processing/summary)

## Replication and partitioning

### 13. Replication

**What it is:** Keeping copies of the same data on several machines, usually 3, often in different availability zones.

**Why it matters:** It survives disk, node and zone failures without data loss, and extra copies can serve reads.

**How it works:**
- Leader-follower: one leader orders writes and followers copy its log (MySQL, Postgres, Kafka).
- Synchronous replication waits for replicas before acking (RPO 0); asynchronous acks first and may lose recent writes.
- Kafka commits when all in-sync replicas have the record; `acks=all` with `min.insync.replicas=2` and replication factor 3.
- Leaderless (Dynamo, Cassandra) writes to several replicas with quorums; consensus (Raft) commits on a majority.

**Trade-off:** Synchronous copies add a round trip to every write; async copies risk losing the last seconds on failover. Erasure coding is cheaper than 3x for cold, large objects.

**Remember:** Three copies, three zones; know whether the ack waits.

**Say it:** "Each partition has three replicas across zones; writes need two acks, so we lose no acknowledged data when one zone goes down."

**Seen in:** [Message queue](/interview-prep/design/distributed-message-queue/summary), [Multi-region DR](/interview-prep/design/multi-region-dr/summary), [Object storage](/interview-prep/design/object-storage-s3/summary)

### 14. Read replicas

**What it is:** Follower copies of a database that serve read queries, while the primary handles all writes.

**Why it matters:** Most systems read far more than they write, often 10:1 or more, so replicas scale reads cheaply without sharding.

**How it works:**
- The primary streams its log (WAL or binlog) to replicas, usually asynchronously.
- The app or a proxy routes writes to the primary and reads to replicas.
- Reads that must see a just-made write go to the primary, or wait for the replica to catch up.
- A replica can be promoted if the primary fails.

**Trade-off:** Replicas are slightly behind, so reads can be stale, and they do nothing for write load. If writes are the bottleneck, shard instead.

**Remember:** Replicas scale reads, never writes.

**Say it:** "Browse traffic goes to read replicas behind the cache; anything a user just wrote is read from the primary for a few seconds so they never see it vanish."

**Seen in:** [Uber](/interview-prep/design/uber/summary), [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Image sharing](/interview-prep/design/image-sharing/summary)

### 15. Replication lag

**What it is:** The delay between a write committing on the primary and that write appearing on a replica.

**Why it matters:** Users see their own changes disappear, and a cache refilled from a lagging replica can hold the old value for a full TTL.

**How it works:**
- Normally milliseconds within a region, often hundreds of milliseconds to seconds across regions, and much more under heavy load.
- Monitor it per replica and alert, for example above 5 s; take badly lagging replicas out of rotation.
- Fixes: read-your-writes routing to the primary, LSN or GTID gating, delayed double delete for caches.
- Cross-region, keep writes in a home region and accept a stated RPO.

**Trade-off:** Removing lag means synchronous replication, which slows every write. Usually you bound and route around lag rather than eliminate it.

**Remember:** Async replicas are always a little in the past.

**Say it:** "I'll assume replicas lag by up to a few seconds, route a user's reads to the primary right after they write, and alert when lag passes five seconds."

**Seen in:** [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary), [Cache invalidation](/interview-prep/design/cache-invalidation/summary), [Multi-region DR](/interview-prep/design/multi-region-dr/summary)

### 16. Sharding

**What it is:** Splitting one dataset across several independent databases (shards), each holding a subset of rows.

**Why it matters:** It is the main way to scale writes and storage past a single machine, and it limits the blast radius of one failure.

**How it works:**
- Choose a shard key that matches the main access pattern, such as tenant_id, user_id or show_id.
- Hash sharding spreads load evenly; range sharding keeps ranges together but risks hot spots.
- A routing layer or lookup table maps keys to shards; many logical shards per physical node make rebalancing easier.
- Queries without the shard key become scatter-gather across all shards.

**Trade-off:** Cross-shard joins and transactions become hard, and resharding is expensive. Do not shard until one well-tuned primary truly cannot cope.

**Remember:** Pick the shard key by your most common query.

**Say it:** "I'll shard by tenant_id with 1,024 logical shards on a few physical clusters, so all of one tenant's queries stay on one shard and we rebalance by moving logical shards."

**Seen in:** [Multi-tenant schema](/interview-prep/design/multi-tenant-saas-schema/summary), [Ticket booking](/interview-prep/design/ticket-booking/summary), [Document search](/interview-prep/design/document-search-engine/summary)

### 17. Partition keys

**What it is:** The field whose value decides which partition or shard stores a record, and which records live together.

**Why it matters:** It decides whether load spreads evenly, whether queries hit one partition or all, and whether related events stay in order.

**How it works:**
- Good keys have high cardinality and match the main query: conversation_id for messages, order_id for order events.
- Composite keys bucket by time, such as (conversation_id, month), to cap partition size.
- In Kafka, the same key always goes to the same partition, so ordering holds per key.
- Salt a hot key with a suffix to spread it, then merge on read.

**Trade-off:** A key that spreads writes well may scatter reads, and vice versa. Avoid low-cardinality or monotonic keys like status or raw timestamp.

**Remember:** Same key, same partition, same order.

**Say it:** "Messages are partitioned by conversation_id plus a time bucket, so a chat's recent history is one partition read and no single group chat grows without bound."

**Seen in:** [Messaging app](/interview-prep/design/messaging-app/summary), [Events table partitioning](/interview-prep/design/events-table-partitioning/summary), [Order workflow](/interview-prep/design/order-processing-workflow/summary)

### 18. Consistent hashing

**What it is:** A way to map keys to nodes on a hash ring so adding or removing a node moves only a small fraction of keys.

**Why it matters:** With `hash(key) mod N`, changing N remaps almost every key, emptying caches and forcing mass data moves.

**How it works:**
- Nodes and keys hash onto the same ring; a key belongs to the next node clockwise.
- Adding a node moves only about 1/N of keys.
- Virtual nodes (100-256 per server) even out load and spread a failed node's keys across many peers.
- Redis Cluster uses a variant: 16,384 fixed hash slots assigned to nodes.

**Trade-off:** It does not fix hot keys, and lookups need ring metadata kept in sync. For a fixed small cluster, a simple slot table may be easier.

**Remember:** Add a node, move about 1/N of keys, not all of them.

**Say it:** "I'll place cache nodes on a consistent-hash ring with virtual nodes, so losing one node shifts only its share of keys and spreads them across the rest."

**Seen in:** [Distributed KV store](/interview-prep/design/distributed-kv-store/summary), [Distributed cache](/interview-prep/design/distributed-cache/summary), [Media CDN](/interview-prep/design/media-cdn/summary)

## Consistency and consensus

### 19. CAP theorem

**What it is:** During a network partition, a replicated system must choose between consistency (every read sees the latest write) and availability (every request gets a non-error answer).

**Why it matters:** Partitions will happen, so you must decide in advance which operations refuse requests and which accept possibly stale or conflicting data.

**How it works:**
- CP systems (Raft-based stores, Spanner, ZooKeeper) reject writes on the minority side.
- AP systems (Dynamo, Cassandra) keep answering and reconcile later.
- The choice can differ per feature: payments CP, likes or presence AP.
- It is about partitions only; it says nothing about normal operation.

**Trade-off:** CP costs availability during failures; AP costs correctness and needs conflict resolution. Do not use CAP to describe normal-case behaviour; that is PACELC.

**Remember:** When the network splits, pick: refuse or risk stale.

**Say it:** "Dispatch must never double-assign a driver, so that path is CP and fails closed during a partition; location reads are AP and can be a few seconds stale."

**Seen in:** [Distributed KV store](/interview-prep/design/distributed-kv-store/summary), [Uber](/interview-prep/design/uber/summary), [Multi-region DR](/interview-prep/design/multi-region-dr/summary)

### 20. PACELC

**What it is:** An extension of CAP: if there is a Partition, choose Availability or Consistency; Else, choose Latency or Consistency.

**Why it matters:** Partitions are rare, but the latency cost of strong consistency is paid on every request. PACELC makes that everyday trade-off explicit.

**How it works:**
- PA/EL: Dynamo, Cassandra; fast and available, eventually consistent.
- PC/EC: Spanner and Raft-based stores; every write waits for a quorum, even with no failure.
- Cross-region synchronous replication adds a full round trip, often 50-150 ms, to every write.
- Many systems are tunable per request, such as Cassandra's ONE versus QUORUM.

**Trade-off:** Choosing consistency in the normal case means slower writes everywhere. Choose it only for data where a stale read costs real money or trust.

**Remember:** Even without failures, consistency costs latency.

**Say it:** "In normal operation I'd pick latency for the cache and feed, accepting seconds of staleness, and consistency for orders, accepting a quorum round trip on each write."

**Seen in:** [Distributed KV store](/interview-prep/design/distributed-kv-store/summary), [Multi-region DR](/interview-prep/design/multi-region-dr/summary), [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary)

### 21. Eventual consistency

**What it is:** If updates stop, all replicas converge to the same value. Until then, different readers may see different values.

**Why it matters:** It lets systems stay fast and available across replicas and regions, at the cost of temporary staleness that users can notice.

**How it works:**
- Writes are acknowledged locally and propagate asynchronously, usually within milliseconds to seconds.
- Conflicts are resolved with last-write-wins timestamps, version vectors or CRDTs.
- Anti-entropy and read repair fix replicas that missed updates.
- Session guarantees (read-your-writes, monotonic reads) hide the worst anomalies from users.

**Trade-off:** Readers can see old or out-of-order data, and conflict resolution can silently drop writes. Do not use it for balances, inventory decrements or uniqueness checks.

**Remember:** Converges eventually; promises nothing about right now.

**Say it:** "Like counts and presence are eventually consistent, converging within a second or two, but I'll add read-your-writes so a user always sees their own like."

**Seen in:** [Likes counter](/interview-prep/design/likes-counter/summary), [Chat presence](/interview-prep/design/chat-presence/summary), [Geo search](/interview-prep/design/geo-search-nearby/summary)

### 22. Read-your-writes

**What it is:** A session guarantee that after you write something, your own later reads always show that write.

**Why it matters:** Without it a user posts a comment or likes a photo, refreshes, and it is gone. It looks like data loss even when it is only replica lag.

**How it works:**
- Route the user's reads to the primary for a short window, such as 5-10 s after a write.
- Return a version or LSN token on write; serve reads only from a replica that has reached it.
- Pin a session to one replica, or overlay the user's recent writes on the client.
- Zanzibar-style revision tokens give the same guarantee for permission checks.

**Trade-off:** It adds routing logic and extra primary load. It only covers the writer; other users may still see stale data, which is usually acceptable.

**Remember:** You must see your own writes; others can wait.

**Say it:** "After a user writes, I'll return a version token and serve their reads only from replicas that have caught up, so their own comment never disappears."

**Seen in:** [Likes counter](/interview-prep/design/likes-counter/summary), [Comment system](/interview-prep/design/comment-system/summary), [Object storage](/interview-prep/design/object-storage-s3/summary)

### 23. Quorums

**What it is:** Requiring a minimum number of replicas, W for writes and R for reads, out of N copies to respond before an operation succeeds.

**Why it matters:** Quorums give consistency without a single leader and tolerate some replicas being down or slow.

**How it works:**
- If R + W > N, every read set overlaps the latest write set in at least one replica.
- Common setting: N=3, W=2, R=2, tolerating one failed replica for both reads and writes.
- W=1, R=1 is fastest but only eventually consistent.
- Sloppy quorums with hinted handoff keep writes flowing during failures but break the overlap guarantee.

**Trade-off:** Larger quorums mean higher tail latency, since you wait for the slowest replica in the set. Quorum overlap alone is not linearizability.

**Remember:** R + W > N means reads overlap writes.

**Say it:** "With three replicas I'd use W=2 and R=2, so any read overlaps the last acknowledged write and we survive one node down."

**Seen in:** [Distributed KV store](/interview-prep/design/distributed-kv-store/summary), [Multi-region DR](/interview-prep/design/multi-region-dr/summary), [Video streaming](/interview-prep/design/video-streaming/summary)

### 24. Leader election

**What it is:** A way for a group of nodes to agree on exactly one node to act as leader, such as a single writer, scheduler or partition owner.

**Why it matters:** Many jobs need one owner. Two leaders at once (split brain) cause duplicate charges, forked logs or double-assigned resources.

**How it works:**
- Use a consensus service (etcd, ZooKeeper, a Raft quorum) instead of building your own.
- The leader holds a lease, for example 10 s, and renews it with heartbeats; if it stops, another node takes over.
- Each new leader gets a higher fencing token or epoch; storage rejects writes with an older token.

**Trade-off:** Failover takes seconds, during which writes pause. Do not centralise work in a leader when a partitioned or leaderless design would do.

**Remember:** A lease without a fencing token is not safe.

**Say it:** "Each partition's writer holds an etcd lease with a fencing token, and storage rejects writes with an older token, so a paused old leader can't corrupt anything."

**Seen in:** [Audit log](/interview-prep/design/audit-log/summary), [Stock exchange](/interview-prep/design/stock-exchange/summary), [Message queue](/interview-prep/design/distributed-message-queue/summary)

### 25. Raft

**What it is:** A consensus algorithm that keeps a replicated log identical across a cluster by electing a leader and committing entries once a majority stores them.

**Why it matters:** It gives strongly consistent, fault-tolerant metadata and state machines without a single point of failure. etcd, Consul, CockroachDB and Kafka KRaft use it.

**How it works:**
- A cluster of 2f+1 nodes (3 or 5) tolerates f failures.
- Nodes elect a leader by majority vote for a numbered term; randomised timeouts (150-300 ms) avoid split votes.
- The leader appends entries and commits once a majority has them; followers apply them in order.
- Higher terms fence out old leaders.

**Trade-off:** Every write needs a majority round trip, and throughput is bounded by one leader. Use it for metadata and coordination, not for high-volume data paths.

**Remember:** Majority commits; the term number fences old leaders.

**Say it:** "Metadata lives in a three-node Raft group across zones, so commits survive one zone failure and a new leader is elected within a few seconds."

**Seen in:** [Message queue](/interview-prep/design/distributed-message-queue/summary), [Object storage](/interview-prep/design/object-storage-s3/summary), [Uber](/interview-prep/design/uber/summary)

### 26. Clock skew

**What it is:** Clock skew is the difference between the wall-clock times of two machines. Even with NTP, servers drift apart by milliseconds, and clocks can jump backwards after a sync.

**Why it matters:** Anything that orders events, expires tokens or generates time-based IDs by wall clock can break. Writes can look reversed, tokens expire early, or IDs repeat.

**How it works:**
- NTP keeps skew to a few milliseconds in a datacenter; cloud time services (AWS Time Sync, Google TrueTime) bound it tighter.
- Allow a tolerance window when checking expiry, for example 30 s on signed URLs.
- Refuse to issue IDs if the clock moves backwards (Snowflake-style generators).
- Use logical clocks (Lamport, vector clocks, hybrid logical clocks) when you need ordering.

**Trade-off:** Tolerance windows make expiry less precise, and logical clocks add metadata and complexity. Do not bother when approximate order is good enough, such as analytics timestamps.

**Remember:** Never trust two machines to agree on "now".

**Say it:** "I won't use wall-clock time to order writes across nodes. I'll use a sequence or hybrid logical clock, and allow about 30 seconds of skew on token expiry."

**Seen in:** [Unique ID generator](/interview-prep/design/unique-id-generator/summary), [Signed URLs](/interview-prep/design/signed-urls/summary), [Distributed KV store](/interview-prep/design/distributed-kv-store/summary)

## Messaging and data flow

### 27. Message queues

**What it is:** A message queue is a durable buffer between producers and consumers. Producers write messages and move on; consumers process them at their own pace.

**Why it matters:** It decouples services in time and load: a spike or a failed consumer does not block the request path, and work is not lost.

**How it works:**
- Two families: work queues (SQS, RabbitMQ), where each message goes to one worker and is deleted on ack, and logs (Kafka), where messages are retained and replayable.
- Consumers ack after processing; unacked messages are redelivered after a visibility timeout (SQS default 30 s).
- Messages that fail repeatedly go to a dead-letter queue (DLQ) after, say, 3-5 attempts.
- Watch queue depth and the age of the oldest message.

**Trade-off:** You get eventual consistency, duplicate deliveries and another system to run. Do not use one when the caller needs the result synchronously.

**Remember:** Queues absorb spikes; they do not create capacity.

**Say it:** "The API writes the job to a queue and returns 202. Workers pull at their own rate, retry with a DLQ after five attempts, and we alert on the age of the oldest message."

**Seen in:** [Job queue](/interview-prep/design/job-queue/summary), [Distributed message queue](/interview-prep/design/distributed-message-queue/summary), [Pub-sub notifications](/interview-prep/design/pubsub-notifications/summary)

### 28. Kafka partitions

**What it is:** A Kafka topic is split into partitions, each an ordered, append-only log. Partitions are the unit of parallelism, ordering and replication.

**Why it matters:** They let a topic scale past one machine. Ordering is guaranteed only within a partition, so the partition key decides which events stay in order.

**How it works:**
- The producer hashes the key (for example user_id or order_id) to pick a partition; same key, same partition, same order.
- Each partition has one leader and followers; RF=3 with min.insync.replicas=2 and acks=all is the standard durable setup.
- Within a consumer group, each partition is read by at most one consumer, so partition count caps consumer parallelism.
- Size for peak: at about 10 MB/s per partition, 1 GB/s needs about 100.

**Trade-off:** More partitions mean more open files, longer leader elections and slower rebalances. A hot key still lands on one partition and cannot be spread without losing its order.

**Remember:** Order per key, parallelism per partition.

**Say it:** "I'll key the topic by order_id so each order's events stay in order, and start with 64 partitions so we can scale to 64 consumers."

**Seen in:** [Distributed message queue](/interview-prep/design/distributed-message-queue/summary), [Pub-sub notifications](/interview-prep/design/pubsub-notifications/summary), [Ad click aggregation](/interview-prep/design/ad-click-aggregation/summary)

### 29. Consumer groups

**What it is:** A consumer group is a set of consumers that share the work of reading a topic. Each partition is assigned to exactly one member, and the group tracks its own offsets.

**Why it matters:** Groups give you both scale-out and independent fan-out. Add consumers to process faster; add a new group to let another service read the same stream from its own position.

**How it works:**
- The group coordinator assigns partitions; when a member joins or dies, a rebalance moves partitions (cooperative rebalancing reduces the pause).
- Each group commits its offsets, so search indexing and analytics can read the same topic at different speeds.
- Consumers beyond the partition count sit idle.
- Lag (latest offset minus committed offset) per group is the main alert.

**Trade-off:** Rebalances pause processing and can cause duplicate processing of uncommitted messages. Do not expect per-message routing or priorities; use separate topics for that.

**Remember:** One partition, one consumer per group; groups never steal from each other.

**Say it:** "Notifications and the search indexer are separate consumer groups on the same topic, so each scales and lags independently, and I alert on lag per group."

**Seen in:** [Distributed message queue](/interview-prep/design/distributed-message-queue/summary), [Incremental indexing](/interview-prep/design/incremental-indexing/summary), [Feed notifications](/interview-prep/design/feed-notifications/summary)

### 30. At-least-once delivery

**What it is:** At-least-once delivery means every message is delivered one or more times. Nothing is lost, but duplicates are possible.

**Why it matters:** It is the practical default for queues and streams. Exactly-once delivery across a network is not achievable in general, so systems choose at-least-once and make processing safe to repeat.

**How it works:**
- The consumer processes first, then acks or commits the offset; a crash in between causes redelivery.
- Producers retry on timeout, which can also write the same message twice.
- Pair it with idempotent consumers: dedup on a message ID, or use upserts and conditional writes.
- At-most-once is the opposite: ack first, accept loss. Fine for metrics, not for payments.

**Trade-off:** You must handle duplicates everywhere downstream. Do not choose it where a duplicate side effect cannot be undone and you cannot add a dedup key.

**Remember:** At-least-once delivery plus idempotent processing equals effectively-once.

**Say it:** "Delivery is at-least-once, so every consumer dedups on event_id. Duplicates and replays are then harmless."

**Seen in:** [Job queue](/interview-prep/design/job-queue/summary), [Messaging app](/interview-prep/design/messaging-app/summary), [Idempotent processing](/interview-prep/design/idempotent-processing/summary)

### 31. Idempotency

**What it is:** An operation is idempotent if doing it twice has the same effect as doing it once. In APIs, the client sends an idempotency key so the server can recognise a retry.

**Why it matters:** Retries and at-least-once delivery cause duplicates. Without idempotency, a timeout followed by a retry can charge a card twice or create two orders.

**How it works:**
- The client generates a unique key (UUID) per logical operation and reuses it on every retry.
- The server stores key, request hash and response in the same transaction as the side effect, with a unique constraint; a repeat returns the stored response.
- Keep keys for a bounded window, typically 24 hours to 7 days.
- Prefer naturally idempotent writes: SET over INCREMENT, upserts, versioned conditional writes.

**Trade-off:** You need storage and a lookup on every write, and must define what "same request" means. Skip it for pure reads, which are already safe.

**Remember:** Retries are only safe if the write is idempotent.

**Say it:** "Every payment call carries an idempotency key stored with a unique constraint, so a retry after a timeout returns the original result instead of charging twice."

**Seen in:** [Idempotent processing](/interview-prep/design/idempotent-processing/summary), [Payment system](/interview-prep/design/payment-system/summary), [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary)

### 32. Outbox pattern

**What it is:** The transactional outbox writes a business change and its outgoing event to the same database in one transaction. A separate relay then publishes the event to the broker.

**Why it matters:** It solves the dual-write problem. Writing to the database and then to Kafka separately means a crash in between leaves one done and the other not.

**How it works:**
- In one local transaction: update the orders table and insert a row into an outbox table.
- A relay polls the outbox, or CDC (Debezium) tails the database log, and publishes to Kafka.
- Delivery is at-least-once, so events carry an ID and consumers dedup.
- Mark or delete published rows; keep the outbox small with periodic cleanup.

**Trade-off:** Adds a table, a relay to operate, and a short publish delay (milliseconds with CDC, about a second with polling). Not needed if the event can be lost or rebuilt cheaply.

**Remember:** One transaction, two records; publish later.

**Say it:** "I won't dual-write. The order and its event commit together via an outbox, and Debezium relays the event to Kafka with at-least-once delivery."

**Seen in:** [Order processing workflow](/interview-prep/design/order-processing-workflow/summary), [Follower fanout](/interview-prep/design/follower-fanout/summary), [Payment system](/interview-prep/design/payment-system/summary)

### 33. Sagas

**What it is:** A saga runs a business transaction that spans several services as a sequence of local transactions. Each step has a compensating action that undoes it if a later step fails.

**Why it matters:** Microservices own separate databases, so there is no single ACID transaction. Two-phase commit is slow and blocks when the coordinator fails, so sagas are the usual answer.

**How it works:**
- Example: reserve stock, authorise payment, assign courier; if courier fails, void payment and release stock.
- Orchestration: a central workflow (Temporal, Step Functions) drives the steps; easier to see and debug.
- Choreography: services react to each other's events; looser coupling, harder to follow.
- Steps and compensations must be idempotent and retryable; persist saga state.

**Trade-off:** No isolation: other requests can see intermediate states, and some actions (an email sent) cannot be truly undone. For one database, use a normal transaction.

**Remember:** Every forward step needs a planned undo.

**Say it:** "Checkout is an orchestrated saga: reserve, authorise, confirm, with compensations like void and release, and saga state persisted so a crash resumes where it stopped."

**Seen in:** [Order processing workflow](/interview-prep/design/order-processing-workflow/summary), [Food delivery](/interview-prep/design/food-delivery/summary), [Ticket booking](/interview-prep/design/ticket-booking/summary)

### 34. Change data capture

**What it is:** Change data capture (CDC) streams every insert, update and delete from a database's write log to other systems. Tools like Debezium read the MySQL binlog or Postgres WAL and publish to Kafka.

**Why it matters:** It keeps caches, search indexes and analytics in sync with the source of truth without dual writes. Nothing is missed, because the log records every commit.

**How it works:**
- A connector tails the replication log and emits one event per row change, with before and after values.
- Events are keyed by primary key, so changes to one row stay in order on one partition.
- Consumers update Elasticsearch, invalidate cache keys or load the warehouse.
- An initial snapshot backfills existing rows, then streaming resumes from a log position.

**Trade-off:** Events mirror table schema, so internal schema changes leak to consumers, and there is a lag of milliseconds to seconds. For domain events with business meaning, prefer an outbox.

**Remember:** The database log is the most honest event stream you have.

**Say it:** "Search stays in sync via CDC from the catalog DB's binlog into Kafka, keyed by product_id, with seconds of lag and no dual writes."

**Seen in:** [Cache invalidation](/interview-prep/design/cache-invalidation/summary), [Incremental indexing](/interview-prep/design/incremental-indexing/summary), [Geo search nearby](/interview-prep/design/geo-search-nearby/summary)

## Resilience

### 35. Rate limiting

**What it is:** Rate limiting caps how many requests a client, user or key can make in a time window. Excess requests are rejected, usually with HTTP 429 and a Retry-After header.

**Why it matters:** It protects services from overload, abuse and noisy neighbours, and enforces fair use and paid tiers.

**How it works:**
- Token bucket: capacity C allows bursts, refill rate r sets the average; the most common choice.
- Sliding window counter: smooths the double-burst problem of fixed windows.
- Distributed state in Redis with atomic Lua scripts; or local limits per node for speed.
- Limit by API key, user, IP and endpoint; enforce at the gateway.

**Trade-off:** A central Redis adds a hop (about 1 ms) and a dependency; decide whether to fail open or fail closed if it is down. Local limits are fast but approximate.

**Remember:** Token bucket: bursts up to C, average r.

**Say it:** "I'll use a token bucket per API key at the gateway, backed by Redis with a Lua script, return 429 with Retry-After, and fail open if Redis is unreachable."

**Seen in:** [API rate limiter](/interview-prep/design/api-rate-limiter/summary), [Spam and abuse controls](/interview-prep/design/spam-abuse-controls/summary), [Online judge](/interview-prep/design/online-judge/summary)

### 36. Backpressure

**What it is:** Backpressure is a signal from a slow consumer to its producers to slow down. It makes the system match its intake to what it can actually process.

**Why it matters:** Without it, buffers grow until memory runs out, latency climbs and the whole pipeline falls over. A system that cannot say "slow down" will eventually crash.

**How it works:**
- Bounded queues and buffers; when full, block, reject (429/503) or shed load.
- Pull-based consumption (Kafka consumers fetch at their own rate) is natural backpressure.
- Credit or window-based flow control, as in TCP windows, gRPC streams and Reactive Streams.
- Trigger on queue depth, consumer lag or p99 latency; coalesce or sample low-value writes first.

**Trade-off:** Producers must handle being slowed or rejected, and pressure propagates upstream to users. Unbounded buffering looks fine until it does not.

**Remember:** Every queue must be bounded.

**Say it:** "Each stage has a bounded queue. When indexing lag passes a threshold, we coalesce updates per key and return 429 to bulk producers rather than buffer without limit."

**Seen in:** [Backpressure pipeline](/interview-prep/design/backpressure-pipeline/summary), [Incremental indexing](/interview-prep/design/incremental-indexing/summary), [Job queue](/interview-prep/design/job-queue/summary)

### 37. Timeouts

**What it is:** A timeout bounds how long a caller waits for a response before giving up. Every network call needs one, for connect and for the full request.

**Why it matters:** Without timeouts, a slow dependency ties up threads and connections until the caller itself fails. Slowness spreads further than outright errors.

**How it works:**
- Set the timeout just above the dependency's normal p99, for example p99 of 80 ms gives a 100-150 ms timeout.
- Use a separate, short connect timeout (about 100 ms to 1 s).
- Propagate a deadline: if the user request has 500 ms total, downstream calls get what is left (gRPC deadlines do this).
- Defaults are often far too long or infinite; set them explicitly.

**Trade-off:** Too short causes false failures and retry storms; too long holds resources. A timed-out write may still have succeeded, so pair timeouts with idempotency.

**Remember:** No call without a deadline.

**Say it:** "Each downstream call gets a timeout just above its p99, and we propagate the request's remaining deadline so nothing waits after the user has given up."

**Seen in:** [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary), [Graceful degradation](/interview-prep/design/graceful-degradation/summary), [Payment system](/interview-prep/design/payment-system/summary)

### 38. Retries with jitter

**What it is:** Retrying a failed call after a delay that grows exponentially and is randomised. The randomness (jitter) stops many clients from retrying at the same instant.

**Why it matters:** Transient failures are common and a retry often succeeds. But synchronised, immediate retries multiply load on a struggling service and turn a blip into an outage.

**How it works:**
- Exponential backoff: 100 ms, 200 ms, 400 ms, capped at a few seconds, with 2-3 attempts maximum.
- Full jitter: sleep a random time between zero and the current backoff cap.
- Retry only transient errors (timeouts, 503, connection reset), never 4xx business errors.
- Use a retry budget (for example retries under 10% of requests) and retry at one layer only.

**Trade-off:** Retries add latency and load, and are unsafe for non-idempotent writes. Skip them when the user would rather fail fast, or the dependency is clearly down (let the circuit breaker handle it).

**Remember:** Back off, add jitter, cap attempts, retry at one layer.

**Say it:** "Clients retry at most twice with exponential backoff and full jitter, only on idempotent calls and transient errors, under a 10% retry budget."

**Seen in:** [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary), [WebSocket scaling](/interview-prep/design/websocket-scaling/summary), [Distributed cache](/interview-prep/design/distributed-cache/summary)

### 39. Circuit breakers

**What it is:** A circuit breaker stops calls to a dependency that is failing. After a cool-down it lets a few test calls through, and closes again if they succeed.

**Why it matters:** It fails fast instead of waiting on timeouts, frees the caller's threads, and gives the failing service room to recover rather than being hammered.

**How it works:**
- Closed: calls flow; track failure rate over a window (for example over 50% errors across at least 20 calls).
- Open: reject immediately for a cool-down, typically 5-30 s, and serve a fallback.
- Half-open: allow a few probe calls; success closes, failure reopens.
- Libraries: Resilience4j; service meshes such as Envoy offer outlier detection.

**Trade-off:** Badly tuned breakers trip on small blips or stay open too long, and need a sensible fallback. Not useful for a dependency with no alternative and no time pressure.

**Remember:** Closed, open, half-open: fail fast, then probe.

**Say it:** "If the recommendations service errors over 50% for 10 seconds, the breaker opens and we show cached popular items; it probes again after 30 seconds."

**Seen in:** [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary), [Graceful degradation](/interview-prep/design/graceful-degradation/summary), [Payment system](/interview-prep/design/payment-system/summary)

### 40. Bulkheads

**What it is:** Bulkheads isolate resources (thread pools, connection pools, queues or whole clusters) per dependency or workload. Named after ship compartments that stop one leak from sinking the ship.

**Why it matters:** Without isolation, one slow dependency can take every shared thread and stall unrelated requests. Bulkheads contain the damage to one feature.

**How it works:**
- Separate thread or connection pools per downstream, for example 20 for payments and 10 for recommendations.
- Separate queues or consumer groups per priority, so bulk jobs never block urgent ones.
- Cell-based architecture: split users into independent cells so a failure hits a fraction of them.
- Combine with timeouts and circuit breakers; reject when a pool is full.

**Trade-off:** Pools are sized separately, so idle capacity in one cannot help another, and there is more to tune. Overkill for a small service with one dependency.

**Remember:** One leak should flood one compartment, not the ship.

**Say it:** "Each push provider gets its own bulkheaded sender pool, so an APNs slowdown cannot delay Android or email notifications."

**Seen in:** [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary), [Feed notifications](/interview-prep/design/feed-notifications/summary), [Read-heavy cache](/interview-prep/design/read-heavy-cache/summary)

### 41. Graceful degradation

**What it is:** Graceful degradation keeps the core product working when parts fail or load is too high, by turning off or simplifying non-essential features.

**Why it matters:** Users accept a page without recommendations; they do not accept a page that will not load. It turns a total outage into a partial one.

**How it works:**
- Rank features: critical (browse, checkout) versus optional (reviews, personalisation).
- Fallbacks: serve stale cache, a static default list, or hide the widget.
- Predefined degradation levels or brownouts, switched automatically on SLO breach or by a kill switch.
- Load shedding: drop low-priority traffic first under overload.

**Trade-off:** Each fallback is code that rarely runs, so it must be tested (game days, chaos tests). Stale or simplified results must be acceptable for that feature.

**Remember:** Protect the checkout; sacrifice the sidebar.

**Say it:** "Under load we step down predefined levels: drop personalised ranking, then reviews, then serve cached listings, while browse and checkout stay at full service."

**Seen in:** [Graceful degradation](/interview-prep/design/graceful-degradation/summary), [Flash sale](/interview-prep/design/flash-sale/summary), [Ranked timeline](/interview-prep/design/ranked-timeline/summary)

### 42. Health checks

**What it is:** Health checks are endpoints or probes that tell a load balancer or orchestrator whether an instance can serve traffic. Unhealthy instances are removed or restarted.

**Why it matters:** They route traffic away from broken nodes automatically, which drives failover and safe rollouts. Bad checks either miss real failures or cause cascading restarts.

**How it works:**
- Liveness: is the process alive? Failing it restarts the container (Kubernetes).
- Readiness: can it serve now? Failing it removes the instance from rotation without a restart.
- Typical cadence: probe every 5-10 s, mark down after 2-3 failures.
- Keep liveness shallow; checking a shared database in liveness can restart every pod during a DB blip.

**Trade-off:** Deep checks catch more but can take the whole fleet out when a shared dependency hiccups. Shallow checks miss partial failures, so pair them with real-traffic metrics.

**Remember:** Liveness restarts; readiness reroutes.

**Say it:** "Readiness checks the instance's own ability to serve; liveness stays shallow, so a database blip does not restart the whole fleet. GeoDNS checks every 10 seconds for regional failover."

**Seen in:** [Multi-region DR](/interview-prep/design/multi-region-dr/summary), [Unique ID generator](/interview-prep/design/unique-id-generator/summary), [Distributed cache](/interview-prep/design/distributed-cache/summary)

## Observability

### 43. Observability

**What it is:** Observability is how well you can understand a system's internal state from its outputs. It rests on metrics, logs and traces, tied together by request IDs.

**Why it matters:** In distributed systems, failures are new and partial. Without good telemetry you cannot detect, locate or explain them, and mean time to recovery grows.

**How it works:**
- Metrics: RED (rate, errors, duration) for services, USE (utilisation, saturation, errors) for resources; Prometheus-style histograms.
- Logs: structured JSON with trace_id; sample high-volume debug logs.
- Traces: OpenTelemetry spans across services show where latency goes.
- Alert on user-facing symptoms (SLO burn), not on every CPU spike.

**Trade-off:** Telemetry costs money and can rival the service itself; high-cardinality labels (per user_id) explode metric storage. Sample traces (say 1-10%) and keep raw logs for limited days.

**Remember:** Metrics tell you that, traces tell you where, logs tell you why.

**Say it:** "Every service emits RED metrics and OpenTelemetry traces with a shared trace_id, and we page only on SLO burn rate, not raw CPU."

**Seen in:** [API monitoring and alerting](/interview-prep/design/api-monitoring-alerting/summary), [Incident response](/interview-prep/design/incident-response/summary), [Canary deployments](/interview-prep/design/canary-deployments/summary)

### 44. p99 latency

**What it is:** p99 latency is the response time that 99% of requests beat; the slowest 1% are above it. It measures the tail, not the typical case.

**Why it matters:** Averages hide pain. A page that calls 100 backends will hit at least one backend's p99 on most requests, so tail latency becomes typical user latency.

**How it works:**
- Compute from histograms (HDR, Prometheus buckets); you cannot average percentiles across hosts.
- Track p50, p95, p99 and sometimes p99.9 per endpoint.
- Tail causes: GC pauses, queueing, cold caches, noisy neighbours, retries.
- Cut it with timeouts, hedged requests (send a second copy after the p95), caching and smaller fan-out.

**Trade-off:** Chasing p99.9 is expensive and hedging adds load (often around 5%). Set tail targets only where users feel them.

**Remember:** Fan-out turns your backend's p99 into your user's median.

**Say it:** "I'll set targets on p99, not average: under 200 ms for the API. With fan-out to 20 shards, I'd hedge requests after the p95 to cut the tail."

**Seen in:** [Retries and circuit breakers](/interview-prep/design/retries-circuit-breakers/summary), [Personalized fast serving](/interview-prep/design/personalized-fast-serving/summary), [Backpressure pipeline](/interview-prep/design/backpressure-pipeline/summary)

### 45. SLOs

**What it is:** A service level objective is a target for a measured user-facing indicator (SLI), for example 99.9% of requests succeed within 300 ms over 30 days. An SLA is the contract; the SLO is the internal goal.

**Why it matters:** SLOs define "good enough" so teams can balance reliability against shipping speed. They drive alerting, priorities and release decisions.

**How it works:**
- Error budget = 1 minus SLO: 99.9% over 30 days allows about 43 minutes of failure.
- Alert on burn rate, for example page when the budget burns 14x faster than sustainable over an hour.
- When the budget is spent, freeze risky releases and fix reliability.
- Pick a few SLIs per journey: availability, latency, freshness.

**Trade-off:** Each extra nine costs far more: 99.99% allows 4.3 minutes a month and often needs multi-region. Do not set 100%; nothing meets it.

**Remember:** 99.9% is 43 minutes a month; 99.99% is 4.3.

**Say it:** "Checkout's SLO is 99.95% success under 500 ms. We page on fast burn of the error budget and freeze risky deploys when it runs out."

**Seen in:** [API monitoring and alerting](/interview-prep/design/api-monitoring-alerting/summary), [Canary deployments](/interview-prep/design/canary-deployments/summary), [Distributed cache](/interview-prep/design/distributed-cache/summary)

## Deployment and regions

### 46. Blue-green deploys

**What it is:** Blue-green runs two full production environments. Blue serves traffic, green gets the new version, then traffic switches all at once to green.

**Why it matters:** It gives near-instant cutover and near-instant rollback: switch the router back to blue. No mixed-version period during the switch.

**How it works:**
- Deploy and smoke-test green while blue serves users.
- Switch the load balancer, DNS weight or alias in one step.
- Keep blue warm for a rollback window (minutes to hours), then recycle it.
- Same idea for data: build a new search index and swap the alias.

**Trade-off:** Doubles capacity during the deploy, and all users get the new version at once, so a bug hits everyone. Database schema must work for both versions. Canary releases are usually preferred for high-traffic services.

**Remember:** Two stacks, one switch, instant rollback.

**Say it:** "For the search index I'd build v2 alongside v1 and swap the alias, a blue-green cutover with instant rollback; for services I'd prefer canaries."

**Seen in:** [Canary deployments](/interview-prep/design/canary-deployments/summary), [E-commerce search](/interview-prep/design/ecommerce-search/summary)

### 47. Feature flags

**What it is:** Feature flags are runtime switches that turn code paths on or off without a deploy. They can target percentages, regions or specific users.

**Why it matters:** They separate deploy from release. You can ship dark, ramp gradually, run experiments and kill a bad feature in seconds instead of rolling back.

**How it works:**
- A flag service (LaunchDarkly, Unleash, in-house) pushes config; SDKs cache locally and evaluate in microseconds.
- Ramp 1%, 5%, 25%, 100% with consistent hashing on user_id so users get a stable experience.
- Kill switches for risky or expensive features, used in incidents and sale events.
- Remove flags after full rollout.

**Trade-off:** Every flag doubles the paths to test, and stale flags become dangerous technical debt. Flags do not help with schema changes that both paths must handle.

**Remember:** Deploy is not release.

**Say it:** "The new ranking ships behind a flag, ramped from 1% by user hash, with a kill switch the on-call can flip in under 30 seconds."

**Seen in:** [Canary deployments](/interview-prep/design/canary-deployments/summary), [Graceful degradation](/interview-prep/design/graceful-degradation/summary), [Flash sale](/interview-prep/design/flash-sale/summary)

### 48. Zero-downtime migrations

**What it is:** Changing a database schema or moving data while the system keeps serving reads and writes. The standard method is expand, migrate, contract.

**Why it matters:** Rolling deploys run old and new code side by side, so a schema change that breaks either version causes an outage. Large tables cannot be locked for hours.

**How it works:**
- Expand: add the new column or table, nullable, compatible with old code.
- Migrate: dual-write new data, backfill old rows in small batches, verify by comparison.
- Switch reads to the new shape behind a flag; then contract by dropping the old column later.
- Use online tools (gh-ost, pt-online-schema-change) for big MySQL tables.

**Trade-off:** It takes several deploys over days or weeks, and dual-writes add temporary complexity. A brief maintenance window may be simpler for a small internal system.

**Remember:** Expand, migrate, contract, never in one deploy.

**Say it:** "I'd do expand-migrate-contract: add the column, dual-write, backfill in batches, flip reads behind a flag, and drop the old column a release later."

**Seen in:** [Multi-tenant SaaS schema](/interview-prep/design/multi-tenant-saas-schema/summary), [Canary deployments](/interview-prep/design/canary-deployments/summary), [Document search engine](/interview-prep/design/document-search-engine/summary)

### 49. Multi-region

**What it is:** Running a service in more than one geographic region, either active-passive (one serves, one waits) or active-active (all serve).

**Why it matters:** It survives a whole-region outage and puts data closer to users, cutting latency. It is also how you meet data residency rules.

**How it works:**
- Route users with GeoDNS or anycast plus health checks; DNS TTL about 60 s for failover.
- Replicate data asynchronously; cross-region round trips are about 50-150 ms, so sync writes are costly.
- Active-active needs a conflict strategy: a home region per user, CRDTs or last-writer-wins.
- Define RPO (data you can lose) and RTO (time to recover), and test failover regularly.

**Trade-off:** Roughly doubles infrastructure cost and adds consistency problems. For most services, multi-AZ in one region (99.95%+) is enough.

**Remember:** Multi-AZ for failures, multi-region for disasters and distance.

**Say it:** "I'd go active-active across two regions with a home region per user to avoid write conflicts, async replication with RPO under a minute, and GeoDNS failover."

**Seen in:** [Multi-region DR](/interview-prep/design/multi-region-dr/summary), [URL shortener](/interview-prep/design/url-shortener/summary), [Likes counter](/interview-prep/design/likes-counter/summary)

## Estimation

### 50. Back-of-the-envelope estimation

**What it is:** Quick, rounded arithmetic to size a system: requests per second, storage, bandwidth and number of machines.

**Why it matters:** It tells you which problems are real. 100 QPS fits on one box; 1M QPS needs sharding and caching. It shapes every later design choice.

**How it works:**
- A day is about 86,400 s, round to 100k; 1M requests/day is about 12 QPS average.
- Peak is often 2-10x average; size for peak.
- Storage = items per day x size x retention x replication (often 3).
- Know rough numbers: memory read about 100 ns, SSD read about 100 µs, same-region round trip about 0.5 ms, cross-continent about 150 ms.

**Trade-off:** Round numbers can be off by 2-3x; that is fine, but do not spend more than a few minutes. Revisit estimates when a design choice depends on them.

**Remember:** One day is about 100k seconds.

**Say it:** "500M daily users, 10 writes each, is 5B a day, about 58k QPS average and roughly 150k at peak. That rules out a single database."

**Seen in:** [Autocomplete](/interview-prep/design/autocomplete/summary), [Web crawler](/interview-prep/design/web-crawler/summary), [Pub-sub notifications](/interview-prep/design/pubsub-notifications/summary)
