# Design WebSocket scaling (live updates): the 5-page summary

A shared realtime platform pushing live updates (orders, rider location, sale stock, chat) to 10 million connected clients over WebSockets. The key idea: a WebSocket pins state to one server, so isolate it in a thin gateway tier, route by user or topic through a pub/sub backbone, and treat reconnect storms and slow consumers as the real risks.

## Page 1. The problem, scope and numbers

**Pitch:** replace 5-30 second polling (stale, battery-hungry, millions of no-change API calls a minute during sales) with one realtime delivery fabric any product team can publish to, that survives sale-day peaks and degrades safely.

**Who uses it:** buyers, sale shoppers, sellers in chat, publishing service engineers, SRE and security.

**In scope:**
- **Authenticated connection:** short-lived JWT at upgrade, refreshed in band.
- **Topics:** subscribe and unsubscribe, authorised per topic pattern (order:{id} only if you own it).
- **Publish API:** to a user or a topic, as reliable or latest-value.
- **Resume:** per-topic sequence numbers, replay from last acked seq, REST catch-up for big gaps.
- **Heartbeats, presence, fallback:** ping/pong, online status, SSE or long polling behind bad proxies.

**Out of scope:** offline push (FCM/APNs), end-to-end chat encryption, client-to-client messaging, voice and video.

**Non-functional targets:**
- **Latency:** publish-to-client p50 under 100 ms, p99 under 500 ms in region.
- **Availability:** 99.95% connection availability; a node or AZ loss recovered within 30 s.
- **Delivery:** reliable topics at-least-once, in order per topic; latest-value topics conflated (only the newest value kept).
- **Bounds and throughput:** under 40 KB and 256 queued messages per connection; 50k publishes/s in, 5M frames/s out.

**Capacity math (10M peak connections, 3M typical, 300-byte frames):**
- **Gateways:** 10M / 150k per node = 67 nodes; with 30% headroom and N+1 per AZ, about 100 nodes over 3 AZs. So size the fleet by memory, not CPU.
- **Memory:** 10M x 40 KB = 400 GB, about 4 GB per node. Kernel TCP buffers dominate, so tune them down.
- **Heartbeats:** 10M / 25 s = 400k pings/s. So use WebSocket ping frames, not app messages.
- **Rider location:** 2M deliveries / 5 s = 400k publishes/s, 1-2 watchers each, about 600k frames/s. So per-user streams need a partitioned backbone.
- **Hot topic:** 1M watchers x 4 updates/s = 4M frames/s; over 100 gateways, 40k frames/s per node. So conflate and serialise once.
- **Bandwidth:** 5M frames/s x 300 B = 1.5 GB/s, about 12 Gbps, about 120 Mbps per node.
- **Reconnect storm:** one 150k node dies; with 0-30 s jitter that is about 5k connects/s, each a 1-2 ms TLS handshake. Without jitter, 150k in one second. So jitter and local auth are mandatory.

## Page 2. The architecture

```
 Mobile / Web clients
      | wss:// (TLS)
 GeoDNS -> L4 load balancer (NLB, least-connections, 350 s idle)
      |
 Gateway fleet (about 100 nodes x 150k conns): auth, heartbeats,
   local index topic -> conns, user -> conns, bounded send queues
      ^                     |                        ^
      | node-level sub      | user -> gw, TTL 60 s   | consume partitions
      |                     v                        |
 NATS / sharded Redis    Presence registry     Kafka user-events
 (ephemeral, by topic)   (Redis Cluster)       (256 parts, 24 h)
      ^                                              ^
      | latest-value broadcast        reliable, seq  |
      +---------- Publish API / Fan-out service -----+
                   ^           ^             ^
              Inventory    Order svc    Logistics      Sync REST API
```

- **L4 load balancer:** spreads new TCP connections by least-connections; drops draining nodes.
- **WebSocket gateway:** TLS, auth, subscriptions, heartbeats, bounded queues, local fan-out. Nothing else.
- **Presence registry:** user_id -> gateway and conn_ids, TTL 60 s refreshed by heartbeats.
- **Publish API / fan-out:** quotas, schema, seq numbers, conflation, routes to Kafka or NATS.
- **Kafka:** reliable per-user streams keyed by user id, 24 h retention for resume.
- **NATS (or sharded Redis):** sub-10 ms broadcast to interested gateways, no storage.
- **Sync API:** current snapshot or missed events since a seq.
- **Auth service:** issues 15-minute JWTs; gateways verify locally with public keys.
- **Control plane:** fleet membership, draining, per-node limits, conflation interval flags.

Business services publish only through the Publish API; they never talk to gateways.

**Flow A: reliable per-user update (order status)**
1. Order service publishes to user u1, topic order:9123.
2. Publish API does INCR seq:order:9123 -> 42, writes to Kafka partition hash(u1) % 256.
3. The gateway holding u1 queues the frame; client applies seq 42 and acks.
4. On a gap (44 after 42) the client asks to resume from 43; offline users get FCM.

**Flow B: hot broadcast (flash-sale stock)**
1. Inventory emits stock for p1 every few milliseconds.
2. Fan-out keeps only the latest value and flushes every 250 ms to topic product:p1.
3. About 100 gateways receive it once each, serialise once, write to about 10k local queues.
4. Full queues keep only the newest value per topic; clients render it with no ack.

## Page 3. The core deep dives

### 1. Two-level fan-out with node-level subscriptions
A gateway subscribes to a topic once, with a reference count: the first local subscriber triggers the backbone subscribe; the last one leaving unsubscribes after 30 s (so flapping users do not churn the broker). A 1M-watcher product on 100 gateways costs the broker 100 sends, not 1M; each gateway encodes once and writes the same bytes to about 10k sockets. Conflation (500 stock changes/s become 4) keeps that affordable.

### 2. Delivery classes, sequence numbers and resume
Reliable topics (order status, chat) get a per-topic seq at publish, kept in Kafka for 24 h and a replay cache (last 100 events or 1 h). Example: Shreya's phone has applied seq 41 on order:9123, loses signal in a tunnel and reconnects with last_seq 41; the gateway replays 42 and 43. If the gap is beyond the cache, the client calls /v1/sync for a snapshot, then continues live ("snapshot plus deltas"). The client ignores any seq at or below its last applied, so duplicates are harmless. Latest-value topics skip acks.

### 3. Slow consumers and bounded queues
One producer serves a million consumers, so it never waits for a slow phone. Each connection has a bounded queue. Latest-value topics keep one slot per topic, overwritten by newer values: Sethu on 2G just sees fewer stock updates. Reliable topics hold up to 256 messages; on overflow the gateway closes with code 4008 and the client resyncs, because silently dropping would break ordering.

### 4. Reconnect storms and graceful draining
A region blip can drop 3M clients at once; synchronized retries overload TLS, auth and the remaining gateways, which fail again. Defences: full-jitter backoff (sleep uniform(0, min(30 s, 500 ms x 2^attempt))), Retry-After hints, LB rate limits returning 503, locally verified JWTs and TLS session resumption. Deploys drain at most 5% of gateways at a time: each sends reconnect hints spread over 2 minutes and exits after 5 minutes.

**Data model:**
- **Presence** (Redis): pres:{user_id}, conn_id -> gateway, TTL 60 s.
- **TopicSeq** (Redis): seq:{topic}, INCR per reliable publish.
- **UserEvent** (Kafka, 256 partitions, RF=3, 24 h): key user_id.
- **Connection** (gateway memory): subscriptions, queue, last_pong; lost on crash.

**Key APIs:**
- `wss://.../v1/connect`: JWT at upgrade; hello frame sets a 25 s heartbeat.
- `{op: sub, topic, last_seq}`: authorised; max 200 per connection.
- `POST /internal/v1/publish`: user or topic, reliable or latest, up to 4 KB.
- `GET /v1/sync?topic&since`: missed events or a snapshot.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Connections:** add gateways at about 150k each; keep under 40 KB per connection.
- **Broadcast fan-out:** conflate harder (a flag), serialise once, spread watchers.
- **Publish rate:** consistent hashing of topics over pub/sub nodes; Kafka keyed by user.
- **Per-user routing:** move from "every gateway filters" to targeted routing via presence.
- **Hot seq key:** busy shared topics (group chat) use the Kafka offset as seq.

**Failure modes:**
- **Gateway crash:** 150k clients reconnect with jitter elsewhere and resume from last_seq; presence expires in 60 s.
- **AZ loss:** a third of gateways gone; headroom plus autoscaling, admission control on connects.
- **Kafka leader failover:** idempotent producer retries; consumers pause; gaps filled by resume.
- **NATS node failure:** in-flight latest values are lost; the next conflated update within 250 ms restores state.
- **Presence shard failure:** replica promoted; routing falls back to filtering.
- **Leaky release:** 2% canary with a memory-per-connection SLO, automatic rollback.

**Trade-offs chosen:**
- **WebSockets over SSE or polling (kept as fallback):** bidirectional acks at low overhead.
- **Kafka plus NATS over one backbone:** replay for reliable, low latency for counters.
- **150k per node over 500k+:** denser is cheaper, but a crash means a bigger storm.
- **Disconnect-and-resync over drop or unbounded buffer:** dropping breaks order; buffering risks OOM.
- **Conflate at 250 ms:** nobody reads more than a few counter updates a second.
- **Filtering first, presence routing later:** filtering survives stale presence; routing scales better.

**What to measure:** connections per node and connect rate; publish-to-deliver p99 per class (synthetic probes, alert on p99); queue depth, drops and slow-consumer disconnects; time-to-reconnect; resume outcomes and client seq gaps; memory per connection; Kafka lag.

## Page 5. Say it in the interview

> "I assume 10 million connections at a sale peak, per-user updates like order tracking plus broadcast topics with a million watchers, and a 500 millisecond p99. WebSockets are stateful, so a thin gateway tier only holds sockets and talks to business services through a pub/sub backbone. Broadcast topics are subscribed once per gateway and fanned out locally, so cost scales with nodes, not connections. Reliable per-user streams go through Kafka with sequence numbers, so a reconnecting client resumes or resyncs from a snapshot. Then I defend it: 150 thousand connections per node, conflation, bounded queues, and jittered reconnects with graceful draining."

**Key points to land:**
- WebSockets make the edge stateful: isolate it in a thin gateway tier.
- Route by logical address (user, topic), never to sockets directly.
- Two-level fan-out: broker to gateways once, gateway to sockets with pre-serialised frames.
- Two delivery classes: reliable (seq, ack, Kafka replay) and latest-value (conflated).
- Snapshot plus deltas: resume from last_seq or resync from the source of truth.
- Bound every queue; conflate state, disconnect-and-resync ordered streams.
- Reconnect storms are the main outage risk: full jitter, hints, local auth.
- LBs balance arrivals, not load: least-connections and gradual draining.
- Heartbeat every 25 s, below every idle timeout.
- Size by memory: 150k per node, about 100 nodes for 10M.

**Likely follow-ups:**
1. **Offline chat recipient?** The chat service persists, FCM/APNs notifies, and the client syncs by seq on next connect.
2. **10x in the first minute of a sale?** Pre-scale, pre-warm TLS, conflate harder, jitter the client's sale-start trigger.
3. **Why not AWS API Gateway WebSockets?** Per-message pricing and limits; at 5M frames/s it is very expensive.
4. **Securing subscriptions?** JWT at upgrade, authorise each subscribe by pattern, cap at 200, re-check on refresh.
5. **Going global?** Regional fleets behind GeoDNS; user streams homed and replicated; broadcast per region.

**Director layer:**
- **Cost drivers:** about 100 gateways, about 12 Gbps peak egress, Kafka (RF=3, 24 h) and NATS.
- **Phasing:** partition filtering and the SDK first; then presence routing and two regions.
- **Ownership:** platform team owns gateways, backbone, SDK; product teams own topics and quotas.
- **Top risks:** reconnect storms, hot-topic CPU, slow-client memory, oversized publishes (4 KB cap).
