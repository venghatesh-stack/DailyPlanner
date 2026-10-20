# Distributed Unique ID Generator (Snowflake): recall card

> **Hook:** Lease a worker id once → Read the clock → Pack 41 + 10 + 12 bits → Mint locally → Fail closed

**P · Problem:** It's really a coordination-avoidance problem: unique, time-ordered IDs everywhere with no network call per ID.

**N · Numbers:**
1. 2^41 ms is about 69.7 years, so the custom epoch is a documented, decades-long decision.
2. 4,096 IDs per ms per worker against 2.5 per ms at peak, so sequence overflow is rare and costs a 1 ms wait.
3. 1,024 workers renewing every 10 s is about 100 writes/s, so ZooKeeper stays tiny and off the hot path.

**H · Hard part:** Clocks that go backwards and two processes holding the same worker id, both of which create silent duplicates.

**B · Boxes:** `App code → IdGenerator library → Monotonic clock check → 64-bit ID`

Side path: `LeaseKeeper → ZooKeeper / etcd` to lease and renew the worker id.

**D · Decisions:**
1. 64-bit Snowflake over 128-bit UUID, because it fits BIGINT and halves index size.
2. Embedded library over a central ID service, because there is no network hop or hot-path dependency.
3. Fail closed over always available, because uniqueness is non-negotiable.

**F · Failures:**
1. Clock jumps back more than 5 ms → the worker refuses, the health check fails and traffic moves elsewhere.
2. Lease renewal stalls (partition or GC pause) → the watchdog self-fences at 25 s, before the 30 s TTL can expire.

**C · Close:** "I rule out auto-increment, a single point of failure, and UUIDv4, which is 128 bits and random. I use the Snowflake layout: 41 bits of milliseconds from a custom epoch, 10 bits of worker id, 12 bits of sequence. Each worker generates locally; the only coordination is leasing a worker id from ZooKeeper at startup. Then I defend the hard parts: clocks going backwards, duplicate worker ids, sequence overflow, and monitoring."

**Quiz yourself:**
1. Are IDs globally ordered? → No, only k-sorted, to within clock skew; strictly increasing per worker.
2. Why return IDs as strings to JavaScript? → Precision is lost above 2^53.
3. How should consumer tables shard? → By hash(id), never by the time bits.
