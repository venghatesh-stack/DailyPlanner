-- 5-day system design bootcamp with daily memory sessions: 30 blocks, 21-25 Oct 2026, 14 h/day.
-- Paste into the Supabase SQL editor and run. Safe to run again: if you ran the
-- earlier version, the existing blocks are updated in place, nothing is duplicated.
-- Then open Planner and tap 'Sync to Google' to send the blocks to Google Calendar.

drop table if exists _plan;
create temp table _plan(plan_date date, start_time text, end_time text, title text, description text);
insert into _plan values
  ('2026-10-21', '06:00', '08:00', '🧠 Memory session 1: palace for ''What to say'' + the card template', 'Day 1 - Foundations, caching and core building blocks

Interactive memory session 1 with Claude (90 min), then 30 min on your own.
Technique: memory palace (method of loci).
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 1'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: read ''What to say'' (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases) once aloud, then skim ''System design in 5 pages'' (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-summary).'),
  ('2026-10-21', '08:30', '10:45', '📚 URL shortener + Unique ID generator', 'Day 1 - Foundations, caching and core building blocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a URL Shortener (TinyURL / Bitly)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary
- Design a Distributed Unique ID Generator (Snowflake)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/summary'),
  ('2026-10-21', '11:00', '13:15', '📚 API rate limiter + Distributed cache', 'Day 1 - Foundations, caching and core building blocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design an API Gateway Rate Limiter
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/summary
- Design a Distributed Cache (Redis / Memcached cluster)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/summary'),
  ('2026-10-21', '14:00', '16:15', '📚 Read-heavy cache, Cache invalidation, Hot keys', 'Day 1 - Foundations, caching and core building blocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a caching strategy for a read-heavy API (product catalog scale)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/summary
- Design cache invalidation for frequently updated content
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/summary
- Design a counter service that avoids hot keys (likes, views, inventory-style counts)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/summary'),
  ('2026-10-21', '16:30', '18:45', '📚 Distributed key-value store', 'Day 1 - Foundations, caching and core building blocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a Distributed Key-Value Store (Dynamo-style)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/summary'),
  ('2026-10-21', '19:30', '22:30', '📚 Mock 1 (45 min): URL shortener + recall', 'Day 1 - Foundations, caching and core building blocks

45-minute timed mock: design a URL shortener from a blank page, out loud, following ''What to say''.
Then 30 min: compare with the summary and write down 3 gaps.
Then 45 min: recall today''s hooks on paper without looking, then say 3 full cards aloud. Today''s cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store
Stop at 22:30 and sleep: sleep is when today''s learning is stored.

Open:
- Design a URL Shortener (TinyURL / Bitly)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary'),
  ('2026-10-22', '06:00', '08:00', '🧠 Memory session 2: active recall + numbers', 'Day 2 - Storage, data modelling and search

Interactive memory session 2 with Claude (90 min), then 30 min on your own.
Technique: active recall with green/amber/red piles, and anchoring numbers to consequences.
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 2'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: Concepts tab in Interview Prep: indexes, sharding keys, replication, consistency levels.'),
  ('2026-10-22', '08:30', '10:45', '📚 Object storage (S3) + File storage (Dropbox)', 'Day 2 - Storage, data modelling and search

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design an Object Storage Service (S3)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/summary
- Design a file storage and sharing system (Dropbox / Google Drive)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/summary'),
  ('2026-10-22', '11:00', '13:15', '📚 Partitioning, time-range queries, audit log', 'Day 2 - Storage, data modelling and search

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a partitioning strategy for a large events table
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/summary
- Design a time-range query store (time-series and event history)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/summary
- Design an audit log and immutable history
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/summary'),
  ('2026-10-22', '14:00', '16:15', '📚 Autocomplete + E-commerce search', 'Day 2 - Storage, data modelling and search

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design Autocomplete (search typeahead suggestions)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary
- Design E-commerce Catalog Search (product search)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary'),
  ('2026-10-22', '16:30', '18:45', '📚 Web crawler + Geo search (nearby)', 'Day 2 - Storage, data modelling and search

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a Web Crawler (search-engine scale)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/summary
- Design geo search for nearby locations (Yelp / Google Maps nearby)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/summary'),
  ('2026-10-22', '19:30', '22:30', '📚 Mock 2 (45 min): Typeahead / search + recall', 'Day 2 - Storage, data modelling and search

45-minute timed mock: ''Design search autocomplete for an e-commerce app'', out loud, with numbers.
Then 30 min: compare with the summary and write down 3 gaps.
Then 45 min: recall today''s hooks on paper without looking, then say 3 full cards aloud. Today''s cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby
Stop at 22:30 and sleep: sleep is when today''s learning is stored.

Open:
- Design Autocomplete (search typeahead suggestions)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary'),
  ('2026-10-23', '06:00', '08:00', '🧠 Memory session 3: chunking, hooks and a pattern palace', 'Day 3 - Async, messaging and real time

Interactive memory session 3 with Claude (90 min), then 30 min on your own.
Technique: chunking, the link method, and a palace for the 10 reusable patterns.
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 3'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: Concepts: queues vs streams, at-least-once vs exactly-once, ordering, idempotency keys, outbox, sagas.'),
  ('2026-10-23', '08:30', '10:45', '📚 Distributed message queue (Kafka) + Idempotent processing', 'Day 3 - Async, messaging and real time

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a Distributed Message Queue (Kafka)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/summary
- Design Exactly-Once-Like Processing Using Idempotency
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary'),
  ('2026-10-23', '11:00', '13:15', '📚 Job queue, Pub/sub notifications, Backpressure', 'Day 3 - Async, messaging and real time

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a Job Queue (background task processing)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/summary
- Design a Pub-Sub System for Event Notifications
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/summary
- Design backpressure for a write-heavy pipeline
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/summary'),
  ('2026-10-23', '14:00', '16:15', '📚 Order workflow (saga) + Payment system', 'Day 3 - Async, messaging and real time

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design an event-driven order processing workflow (e-commerce)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/summary
- Design a Payment System (e-commerce pay-in and pay-out)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary'),
  ('2026-10-23', '16:30', '18:45', '📚 Messaging app, Presence, WebSocket scaling', 'Day 3 - Async, messaging and real time

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a Messaging App (WhatsApp / Messenger)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary
- Design Presence for a Chat Application (online / away / last seen)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary
- Design WebSocket scaling (live updates)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/summary'),
  ('2026-10-23', '19:30', '22:30', '📚 Mock 3 (45 min): WhatsApp + recall', 'Day 3 - Async, messaging and real time

45-minute timed mock: ''Design WhatsApp'' (1:1 and group chat, delivery receipts, presence).
Then 30 min: compare with the summary and write down 3 gaps.
Then 45 min: recall today''s hooks on paper without looking, then say 3 full cards aloud. Today''s cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling
Stop at 22:30 and sleep: sleep is when today''s learning is stored.

Open:
- Design a Messaging App (WhatsApp / Messenger)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary'),
  ('2026-10-24', '06:00', '08:00', '🧠 Memory session 4: explain it, then defend it', 'Day 4 - Classic product designs

Interactive memory session 4 with Claude (90 min), then 30 min on your own.
Technique: elaborative interrogation (''why?'' and ''what if?''), the Feynman teach-back and interleaving.
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 4'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: write your checklist for product designs: users and scale, read/write ratio, core entities, APIs, data stores, hot paths, failure modes.'),
  ('2026-10-24', '08:30', '10:45', '📚 Uber: matching, location updates, dispatch', 'Day 4 - Classic product designs

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design Uber (ride-hailing)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
- Design Google Maps (routing, ETA and navigation)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/summary'),
  ('2026-10-24', '11:00', '13:15', '📚 Food delivery (Swiggy) + News feed', 'Day 4 - Classic product designs

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design Swiggy / DoorDash-style food delivery ordering
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary
- Design a Social News Feed (Facebook / Twitter / Instagram home timeline)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/summary'),
  ('2026-10-24', '14:00', '16:15', '📚 Fan-out, Ranked timeline, Notifications for feeds', 'Day 4 - Classic product designs

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design fanout for a follower graph
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/summary
- Design a ranked home timeline (ranking and freshness)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/summary
- Design notifications for a feed action (like, comment, follow, mention)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/summary'),
  ('2026-10-24', '16:30', '18:45', '📚 Video streaming, Media CDN, Image sharing', 'Day 4 - Classic product designs

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design Netflix / YouTube-style video streaming
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/summary
- Design a CDN strategy for media delivery (video, images, live events)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/summary
- Design Instagram-style image sharing
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/summary'),
  ('2026-10-24', '19:30', '22:30', '📚 Mock 4 (45 min): Uber or Swiggy + recall', 'Day 4 - Classic product designs

45-minute timed mock: ''Design Swiggy/Uber'', the one you are weaker on.
Then 30 min: compare with the summary and write down 3 gaps.
Then 45 min: recall today''s hooks on paper without looking, then say 3 full cards aloud. Today''s cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=uber,google-maps-navigation,food-delivery,news-feed,follower-fanout,ranked-timeline,feed-notifications,video-streaming,media-cdn,image-sharing
Stop at 22:30 and sleep: sleep is when today''s learning is stored.

Open:
- Design Uber (ride-hailing)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
- Design Swiggy / DoorDash-style food delivery ordering
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary'),
  ('2026-10-25', '06:00', '08:00', '🧠 Memory session 5: mixed, timed recall', 'Day 5 - High-stakes systems, reliability and full mocks

Interactive memory session 5 with Claude (90 min), then 30 min on your own.
Technique: interleaved, timed recall under pressure.
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 5'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store,object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby,distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling,uber,google-maps-navigation,food-delivery,news-feed,follower-fanout,ranked-timeline,feed-notifications,video-streaming,media-cdn,image-sharing
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: redo your 3 weakest cards from the drill, from memory.'),
  ('2026-10-25', '08:30', '10:45', '📚 Flash sale + Ticket booking (contention, inventory)', 'Day 5 - High-stakes systems, reliability and full mocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a flash sale system (Big Billion Days style sale event)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/summary
- Design a ticket booking system (Ticketmaster / BookMyShow)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/summary'),
  ('2026-10-25', '11:00', '13:15', '📚 Leaderboard, Ad-click aggregation, Stock exchange', 'Day 5 - High-stakes systems, reliability and full mocks

For each design (45-60 min):
1. Read its recall card''s Hook first (1 min), so the details have somewhere to land.
2. Read the 5-page summary (15 min), then the hard parts of the full deep dive (20 min).
3. Close everything. Say the card from memory in P-N-H-B-D-F-C order, out loud, in 3 minutes (''Please Never Hide Bad Design From Customers'').
4. Open the card, fix the gaps, answer its 3 quiz questions. Mark it green, amber or red.
Work 50 min on, 10 min off.

Open:
- Design a real-time gaming leaderboard
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/summary
- Design an ad click event aggregation system
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/summary
- Design a stock exchange (order matching engine)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/summary'),
  ('2026-10-25', '14:00', '16:15', '📚 Reliability and security pack', 'Day 5 - High-stakes systems, reliability and full mocks

Faster pass, about 20 min each: read the Hook, the card, then say it from memory and answer one failure question aloud.

Open:
- Design multi-region failover and disaster recovery
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/summary
- Design retries, timeouts and circuit breakers (resilient service client)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/summary
- Design graceful degradation when a dependency fails
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/summary
- Design a canary deployment and rollback strategy
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/summary
- Design authentication and session management (web app login, tokens, sessions)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/summary
- Design role-based access control (centralized authorization service)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/summary'),
  ('2026-10-25', '16:30', '18:45', '📚 Mock 5 (60 min) + Mock 6 (45 min)', 'Day 5 - High-stakes systems, reliability and full mocks

Mock 5 (60 min): a design you have NOT studied this week, picked at random from Interview Prep -> System design. Use P-N-H-B-D-F-C to structure it even without a card.
Mock 6 (45 min): ''Design a payment system'' with failures and idempotency.
Review both.'),
  ('2026-10-25', '19:30', '22:30', '📚 Consolidate: cheat sheet + spaced review plan', 'Day 5 - High-stakes systems, reliability and full mocks

Write a one-page cheat sheet: the time anchors (day 100K s, month 2.6M s, year 30M s), the 10 patterns from your palace, your top trade-offs.
Say today''s cards from memory: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=flash-sale,ticket-booking,leaderboard,ad-click-aggregation,stock-exchange,multi-region-dr,retries-circuit-breakers,graceful-degradation,canary-deployments,auth-sessions,rbac-authorization
Set your review dates for red and amber cards: tomorrow, in 3 days, in a week, in two weeks.
Stop at 22:30 and sleep.');

-- 1. Update blocks from an earlier run (same day and start time).
update daily_events e
set title = p.title, description = p.description, end_time = p.end_time
from _plan p
where e.user_id = (select id::text from users where email = 'venghatesh@gmail.com')
  and e.plan_date = p.plan_date and e.start_time = p.start_time
  and (e.title like '📚 %' or e.title like '🧠 %')
  and coalesce(e.is_deleted, false) = false;

-- 2. Insert the blocks that are not there yet.
insert into daily_events (user_id, plan_date, start_time, end_time, title, description, priority, reminder_minutes, is_deleted)
select (select id::text from users where email = 'venghatesh@gmail.com'), p.plan_date, p.start_time, p.end_time, p.title, p.description, 'high', 5, false
from _plan p
where not exists (select 1 from daily_events e
                  where e.user_id = (select id::text from users where email = 'venghatesh@gmail.com')
                    and e.plan_date = p.plan_date and e.start_time = p.start_time
                    and (e.title like '📚 %' or e.title like '🧠 %')
                    and coalesce(e.is_deleted, false) = false);

-- To remove the whole plan later:
-- update daily_events set is_deleted = true
--  where (title like '📚 %' or title like '🧠 %') and plan_date between '2026-10-21' and '2026-10-25'
--    and user_id = (select id::text from users where email = 'venghatesh@gmail.com');
