# Design Presence for a Chat Application (online / away / last seen): the 5-page summary

Presence looks like one boolean per user, but it is a high-churn, high-fan-out stream: each change may reach hundreds of watchers, and mobile networks make users flicker. The key idea: treat presence as soft state built from live connections and leases, keep heartbeats at the gateway, debounce transitions, and fan out only to watchers who are actually looking.

## Page 1. The problem, scope and numbers

**Pitch:** show whether a contact is online, idle, on DND or when they were last seen, fresh, stable and private, cheaply enough for hundreds of millions of users. Today polling shows stale, flickering dots and eats a large share of chat backend capacity.

**Who uses it:** mobile users (no flicker, low battery cost), desktop team users (active, away, DND), privacy-conscious users (hide last seen, appear offline), and the messaging and calling teams (push versus in-app delivery).

**In scope:**
- **Per-device state** aggregated per user: active over idle over DND over offline.
- **Real-time push** of changes to subscribed watchers over the existing WebSocket.
- **Snapshot plus subscribe** for the user ids on screen.
- **Last seen**, served subject to privacy settings.
- **Manual states:** DND, appear offline, custom status with expiry.
- **Approximate online counts** for large channels.

**Out of scope:** typing indicators and read receipts, message delivery and storage, call signalling, activity analytics, strongly consistent presence.

**Non-functional targets:**
- **Latency:** online visible within 2 s p95; offline within 60 s p95 on unclean disconnect, about 2 s on clean logout; snapshot p99 under 50 ms.
- **Availability:** 99.9%; a failure shows stale or unknown presence, never blocks messaging.
- **Consistency:** eventual, but monotonic per user: never an older state after a newer one.
- **Battery and privacy:** heartbeat at most every 30 s in foreground, none in background; zero leaks of hidden state.
- **Stability and cost:** under 1% of transitions shown as flaps; cost 70% below polling.

**Capacity math (300M DAU, 50M concurrent connections, 1.3 devices each):**
- **Heartbeats:** 50M / 30 s = 1.7M pings/s, about 4k/s per node on 400 gateways. So they stay at the gateway and never reach the presence service.
- **Transitions:** 300M x 10 / 86,400 = about 35k/s, about 100k/s at 3x peak. So the presence service only sees changes.
- **Fan-out:** 100k/s x 20 watchers = 2M pushes/s, about 120 MB/s. This is the bottleneck that debouncing and on-screen subscriptions exist to control.
- **State:** 65M online devices x 100 B = 6.5 GB. So keep it in memory and shard for throughput.
- **Subscriptions:** 50M connections x 100 visible users = 5B edges x 40 B = 200 GB, about 0.5 GB per gateway. So gateways hold them locally.
- **Polling baseline:** 50M x 200 contacts / 30 s = 333M lookups/s, over 100x the push design.
- **Last seen:** written only on going offline, about 15k/s. Trivial for Cassandra or DynamoDB.

## Page 2. The architecture

```
  Phone / Desktop clients
      |  WebSocket (ping every 30 s)
      v
  Gateway nodes x400 -- local map: watched_uid -> [connections]
      |  connect / disconnect / activity          ^  presence deltas
      v                                           |
  Presence service, sharded by user_id            |
   in RAM: devices, leases, aggregate, privacy,   |
   debounce timers, version                       |
      |  publish transition                       |
      v                                           |
  Pub/Sub bus (Redis or NATS), topic presence:{uid} ---+
      +--> Last seen store (Cassandra / DynamoDB)
      +--> Channel counter service -> online counts every 30 s
  Ring of presence shards kept in etcd; gateways cache it
```

- **WebSocket gateway:** terminates sockets, answers pings, detects disconnects, pushes deltas.
- **Presence service:** per-user soft state: leases, aggregate, debounce, privacy, version.
- **Pub/Sub bus:** routes each transition only to gateways with a watcher of that user.
- **Subscription manager (in gateway):** ref-counts watched users; subscribes once per user.
- **Last seen store:** durable last offline time per user.
- **Privacy settings service:** visibility and block lists, cached in presence shards.
- **Channel counter service:** approximate online counts for large channels.
- **Ring coordinator:** consistent hash ring of presence nodes in etcd or ZooKeeper.

**Flow A: user comes online**
1. Gateway authenticates and sends DeviceConnected(user, device, gateway, epoch) to the owner shard.
2. Shard creates the device lease (TTL 60 s) and recomputes the aggregate.
3. If now online and not hidden, wait a 2 s debounce; if still connected, bump version, publish.
4. Bus delivers to subscribed gateways; they push to watchers, who drop older versions.

**Flow B: phone loses signal**
1. Missed pings or a TCP reset: gateway sends DeviceDisconnected(unclean).
2. Shard starts a 20 s offline grace. A reconnect on any gateway renews the lease, publishing nothing.
3. Otherwise: aggregate offline, last seen written, version bumped, offline published.

## Page 3. The core deep dives

### 1. Heartbeats, leases and failure detection
You only ever detect silence, not death. The WebSocket ping every 30 s is the heartbeat, handled by the gateway. The presence service holds a 60 s lease per device, longer than the ping interval plus jitter. Clean logouts publish offline in about 2 s; crashes rely on a TCP reset or missed pings plus the grace. Millions of leases need timers, so each shard uses a hashed timing wheel with 1 s slots: O(1) insert and cancel, each tick expires one slot, a renewal moves the lease to a later slot.

### 2. Debounce and multi-device aggregation
Fast online, slow offline. Going online waits 2 s so a quick open and close notifies nobody; going offline waits 20 s after an unclean drop. If Shreya's phone switches from Wi-Fi to 4G and reconnects in 5 s, Sethu sees her online the whole time, and a full fan-out is saved. The aggregate is the most active device: desktop idle plus phone active shows active; when the phone backgrounds, she shows idle, not offline. Desktop idle needs 10 minutes without input.

### 3. Interest-based fan-out with backpressure
Each user has a topic presence:{uid}. Clients subscribe only to the about 100 users on screen (cap 500). A gateway subscribes once per watched user, ref-counted, so the bus delivers once per gateway, not per connection. Gateways keep a per-connection map of uid to latest state and flush every 250 ms (1 s under load). Presence is state, so only the latest value matters. A slow client's backlog is replaced by a snapshot. Under overload, idle and active nuance is dropped first.

### 4. Ordering and ownership
Each user's shard is the single writer and bumps a monotonic version per transition; gateways and clients drop lower versions. Each connection carries a conn_epoch, so a late disconnect from an old connection cannot override a new connect. If a shard dies, the ring moves its users to neighbours and gateways re-send DeviceConnected; state rebuilds in seconds and clients briefly see "unknown", not a false offline.

**Data model:**
- **UserPresence** (shard memory): uid; devices map (gateway, conn_epoch, state, lease expiry), aggregate, version; owner = ring(uid); not persisted.
- **LastSeen** (Cassandra/DynamoDB): PK uid; last_seen_ts; written on going offline.
- **PresenceSettings** (Postgres plus shard cache): PK uid; last seen visibility, appear offline, dnd_until, custom status.
- **GatewaySubscriptions** (gateway memory): watched_uid to connections, and back.

**Key APIs:**
- `WS subscribe / unsubscribe {uids}`: up to 500 per connection; returns a snapshot.
- `WS presence {uid, state, v, ts}`: server push; may be batched per second.
- `RPC PresenceService.DeviceEvent`: connect, clean or unclean disconnect, activity, with conn_epoch.
- `RPC PresenceService.BatchGet {viewer_uid, uids}`: privacy applied per viewer.
- `PUT /v1/me/presence-settings`: last seen visibility, appear offline, DND; publishes at once.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Fan-out:** debounce, on-screen subscriptions, gateway-level ref counting and 250 ms coalescing.
- **Celebrities or support agents with 2M watchers:** cap subscribers; above a threshold switch to pull-on-view with state cached for 30 s, or disable presence.
- **100k-member channels:** never per-member fan-out (it is O(n squared)); show a count every 30 s, fetch presence only for the 50 members on screen.
- **Heartbeats:** stay on gateways; add gateway nodes, not presence shards.
- **Cross-region watchers:** users homed in a region; a bus bridge forwards only topics with remote subscribers, adding 100-200 ms.

**Failure modes:**
- **Gateway crash (125k sockets):** clients reconnect elsewhere with jittered backoff; leases and grace bridge the gap; only those not back in time go offline.
- **Presence shard crash:** ring reassigns users, gateways re-register devices, brief unknown state.
- **Pub/Sub degraded:** deltas lost or late; snapshots on screen open and reconnect repair it; messaging unaffected.
- **Mass reconnect after a network blip:** jitter spreads load; debounce hides most offline-then-online flips; gateways coalesce.
- **Last seen store slow:** writes buffered and retried; reads use in-memory values or omit them.
- **Privacy cache stale:** changes invalidate and publish at once; on a miss, fail closed and show offline.

**Trade-offs chosen:**
- **Push transitions plus a snapshot on open over polling:** polling is over 300M lookups/s.
- **Gateway pings over a client presence API:** 1.7M heartbeats/s stay at the edge.
- **20 s grace and 60 s lease over a 5 s timeout:** avoids mobile flapping; offline is less urgent than online.
- **Redis Pub/Sub or NATS over Kafka or direct RPC:** ephemeral, low latency, at-most-once; snapshots repair gaps.
- **Soft state plus persisted last seen over persisting everything:** state rebuilds from gateways; persisting would cost about 100k writes/s for nothing.

**What to measure:** online propagation p50/p95, offline detection for clean and unclean drops, flap rate before and after debounce, transitions and pushes per second per gateway, subscriptions per connection, sampled accuracy against real connection state (target over 99%), reconnect time, buffer overflows and snapshot resyncs.

## Page 5. Say it in the interview

> "Presence sounds trivial, so let me say what makes it hard. I assume online, idle, DND and offline with last seen; 300 million daily users and 50 million concurrent connections; about 200 contacts each; channels up to 100k members; online shown within 2 seconds, offline within about a minute; eventual consistency. Polling a presence table is far too much load. Instead the WebSocket itself is the heartbeat, a presence service sharded by user id holds each user's devices with a lease, and only transitions are published on a per-user channel. Gateways subscribe on behalf of clients, and clients subscribe only to users on screen. Fan-out is the bottleneck, so I debounce flapping, aggregate devices and avoid per-member fan-out in large channels. Gateway crashes are absorbed by leases and fast reconnects."

**Key points to land:**
- Presence is soft state from live connections and leases; persist only last seen.
- The socket ping is the heartbeat and stays at the gateway.
- Shard by user id with consistent hashing so all devices aggregate in one place.
- Fan-out is the bottleneck: 100k transitions/s x 20 watchers = 2M pushes/s.
- Subscribe only to users on screen; gateways ref-count and fan out locally.
- Fast online (2 s), slow offline (20 s grace) to suppress mobile flapping.
- Monotonic versions and connection epochs stop going backwards.
- Large channels get counts, not per-member presence.
- Privacy is enforced server-side in one place before any publish or read.

**Likely follow-ups:**
1. **Typing indicators?** Same transport, per-conversation topic, a 5 s TTL refreshed while typing, never persisted, only to participants with the chat open.
2. **Why not Redis TTL keys with expiry notifications?** Expiry fires only when keys are accessed or sampled, so offline detection lags unpredictably; a shard with a timing wheel is precise and cheaper at 50M users.
3. **A user with 5,000 contacts?** Watchers subscribe only to what is on screen, so a big contact list does not mean big fan-out.
4. **Across regions?** Home users in a region; a cross-region bridge forwards only topics with remote subscribers; 100-200 ms extra is fine.
5. **How do you test it?** Simulated clients that flap realistically, chaos tests killing gateways and shards, and a continuous accuracy auditor in production.

**Director layer:**
- **Cost drivers:** reuse the 400-node gateway fleet; about 6.5 GB of shard state and 200 GB of gateway subscriptions; the goal is 70% cheaper than polling.
- **Phasing:** first replace polling with push plus snapshots; then debounce and multi-device aggregation; then large-channel counts and cross-region bridging.
- **Ownership:** realtime infrastructure owns gateways and the bus; a presence team owns shards and privacy rules; privacy and trust reviews visibility.
- **Top risks:** fan-out storms on gateway restarts, hot users with millions of watchers, privacy leaks via timing, and presence scraping (contacts only, rate limits).
