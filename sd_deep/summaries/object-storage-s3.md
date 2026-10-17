# Design an Object Storage Service (S3): the 5-page summary

Object storage looks like a giant key-value store of immutable blobs, but it is really two systems: a strongly consistent, range-partitioned metadata index (bucket and key to version and chunk locations) and a cheap, self-healing data plane that erasure-codes chunks across drives, racks and availability zones. The single most important idea: write the fragments first, then commit the metadata, and ack only after that commit; the commit is the one point that makes reads strongly consistent.

## Page 1. The problem, scope and numbers

**Pitch:** one cheap, practically infinite, eleven-nines durable store with an S3-compatible HTTP API, so teams stop running their own NFS and HDFS clusters and the company pays commodity disk prices.

**Who uses it:** backend developers (SDKs, pre-signed URLs), data engineers (multi-GB parallel uploads, range reads, fast LIST), security admins (policies, encryption, audit logs), storage operators (drive health, repair progress, capacity forecasts).

**In scope:**
- **Buckets:** create, delete, policy, versioning, lifecycle, encryption, replication config.
- **Objects:** PUT up to 5 GB, GET with Range, HEAD, DELETE, COPY, conditional requests.
- **Multipart upload:** parts of 5 MB to 5 GB, up to 10,000 parts, atomic complete.
- **LIST v2:** by prefix and delimiter, 1,000 keys per page, continuation tokens.
- **Versioning and access:** version ids, delete markers, signed requests, pre-signed URLs.
- **Storage classes, encryption, checksums, event notifications.**

**Out of scope:** POSIX semantics and file gateways, query-in-place (S3 Select), CDN edge caching, billing internals, synchronous multi-region writes.

**Non-functional targets:**
- **Durability:** 11 nines per object per year; survive loss of a full AZ plus one more drive.
- **Availability:** 99.99% for standard-class reads and writes.
- **Consistency:** strong read-after-write for PUT, DELETE and LIST on a single key; no multi-key transactions.
- **Latency:** small GET p99 under 100 ms first byte; small PUT p99 under 200 ms.
- **Throughput:** 1M requests/s per region; a prefix partition takes 3,500 writes/s and 5,500 reads/s before splitting.
- **Cost:** 1.5x raw storage overhead or less for the standard class.

**Capacity math (100 PB, 100B objects, 1M requests/s, RS(10,4)):**
- **Raw disk:** 100 PB x 1.4 = 140 PB; / 16 TB usable per drive = about 8,750 drives; / 60 per server = about 150 servers, plan 200+. So erasure coding, not 3x replication.
- **Growth:** 0.6 PB/day net x 1.4 = 0.84 PB raw = about 52 drives, about one server per day.
- **Drive failures:** 8,750 x 1.5% AFR = about 130 a year; several a day at 10x. So repair is continuous background load.
- **Repair:** one lost 16 TB drive means reading 10 fragments per lost fragment, about 160 TB; at 50 GB/s about 1 hour. So spread stripes over hundreds of drives.
- **Metadata:** 100B x 500 B = 50 TB, 150 TB with 3 replicas; at 1 TB per replica about 50,000 partitions. So the index must be partitioned and the hot problem is request heat, not bytes.
- **Ingest:** 1 PB/day = 11.6 GB/s, about 35 GB/s peak, about 50 GB/s after coding (about 25 MB/s per drive).

## Page 2. The architecture

```
 Clients / SDKs / pre-signed browser uploads
        | HTTPS (SigV4)
        v
 Load balancers -> Front-end fleet (stateless) <------> IAM / policy svc
                   auth, chunking, erasure coding,
                   metadata cache + witness check
          |                      |                        |
          | lookups / commits    | stripe placement       | fragment I/O
          v                      v                        v
 Metadata service        Placement service        Storage nodes (AZ a/b/c)
 range partitions,       drives, failure          HDD JBOD, local LSM
 Raft x3 per partition   domains, health          store, checksums
          |                                               ^ read / rebuild
          v                                               |
 Witness (recent writes)   Background: scrubber, repair, GC, lifecycle,
                           metering, cross-region replication
```

- **Front-end fleet:** TLS, signature check, policies, chunking, erasure coding, quotas.
- **Metadata service:** sorted (bucket, key, version) index; 3-AZ Raft per partition.
- **Partition manager:** splits hot or large ranges, merges cold ones, balances leaders.
- **Placement service:** picks drives per stripe across AZs and racks; avoids degraded drives.
- **Storage nodes:** fragments on HDDs, checksums verified on every read.
- **Witness:** tracks recently written keys so caches know when they may be stale.
- **Repair and scrubber:** rebuild lost fragments, most-damaged stripes first; catch bit rot.
- **Garbage collector:** deletes unreferenced fragments after a grace period.
- **KMS:** envelope encryption with per-object data keys wrapped by bucket keys.

**Flow A: PUT a 50 MB object**
1. Front-end authenticates, checks policy and the partition's request quota.
2. Placement returns 14 drives on 14 servers, spread 5/5/4 across 3 AZs.
3. Per 8 MB chunk-set, compute RS(10,4) fragments plus CRC32C; write all 14 in parallel; accept with at least 12 durable, repair the rest.
4. Verify the client checksum, conditional-write the version and chunk map to the partition leader (Raft majority), bump the witness, return 200.

**Flow B: GET with Range**
1. Use the cached metadata only if the witness says it is fresh; else read the leader.
2. Map the range to stripes and read the 10 data fragments, no decode needed.
3. A slow or failed fragment triggers a hedged read of parity and a decode.

## Page 3. The core deep dives

### 1. Erasure coding instead of replication
RS(10,4) (Reed-Solomon) cuts data into 10 fragments and computes 4 parity fragments; any 10 of the 14 rebuild the data. Overhead is 1.4x instead of 3x, and it survives 4 lost fragments instead of 2. The cost is repair: one lost fragment means reading 10. Placement puts at most one fragment of a stripe per server and rack, so a dead server degrades many stripes by one fragment and repair runs in parallel. Repair goes by risk: a stripe at 12 of 14 jumps ahead of one at 13, and one at 10 gets unthrottled bandwidth. Small objects (1 KB) are packed into shared stripes; metadata stays 3x replicated.

### 2. Strong read-after-write with caches
A PUT acks only after the Raft commit (2 of 3 AZs) and a witness bump. The witness holds the latest write sequence per key hash. A front-end uses its cached entry only if the entry's sequence is at least the witness's; otherwise it asks the leader. So a GET right after a PUT can never return the old version, yet most reads stay cached. LIST always reads partition leaders. If the witness is down, everything reads leaders: slower, still correct.

### 3. Hot key ranges in the metadata index
Every request touches the index, and sequential keys (logs/2026-10-11/...) push all writes into one range. Each partition reports ops/s and size; above about 3,500 writes/s, 5,500 reads/s or 1 TB sustained, it splits at the load median (not the size median), repeatedly if the newest range stays hot. During a split clients get 503 SlowDown and back off with jitter; guidance is to spread prefixes.

### 4. Deletes, orphans and integrity
DELETE only changes metadata (a delete marker with versioning). GC deletes stripes unreferenced after 48 hours, including orphans from a PUT whose metadata commit failed. Checksums run end to end: client to front-end (400 BadDigest on mismatch), CRC32C per fragment on read, repair and scrub.

**Data model:**
- **Bucket:** globally unique bucket_name; owner, region, versioning, policy, encryption, lifecycle; heavily cached.
- **Object version:** key (bucket, key, inverted version_id) so newest sorts first; size, ETag, class, wrapped data key, chunk_map of stripe ids; range-partitioned.
- **Stripe:** stripe_id (hash-partitioned); fragment locations, checksums, state. Objects point to stripes, so repair never touches object records.
- **Fragment:** stripe_id plus index, data and CRC32C in a local LSM store.
- **Multipart upload:** (bucket, key, upload_id) to parts, expired after 7 days.

**Key APIs:**
- `PUT /{bucket}/{key}`: up to 5 GB; If-None-Match: * for create-only.
- `GET /{bucket}/{key}?versionId=`: strongly consistent with the latest commit.
- `GET /{bucket}?list-type=2&prefix=&delimiter=/`: range scan over the sorted index.
- `PUT /{bucket}/{key}?partNumber=N&uploadId=U`: idempotent per part number.
- `POST /{bucket}/{key}?uploadId=U`: atomically commits the assembled object.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Metadata heat, not bytes:** load-based range splits, cached routing tables, per-bucket quotas.
- **Reads:** front-end metadata caches with the witness, data fragments read without decode, CDN for public objects, extra cached copies of a viral object (50k GETs/s).
- **Writes:** stateless front-ends, parallel fragment writes, multipart for big objects, fresh writes spread over empty drives.
- **Repair at several failures a day:** wide stripe spread and prioritised, throttled repair bandwidth.
- **1 trillion objects:** 500+ TB of metadata, so the routing table itself is partitioned and GC and scrubbing run per cell.

**Failure modes:**
- **Drive dies:** affected stripes decode from parity; repair restores redundancy in about an hour.
- **Server or rack dies:** up to 60 drives lost, but at most one fragment per stripe; parallel repair.
- **AZ lost:** metadata keeps a 2-of-3 Raft majority; stripes lose about 5 fragments, more than RS(10,4) tolerates, so meeting the "AZ plus one drive" target needs a wider code or cross-AZ layout; writes use degraded placement.
- **Partition leader dies:** new leader in 1-3 s; retriable errors; no committed write lost.
- **Hot partition:** 503 SlowDown for that range only, then a split.
- **Front-end crash after fragments, before commit:** object never visible; GC removes the orphans.
- **Bad deploy corrupting writes:** staged per cell; checksums catch it; versioning and GC grace allow recovery.

**Trade-offs chosen:**
- **RS(10,4) for bulk data, replication for small objects and metadata:** under half the disk cost; metadata needs low latency.
- **Range partitioning over hash:** sorted prefix LIST; heat handled by splits.
- **Strong over eventual consistency:** apps can treat it as a source of truth; the witness keeps caching.
- **Ack after metadata commit:** never ack data that is not reachable.
- **Async GC with grace over synchronous delete:** fast DELETE, no races with readers.
- **Async, opt-in cross-region replication:** sync would add 50-150 ms per PUT.

**What to measure:** latency p50/p99 and errors per operation, 503 SlowDown per partition and hot-partition count, stripes by remaining redundancy (14 down to 10) and repair backlog age (page if any stripe sits at minimum redundancy over 1 hour), drive failures per day by model and batch, scrub coverage and checksum errors, witness check latency, garbage and incomplete multipart bytes, Raft elections and commit latency.

## Page 5. Say it in the interview

> "I am designing an S3-style service: PUT, ranged GET, DELETE, LIST by prefix, multipart and versioning, about 100 petabytes and 100 billion objects in a region, a million requests a second, eleven nines durability and strong read-after-write. One server with files and a key table fails on durability and index scale, so I split it into two systems. The data plane chunks objects and erasure-codes each stripe into 10 data plus 4 parity fragments across three AZs: 1.4x storage instead of 3x, surviving four lost fragments. The metadata plane is a range-partitioned, Raft-replicated index from bucket and key to version and chunk locations. A PUT writes fragments, commits metadata, then acks; that commit makes reads consistent. Hot key ranges split automatically, and repair, scrubbing and GC run all the time."

**Key points to land:**
- Two systems: a consistent, range-partitioned index and an erasure-coded, self-healing data plane.
- RS(10,4): 1.4x overhead and 4 lost fragments tolerated, versus 3x replication.
- Fragments first, metadata last; the commit is the linearisation and ack point.
- Strong read-after-write with caches via a witness check; no multi-key transactions.
- The bottleneck is metadata heat; split by load; 503 SlowDown means back off.
- Durability is a model: failure rate, repair time, failure-domain spread.
- End-to-end checksums and scrubbing catch silent corruption.
- Deletes are metadata-only; GC with a grace period reclaims space.
- Multipart makes huge objects parallel, resumable parts committed atomically.
- Small objects are packed; large ones striped; metadata on Raft.

**Likely follow-ups:**
1. **How does versioning work?** Each PUT writes a time-ordered version id, inverted so newest sorts first; DELETE writes a delete marker; GET returns the newest non-marker.
2. **LIST on a bucket with 1 billion keys?** A range scan from the prefix, 1,000 keys from one or two partitions per page, seeking past common prefixes for the delimiter.
3. **Pre-signed URLs?** The SDK signs method, key, expiry and headers with HMAC (SigV4); the front-end recomputes it and re-checks current policy, so no server state.
4. **A cheaper archive tier?** Lifecycle moves old objects to denser media with wider codes; metadata keeps the key; GET needs a restore job first.
5. **Cross-region replication?** A service consumes the change log, copies new versions asynchronously with the same version ids, and tracks lag.

**Director layer:**
- **Cost drivers:** about 9,000 dense HDDs and 150-200 servers, about one new server a day, 150 TB of SSD for metadata, cross-AZ repair bandwidth.
- **Phasing:** core PUT, GET and LIST first, then multipart, versioning and lifecycle, then archive and cross-region; success is 80% of NFS and HDFS data migrated in 12 months.
- **Team ownership:** front-end and API, metadata index, data plane and placement, durability (repair, scrub, GC), security and KMS, fleet operations.
- **Top risks:** silent corruption, correlated failures (power domain, bad drive batch, bad deploy), metadata bugs making data unreachable, hot prefixes throttling big tenants, accidental customer deletes.
