# Design an audit log and immutable history: the 5-page summary

An audit log answers "who did what, to which resource, when, from where, and was it allowed", and must be believable even when the suspect is an insider. The single most important idea: volume is easy, guarantees are hard, so design three separately: completeness (a transactional outbox), integrity (hash chains and signed, externally anchored Merkle roots plus WORM storage) and usability (rebuildable search indexes, privacy by crypto-shredding).

## Page 1. The problem, scope and numbers

**Pitch:** a trustworthy, tamper-evident record of every change to or access of sensitive data (payouts, refunds, permissions, customer PII), searchable in seconds and verifiable by an outsider.

**Who uses it:** investigators (fast search), compliance (evidence controls work), external auditors (exports they verify), service teams (under 5 ms added), the privacy office (erasure). Today's app logs rotate in 30 days, are editable and miss events on crashes.

**In scope:**
- **Capture:** outbox plus CDC, or an authenticated ingest API, with schema validation.
- **Integrity:** gapless per-stream sequence numbers, hash chains, per-minute Merkle trees, signed tree heads (STHs).
- **Storage:** append-only ledger plus WORM archive with retention locks and legal holds.
- **Query and export:** by actor, resource, action, tenant and time; inclusion proofs; evidence packages.
- **Verification and privacy:** continuous verifiers; per-subject PII encryption; every read of the log is itself logged.

**Out of scope:** debug logs and tracing, SIEM rules, public blockchain anchoring, being the source of truth for business state.

**Non-functional targets:**
- **Completeness:** no committed action without its audit record.
- **Integrity:** any edit, deletion, insertion or reordering detected within 24 h.
- **Durability:** ledger RF=3, archive 11 nines, zero loss of acknowledged events.
- **Latency:** commit to queryable p99 under 60 s (security alerts under 10 s); 90-day actor search p95 under 3 s; under 5 ms p99 added to writes.
- **Availability and retention:** ingest 99.99% (buffered), query 99.9%; 7 years financial, 2 years access.

**Capacity math (50k events/s peak, 15k/s average, 1 KB per event):**
- **Volume:** 15k x 86,400 = 1.3B events/day = 1.3 TB/day. So store diffs, not full objects.
- **Archive:** 6x compression gives 215 GB/day; x 2,555 days = about 550 TB over 7 years. So cheap object storage with Object Lock.
- **Hot ledger:** 1.3 TB x 90 days x RF 3 = 350 TB raw, about 90 TB compressed.
- **Chains:** SHA-256 at 500 MB/s per core is not the limit; the serial chain is. One chain handles 5-10k events/s, so 50k/s needs at least 8; use 64 partitions.
- **Proofs:** a minute of 3M leaves gives depth 22, so an inclusion proof is 22 x 32 B = 704 B. Verification is cheap.

## Page 2. The architecture

```
 Services (orders, payments, IAM, support console)
   | one DB txn: business row + outbox row   (no DB: SDK -> Ingest API)
 Service DB outbox --CDC (Debezium)--> Kafka audit.raw (RF=3, acks=all)
                                             |
                                             v
                        Chainer, one leader per partition (etcd lease):
                        dedupe event_id, assign seq, hash-chain
                          |                 |                  |
                          v                 v                  v
                 Ledger (append-only)  Merkle batcher 60 s  Search indexes
                 (partition, day, seq)  sign STH in HSM      (OpenSearch)
                          |                 |                  |
                          v                 v                  v
                 S3 Object Lock WORM   Anchor account +     Audit Query API
                 (hourly Parquet)      external witness     (reads audited)
 Verifier (separate team): recompute chains, roots, compare to anchored STHs
```

- **Outbox library:** canonical event inside the caller's transaction; redacts secrets.
- **CDC connector:** tails the binlog to Kafka, at-least-once, in order.
- **Kafka audit.raw:** durable buffer partitioned by stream key (tenant or domain).
- **Chainer:** single writer per partition; dedupes, sequences, chains, appends conditionally.
- **Ledger:** append-only rows; no UPDATE or DELETE grants; hot for 90 days.
- **Merkle batcher:** per-minute trees, global root, STH signed by a non-exportable HSM key.
- **WORM archiver:** hourly Parquet plus manifests in compliance-mode Object Lock.
- **Read model:** search and aggregation indexes; rebuildable and untrusted.
- **Verifier and key service:** independent integrity checks; per-subject PII keys.

**Flow A: record a refund atomically**
1. Shreya, a support agent, issues a refund; one transaction updates the refund row and inserts an outbox row (UUIDv7 event_id, before/after diff).
2. Debezium publishes it to Kafka; the chainer dedupes, assigns seq, chains, appends, then commits the offset.
3. Indexes update within seconds; a rules engine alerts on sensitive actions.

**Flow B: seal and anchor (every 60 s)**
1. Build per-partition trees over new leaves, then a global tree over the roots.
2. Sign STH {tree_size, root, ts, prev_sth_hash}; write it to the ledger and the security-owned anchor account.
3. An external witness or RFC 3161 timestamp authority co-signs it.

## Page 3. The core deep dives

### 1. Completeness: the transactional outbox
Dual writes break on crashes: the refund commits, the service dies before calling the audit API, and the record is gone. With an outbox both rows commit or neither does. CDC delivers at least once, so the chainer dedupes on event_id (source-generated, 7-day dedupe window plus a unique index) and commits Kafka offsets only after the ledger write. That is exactly-once effect. Integrity cannot prove nothing is missing, so the verifier also reconciles outbox counts against ledger counts per service every 5 minutes and flags sequence gaps.

### 2. Integrity: hash chains, Merkle trees, anchors
Each entry stores entry_hash = SHA-256(prev_hash, seq, canonical bytes), so it commits to everything before it. A DBA who changes an actor breaks that hash and the next entry's prev_hash. But an attacker with write access could recompute the whole chain, so each minute's roots go into a signed STH anchored in an account the pipeline team does not control. Merkle leaves and nodes use different prefixes (0x00, 0x01) to block second-preimage tricks. An inclusion proof is log2(n) sibling hashes; a consistency proof shows an older tree is a prefix of the newer one. Truncation is caught because an anchored tree_size is larger than the ledger.

### 3. Single writer per chain: leases and fencing
Each partition's chainer holds an etcd lease with a fencing token. After a GC pause two may believe they lead. Appends are conditional: insert IF NOT EXISTS on (partition, seq) with the token, so the stale leader fails and steps down instead of forking the chain.

### 4. Privacy versus immutability: crypto-shredding
PII (name, phone, address, IP) is encrypted with a per-subject key; action, resource and outcome stay clear. Erasure destroys the key after a legal-hold check. Hashes cover ciphertext, so proofs still verify. Secrets are redacted at source, because WORM storage cannot be undone.

**Data model:**
- **Outbox row** (service DB): id, unique event_id, canonical payload; deleted after delivery.
- **LedgerEntry** (Cassandra): partition key (partition, day), clustered by seq; prev_hash, entry_hash, key_id.
- **SignedTreeHead:** monotonic sth_id, tree_size, root, partition roots, prev_sth_hash, signature, witness signature.
- **ArchiveSegment manifest** (S3): first and last seq, segment hash, covering STH, retain_until.
- **AuditIndexDoc** (OpenSearch): actor, action, resource, time; daily indices routed by tenant.

**Key APIs:**
- `POST /v1/audit/events`: idempotent on event_id; mTLS; max 64 KB; rejects secret-tagged fields.
- `GET /v1/audit/search`: needs investigator role and case_id; the query is itself audited.
- `GET /v1/audit/entries/{partition}/{seq}/proof`: entry, audit path and signed STH.
- `GET /v1/audit/sth/consistency`: proves the later tree only appended.
- `POST /v1/audit/exports`: events, proofs, STHs and public keys for auditors.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Serial chains:** add partitions; a global Merkle root still ties them together each minute.
- **Writes:** Kafka absorbs bursts; chainers batch appends (500 events or 20 ms); ledger writes are sequential.
- **Hot tenant (30k events/s):** key on tenant plus sub-stream so it spans several chains.
- **Reads:** never from the ledger; OpenSearch for investigations, Parquet pruning for exports.
- **Archive cost:** linear in volume; keep payloads as diffs.

**Failure modes:**
- **Kafka down:** outbox rows pile up in service DBs; outbox-age alert at 5 minutes; no loss.
- **Chainer leader crash:** lease expires in 10 s; new leader recovers the tail from the ledger; fencing blocks the old one.
- **Ledger partial outage:** no appends, no offset commits, backpressure into Kafka; no gaps since seq is assigned only on success.
- **KMS signing down:** roots still computed; STHs signed on recovery; alert after 15 unsigned minutes.
- **Verifier finds a mismatch:** Sev-1 security incident; freeze the partition, compare with WORM and anchors, preserve evidence.
- **Index corrupted:** rebuild from ledger or archive; integrity unaffected.
- **Signing key stolen:** forged heads conflict with witnessed ones; revoke, rotate, re-sign the latest head.

**Trade-offs chosen:**
- **Outbox plus CDC over sync logging:** atomic, no extra hop, survives pipeline outages; sync only for a few fail-closed admin actions.
- **Per-partition order over global order:** one global writer caps throughput, and audit questions are per actor or resource.
- **Chains plus Merkle trees:** chains detect edits simply; trees add small proofs for auditors.
- **Compliance mode over governance mode:** only compliance mode stops a privileged insider deleting.
- **Separate projections over querying the ledger:** the ledger stays simple and trusted.
- **Crypto-shredding over deletion:** honours erasure and keeps proofs valid.

**What to measure:** outbox age (alert over 5 min), commit-to-ledger and commit-to-index lag, sequence gaps (must be 0), verifier coverage and mismatches (must be 0), STH interval and signing failures, reconciliation deltas, chainer append latency, query p95, searches without case ids, erasure SLA.

## Page 5. Say it in the interview

> "An audit log must guarantee three things. Completeness: if an action happened, its record exists. Integrity: nobody, including a DBA or an engineer like me, can change history without detection. Usability: auditors can find every action by a person or on a resource, years later. For completeness the service writes the audit row in the same transaction as the business change, and CDC ships it to Kafka. For integrity a single writer per partition assigns sequence numbers and chains hashes; every minute I build a Merkle tree, sign the root with an HSM key, anchor it outside the system, and seal segments in S3 Object Lock compliance mode. Reads go to separate indexes, every query is itself audited, and verifiers recompute everything continuously."

**Key points to land:**
- Three guarantees, designed separately: completeness, integrity, usability.
- Completeness comes from the outbox, not best-effort logging.
- Partitioned hash chains plus Merkle trees with signed heads, anchored outside the team.
- WORM prevents deletion; cryptography detects change; separation of duties.
- One writer per chain with fencing tokens; 64 chains for throughput.
- Exactly-once effect = at-least-once delivery + idempotent append on event_id.
- Indexes are rebuildable and untrusted; proofs come from the ledger.
- Privacy: minimise, encrypt per subject, crypto-shred.
- Audit the auditors; an unverified audit log is just a log.

**Likely follow-ups:**
1. **Why not a blockchain?** We need tamper evidence, not consensus among distrusting parties; a Merkle log with signed, witnessed heads does it far cheaper and faster.
2. **How do you prove completeness?** Atomic outbox, sequence gap checks, count reconciliation, and auditors performing known actions and finding them.
3. **A DBA edits business data directly in the DB?** CDC on business tables flags changes with no matching outbox event; direct access goes through a recorded bastion.
4. **What evidence goes to an auditor?** Scoped Parquet events, inclusion proofs, signed STHs, consistency proofs, public keys and a reference verifier they run themselves.
5. **How fast are new events searchable?** Seconds: CDC about 1 s, batching 20 ms, index refresh 1-5 s; p99 target 60 s.

**Director layer:**
- **Cost drivers:** about 550 TB of 7-year WORM archive, 90 TB of hot ledger, search indexes; control volume with diffs.
- **Phasing:** outbox, chains and WORM for payouts, refunds and IAM first; then Merkle proofs, exports and customer activity views.
- **Team ownership:** platform runs the pipeline; security owns signing keys and anchors; a separate team runs verifiers; services own events.
- **Top risks:** insider tampering, pipeline outage blocking business, PII versus erasure rights, signing key compromise.
