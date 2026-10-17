# Design graceful degradation when a dependency fails: the 5-page summary

Graceful degradation keeps a product page and checkout working when one of its 12 dependencies fails, by deciding in advance what is essential, what can be stale and what can disappear. The single most important idea: fallbacks must be static (precomputed, local, always exercised), because a clever emergency path that calls another service is just a new outage.

## Page 1. The problem, scope and numbers

**Pitch:** a product page fans out to about 12 services. Last quarter a recommendations outage took the whole page down for 9 minutes, because the page waited synchronously with a 5 s timeout and turned the error into a 500. Make non-essential failures invisible and essential ones fail safely.

**Who uses it:** shoppers, on-call SRE (see and switch off degraded features), feature PMs (own their widget's degraded mode), finance (no mispriced orders).

**In scope:**
- **Dependency registry:** tier (T0 critical, T1 important, T2 optional), timeout, degraded mode, staleness limit, owner.
- **Page assembly (BFF, Backend-for-Frontend):** parallel fan-out, per-call deadlines, circuit breakers, per-widget fallbacks.
- **Serve-stale caching**, local precomputed fallbacks, kill switches and brownout levels.
- **Async order path:** accept orders into a durable queue when fulfillment is down.
- **Checkout guard:** re-price and re-check stock at the source of truth, or block.

**Out of scope:** multi-region failover, search rebuilds, seller and back-office tools, payment routing.

**Non-functional targets:**
- **Latency:** product page p99 under 600 ms, healthy and degraded alike.
- **Availability:** T0 flows 99.95% monthly; checkout at least 99.9% with any single T1/T2 dependency down.
- **Reaction:** automatic degrade within 10 s; manual kill switch within 30 s; flags reach 99% of instances in 10 s.
- **Staleness:** display price at most 5 min, stock band 2 min, catalog content 24 h.
- **Correctness:** zero orders charged at a price not validated in the last 60 s.

**Capacity math (sale peak: 50k page RPS, 1.5k orders/s):**
- **Fan-out:** 50k x 12 = 600k backend calls/s; dropping the 8 T2 calls saves 400k/s, two thirds of load. So shedding optional work is the cheapest capacity in a crisis.
- **Hot cache:** 2M hot SKUs x 8 KB = 16 GB. Too big per pod, so a shared Redis tier plus a per-pod LRU of the top 50k SKUs (400 MB).
- **Full snapshot:** 150M SKUs x 8 KB = 1.2 TB in object storage and CDN. So pages survive a catalog database outage.
- **Bestseller lists:** 20k categories x 50 items x 100 B = 100 MB, so ship them to every pod hourly.
- **Order backlog:** 1.5k/s x 1,800 s = 2.7M messages x 4 KB = about 11 GB for a 30-minute fulfillment outage. Easy for one Kafka topic.
- **Latency budget:** 50 ms edge + 400 ms parallel fan-out (T0 300 ms, T2 cut at 100 ms) + 150 ms render = 600 ms.

## Page 2. The architecture

```
 Mobile/Web -> CDN (stale-if-error snapshots) -> API gateway (priority shed)
                                                      |
                                                      v
 Flag / kill-switch svc --cache--> Page assembly (BFF)
 Load monitor (brownout level) --> registry, timeouts, breakers, bulkheads,
                                   local fallbacks (bestsellers, LRU)
             T0/T1  |        |       |        |        |       | T2
                 Catalog  Pricing  Cart    Stock    Recos   Reviews
                    |                |
          Redis (serve stale)        v
                                Checkout guard -> Payment
                                     | fulfillment down
                                     v
                         Kafka orders topic -> Fulfillment workers
```

- **Dependency registry:** tier, timeout, degraded mode and owner per dependency; reviewed like code.
- **BFF:** parallel fan-out, per-widget deadlines, degraded markers, applies brownout level.
- **Resilience layer:** timeouts, circuit breakers, bulkheads; triggers the fallback on failure.
- **Fallback store:** precomputed bestsellers, banners, generic delivery text on every pod.
- **Serve-stale cache:** Redis and CDN with soft and hard TTLs.
- **Flag service:** kill switches with criticality levels, cached locally, audited, with TTL.
- **Brownout controller:** watches CPU and queueing delay; raises level with hysteresis.
- **Gateway shedder:** checkout > cart > product page > browse > prefetch and bots.
- **Async order pipeline:** outbox to Kafka, idempotent fulfillment workers.

**Flow A: product page with recommendations down**
1. BFF reads brownout level and flags from local cache, fans out in parallel.
2. Recos breaker is OPEN, so the call short-circuits in under 1 ms.
3. The local bestseller list fills the slot, titled "Popular in this category".
4. Response carries degraded=["recos"]; a metric counts it; no user error.

**Flow B: order while fulfillment is down**
1. Payment authorised; order written as ACCEPTED with an outbox event.
2. Shopper sees "Order placed, confirmation details shortly".
3. Workers consume by order_id on recovery; status CONFIRMED, user notified.
4. Not processable in 24 h: auto-cancel, refund and apology credit.

## Page 3. The core deep dives

### 1. Criticality tiers and deadline-bounded fan-out
Every call starts together. The page waits for T0 up to 300 ms and for T2 widgets only up to 100 ms; anything late gets its fallback. Example: reviews p99 jumps from 50 ms to 4 s. The 100 ms deadline drops it, a slow-call breaker opens, and the page never waits past its own budget. The lesson from the 9-minute outage: a soft dependency with a long synchronous timeout is really a hard one. Each dependency declares one mode: stale, default, hide, defer, or block safely.

### 2. Static stability: fallbacks that need nothing at failure time
Batch jobs build bestseller lists and product snapshots hourly and ship them to pods and the CDN. Flags and the registry are cached and saved to disk for cold starts. The fallback never makes a network call to a system that shares fate with the primary. If the fallback job itself fails for 6 hours, pods keep the last good file and alert when it is older than 3 h.

### 3. Serve-stale caching and the money red line
Product snapshots have a soft TTL of 60 s (refresh in the background, still serve) and a hard TTL of 24 h (serve while the origin errors). Single-flight refresh, one loader per key, plus jittered TTLs prevent a stampede when the catalog recovers. Stale is for display only. A display price older than 5 min shows "price may change". At checkout the guard re-prices against Pricing; if Pricing is down, checkout says "try again shortly" rather than guess.

### 4. Brownout levels with hysteresis
Level 1 stops all T2 calls (two thirds of backend load). Level 2 drops T1 enrichments such as personalised delivery estimates. Level 3 serves a static, cacheable product page with a buy button. The controller raises a level after 30 s of hot signals (CPU over 85%, queueing delay p99 over 20 ms) and lowers one step only after 5 minutes healthy, so it does not flap.

**Data model:**
- **DependencyPolicy** (Git-backed config): PK dependency; tier, timeout_ms, degraded_mode, staleness_limit_s, owner.
- **ProductSnapshot** (Redis + object store): key pdp:{sku}, hash-slot sharded; display_price, price_as_of, stock_band.
- **FallbackList** (pod memory): category_id -> 50 SKUs, generated_at.
- **Flag** (Postgres + client cache): PK name, global version, TTL, changed_by, reason.
- **OrderEvent** (outbox + Kafka): key order_id, 64 partitions; consumers idempotent on order_id.

**Key APIs:**
- `GET /v1/pdp/{sku}`: never 500 on a T2 failure; mandatory degraded list and price as_of.
- `POST /v1/checkout`: idempotency key; re-prices at the source; 409/503 with retry hint.
- `PUT /v1/killswitch/{feature}`: RBAC, audited, auto-expires via ttl_minutes.
- `PUT /v1/brownout`: manual override, level 0-3 with TTL and reason.
- `GET /v1/degradation/status`: degraded % per feature, breaker states, brownout level.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x (sale peaks are 10x normal):**
- **Backend fan-out:** brownout drops T2 calls first; the gateway sheds bots and prefetch before browse, never checkout until last.
- **Hot keys:** when personalisation fails, everyone sees the same lists; pre-warm, replicate hot keys across Redis shards, rotate several lists.
- **Recovery stampede:** single-flight, jittered TTLs, background revalidation.
- **Crawlers:** served cached snapshots.

**Failure modes:**
- **Recommendations down:** breaker opens, local bestsellers fill in; no latency or checkout impact.
- **Catalog DB down:** Redis and CDN serve snapshots up to 24 h; cold SKUs from object storage; editing paused.
- **Pricing down:** stale display prices with a note; checkout blocked; T0 incident.
- **One pricing shard down:** only its SKUs show "price unavailable"; the rest sells.
- **Fulfillment down:** orders accepted and queued; backlog drains on recovery.
- **Flag service down:** cached flags; the local controller still browns out from local signals.
- **Dependency returns 200 with wrong data (price 0):** validation (price over 0, within 50% of last known) treats it as failure.
- **Kill switch forgotten:** TTL expiry with notification; dashboard of active switches.

**Trade-offs chosen:**
- **Precomputed, local fallbacks over on-demand ones:** no new dependency at failure time, and 100 MB is cheap.
- **Stale display price, validated at checkout, over blocking the page:** browsing lives; correctness is enforced where money moves.
- **Cached reviews (up to 24 h) over hiding them:** reviews change slowly and drive conversion.
- **Automatic brownout with manual override over either alone:** machines react in seconds, humans fix false positives.
- **Accept and queue orders over rejecting checkout:** keeps revenue; rare cancellations are compensated.
- **Explicit degraded markers over silent degradation:** clients render properly and degraded responses are counted.

**What to measure:** degraded response ratio per feature, T0 flow availability separate from the page SLO, conversion in degraded vs normal mode, age of fallback data served, breaker states, brownout level and shed rate by class, active kill switches and their age, order queue oldest-message age, checkout price-revalidation mismatches.

## Page 5. Say it in the interview

> "I would start by separating what the user must be able to do from what makes the page nicer. At 50k page requests a second with a dozen dependencies, only catalog, cart, price and payment are truly critical; reviews, recommendations and ads are optional. So step one is a criticality map with a declared degraded mode for each: stale, default, hidden or deferred. The page assembly layer fans out in parallel with tight deadlines and circuit breakers, so optional widgets drop out instead of slowing the page. Fallbacks are static, precomputed bestseller lists and snapshots held locally, because a fallback that calls another service is just a new failure. Kill switches and brownout levels shed whole tiers under overload, and orders go into a durable queue when fulfillment is down. The red line: never charge a stale price, and we test the degraded paths continuously."

**Key points to land:**
- Degradation is a product decision first: every dependency gets a tier, a mode and an owner.
- Keep hard dependencies few; give soft ones short budgets (100 ms).
- Static stability: precomputed, local fallbacks that need nothing at failure time.
- Serve stale with soft and hard TTLs; re-validate when money moves.
- Brownout: fast up (30 s), slow down (5 min).
- Shed by priority at the edge so checkout survives.
- Turn synchronous writes into queued work, with idempotent consumers.
- Untested fallbacks are liabilities: exercise them always, measure conversion.
- Be honest in the API: mark degraded fields and their freshness.

**Likely follow-ups:**
1. **How do you know the degraded mode works?** A canary cell always runs with one T2 dependency off on rotation, weekly game days disable T1, and we compare conversion to control.
2. **Isn't a stale price a legal risk?** Display staleness is bounded and labelled; the charged price is re-validated and shown before payment, or checkout blocks.
3. **What if a dependency returns wrong data, not errors?** Validate schema and ranges against last known and treat implausible data as failure; add anomaly detection on business metrics.
4. **How do you stop new hard dependencies?** The client library requires a registry entry, design reviews check tiers, and CI chaos tests disable new dependencies.
5. **Isn't this just circuit breakers?** Breakers detect and short-circuit; degradation is the policy of what happens next: fallbacks, brownout, async paths and UX.

**Director layer:**
- **Cost drivers:** a 3-replica Redis tier, about 1.2 TB of snapshots in object storage and CDN, hourly batch jobs, and the conversion lost while degraded.
- **Phasing:** dependency map and T2 timeouts first (biggest win, lowest risk), then serve-stale caching, kill switches, automatic brownout, the async order path; a game day after each.
- **Team ownership:** each feature team owns its degraded mode; a platform team owns the BFF, registry and flags; SRE owns brownout and game days.
- **Top risks:** broken untested fallbacks, fallbacks that cascade, stale data causing business harm, and misuse or outage of the flag service.
