# Flash sale system (Big Billion Days style sale event): recall card

> **Hook:** Serve reads from the CDN → Queue deal checkout only → Reserve atomically in Redis → Kafka order intent → DB guard: sold < quota

**P · Problem:** It's really a demand-shaping and hot-counter problem: sell scarce stock fairly to a stampede without overselling.

**N · Numbers:**
1. 1M page views/s at 95% CDN hit leaves about 50k/s at origin, so reads live at the edge and in pre-warmed caches.
2. About 330k buy attempts/s, so a waiting room admits only about 25k/s.
3. 10k payment initiations/s but 2-3k TPS per gateway, so route across 4-5 gateways: payments are the real ceiling.

**H · Hard part:** Zero oversell on a few hot SKUs at hundreds of thousands of attempts a second.

**B · Boxes:** `CDN and WAF → API gateway → Waiting room → Deal inventory (Redis Lua) → Kafka → Order service (MySQL)`

Side path: `Order service → Payment orchestrator → 4-5 gateways` with health-weighted routing.

**D · Decisions:**
1. Redis gate plus DB guard over the DB alone, because Redis takes the attempt rate and the DB guarantees no oversell.
2. Queue deal checkout only over the whole site, because queueing normal shopping loses GMV.
3. 98% preload over 100%, because a tiny delay buys zero oversell after a Redis failover.

**F · Failures:**
1. Redis shard failover → reservations retry on other shards; lost decrements are caught by the DB guard and 30 s reconciliation.
2. Gateway success drops from 90% to 40% → breaker opens, weight shifts, affected holds extended 5 minutes.

**C · Close:** "So I shape demand first: browse comes from the CDN, and only deal checkout goes through a waiting room that admits users at the rate payments can absorb. The hot path is tiny: quota sits in 32 sharded Redis counters, a Lua script checks the per-user limit and reserves a unit for ten minutes, and orders go through Kafka with a conditional database update as the final guard. I pre-warm everything and rehearse a degradation ladder."

**Quiz yourself:**
1. Why 32 counter shards per deal? → A single key caps throughput at one Redis node.
2. Why random order for the first 60 s? → It removes the bot and latency advantage at the drop.
3. What if UPI succeeds after the hold expired? → Re-reserve if quota remains, else auto-refund.
