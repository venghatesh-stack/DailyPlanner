# Design a Payment System (e-commerce pay-in and pay-out): the 5-page summary

A payment system moves money between buyers, the marketplace and sellers through external PSPs (payment service providers) that time out, retry and report late. The single most important idea: traffic is modest, so design for correctness: idempotency keys at every hop, a state machine where a timeout is UNKNOWN rather than FAILED, a double-entry ledger, the outbox pattern, and daily reconciliation.

## Page 1. The problem, scope and numbers

**Pitch:** take payments by card and UPI, refund them, and pay sellers on schedule, with zero double charges, zero lost payments and a provable record of every rupee.

**Who uses it:** buyers (pay in a few taps, clear result, refunds), sellers (balance, pay-out schedule, deductions), finance operators (reconciliation dashboard, exceptions, approved adjustments), and the checkout service (idempotent APIs, reliable events).

**In scope:**
- **Payment intent** per order with an idempotency key; PSP-hosted card fields.
- **Authorise-then-capture** for cards; direct capture or collect for UPI.
- **Webhooks and polling:** verified, idempotent updates; status queries for stuck payments.
- **Refunds:** full and partial, against the original payment.
- **Ledger and pay-outs:** double-entry journal, balances, seller pay-out batches.
- **Reconciliation and routing:** daily match with PSP and bank files; routing by method, bank, success rate and cost.

**Out of scope:** being an acquirer or issuing cards, BNPL and stored-value wallets, fraud model training, tax and invoicing, multi-currency FX in phase 1.

**Non-functional targets:**
- **Correctness:** 0 duplicate charges, 0 ledger imbalance, every payment reaches a terminal state.
- **Latency:** create intent p99 under 300 ms; confirm p99 under 3 s, excluding user authentication.
- **Availability:** 99.99% for create and confirm; degraded mode if a PSP is down.
- **Durability:** synchronous replication for payments and ledger; RPO 0, RTO under 15 minutes; 10-year retention.
- **Security:** PCI-DSS SAQ-A scope (no raw card numbers), signed webhooks, encryption everywhere.

**Capacity math (10M orders/day, 1.3 attempts each):**
- **Attempts:** 10M x 1.3 = 13M/day = about 150/s; normal peak 500/s, sale peak 5,000/s for 30 minutes. So size for the sale spike with 2x headroom.
- **DB writes:** 5,000/s x (1 insert + 3 updates) = 20,000 writes/s. So shard payments 8-16 ways.
- **Ledger:** 13M x 8 lines = about 100M lines/day x 300 B = 30 GB/day, 11 TB/year, 110 TB in 10 years. So append-only and sharded by account.
- **Webhooks:** 2 per attempt = 26M/day, 10,000/s peak. So the handler only verifies and stores, then processes async.
- **PSP concurrency:** 5,000/s x 1.5 s latency / 3 PSPs = 2,500 in-flight calls per PSP. So pool and bulkhead per PSP.

## Page 2. The architecture

```
 Buyer app -> Checkout/Order svc --create intent (Idempotency-Key)-->
                                                       Payment service
                                     Risk svc <-score--   |
                                                          v
                 Payments DB (sharded): payments, attempts, idem keys, outbox
                       |                          ^ signed webhooks
                       v                          |
                 PSP gateway --route, breaker--> PSP A | PSP B | UPI switch
 Outbox relay (CDC) ----> Kafka: payment.events (key = payment_id)
                             |              |               |
                             v              v               v
                    Ledger (dbl entry)  Order svc     Notification svc
                             |
       Reconciliation svc <--+--> Payout svc -> Bank (NEFT/IMPS)
       ^ PSP settlement files, bank statements
       Status poller: PENDING/UNKNOWN > N min -> query PSP
```

- **Payment service:** intents, idempotency, state machine, refunds; the single writer of payment state.
- **PSP gateway:** adapters, timeouts, safe retries, routing, circuit breakers, webhook verification.
- **Risk service:** fraud score and rules before authorisation; can require 3-D Secure or block.
- **Token vault:** PSP and network tokens plus last4, BIN, expiry; never the raw card number.
- **Outbox relay:** publishes outbox rows to Kafka (Debezium CDC); at-least-once.
- **Ledger service:** append-only double-entry journal; debits equal credits per transaction.
- **Status poller:** queries the PSP for payments stuck past 2, 10 and 60 minutes.
- **Reconciliation service:** daily ledger vs PSP settlement vs bank statement; opens exceptions.
- **Payout service:** seller payables from the ledger, bank transfer batches, status tracking.

**Flow A: card checkout**
1. Order service calls POST /payments with key order_id + attempt_no.
2. Payment service replays a stored response if the key exists; else inserts CREATED and the key together.
3. Risk scores; the gateway picks a PSP and passes our payment_id as the PSP's idempotency key.
4. Buyer completes PSP-hosted fields and 3-D Secure; state PENDING.
5. Signed webhook: PENDING -> AUTHORIZED plus outbox row; capture on shipment; ledger posts; order confirmed.

**Flow B: timeout and unknown outcome**
1. PSP call times out after 10 s; payment goes to UNKNOWN, client shows "processing".
2. Poller queries the PSP by our reference at 30 s, 2 min, 10 min.
3. Success: move to AUTHORIZED or CAPTURED. No record: FAILED, new attempt with a new key.
4. Unresolved by end of day: the settlement file decides; a late success on a cancelled order is auto-refunded.

## Page 3. The core deep dives

### 1. Idempotency end to end
Claim the key atomically with a hash of the request body. Completed: replay the stored response. Different body: 422. In flight (locked_until in the future): 409, retry later. The response is stored in the same transaction as the business write, so a crash cannot leave a half-applied request. Example: Sethu double-taps Pay and two requests arrive 50 ms apart; the second gets 409 or the replay, and UNIQUE(order_id, attempt_no) is the backstop. At the PSP, payment_id is the idempotency key, so a retry after a network error cannot charge twice.

### 2. The state machine and UNKNOWN
States: CREATED, PENDING, UNKNOWN, AUTHORIZED, CAPTURED, FAILED, VOIDED, EXPIRED, PARTIALLY_REFUNDED, REFUNDED, DISPUTED. Only legal transitions apply, with an optimistic version check; each writes a history row and an outbox row in the same transaction. A late "pending" webhook after "captured" is recorded and ignored. Webhook and synchronous response race through the same transition, so the second is a no-op. Truth is found in three layers: webhooks, status polling, daily reconciliation.

### 3. Double-entry ledger
Every business event maps to balanced lines in integer paise. Shreya pays Rs 1,499 with a 10% commission and a 2% PSP fee: debit PSP receivable 1,469.02 and PSP fees 29.98; credit seller pending 1,349.10 and commission revenue 149.90. Debits = credits = 1,499. Corrections are new reversing entries, never updates. UNIQUE(source_event_id, account_id, direction) makes replays harmless. The hot commission_revenue account is split into 16-64 sub-accounts by hash(txn_id) to avoid row-lock contention.

**Data model:**
- **payment:** sharded; PK payment_id, UNIQUE(order_id, attempt_no), index (status, updated_at) for the poller; amount_minor as BIGINT, never floats.
- **idempotency_key:** PK (client_id, key) on the same shard; request_hash, stored response, locked_until.
- **payment_event and outbox:** same DB; UNIQUE(psp_event_id) dedupes webhooks.
- **ledger_entry:** sharded by account_id; append-only; per txn_id debits equal credits.
- **recon_item:** (date, psp, psp_reference); matched, mismatch or missing; drives exceptions.

**Key APIs:**
- `POST /v1/payments`: same key and body replays; same key, different body returns 422.
- `POST /v1/payments/{id}/capture`: partial capture up to the authorised amount; card auths expire in about 7 days.
- `POST /v1/payments/{id}/refunds`: row lock enforces sum of refunds <= captured.
- `POST /v1/webhooks/{psp}`: HMAC check, reject timestamps over 5 minutes old, dedupe event id.
- `GET /v1/ledger/accounts/{id}/balance`: from a balance table updated in the same transaction.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **PSPs, not us:** pre-negotiate PSP capacity and TPS, per-PSP bulkheads and breakers, route by success rate.
- **Payment writes:** pre-scale shards and connection pools; admission control at the API.
- **Ledger hot accounts:** sub-accounts, or balances computed asynchronously from entries.
- **Reads:** the payer's own status from the primary (read-your-writes); replicas and caches for dashboards.
- **Non-critical work:** queue notifications and analytics; load-test with PSP sandboxes.

**Failure modes:**
- **Primary PSP outage on sale day:** breaker opens within about 30 s (over 20% errors on 200 requests); new payments shift to other PSPs; the poller resolves in-flight ones.
- **Payments DB primary fails:** failover to the synchronous replica in under a minute; retryable 503s; keys make retries safe.
- **Kafka or relay down:** payments still commit; outbox rows wait; orders confirm late, nothing lost.
- **Webhook flood:** the handler verifies, writes to an inbox and returns 200; PSPs retry any 5xx.
- **Ledger bug posts wrong amounts:** imbalance check or reconciliation catches it; pause, post reversals, replay.
- **Bank rejects a pay-out file:** amounts return to seller payable; resubmit with the same keys.

**Trade-offs chosen:**
- **Return PENDING and confirm via webhook over synchronous confirmation:** UPI and 3-D Secure are asynchronous; holding connections fails on mobile networks.
- **Auth-capture for physical goods, immediate capture for digital and UPI:** a void beats a refund, but auths expire.
- **Sharded relational DB with synchronous replicas:** constraints and transactions are the cheapest correctness tools.
- **Several PSPs over one:** higher authorisation rates and sale-day resilience outweigh integration and reconciliation cost.
- **Separate ledger service fed by the outbox:** clear ownership and audit; consistency via idempotent posting and reconciliation.

**What to measure:** success rate by PSP, method, bank and BIN (the north star); duplicate charges and ledger imbalance (both must be 0, page on any); PENDING and UNKNOWN by age bucket; PSP latency and breaker changes; webhook lag; outbox and consumer lag; reconciliation auto-match rate (target 99.99%) and open exceptions; refund and pay-out timeliness.

## Page 5. Say it in the interview

> "Payments are a correctness problem more than a scale problem: about 150 payments a second on average and 5,000 on sale days, but zero tolerance for double charges. The naive version calls the PSP and marks the order paid; it double-charges on retries and loses payments on timeouts. So my core is a payment service with an idempotency key for every attempt and a persisted state machine, a PSP gateway with routing and circuit breakers, a double-entry ledger as the source of truth for money, and the outbox pattern so state changes and events never diverge. A payment that times out goes to UNKNOWN and is resolved by querying the PSP, by webhooks, and finally by daily reconciliation. The two numbers that must always be zero are duplicate charges and ledger imbalance."

**Key points to land:**
- A correctness problem: 150/s average, 5,000/s peak, zero double charges.
- Idempotency keys at every hop, backed by unique constraints.
- A timeout is UNKNOWN, not FAILED; query before any retry.
- Double-entry ledger: append-only, balanced, idempotent; imbalance is a page.
- Outbox so state changes and events never diverge.
- Three layers of truth: webhooks, polling, daily reconciliation.
- PSP gateway with routing, breakers and bulkheads; never retry hard declines.
- Sagas with void and refund compensations across order, inventory and payment.
- No raw card numbers; integers in paise, never floats.

**Likely follow-ups:**
1. **How do you never charge twice?** A key per attempt at our API, payment_id as the PSP's key, unique constraints, UNKNOWN instead of blind retries, and reconciliation to refund any late duplicate.
2. **How do you handle 10x sale traffic?** Pre-scale shards and pools, pre-negotiate PSP capacity, queue non-critical work, route aggressively, admission control at the API.
3. **Where is card data stored?** Nowhere raw: PSP-hosted fields; we keep a token and last4, BIN, expiry, with network tokens under RBI rules.
4. **Why not eventual consistency everywhere?** Inside a payment, state, key and outbox need one ACID transaction; across services, reliable events plus reconciliation are enough.
5. **How do you test it?** A fault-injecting PSP simulator (timeouts, duplicate and late webhooks), property tests on the state machine, ledger invariants checked in CI and production.

**Director layer:**
- **Cost drivers:** PSP fees and multi-PSP integrations, 8-16 payment shards with synchronous replicas, 110 TB of ledger over 10 years, reconciliation and finance operations.
- **Phasing:** multi-currency FX is out of phase 1; new methods like BNPL plug in as adapters with ledger rules.
- **Team ownership:** payments core, PSP gateway and routing, ledger and reconciliation (with finance), pay-outs, risk.
- **Top risks:** double charges after timeouts, a PSP outage on sale day, unnoticed ledger-PSP drift, fraud and chargebacks; plus PCI, RBI tokenisation and data localisation compliance.
