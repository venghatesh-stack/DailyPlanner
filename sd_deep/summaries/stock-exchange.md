# Design a stock exchange (order matching engine): the 5-page summary

A stock exchange matches buy and sell orders fairly, in microseconds, without ever losing an acknowledged order. The single most important idea: do NOT distribute the hot path. A sequencer gives every command one order, a single-threaded deterministic matcher per symbol shard applies it, and an append-only journal is the source of truth, so hot standbys replaying the same journal give both durability and fast failover.

## Page 1. The problem, scope and numbers

**Pitch:** a fair, transparent, reliable venue for price discovery. Match orders under strict price-time priority at microsecond latency, keep a regulator-grade audit trail, lose nothing that was acknowledged, and survive hardware failure without halting the market.

**Who uses it:** trading members (low, predictable latency, fair queue position), the regulator (audit, surveillance), clearing (every trade exactly once), data vendors (gap-free feeds), operations (halts, failover).

**In scope:**
- **Orders:** new (limit, market, IOC, FOK), cancel and cancel-replace, with validation and member auth.
- **Pre-trade risk:** price band (e.g. +/- 10% of reference), max quantity and notional, credit limit, self-trade prevention.
- **Matching:** price-time priority; trades print at the resting order's price; partial fills.
- **Outputs:** execution reports; sequenced level-2/level-3 market data with snapshots; trades to clearing.
- **Market controls:** opening and closing auctions, halts, circuit breakers, member kill switch.

**Out of scope:** clearing and settlement, broker OMS and retail UI, derivatives margining, cross-venue routing.

**Non-functional targets:**
- **Latency:** order-to-ack p99 under 100 microseconds (p99.9 under 250); matcher under 10 microseconds per order; market data under 20 microseconds after a match.
- **Throughput:** 500k orders/s exchange-wide, 50k/s on the hottest symbol, 3x headroom.
- **Durability:** RPO 0 for acknowledged commands (journaled to 2 of 3 replicas before ack).
- **Availability:** 99.99% in trading hours; RTO under 1 s per matcher shard.
- **Consistency, fairness, audit:** total order per symbol; bit-identical replay; one sequencing point; all events kept 7 years.

**Capacity math (1B order messages over a 6.25 h session = 22,500 s):**
- **Rate:** 1e9 / 22,500 = 44k/s; peak 10x = 450k, plan for 500k/s. Hottest symbol about 50k/s against 1M+ ops/s per core. So one thread per symbol is plenty.
- **Journal:** 1e9 x 128 B = 128 GB/day; 384 GB with 3 replicas; about 224 TB over 7 years. Peak write is 500k x 128 B = 64 MB/s. So a sequential append log is trivial for NVMe.
- **Market data:** 2 messages per order event = 1M msg/s x 40 B = 320 Mbps. So multicast, cost independent of subscriber count.
- **Book memory:** 10M resting orders x 100 B = 1 GB. So the whole book lives in RAM, hot symbols in L3 cache.
- **Trades:** 20:1 order-to-trade = 50M trades x 200 B = 10 GB/day. Throughput is modest; the hard part is tail latency and determinism.

## Page 2. The architecture

```
 Members (FIX / binary, in colo)
      |                       ^ exec reports
      v                       |
 Order Gateways --> Pre-trade Risk (in memory)
                         |
                         v
                 Sequencer + Journal --replicate--> Standby journal
                         | ring buffer              + hot standby
                         v                            (replays same seq)
           Matching engine shards (1 thread per symbol group)
           [INFY book] [TCS book] ...
                         v output events
                     Publisher --> Market data (UDP multicast A/B)
                         |    --> Snapshot / retransmit server
                         v
         Trade capture -> Clearing feed, Audit store, Reporting DB
```

- **Order gateway:** sessions, auth, parsing, throttles, cancel-on-disconnect, exec reports back.
- **Pre-trade risk:** price bands, fat-finger caps, credit limits; in memory, no DB calls.
- **Sequencer:** assigns the monotonic sequence number and replicates before releasing.
- **Journal:** append-only log of every command and output; basis of recovery and audit.
- **Matching engine shard:** single-threaded loop owning the books for a set of symbols.
- **Hot standby:** replays the same stream in lockstep; promoted with no rebuild.
- **Publisher:** sequenced multicast on redundant A/B lines, snapshots, retransmits.
- **Trade capture:** deterministic trade IDs; clearing feed exactly once.
- **Control plane:** trading phases, halts, kill switches, failover with an external arbiter.

**Flow A: a limit order that partially fills**
1. Member sends BUY 300 INFY @ 1500.00; gateway validates and throttles.
2. Risk checks the band (reference 1495, within 10%) and reserves 4.5 lakh notional.
3. Sequencer assigns seq 4,812,005, journals, waits for the standby's ack, puts it on the ring buffer.
4. Matcher fills 200 @ 1499.50 and 100 @ 1500.00, at the makers' prices.
5. Acks and fills go to taker and makers, deltas to market data, trades to clearing.

**Flow B: matcher failover**
1. Primary misses 3 heartbeats of 100 ms; the arbiter bumps the epoch and promotes the standby.
2. Output tagged with the old epoch is dropped; the new primary continues from the next sequence; the publisher dedups by sequence.

## Page 3. The core deep dives

### 1. Single-threaded matching and the order book
Each book has bid and ask sides as price levels. Each level is a FIFO doubly linked list with total quantity; best-bid and best-ask pointers give the top instantly; an orderId hash map gives O(1) cancel. Because price bands bound the range, levels sit in an array indexed by tick offset (tree fallback). Prices are integer ticks, never floats: a 0.05 rupee tick means price x 20. Orders are pre-allocated in an object pool, so no garbage collection pauses. To match, walk the opposite side from the best price while the order crosses, oldest order first at each level; any remainder rests at the tail of its level. One thread owns the book, so no locks. A cancel racing a fill is resolved purely by sequence: if Shreya's aggressive buy is sequenced before Sethu's cancel, Sethu gets "too late to cancel".

### 2. Sequencer, journal and RPO 0
Ordering is the product: one sequencer per symbol group defines time priority. A command is acknowledged only after it is journaled and replicated to another node's memory or NVMe. In the colo that costs single-digit microseconds, far less than a local fsync. Every database downstream (trades, audit, reporting) is a projection of the journal, fed asynchronously, so a slow clearing feed never slows matching.

### 3. Determinism gives HA, recovery and testing
The engine's state is a pure function of the command sequence. So a hot standby that applies the same stream is always ready; a restart loads a snapshot (every N million records or 1 minute) plus the journal tail; and a new build is tested by replaying production journals and diffing every output. Trade IDs come from (seq, match index), so a replay after a mid-match crash emits the same fills with the same IDs and the publisher dedups them.

### 4. Market data and fairness
Packets carry sequence numbers on identical A and B multicast lines. A subscriber that sees seq 1001 after 998 checks line B, then asks the TCP retransmit server for 999-1000, then falls back to a snapshot tagged with its sequence plus incrementals. Multicast and equal-length colo cables mean no member sees data early.

**Data model:**
- **Order** (matcher RAM): orderId, memberId, side, price in ticks, qtyOpen, qtyFilled, seq, list pointers.
- **Journal record** (NVMe, replicated): seq per shard (dense), epoch, ts_ns, type, binary payload, crc32.
- **Trade:** PK tradeId, unique (shard, seq, matchIndex); partitioned by trade date and symbol.
- **Member risk state** (RAM, snapshotted): credit limit, used notional, open orders, kill switch.
- **Audit event** (columnar store): partition by date, sort by (symbol, seq); 7 years.

**Key APIs:**
- `NewOrderSingle (FIX 35=D)`: ClOrdID unique per session per day; a duplicate is rejected, not re-applied.
- `OrderCancelRequest (35=F)`: whichever of cancel or fill is sequenced first wins.
- `OrderCancelReplaceRequest (35=G)`: price change or quantity increase loses time priority.
- `MarketDataIncremental (UDP multicast)`: seq plus add, modify, delete, trade, status.
- `POST /control/symbols/{sym}/halt`: the halt is itself a sequenced command, so all replicas agree.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Matching:** add shards; spread symbols over more cores and hosts. One thread already handles 20x the hottest symbol's peak.
- **Hot symbol on news (20x normal):** pin it to its own core; the ring buffer absorbs bursts; gateways apply backpressure.
- **Sequencing and market data:** partition sequencers and multicast channels by symbol group.
- **Runaway algorithms:** per-session throttles (e.g. 2,000 msg/s), message-to-trade limits, max open orders, kill switch.

**Failure modes:**
- **Primary matcher dies:** standby promoted in under 1 s via quorum and epoch bump; journaled but unmatched orders are replayed.
- **Sequencer leader dies:** a new leader is elected from replicas holding all committed entries; gateways retry unacked commands, deduped by ClOrdID.
- **Gateway dies:** members reconnect to a backup; cancel-on-disconnect fires per member preference.
- **Split brain:** epoch fencing through an external arbiter; outputs with a stale epoch are rejected.
- **Clearing feed slow:** matching continues; the journal is the buffer; consumers catch up from offsets.
- **Bug produces wrong fills:** halt the symbol, replay on a fixed build, bust or adjust trades per exchange rules.
- **Whole data centre lost:** DR site with an async journal a few ms behind; market halted, members reconcile. RPO of a few ms is accepted for DR.

**Trade-offs chosen:**
- **Single-threaded per shard over locks:** deterministic, lock-free, faster, and enables replay.
- **Synchronous replication over async journal or local fsync:** RPO 0 for microseconds.
- **Hot standby over cold or warm restart:** failover under 1 s; double hardware is cheap for an exchange.
- **Multicast A/B over TCP per subscriber:** simultaneous delivery, constant cost.
- **Fixed-point ticks over doubles:** exact, comparable, allocation free.
- **Risk before sequencing over inside the matcher:** keeps the matcher minimal; risk spans symbols.

**What to measure:** order-to-ack and tick-to-trade latency at p50, p99, p99.9 and max per gateway and shard; replication lag; ring buffer occupancy; primary versus standby output hash divergence (must be zero); rejects by reason; market data gaps and retransmits; message rate per member and kill switch activations; downstream lag.

## Page 5. Say it in the interview

> "Assume 1 billion order messages a day, 500k a second at peak, with acknowledgements under 100 microseconds and zero loss of anything acknowledged. Throughput is modest; tail latency and fairness are the hard part. So I will not distribute the hot path. Gateways validate and throttle, an in-memory risk stage checks bands and credit, and a sequencer stamps each command with one sequence number and replicates it to a standby before the ack. Each symbol group has a single-threaded matcher over an in-memory book: price levels with FIFO queues, integer ticks, price-time priority. Because it is deterministic, the journal is the truth: a hot standby replays it for sub-second failover, restarts use snapshot plus tail, and releases are tested by replaying production. Market data goes out on sequenced A/B multicast."

**Key points to land:**
- Ordering is the product: one sequencer per symbol group defines fairness.
- Shard by symbol; never parallelise inside a book.
- The journal is the source of truth; everything else is a projection.
- Determinism gives HA, recovery and testing from one mechanism.
- Ack only after replication to a second node: RPO 0 at microsecond cost.
- Book: FIFO price levels, best pointers, orderId map, integer ticks.
- Market data on A/B multicast with sequence numbers, retransmit and snapshots.
- Risk before sequencing; price bands, kill switches and circuit breakers.
- Epoch fencing prevents split brain.
- Measure p99.9 and max, not averages.

**Likely follow-ups:**
1. **Why not a database with row locks?** A DB round trip is milliseconds and locks add nondeterminism; the book fits in memory and durability comes from the journal.
2. **How is no acked order lost?** We ack only after journaling and replication; any recovery replays the journal, so every acked command is applied.
3. **How do you scale 10x?** More shards and cores, sequencing and market data partitioned by symbol group; one thread has 20x headroom on the hottest symbol.
4. **Stop orders?** A trigger book per symbol keyed by stop price; after each trade, crossed stops are injected as new sequenced orders in a deterministic order.
5. **How do you test the matcher?** Unit and property tests (no crossed book, quantities conserved) plus replaying production journals through the new build and diffing every output.

**Director layer:**
- **Cost drivers:** double hardware for hot standbys, colo network and equal-length cabling, 7 years of audit storage (about 224 TB primary journal).
- **Team ownership:** matching engine core, gateways and risk, market data, post-trade (trade capture, clearing, surveillance), and exchange operations for control plane and runbooks.
- **Release discipline:** changes only outside market hours, gated by shadow replay of production journals.
- **Top risks:** runaway algorithms (Knight Capital lost about 440M USD in 45 minutes), matcher bugs giving wrong fills, split brain, flash crashes, and fairness complaints.
