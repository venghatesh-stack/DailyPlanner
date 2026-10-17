# Design a Distributed Unique ID Generator (Snowflake): the 5-page summary

A Snowflake ID packs a timestamp, a worker id and a per-millisecond sequence into 64 bits, so every service can mint unique, roughly time-ordered IDs locally with no network call. The single most important idea: coordinate once (lease a worker id), never per ID, and fail closed whenever the clock or the lease cannot be trusted.

## Page 1. The problem, scope and numbers

**Pitch:** one company-wide way to mint unique, compact, time-ordered 64-bit identifiers across thousands of machines, shards and regions, at hundreds of thousands per second.

**Why now:** once databases are sharded, auto-increment keys overlap across shards, and a central sequence becomes a bottleneck and a single point of failure. Teams are inventing their own schemes and getting collisions.

**Who uses it:** backend developers (`next_id()` in one line, batches for bulk inserts), DBAs and data engineers (IDs that append to the right edge of B-tree indexes and encode creation time), and SREs (dashboards on clock offset, leases and overflow).

**In scope:**
- **next_id():** returns a unique 64-bit ID, in-process.
- **next_ids(n):** up to 4,096 IDs per call for bulk inserts.
- **parse(id):** decodes timestamp, datacenter, worker and sequence for debugging.
- **Worker-id leases:** acquired at startup, renewed, released on shutdown.
- **Clock regression handling:** wait if small, fail closed with a clear error if large.
- **Sidecar / gRPC endpoint** for languages without the native library.

**Out of scope:** human-friendly short codes (they can be derived from IDs), gapless legal sequences such as invoice numbers, secret tokens, and strict global event ordering (use a per-partition log like Kafka).

**Non-functional targets:**
- **Uniqueness:** zero duplicates, ever, including across restarts and clock events.
- **Latency:** in-process p99 under 10 microseconds; sidecar p99 under 2 ms.
- **Availability:** 99.999%; generation is independent of the coordinator once a lease is held.
- **Ordering:** strictly increasing per worker; k-sorted across workers (ordered to within clock skew, about 10 ms).
- **Longevity:** about 69 years from a custom epoch of 2026-01-01.

**Capacity math (peak 500k IDs/s, average 100k/s, up to 1,024 workers):**
- **Time range:** 2^41 ms = 2.2e12 ms = about 69.7 years, so IDs last until about 2095. So the epoch choice is a documented, decades-long decision.
- **Per worker:** 2^12 = 4,096 IDs per ms, about 4.1M per second. At peak, 500k / about 200 active workers = 2.5 per ms. So sequence overflow is rare and only costs a 1 ms wait.
- **Fleet:** 1,024 x 4.1M = about 4.2 billion IDs/s theoretical; peak uses 0.01%. So capacity is not the problem; correctness under clock and lease failures is.
- **Storage:** 8 bytes versus 16 for a UUID; 10 billion rows with 3 indexes each holding the key saves about 320 GB. So the compact key is worth the coordination.
- **Coordinator load:** 1,024 workers renewing every 10 s = about 100 writes/s. So ZooKeeper is trivially loaded and stays off the hot path.

## Page 2. The architecture

```
 +------------------ Service instance ------------------+
 | app code -> IdGenerator.next()                       |
 |              state: worker_id=37, last_ms, seq       |
 |              reads monotonic-guarded wall clock      |
 | LeaseKeeper: renew every 10 s, TTL 30 s ---------+   |
 +--------------------------------------------------|---+
                                                    v
  NTP / chrony (slew only)       ZooKeeper / etcd (3 or 5 nodes)
  offset -> monitoring           /idgen/dc-02/workers/0..1023

 64-bit ID layout:
 | 0 | 41 bits ms since 2026-01-01 | 5 dc | 5 worker | 12 seq |
```

- **IdGenerator library:** holds worker_id, last_ms and seq; composes IDs; enforces monotonic time.
- **LeaseKeeper:** leases a free worker id, renews it, self-fences if renewal fails.
- **Coordination cluster (ZooKeeper/etcd):** source of truth for worker ids in use per datacenter.
- **Clock discipline (chrony/NTP):** keeps clocks within a few ms; slews, never steps; exports offset.
- **Sidecar / gRPC service:** same library behind a batch endpoint for other languages.
- **ID parser and tooling:** decodes IDs for debugging and data pipelines.
- **Monitoring:** rate, overflow waits, clock regressions, lease events, downstream duplicate keys.

**Flow A: startup and lease**
1. Read datacenter id from config; list /idgen/dc-XX/workers and pick the lowest free id.
2. Create an ephemeral node with host and pid (session timeout 30 s).
3. Wait until the clock passes the last timestamp this worker id used, then report ready.

**Flow B: generate an ID (hot path)**
1. now = current_ms() - EPOCH.
2. If now < last_ms: spin if the gap is 5 ms or less, else throw ClockMovedBackwards.
3. If now == last_ms: seq + 1; if it wraps past 4,095, spin to the next ms. If now > last_ms: seq = 0.
4. Return (now << 22) | (dc << 17) | (worker << 12) | seq.

## Page 3. The core deep dives

### 1. The bit layout and k-sorted IDs
One sign bit (always 0, so the ID fits a signed Java long or MySQL BIGINT), 41 bits of milliseconds since 2026-01-01, 5 bits datacenter, 5 bits worker (1,024 workers in total), 12 bits sequence. Because time is in the high bits, a newer ID is almost always larger. Across workers, order holds only to within NTP skew: if Shreya's ID comes from worker 3 and Sethu's from worker 9 a few ms later, Sethu's may still sort first. Per worker, IDs are strictly increasing. Datacenter bits let regions generate without ever talking to each other.

### 2. Clocks going backwards
NTP can step a clock back, a VM can pause, a leap second can repeat. The generator keeps last_ms. If the clock is behind by 5 ms or less, it spins until it catches up. If it is behind by more, say 800 ms after an NTP step, it refuses: it throws, the health check fails, the load balancer routes callers to another instance and an alert fires. Prevention: chrony set to slew only (step only at boot), leap seconds smeared, offset over 50 ms alerts. On restart, a last_ms checkpoint written to local disk every second (plus a hint in ZooKeeper) makes the new process wait until its clock passes it.

### 3. Worker-id leases and self-fencing
Two processes with the same worker id will create duplicates silently. So worker ids are leased: an ephemeral ZooKeeper node or an etcd lease with a 30 s TTL, renewed every 10 s. The key rule is self-fencing: if 25 s pass without a confirmed renewal (partition, long GC pause), the generator stops issuing before the TTL can expire. Only after expiry can another instance claim the id, so the two windows never overlap. Example: a VM is paused 40 s by live migration; on resume the watchdog sees the last renewal is too old and disables generation before issuing a single ID.

### 4. Why not the alternatives
Auto-increment is a single point of failure. UUIDv4 is 128 bits and random, so inserts land all over the B-tree. A ticket server (Flickr: two MySQL servers with odd and even auto-increment) works but puts a network hop and a central dependency on every insert, and the two servers' numbers are not time-aligned.

**Data model:**
- **Worker lease** (ZooKeeper ephemeral node or etcd key): path /idgen/{dc}/workers/{worker_id}; host, pid, acquired_at, last_ts_hint.
- **Generator state** (process memory): worker_id, dc_id, last_ms, seq; can be packed into one 64-bit atomic for lock-free CAS.
- **Last-used checkpoint** (local disk per worker id): last_ms, written every second.
- **The ID in consumer tables:** BIGINT primary key; shard by hash(id), never by the time bits.

**Key APIs:**
- `IdGenerator.next_id()`: throws ClockMovedBackwards or LeaseLost; never returns a possible duplicate.
- `IdGenerator.next_ids(n)`: reserves a contiguous sequence block within one or more ms.
- `IdGenerator.parse(id)`: pure function, usable in data pipelines.
- `POST /v1/ids:batch`: sidecar endpoint; IDs returned as strings for JavaScript safety.
- `GET /v1/ids/{id}`: debug decode.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **ID throughput:** none central. At 5M IDs/s, 200 workers each need 25 per ms, still under 4,096. The real limit is the caller's CPU.
- **Sequence overflow:** a burst over 4,096 in one ms waits up to 1 ms; sustained overflow is a metric that triggers adding workers.
- **Worker ids per datacenter:** 32 per dc in the 5+5 split. Alert at 80% used; reclaim stale leases or rebalance the bits.
- **Hot shards downstream:** time-ordered IDs make the newest range hot, so shard by hash(id) or embed shard bits.
- **Coordinator:** about 100 writes/s at 1,024 workers; it stays tiny even at 10x.

**Failure modes:**
- **Clock jumps back more than 5 ms:** the worker refuses to issue, health check fails, traffic moves to other instances, alert fires.
- **ZooKeeper down:** running workers continue on held sessions; new instances stay unready; no hot-path impact.
- **Lease lost (partition or GC pause):** the watchdog disables generation before TTL expiry; the instance later leases a new id.
- **All worker ids taken:** new instances cannot generate; alerted at 80%.
- **Bug in bit composition deployed:** a canary with a uniqueness checker across many workers catches it; downstream duplicate-key errors are the backstop.
- **Same static worker id in two configs:** prevented by banning static ids in production.

**Trade-offs chosen:**
- **64-bit Snowflake over 128-bit UUID:** fits BIGINT and halves index size; we accept coordinating worker ids, which UUIDs avoid.
- **Embedded library over a central ID service:** no network hop and no new hot-path dependency; sidecar for polyglot services.
- **Leased worker ids over static config:** automatic and exclusive under autoscaling; static config causes silent duplicates.
- **Fail closed over always available:** uniqueness is non-negotiable; brief waits hide jitter.
- **Bit split 41/5+5/12:** matches 1,024 workers and the burst rate; dc bits keep regions independent.
- **Raw IDs internally, obfuscated externally:** sequential-ish IDs reveal order volume and allow enumeration.

**What to measure:** IDs/s per worker and fleet, overflow waits per minute, clock regression events and max regression, NTP offset per host (alert over 50 ms), lease renew latency and failures, worker ids in use per dc, sidecar p99, and downstream duplicate-key errors (must be 0).

## Page 5. Say it in the interview

> "First I pin down three things: must IDs fit in 64 bits, must they sort by time, and how many per second. Assuming 64-bit, roughly time-ordered, about half a million a second, I rule out auto-increment, a single point of failure, and UUIDv4, which is 128 bits and random and hurts B-tree locality. A ticket server works but adds a network hop to every insert. So I use the Snowflake layout: 41 bits of milliseconds from a custom epoch, 10 bits of worker id, 12 bits of sequence. Each worker generates locally with no coordination; the only coordination is leasing a worker id from ZooKeeper at startup. Then I defend the hard parts: clocks going backwards, two workers with one id after a lease expires, sequence overflow, multi-region, and monitoring."

**Key points to land:**
- Clarify first: 64-bit? time-sortable? how many per second? public-facing?
- Compare five options fast: auto-increment, UUID, ticket server, range blocks, Snowflake.
- 1 + 41 + 10 + 12 = 64 bits; about 69 years; 4,096 IDs per ms per worker.
- Coordinate once (the worker-id lease), never per ID.
- The real risks are clocks going backwards and duplicate worker ids; fail closed on both.
- Self-fence: stop issuing before the lease TTL could have expired.
- IDs are k-sorted, not causally ordered; do not use them as a sequencer.
- 8-byte time-ordered keys are B-tree friendly; shard by hash, not by ID range.
- Return IDs as strings to JavaScript clients (precision is lost above 2^53).

**Likely follow-ups:**
1. **IDs on offline mobile clients?** Use UUIDv7 or ULID on the device and optionally map to a server ID on sync, or lease each device a worker range.
2. **Non-guessable public IDs?** Encrypt the 64-bit ID with a keyed 64-bit cipher and base62-encode it; keep raw IDs internal.
3. **100,000 workers?** Move to 17 worker bits with 5-6 sequence bits, or 10 ms time units, or 128-bit IDs; or embed a shard id and generate inside each shard.
4. **How did Instagram do it?** A PL/pgSQL function per Postgres logical shard: 41 bits ms, 13 bits shard id, 10 bits sequence, so the shard is readable from the ID.
5. **Can it order a ledger?** No. Ledgers need a strict per-account sequence or a transactional DB order; Snowflake IDs identify, they do not sequence.

**Director layer:**
- **Cost drivers:** small. A 3-5 node coordination cluster and NTP; the main cost is the migration effort across teams.
- **Phasing:** ship the library and leases first, then the sidecar for other languages; adoption target is all new sharded tables within 2 quarters.
- **Ownership:** a platform team owns the library, leases and dashboards; service teams own adoption and string serialisation in their APIs.
- **Top risks:** clock regressions, duplicate worker ids, JavaScript precision loss, and public IDs leaking volume.
