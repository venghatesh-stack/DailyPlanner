-- 5-day system design bootcamp: 30 study blocks, 21-25 Oct 2026, 14 h/day.
-- Paste into the Supabase SQL editor and run. Safe to run twice (no duplicates).
-- Then open Planner and tap 'Sync to Google' to send the blocks to Google Calendar.
with me as (select id::text as uid from users where email = 'venghatesh@gmail.com'),
plan(plan_date, start_time, end_time, title, description) as (values
  ('2026-10-21', '06:00', '08:00', '📚 Framework + how to talk through a design', 'Day 1 - Foundations, caching and core building blocks

Read ''System design: what to say, step by step'' (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases) and say every line out loud once.
Read ''System design in 5 pages'' (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-summary).
Then the Concepts tab in Interview Prep -> System design: caching, consistency (CAP), partitioning, replication.'),
  ('2026-10-21', '08:30', '10:45', '📚 URL shortener + Unique ID generator', 'Day 1 - Foundations, caching and core building blocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a URL Shortener (TinyURL / Bitly): https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary
- Design a Distributed Unique ID Generator (Snowflake): https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/summary'),
  ('2026-10-21', '11:00', '13:15', '📚 API rate limiter + Distributed cache', 'Day 1 - Foundations, caching and core building blocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design an API Gateway Rate Limiter: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/summary
- Design a Distributed Cache (Redis / Memcached cluster): https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/summary'),
  ('2026-10-21', '14:00', '16:15', '📚 Read-heavy cache, Cache invalidation, Hot keys', 'Day 1 - Foundations, caching and core building blocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a caching strategy for a read-heavy API (product catalog scale): https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/summary
- Design cache invalidation for frequently updated content: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/summary
- Design a counter service that avoids hot keys (likes, views, inventory-style counts): https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/summary'),
  ('2026-10-21', '16:30', '18:45', '📚 Distributed key-value store', 'Day 1 - Foundations, caching and core building blocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a Distributed Key-Value Store (Dynamo-style): https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/summary'),
  ('2026-10-21', '19:30', '22:30', '📚 Mock 1 (45 min): URL shortener + review', 'Day 1 - Foundations, caching and core building blocks

Set a 45-minute timer. Design a URL shortener from a blank page, out loud, following the ''What to say'' order: clarify, assume, requirements, numbers, hard parts, simple design, deep dive, failures, summary.
Then 30 min: compare with the summary and write down 3 gaps.
Last hour: recall today''s 8 designs on paper, one box diagram each, without looking.

Open:
- Design a URL Shortener (TinyURL / Bitly): https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary'),
  ('2026-10-22', '06:00', '08:00', '📚 Recall Day 1 + storage concepts', 'Day 2 - Storage, data modelling and search

From memory, draw the high-level design of the 8 Day 1 designs (10 min each), then check against the summaries.
Concepts tab: indexes, sharding keys, replication, consistency levels.'),
  ('2026-10-22', '08:30', '10:45', '📚 Object storage (S3) + File storage (Dropbox)', 'Day 2 - Storage, data modelling and search

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design an Object Storage Service (S3): https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/summary
- Design a file storage and sharing system (Dropbox / Google Drive): https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/summary'),
  ('2026-10-22', '11:00', '13:15', '📚 Partitioning, time-range queries, audit log', 'Day 2 - Storage, data modelling and search

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a partitioning strategy for a large events table: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/summary
- Design a time-range query store (time-series and event history): https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/summary
- Design an audit log and immutable history: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/summary'),
  ('2026-10-22', '14:00', '16:15', '📚 Autocomplete + E-commerce search', 'Day 2 - Storage, data modelling and search

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design Autocomplete (search typeahead suggestions): https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary
- Design E-commerce Catalog Search (product search): https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary'),
  ('2026-10-22', '16:30', '18:45', '📚 Web crawler + Geo search (nearby)', 'Day 2 - Storage, data modelling and search

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a Web Crawler (search-engine scale): https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/summary
- Design geo search for nearby locations (Yelp / Google Maps nearby): https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/summary'),
  ('2026-10-22', '19:30', '22:30', '📚 Mock 2 (45 min): Typeahead / search + review', 'Day 2 - Storage, data modelling and search

45-minute timed mock: ''Design search autocomplete for an e-commerce app''. Out loud, with numbers.
30 min review against the summaries.
Then recall today''s designs on paper.

Open:
- Design Autocomplete (search typeahead suggestions): https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary'),
  ('2026-10-23', '06:00', '08:00', '📚 Recall Day 2 + messaging concepts', 'Day 3 - Async, messaging and real time

From memory, draw Day 2''s designs, then check.
Concepts: queues vs streams, at-least-once vs exactly-once, ordering, idempotency keys, outbox pattern, sagas.'),
  ('2026-10-23', '08:30', '10:45', '📚 Distributed message queue (Kafka) + Idempotent processing', 'Day 3 - Async, messaging and real time

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a Distributed Message Queue (Kafka): https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/summary
- Design Exactly-Once-Like Processing Using Idempotency: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary'),
  ('2026-10-23', '11:00', '13:15', '📚 Job queue, Pub/sub notifications, Backpressure', 'Day 3 - Async, messaging and real time

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a Job Queue (background task processing): https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/summary
- Design a Pub-Sub System for Event Notifications: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/summary
- Design backpressure for a write-heavy pipeline: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/summary'),
  ('2026-10-23', '14:00', '16:15', '📚 Order workflow (saga) + Payment system', 'Day 3 - Async, messaging and real time

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design an event-driven order processing workflow (e-commerce): https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/summary
- Design a Payment System (e-commerce pay-in and pay-out): https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary'),
  ('2026-10-23', '16:30', '18:45', '📚 Messaging app, Presence, WebSocket scaling', 'Day 3 - Async, messaging and real time

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a Messaging App (WhatsApp / Messenger): https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary
- Design Presence for a Chat Application (online / away / last seen): https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary
- Design WebSocket scaling (live updates): https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/summary'),
  ('2026-10-23', '19:30', '22:30', '📚 Mock 3 (45 min): WhatsApp + review', 'Day 3 - Async, messaging and real time

45-minute timed mock: ''Design WhatsApp'' (1:1 and group chat, delivery receipts, presence).
30 min review.
Then recall today''s designs.

Open:
- Design a Messaging App (WhatsApp / Messenger): https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary'),
  ('2026-10-24', '06:00', '08:00', '📚 Recall Day 3 + product-design checklist', 'Day 4 - Classic product designs

From memory, draw Day 3''s designs, then check.
Write your own checklist for product designs: users and scale, read/write ratio, core entities, APIs, data stores, hot paths, failure modes.'),
  ('2026-10-24', '08:30', '10:45', '📚 Uber: matching, location updates, dispatch', 'Day 4 - Classic product designs

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design Uber (ride-hailing): https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
- Design Google Maps (routing, ETA and navigation): https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/summary'),
  ('2026-10-24', '11:00', '13:15', '📚 Food delivery (Swiggy) + News feed', 'Day 4 - Classic product designs

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design Swiggy / DoorDash-style food delivery ordering: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary
- Design a Social News Feed (Facebook / Twitter / Instagram home timeline): https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/summary'),
  ('2026-10-24', '14:00', '16:15', '📚 Fan-out, Ranked timeline, Notifications for feeds', 'Day 4 - Classic product designs

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design fanout for a follower graph: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/summary
- Design a ranked home timeline (ranking and freshness): https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/summary
- Design notifications for a feed action (like, comment, follow, mention): https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/summary'),
  ('2026-10-24', '16:30', '18:45', '📚 Video streaming, Media CDN, Image sharing', 'Day 4 - Classic product designs

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design Netflix / YouTube-style video streaming: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/summary
- Design a CDN strategy for media delivery (video, images, live events): https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/summary
- Design Instagram-style image sharing: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/summary'),
  ('2026-10-24', '19:30', '22:30', '📚 Mock 4 (45 min): Uber or Swiggy + review', 'Day 4 - Classic product designs

45-minute timed mock: ''Design Swiggy/Uber'' - pick the one you are weaker on.
30 min review.
Then recall today''s designs.

Open:
- Design Uber (ride-hailing): https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
- Design Swiggy / DoorDash-style food delivery ordering: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary'),
  ('2026-10-25', '06:00', '08:00', '📚 Recall the 5 weakest designs of the week', 'Day 5 - High-stakes systems, reliability and full mocks

Pick the 5 designs you marked as weakest (from your mock notes). Redraw each from memory and fix the gaps.'),
  ('2026-10-25', '08:30', '10:45', '📚 Flash sale + Ticket booking (contention, inventory)', 'Day 5 - High-stakes systems, reliability and full mocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a flash sale system (Big Billion Days style sale event): https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/summary
- Design a ticket booking system (Ticketmaster / BookMyShow): https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/summary'),
  ('2026-10-25', '11:00', '13:15', '📚 Leaderboard, Ad-click aggregation, Stock exchange', 'Day 5 - High-stakes systems, reliability and full mocks

How to study each design (about 45-60 min each):
1. Read its 5-page summary (15 min).
2. Open the full deep dive: requirements, numbers, data model, the hard parts (20-25 min).
3. Close everything. Draw it from memory and explain it OUT LOUD using the ''What to say'' script (15 min).
4. Answer its follow-up questions; note what you could not answer.
Work in 50 min on / 10 min off.

Open:
- Design a real-time gaming leaderboard: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/summary
- Design an ad click event aggregation system: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/summary
- Design a stock exchange (order matching engine): https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/summary'),
  ('2026-10-25', '14:00', '16:15', '📚 Reliability and security pack', 'Day 5 - High-stakes systems, reliability and full mocks

Faster pass, about 25 min each: summary + out-loud explanation of the key idea and one failure scenario.
How to study each design (about 45-60 min each):

Open:
- Design multi-region failover and disaster recovery: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/summary
- Design retries, timeouts and circuit breakers (resilient service client): https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/summary
- Design graceful degradation when a dependency fails: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/summary
- Design a canary deployment and rollback strategy: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/summary
- Design authentication and session management (web app login, tokens, sessions): https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/summary
- Design role-based access control (centralized authorization service): https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/summary'),
  ('2026-10-25', '16:30', '18:45', '📚 Mock 5 (60 min) + Mock 6 (45 min)', 'Day 5 - High-stakes systems, reliability and full mocks

Mock 5 (60 min): a design you have NOT studied this week, picked at random from Interview Prep -> System design.
Mock 6 (45 min): ''Design a payment system'' with failures and idempotency.
Review both.'),
  ('2026-10-25', '19:30', '22:30', '📚 Consolidate: cheat sheet and patterns', 'Day 5 - High-stakes systems, reliability and full mocks

Write a one-page cheat sheet: key numbers (QPS math, storage per day), the 10 patterns you used most (cache-aside, fan-out on write/read, sharding by key, outbox, saga, idempotency keys, leader election, consistent hashing, CDN, queues for spikes) and your top trade-offs.
Re-read ''What to say'' once. Stop by 22:30 and sleep.')
)
insert into daily_events (user_id, plan_date, start_time, end_time, title, description, priority, reminder_minutes, is_deleted)
select me.uid, p.plan_date::date, p.start_time, p.end_time, p.title, p.description, 'high', 5, false
from plan p cross join me
where not exists (select 1 from daily_events e where e.user_id = me.uid and e.plan_date = p.plan_date::date
                  and e.start_time = p.start_time and e.title = p.title and coalesce(e.is_deleted,false) = false);

-- To remove the whole plan later:
-- update daily_events set is_deleted = true where title like '📚 %' and plan_date between '2026-10-21' and '2026-10-25'
--   and user_id = (select id::text from users where email = 'venghatesh@gmail.com');
