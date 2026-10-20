# Messaging App (WhatsApp / Messenger): recall card

> **Hook:** Socket to gateway → Dedupe client_msg_id → Stamp per-conversation seq → Write device inbox → Deliver or push → Ack and delete

**P · Problem:** It's really a reliable, ordered delivery problem to devices that are often offline, over hundreds of millions of live connections.

**N · Numbers:**
1. About 1.5M messages/s at peak become about 4.3M deliveries/s, so fan-out, not sends, is the load.
2. 300M sockets / 500K per gateway = 600 gateways, about 900 with headroom, so connections are the scaling unit.
3. 300M / 240 s = 1.25M heartbeats/s, as many as messages, so gateways answer them locally, never the backend.

**H · Hard part:** Delivering every message once and in order to flaky, often-offline devices, and surviving reconnect storms.

**B · Boxes:** `Client → Gateway → Chat service → ScyllaDB message store and device inbox → Recipient gateway`

Side path: `Chat service → Push service → APNs / FCM` for offline devices.

**D · Decisions:**
1. Per-conversation sequencer over timestamps or global order, because it gives deterministic order and chats are low throughput.
2. Persistent binary socket over plain polling, because it has the lowest latency and overhead.
3. Sender Keys now over MLS, because one ciphertext per group message is enough and MLS is newer.

**F · Failures:**
1. Gateway with 500K connections dies → clients reconnect with full-jitter backoff, admission control and paged sync.
2. Conversation owner fails → ownership moves by hashing; last_seq reloads under a new fencing epoch; clients retry with the same id.

**C · Close:** "Each device keeps a long-lived socket to a gateway, and a session registry maps device to gateway. The chat service dedupes on a client message id, stamps a per-conversation sequence number, writes to a store keyed by conversation and time bucket, and adds an entry to each recipient device's inbox. Online devices get it through their gateway; offline ones get a push and sync from a cursor. At-least-once with dedupe on both ends means users see exactly once."

**Quiz yourself:**
1. What if the SENT ack is lost and the client retries? → The dedupe record returns the original msg_id and seq.
2. Why no server-side search? → End-to-end encryption means the server only routes ciphertext.
3. What do you shed first under overload? → Typing and presence, then read receipts; delivery last.
