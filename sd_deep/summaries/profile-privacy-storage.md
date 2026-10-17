# Design user profile storage with privacy controls: the 5-page summary

Profile reads are the hottest path in a consumer product (every feed item and comment renders a name and avatar), yet every field can have its own audience, and regulators demand consent, export and verifiable erasure. The single most important idea: cache filtered views per audience class with a privacy version, make tightening synchronous and fail-closed, and treat erasure as a tracked workflow plus crypto-shredding.

## Page 1. The problem, scope and numbers

**Pitch:** one service that stores profiles, decides per viewer which fields are visible, and proves that a hide, a block or a deletion reaches every copy of the data.

**Who uses it:** privacy-conscious users (hide phone and birthday, block harassers, delete data), viewers (fast, accurate profiles), internal consumer teams (search, ads, warehouse) who want allowed fields without building privacy logic, and privacy operations analysts who must prove erasure to regulators.

**In scope:**
- **Per-field audiences:** public, followers, friends, custom list, only me.
- **Blocks and private accounts:** checked before any field rule.
- **Filtered views:** single read, plus a batch API for up to 100 owners.
- **PII vault:** email, phone, full date of birth and address, encrypted with per-user keys.
- **Consents:** per purpose, with timestamp and policy-text version.
- **Change stream, export and erasure:** purpose-filtered events to consumers; export and erase within 30 days.

**Out of scope:** the social graph itself, avatar media storage, moderation of profile text, authentication and sessions.

**Non-functional targets:**
- **Latency:** p99 under 30 ms for one profile, under 40 ms for a batch of 50.
- **Privacy propagation:** a tightening change effective everywhere in under 5 s p99.
- **Availability:** 99.99% for public card reads; degraded mode serves the public card only.
- **Durability:** RF=3 in a region, async cross-region replica.
- **Security and compliance:** every vault read logged; erasure 100% within 30 days.

**Capacity math (300M users, 4 KB per profile):**
- **Storage:** 300M x 4 KB = 1.2 TB; x3 replicas = 3.6 TB; about 10 TB with history and consents. So size is not the problem; read rate and correctness are.
- **Card cache:** 100M active x 300 B = 30 GB per region. It fits in one Memcached tier, so cache every region.
- **Reads:** 2M/s at peak, 90% card only. At 98% hits, 40,000/s reach the store, so a 30-node Cassandra cluster is enough.
- **Invalidations:** (5,000 profile + 500 privacy + 300 block) = 5,800 changes/s x 3 audience views = 17,400 deletes/s, x 5 regions = 87,000/s. So a pub/sub bus handles it.
- **Erasure:** 50,000/day x 15 consumers = 750,000 acks/day, about 9/s. Low volume, so the hard part is tracking, not throughput.

## Page 2. The architecture

```
 Viewer -> Edge/API -> Profile Service (read, write, batch hydrate)
                         |            |                 |
                 Policy Engine    View cache       Write path (CAS + outbox)
                 (rules library)  (owner, class,        |
                         |         privacy_version)     v
               Graph Service     |      Card store | Extended | PII Vault
               (follows, blocks) +----> (KV, RF3)  | (KV,RF3) | (enc,DEK)
                                             |                   |
                           outbox -> Privacy Change Stream    KMS (KEK)
                                     (Kafka, key = user_id)
                             |          |         |          |
                       Search idx  Ads feats  Warehouse  Cache invalidator
                            (purpose-filtered projections, delete acks)
                                        |
                         Erasure Orchestrator + Deletion Ledger
```

- **Profile Service:** the only read and write path; applies policy and owns the caches.
- **Policy Engine:** pure function visible_fields(settings, relationship, surface, purpose).
- **Graph Service:** returns self, friend, follower, blocked or none per viewer and owner.
- **Card and Extended stores:** wide-column KV keyed by user_id, RF=3, versioned rows.
- **PII Vault:** encrypted, region-pinned, purpose-bound access, every read audited.
- **View cache:** Memcached views per (owner, audience class), plus a hot-key local cache.
- **Privacy Change Stream:** Kafka fed by a transactional outbox, ordered per user.
- **Consent store:** per-purpose consent history, read by the projections.
- **Erasure Orchestrator:** runs deletes, collects acks, escalates, destroys keys.

**Flow A: feed hydration (50 authors)**
1. Feed calls BatchGetProfiles(viewer V, 50 owners, surface feed).
2. One batched Graph call returns all 50 relationships (cached, p99 5 ms).
3. Each owner maps to a class: blocked is dropped; else self, friend, follower or public.
4. Multiget view:{owner}:{class}; reject hits whose privacy_version is old.
5. Misses read the stores, run policy, refill (TTL 10 min public, 60 s friend).

**Flow B: privacy tightening (hide birthday from public)**
1. PATCH /v1/me/privacy; CAS on the row, privacy_version +1, outbox record in the same write.
2. Before 200, delete the public and follower views locally and broadcast to all regions.
3. The relay publishes VisibilityChanged; search drops the field.

## Page 3. The core deep dives

### 1. Policy evaluation by audience class
Order matters: blocks first, then account privacy, then the field audience. The answer is a class (self, friend, follower, public), not a per-viewer result, so the cache holds at most a few views per owner instead of one per viewer. Example: Sethu views Shreya's profile. Graph says follower, so Sethu gets view:shreya:follower, which has her bio but not her birthday (friends only). Custom-list fields are the exception: they are evaluated per request with a cached, versioned membership check. Hidden fields are absent, never marked hidden, and a blocked viewer gets the same response as for a missing account, so nothing leaks that the profile exists.

### 2. Stale privacy in caches: versions, not just deletes
The race: a fill reads the old row, the user tightens and the cache is deleted, then the slow fill writes the old public view back. The fix: each entry stores privacy_version, and every read compares it with the owner's current version from a small, strongly updated map; older entries count as misses. Fills use add-if-absent. Remote regions get the version map in under a second, so even a delayed delete is safe. Tightening is synchronous; loosening can be eventual, because showing less is always safe.

### 3. Propagating changes to every copy
Dual writes (store, then Kafka) lose events. Instead the event is written with the row: a logged batch in the same Cassandra partition, or the same PostgreSQL transaction. A relay publishes to Kafka keyed by user_id, so each user's events stay in order. Delivery is at-least-once, so consumers apply by version and ignore older or duplicate events. Each consumer is registered with purposes and gets a projection: search sees public fields only, ads sees consented attributes. PII never enters the stream.

### 4. Erasure you can prove
Delete puts the account in pending_deletion (hidden at once, 14-day undo). Then the Orchestrator writes tombstones, deletes card, extended and vault rows, publishes UserErased, and opens a ledger row per consumer. Missing acks escalate at day 20 and 25; at day 28 the consumer's access is revoked. Backups are immutable for 35 days, so PII is encrypted with a per-user data key (DEK) wrapped by a KMS key (KEK); destroying the DEK after a 7-day safety window makes every backup copy unreadable. This is crypto-shredding.

**Data model:**
- **profile_card** (Cassandra): partition user_id; name, handle, avatar, account_private, privacy_version, version.
- **profile_extended** (Cassandra): partition user_id, clustering field_key; value, audience.
- **pii_record** (region-pinned PostgreSQL): (user_id, field_key); ciphertext, dek_id.
- **consent** (PostgreSQL): (user_id, purpose, ts), append-only, latest wins.
- **deletion_ledger** (PostgreSQL): (request_id, consumer); status, due_by, acked_at.

**Key APIs:**
- `POST /v1/profiles:batchGet`: up to 100 owners; blocked owners silently omitted.
- `PATCH /v1/me/profile`: CAS on expected_version; 409 on conflict.
- `PATCH /v1/me/privacy`: returns privacy_version after synchronous invalidation.
- `POST /v1/me/data-requests`: export or erase; returns request_id and due date.
- `POST /internal/vault/read`: purpose-bound token required; every call logged.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Read fan-out:** audience-class caching keeps cardinality small; request coalescing stops stampedes.
- **Celebrity profiles (500,000 reads/s):** promote the public view to an in-process cache on every node, 5 s TTL plus push invalidation.
- **Writes:** single-partition edits by user_id with CAS; add nodes to the ring.
- **Invalidation volume:** delete only the affected classes; version checks cover delayed deletes.

**Failure modes:**
- **Graph Service slow (over 20 ms) or down:** circuit breaker; everyone is treated as public (fail closed); a local bloom filter of recent blocks still hides blocked viewers.
- **Cache shard lost:** consistent hashing remaps keys; per-owner single-flight protects the store.
- **Kafka relay stalls:** outbox rows pile up; alarm at 30 s outbox age; synchronous invalidation still protects caches.
- **KMS regional outage:** cached DEKs serve for their TTL; new PII reads fail, surfaces render without PII.
- **Region loss:** non-PII data served from other regions; EU PII stays down rather than moving.
- **Consumer misses deletions for a week:** 14-day Kafka retention plus ledger; beyond that, a reconciliation job compares IDs to tombstones.

**Trade-offs chosen:**
- **Cache per audience class over per viewer or no cache:** per viewer explodes memory; no cache cannot serve 2M reads/s.
- **Asymmetric propagation over all-synchronous:** pay the synchronous cost only for tightening.
- **Separate PII vault over one store:** smaller blast radius, crypto-shredding, residency, audit.
- **Central policy over per-surface logic:** one implementation cannot drift.
- **Fail closed over fail open:** hiding from friends briefly beats showing friends-only data to strangers.
- **Delete plus crypto-shred over rewriting backups:** backups are immutable.
- **Per-user version over timestamps:** clock skew cannot reorder two privacy updates.

**What to measure:** tightening propagation p50/p99 from synthetic probes per surface; violation rate from an offline auditor (target 0 per million renders); cache hit rate per class (over 98%) and stale-version rejections; read and batch p99; graph latency and breaker state; outbox age and consumer lag; open erasures by age and missing acks; vault reads per caller and purpose (0 unlogged).

## Page 5. Say it in the interview

> "I will assume 300 million users and about 2 million profile reads a second, mostly name and avatar, with per-field audiences, blocks that override everything, and export and erasure within 30 days. I split data by sensitivity: a public card cached everywhere, an extended profile with per-field audiences, and a PII vault encrypted with a per-user key. One Policy Engine checks blocks, then account privacy, then fields, and I cache the result per audience class with a privacy version, never per viewer. Tightening is synchronous and fails closed; loosening can lag. Every write goes through an outbox to Kafka keyed by user, and each consumer gets only the fields its purpose allows. Erasure is a ledger-tracked workflow with per-consumer acks, and destroying the user's key covers the backups."

**Key points to land:**
- Data is only about 10 TB; this is a read-rate and correctness problem.
- Three stores by sensitivity: card, extended, PII vault.
- One Policy Engine; order is blocks, account privacy, field audience.
- Cache per audience class with privacy_version; reject older versions.
- Tightening synchronous and fail-closed; loosening eventual.
- Outbox plus Kafka keyed by user_id; idempotent consumers by version.
- Purpose-filtered projections and consent checks; PII never on the stream.
- Erasure: ledger with acks, escalation at day 20, 25 and 28, crypto-shredding.
- Hidden means absent; no existence leaks.
- Prove it with synthetic probes and an offline auditor.

**Likely follow-ups:**
1. **Can a blocked user see me through search or mentions?** No: every surface hydrates through the Profile Service, and search applies a block filter at query time from the graph.
2. **Public then private within one second?** Versions order the changes and the private change invalidates synchronously; the worst case is a second when the value was legitimately public.
3. **How do you export across 15 systems?** The same consumer registry: each system has an export endpoint; the orchestrator builds an encrypted archive with a time-limited link.
4. **How do you test privacy continuously?** Property tests on the Policy Engine, synthetic accounts probed from each relationship class in production, and an offline auditor of sampled responses.
5. **Analytics after deletion?** Analytics uses pseudonymous IDs; erasure destroys the pseudonym mapping, and anything that can re-identify is deleted.

**Director layer:**
- **Cost drivers:** the cache tier in 5 regions (30 GB each), a 30-node store cluster, KMS and per-user keys, and auditing.
- **Phasing:** first the single service, policy library and class caching; then outbox and projections, migrating existing search and ads copies; then the ledger and crypto-shredding.
- **Team ownership:** profile platform, privacy engineering (policy, auditor), security (vault, KMS), privacy operations, and each consumer team for its acks.
- **Top risks:** stale caches leaking hidden fields, consumers ignoring deletions, insider access to PII, and policy logic drifting across services.
