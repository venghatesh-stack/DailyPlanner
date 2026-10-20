# ticket booking system (Ticketmaster / BookMyShow): recall card

> **Hook:** Cache browse → Waiting room → Conditional hold → Pay with idempotency → Confirm or refund

**P · Problem:** It's really a contended-inventory problem: a sudden herd fighting over a few seats that must never be sold twice.

**N · Numbers:**
1. 10M users polling every 10 s is 1M status reads/s, so queue status is served from the edge and Redis, never the database.
2. The booking tier takes 5k holds/s with about 2 attempts per user, so admit about 2,500 users/s.
3. About 120 bookings/s in steady state, so normal load is small and the design is for the on-sale spike.

**H · Hard part:** Turning a 10M-person spike into a safe rate, and keeping hold-pay-confirm correct when payments are slow and outcomes unknown.

**B · Boxes:** `CDN → API gateway / WAF → Waiting room → Booking + Inventory → Postgres sharded by show`

Side path: `Postgres outbox → Kafka → Redis seat map, QR tickets, notifications`.

**D · Decisions:**
1. Database conditional update over Redis locks, because Redis failover can drop locks and the DB is durable.
2. Waiting room over returning errors, because errors cause refresh storms and a queue is fair.
3. Orchestrated saga over 2PC, because payment gateways cannot join 2PC and refunds stay clear.

**F · Failures:**
1. Inventory DB primary fails mid on-sale → sync replica promoted in 10-30 s; admission drops to 0 so users wait.
2. Payment succeeds after the hold expired → re-grab the same seats, else mark FAILED and auto-refund.

**C · Close:** "I split a cached read path for catalog and seat maps from a strongly consistent inventory service sharded by show. Hot events sit behind a waiting room that admits users at a rate set by backend health. A hold is one conditional update from available to held, all or nothing, with a database-clock expiry. Payment uses the order id as its idempotency key, and the webhook moves held to sold only if the hold is still ours. Oversell is monitored at zero."

**Quiz yourself:**
1. Redis says a seat is free but it is not? → The DB update decides; the user gets a 409.
2. Why can a crashed worker never lock a seat forever? → Holds expire; the sweeper and lazy expiry release them.
3. How does the waiting room pick its rate? → Add 200/s while healthy, multiply by 0.7 when hold p99 passes 300 ms.
