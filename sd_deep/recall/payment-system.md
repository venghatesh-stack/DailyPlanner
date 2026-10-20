# Payment System (e-commerce pay-in and pay-out): recall card

> **Hook:** Idempotency key per attempt → State machine → Timeout means UNKNOWN → Double-entry ledger → Outbox → Daily reconciliation

**P · Problem:** It's really a correctness problem with external parties that time out, retry and report late, not a scale problem.

**N · Numbers:**
1. About 150 attempts/s average but 5,000/s for 30 minutes at a sale peak, so size for the spike with 2x headroom.
2. 5,000/s x 4 writes = 20,000 DB writes/s, so shard payments 8-16 ways.
3. 10,000 webhooks/s at peak, so the handler only verifies and stores, then processes async.

**H · Hard part:** Zero double charges and zero lost payments when a PSP call can time out with an unknown outcome.

**B · Boxes:** `Order service → Payment service → Payments DB → PSP gateway → PSP`

Side path: `Outbox relay → Kafka → Ledger, Reconciliation, Payout service`.

**D · Decisions:**
1. PENDING plus webhook over synchronous confirmation, because UPI and 3-D Secure are asynchronous and held connections fail on mobile.
2. Several PSPs over one, because higher authorisation rates and sale-day resilience outweigh integration cost.
3. Sharded relational DB with synchronous replicas over looser stores, because constraints and transactions are the cheapest correctness tools.

**F · Failures:**
1. Primary PSP outage on sale day → the breaker opens in about 30 s; new payments shift to other PSPs; the poller resolves in-flight ones.
2. Kafka or relay down → payments still commit; outbox rows wait; orders confirm late, nothing lost.

**C · Close:** "Payments are a correctness problem more than a scale problem. Every attempt has an idempotency key and a persisted state machine. A PSP gateway handles routing and circuit breakers, a double-entry ledger is the source of truth for money, and the outbox keeps state and events together. A timeout goes to UNKNOWN and is resolved by polling, webhooks and daily reconciliation. Duplicate charges and ledger imbalance must always be zero."

**Quiz yourself:**
1. Sethu double-taps Pay. What happens? → The second request gets 409 or the replay; UNIQUE(order_id, attempt_no) is the backstop.
2. How is a ledger mistake fixed? → A new reversing entry, never an update.
3. Why integers in paise? → Floats lose precision on money.
