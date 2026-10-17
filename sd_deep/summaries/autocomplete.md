# Design Autocomplete (search typeahead suggestions): the 5-page summary

Autocomplete answers on every keystroke, so it has about 100 ms end to end and under 20 ms on the server, at several times the QPS of search. The key idea: precompute top-k suggestions per prefix offline, serve them from an in-memory trie cached at the edge, and blend in a small real-time trending layer.

## Page 1. The problem, scope and numbers

**Pitch:** show the 10 best query completions within 100 ms of a keystroke, so users type less, make fewer typos, hit fewer zero-result pages and reach queries that convert.

**Who uses it:** mobile shoppers on slow networks ("redm" should find "redmi note 13 pro"), returning users (own recent searches first), Hindi and Hinglish users, relevance engineers running ranking experiments.

**In scope:**
- **Prefix match:** up to 10 ranked suggestions, on full query and word starts ("pro max").
- **Fuzzy:** edit distance 1 on the last token for prefixes of 4+ characters.
- **Blending:** personal history, trending and global suggestions with configurable weights.
- **Localization:** by language and region, including transliterated input.
- **Safety:** blocklist and policy classifier before returning; users can delete history.
- **Logging:** impressions and selections, for metrics and the next build.

**Out of scope:** the search results page, voice input, full-sentence correction, ads in suggestions.

**Non-functional targets:**
- **Latency:** server p99 under 20 ms; client p99 under 100 ms including network.
- **Availability:** 99.9%; failure degrades silently and never blocks search.
- **Throughput:** 100K QPS average, 350K QPS peak.
- **Freshness:** base daily; trending and blocklist under 15 minutes.
- **Consistency:** eventual; replicas may differ for minutes during a rollout.
- **Privacy:** a query becomes a global suggestion only after 50+ distinct users.

**Capacity math (200M DAU, 10 searches each, 5 requests per search after debounce):**
- **Requests:** 2B x 5 = 10B/day / 86,400 = about 116K QPS, about 400K at 3.5x peak. So no database on the hot path.
- **Caching:** CDN and client caches for prefixes up to 3 characters absorb about 50%, so origin peaks near 200K QPS.
- **Nodes:** about 20K QPS each (50 us CPU per lookup), so about 10 per replica set; 60-80 across 3 regions.
- **Trie size:** 20M surviving queries share prefixes into about 150M nodes; top 10 ids x 4 B = 6 GB plus 4 GB overhead, about 10-12 GB with strings. It fits in RAM, so replicate rather than shard.
- **Logs:** 2B x 100 B = 200 GB/day into the lake. So the heavy work is offline aggregation.
- **Bandwidth:** 400K x 1 KB = 400 MB/s at peak, mostly from the CDN.

## Page 2. The architecture

```
 Client (debounce 60 ms, cancel, local cache, recent history)
    | GET /v1/suggest?q=ipho&lang=en&region=IN
    v
 CDN edge cache (public responses, short prefixes, TTL 5-15 min)
    | miss
    v
 Suggest API (stateless) -> User history (Redis + Cassandra)
    | blend + filter       -> Policy / blocklist (in-memory copy)
    v
 Suggest Nodes: in-memory trie snapshot vN + trending delta map
    ^ load snapshot                          ^ push every 1 min
 Object store (versioned snapshots)       Flink (sliding-window counts)
    ^                                        ^
 Trie Builder (Spark, daily) <- Data lake <- Kafka (query + select logs)
```

- **Client SDK:** debounce, cancel stale calls, cache per prefix, log selections.
- **CDN edge:** caches public responses by prefix, language and region.
- **Suggest API:** normalize, merge base, trending and personal, filter, return 10.
- **Suggest Nodes:** read-only trie snapshot in memory; swap versions atomically.
- **Kafka logging:** async, fire-and-forget query, impression and selection events.
- **Trie Builder (Spark):** daily decay, thresholds, filtering, scoring, trie build.
- **Trending (Flink):** sliding-window counts, spikes against baseline, delta map.
- **Policy service:** blocklist and classifier, pushed to nodes within minutes.
- **Snapshot registry:** versions, validation, canary and rollback pointer.

**Flow A: keystroke to suggestions**
1. Shreya types "ipho"; after 60 ms idle the client cancels older calls and sends the request.
2. CDN misses on "ipho|en|IN"; the API normalizes (lowercase, NFKC) and calls a node with a 10 ms timeout.
3. The node walks 4 characters, reads the stored top 10 and merges trending deltas for "ipho".
4. The API adds personal matches, removes blocked items, dedupes and returns 10; the client logs impressions.

**Flow B: daily rebuild and rollout**
1. Spark reads 30 days of logs, removes bots and PII, counts distinct users with 7-day half-life decay.
2. Drop queries under 50 users, build per-language tries, upload with version and checksum.
3. Validate against a golden set; canary on 5% of nodes for 30 minutes; then all nodes swap.

## Page 3. The core deep dives

### 1. The top-k annotated trie
A trie is a tree where each edge is a character, so all queries sharing "iph" share a path. Searching the subtree on every keystroke is too slow, so the build stores the answer in each node. Insert every query with its score, then walk post-order: each node keeps the best 10 among its own query and its children's top-10 lists. A lookup is then O(prefix length): walk 4 edges for "ipho" and read 10 ids. Build cost is O(total characters x k log k), paid offline. Snapshots are compact arrays, memory-mapped, about 10 GB per language set, with lookups in tens of microseconds.

### 2. Scoring: decay and distinct users
Score favours queries that many different users issued recently and that led to clicks or purchases. An event of age t is weighted 0.5^(t/H) with half-life H = 7 days, so a query from 14 days ago counts a quarter. Counting distinct users, not raw searches, resists bots: a farm repeating one query a million times is still a few users. The 50-user threshold also stops private queries (a phone number) from ever surfacing.

### 3. Freshness: batch base plus streaming trending
A daily build cannot catch a phone launch at 10 am. Flink counts queries in 5-minute tumbling windows into a 15-minute sliding view and compares with the same hour last week. A query with a high z-score and 200+ distinct users (counted with HyperLogLog, a small probabilistic distinct counter) becomes trending. Flink pushes a small delta map, prefix -> (query, boost), every minute; entries expire after 2 hours. Nodes merge it with the base top 10 at read time. Only a few thousand prefixes need minute-level freshness, so this is cheap.

### 4. Caching and the client
The client debounces, cancels in-flight calls, and tags requests with sequence numbers so a late reply for "ip" never overwrites "iph". It keeps 200 prefixes and filters cached results locally while waiting. Global responses are public (max-age 300); personalized ones are private, so the CDN never stores someone's history.

**Data model:**
- **Query log event** (Kafka -> lake, by date/hour): key user_hash; query, lang, region, source; 30 days.
- **Query stats** (lake table): key (lang, region, query); decayed distinct users, CTR, conversion.
- **Trie snapshot** (object store, memory-mapped): snapshots/{lang}/{version}/{shard}.bin, checksum.
- **Trending delta** (memory on nodes): key prefix; entries with boost and expires_at.
- **User history** (Redis plus Cassandra): partition by user_id; last 50 queries, 90-day TTL.

**Key APIs:**
- `GET /v1/suggest`: public cache when not personalized, private otherwise; ETag is the snapshot version.
- `POST /v1/suggest/events`: batched; 100% of selections, 10% of impressions.
- `DELETE /v1/users/me/history/{query_hash}`: removes history; client clears its cache.
- `POST /v1/admin/blocklist`: audited; reaches nodes within 1-5 minutes.
- `POST /internal/snapshots/{version}/activate`: canary and rollback.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Request rate:** CDN and client caches take short prefixes; nodes serve from memory, no disk.
- **Hot prefixes ("iph" at 10x in a launch):** CDN, an in-process LRU of 100K hot prefixes per node, more replicas, autoscaled API.
- **Writes:** none on the hot path; logging is async and aggregation is batch plus stream.
- **Data growth:** range-shard a very large language only if it stops fitting in memory.

**Failure modes:**
- **Node crash:** the load balancer drops it; replicas serve; the snapshot is safe in object storage.
- **Bad snapshot:** validation blocks it; if it slips, canary metrics (acceptance, empty-response rate) trigger rollback.
- **Trending pipeline down:** nodes keep deltas until expiry, then serve base only.
- **History store slow:** 5 ms timeout, skip personalization, return global suggestions.
- **Kafka backlog:** bounded buffers drop some events; aggregation uses what arrives.
- **Region outage:** GeoDNS sends users elsewhere; the CDN still serves cached prefixes.
- **Total outage:** the client hides the dropdown; search still works.
- **Offensive suggestion goes viral:** emergency read-time blocklist rule within minutes; next build excludes it.

**Trade-offs chosen:**
- **Precompute over query-time ranking:** constant-time lookups at 400K QPS; cost moves offline.
- **Daily base plus streaming delta over full real-time:** cheap and robust; few prefixes need it.
- **Personalize on device or as a private layer:** keeps global responses CDN-cacheable.
- **Custom in-memory service over Elasticsearch completion:** lower latency, exact blend control, cheaper here.
- **Full replication over sharding:** 10 GB fits in memory, so no routing.
- **Decayed distinct users over ML first:** explainable; ML in phase 2.

**What to measure:** acceptance rate and selected position, keystrokes saved, client and server p99, timeout and empty rates, CDN hit ratio and origin QPS, snapshot and delta age, build failures, offensive reports per million impressions.

## Page 5. Say it in the interview

> "Scope: query autocomplete for 200 million daily users, top 10 suggestions by popularity and recency, client p99 under 100 ms, a day of freshness for the long tail and minutes for trending. Every keystroke is a request, so about 116 thousand QPS average and 400 thousand at peak, and nothing on the hot path can touch a database. I precompute top-k suggestions per prefix offline from query logs, build trie snapshots of about 10 GB, and load them into memory on replicated suggest nodes, with short prefixes cached at the CDN. A streaming job adds a trending layer merged at read time, and the client debounces, cancels and caches. Failures degrade to base suggestions or none, never a broken search box. I would measure acceptance rate, keystrokes saved, latency and freshness."

**Key points to land:**
- Every keystroke is a request: about 116K QPS average, 400K peak; no DB on the hot path.
- Precompute top-k per prefix; lookup is O(prefix length).
- The snapshot is about 10 GB, so scale by replication.
- Daily batch base plus streaming trending, merged at read time.
- Cache at client, CDN and node; keep global responses public.
- Debounce, cancellation and sequence numbers cut load and flicker.
- Distinct-user thresholds and HyperLogLog for privacy and anti-manipulation.
- Read-time blocklist for takedowns in minutes.
- Degrade silently: no suggestions beats a broken search box.
- Measure acceptance and keystrokes saved, not only latency.

**Likely follow-ups:**
1. **Typos in the prefix?** For 4+ characters, a bounded edit-distance-1 walk with a Levenshtein automaton, or misspelling aliases mined from queries users rewrote.
2. **Mid-word matches like "pro max"?** Also index each query by its word starts, at lower weight, mapping "pro max" to "iphone 15 pro max".
3. **Adding ML ranking?** Take the top 50 from the trie, rank with gradient boosted trees on popularity, CTR, conversion and history, under 5 ms.
4. **Merchandising campaigns?** A separate curated boost table merged at read time with caps, expiry and policy review.
5. **Several languages in one box?** Detect script per keystroke, query that language's trie plus transliteration aliases, blend by user preference.

**Director layer:**
- **Cost drivers:** 60-80 serving nodes, CDN bandwidth (400 MB/s peak), and daily Spark over 200 GB of logs.
- **Phasing:** decayed-popularity trie and trending first; ML ranking and entity suggestions in phase 2.
- **Team ownership:** search relevance (scoring, experiments), data platform (Kafka, Spark, Flink), serving, trust and safety (blocklist).
- **Top risks:** offensive suggestions, bot manipulation, private query leaks, and a bad snapshot shipped to everyone.
