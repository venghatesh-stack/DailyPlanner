# Autocomplete (search typeahead suggestions): recall card

> **Hook:** Aggregate query logs daily → Store top 10 in every trie node → Replicate in memory → Cache at CDN → Merge trending deltas

**P · Problem:** It's really a precomputed top-k lookup by prefix under a keystroke-level latency budget.

**N · Numbers:**
1. About 116K QPS average and 400K at peak, so no database on the hot path.
2. The trie is about 10-12 GB, so it fits in RAM and we replicate rather than shard.
3. CDN and client caches absorb about 50%, so origin peaks near 200K QPS.

**H · Hard part:** Answering every keystroke in under 20 ms on the server while staying fresh for trending queries and safe from offensive ones.

**B · Boxes:** `Client → CDN edge cache → Suggest API → Suggest Nodes (in-memory trie)`

Side path: `Kafka logs → Data lake → Spark Trie Builder → Object store snapshots`, plus Flink trending deltas.

**D · Decisions:**
1. Precompute over query-time ranking, because lookups stay constant time at 400K QPS.
2. Daily base plus streaming delta over full real-time, because only a few thousand prefixes need minute freshness.
3. Full replication over sharding, because 10 GB fits in memory and needs no routing.

**F · Failures:**
1. Bad snapshot → validation blocks it; if it slips, canary metrics trigger rollback.
2. Total outage → the client hides the dropdown and search still works.

**C · Close:** "Every keystroke is a request, so about 400 thousand QPS at peak and nothing on the hot path touches a database. I precompute the top 10 per prefix offline from decayed distinct-user counts, build a 10 GB trie snapshot, and load it into memory on replicated nodes, with short prefixes cached at the CDN. A streaming job adds trending, merged at read time. Failures degrade to fewer suggestions, never a broken search box."

**Quiz yourself:**
1. Why count distinct users, not raw searches? → It resists bots, and a 50-user threshold keeps private queries out.
2. What stops a late reply for "ip" overwriting "iph"? → Client sequence numbers plus cancelling stale calls.
3. Why keep personalized responses private? → So the CDN never stores someone's history.
