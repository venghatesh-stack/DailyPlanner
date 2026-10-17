# Design a ticket booking system (Ticketmaster / BookMyShow): the 5-page summary

Ticket booking looks like simple CRUD until a big concert on-sale sends 10 million people at 60,000 seats in ten minutes. The single most important idea: separate browsing (cached, stale is fine) from booking (strongly consistent), put a virtual waiting room in front of booking, and make hold-pay-confirm a short conditional update plus an idempotent saga, so a seat is never sold twice.

## Page 1. The problem, scope and numbers

**Pitch:** a fair, fast way for fans to get tickets, and a way for organisers to sell out without overselling or crashing.

**Who uses it:** fans (fair access, no double charges), organisers and venues (sell out, held-back seats respected), finance (payments reconcile, refunds on time), trust and safety (bots and scalpers).

**In scope:**
- **Browse and search** events by city, date, venue and genre.
- **Seat map** with per-seat status (available, held, sold, blocked) and price tiers; general admission counts.
- **Waiting room** for high-demand events: queue tokens and controlled admission.
- **Atomic holds:** up to N seats, all or none, 10-minute TTL, extended once when payment starts.
- **Checkout** via an external payment gateway with idempotency keys and webhooks.
- **Tickets:** signed QR tickets, notifications, cancel and refund, per-user and per-card limits.

**Out of scope:** resale marketplace, dynamic pricing, venue gate hardware, recommendations.

**Non-functional targets:**
- **Consistency:** linearizable seat transitions, zero double sells.
- **Latency:** hold p99 under 300 ms at 20k hold attempts/s per hot event; browse p99 under 200 ms; seat map at most 5 s stale.
- **Availability:** booking 99.95%, browse 99.99%.
- **Durability:** confirmed bookings never lost (synchronous replica, RPO 0).
- **Scale and fairness:** 10M concurrent waiting users; 2,000-5,000 admissions/s; FIFO after a randomised pre-queue; 4 tickets per account.

**Capacity math:**
- **Steady bookings:** 2M/day / 86,400 = about 23/s, peak 5x about 120/s, holds about 350/s. Small, so steady state is not the problem.
- **Steady browse:** 100 reads per booking = about 12k QPS at peak, mostly cacheable. So CDN plus Redis.
- **On-sale joins:** 10M users / 600 s = about 17k joins/s; polling every 10 s gives 1M status reads/s. So queue status is served at the edge plus Redis, never the database.
- **Admission:** if the booking tier takes 5k holds/s and each user makes about 2 attempts, admit about 2,500 users/s. 20,000 orders of 3 seats sell out the stadium in well under a minute of admitted traffic.
- **Storage:** 1M movie shows/day x 200 seats x 100 B = 20 GB/day of seat rows (archived after the show); bookings 2 GB/day, about 730 GB/year.
- **Seat map:** 60k seats x 2 bits = 15 KB per stadium. Trivial to cache and push.

## Page 2. The architecture

```
 Users (app / web)
     |
     v
 CDN (event pages, seat layouts) -> API gateway / WAF / bot check
     |                         |  hot event? <-> Waiting room (Redis queue,
     | browse                  |  book            admission control, JWT)
     v                         v  (token required)
 Catalog / Search      Booking + Inventory svc <-> Payment svc <-> Gateway
     |                    |               |                      (webhooks)
     v                    v               v
 Elasticsearch     Redis seat map    Inventory DB (Postgres, by show,
                        ^            sync replica): seats, holds, orders
                        |                 | outbox / CDC
                        +------ Kafka <---+--> Ticketing (QR), Notify,
                                              Analytics, Reconciliation
```

- **CDN:** event pages, images and seat-map geometry; absorbs most reads.
- **API gateway and WAF:** auth, rate limits, CAPTCHA, bot scoring, admission-token checks.
- **Waiting room:** queue positions in Redis, admits at a controlled rate, issues 15-minute signed tokens.
- **Catalog and search:** events, venues and prices from Elasticsearch.
- **Inventory service:** authoritative seat state machine; atomic multi-seat holds and expiry.
- **Booking service:** order lifecycle; orchestrates the hold-pay-confirm saga.
- **Payment service:** idempotent intents, webhooks, reconciliation, refunds.
- **Seat-map cache:** Redis bitmap per show, refreshed from inventory events.
- **Expiry sweeper:** releases expired holds every 5-10 s.
- **Kafka with outbox:** keeps caches, tickets and analytics in sync without dual writes.

**Flow A: hold and pay**
1. Admitted user picks 3 seats; `POST /holds` with an idempotency key.
2. One transaction moves seats AVAILABLE -> HELD; commit only if 3 rows changed.
3. Order PENDING_PAYMENT; payment intent keyed by order_id.
4. Webhook verified and deduped; seats HELD -> SOLD if the hold is ours; order CONFIRMED; QR issued.

**Flow B: waiting room**
1. Users present at T0 are shuffled randomly; later arrivals join FIFO.
2. A controller advances "now serving" by N per second based on booking health.
3. Clients poll every 10-15 s and get an admission token when their turn comes.

## Page 3. The core deep dives

### 1. The atomic hold: a compare-and-set per seat
`UPDATE seats SET status='HELD', hold_id=?, expires_at=now()+10min WHERE show_id=? AND seat_id IN (...) AND status='AVAILABLE'`. If Shreya asks for 3 seats and 3 rows change, commit; if only 2 do, roll back and return 409 with the taken seat. If Sethu clicks the same seat in the same millisecond, exactly one update wins. Seat IDs are sorted to avoid deadlocks, all seats of a show sit on one shard so this is a single-shard transaction, and no lock is held during user think time.

### 2. Holds are leases with expiry
Every hold carries expires_at from the database clock, never app-server time. A sweeper releases expired holds every 5-10 s, and reads treat HELD past expiry as available (lazy expiry), so a crashed worker can never lock a seat forever. When payment starts, the hold is extended once by up to 5 minutes for slow UPI payments.

### 3. Payment as an idempotent saga
Payments are external, slow (1-30 s) and sometimes return unknown outcomes, so they cannot join a transaction. Hold, then pay with idempotency key = order_id, then confirm HELD -> SOLD. Webhooks are deduped by gateway event id. If the webhook is lost, reconciliation polls the gateway for PENDING orders older than 2 minutes. If payment succeeds after the hold expired, try to re-grab the same seats; if they are gone, mark FAILED and auto-refund.

### 4. Adaptive admission
The waiting room treats the booking tier like a congested network link: add 200 users/s while healthy; multiply by 0.7 when hold p99 exceeds 300 ms, errors exceed 1% or DB CPU exceeds 70%. Close the queue as SOLD_OUT when inventory reaches zero.

**Data model:**
- **seat_inventory** (Postgres, sharded by show_id): PK (show_id, seat_id); status, hold_id, expires_at, order_id, version.
- **orders:** PK order_id; unique (user_id, idempotency_key) makes create-order idempotent.
- **payments:** unique (gateway, gateway_ref); raw webhook events.
- **general_admission_counter:** held = held + n WHERE capacity - sold - held >= n.
- **queue** (Redis per event): sorted set of tickets by position plus a "now serving" pointer.

**Key APIs:**
- `GET /v1/shows/{showId}/seatmap`: layout from CDN, status from Redis, up to 5 s stale.
- `POST /v1/shows/{showId}/holds`: all or nothing; a retry with the same key returns the same hold.
- `POST /v1/orders/{orderId}/payment`: idempotency key = orderId; extends the hold once.
- `POST /v1/webhooks/payments`: deduped by gateway event id.
- `GET /v1/queue/{eventId}/status`: from Redis, edge-cached for a few seconds.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **On-sale herd:** the waiting room turns 10M arrivals into a rate the database can take; status polls never reach the DB.
- **Seat-map reads:** Redis bitmaps refreshed by CDC; DB reads would multiply load 100x.
- **Mega event on one shard:** pre-place it on a dedicated shard; split GA counters into sub-counters.
- **Hot sections:** offer server-side "best available" so thousands do not collide on the front rows.
- **Many small shows:** spread naturally across shards and rarely need a waiting room.

**Failure modes:**
- **Inventory DB primary fails mid on-sale:** synchronous replica promoted in 10-30 s; admission drops to 0 so users wait instead of erroring; holds are durable.
- **Payment gateway degraded:** fail over to a secondary gateway, extend holds once, reconcile by polling, slow admission.
- **Kafka or outbox relay down:** bookings still succeed (DB is truth); seat maps go stale and tickets are delayed until the relay catches up.
- **Waiting-room Redis node lost:** replica promoted; positions are also in the signed tickets.
- **Sweeper stuck:** lazy expiry keeps seats sellable; alert on expired-but-HELD rows.
- **Bot attack:** WAF, bot scoring, CAPTCHA step-up, suspicious tickets demoted before admission.

**Trade-offs chosen:**
- **Database conditional update over Redis locks:** Redis failover can drop locks; the DB is durable and the waiting room bounds contention.
- **Logical hold with TTL over row locks:** no locks across think time, and it survives crashes.
- **Waiting room over returning errors:** errors cause refresh storms and anger; a queue is fair and protects the core.
- **Cached seat map over live DB reads:** staleness is safe because the hold is authoritative.
- **Orchestrated saga over 2PC:** gateways cannot join 2PC; orchestration gives timeouts and clear refunds.
- **Postgres sharded by show:** constraints, transactions and team familiarity; DynamoDB conditional writes are a fine alternative.

**What to measure:** an oversell detector (seats with more than one confirmed order; page at 1); hold attempts, success, 409 rate and p99 per hot event; queue length, admit rate, wait and abandonment; hold-to-payment and payment-to-confirm conversion; PENDING orders older than 5 minutes and orphaned payments; expired-but-HELD count; outbox lag and seat-map staleness; bot and per-account outliers.

## Page 5. Say it in the interview

> "We sell reserved seats for movies and big concerts, with a 10-minute hold, and we must never sell a seat twice. Normal load is small, about 120 bookings a second, but one on-sale can bring 10 million people for 60,000 seats, so I design for the spike. I split a cached read path for catalog and seat maps from a strongly consistent inventory service sharded by show. Hot events sit behind a virtual waiting room that admits users at a rate driven by backend health. A hold is one conditional update from available to held with a database-clock expiry, all or nothing. Payment uses an idempotency key, and the webhook moves held to sold only if the hold is still ours. Late payments re-grab the seats or are refunded, and oversell is monitored at zero."

**Key points to land:**
- Split the read path (cached, stale OK) from the write path (strongly consistent).
- The waiting room converts a 10M spike into a controlled admission rate.
- Hold = conditional UPDATE WHERE status='AVAILABLE', all or nothing, in one short transaction.
- Holds are leases on the database clock, swept actively and expired lazily.
- Never hold a lock across payment; booking is a saga with refunds as compensation.
- Idempotency keys on hold, order and payment; webhooks deduped by event id.
- Shard by show; dedicated shards for mega events; split GA counters.
- Outbox plus CDC keep caches and tickets in sync without dual writes.
- Late payment after expiry: re-grab if possible, else auto-refund.
- Oversell must be zero and is watched continuously.

**Likely follow-ups:**
1. **Redis says a seat is free but it is not?** Redis is only a view; the DB conditional update decides, so a stale cache just yields a 409.
2. **General admission?** A counter per section, held = held + n only while capacity - sold - held >= n, split into sub-counters for hot events.
3. **How is the queue fair against bots?** Verified pre-registration, randomise everyone present at T0, one ticket per account and device, CAPTCHA, per-card limits.
4. **Phone goes offline during payment?** Webhooks and reconciliation finish the booking server-side; the app fetches status on reconnect.
5. **Scanning tickets with poor venue internet?** The QR is a signed JWT verified offline; scanners sync later and the first scan wins.

**Director layer:**
- **Cost drivers:** pre-scaled capacity and edge serving for on-sale spikes, load tests at 2x the expected peak, and gateway fees.
- **Phasing:** start with a sharded inventory DB, holds with TTL and the payment saga; add the waiting room, best-available allocation and bot defences for mega events.
- **Team ownership:** discovery and catalog, inventory and booking, payments, waiting room and edge, trust and safety.
- **Top risks:** thundering herd on the DB, paid but unconfirmed bookings, bots buying inventory, and public backlash from opaque failures.
