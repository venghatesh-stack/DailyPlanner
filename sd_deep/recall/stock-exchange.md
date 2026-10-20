# Stock exchange (order matching engine): recall card

> **Hook:** Gateway → Risk → Sequence → Journal → Match → Multicast

**P · Problem:** It's really a total-ordering problem: one fair sequence per symbol, applied deterministically, with zero loss of acknowledged orders.

**N · Numbers:**
1. 500k orders/s at peak, hottest symbol 50k/s against 1M+ ops/s per core, so one thread per symbol group is plenty.
2. 128 GB/day of journal at 64 MB/s peak, so a sequential append log is trivial for NVMe.
3. 10M resting orders x 100 B = 1 GB, so the whole book lives in RAM.

**H · Hard part:** Tail latency under 100 microseconds and strict fairness, while never losing an acked order and failing over in under a second.

**B · Boxes:** `Order gateway → Pre-trade risk → Sequencer + journal → Matching shard → Publisher`

Side path: `Journal → Trade capture → Clearing and audit` as async projections.

**D · Decisions:**
1. Single-threaded matcher per shard over locks, because it is deterministic, lock-free and replayable.
2. Synchronous replication before ack over local fsync, because it gives RPO 0 for microseconds.
3. Multicast A/B over TCP per subscriber, because everyone gets data at the same time at constant cost.

**F · Failures:**
1. Primary matcher dies → arbiter bumps the epoch and promotes the hot standby in under 1 s.
2. Clearing feed is slow → matching carries on; the journal buffers and consumers catch up from offsets.

**C · Close:** "So I don't distribute the hot path. Gateways validate, an in-memory risk stage checks bands and credit, and a sequencer stamps every command and replicates it before the ack. Each symbol group has a single-threaded matcher over an in-memory book with price-time priority and integer ticks. Because it is deterministic, the journal is the truth: a hot standby replays it for fast failover, and new builds are tested by replaying production. Market data goes out on sequenced A/B multicast."

**Quiz yourself:**
1. Why not a database with row locks? → Milliseconds per round trip, and locks add nondeterminism.
2. Who wins when a cancel races a fill? → Whichever the sequencer ordered first.
3. How does a replay avoid duplicate trades? → Trade IDs come from (seq, match index), and the publisher dedups.
