# Audit log and immutable history: recall card

> **Hook:** Outbox in the same transaction → CDC to Kafka → Single writer chains hashes → Sign Merkle root each minute → Anchor outside → Seal in WORM

**P · Problem:** It's really a tamper-evident append-only log that must be believable even when the suspect is an insider.

**N · Numbers:**
1. 1.3B events/day is 1.3 TB/day, so store diffs, not full objects.
2. About 550 TB over 7 years, so archive in cheap object storage with Object Lock.
3. One chain handles 5-10k events/s and peak is 50k/s, so use 64 partitions.

**H · Hard part:** Proving nothing is missing and nothing was changed, without a single global writer capping throughput.

**B · Boxes:** `Service DB outbox → Debezium CDC → Kafka audit.raw → Chainer → Ledger → S3 Object Lock`

Side path: `Merkle batcher → HSM-signed tree head → external anchor and witness`.

**D · Decisions:**
1. Outbox plus CDC over synchronous logging, because it is atomic and survives pipeline outages.
2. Per-partition order over global order, because one global writer caps throughput and questions are per actor or resource.
3. Crypto-shredding over deletion, because it honours erasure and keeps proofs valid.

**F · Failures:**
1. Kafka down → outbox rows pile up in service DBs; alert at 5 minutes, no loss.
2. Chainer leader crash → lease expires in 10 s; fencing tokens block the old leader from forking the chain.

**C · Close:** "I design three guarantees separately. Completeness: the audit row commits in the same transaction as the business change, and CDC ships it. Integrity: one writer per partition sequences and chains hashes, and every minute I sign a Merkle root in an HSM, anchor it outside the team and seal segments in WORM storage. Usability: rebuildable search indexes, every query audited, and verifiers recompute everything continuously."

**Quiz yourself:**
1. Why not a blockchain? → We need tamper evidence, not consensus; signed, witnessed Merkle heads are far cheaper.
2. Can an attacker recompute the whole chain? → Yes, which is why signed tree heads are anchored outside their control.
3. How do you erase a customer's PII? → Destroy their per-subject key; hashes cover ciphertext so proofs still verify.
