# Design Exactly-Once-Like Processing Using Idempotency: the 5-page summary

This design makes retried order and payment work safe, so a lost acknowledgement never becomes a double charge, a double refund or stock decremented twice. The single most important idea: exactly-once delivery is impossible, but exactly-once effect is not: deliver at least once, and at every hop commit a dedup record in the same transaction as the side effect.

## Page 1. The problem, scope and numbers

**Pitch:** mobile apps, gateways, service meshes and consumers all retry. Each retry is reasonable; together they double charge customers, and the duplicate rate spikes on sale days exactly when traffic peaks. Make every mutating call and every consumer safe to retry by design.

**Who uses it:** shoppers (charged once), service teams (shared libraries, not hand-rolled dedup), finance (ledger matches the gateway), on-call (see duplicates caught and stuck requests).

**In scope:**
- **Idempotency-Key** on every POST/PATCH/DELETE, required on payments; scoped per tenant, with a request fingerprint and the stored final response.
- **Multi-phase requests** with recovery points that resume on retry.
- **Derived keys** for foreign calls (k1:charge for the payment gateway).
- **Transactional outbox** to publish events, **consumer inbox** to dedup them.
- **Completer** for abandoned requests, **reaper** for expired keys, **daily reconciliation** against the gateway.

**Out of scope:** 2PC/XA across services, cross-region active-active writes for one key, fraud detection of deliberate repeat purchases, providers with no idempotency or status API.

**Non-functional targets:**
- **Latency:** middleware overhead p99 under 5 ms per request.
- **Correctness:** no duplicate effect within the key window; business-key uniqueness forever.
- **Durability:** the key record commits in the same transaction as the business write.
- **Availability:** fail closed for payments (reject rather than risk a duplicate), fail open for low-risk endpoints.
- **Retention:** API keys 72 h; consumer inbox 7 days, matching bus retention.
- **Throughput:** 20k keyed API requests/s and 200k consumer events/s at peak.

**Capacity math (3k requests/s average, 20k/s peak):**
- **Key storage:** 260M keyed requests/day x 3 days = 780M rows x 600 B = about 470 GB over 32 shards, about 15 GB each. So keys can live in the business database, sharded with the orders.
- **Key writes:** 20k inserts + 20k finishes = 40k writes/s, about 1.25k/s per shard. Well within capacity.
- **Inbox writes:** 200k events/s x 6 consumers = 1.2M inserts/s, spread over consumer databases.
- **Inbox storage:** a consumer at 40k events/s x 86,400 x 7 days = 24B rows x 80 B = about 2 TB. Too much, so high-volume consumers store a per-partition offset watermark instead (64 rows).
- **Duplicates:** 0.5% retries is 100 duplicates/s at peak, each served from the stored response in about 2 ms.

## Page 2. The architecture

```
 Client SDK (one key per user action, retries with jitter)
    | POST /orders/{id}/pay   Idempotency-Key: k1
    v
 API gateway (never retries a POST without a key)
    v
 Order-Pay service: Idempotency middleware -> phase runner (recovery points)
    | tx: key + order       | charge, key k1:charge   | tx: charge + outbox
    v                       v                         v
 Orders DB shard        Payment gateway          outbox (same shard)
 (idempotency_keys)     (idempotent API)              | CDC relay
                                                      v
                              Kafka (idempotent producer, read_committed)
                                  |              |               |
                              Inventory       Loyalty       Notifications
                              inbox + tx      inbox + tx    best-effort
 Completer (stuck keys)    Reaper (keys > 72 h)    Reconciler (daily)
```

- **Client SDK:** one UUIDv4 key per action, kept until a final answer; backoff with jitter.
- **Idempotency middleware:** fingerprint, insert or load the key, lease lock; 409 or 422.
- **Phase runner:** each phase commits its writes with the new recovery point.
- **Key store:** in the business shard, unique (tenant_id, key), partitioned by day.
- **Outbox and relay:** event rows in the business transaction; Debezium CDC publishes them.
- **Inbox library:** inserts (consumer, event_id) in the consumer's own transaction.
- **Completer:** finishes keys stuck over 5 minutes with no active lock.
- **Reconciler:** compares our ledger with gateway settlement files daily.

**Flow A: pay, response lost, retry**
1. Insert key row (k1, fingerprint, recovery_point=started, locked).
2. Charge the gateway with key k1:charge; get ch_9.
3. One transaction: charge row, OrderPaid outbox row, recovery_point=charge_created.
4. Store 200 {ch_9}, set finished; the response is lost on the network.
5. Retry with k1 finds finished and a matching fingerprint: return stored 200, gateway untouched.

**Flow B: event consumed once in effect**
1. Relay publishes outbox row 7781 as OrderPaid(event_id 7781), crashes, republishes it.
2. Inventory inserts processed_events(inventory, 7781), decrements stock, commits, crashes before its offset commit.
3. On restart the insert hits the unique constraint; the handler is skipped and the offset advances.

## Page 3. The core deep dives

### 1. The idempotency key: insert-or-load, fingerprint, lease
The key is claimed with INSERT ... ON CONFLICT DO NOTHING on a unique index; whoever inserts first runs. Otherwise the row is loaded FOR UPDATE. A different fingerprint (hash of method, path and normalised body) means a client bug: 422, never the cached answer. A finished row returns the stored response. A row locked under 60 s ago returns 409, retry later. Only final outcomes (success, card declined, validation error) are stored; a transient 500 just clears the lock, so the retry resumes. Lease checks use the database clock, never the pod's.

### 2. Atomic phases and recovery points for foreign calls
Never hold a transaction open across a network call. The pay flow moves started -> charge_created -> finished. Example: the pod charges Shreya's card, then crashes before phase 3 commits. The row stays at started with a lock expiring in 60 s. Her retry after 2 s gets 409; after backoff it takes the lock and resumes. The gateway is called again with k1:charge and returns the original ch_9 instead of charging twice. If she never returns, the Completer finishes it after 5 minutes. A slow original (GC pause) that wakes late is fenced: each phase updates WHERE recovery_point = expected, so its commit fails.

### 3. Outbox, inbox and watermarks
Writing to the database and then to Kafka will eventually diverge. The outbox puts the event row in the same transaction; the relay publishes at least once with event_id = outbox id. Consumers commit the inbox row and their change together, and only then the Kafka offset; reversed, a crash loses the event. High-volume consumers keep one offset watermark per partition plus entity versions, so a republished duplicate with a new offset is still a no-op.

### 4. Kafka exactly-once covers only Kafka
The idempotent producer (producer id plus sequence numbers) removes broker-retry duplicates, and transactions make Kafka-to-Kafka steps atomic. Database writes and gateway charges are outside Kafka, so they still need their own keys.

**Data model:**
- **idempotency_keys** (Orders DB, by day): UNIQUE (tenant_id, key); fingerprint, recovery_point, locked_at, response (PII-redacted).
- **charges:** PK charge_id; UNIQUE (order_id, attempt_type) as the business backstop after keys expire.
- **outbox:** PK id (becomes event_id), sent_at; CDC tails the binlog.
- **processed_events** (each consumer DB): PK (consumer, event_id); dropped after 7 days.
- **partition_watermarks:** PK (consumer, topic, partition), last_offset.

**Key APIs:**
- `POST /v1/orders/{order_id}/pay`: 402 is final and cached; 409 and 503 retry with the same key.
- `POST /v1/refunds`: total refunds never exceed the captured amount, checked under a row lock.
- `GET /v1/idempotency/{key}`: support and debugging, bodies redacted.
- `POST /charges` (gateway): keys kept 24 h; query by metadata after that.
- `order-events` topic: key order_id; enable.idempotence=true, acks=all.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Key writes:** keys shard with the business data, so they scale with the order shards.
- **Inbox size:** move high-volume consumers to offset watermarks plus versions; time-partitioned tables drop cheaply.
- **Retry storms:** retry at one layer only, full jitter (200 ms base, 10 s cap, 4 attempts), only on transient errors and 409.

**Failure modes:**
- **Orders DB primary fails:** 503 for that shard (fail closed); clients retry with the same key after promotion.
- **Pod crashes mid-request:** lease expires in 60 s; retry or Completer resumes; the derived key prevents a double charge.
- **Gateway times out:** outcome unknown, phase does not advance; the retry with the same key returns the original result or charges once.
- **Relay crashes after publishing:** rows republished with the same event_id; inboxes dedup.
- **Retry after the gateway's 24 h retention:** query by order_id metadata and adopt any existing charge.
- **Client makes a new key per retry:** UNIQUE (order_id, capture) and the gateway metadata check catch it.
- **Replay after inbox expiry:** entity versions make stale events no-ops.
- **Reconciler finds a duplicate:** automatic refund keyed refund:charge_id, plus an incident.

**Trade-offs chosen:**
- **Keys in the business shard over Redis:** only a shared local transaction makes record and effect atomic without 2PC; Redis is for low-risk dedup.
- **Outbox with CDC over 2PC:** Kafka does not join XA; 2PC blocks and adds latency.
- **409 over waiting on an in-flight duplicate:** holding connections wastes resources and can deadlock.
- **72 h keys, permanent business uniqueness:** covers realistic retries; forever-uniqueness belongs on business tables.
- **Fail closed for money, open for low-risk:** a short payment outage beats a duplicate charge.
- **Best-effort SMS dedup (Redis SETNX, 24 h):** a rare duplicate message is acceptable.

**What to measure:** cached replays per endpoint, 409 and 422 rates per client version, stuck keys by age and Completer actions, inbox skip rate per consumer, oldest unsent outbox row, gateway replays versus new charges, reconciliation mismatches by type, middleware p99 and fail-closed rejections.

## Page 5. Say it in the interview

> "A client pays for an order, we charge a gateway, emit OrderPaid, and inventory, loyalty and notifications react. Duplicates come from client retries, proxies, producer retries and redelivery. Money and stock must be exactly-once in effect; a duplicate SMS is tolerable. Assume 20 thousand payments a second at peak and 200 thousand events a second. Exactly-once delivery is impossible, but at-least-once plus idempotent processing gives exactly-once effect, so I put a boundary at every hop. At the API, an Idempotency-Key stored with a fingerprint and the final response, in the order's own database with a unique index. The request runs in phases with recovery points, and the gateway call reuses a derived key, so a retry resumes safely. Events go through an outbox, and each consumer records the event id in the same transaction as its write. A daily reconciliation proves it."

**Key points to land:**
- Exactly-once effect = at-least-once delivery + idempotent receiver.
- A boundary at every hop: client-API, service-gateway, relay-bus, bus-consumer.
- The dedup record commits with the effect, in the same shard, no 2PC.
- Keys: client-generated, tenant-scoped, fingerprinted; 409 in progress; cache only final outcomes.
- Atomic phases, derived keys for foreign calls, a completer for abandoned work.
- Outbox to publish; inbox or offset watermark to consume.
- Kafka EOS covers Kafka-to-Kafka only.
- Business uniqueness and versions are the backstop after keys expire.
- Retry with jitter at one layer; reconcile against an independent ledger.

**Likely follow-ups:**
1. **Why not just Kafka exactly-once?** It covers Kafka-to-Kafka only; our effects are database writes and gateway charges, which need their own idempotency.
2. **Why not 2PC across the DB and Kafka?** Kafka does not support XA, 2PC blocks on coordinator failure, and it adds latency; an outbox gives atomicity with one local transaction.
3. **Client reuses a key days later?** An expired key counts as new, which is why SDKs use a UUIDv4 per action and one-capture-per-order uniqueness stays as the backstop.
4. **Dedup 1M events/s cheaply?** Process partitions in order and store a per-partition watermark in the same transaction, plus entity versions for republished duplicates.
5. **Support agent clicks refund twice?** The UI makes one key per refund intent, and the server caps total refunds at the captured amount under a row lock.

**Director layer:**
- **Cost drivers:** about 470 GB of 72-hour keys, inbox tables per consumer (TB-scale without watermarks), CDC and reconciliation jobs; overhead held under 5 ms p99.
- **Phasing:** keys and middleware on payment and order APIs first (100% coverage), then outbox and inbox libraries, then 80% of all mutating APIs.
- **Team ownership:** a platform team owns the libraries and Completer; service teams adopt them; finance owns reconciliation.
- **Top risks:** clients minting a new key per retry, key reuse with different parameters, unbounded key growth, retrying a non-idempotent call after an unknown outcome.
- **Proof:** fault injection between every phase, dropped responses and topic replays, asserting zero reconciliation mismatches.
