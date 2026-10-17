# Design backpressure for a write-heavy pipeline: the 5-page summary

A write pipeline runs at the speed of its slowest stage, usually the database, and every unbounded queue turns overload into memory exhaustion and latency. The key idea: a chain of bounded queues with a durable log as the shock absorber and an explicit feedback loop that slows or sheds low-priority producers first, never losing an acknowledged write.

## Page 1. The problem, scope and numbers

**Pitch:** survive 5-10x write bursts (sale launches, flash deals, batch imports) without collapse: absorb, slow down or shed by priority, recover by itself, and never lose a write that got a 2xx.

**Who uses it:** producer service engineers (simple SDK: 2xx or a clear retry signal), pipeline on-call SREs (which stage and which tenant is under pressure), data consumers such as analysts and search indexers (how stale, and nothing acknowledged dropped).

**In scope:**
- **Ingest:** HTTP/gRPC writes with idempotency key, tenant, priority class; payload up to 1 MB.
- **Admission:** per-tenant, per-class token buckets; 429 with Retry-After; bounded pod buffers return 503.
- **Durable append:** acknowledge only after Kafka has it (acks=all, min in-sync replicas 2).
- **Drain:** pull-based consumers, batched idempotent upserts, adaptive concurrency, pause and resume.
- **Pressure levels:** green, yellow, orange, red from lag, buffer and sink latency; shed by class.
- **DLQ and admin:** dead-letter after 3 attempts with replay; quota and override APIs.

**Out of scope:** sink schema and resharding, stream processing (windows, joins), cross-region active-active log.

**Non-functional targets:**
- **Ingest latency:** p99 under 50 ms for 2xx at 10x load (append only).
- **Availability:** 99.95% for the critical class, 99.9% for others (a 429 counts as available).
- **Durability:** acknowledged writes survive losing 1 broker and 1 AZ; RPO 0.
- **Freshness:** critical lag p99 under 5 s; low priority under 15 min at peak.
- **Stability and fairness:** back to baseline within 5 min after load drops; no tenant below its guaranteed quota.

**Capacity math (50k writes/s steady, 500k peak for 15 min, 1 KB events, sink 80k/s batched):**
- **Bandwidth:** 500k x 1 KB = 500 MB/s; x3 replicas = 1.5 GB/s; at 50 MB/s per disk, plan 36 brokers.
- **Backlog:** (500k - 80k) x 900 s = 378M events, about 378 GB. So a durable log must absorb it.
- **Drain:** spare sink capacity 30k/s, so 378M / 30k = 3.5 hours. Too slow, so shed or sample clickstream in red; critical (25k/s at peak) always fits.
- **Storage:** 4.3 TB/day x 3 x 7 days = about 90 TB; provision 120 TB.
- **Partitions:** 500 MB/s / 5 MB/s = 100; round to 128 so consumers can scale out.
- **Ingest pods:** 10k req/s each, so 65 with headroom; buffers capped at 10k messages (10 MB).

## Page 2. The architecture

```
 Producers (apps, SDKs, CDC): token bucket, jittered retry, Retry-After
    |
    v
 Gateway: per-tenant/class buckets, admission  -> 429/503 + Retry-After
    |        ^ admit rates + shed rules
    |        +---------------- Pressure Controller (levels, hysteresis)
    v                             ^ lag, buffer, sink p99, errors
 Ingest pods (bounded buffer) -> Kafka (RF 3, min ISR 2, 7 d, quotas)
                                    | pull (consumer sets the rate)
                                    v
                           Consumers: bounded pool, pause/resume,
                           AIMD limiter, circuit breaker
                              |                  |
                     batched UPSERT          poison msgs
                              v                  v
                         Sink DB            DLQ topic + replay
```

- **Producer SDK:** client bucket, full-jitter backoff, 10% retry budget, local spool.
- **Gateway:** classifies traffic, enforces buckets, rejects early and cheaply.
- **Ingest service:** validates, buffers boundedly, batches to Kafka, returns 202 after ack.
- **Kafka:** absorbs bursts on disk; separate topics per priority class.
- **Consumers:** pull 500 records, commit offsets only after the sink write succeeds.
- **AIMD limiter and breaker:** finds the DB's limit; stops hammering a failing DB.
- **Pressure Controller:** computes the level each second, pushes rates and shed rules.
- **Spill and DLQ:** red-state bulk to object storage; poison messages to the DLQ.

**Flow A: normal write (green)**
1. SDK takes a token and posts the event with its idempotency key; the gateway admits.
2. Ingest buffers it, produces with acks=all; the broker acks after 2 of 3 replicas.
3. Ingest returns 202 (p99 about 20 ms); a consumer upserts 500 rows and commits.

**Flow B: burst with sink saturation**
1. Traffic jumps 10x; Kafka absorbs it and lag grows from 1 s to 60 s.
2. Sink p99 goes 15 -> 80 ms; AIMD halves in-flight writes 64 -> 32; full consumers pause partitions.
3. Clickstream lag over 120 s: orange, clickstream admission cut to 50%; critical untouched.
4. Lag over 15 min or disk over 70%: red, spill clickstream, drop debug logs, 429 to low priority.
5. After the burst the controller steps down one level every 2 minutes.

## Page 3. The core deep dives

### 1. Backpressure: buffer, slow or drop
Excess load can only be buffered, slowed or dropped, so choose per class. Implicit backpressure: consumers pull only as fast as the limiter allows and pause partitions when their local queue is full, so lag grows in Kafka, not in memory or in the DB. Explicit backpressure: when lag or disk grows, the Pressure Controller tightens the gateway, which returns 429 with Retry-After. Every queue is bounded, and every bound sends a signal upstream.

### 2. Adaptive concurrency (AIMD)
Like TCP congestion control: add 1 in-flight write each time a full window meets the latency target (p99 50 ms); halve it on a spike, error or timeout. Bounds are a floor of 4 and a ceiling of 128 batches. Little's Law (in-flight = rate x time) shows how small the need is: 80k rows/s in 500-row batches is 160 batches/s; at 25 ms each, 160 x 0.025 = 4 in flight. So the limiter settles low and halves within a second when the DB compacts.

### 3. Shedding with priority and hysteresis
Traffic is critical (orders, payments, 5% of volume), standard or bulk. The level comes from the worst normalized signal; each level maps to per-class admission multipliers. Bulk is sampled at orange and spilled at red; critical never drops below its guarantee. The gateway rejects before reading the body, and retries are shed before first attempts. Hysteresis (stay healthy 2 minutes before stepping down) stops flapping.

### 4. Retries without storms, and no lost writes
Clients wait a random time between 0 and min(30 s, base x 2^attempt), or Retry-After if larger. A retry budget allows retries up to 10% of recent successes, so retries cannot multiply load. Only the outermost layer retries. Delivery is at least once: the sink upsert uses the business key plus a version guard, so a replayed batch is a no-op.

**Data model:**
- **Event** (Kafka events.class): partition hash(key) mod 128; idempotency_key, tenant, class, payload, attempt.
- **Sink row** (Cassandra or sharded Postgres): PK business key; upsert only if version is newer.
- **Quota** (etcd or Postgres, cached on gateways): PK (tenant_id, class); rate, burst, guaranteed rate.
- **Pressure state** (controller, pub-sub): per topic; level, lag, sink p99, admit multiplier.
- **DLQ record** (dlq.topic plus Postgres index): original offset, error class, attempts; 14 days.

**Key APIs:**
- `POST /v1/events`: always returns Retry-After and X-Pressure-Level.
- `POST /v1/events:batch`: up to 500 events; client retries only rejected indexes.
- `GET /v1/pressure`: polled by gateways and smart SDKs every 1-5 s.
- `PUT /admin/v1/quotas/{tenant_id}`: audited; reaches all gateways within 5 s.
- `POST /admin/v1/dlq/{topic}:replay`: replay is itself rate limited.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Sink DB:** batch 500 rows per upsert (10-50x throughput), partition by key, keep writes idempotent.
- **Kafka:** partitions scale linearly; per-client quotas stop one producer saturating the cluster.
- **Consumers:** over-provision partitions and autoscale on lag in seconds, capped at what the DB can take.
- **Beyond 10x:** independent cells by tenant or region, tiered storage, shedding pushed into clients.

**Failure modes:**
- **Sink DB degraded:** AIMD halves, breaker opens, consumers pause, lag grows in Kafka, bulk spills; recovery ramps from half-open probes.
- **Broker lost:** leaders move to in-sync replicas in seconds; partitions below 2 replicas return 503.
- **Consumer group crashes:** offsets not committed, so nothing is lost; roll back, replay idempotently.
- **Pressure Controller down:** gateways keep last rates for 60 s, then safe defaults.
- **Retry storm from an old SDK:** shed retries first; per-tenant buckets cap the tenant.
- **Metastable failure:** drop work past its client deadline; shed retries; recover with hysteresis.
- **AZ outage:** replicas in 3 AZs keep data; capacity drops a third, so bulk is shed.

**Trade-offs chosen:**
- **Kafka between producers and DB over synchronous writes:** decouples rates; costs eventual consistency.
- **Reject with 429 over blocking producers:** blocking hides overload and ties up threads.
- **Guaranteed floor plus adaptive multipliers over static or adaptive alone:** fair, efficient, stable.
- **Spill bulk over dropping:** cheap and backfillable; drop only data marked lossy.
- **Batched writes (max 50 ms wait) over per-record:** the cheapest capacity win.
- **Scale consumers on lag, not CPU:** CPU is low while waiting on a slow DB.

**What to measure:** consumer lag in seconds per partition, buffer occupancy and 503 rate, 429 rate per tenant, shed and spilled counts, retry ratio (alert at 10%), sink p99 and AIMD limit, breaker changes, broker disk and under-replicated partitions, end-to-end freshness, hourly reconciliation (accepted = persisted + DLQ + shed).

## Page 5. Say it in the interview

> "Backpressure is about making the fastest part of the system respect the slowest part without losing acknowledged data. I will assume 50 thousand writes a second steady, 500 thousand at a sale peak, a database that sustains about 80 thousand, and a rule that a 2xx means durable. The design is a pipeline of bounded queues. Producers go through a gateway with per-tenant token buckets. Ingest pods append to Kafka with acks all, our shock absorber, and return 202 quickly. Consumers pull at the rate the database can take, with an adaptive concurrency limiter, batched idempotent upserts and pause and resume on partitions. A pressure controller watches lag and database latency and tightens admission at the edge, shedding low-priority classes first. Retries use jitter and a budget, critical traffic has its own bulkhead, and I alert on lag in seconds and retry ratio, not CPU."

**Key points to land:**
- A pipeline runs at the speed of its slowest stage, usually the sink DB.
- Excess load is buffered, slowed or dropped; choose per class.
- Bound every queue, and make every bound signal upstream.
- A durable log is the shock absorber; pull consumers give natural backpressure.
- AIMD on p99 protects the DB better than a fixed pool size.
- Acknowledge after durable append; at-least-once plus idempotent upserts.
- Retries amplify overload: one layer, full jitter, budget, Retry-After.
- Shed early, cheaply, by priority; spill rather than drop; hysteresis.
- Bulkheads per class and a breaker per sink keep failures local.

**Likely follow-ups:**
1. **Why not autoscale the database?** It scales in minutes to hours and rebalancing adds load mid-burst; we pre-scale for known events, but backpressure covers the unknown spike and a degraded DB.
2. **How is no acknowledged write lost?** Ack only after 2 of 3 replicas, unclean leader election off, commit after the sink write, and hourly reconciliation that alerts on drift.
3. **Read-your-writes with async writes?** Keep a small synchronous path or an ingest-populated cache for the critical class; analytics writes rarely need it.
4. **How do you test it?** Load tests at 1x, 5x, 10x with real key skew, chaos that slows the DB and kills brokers, and game days before each sale.
5. **A tenant needs 3x quota for the sale?** Schedule a burst reservation in advance; others' unused capacity can be lent, never their guaranteed floor.

**Director layer:**
- **Cost drivers:** about 36 brokers and 120 TB of Kafka disk sized for peak, and 65 ingest pods; buffer capacity must not double spend for a few peak days.
- **Phasing:** SDK contract (429, Retry-After, jitter) and bounded buffers first, then the pressure controller and spill.
- **Team ownership:** platform owns gateway, Kafka and controller; producer teams agree priority classes per topic.
- **Top risks:** retry storms causing metastable failure, disk filling in a long sink outage, shedding data a team needed, and an oscillating limiter.
