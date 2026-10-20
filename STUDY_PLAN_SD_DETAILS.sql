-- Fills in every field of the System design bootcamp tasks (sprints, due times, planned hours, Eisenhower).
-- Run after STUDY_PLAN_SD_5DAY.sql. Safe to run again.

-- ════════════════════════════════════════════════════════════════════
--  PART 3: fill in every field of the bootcamp tasks.
--  One sprint per day, due time = end of the study block, planned hours,
--  Eisenhower = Do, duration 0 days (same day), actual hours 0.
--  Also sets the goal's daily commitment (14 h) and deadline for the
--  Goal Planner countdown. Safe to run again.
-- ════════════════════════════════════════════════════════════════════
drop table if exists _okr_detail;
create temp table _okr_detail(task_text text, due_time text, planned numeric, sprint_no int, notes text);
insert into _okr_detail values
    ('Recall card green: Design a URL Shortener (TinyURL / Bitly)', '10:45', 1.12, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary'),
    ('Recall card green: Design a Distributed Unique ID Generator (Snowflake)', '10:45', 1.12, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/unique-id-generator/summary'),
    ('Recall card green: Design an API Gateway Rate Limiter', '13:15', 1.12, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/api-rate-limiter/summary'),
    ('Recall card green: Design a Distributed Cache (Redis / Memcached cluster)', '13:15', 1.12, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-cache/summary'),
    ('Recall card green: Design a caching strategy for a read-heavy API (product catalog scale)', '16:15', 0.75, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/read-heavy-cache/summary'),
    ('Recall card green: Design cache invalidation for frequently updated content', '16:15', 0.75, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/cache-invalidation/summary'),
    ('Recall card green: Design a counter service that avoids hot keys (likes, views, inventory-style counts)', '16:15', 0.75, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/hot-key-counter/summary'),
    ('Recall card green: Design a Distributed Key-Value Store (Dynamo-style)', '18:45', 2.25, 1, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-kv-store/summary'),
    ('Recall card green: Design an Object Storage Service (S3)', '10:45', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/object-storage-s3/summary'),
    ('Recall card green: Design a file storage and sharing system (Dropbox / Google Drive)', '10:45', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/file-storage/summary'),
    ('Recall card green: Design a partitioning strategy for a large events table', '13:15', 0.75, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/events-table-partitioning/summary'),
    ('Recall card green: Design a time-range query store (time-series and event history)', '13:15', 0.75, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/time-range-queries/summary'),
    ('Recall card green: Design an audit log and immutable history', '13:15', 0.75, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/audit-log/summary'),
    ('Recall card green: Design Autocomplete (search typeahead suggestions)', '16:15', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary'),
    ('Recall card green: Design E-commerce Catalog Search (product search)', '16:15', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary'),
    ('Recall card green: Design a Web Crawler (search-engine scale)', '18:45', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/web-crawler/summary'),
    ('Recall card green: Design geo search for nearby locations (Yelp / Google Maps nearby)', '18:45', 1.12, 2, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/geo-search-nearby/summary'),
    ('Recall card green: Design a Distributed Message Queue (Kafka)', '10:45', 1.12, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/distributed-message-queue/summary'),
    ('Recall card green: Design Exactly-Once-Like Processing Using Idempotency', '10:45', 1.12, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary'),
    ('Recall card green: Design a Job Queue (background task processing)', '13:15', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/job-queue/summary'),
    ('Recall card green: Design a Pub-Sub System for Event Notifications', '13:15', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/pubsub-notifications/summary'),
    ('Recall card green: Design backpressure for a write-heavy pipeline', '13:15', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/backpressure-pipeline/summary'),
    ('Recall card green: Design an event-driven order processing workflow (e-commerce)', '16:15', 1.12, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/order-processing-workflow/summary'),
    ('Recall card green: Design a Payment System (e-commerce pay-in and pay-out)', '16:15', 1.12, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary'),
    ('Recall card green: Design a Messaging App (WhatsApp / Messenger)', '18:45', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary'),
    ('Recall card green: Design Presence for a Chat Application (online / away / last seen)', '18:45', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary'),
    ('Recall card green: Design WebSocket scaling (live updates)', '18:45', 0.75, 3, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/websocket-scaling/summary'),
    ('Recall card green: Design Uber (ride-hailing)', '10:45', 1.12, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary'),
    ('Recall card green: Design Google Maps (routing, ETA and navigation)', '10:45', 1.12, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/google-maps-navigation/summary'),
    ('Recall card green: Design Swiggy / DoorDash-style food delivery ordering', '13:15', 1.12, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary'),
    ('Recall card green: Design a Social News Feed (Facebook / Twitter / Instagram home timeline)', '13:15', 1.12, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/news-feed/summary'),
    ('Recall card green: Design fanout for a follower graph', '16:15', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/follower-fanout/summary'),
    ('Recall card green: Design a ranked home timeline (ranking and freshness)', '16:15', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ranked-timeline/summary'),
    ('Recall card green: Design notifications for a feed action (like, comment, follow, mention)', '16:15', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/feed-notifications/summary'),
    ('Recall card green: Design Netflix / YouTube-style video streaming', '18:45', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/video-streaming/summary'),
    ('Recall card green: Design a CDN strategy for media delivery (video, images, live events)', '18:45', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/media-cdn/summary'),
    ('Recall card green: Design Instagram-style image sharing', '18:45', 0.75, 4, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/image-sharing/summary'),
    ('Recall card green: Design a flash sale system (Big Billion Days style sale event)', '10:45', 1.12, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/flash-sale/summary'),
    ('Recall card green: Design a ticket booking system (Ticketmaster / BookMyShow)', '10:45', 1.12, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ticket-booking/summary'),
    ('Recall card green: Design a real-time gaming leaderboard', '13:15', 0.75, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/leaderboard/summary'),
    ('Recall card green: Design an ad click event aggregation system', '13:15', 0.75, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ad-click-aggregation/summary'),
    ('Recall card green: Design a stock exchange (order matching engine)', '13:15', 0.75, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/stock-exchange/summary'),
    ('Recall card green: Design multi-region failover and disaster recovery', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/multi-region-dr/summary'),
    ('Recall card green: Design retries, timeouts and circuit breakers (resilient service client)', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/retries-circuit-breakers/summary'),
    ('Recall card green: Design graceful degradation when a dependency fails', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/graceful-degradation/summary'),
    ('Recall card green: Design a canary deployment and rollback strategy', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/canary-deployments/summary'),
    ('Recall card green: Design authentication and session management (web app login, tokens, sessions)', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/auth-sessions/summary'),
    ('Recall card green: Design role-based access control (centralized authorization service)', '16:15', 0.38, 5, 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it. Done = every line right.
Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/recall
Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/rbac-authorization/summary'),
    ('Mock 1: URL shortener (45 min)', '20:15', 0.75, 1, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a URL Shortener (TinyURL / Bitly)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/url-shortener/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Mock 2: search autocomplete (45 min)', '20:15', 0.75, 2, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design Autocomplete (search typeahead suggestions)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/autocomplete/summary
Design E-commerce Catalog Search (product search)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/ecommerce-search/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Mock 3: WhatsApp (45 min)', '20:15', 0.75, 3, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a Messaging App (WhatsApp / Messenger)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/messaging-app/summary
Design Presence for a Chat Application (online / away / last seen)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/chat-presence/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Mock 4: Uber or Swiggy (45 min)', '20:15', 0.75, 4, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design Uber (ride-hailing)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/uber/summary
Design Swiggy / DoorDash-style food delivery ordering
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/food-delivery/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Mock 5: an unseen design (60 min)', '17:45', 1.0, 5, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Pick a design you have not studied: https://dailyplanner-zus3.onrender.com/interview-prep/design

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Mock 6: payment system (45 min)', '18:45', 0.75, 5, 'Set a timer and design it out loud, following ''What to say'': https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-phrases
Afterwards compare with the card and write down 3 gaps.

Read first:
Design a Payment System (e-commerce pay-in and pay-out)
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/payment-system/summary
Design Exactly-Once-Like Processing Using Idempotency
  Card: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/recall
  Summary: https://dailyplanner-zus3.onrender.com/interview-prep/design/idempotent-processing/summary

All recall cards: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards'),
    ('Concepts 1 to 10: say each ''Say it'' line from memory', '08:00', 0.5, 1, 'Concepts 1 to 10 (Scaling and traffic, caching). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    ('Memory session 1 with Claude', '07:30', 1.5, 1, '1. Open the guide and copy the ''Session 1'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    ('Concepts 11 to 20: say each ''Say it'' line from memory', '08:00', 0.5, 2, 'Concepts 11 to 20 (Caching, databases, replication). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    ('Memory session 2 with Claude', '07:30', 1.5, 2, '1. Open the guide and copy the ''Session 2'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    ('Concepts 21 to 30: say each ''Say it'' line from memory', '08:00', 0.5, 3, 'Concepts 21 to 30 (Consistency, consensus, messaging). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    ('Memory session 3 with Claude', '07:30', 1.5, 3, '1. Open the guide and copy the ''Session 3'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    ('Concepts 31 to 40: say each ''Say it'' line from memory', '08:00', 0.5, 4, 'Concepts 31 to 40 (Messaging, data flow, resilience). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    ('Memory session 4 with Claude', '07:30', 1.5, 4, '1. Open the guide and copy the ''Session 4'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new'),
    ('Concepts 41 to 50: say each ''Say it'' line from memory', '08:00', 0.5, 5, 'Concepts 41 to 50 (Resilience, observability, deployment, estimation). Read each one, cover it, say its ''Say it'' line aloud.
Open the guide: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts
PDF for your phone: https://dailyplanner-zus3.onrender.com/interview-prep/guides/system-design-concepts/pdf'),
    ('Memory session 5 with Claude', '07:30', 1.5, 5, '1. Open the guide and copy the ''Session 5'' prompt: https://dailyplanner-zus3.onrender.com/interview-prep/guides/memory-techniques
2. Download the cards and attach them to a new Claude chat: https://dailyplanner-zus3.onrender.com/interview-prep/recall-cards.pdf?slugs=url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store,object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby,distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling,uber,google-maps-navigation,food-delivery,news-feed,follower-fanout,ranked-timeline,feed-notifications,video-streaming,media-cdn,image-sharing
3. Paste the prompt and answer out loud.
New chat: https://claude.ai/new');
drop table if exists _okr_sprint;
create temp table _okr_sprint(n int, name text, day date);
insert into _okr_sprint values
    (1, 'Day 1: Foundations and caching', '2026-10-21'::date),
    (2, 'Day 2: Storage and search', '2026-10-22'::date),
    (3, 'Day 3: Messaging and real time', '2026-10-23'::date),
    (4, 'Day 4: Classic products', '2026-10-24'::date),
    (5, 'Day 5: High-stakes systems and reliability', '2026-10-25'::date);

do $det$
declare
  uid text; pid uuid; oid uuid; sid uuid; s record;
  has_sprints boolean := to_regclass('public.sprints') is not null;
  has_task_sprint boolean := exists (select 1 from information_schema.columns
      where table_name = 'project_tasks' and column_name = 'sprint_id');
begin
  select id::text into uid from users where email = 'venghatesh@gmail.com';
  select project_id into pid from projects
   where user_id = uid and name = 'System design bootcamp (21-25 Oct)' and coalesce(is_archived, false) = false limit 1;
  if pid is null then raise exception 'Run PART 2 first: the bootcamp project does not exist yet'; end if;

  update project_tasks t
     set due_time = d.due_time, planned_hours = d.planned, notes = coalesce(d.notes, t.notes), actual_hours = coalesce(t.actual_hours, 0),
         duration_days = 0, quadrant = 'do', priority = 'high',
         status = coalesce(nullif(t.status, ''), 'open'), is_recurring = false
    from _okr_detail d
   where t.user_id = uid and t.project_id = pid and t.task_text = d.task_text;

  if has_sprints and has_task_sprint then
    for s in select * from _okr_sprint order by n loop
      execute 'select id from sprints where user_id = $1 and project_id = $2 and name = $3 and coalesce(is_deleted,false) = false limit 1'
        into sid using uid, pid, s.name;
      if sid is null then
        execute 'insert into sprints (user_id, project_id, name, starts_on, ends_on, is_active, order_index) values ($1,$2,$3,$4,$4,$5,$6) returning id'
          into sid using uid, pid, s.name, s.day, s.n = 1, s.n;
      end if;
      execute 'update project_tasks t set sprint_id = $1 from _okr_detail d
                where t.user_id = $2 and t.project_id = $3 and t.task_text = d.task_text and d.sprint_no = $4'
        using sid, uid, pid, s.n;
    end loop;
  end if;

  select id into oid from objectives where user_id = uid and project_id = pid and title = 'Walk into any system design interview able to recall and present a design calmly' limit 1;
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
    update objectives set category = coalesce(category, 'Career') where id = oid;
  end if;
end
$det$;

-- Check: every bootcamp task with its sprint, due time and planned hours.
select t.due_date, t.due_time, t.planned_hours, t.quadrant, t.task_text
from project_tasks t join projects p on p.project_id = t.project_id
where p.name = 'System design bootcamp (21-25 Oct)' order by t.due_date, t.due_time, t.task_text;
