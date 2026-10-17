# Design a flash sale system (Big Billion Days style sale event): the 5-page summary

At 00:00 on day one of a big Indian sale, tens of millions of users open the app at once and hammer a few hundred deal SKUs with tiny stock, such as 1,000 phones at Rs 9,999. The single most important idea: shape demand before it reaches inventory (CDN for reads, a waiting room only for deal checkout), make the stock decrement atomic and cheap in Redis with a durable database guard behind it, and bound every arrow to the slowest dependency behind it.

## Page 1. The problem, scope and numbers

**Pitch:** stay up under 50-100x normal load, sell limited deals fairly without overselling, and turn demand into paid, deliverable orders.

**Who uses it:** deal hunters (Shreya at 11:58 pm on Android, paying by UPI), regular shoppers (Sethu, card offer and EMI), category managers, war room SREs, sellers, banks and warehouses.

**In scope:**
- **Deal config** (price, quota, slot, per-user limit) and a **virtual waiting room** for deal checkout with signed, short-lived admission tokens and position and ETA.
- **Atomic reservation** with a per-user limit and a 10-minute TTL (15 for pending UPI collect).
- **Checkout and payment:** serviceability, offers, idempotent orders, release on expiry, refunds for late success.
- **Stock hints, war-room controls and anti-abuse** (bot scoring, device and payment instrument limits).

**Out of scope:** search and recommendation algorithms, warehouse and last-mile, seller onboarding, post-sale returns, dynamic pricing in a slot.

**Non-functional targets:**
- **Availability:** 99.99% for browse, cart, checkout and payment in the sale window; the rest degrades.
- **Latency:** PDP p99 under 300 ms at the edge, reserve p99 under 50 ms, checkout p99 under 1 s, queue poll under 100 ms.
- **Consistency:** linearizable decrement per deal (zero oversell); stock hints eventual within 1-2 s.
- **Durability:** order intents in Kafka (RF 3, acks=all) before the 202; every paid order ships or is refunded within 30 minutes.
- **Fairness:** randomized admission at the opening, 1 unit per user, bots under 1% of deal buys.

**Capacity math (60M users on day one, 8M concurrent sessions at peak):**
- **Page views:** 8M sessions / 8 s = 1M req/s; at 95% CDN hit, origin sees about 50k/s plus 300k/s API calls. So reads live at the edge and in pre-warmed caches.
- **Buy attempts:** 20M users x 2 taps in 120 s = about 330k/s. So a waiting room admits only about 25k/s.
- **Reservations:** 25k/s over 32 counter shards per deal is under 1k ops/s per shard, against about 100k/s a Redis shard can do. So shard the counter and rate-limit upstream.
- **Orders:** 500k deal units in about 2 minutes is about 4k/s, plus 6k/s normal = 10k writes/s into 64 MySQL shards (about 150/s each). So write orders asynchronously via Kafka (10k/s x 5 KB = 50 MB/s).
- **Payments:** 10k initiations/s, but each gateway takes 2-3k TPS. So route across 4-5 gateways: payment partners are the real ceiling.

## Page 2. The architecture

```
 Mobile/Web -> GSLB -> CDN + WAF + bot score (deal pages, TTL 5-10 s)
                          v
          API gateway (priority classes, load shedding, rate limits)
     |              |              |                 |              |
     v              v              v                 v              v
 Browse/Search   Cart svc     Waiting room       Checkout      Reco (shed 1st)
 (Aerospike)                  (ZSET, tokens) --> Deal inventory
                                                 Lua reserve, 32 Redis shards
                                                    | order intent
                                                    v
                                             Kafka (RF 3, acks=all)
                    |                               |                |
                    v                               v                v
       Order svc (MySQL, sold<quota) <-- Payment orch.   Expiry + recon 30 s
 Control plane: flags, degradation L0-L5, admission rate knob, dashboards
```

- **CDN and edge:** absorb about 95% of reads, WAF, bot scoring, coarse rate limits.
- **API gateway:** classifies priority (pay > cart > browse > reco) and sheds the lowest first.
- **Browse and search:** read-only, from pre-warmed Aerospike, Redis and local caches.
- **Waiting room:** Redis sorted set per deal; admits batches; HMAC tokens bound to user.
- **Deal inventory:** owns quota; atomic Lua reserve, release, sold-out flags.
- **Kafka:** durable buffer between reservation and order creation; smooths MySQL writes.
- **Order service:** idempotent orders, final conditional quota update, the state machine.
- **Payment orchestrator:** health-weighted gateway routing, callbacks, polling, refunds.
- **Expiry and reconciliation:** release expired holds; fix Redis vs DB drift every 30 s.

**Flow A: deal drop purchase**
1. T-30 min: pages and prices pushed to CDN and caches; Redis preloaded with 98% of quota over 32 sub-counters.
2. T-0: Shreya taps Buy; no token, so she joins the queue with a random score and polls every 3-5 s.
3. Admitter pops 25k users/s; she gets a signed token {user, deal, exp}.
4. Reserve: Lua on shard hash(user) checks her hold, decrements if above 0, else tries 2 more shards; hold TTL 600 s.
5. Intent to Kafka, 202 to the client; Order service inserts PAYMENT_PENDING and runs UPDATE ... WHERE sold < quota.
6. UPI callback verified; order CONFIRMED; fulfilment and notifications follow.

**Flow B: payment fails or hold expires**
1. Order CANCELLED; a shard is INCRed and her hold removed so she can retry.
2. A late UPI success re-reserves if quota remains, else auto-refunds.

## Page 3. The core deep dives

### 1. Atomic reservation: fast gate plus durable guard
Oversell is a check-then-act race, so check and act must be one step. The Lua script runs atomically in Redis: reject a second hold by the same user, decrement the shard only if positive, and record the reservation with a TTL. Row locks in MySQL would also be correct but serialise to a few hundred a second on one hot row. Behind Redis, the order consumer runs `UPDATE deal_quota_ledger SET sold = sold + 1 WHERE deal_id = ? AND sold < quota`; zero rows means cancel and refund if needed. Why both? Redis can lose the last few decrements on failover. So preload only 98%, and every 30 s reconcile remaining = quota - sold - active reservations; the last 2% is released near the end.

### 2. Hot keys and counter sharding
A single key caps throughput at one Redis node whatever the cluster size. Each hero deal's quota is split across 32 keys with hash tags on different slots and nodes. Users start at hash(user) mod 32 and probe others when theirs is empty; empty slices are negative-cached locally for 5 s to avoid probe storms. Sold out is declared only when all 32 are empty, and shown as "Sold out, check back", because expiring holds return units.

### 3. The waiting room: admission control
Gate the scarce resource, not the whole site. Only deal checkout is queued. Users arriving in the first 60 s get random scores, so script speed and low latency give no edge; later arrivals are FIFO. An admitter pops batches and adapts with AIMD (additive increase, multiplicative decrease): cut 30% when checkout p99 exceeds 1 s or errors exceed 1%, add 1k/s per second when healthy. Tokens are verified by HMAC locally, with no database call.

### 4. Reservations as a saga
The order state machine RESERVED -> PAYMENT_PENDING -> CONFIRMED or CANCELLED is the saga log. A sweeper reads a ZSET of expiries every second and releases units. Callbacks are deduped on gateway txn id; PENDING over 2 minutes is polled; final state by T+30 minutes. Every step and compensation is idempotent.

**Data model:**
- **DealQuotaShard** (Redis): deal:{id}:stock:{0..31}, preloaded to quota x 0.98 / 32; soldout flags with 5 s TTL.
- **Reservation** (Redis): resv:{id}; user hold deal:{id}:user:{uid} via SET NX, TTL 600 s.
- **Order** (MySQL on Vitess, by user_id): unique reservation_id makes creation idempotent.
- **DealQuotaLedger** (MySQL, one row per deal, hot deals on their own shard): quota, sold, released.
- **PaymentTxn** (MySQL): unique (order_id, attempt); idempotency key, status.

**Key APIs:**
- `POST /v1/deals/{id}/queue`: WAITING with position and jittered pollAfterMs, or ADMITTED with a token.
- `POST /v1/deals/{id}/reserve`: token plus Idempotency-Key; 202, 409 LIMIT_REACHED or 410 SOLD_OUT.
- `POST /v1/checkout`: applies the bank offer against its budget, returns a payment intent.
- `POST /v1/payments/callback/{gateway}`: verify signature and amount, idempotent on txnId.
- `POST /v1/admin/sale/degrade`: level 0-5, audited, live in under 5 s.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Reads:** CDN with 5-10 s TTL and stale-while-revalidate; single-flight per key; TTL jitter of 20%.
- **Cold start:** pre-warm data and runtimes (JIT, pools, TLS, DNS) from T-60 minutes; pre-provision, autoscale only as a safety net.
- **Hot counters:** more slices, plus a lower admission rate.
- **Payments:** add gateways and weight by health per bank and method.
- **Order writes:** more Kafka partitions and consumers, more MySQL shards.

**Failure modes:**
- **Redis shard failover:** reservations fail for 1-2 s and retry on other shards; lost decrements are caught by the DB guard and reconciliation.
- **Gateway success drops from 90% to 40%:** breaker opens, weight shifts, affected holds extended 5 minutes.
- **Kafka consumer lag:** holds already own the units, so correctness holds; scale consumers, extend TTLs, show "confirming".
- **Recommendation latency spike:** bulkhead and 50 ms timeout return a static fallback; checkout unaffected.
- **Order DB shard down:** its writes queue in Kafka and drain after recovery.
- **Bot flood:** WAF, per-device and per-IP limits, proof-of-work, account age over 14 days.

**Degradation ladder:** L1 drop recommendations, reviews and personalised widgets; L2 cut admission 30% and raise listing TTLs to 60 s; L3 drop order history and wishlist sync; L4 healthy gateways only; L5 static deal pages and checkout only. Each level has an owner and trigger; step down one level after 10 minutes stable.

**Trade-offs chosen:**
- **Redis gate plus DB guard over DB alone:** Redis takes the attempt rate; the DB guarantees no oversell.
- **Queue deal checkout only over the whole site:** queueing normal shopping loses GMV.
- **Random for 60 s, then FIFO, over strict FIFO:** removes the bot and latency advantage at the drop.
- **Async orders via Kafka over a sync DB write:** user latency at Redis speed; the hold already guarantees the unit.
- **98% preload over 100%:** a tiny delay for zero oversell.
- **10-minute TTL over 2 minutes or until payment:** enough for UPI and 3DS, short enough to recycle stock.

**What to measure:** admitted/s vs reservation attempts/s vs successes/s per deal; Redis remaining vs DB ledger (alert on drift over 0.5%); oversell (must be 0) and paid-without-order age; reservation-to-payment conversion; payment success per gateway, bank and method; CDN hit ratio and origin QPS; Kafka lag; queue size, wait and abandonment; current degradation level.

## Page 5. Say it in the interview

> "Let me frame this around the first fifteen minutes of a big Indian sale: 50 to 80 million users, a few hundred hero deals with tiny stock, a million page views a second and around 300,000 buy attempts a second at each drop. Correctness means no oversell, and every paid order ships or is refunded. Three ideas. First, shape demand: browse comes from the CDN and caches, and only deal checkout goes through a waiting room that admits users at the rate checkout and payments can absorb. Second, keep the hot path tiny: quota sits in sharded Redis counters, a Lua script checks the per-user limit and reserves a unit for ten minutes, and orders and payments go asynchronously through Kafka, with a conditional database update as the final guard. Third, prepare: pre-warm everything and rehearse a degradation ladder."

**Key points to land:**
- Shape demand first: CDN for reads, waiting room only for deal checkout.
- Bound every arrow to the slowest dependency: the hot key, then payment TPS.
- Atomic Lua reserve on 32 sharded counters, per-user limit inside the script.
- Fast gate in Redis, final guard in the DB: WHERE sold < quota.
- Preload 98% and reconcile every 30 s to survive Redis failover.
- TTL holds plus a saga; a late payment means re-reserve or auto-refund.
- Idempotency keys everywhere; unique reservation_id on orders.
- Pre-warm data and runtimes; single-flight against stampedes.
- A rehearsed degradation ladder; shed recommendations first.
- Multi-gateway routing with breakers; payment partners are the real ceiling.

**Likely follow-ups:**
1. **Why not pre-mint N tokens?** They prevent oversell too, but release and per-user limits are awkward; good for very small quotas like 100 units.
2. **Strict first-come-first-served?** Score by server-side arrival time at the edge, accept that bots matter more, invest more in bot defence.
3. **Stock across warehouses?** Quota is a national pool; FC allocation happens after confirmation, with serviceability checked before reserve so quota is not burned.
4. **Multi-region?** Each deal's counters are single-homed to avoid cross-region consensus; DR holds warm replicas and takes over with a quota handoff.
5. **The one metric in the first 10 minutes?** Successful reservations/s against admitted/s, with payment success; a widening gap means the bottleneck moved.

**Director layer:**
- **Cost drivers:** capacity pre-provisioned for a known step function (private cloud plus burst), CDN egress at 1M req/s, and 4-5 payment gateways.
- **Phasing:** rehearse with game days at 1.5x forecast and chaos tests, then a change freeze a week before the sale.
- **Team ownership:** edge and bot defence, deal inventory and waiting room, orders, payments, and a war room with named owners per ladder level.
- **Top risks:** thundering herd at 00:00, oversell after Redis failover, bank throttling, bots buying out deals, and a non-critical service cascading into checkout.
