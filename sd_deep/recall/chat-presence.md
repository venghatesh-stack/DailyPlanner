# Presence for a Chat Application (online / away / last seen): recall card

> **Hook:** Socket ping is the heartbeat → Shard holds a device lease → Debounce fast online, slow offline → Publish only transitions → Push to on-screen watchers

**P · Problem:** It's really a high-churn soft-state fan-out problem, not a boolean per user.

**N · Numbers:**
1. 50M connections pinging every 30 s is 1.7M heartbeats/s, so they stay at the gateway and never reach the presence service.
2. 100k transitions/s x 20 watchers is 2M pushes/s, so fan-out is the bottleneck that debouncing and on-screen subscriptions control.
3. Polling would be 333M lookups/s, over 100x the push design, so push transitions plus a snapshot on open.

**H · Hard part:** Fanning out changes cheaply while mobile networks make users flicker, without ever showing an older state.

**B · Boxes:** `Client → WebSocket gateway → Presence shard → Pub/Sub bus → Subscribed gateways → Watchers`

Side path: `Presence shard → Last seen store (Cassandra) on going offline`.

**D · Decisions:**
1. A 20 s grace and 60 s lease over a 5 s timeout, because it avoids mobile flapping and offline is less urgent than online.
2. Redis Pub/Sub or NATS over Kafka, because presence is ephemeral and snapshots repair gaps.
3. Soft state plus persisted last seen over persisting everything, because state rebuilds from gateways.

**F · Failures:**
1. Gateway crash → clients reconnect elsewhere with jitter; leases and grace bridge the gap.
2. Presence shard crash → the ring reassigns users, gateways re-register devices, watchers briefly see unknown.

**C · Close:** "Polling is far too much load. Instead the WebSocket ping is the heartbeat, a presence service sharded by user id holds each device with a lease, and only transitions are published on a per-user channel. Gateways subscribe on behalf of clients, and clients subscribe only to users on screen. I debounce flapping, aggregate devices, use versions so state never goes backwards, and show counts, not per-member presence, in large channels."

**Quiz yourself:**
1. Why not Redis TTL keys with expiry notifications? → Expiry fires lazily, so offline detection lags unpredictably.
2. How does a late disconnect not override a new connect? → Each connection carries a conn_epoch and the shard bumps a monotonic version.
3. How do you show presence in a 100k-member channel? → An online count every 30 s, and presence only for members on screen.
