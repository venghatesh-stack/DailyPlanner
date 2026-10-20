# Swiggy / DoorDash-style food delivery ordering: recall card

> **Hook:** Signed quote → Idempotent order → Saga: pay, restaurant accepts → Zone micro-batch dispatch → Live tracking → Capture on delivery

**P · Problem:** It's really a three-sided real-time marketplace where money and assignment must be exact but the heavy load is location and dispatch.

**N · Numbers:**
1. About 170 orders/s at dinner peak, 1.4k state writes/s, so sharded Postgres is enough and we spend it on correctness.
2. 300k riders pinging every 4 s is 75k updates/s, so keep only the latest position in Redis and send history to Kafka.
3. About 300k live orders pushed every 4-5 s is 70k WebSocket messages/s, so tracking gets a dedicated push gateway.

**H · Hard part:** Never double-charging or double-assigning across long, failure-prone waits, while matching riders to orders every few seconds per zone.

**B · Boxes:** `Customer app → API gateway → Order service (state machine, saga) → Payment service → Kafka → Dispatch`

Side path: `Rider app → Location ingest → Redis (latest position per H3 cell)` feeds dispatch and tracking.

**D · Decisions:**
1. Orchestrated saga over choreography, because long timers and many compensation branches need one owner.
2. Micro-batch dispatch over greedy nearest rider, because it cuts total travel and enables batching.
3. Redis plus Kafka over PostGIS for locations, because 75k/s of ephemeral data only needs the latest value.

**F · Failures:**
1. Primary PSP degraded → route to a secondary PSP; resolve pending payments by webhook and polling.
2. Dispatch worker crashes → its zone lease expires in 10 s and another worker rebuilds from Redis; at most one batch is late.

**C · Close:** "So this is a three-sided marketplace. The order is a versioned state machine in sharded Postgres with an outbox, and placement is an orchestrated saga: authorise, wait for the restaurant, dispatch, capture on delivery, with void or refund as compensation. The real load is 75 thousand location pings a second and per-zone dispatch, so I partition by city, keep latest positions in Redis, and widen ETAs before failing orders."

**Quiz yourself:**
1. PSP call times out, do you retry? → No, query status with the same key first, retry only if not found.
2. Two workers assign the same order? → One owner per zone by lease, plus a CAS on order and rider versions.
3. When is the rider dispatched? → Timed to food-ready, not to order acceptance.
