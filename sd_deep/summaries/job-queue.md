# Design a Job Queue (background task processing): the 5-page summary

A job queue takes slow or flaky work (invoices, refunds, image resizing, notifications) off the request path so the user gets a fast answer and the work still happens. The single most important idea: exactly-once delivery over a network is impossible, so choose at-least-once with leases, retries and idempotent handlers, then spend the design on durability, tenant fairness, backpressure and visible failures.

## Page 1. The problem, scope and numbers

**Pitch:** one shared, reliable background job platform for every team, replacing home-grown cron-plus-table setups that inflate checkout latency, fail when a downstream is flaky and lose work when a pod restarts.

**Who uses it:** producer engineers (enqueue in one call, check status), handler owners (lease in batches, extend leases, set retry policy) and on-call operators (backlog, pause and resume, DLQ redrive).

**In scope:**
- **Enqueue:** payload up to 256 KB, optional delay or run_at, priority, dedup key, ordering key.
- **Lease:** batches with a visibility timeout; heartbeat, ack, or nack with a reason.
- **Retries:** per-queue max attempts, capped exponential backoff with full jitter.
- **DLQ:** per queue, with inspect, bulk redrive and purge.
- **Status and control:** job status API, cancel before start, pause and resume queues.
- **Per-key FIFO:** optional; one job per ordering key in flight.

**Out of scope:** exactly-once side effects (handlers own idempotency), workflow orchestration (Temporal), stream processing (Flink), sub-10 ms dispatch, cross-region active-active.

**Non-functional targets:**
- **Latency:** enqueue p50 under 10 ms, p99 under 50 ms; ready to leased p99 under 1 s when workers are free.
- **Availability:** enqueue 99.99%, dequeue 99.95%.
- **Durability:** zero acked jobs lost; survive one AZ loss (3 replicas, 2 in sync).
- **Throughput:** 15k enqueues/s and 15k completions/s; burst 30k/s for 10 minutes.
- **Semantics:** at-least-once; duplicates under 0.1% in steady state.
- **Freshness SLO:** oldest ready job under 30 s p99 normally, under 5 minutes on sale peaks.

**Capacity math (100M jobs/day, 10x sale peaks, 2.3 KB per job, 500 queues, 80 teams):**
- **Rate:** 100M / 86,400 = 1,160 jobs/s; 10x = 12k/s, plan 15k/s. Past Postgres SKIP LOCKED territory (about 2k jobs/s), so a real broker.
- **Ingress:** 15k x 2.3 KB = 35 MB/s; x RF 3 = 105 MB/s. Kafka storage 230 GB/day x 3 replicas x 3 days = 2.1 TB, about 12 brokers.
- **Workers (Little's law):** 15k/s x 0.5 s = 7,500 concurrent slots; at 50 per pod, 150 pods.
- **Redis hot window:** 5 minutes of backlog = 15k x 300 x 2.5 KB = 11 GB on 8 shards. So Redis holds only a bounded window; Kafka holds the backlog.
- **Redis ops:** about 4 per job = 60k ops/s; one shard does 100k+/s, so 8 shards leave room for Lua.
- **Job state:** 700M rows (7 days) x 500 B = 350 GB; about 3 writes per job = 45k/s at peak. So a sharded store.

## Page 2. The architecture

```
 Producers (checkout, seller, notifications): POST /queues/{q}/jobs
      v
 Enqueue API (stateless) --acks=all--> Kafka jobs.p0/p1/p2 (RF 3, 3 days)
      | dedup (Redis SETNX)                  | consume
      v                                      v
 Job State Store (sharded MySQL) <------ Relay / Dispatcher (rate limits)
      ^                                      | ZADD ready / delay
      |                                      v
      |                  Ready Store (Redis, 8 shards): ready, delay,
      |                  inflight sets per queue shard (Lua scripts)
      |                      | lease / ack              | expired
      |                      v                          v
      +----- ack/nack -- Worker pools (pull)      Reaper + Retry
                             | max attempts -> DLQ <----+ (redrive console)
 Control plane (etcd): queue config, limits, pause flags
```

- **Enqueue API:** auth, size check, ULID job_id, dedup, Kafka write with acks=all, returns 202.
- **Kafka:** durable source of truth for accepted jobs; absorbs bursts; replay after Redis loss.
- **Relay:** moves due jobs into ready sets, future ones into delay sets; per-queue rate limits.
- **Ready Store (Redis):** ready, delay and in-flight sorted sets plus job hash; atomic Lua transitions.
- **Lease service:** lease, heartbeat, ack, nack; per-queue concurrency caps; long poll up to 20 s.
- **Worker pools:** team handlers on the SDK, autoscaled on oldest-job age.
- **Reaper and Retry:** every second returns expired leases, promotes due delays, routes exhausted jobs to DLQ.
- **Job State Store:** status, attempts, last error by job_id; 7-day TTL.
- **Control plane:** per-queue max attempts, backoff, timeout, concurrency, priority, owner.

**Flow A: enqueue to completion**
1. Producer enqueues to refunds with dedup_key order123-refund; SET NX EX 86400; a repeat returns the original job_id.
2. API writes to Kafka with acks=all, records queued asynchronously, returns 202.
3. Relay runs Lua: HSET job, ZADD ready:{refunds#3}; commits the offset after success.
4. Worker leases 10 with 30 s visibility; Lua moves them to inflight with deadline now+30 s.
5. Handler heartbeats every 10 s if long, then acks with its lease token; state becomes succeeded.

**Flow B: failure, retry, dead letter**
1. Gateway returns 503; handler nacks retryable.
2. Delay = random(0, min(15 min, 2 s x 2^attempt)); job goes into the delay set.
3. A crashed worker's lease expires; the Reaper counts it as a failed attempt.
4. After 5 attempts: DLQ with all errors, state dead, owning team alerted; redrive keeps job_id.

## Page 3. The core deep dives

### 1. Leases: the failure detector
A lease (visibility timeout) hides a job from other workers until a deadline. Popping from ready and recording the lease must be one atomic Lua step; otherwise a crash between them loses the job or hands it to two workers. The hash tag {q#s} keeps one queue shard's keys in one Redis slot, so the script is atomic. Default 30 s: short enough to retry crashed work quickly, long enough for most jobs; the SDK heartbeats every timeout/3. Lua uses Redis server TIME, not host clocks, so skew cannot fire jobs early.

### 2. Zombies and exactly-once effect
Example: Sethu's worker hits a GC pause longer than 30 s; the lease expires and Shreya's worker takes the job. Each lease carries a random lease_token; when Sethu's worker wakes and acks, the token is stale and it gets 409. A worker that finishes the side effect but crashes before ack causes redelivery, which is why delivery is at-least-once. For a refund, three layers stop a double payout: enqueue dedup key per order, a unique constraint on refund(order_id) in the handler's transaction, and an idempotency key passed to the gateway.

### 3. Kafka plus Redis, and why not either alone
Kafka's progress unit is an offset per partition: one slow job blocks everything behind it, there is no per-message retry or delay, and parallelism is capped by partitions. Redis gives per-job leases, delays and priorities but RAM must never be the backlog. So Kafka is the durable buffer and replay source; the Relay moves only a bounded window (about 5 minutes of work) into Redis. If a Redis shard loses its last second of writes, the Relay re-reads Kafka from the last committed offset.

### 4. Retries without storms
Full jitter spreads retries uniformly, so thousands of jobs that failed together do not return in waves. A per-queue circuit breaker pauses the queue when failures exceed 50% over 1 minute, then resumes with a ramp-up.

**Data model:**
- **Job envelope** (Kafka jobs.p{priority}): partition key queue#(ordering_key or hash(job_id) mod 16).
- **Ready, delay, in-flight sets** (Redis): scores are run_at (priority-adjusted) and lease deadline.
- **Job state** (MySQL, 16 shards): PK job_id; index (queue, status, updated_at); daily partitions dropped at 7 days.
- **Dedup keys** (Redis): SET NX EX 86400.
- **Queue config** (etcd): /queues/{name}, watched by Relay and Lease service.

**Key APIs:**
- `POST /v1/queues/{queue}/jobs`: 24 h dedup; 413 over 256 KB; 429 with Retry-After.
- `POST /v1/queues/{queue}/lease`: long poll; respects the concurrency cap.
- `POST /v1/jobs/{job_id}/heartbeat`: 409 means the lease is lost; stop.
- `POST /v1/jobs/{job_id}/ack` and `/nack`: stale token rejected; non-retryable goes to DLQ.
- `POST /v1/queues/{queue}/dlq/redrive`: rate-limited to avoid a thundering herd.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot queue (5M jobs in a minute):** split into virtual shards, concurrency cap, relay rate limit, lower priority class.
- **Redis memory:** Relay respects a high-water mark; backlog stays in Kafka.
- **Priorities:** separate Kafka topics per class, so a p2 backlog never delays p0 ingestion; weighted round-robin leasing.
- **Workers:** autoscale on oldest-job age; under overload, pause low-priority relays (marketing email) while payments flow.
- **Job state writes:** shard by hash(job_id).

**Failure modes:**
- **Worker crash mid-job:** lease expires within 30 s, job retried; idempotency absorbs partial effects.
- **Redis primary fails:** replica promoted in 10-20 s; Relay replays Kafka; duplicates possible, no loss.
- **Kafka broker loss:** leaders re-elected from in-sync replicas; idempotent producers retry; if not acked within 2 s, return 503, never a false ack.
- **Downstream outage:** retryable nacks, jittered backoff, circuit breaker pauses the queue; jobs wait safely.
- **Bad deploy fails every job:** DLQ inflow alert to the owner; roll back, then redrive.
- **AZ loss:** Kafka keeps 2 replicas and accepts writes; Redis promotes replicas elsewhere; oldest-job age rises briefly.
- **Reaper leader dies:** etcd lock expires (10 s TTL); a standby takes over.
- **Poison pill:** crash loops counted via lease expiry; DLQ after max attempts.

**Trade-offs chosen:**
- **At-least-once plus idempotency over exactly-once:** exactly-once across external side effects is not achievable.
- **Kafka plus Redis over one broker:** durable replay plus per-job leases; Postgres is right below about 2k jobs/s.
- **Pull with long polling over push:** workers take only what they can process, natural backpressure.
- **30 s timeout plus heartbeats:** quick retry of crashed work, long jobs still covered.
- **Per-key ordering over strict queue FIFO:** FIFO kills parallelism and one failure blocks all.
- **Separate state store over Redis:** history for days without wasting RAM or losing it on failover.

**What to measure:** age of oldest ready job per queue (the SLO and autoscaling signal); ready, delayed and in-flight depth; enqueue, lease, ack and nack rates; lease expiry rate; retry histogram; DLQ inflow with owner alert; handler duration and enqueue-to-ack latency; Relay Kafka lag; Redis memory; duplicate rate from idempotency conflicts.

## Page 5. Say it in the interview

> "I will assume 100 million jobs a day with sale peaks of 15 thousand a second, many teams sharing one platform, and at-least-once delivery with idempotent handlers, because exactly-once delivery over a network is not achievable. Once enqueue returns, the job must survive an AZ loss. I start with a Postgres table and SKIP LOCKED and show where it breaks. The scaled design: a stateless enqueue API writes to Kafka with acks all as the durable buffer; a relay moves due jobs into Redis sorted sets per queue shard; workers lease with a 30-second visibility timeout, heartbeat and ack. Failures retry with backoff and jitter and land in a dead letter queue after five attempts. Kafka absorbs bursts so Redis never fills, every queue has concurrency and rate limits, and I alert on the age of the oldest ready job."

**Key points to land:**
- Start with Postgres SKIP LOCKED, then say why it stops scaling at a few thousand jobs/s.
- At-least-once plus idempotent handlers equals exactly-once effect.
- Leases are the failure detector; heartbeats for long jobs; lease tokens stop zombies.
- Kafka is the durable buffer and replay source; Redis holds only a bounded hot window.
- Atomic Lua for lease and ack; Redis server time as the single clock.
- Capped exponential backoff with full jitter, max attempts, DLQ with redrive.
- Per-queue concurrency caps, rate limits and priority classes give isolation and a shedding order.
- The SLO is oldest ready job age, not CPU or queue length.
- Hot queues split into virtual shards; ordering only per key, never global.

**Likely follow-ups:**
1. **Why not SQS?** For one team on AWS, yes. At company scale we want replay, priority classes, cross-queue fairness and portability; SQS caps delay at 15 minutes.
2. **Why not Kafka consumer groups alone?** One slow job blocks its partition, there is no per-message retry or delay, and parallelism is capped by partitions.
3. **Cron schedules?** A leader-locked cron service enqueues each fire with dedup_key = schedule_id + fire_time, so failover cannot double-fire.
4. **A 2-hour job?** Heartbeats up to a max lease, but better split into checkpointed chunks so a crash or deploy loses minutes, not hours.
5. **Zero-downtime worker deploys?** On SIGTERM stop leasing, finish or nack in-flight jobs within about 60 s; lease expiry recovers the rest.

**Director layer:**
- **Cost drivers:** about 150 worker pods at peak (team-owned), 12 Kafka brokers, 8 Redis shards, 350 GB sharded state.
- **Phasing and migration:** ship the SDK and core queues, then priorities and DLQ console; migrate teams off cron tables in shadow mode (double-write, compare, cut over per queue with a rollback flag), targeting 80% in two quarters.
- **Ownership:** platform team runs Kafka, Redis, Relay and Lease; product teams own handlers, idempotency and their DLQ alerts.
- **Top risks:** non-idempotent handlers, retry storms amplifying a downstream outage, sale-day Redis exhaustion, the platform as a shared single point of failure.
