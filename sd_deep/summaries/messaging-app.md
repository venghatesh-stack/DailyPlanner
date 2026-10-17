# Design a Messaging App (WhatsApp / Messenger): the 5-page summary

A messaging app must deliver every message once, in order, to devices that are often offline, at tens of billions of messages a day, without the server ever reading the content. The single most important idea: at-least-once delivery plus idempotency keys and client dedupe gives effectively exactly-once, ordered by a per-conversation sequence number, over a gateway fleet that holds 300M live connections.

## Page 1. The problem, scope and numbers

**Pitch:** fast, reliable, private messaging for individuals and groups that works on 2G in a village as well as on Wi-Fi in a city.

**Who uses it:** end users (instant, private, light on data and battery), business users (throughput, delivery status), the security team (E2EE correctness), legal and compliance (residency, spam), and SRE (connection capacity, deploys that do not drop millions of sockets).

**In scope:**
- **1:1 and group chat:** groups up to 1,024 members; text, replies, reactions.
- **Message states:** clock (sending), one tick (server), two ticks (device), blue ticks (read).
- **Offline queueing and sync**, ordered per conversation, plus push notifications.
- **Presence and typing**, with privacy settings.
- **Media:** client-encrypted, resumable uploads to blob storage.
- **Multi-device:** phone plus up to 4 linked devices, each with its own keys.

**Out of scope:** voice and video calls, stories, payments, bots, server-side search (impossible with E2EE), broadcast channels with millions of followers, global ordering across chats.

**Non-functional targets:**
- **Latency:** p99 under 500 ms send-to-receive in a region, both online; under 1 s globally.
- **Reliability:** zero loss of acknowledged messages; duplicates shown under 1 per 10M.
- **Ordering:** total order per conversation via server sequence numbers.
- **Availability:** 99.99% for send and receive.
- **Durability:** undelivered messages kept RF=3 across zones for up to 30 days.
- **Efficiency:** idle heartbeat at most every 4-5 minutes; under 100 bytes of framing.

**Capacity math (1B DAU, 50 messages per user per day, 200 B each):**
- **Messages:** 50B / 86,400 = about 580K/s, about 1.5M/s at a 2.5x peak.
- **Deliveries:** 75% 1:1 x 1.3 devices + 25% group x 20 members x 1.3 = about 7.5 per message, so about 4.3M deliveries/s. So fan-out, not sends, is the load.
- **Connections:** 30% of DAU = 300M sockets / 500K per gateway = 600 gateways, about 900 with failover headroom. So connections are the scaling unit.
- **Heartbeats:** 300M / 240 s = 1.25M/s, as many as messages. So gateways answer them locally, never the backend.
- **Text storage:** 50B x 200 B = 10 TB/day; 30 days = 300 TB, 900 TB with RF 3.
- **Media:** 5% x 300 KB = 750 TB/day into blob storage with lifecycle expiry.

## Page 2. The architecture

```
 Phone / laptop  (TLS/Noise long-lived socket)
      |                      |
      | pre-signed PUT       v  L4 load balancer (sticky)
      v                Gateway fleet (600-900) <--register--> Session registry
 Blob store + CDN            | frames      ^ deliver          (Redis, TTL)
                             v             |                      ^
                       Chat service: dedupe, sequence, persist, route
                        |              |              |
                        v              v              v
                  Message store    Group svc     Push svc -> APNs / FCM
                  (conv_id, bucket) (members)    (offline devices)
                  + device inbox
                  Presence svc (heartbeat TTL, pub/sub) and Key service
```

- **Client app:** local encrypted DB, outbox with client_msg_id, Signal sessions, dedupe.
- **Gateway:** holds sockets, auth, heartbeats, flow control; forwards frames.
- **Session registry:** device_id -> gateway and connection epoch, TTL refreshed by heartbeats.
- **Chat service:** dedupe, per-conversation sequence, persistence, inbox writes, routing.
- **Message store (ScyllaDB):** partitioned by (conversation, time bucket), clustered by seq.
- **Device inbox:** per-device queue of pending message references; the offline queue.
- **Group service:** membership, roles, member device lists, sender-key metadata.
- **Presence service:** online and last-seen, published only to contacts with the chat open.
- **Push service:** APNs and FCM wake-ups for offline devices, no plaintext.
- **Key service:** public identity keys and prekeys per device.

**Flow A: send 1:1, recipient online**
1. Shreya's phone encrypts per device of Sethu and sends SEND with a client_msg_id.
2. Chat owner of the conversation dedupes, assigns the next seq, writes the message and Sethu's inbox rows.
3. Shreya gets SENT (one tick).
4. Registry lookup finds Sethu's gateway; it writes the frame down his socket.
5. Sethu's client dedupes by msg_id and acks; inbox row deleted; Shreya sees two ticks.

**Flow B: recipient offline, then reconnects**
1. No registry entry, so the message waits in the inbox and a push is sent.
2. Sethu reconnects, registers with a new epoch, sends SYNC with his cursor.
3. The inbox is paged 100 at a time; each acked page is removed and receipts flow back.

## Page 3. The core deep dives

### 1. Effectively exactly-once delivery
The network is at-least-once, so both ends dedupe. Shreya's outbox stores each message with a UUID client_msg_id and retries until SENT. The server keeps a dedupe record on (device_id, client_msg_id) for 7 days. If the SENT ack is lost on a flaky network and she retries, the server returns the original msg_id and seq, and stores nothing new. On the other side, the server keeps the inbox entry until Sethu's device acks, and redelivers after 10 s or on reconnect; his client dedupes on msg_id and re-acks. Result: no loss, no visible duplicate.

### 2. Ordering with a per-conversation sequencer
Each conversation is owned by one chat service instance, chosen by consistent hashing on conv_id. The owner keeps last_seq in memory and stamps each message. Two group members sending at the same instant are serialised by that owner, so everyone sees the same order. Client clocks are ignored; seq orders, server_ts only labels. Steps: dedupe, allocate, then a conditional insert. A crash between allocation and write leaves a gap, never a duplicate; a client that sees a gap asks SYNC for the range, and empty gaps are confirmed. On failover the new owner reloads the max seq under a new fencing epoch, so two owners never allocate at once.

### 3. The connection tier and reconnect storms
300M sockets sit on 600-900 gateways that handle TLS, auth and 1.25M heartbeats/s locally. The registry entry carries a connection epoch, so a stale gateway cannot overwrite a newer registration. The scariest failure is a gateway with 500K connections dying: every client reconnects at once. Defence: full-jitter backoff (wait a random 0 to min(60 s, 0.5 s x 2^n)), admission control returning RETRY_AFTER, TLS session resumption, and paged sync. Deploys drain 1-2% of connections per minute.

### 4. End-to-end encryption
Signal protocol: the key service holds public keys and prekeys per device. A 1:1 message carries one ciphertext per recipient device. Groups use Sender Keys, so the server stores one ciphertext; removing a member rotates the key. Media is AES-256 encrypted on the device, with the key inside the message. The server sees routing metadata only.

**Data model:**
- **Message** (ScyllaDB): PK ((conv_id, bucket), seq DESC); 10-day buckets, TTL 30 days.
- **DeviceInbox:** PK (device_id, inbox_seq); deleted on ack, TTL 30 days.
- **DedupeRecord:** PK device_id#client_msg_id -> msg_id, seq; TTL 7 days.
- **Conversation:** conv_id (direct = hash of the two user ids), members_version, last_seq.
- **Session** (Redis): device_id -> gateway_id, connection_epoch; TTL 2 x heartbeat.

**Key APIs:**
- `SEND` frame: idempotent on (device_id, client_msg_id); retried until SENT.
- `DELIVER` frame: redelivered if not acked within 10 s or on reconnect.
- `SYNC` frame: page the inbox from a cursor after reconnect.
- `RECEIPT` frame: cumulative, "read up to seq 812".
- `GET /v1/keys/{user_id}/devices`: consumes one prekey per device to start a session.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Connections:** add gateways (500K each); the in-memory, sharded registry serves millions of lookups/s.
- **Fan-out:** batch registry lookups and send one RPC per gateway; cap groups at 1,024.
- **Hot group partitions:** time-bucketed partitions, read coalescing, per-group rate limits.
- **Store tail latency:** ScyllaDB shard-per-core, compaction throttling.
- **Overload:** shed typing and presence first, then delay read receipts; delivery degrades last.

**Failure modes:**
- **Gateway crash:** clients reconnect with jitter elsewhere; newer epochs win; inboxes sync on reconnect.
- **Conversation owner fails:** ownership moves by hashing; last_seq reloaded under a new epoch; clients retry with the same id.
- **Store replica down:** RF 3 with LOCAL_QUORUM continues on 2 of 3; repair restores it.
- **Registry shard lost:** lookups fail open to "offline": inbox plus push; rebuilt by the next heartbeats.
- **APNs or FCM degraded:** push retries; messages are safe in inboxes.
- **Region outage:** DNS steers clients to another region; conversations fail over to replicas, and async replication may lose the last seconds.
- **Partition between regions:** each conversation has one home region that sequences it, so no split-brain ordering.

**Trade-offs chosen:**
- **Persistent binary socket, long-polling fallback:** lowest latency and overhead.
- **Per-conversation sequencer over timestamps or global order:** deterministic order, chats are low throughput.
- **30-day server retention:** enough for offline and multi-device sync, limits metadata and storage (300 TB, not petabytes).
- **Sender Keys now, MLS later:** one ciphertext per group message; MLS scales past about 1K members but is newer.
- **ScyllaDB:** append-heavy, partition-by-conversation access, low tail latency without JVM GC.
- **Cumulative receipts:** one "read up to 812" replaces dozens.

**What to measure:** delivery latency p50/p99, connections and reconnect rate per gateway, SEND ack timeouts and dedupe hit rate, inbox depth and oldest undelivered age, store p99, push success, seq gap rate, load-shedding activations. Synthetic probe accounts send sequenced messages and alert on any gap: message loss target is zero.

## Page 5. Say it in the interview

> "I will assume 1 billion daily users sending 50 messages each: about 1.5 million messages a second at peak, which fan out to several million deliveries, and 300 million open connections. Groups up to 1,024, end-to-end encrypted. Each device keeps a long-lived socket to a gateway; a session registry maps device to gateway. The chat service dedupes on a client message id, stamps a per-conversation sequence number, writes to a store partitioned by conversation and time bucket, and adds an entry to each recipient device's inbox. Online devices get the message through their gateway; offline ones get a push and sync from a cursor on reconnect. Delivery is at-least-once with dedupe on both ends, so users see exactly once. The scariest failure is a reconnect storm, handled with jittered backoff and admission control."

**Key points to land:**
- Order per conversation with a single sequencer, never global, never client clocks.
- At-least-once plus idempotency keys plus client dedupe = effectively exactly-once.
- Gateways plus a session registry; connections (300M) are the scaling unit.
- Offline: durable per-device inbox, push to wake, sync from a cursor.
- Store keyed (conversation, time bucket), clustered by seq: one slice per read.
- 1.5M sends/s become about 4.3M deliveries/s.
- Presence and typing are soft state, subscribe-on-view, shed first.
- Reconnect storms: full jitter, admission control, paged sync.
- Signal protocol: the server routes ciphertext only, so no server search.

**Likely follow-ups:**
1. **Latency budget for 500 ms?** Client upload 100-200 ms, gateway plus sequencing plus quorum write 20-30 ms, registry about 5 ms, push to device 100-200 ms; server side well under 50 ms.
2. **Groups of 100K?** Switch to a read model: store once, no per-device inbox rows, push via per-channel pub/sub, offline members pull the log; per-channel keys or no E2EE.
3. **Multi-device without the phone online?** Each device is a full endpoint with its own keys and inbox; senders encrypt to all devices; history comes encrypted from another device or backup.
4. **Recipient in another region?** The conversation is homed in one region; messages cross a 100-200 ms link and a regional relay delivers to the recipient's gateway.
5. **How do you detect loss?** Synthetic probes between regions, client-reported seq gaps, and reconciling SENT acks against device acks by age.

**Director layer:**
- **Cost drivers:** 600-900 gateways for 300M sockets, about 900 TB of replicated message data, 750 TB/day of media with lifecycle expiry, and push volume.
- **Phasing:** 1:1 and offline sync first; then groups with Sender Keys, multi-device, and later MLS for large groups.
- **Team ownership:** connection tier, messaging core (sequencing, store, inbox), groups and presence, media, crypto and keys, integrity and spam.
- **Top risks:** reconnect storms after failures, spam at scale with no content visibility, hot large groups, key or protocol bugs, and store latency spikes.
