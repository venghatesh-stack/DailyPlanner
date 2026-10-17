# Design a deduplication system for similar content (near-duplicate detection): the 5-page summary

Exact duplicates are easy: hash the bytes. The hard part is near-duplicates (a listing with one word changed, a re-uploaded photo with a watermark) across 2 billion items, where comparing against everything is impossible. The single most important idea: compute similarity-preserving sketches, use locality-sensitive hashing to fetch about 30 candidates in a few dozen lookups, then verify those precisely and group duplicates into clusters with one canonical item.

## Page 1. The problem, scope and numbers

**Pitch:** detect exact and near-duplicate marketplace listings at upload in under 200 ms, group them into clusters so search shows one product with seller offers underneath, and never block a seller when dedup is down.

**Who uses it:** sellers (told "this product exists, add your offer"), catalog quality analysts (review grey-zone pairs side by side), search engineers (stable cluster_id and canonical_id to collapse results), trust and safety (spam-ring signals).

**In scope:**
- **Exact dedup:** SHA-256 of normalised text plus image byte hash.
- **Near-duplicates:** MinHash LSH and SimHash for text; perceptual hash (pHash, Hamming 8 or less of 64) and embeddings for images.
- **Verification:** exact similarity plus attribute guard rules (model number, size, colour, pack size).
- **Clustering:** union-find with a canonical item chosen by quality score.
- **Three paths:** sync check at upload, async re-check on edits, nightly batch re-clustering; human review for the grey zone.

**Out of scope:** counterfeit and legal takedown decisions, video and audio fingerprinting, review dedup, the external web.

**Non-functional targets:**
- **Latency:** sync check p50 under 60 ms, p99 under 200 ms.
- **Quality:** auto-merge precision 99% or more; recall 90% or more at Jaccard 0.8 or above.
- **Availability:** 99.9%, and fail open on timeout so uploads never block.
- **Freshness:** a new item is findable as a candidate within 60 s.
- **Stability:** under 1% of cluster ids change per day outside real merges and splits.

**Capacity math (2B items, 50M new or edited per day, 5x peak):**
- **Checks:** 50M / 86,400 = about 580/s, about 2,900/s at peak. So the online path must be a few lookups, not a scan.
- **Band lookups:** 2,900 x 32 bands = about 93k KV point reads/s. So the band index is a sharded SSD key-value store.
- **MinHash signatures:** 2B x 512 B (128 x 32-bit) = about 1 TB. So store them once and verify from signatures, not raw text.
- **Indexes:** bands 2B x 32 x 12 B = about 770 GB on about 16 KV nodes; embeddings 2B x 256 B = 512 GB, about 1.3 TB with the HNSW graph, on about 20 nodes.
- **Verification:** 30 candidates x about 20 microseconds = under 1 ms CPU per check. So precision is cheap once candidates are few.
- **Nightly batch:** 10-20B candidate pairs, a few hours on about 500 Spark cores.

## Page 2. The architecture

```
 Seller upload / edit
      |
 Listing service --sync check, 200 ms budget, fail open--> Dedup API
      |                                                       |
      |   Feature extractor: normalise, shingle, SHA-256, MinHash,
      |                      SimHash, pHash, embedding
      |                                                       |
      |        Exact-hash KV | LSH band index | SimHash tables | ANN (HNSW)
      |                         \ candidates (cap 100) /
      |              Verifier: Jaccard, Hamming, cosine, attribute guards
      |                 |                  |                  |
      |             duplicate          grey zone            unique
      |                 v                  v                  v
      |          Cluster store        Review queue     index sketches
      v                 v
 listing.changes (async)  dedup.decisions -> Catalog, Search; nightly Spark
```

- **Dedup API:** sync check with a 200 ms budget; returns decision and evidence; fails open.
- **Feature extractor:** Unicode normalisation, boilerplate stripping, shingles and all sketches.
- **Exact-hash KV:** content hash to item ids; the cheap first check.
- **LSH band index:** (band_no, band_hash) to item ids; 32 bands of 4 rows, capped buckets.
- **SimHash tables:** 4 tables keyed by 16-bit blocks for Hamming 3 or less.
- **ANN index:** HNSW vectors per category for paraphrases, crops, other languages.
- **Verifier:** exact similarity, guard rules and a calibrated classifier giving a probability.
- **Cluster store:** union-find, canonical choice, stable ids, merge history for appeals.
- **Review queue and nightly Spark:** human labels for calibration; full-corpus repair of drift.

**Flow A: sync check at upload**
1. Listing service posts title, description, attributes and image URLs.
2. Extractor builds 5-word shingles, MinHash-128, SimHash-64, a 256 px thumbnail pHash, an embedding (20 ms on GPU).
3. In parallel: exact lookup, 32 band lookups, 4 SimHash lookups, ANN top-20; union capped at 100.
4. Verify: probability 0.97 or more is a duplicate; 0.80-0.97 grey zone (accept, queue review); else unique.
5. Reply in about 60 ms; then insert the sketches into all indexes asynchronously.

**Flow B: edit**
1. listing.changes event; recompute sketches, replace band entries if they changed.
2. Re-verify; the item may move cluster; a canonical change tells search to re-collapse.

## Page 3. The core deep dives

### 1. MinHash plus LSH banding: 2B items to about 30 candidates
Text becomes a set of 5-word shingles (character 4-grams for short titles). Near-duplicate means Jaccard similarity of 0.8 or more. MinHash: for a random hash function, the chance two sets share the same minimum hash equals their Jaccard similarity, so with 128 functions the fraction of matching slots estimates Jaccard (standard error about 0.04). LSH splits the 128 values into 32 bands of 4; two items become candidates if any whole band matches. The chance is 1 - (1 - s^4)^32, an S-curve with its threshold near (1/32)^(1/4) = 0.42: about 1.0 at s = 0.8, 0.87 at 0.5, 0.23 at 0.3. So recall is near total at 0.8 and verification removes the false positives.

### 2. SimHash with pigeonhole tables
SimHash makes a 64-bit fingerprint; each bit is the sign of a weighted sum of token hash bits, so similar texts differ in few bits. To find all fingerprints within Hamming distance 3, split them into 4 blocks of 16 bits: by pigeonhole, at least one block matches exactly. Store 4 tables keyed by block, look up all 4, check candidates exactly. Only 8 bytes per item.

### 3. Precision: guards, chaining and three zones
"Running shoe size 8" and "size 9" have Jaccard 0.95 but are different products, so differing size, colour, model number or pack quantity blocks an auto-merge and marks them as variants. Transitive chaining is the other trap: A~B at 0.85 and B~C at 0.85, but A vs C is 0.6. So merges verify against the canonical item, cap cluster diameter and honour cannot-link labels from human reviewers. Clusters are union-find (path compression, union by size, nearly O(1)).

### 4. Boilerplate and adversaries
"Free shipping, 100% original" collides everywhere, creating giant buckets. Strip known boilerplate, IDF-weight shingles, ignore buckets over 10k items. Adversaries use homoglyphs and zero-width characters: NFKC and confusables mapping remove them, and image pHash still matches.

**Data model:**
- **ItemSignature** (ScyllaDB): partition item_id; SHA-256, MinHash blob, SimHash, pHash, guard attributes; about 1 TB.
- **LSHBucket** (ScyllaDB wide rows): partition (band_no, band_hash), clustering item_id; capped at 10k.
- **SimHashBlock**: partition (table_no, block16) to item_id and simhash.
- **Cluster** (Postgres sharded by cluster_id): canonical_id, members, cannot-link pairs; item_to_cluster keyed by item_id.
- **ExactHash** (Redis backed by ScyllaDB): content_sha256 to item_ids.

**Key APIs:**
- `POST /v1/dedup/check`: 200 ms budget; decision=unknown on timeout (fail open).
- `GET /v1/clusters/{cluster_id}`: for catalog and analysts.
- `POST /v1/clusters/{cluster_id}/split`: appeals; adds a cannot-link constraint.
- `POST /v1/review/{pair_id}/label`: feeds calibration; not_dup writes a cannot-link edge.
- `Kafka dedup.decisions`: keyed by cluster_id for cluster views.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Hot LSH buckets:** boilerplate stripping, IDF weighting, bucket caps, drop a band whose bucket exceeds 10k ids.
- **Reads:** the band index is a sharded KV; 32 parallel point lookups per check; cache recent signatures.
- **Writes:** band inserts are append-only and async after the decision; the nightly rebuild compacts lists.
- **ANN:** sharded by category so a query touches one shard.
- **Huge clusters (a phone charger with 500k members):** membership in a separate paginated table, canonical id cached.

**Failure modes:**
- **Dedup times out at upload:** the listing goes live as "pending dedup"; the async path clusters it within a minute.
- **Slow band partition:** 30 ms per-lookup timeout, skip that band, slightly lower recall for that request.
- **Embedding server down:** use MinHash, SimHash and pHash only; mark text-only and re-check later.
- **Bad threshold deploy causing mass merges:** merges-per-hour limits per category trip a breaker; merges are reversible from history.
- **Nightly batch fails:** online clusters stay authoritative; the job restarts from checkpoints; no partial diff applied.
- **Concurrent near-identical uploads:** both pass as unique; the async re-check or the nightly batch merges them.

**Trade-offs chosen:**
- **Several sketches over one:** MinHash gives calibrated Jaccard, SimHash is tiny, embeddings catch paraphrases and Hindi-English pairs.
- **b=32, r=4:** threshold about 0.42 gives near-total recall at 0.8 with manageable candidates.
- **Sync plus async plus batch over one path:** instant seller feedback, edits and races caught, drift repaired.
- **Merge into a cluster over blocking:** honest sellers keep selling via offers; block only high-confidence spam.
- **Fail open over fail closed:** listing revenue outweighs temporary duplicates the later paths clean up.
- **Union-find over correlation clustering:** near-linear and incremental; the better-quality method is too expensive.

**What to measure:** weekly precision on 2,000 labelled pairs per category, recall on planted duplicates per perturbation type, check p50/p99 and fail-open rate, candidates per check, bucket size (max, p99), grey-zone backlog, merges and splits per hour, appeal overturn rate (under 0.5%), duplicates on the first search page (target -70%).

## Page 5. Say it in the interview

> "First I define duplicate: exact means byte-identical; near means Jaccard above 0.8 on 5-word shingles; semantic means the same product described differently. Assume 2 billion items, 50 million new or edited a day, a 200 ms check at upload, and a strong preference for precision, because a wrong merge hides a real seller. Hashing catches exact copies but not a one-word edit, and comparing every pair is impossible. So I compute sketches, MinHash and SimHash for text, perceptual hashes and embeddings for images, and use locality-sensitive hashing to turn a check into 32 bucket lookups returning about 30 candidates. I verify those exactly with attribute guards like size and model number, and union-find groups duplicates under a canonical item. The check fails open; async and nightly jobs repair the rest."

**Key points to land:**
- Define duplicate tiers first: exact, near, semantic; each needs a different technique.
- All-pairs comparison is impossible at 2B items; exact hashes miss one-word edits.
- MinHash estimates Jaccard; LSH gives about 30 candidates in 32 lookups.
- SimHash with pigeonhole block tables: Hamming search in 8 bytes per item.
- Attribute guards stop merging variants; cannot-link labels stop chaining.
- Union-find clusters with a sticky canonical and stable ids feed search.
- Three zones: auto-merge at 0.97, human review from 0.80, else unique.
- Fail open at upload; async and nightly batch repair races and drift.
- Precision from labelled samples, recall from planted duplicates.

**Likely follow-ups:**
1. **Why not compare against the whole category?** Tens of millions of items at microseconds each is tens of seconds per check; LSH cuts it to about 30.
2. **Web crawl at 10B pages?** 64-bit SimHash with Hamming 3 and permuted tables, after stripping navigation and ads; batch in Spark, online lookups only for fresh pages.
3. **Images only?** pHash and dHash with the same block tables, CLIP embeddings for crops and watermarks, keypoint matching for borderline pairs.
4. **An item keeps flipping clusters on edits?** Hysteresis: a higher score to move than to stay, sticky canonicals, rate-limited moves.
5. **A spam ring cloning listings?** Look at the graph: many near-duplicate edges from new sellers to the same popular listings, shared images; feed trust and safety.

**Director layer:**
- **Cost drivers:** about 3 TB of sharded indexes (bands, signatures, vectors), GPU embedding serving, nightly 500-core Spark, and the human review team.
- **Phasing:** a small startup runs MinHash LSH in memory with nightly recompute; add SimHash, images, ANN and the review loop as volume and paraphrase abuse grow.
- **Team ownership:** dedup platform (sketches, indexes, verifier), catalog (clusters, canonicals), search (collapsing), trust and safety, a labelling operations team.
- **Top risks:** false merges of variants, adversarial evasion, boilerplate latency spikes, threshold changes churning search.
