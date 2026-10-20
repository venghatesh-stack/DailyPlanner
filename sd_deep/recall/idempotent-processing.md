# Exactly-Once-Like Processing Using Idempotency: recall card

> **Hook:** Client key per action → Insert-or-load key row → Phases with recovery points → Derived key to gateway → Outbox → Consumer inbox

**P · Problem:** It's really an at-least-once delivery problem where every hop needs an idempotent receiver to get exactly-once effect.

**N · Numbers:**
1. 780M key rows x 600 B is about 470 GB over 32 shards, so keys live in the business database next to the orders.
2. A 40k events/s consumer would keep about 2 TB of inbox rows for 7 days, so high-volume consumers store a per-partition offset watermark instead.
3. 0.5% retries is 100 duplicates/s at peak, so each is served from the stored response in about 2 ms.

**H · Hard part:** Making the dedup record and the side effect atomic without 2PC, and resuming safely after a crash mid-way through a foreign call.

**B · Boxes:** `Client SDK → API gateway → Idempotency middleware → Phase runner → Orders DB + outbox → Kafka → Consumer inbox`

Side path: `Completer, Reaper and daily Reconciler` clean up stuck keys and prove the ledger.

**D · Decisions:**
1. Keys in the business shard over Redis, because only a shared local transaction makes record and effect atomic.
2. Outbox with CDC over 2PC, because Kafka does not join XA and 2PC blocks and adds latency.
3. Returning 409 over waiting on an in-flight duplicate, because holding connections wastes resources and can deadlock.

**F · Failures:**
1. Pod crashes after charging → the lease expires in 60 s; the retry resumes and the derived key returns the original charge.
2. Relay crashes after publishing → rows are republished with the same event_id; consumer inboxes dedup them.

**C · Close:** "Exactly-once delivery is impossible, but exactly-once effect is not. I put a boundary at every hop. At the API, an idempotency key with a fingerprint and the final response, stored in the order's own database. The request runs in phases with recovery points, and the gateway call uses a derived key, so a retry resumes safely. Events go through an outbox, each consumer records the event id with its write, and a daily reconciliation proves it."

**Quiz yourself:**
1. Why not just Kafka exactly-once? → It covers Kafka-to-Kafka only, not database writes or charges.
2. Same key, different body? → 422, never the cached answer.
3. What backstops expired keys? → Business uniqueness, like one capture per order, and entity versions.
