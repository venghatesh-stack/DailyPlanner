# Design a Pub-Sub System for Event Notifications: the 5-page summary

A pub-sub platform lets a service announce a fact once (order shipped, payment failed) so that any number of independent subscribers can react, without the publisher knowing who they are. The single most important idea: store each event once in a partitioned, replicated log and fan out on read, with a cursor and per-message acks per subscription, so a slow or dead subscriber only delays itself.

## Page 1. The problem, scope and numbers

**Pitch:** a shared, durable event backbone: publish once, deliver at least once to every matching subscription, with retries, replay and reliable webhooks for sellers.

**Why now:** today the order service calls notifications, analytics, seller dashboards, loyalty and fraud one by one. Every new consumer needs a producer change, a slow consumer slows the producer, and each team builds webhooks differently.

**Who uses it:** publisher engineers (know the event is durable when the call returns), internal subscriber engineers (filtered pull or push, parallel work, replay) and external seller developers (signed webhooks, retries, delivery history).

**In scope:**
- **Topics:** partitions, retention up to 7 days, a schema.
- **Publish:** single or batched, with attributes and an optional ordering key.
- **Subscriptions:** pull or push, attribute filter, ack deadline, max attempts, dead-letter topic.
- **Ordering per key and replay:** in order per key; seek to a time or snapshot.
- **Visibility:** backlog, oldest unacked age, delivery logs.

**Out of scope:** end-user push, SMS and email (the Notification Service is just a subscriber), stream processing, global total order, exactly-once to webhooks, synchronous cross-region replication.

**Non-functional targets:**
- **Latency:** publish p50 10 ms, p99 50 ms; publish to push delivery p99 500 ms for healthy endpoints.
- **Durability:** ack after 2 of 3 replicas in separate AZs; RPO 0 in region.
- **Availability:** publish 99.99%, delivery 99.95%.
- **Fan-out and isolation:** start delivering to 10k subscriptions within 1 s; a failing subscription adds zero latency to others.

**Capacity math (2B events/day, 1 KB each, peak 5x):**
- **Publishes:** 2B / 86,400 = 23k/s; x5 = 115k/s. Plan for 100-120k/s, so partition topics.
- **Ingress:** 115k x 1 KB = 115 MB/s; x3 replicas = 350 MB/s of writes. Sequential appends handle that cheaply.
- **Storage:** 2 TB/day x 3 x 7 days = 42 TB. Keep 24 h on SSD (6 TB), the rest in tiered object storage, so replay is affordable.
- **Deliveries:** 115k x 4 subscriptions = 460k/s, about 1 GB/s egress. So never copy events per subscription.
- **Push:** 40% of 460k = 185k HTTP deliveries/s; batching brings this to about 40k requests/s. At 200 ms each, 8k in flight, about 16 workers at 500 each, provisioned 3x.
- **Ack state:** 50k subscriptions x 2k unacked = 100M entries; range-compressed it is a few GB in memory.

## Page 2. The architecture

```
 Publishers (order, payment, catalog): Publish(topic, msgs, attrs, key)
     v
 Publish Front-end ---- schema check ----> Schema Registry
     | append, wait for ISR=2
     v
 Topic Log (partitioned, RF=3, 24 h on SSD + tiered object storage)
     | tail read from each subscription's cursor
     v
 Subscription Dispatchers (filter -> Ack Tracker: cursor + ack ranges)
     | pull leases                     | push tasks
     v                                 v
 Subscriber Front-end              Push Workers (per-endpoint queue,
 (Pull, Ack, ModAck, Seek)          AIMD, breaker, HMAC) -> HTTPS POST
     v                                 v
 Internal consumers                Webhooks (Notification svc, sellers)
 Metadata store: topics, subs, cursors | Dead-letter topic per subscription
```

- **Publish Front-end:** stateless; auth, schema check, picks partition by key hash.
- **Topic Log:** Kafka-like replicated append-only log; old segments tiered to object storage.
- **Metadata store:** strongly consistent configs, cursors and partition ownership; watched by all.
- **Schema Registry:** rejects publishes and schema changes that break compatibility.
- **Subscription Dispatcher:** owns (subscription, partition) by lease; filters, orders, advances cursors.
- **Ack Tracker:** cursor plus acked ranges and deadlines; checkpointed every second.
- **Subscriber Front-end:** pull with long polling and flow control; ack, nack, seek.
- **Push Workers:** per-endpoint queues, signing, batching, backoff, breakers, delivery logs.
- **Dead-letter and cross-region replicator:** failed messages for inspection; async DR mirror.

**Flow A: publish and pull**
1. Order service publishes OrderShipped, key order_123; it hashes to partition 17.
2. Leader appends and waits for one follower in another AZ; returns message_id topic/17/offset.
3. The fraud-sub dispatcher tails partition 17, checks the filter, marks it outstanding.
4. Fraud pulls it with a 10 s ack deadline, processes, acks; the cursor advances if the gap closes.

**Flow B: push to a failing webhook**
1. Worker signs with HMAC-SHA256 and POSTs with a 10 s timeout; the seller returns 503.
2. Retry with jittered backoff (cap 10 min); the endpoint's concurrency is halved.
3. After 10 failures the breaker opens; messages wait in the log. After 5 attempts or 24 h, dead-letter.

## Page 3. The core deep dives

### 1. Fan-out on read: one copy, many cursors
The naive design copies each event into every subscription's queue, so write cost grows with subscribers. Here the event is written once; each subscription only writes small state: cursor, acked ranges, deadlines, attempts. Tailing readers hit the page cache, so 4 or 400 subscriptions on fresh data cost little I/O. Lagging readers use a separate tiered-storage path with its own cache, so they do not evict hot pages. Topics with over 10k subscriptions go to a high-fan-out tier that shards dispatch across many workers. The catch: retention is shared, so alert on slow subscribers before data expires.

### 2. Per-message acks with cursor plus ranges
Plain consumer-group offsets cause head-of-line blocking: one slow message stops the partition. Here consumers ack individually and out of order. Example: offsets 100-109 are delivered; 101-109 are acked but 100 is slow. The tracker stores cursor=100 and acked range [101,109]. When 100 is acked, the cursor jumps to 110. A missed deadline means redelivery with delivery_attempt +1; after 5 attempts, dead-letter. If a dispatcher dies, the new owner reloads the 1-second-old checkpoint and redelivers: duplicates, never gaps.

### 3. Ordering per key, never global
Global order caps throughput at one partition. Instead, the same key goes to the same partition, and an ordered subscription allows only one outstanding message per key. A poison message for order_123 blocks only that key; other keys flow. When it is dead-lettered, the key unblocks, and order for that key is broken, so decide that explicitly. Payloads carry an entity version so consumers can drop stale updates after replay or failover. Adding partitions to an ordered topic remaps keys, so disallow it or drain and switch at a fence offset.

### 4. Webhooks that cannot hurt each other
Each endpoint gets its own queue and its own concurrency window (AIMD: grow slowly on success, halve on failure). Backoff is random(0, min(10 min, 1 s x 2^attempt)). A breaker opens after 10 failures and probes once a minute, so a dead endpoint costs nothing but probes. Requests are signed with HMAC over timestamp plus body against tampering and replay. An egress proxy blocks private IP ranges and re-resolves DNS at send time (SSRF protection).

**Data model:**
- **Log record:** (topic, partition, offset); payload, attributes, ordering_key, producer_id and seq for dedup; 1 GB segments.
- **Topic and Subscription** (metadata store): partitions, retention, schema; filter AST, endpoint, ack deadline, DLQ.
- **Ack state** (compacted internal topic plus memory): key (sub, partition); cursor, ranges, outstanding.
- **Delivery log** (Cassandra, 7-day TTL): key (sub, day), newest first; status code, latency.

**Key APIs:**
- `POST /v1/topics/{topic}:publish`: up to 1,000 messages or 10 MB; returns after ISR ack; 429 over quota.
- `PUT /v1/subscriptions/{sub}`: pull or push, filter, ack deadline 10-600 s, max attempts, DLQ.
- `POST /v1/subscriptions/{sub}:pull`: up to 1,000 messages, long poll up to 30 s.
- `POST /v1/subscriptions/{sub}:acknowledge`: idempotent; modifyAckDeadline 0 means nack.
- `POST /v1/subscriptions/{sub}:seek`: reset to a time or snapshot for replay.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **High-fan-out topics:** write cost stays constant; the high-fan-out tier, batching per endpoint and per-subscription rate limits cap egress.
- **Writes:** more partitions (64 for big topics); publishers batch for 5-10 ms.
- **Reads:** tailing from page cache; lagging reads from tiered storage on a separate path.
- **Noisy publishers:** per-topic token-bucket quotas with 429s; separate cells for the largest tenants.
- **Overload:** keep accepting publishes (the log is the buffer); let push lag, internal critical subscriptions first.

**Failure modes:**
- **Broker dies:** new leaders elected from the ISR in seconds; idempotent retries; brief p99 spike, no loss.
- **Dispatcher dies:** leases expire in about 10 s; another owner reloads the checkpoint and redelivers.
- **Endpoint down for hours:** breaker open, backlog is just a cursor gap; DLQ after 24 h; seller sees it and replays.
- **Metadata store down:** data plane runs on cached configs; config changes fail.
- **AZ loss:** two replicas remain, so writes continue with minISR=2.
- **Region loss:** DNS fails over; async mirror means seconds of loss or duplicates; dedup by message_id.
- **Subscriber near retention:** alert at 50% and 80% of retention age; extend retention temporarily.

**Trade-offs chosen:**
- **Shared log over per-subscription copies:** cost independent of fan-out, free replay; complexity moves into ack tracking.
- **Both pull and push:** pull gives natural backpressure; push is required for webhooks.
- **Per-message acks over offsets:** no head-of-line blocking; per-message retry and DLQ.
- **Per-key, opt-in ordering over global:** global order caps throughput.
- **In-region ISR ack over cross-region sync:** RPO 0 against AZ loss for 2-5 ms; sync cross-region adds 30-80 ms.
- **Attribute filters over payload queries:** saves egress while staying cheap and safe.

**What to measure:** publish rate, errors and p99 per topic; per-subscription unacked count and oldest unacked age (the key health signal); end-to-end latency; redelivery and DLQ rates; push success, status codes and breaker state per endpoint; under-replicated partitions and ISR shrinks; checkpoint lag; 429s per publisher. Canary publishers send sequenced heartbeats to every partition each minute so subscribers can detect gaps.

## Page 5. Say it in the interview

> "Publishers are internal services emitting facts like order shipped; subscribers pull, or receive internal and external webhooks. I assume 2 billion events a day, about 100 thousand a second at sale peaks, average fan-out of four with some topics at ten thousand subscribers, at-least-once per subscription, order only per key, seven-day replay and attribute filters. The naive design copies each event into every subscriber's queue. Instead I store each event once in a partitioned, replicated log and track a cursor and individual acks per subscription. Pull subscribers lease messages with a ten-second ack deadline; push workers batch, retry with jittered backoff and dead-letter after five attempts. Each endpoint is bulkheaded, the log is the buffer under overload, and I watch oldest unacked age per subscription."

**Key points to land:**
- Pub-sub broadcasts facts; each subscription is its own work queue.
- Store once, fan out on read: publish cost does not grow with subscribers.
- At-least-once with message_id and delivery_attempt; consumers dedup.
- Cursor plus ack ranges avoid head-of-line blocking.
- Order per key, one in flight per key; dead-lettering breaks order explicitly.
- Webhooks: per-endpoint bulkheads, AIMD, jittered backoff, breakers, HMAC, SSRF checks.
- RF=3, minISR=2, acks=all gives RPO 0 in region; cross-region is async.
- The log is the buffer; backlog lives on disk, not in RAM.
- Transactional outbox so a DB write and its publish cannot diverge.

**Likely follow-ups:**
1. **Exactly-once to subscribers?** Not across the network. Publishes are deduped with idempotent producers; subscribers dedup by message_id, ideally in the same DB transaction.
2. **How do the order write and the publish both happen?** Transactional outbox: order and outbox row in one transaction; a relay or CDC publishes; duplicates are absorbed by dedup.
3. **1 million webhooks on one topic?** Shard subscribers across many workers, batch per endpoint, rate limit; and ask whether sellers should get a digest or pull API instead.
4. **Why not Google Pub/Sub or SNS plus SQS?** On a single cloud, probably yes. At our scale, cost per delivery, multi-cloud, deep replay and custom webhooks favour Kafka plus our own dispatch layer.
5. **Schema evolution?** Registry with backward compatibility: only add optional fields, never repurpose; breaking changes get a new event version run in parallel.

**Director layer:**
- **Cost drivers:** about 1 GB/s egress, 42 TB of retention (mostly tiered), push workers provisioned 3x for slow endpoints.
- **Adoption goal:** replace 70% of point-to-point fan-out calls within 3 quarters; 99.9% webhook success within 1 hour.
- **Team ownership:** log platform, dispatch and webhooks, schema governance; each producer owns its schemas.
- **Top risks:** egress storms from high-fan-out topics, schema changes breaking consumers, consumers assuming exactly-once, and sellers blaming the platform for dropped events (answer: delivery logs, receipts, replay).
