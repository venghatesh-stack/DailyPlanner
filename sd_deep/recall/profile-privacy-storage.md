# User profile storage with privacy controls: recall card

> **Hook:** Split by sensitivity → Policy picks audience class → Cache per class with privacy version → Tighten synchronously → Outbox to Kafka → Erase with ledger and key shredding

**P · Problem:** It's really a read-heavy, per-viewer access-filtering problem where every cached copy must obey the latest privacy setting.

**N · Numbers:**
1. 300M x 4 KB is about 10 TB with history, so size is not the problem; read rate and correctness are.
2. 2M reads/s at peak, 98% cache hits leaves 40,000/s on the store, so a 30-node Cassandra cluster is enough.
3. 5,800 changes/s x 3 views x 5 regions = 87,000 invalidations/s, so a pub/sub bus carries them.

**H · Hard part:** Serving 2M reads a second from caches while a hide or block takes effect everywhere in under 5 seconds.

**B · Boxes:** `Viewer → Profile Service → Policy Engine → View cache → Card store / PII Vault`

Side path: `Outbox → Kafka (key = user_id) → Search, Ads, Warehouse, Erasure Orchestrator`.

**D · Decisions:**
1. Cache per audience class over per viewer, because per viewer explodes memory and no cache cannot serve 2M reads/s.
2. Fail closed over fail open, because hiding from friends briefly beats showing friends-only data to strangers.
3. Delete plus crypto-shred over rewriting backups, because backups are immutable for 35 days.

**F · Failures:**
1. Graph Service slow or down → breaker treats everyone as public; a local bloom filter still hides blocked viewers.
2. Kafka relay stalls → outbox rows pile up and alarm at 30 s; synchronous invalidation still protects caches.

**C · Close:** "I split profiles into a public card, an extended profile and an encrypted PII vault. One Policy Engine checks blocks, then account privacy, then field audiences, and I cache the result per audience class with a privacy version. Tightening is synchronous and fails closed. Changes flow through an outbox to Kafka, filtered by purpose. Erasure is a tracked workflow, and destroying the user's key covers backups."

**Quiz yourself:**
1. How do you stop a slow cache fill writing back an old public view? → Store privacy_version in each entry and treat older versions as misses.
2. Why is loosening allowed to be eventual? → Showing less than allowed is always safe.
3. How does erasure reach immutable backups? → Destroy the per-user data key, so every backup copy is unreadable.
