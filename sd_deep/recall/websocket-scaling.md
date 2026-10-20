# WebSocket scaling (live updates): recall card

> **Hook:** Thin gateway holds sockets → Route by user or topic → Subscribe once per gateway → Fan out locally → Resume by seq

**P · Problem:** It's really a stateful fan-out problem where every connection is pinned to one server.

**N · Numbers:**
1. 10M connections at 150k per node is about 100 nodes over 3 AZs, so size the fleet by memory, not CPU.
2. 1M watchers x 4 updates/s = 4M frames/s, so conflate and serialise once per gateway.
3. One dead 150k node with 0-30 s jitter is about 5k connects/s, so jitter and local auth are mandatory.

**H · Hard part:** Reconnect storms and slow consumers, not steady-state throughput.

**B · Boxes:** `Publishing service → Publish API → Kafka / NATS → Gateway → Client`

Side path: `Gateway → Presence registry (Redis)` for user-to-gateway routing.

**D · Decisions:**
1. Kafka plus NATS over one backbone, because reliable streams need replay and counters need low latency.
2. 150k per node over 500k+, because a denser node's crash means a bigger storm.
3. Disconnect-and-resync over dropping or unbounded buffering, because dropping breaks order and buffering risks OOM.

**F · Failures:**
1. Gateway crashes → 150k clients reconnect with jitter elsewhere and resume from last_seq.
2. NATS node fails → in-flight latest values are lost; the next conflated update within 250 ms restores state.

**C · Close:** "WebSockets are stateful, so a thin gateway tier only holds sockets and talks to business services through a pub/sub backbone. Broadcast topics are subscribed once per gateway and fanned out locally, so cost scales with nodes, not connections. Reliable per-user streams go through Kafka with sequence numbers, so a reconnecting client resumes or resyncs from a snapshot. Then I defend it with conflation, bounded queues, and jittered reconnects with graceful draining."

**Quiz yourself:**
1. What does a slow phone get on a stock topic? → Only the newest value; its slot is overwritten.
2. What if a client's gap is beyond the replay cache? → It calls /v1/sync for a snapshot, then continues live.
3. Why a 25 s heartbeat? → It must be below every idle timeout, like the LB's 350 s.
