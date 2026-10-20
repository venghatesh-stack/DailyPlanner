# Instagram-style image sharing: recall card

> **Hook:** Presigned upload → Object store → Kafka resize workers → Content-addressed URLs → CDN → Hybrid fan-out feed

**P · Problem:** It's really an egress problem: a read-heavy media pipeline glued to a social graph.

**N · Numbers:**
1. 50B image views/day x 60 KB = 3 PB/day, so the CDN hit ratio is the number we protect.
2. 230 TB/day of new storage is about 118 PB/year of disk, so erasure code and tier originals to cold storage after 90 days.
3. 100M posts x 200 followers = 20B timeline inserts/day, so cap celebrity fan-out.

**H · Hard part:** Delivering petabytes of images cheaply and fast, while celebrity posts do not explode fan-out writes.

**B · Boxes:** `Client → Presigned URL → Object store → Kafka → Resize workers → CDN`

Side path: `Post service → outbox → Fan-out workers → Redis timelines` for the feed.

**D · Decisions:**
1. Presigned direct upload over proxying bytes, because the app tier scales with metadata, not megabytes.
2. Hybrid fan-out at 10k followers over pure push or pull, because most reads stay fast and celebrity writes stay bounded.
3. AVIF with fallbacks over plain JPEG, because encode CPU is paid once and egress savings come on every view.

**F · Failures:**
1. Resize backlog → posts still publish; the image proxy resizes on demand; autoscale on Kafka lag.
2. CDN outage in a region → multi-CDN DNS steering shifts traffic in minutes; the origin shield is sized for 2x misses.

**C · Close:** "Views outnumber uploads 500 to 1, so this is a delivery problem first. Clients upload straight to object storage, and workers make four variants under content-addressed keys, so URLs are immutable and cached for a year. Metadata is sharded by user with time-sortable IDs. Feeds push to Redis timelines for normal authors and pull for celebrities. Egress is about 3 petabytes a day, so I live by CDN hit ratio."

**Quiz yourself:**
1. Why content-addressed URLs? → Content never changes under a URL, so no routine invalidation.
2. Celebrity with 50M followers posts? → One write to their recent list; followers pull it at read time.
3. New 2160 px variant? → Serve it from the on-the-fly resizer; don't reprocess the archive.
