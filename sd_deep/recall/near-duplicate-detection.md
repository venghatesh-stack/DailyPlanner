# deduplication system for similar content (near-duplicate detection): recall card

> **Hook:** Normalise and shingle → MinHash and SimHash sketches → LSH bands give 30 candidates → Verify with guards → Union-find cluster → Fail open

**P · Problem:** It's really a similarity search problem: find near-neighbours among 2 billion items without comparing against all of them.

**N · Numbers:**
1. About 2,900 checks/s at peak x 32 bands = about 93k point reads/s, so the band index is a sharded SSD key-value store.
2. 2B x 512 B MinHash signatures = about 1 TB, so store them once and verify from signatures, not raw text.
3. 30 candidates x about 20 microseconds = under 1 ms per check, so precision is cheap once candidates are few.

**H · Hard part:** Getting from 2B items to a few dozen candidates in one lookup round, then not merging variants like size 8 and size 9.

**B · Boxes:** `Listing service → Dedup API → Feature extractor → LSH, SimHash, ANN indexes → Verifier → Cluster store`

Side path: `listing.changes → async re-check` and a nightly Spark re-cluster.

**D · Decisions:**
1. Several sketches over one, because MinHash gives calibrated Jaccard, SimHash is tiny and embeddings catch paraphrases.
2. Fail open over fail closed, because listing revenue outweighs temporary duplicates that later paths clean up.
3. Union-find over correlation clustering, because it is near-linear and incremental.

**F · Failures:**
1. Dedup times out at upload → the listing goes live as "pending dedup"; the async path clusters it within a minute.
2. Bad threshold deploy causes mass merges → merges-per-hour limits trip a breaker; merges are reversible from history.

**C · Close:** "Hashing catches exact copies but not a one-word edit, and comparing every pair is impossible. So I compute sketches, MinHash and SimHash for text, perceptual hashes and embeddings for images, and LSH turns a check into 32 bucket lookups returning about 30 candidates. I verify those exactly with attribute guards like size and model number, and union-find groups duplicates under a canonical item. The check fails open; async and nightly jobs repair the rest."

**Quiz yourself:**
1. Why 32 bands of 4 rows? → Threshold near 0.42, so recall is near total at Jaccard 0.8.
2. How does SimHash find Hamming 3? → Four 16-bit block tables; by pigeonhole one block matches.
3. How do you stop chaining A~B~C? → Verify against the canonical and honour cannot-link labels.
