# Social News Feed (Facebook / Twitter / Instagram home timeline): recall card

> **Hook:** Post with Snowflake ID → Push IDs to normal followers → Pull celebrity lists at read → Rank in 50 ms → Hydrate from cache → Degrade to chronological

**P · Problem:** It's really a read-heavy merge problem: decide where to pay the cost of merging hundreds of followed accounts into one list.

**N · Numbers:**
1. About 175K feed reads/s at peak, so a feed load must be a cache lookup, not a query.
2. 1.2K posts/s x 200 followers = 240K timeline inserts/s, so writes are amplified 200x and a 100M-follower celebrity cannot be pushed.
3. 500M x 800 IDs x 32 B = about 12.8 TB, so timelines store IDs only, capped, skipping inactive users.

**H · Hard part:** Celebrity posts that would cause write storms, while every feed still loads in under 200 ms.

**B · Boxes:** `Post service → Kafka → Fan-out workers → Redis timeline → Feed service → Ranking`

Side path: `Feed service → Object cache` to hydrate posts, users and counts.

**D · Decisions:**
1. Hybrid fan-out over pure push or pull, because it bounds write amplification and keeps reads to one lookup plus a few lists.
2. IDs only in timelines over full posts, because it uses 50-100x less memory and one invalidation covers an edit.
3. Snapshot cursors over offset paging for ranked feeds, because page 2 never repeats page 1 as new posts arrive.

**F · Failures:**
1. Ranking times out or is down → serve first-pass or chronological order, marked degraded.
2. Timeline shard lost → users rebuild by pull from author indexes under a global rebuild limiter.

**C · Close:** "Reads dominate, so I precompute timelines. But one celebrity post could mean 100 million cache writes, so I push post IDs into active followers' Redis timelines for normal authors and pull celebrity posts at read time. Fan-out workers consume an outbox event. The feed service merges, filters, hydrates from caches, ranks with a two-stage model in 50 milliseconds and paginates with a snapshot cursor. If anything fails, we degrade to chronological, never a blank screen."

**Quiz yourself:**
1. Where is the push/pull cut-off? → Promote at 100K followers, demote at 80K.
2. How does a delete vanish at once? → A tombstone checked on every read; cleanup is lazy.
3. What does a Snowflake ID give you? → Sort key, merge key and cursor in one.
