-- 5-day system design bootcamp with daily memory sessions: 30 blocks, 21-25 Oct 2026, 14 h/day.
-- Paste into the Supabase SQL editor and run. Safe to run again: if you ran the
-- earlier version, the existing blocks are updated in place, nothing is duplicated.
-- Then open Planner and tap 'Sync to Google' to send the blocks to Google Calendar.

drop table if exists _plan;
create temp table _plan(plan_date date, start_time time, end_time time, title text, description text);
insert into _plan values
  ('2026-10-21', '06:00', '08:00', '🧠 Memory session 1: palace for ''What to say'' + the card template', 'Day 1 - Foundations, caching and core building blocks

Interactive memory session 1 with Claude (90 min), then 30 min on your own.
Technique: memory palace (method of loci).
1. Open https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques and copy the ''Session 1'' prompt.
2. Start a new Claude chat. Attach this PDF of cards to the Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener
3. Paste the prompt and answer OUT LOUD before typing.
4. Write down your green, amber and red cards.

Your own 30 min: ''50 core concepts'' guide, concepts 1 to 10 (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts). For each, read it, then close it and say its ''Say it'' line aloud.'),
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

Your own 30 min: ''50 core concepts'' guide, concepts 11 to 20 (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts). For each, read it, then close it and say its ''Say it'' line aloud.'),
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

Your own 30 min: ''50 core concepts'' guide, concepts 21 to 30 (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts). For each, read it, then close it and say its ''Say it'' line aloud.'),
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

Your own 30 min: ''50 core concepts'' guide, concepts 31 to 40 (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts). For each, read it, then close it and say its ''Say it'' line aloud.'),
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

Your own 30 min: ''50 core concepts'' guide, concepts 41 to 50 (https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts). For each, read it, then close it and say its ''Say it'' line aloud. Then redo your 3 weakest cards from the drill.'),
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
  and e.plan_date = p.plan_date and e.start_time::time = p.start_time
  and (e.title like '📚 %' or e.title like '🧠 %')
  and coalesce(e.is_deleted, false) = false;

-- 2. Insert the blocks that are not there yet.
insert into daily_events (user_id, plan_date, start_time, end_time, title, description, priority, reminder_minutes, is_deleted)
select (select id::text from users where email = 'venghatesh@gmail.com'), p.plan_date, p.start_time, p.end_time, p.title, p.description, 'high', 5, false
from _plan p
where not exists (select 1 from daily_events e
                  where e.user_id = (select id::text from users where email = 'venghatesh@gmail.com')
                    and e.plan_date = p.plan_date and e.start_time::time = p.start_time
                    and (e.title like '📚 %' or e.title like '🧠 %')
                    and coalesce(e.is_deleted, false) = false);


-- ════════════════════════════════════════════════════════════════════
--  PART 2: the same plan in Projects, in OKR form.
--  Project -> Objective -> 5 Key Results -> Initiatives -> Epics -> 64 tasks.
--  Ticking tasks off moves the objective's progress bar automatically.
--  Safe to run again: anything already there is reused, nothing is duplicated.
-- ════════════════════════════════════════════════════════════════════
drop table if exists _okr_kr;
create temp table _okr_kr(n int, title text, target numeric, unit text, initiative text);
insert into _okr_kr values
    (1, 'Recall cards said from memory and marked green', 48, 'cards', 'Study the 48 designs'),
    (2, 'Timed mock interviews completed', 6, 'mocks', 'Mock interviews'),
    (3, 'Core concepts explained aloud from memory', 50, 'concepts', 'The 50 core concepts'),
    (4, 'Memory sessions with Claude completed', 5, 'sessions', 'Daily memory sessions'),
    (5, 'Focused study hours logged', 70, 'hours', 'Daily study blocks');
drop table if exists _okr_task;
create temp table _okr_task(kr int, epic text, task_text text, due date, notes text);
insert into _okr_task values
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a URL Shortener (TinyURL / Bitly)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a Distributed Unique ID Generator (Snowflake)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design an API Gateway Rate Limiter', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a Distributed Cache (Redis / Memcached cluster)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a caching strategy for a read-heavy API (product catalog scale)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design cache invalidation for frequently updated content', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a counter service that avoids hot keys (likes, views, inventory-style counts)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/summary'),
    (1, 'Day 1 - Foundations and caching', 'Recall card green: Design a Distributed Key-Value Store (Dynamo-style)', '2026-10-21'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design an Object Storage Service (S3)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design a file storage and sharing system (Dropbox / Google Drive)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design a partitioning strategy for a large events table', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design a time-range query store (time-series and event history)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design an audit log and immutable history', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design Autocomplete (search typeahead suggestions)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design E-commerce Catalog Search (product search)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design a Web Crawler (search-engine scale)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/summary'),
    (1, 'Day 2 - Storage and search', 'Recall card green: Design geo search for nearby locations (Yelp / Google Maps nearby)', '2026-10-22'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design a Distributed Message Queue (Kafka)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design Exactly-Once-Like Processing Using Idempotency', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design a Job Queue (background task processing)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design a Pub-Sub System for Event Notifications', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design backpressure for a write-heavy pipeline', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design an event-driven order processing workflow (e-commerce)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design a Payment System (e-commerce pay-in and pay-out)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design a Messaging App (WhatsApp / Messenger)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design Presence for a Chat Application (online / away / last seen)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary'),
    (1, 'Day 3 - Messaging and real time', 'Recall card green: Design WebSocket scaling (live updates)', '2026-10-23'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design Uber (ride-hailing)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design Google Maps (routing, ETA and navigation)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design Swiggy / DoorDash-style food delivery ordering', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design a Social News Feed (Facebook / Twitter / Instagram home timeline)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design fanout for a follower graph', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design a ranked home timeline (ranking and freshness)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design notifications for a feed action (like, comment, follow, mention)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design Netflix / YouTube-style video streaming', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design a CDN strategy for media delivery (video, images, live events)', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/summary'),
    (1, 'Day 4 - Classic products', 'Recall card green: Design Instagram-style image sharing', '2026-10-24'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design a flash sale system (Big Billion Days style sale event)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design a ticket booking system (Ticketmaster / BookMyShow)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design a real-time gaming leaderboard', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design an ad click event aggregation system', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design a stock exchange (order matching engine)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design multi-region failover and disaster recovery', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design retries, timeouts and circuit breakers (resilient service client)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design graceful degradation when a dependency fails', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design a canary deployment and rollback strategy', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design authentication and session management (web app login, tokens, sessions)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/summary'),
    (1, 'Day 5 - High-stakes systems and reliability', 'Recall card green: Design role-based access control (centralized authorization service)', '2026-10-25'::date, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/summary'),
    (2, 'Mocks', 'Mock 1: URL shortener (45 min)', '2026-10-21'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a URL Shortener (TinyURL / Bitly)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (2, 'Mocks', 'Mock 2: search autocomplete (45 min)', '2026-10-22'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design Autocomplete (search typeahead suggestions)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary
Design E-commerce Catalog Search (product search)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (2, 'Mocks', 'Mock 3: WhatsApp (45 min)', '2026-10-23'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a Messaging App (WhatsApp / Messenger)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary
Design Presence for a Chat Application (online / away / last seen)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (2, 'Mocks', 'Mock 4: Uber or Swiggy (45 min)', '2026-10-24'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design Uber (ride-hailing)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
Design Swiggy / DoorDash-style food delivery ordering
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (2, 'Mocks', 'Mock 5: an unseen design (60 min)', '2026-10-25'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Pick a design you have not studied: https://dailyplanner-zus3.onrender.com/interview-prep/design

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (2, 'Mocks', 'Mock 6: payment system (45 min)', '2026-10-25'::date, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a Payment System (e-commerce pay-in and pay-out)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary
Design Exactly-Once-Like Processing Using Idempotency
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    (3, 'Concepts', 'Concepts 1 to 10: say each ''Say it'' line from memory', '2026-10-21'::date, 'Concepts 1 to 10 (Scaling and traffic, caching). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    (4, 'Memory sessions', 'Memory session 1 with Claude', '2026-10-21'::date, '1. Open the guide and copy the ''Session 1'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    (3, 'Concepts', 'Concepts 11 to 20: say each ''Say it'' line from memory', '2026-10-22'::date, 'Concepts 11 to 20 (Caching, databases, replication). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    (4, 'Memory sessions', 'Memory session 2 with Claude', '2026-10-22'::date, '1. Open the guide and copy the ''Session 2'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    (3, 'Concepts', 'Concepts 21 to 30: say each ''Say it'' line from memory', '2026-10-23'::date, 'Concepts 21 to 30 (Consistency, consensus, messaging). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    (4, 'Memory sessions', 'Memory session 3 with Claude', '2026-10-23'::date, '1. Open the guide and copy the ''Session 3'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    (3, 'Concepts', 'Concepts 31 to 40: say each ''Say it'' line from memory', '2026-10-24'::date, 'Concepts 31 to 40 (Messaging, data flow, resilience). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    (4, 'Memory sessions', 'Memory session 4 with Claude', '2026-10-24'::date, '1. Open the guide and copy the ''Session 4'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    (3, 'Concepts', 'Concepts 41 to 50: say each ''Say it'' line from memory', '2026-10-25'::date, 'Concepts 41 to 50 (Resilience, observability, deployment, estimation). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    (4, 'Memory sessions', 'Memory session 5 with Claude', '2026-10-25'::date, '1. Open the guide and copy the ''Session 5'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store,object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby,distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling,uber,google-maps-navigation,food-delivery,news-feed,follower-fanout,ranked-timeline,feed-notifications,video-streaming,media-cdn,image-sharing
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new');

do $okr$
declare
  uid text; pid uuid; oid uuid; kid uuid; iid uuid; eid uuid; tid uuid;
  has_epics boolean := to_regclass('public.epics') is not null;
  has_task_epic boolean := exists (select 1 from information_schema.columns
      where table_name = 'project_tasks' and column_name = 'epic_id');
  has_task_obj boolean := exists (select 1 from information_schema.columns
      where table_name = 'project_tasks' and column_name = 'objective_id');
  k record; t record;
begin
  select id::text into uid from users where email = 'venghatesh@gmail.com';
  if uid is null then raise exception 'No user with that email'; end if;

  select project_id into pid from projects
   where user_id = uid and name = 'System design bootcamp (21-25 Oct)' and coalesce(is_archived, false) = false limit 1;
  if pid is null then
    insert into projects (user_id, name, description)
    values (uid, 'System design bootcamp (21-25 Oct)', 'Five days, 14 hours a day: recall cards, memory sessions with Claude, the 50 core concepts and 6 timed mocks. The calendar blocks are in the Planner.')
    returning project_id into pid;
  end if;

  select id into oid from objectives
   where user_id = uid and project_id = pid and title = 'Walk into any system design interview able to recall and present a design calmly' and coalesce(is_deleted, false) = false limit 1;
  if oid is null then
    insert into objectives (user_id, project_id, title, description, time_horizon, start_date, target_date, status)
    values (uid, pid, 'Walk into any system design interview able to recall and present a design calmly', 'Measured by recall, not by hours read: every design said from memory, every concept explained aloud, and 6 timed mocks.',
            'ongoing', '2026-10-21', '2026-10-25', 'active')
    returning id into oid;
  end if;

  for k in select * from _okr_kr order by n loop
    select id into kid from key_results
     where user_id = uid and objective_id = oid and title = k.title and coalesce(is_deleted, false) = false limit 1;
    if kid is null then
      insert into key_results (user_id, objective_id, title, unit, start_value, current_value, target_value, order_index)
      values (uid, oid, k.title, k.unit, 0, 0, k.target, k.n) returning id into kid;
    end if;
    select id into iid from initiatives
     where user_id = uid and key_result_id = kid and title = k.initiative and coalesce(is_deleted, false) = false limit 1;
    if iid is null then
      insert into initiatives (user_id, key_result_id, title, status, order_index)
      values (uid, kid, k.initiative, 'active', k.n) returning id into iid;
    end if;

    for t in select * from _okr_task where kr = k.n loop
      eid := null;
      if has_epics then
        execute 'select id from epics where user_id = $1 and initiative_id = $2 and title = $3 and coalesce(is_deleted,false) = false limit 1'
          into eid using uid, iid, t.epic;
        if eid is null then
          execute 'insert into epics (user_id, initiative_id, title, status) values ($1, $2, $3, ''active'') returning id'
            into eid using uid, iid, t.epic;
        end if;
      end if;
      select task_id into tid from project_tasks
       where user_id = uid and project_id = pid and task_text = t.task_text and coalesce(is_deleted, false) = false limit 1;
      if tid is null then
        insert into project_tasks (project_id, user_id, task_text, status, priority, start_date, due_date, notes,
                                   key_result_id, initiative_id)
        values (pid, uid, t.task_text, 'open', 'high', t.due, t.due, t.notes, kid, iid)
        returning task_id into tid;
      end if;
      if has_task_epic and eid is not null then
        execute 'update project_tasks set epic_id = $1 where task_id = $2' using eid, tid;
      end if;
      if has_task_obj then
        execute 'update project_tasks set objective_id = $1 where task_id = $2' using oid, tid;
      end if;
    end loop;
  end loop;
end
$okr$;

-- PART 3: fill in every field of the bootcamp tasks: a sprint per day,
-- due time, planned hours, Eisenhower = Do, and notes with tappable links.
-- Also sets the goal daily commitment (14 h) and deadline. Safe to run again.

drop table if exists _d;
create temp table _d(k text, kind text, arg text, due text, planned numeric, sp int);
insert into _d values
  ('url-shortener','card','','10:45',1.12,1),
  ('unique-id-generator','card','','10:45',1.12,1),
  ('api-rate-limiter','card','','13:15',1.12,1),
  ('distributed-cache','card','','13:15',1.12,1),
  ('read-heavy-cache','card','','16:15',0.75,1),
  ('cache-invalidation','card','','16:15',0.75,1),
  ('hot-key-counter','card','','16:15',0.75,1),
  ('distributed-kv-store','card','','18:45',2.25,1),
  ('object-storage-s3','card','','10:45',1.12,2),
  ('file-storage','card','','10:45',1.12,2),
  ('events-table-partitioning','card','','13:15',0.75,2),
  ('time-range-queries','card','','13:15',0.75,2),
  ('audit-log','card','','13:15',0.75,2),
  ('autocomplete','card','','16:15',1.12,2),
  ('ecommerce-search','card','','16:15',1.12,2),
  ('web-crawler','card','','18:45',1.12,2),
  ('geo-search-nearby','card','','18:45',1.12,2),
  ('distributed-message-queue','card','','10:45',1.12,3),
  ('idempotent-processing','card','','10:45',1.12,3),
  ('job-queue','card','','13:15',0.75,3),
  ('pubsub-notifications','card','','13:15',0.75,3),
  ('backpressure-pipeline','card','','13:15',0.75,3),
  ('order-processing-workflow','card','','16:15',1.12,3),
  ('payment-system','card','','16:15',1.12,3),
  ('messaging-app','card','','18:45',0.75,3),
  ('chat-presence','card','','18:45',0.75,3),
  ('websocket-scaling','card','','18:45',0.75,3),
  ('uber','card','','10:45',1.12,4),
  ('google-maps-navigation','card','','10:45',1.12,4),
  ('food-delivery','card','','13:15',1.12,4),
  ('news-feed','card','','13:15',1.12,4),
  ('follower-fanout','card','','16:15',0.75,4),
  ('ranked-timeline','card','','16:15',0.75,4),
  ('feed-notifications','card','','16:15',0.75,4),
  ('video-streaming','card','','18:45',0.75,4),
  ('media-cdn','card','','18:45',0.75,4),
  ('image-sharing','card','','18:45',0.75,4),
  ('flash-sale','card','','10:45',1.12,5),
  ('ticket-booking','card','','10:45',1.12,5),
  ('leaderboard','card','','13:15',0.75,5),
  ('ad-click-aggregation','card','','13:15',0.75,5),
  ('stock-exchange','card','','13:15',0.75,5),
  ('multi-region-dr','card','','16:15',0.38,5),
  ('retries-circuit-breakers','card','','16:15',0.38,5),
  ('graceful-degradation','card','','16:15',0.38,5),
  ('canary-deployments','card','','16:15',0.38,5),
  ('auth-sessions','card','','16:15',0.38,5),
  ('rbac-authorization','card','','16:15',0.38,5),
  ('Mock 1:','mock','url-shortener','20:15',0.75,1),
  ('Mock 2:','mock','autocomplete,ecommerce-search','20:15',0.75,2),
  ('Mock 3:','mock','messaging-app,chat-presence','20:15',0.75,3),
  ('Mock 4:','mock','uber,food-delivery','20:15',0.75,4),
  ('Mock 5:','mock','','17:45',1.0,5),
  ('Mock 6:','mock','payment-system,idempotent-processing','18:45',0.75,5),
  ('Concepts 1 to','concepts','1 to 10 (Scaling and traffic, caching)','08:00',0.5,1),
  ('Memory session 1 ','memory','1|url-shortener','07:30',1.5,1),
  ('Concepts 11 to','concepts','11 to 20 (Caching, databases, replication)','08:00',0.5,2),
  ('Memory session 2 ','memory','2|url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store','07:30',1.5,2),
  ('Concepts 21 to','concepts','21 to 30 (Consistency, consensus, messaging)','08:00',0.5,3),
  ('Memory session 3 ','memory','3|object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby','07:30',1.5,3),
  ('Concepts 31 to','concepts','31 to 40 (Messaging, data flow, resilience)','08:00',0.5,4),
  ('Memory session 4 ','memory','4|distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling','07:30',1.5,4),
  ('Concepts 41 to','concepts','41 to 50 (Resilience, observability, deployment, estimation)','08:00',0.5,5),
  ('Memory session 5 ','memory','5|','07:30',1.5,5);
drop table if exists _s;
create temp table _s(n int, name text, day date);
insert into _s values
  (1,'Day 1: Foundations and caching','2026-10-21'),
  (2,'Day 2: Storage and search','2026-10-22'),
  (3,'Day 3: Messaging and real time','2026-10-23'),
  (4,'Day 4: Classic products','2026-10-24'),
  (5,'Day 5: High-stakes systems and reliability','2026-10-25');

do $det$
declare
  b text := 'https://dailyplanner-zus3.onrender.com/interview-prep';
  nl text := chr(10);
  uid text; pid uuid; oid uuid; sid uuid; tid uuid;
  r record; s record; txt text; p text; ttl text;
  has_spr boolean := to_regclass('public.sprints') is not null
    and exists (select 1 from information_schema.columns where table_name = 'project_tasks' and column_name = 'sprint_id');
  sprint_ids uuid[] := array[]::uuid[];
begin
  select id::text into uid from users where email = 'venghatesh@gmail.com';
  select project_id into pid from projects where user_id = uid and name = 'System design bootcamp (21-25 Oct)'
    and coalesce(is_archived, false) = false limit 1;
  if pid is null then raise exception 'Run STUDY_PLAN_SD_5DAY.sql first: the bootcamp project is missing'; end if;

  if has_spr then
    for s in select * from _s order by n loop
      execute 'select id from sprints where user_id = $1 and project_id = $2 and name = $3 and coalesce(is_deleted,false) = false limit 1'
        into sid using uid, pid, s.name;
      if sid is null then
        execute 'insert into sprints (user_id, project_id, name, starts_on, ends_on, is_active, order_index) values ($1,$2,$3,$4,$4,$5,$6) returning id'
          into sid using uid, pid, s.name, s.day, s.n = 1, s.n;
      end if;
      sprint_ids := sprint_ids || sid;
    end loop;
  end if;

  for r in select * from _d loop
    if r.kind = 'card' then
      select task_id into tid from project_tasks where user_id = uid and project_id = pid
        and task_text like 'Recall card green:%' and notes like '%/design/' || r.k || '/recall%' limit 1;
      txt := 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it.' || nl
          || 'Card: ' || b || '/design/' || r.k || '/recall' || nl
          || 'Summary: ' || b || '/design/' || r.k || '/summary';
    else
      select task_id into tid from project_tasks where user_id = uid and project_id = pid
        and task_text like r.k || '%' limit 1;
      if r.kind = 'mock' then
        txt := 'Set a timer and design it out loud, following What to say: ' || b || '/guides/system-design-phrases' || nl
            || 'Afterwards compare with the card and write down 3 gaps.' || nl;
        if r.arg = '' then
          txt := txt || nl || 'Pick a design you have not studied: ' || b || '/design';
        else
          foreach p in array string_to_array(r.arg, ',') loop
            select substring(task_text from 'Recall card green: (.*)') into ttl from project_tasks
              where user_id = uid and project_id = pid and notes like '%/design/' || p || '/recall%' limit 1;
            txt := txt || nl || coalesce(ttl, p) || nl
                || '  Card: ' || b || '/design/' || p || '/recall' || nl
                || '  Summary: ' || b || '/design/' || p || '/summary';
          end loop;
        end if;
        txt := txt || nl || nl || 'All recall cards: ' || b || '/recall-cards';
      elsif r.kind = 'concepts' then
        txt := 'Concepts ' || r.arg || '. Read each one, cover it, say its Say it line aloud.' || nl
            || 'Open the guide: ' || b || '/guides/system-design-concepts' || nl
            || 'PDF for your phone: ' || b || '/guides/system-design-concepts/pdf';
      else
        txt := '1. Copy the Session ' || split_part(r.arg, '|', 1) || ' prompt: ' || b || '/guides/memory-techniques' || nl
            || '2. Download the cards and attach them to a new Claude chat: ' || b || '/recall-cards.pdf'
            || case when split_part(r.arg, '|', 2) <> '' then '?slugs=' || split_part(r.arg, '|', 2) else '' end || nl
            || '3. Paste the prompt and answer out loud.' || nl
            || 'New chat: https://claude.ai/new';
      end if;
    end if;
    if tid is null then
      raise notice 'Task not found for %', r.k;
      continue;
    end if;
    update project_tasks set due_time = r.due, planned_hours = r.planned, actual_hours = coalesce(actual_hours, 0),
           duration_days = 0, quadrant = 'do', priority = 'high', is_recurring = false,
           status = coalesce(nullif(status, ''), 'open'), notes = txt
     where task_id = tid;
    if has_spr then
      execute 'update project_tasks set sprint_id = $1 where task_id = $2' using sprint_ids[r.sp], tid;
    end if;
  end loop;

  select id into oid from objectives where user_id = uid and project_id = pid limit 1;
  if oid is not null then
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'daily_commit_minutes') then
      execute 'update objectives set daily_commit_minutes = 840 where id = $1' using oid;
    end if;
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'effort_minutes') then
      execute 'update objectives set effort_minutes = 4200 where id = $1' using oid;
    end if;
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'target_at') then
      execute 'update objectives set target_at = ''2026-10-25 22:30:00+05:30'' where id = $1' using oid;
    end if;
  end if;
end
$det$;

-- Check: should show 64 tasks, 64 with links, 64 with a due time.
select count(*) as tasks,
       count(*) filter (where t.notes like '%https://%') as with_links,
       count(*) filter (where t.due_time is not null) as with_due_time
from project_tasks t join projects p on p.project_id = t.project_id
where p.name = 'System design bootcamp (21-25 Oct)';

-- To remove the whole plan later:
-- update daily_events set is_deleted = true
--  where (title like '📚 %' or title like '🧠 %') and plan_date between '2026-10-21' and '2026-10-25'
--    and user_id = (select id::text from users where email = 'venghatesh@gmail.com');
-- and the project (its objective, key results and tasks go with it):
-- delete from projects where name = 'System design bootcamp (21-25 Oct)'
--   and user_id = (select id::text from users where email = 'venghatesh@gmail.com');
