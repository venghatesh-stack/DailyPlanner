# Design notifications for a feed action (like, comment, follow, mention): the 5-page summary

When someone likes, comments on, mentions or follows, the affected user should hear about it quickly, once, on the right channel, and without being spammed. The single most important idea: the real enemy is spam, not throughput, so build an idempotent event pipeline (outbox, Kafka keyed by recipient) with an aggregation, preference and rate-limit layer in front of unreliable push providers.

## Page 1. The problem, scope and numbers

**Pitch:** tell users within seconds when people engage with their content, stay quiet for low-value events, and run cheaply at billions of events a day.

**Who uses it:** casual users (replies, not a buzz per like), creators with 2M followers (a summary, not a melting phone), harassed users (silence strangers now), growth, trust and safety, SRE.

**In scope:**
- **Candidates** from like, comment, reply, mention, follow and share; drop self-actions, blocked users and opted-out types.
- **Aggregation:** same type on the same object for the same recipient becomes one group that updates in place ("Shreya and 39 others liked your post").
- **In-app inbox** with cursor pagination, read state and an unread badge synced across devices.
- **Mobile push** via APNs and FCM with priority, quiet hours, rate limits and daily caps; device token hygiene.
- **Retraction** on undo; a daily email digest for users inactive 3+ days.

**Out of scope:** marketing campaigns, chat delivery, ML ranking (hook only), SMS and WhatsApp, desktop web push.

**Non-functional targets:**
- **Latency:** mention and reply action-to-push p95 under 5 s, p99 under 15 s; inbox first page p99 under 150 ms; feed write path adds at most 5 ms.
- **Availability:** 99.95% inbox reads, 99.9% push pipeline.
- **Consistency:** eventual; badge converges with the inbox within 60 s; nothing shown from a blocked user once the block is acknowledged.
- **Durability:** no accepted event lost (Kafka RF 3, acks=all, min.insync.replicas=2).
- **Delivery and cost:** effectively-once to the user (duplicates under 0.01%); under 0.01 USD per 1,000 notifications; opt-out under 0.5% a month.

**Capacity math (300M DAU, 5B feed actions/day, peak 4x average):**
- **Candidates:** 40% of actions = 2B/day; 2B / 86,400 = about 23K/s, 93K/s peak. So the pipeline must be asynchronous and partitioned.
- **Stored writes:** aggregation collapses 4x to 700M rows/day, about 25K writes/s with updates, 100K/s peak. So use a write-optimised store (Cassandra).
- **Pushes:** 30% of rows = 200M/day, about 2.3K/s, 10K/s peak; at 50-200 ms per call that is about 2,000 concurrent HTTP/2 streams. So pool connections per provider.
- **Storage:** 700M x 300 B = 210 GB/day; x 90 days = 19 TB; x RF 3 = 57 TB. So partition by recipient with TTL expiry.
- **Reads:** 30% of DAU open the inbox 5 times a day = 5K/s, 20K/s peak; badge checks are 10x, 200K/s. So the badge lives in Redis.

## Page 2. The architecture

```
 Feed svc --(like row + outbox row, one txn)--> Feed DB --CDC--> Kafka
                       feed-actions (512 parts, by recipient) | notif-high
                                                              v
 Preference + block svc <--(prefs, blocks)-- Notification Processor
                                        dedupe -> filter -> aggregate -> emit
                                              |              |           |
                                       upsert v         incr v      jobs v
                                 Cassandra inbox   Redis: unread,  Delivery
                                 (recipient, ts)   windows, idem,  Router
                                        ^          rate limits     | quiet hrs
                                        |              ^           v caps
 Mobile <-- GET inbox / badge -- Notification Read API      APNs sender
 client <------------------- push ------------------------- FCM sender
```

- **Outbox plus CDC:** like and event commit in one transaction, so no lost events.
- **Kafka:** keyed by recipient; separate high-priority lane for mentions and replies.
- **Notification Processor:** stateless; dedupes, filters, aggregates, writes inbox, emits push jobs.
- **Preference and block service:** mutes, quiet hours, consent; cached 30 s with invalidation.
- **Cassandra inbox:** partition (recipient_id, month bucket), newest first, 90-day TTL.
- **Redis:** unread counters, aggregation windows, idempotency keys, token buckets.
- **Delivery Router:** picks channel and timing; quiet hours, caps, collapse keys.
- **Push senders:** one bulkheaded pool per provider; prune invalid tokens.
- **Read API:** inbox pages, mark read, badge, preferences.

**Flow A: a like on a viral post becomes one push**
1. Sethu likes Shreya's post P; like row and outbox row commit together; CDC publishes to partition hash(Shreya).
2. Processor runs SET NX on event_id (24 h TTL); a duplicate is skipped.
3. Checks blocks and mutes, then aggregates on key agg:Shreya:P:like (count, last 3 actors).
4. Upserts the inbox group; bumps unread only if the group is new or was read.
5. Router: likes are low priority; defer in quiet hours; else one push with collapse-id agg:Shreya:P:like.

**Flow B: a mention in near real time**
1. A comment with @Shreya goes to notif-high, its own consumer group.
2. No aggregation; inbox row and counter written; router checks quiet hours and a cap of 30 an hour.
3. Push in about 1-3 s; retries at 1 s, 4 s, 16 s plus jitter.

## Page 3. The core deep dives

### 1. Outbox, partitioning and effectively-once
Never dual-write to a database and a broker. The feed service inserts the like and an outbox row in one transaction (under 1 ms extra), and CDC publishes it, so a notification outage never fails a like. That gives at-least-once delivery, so every stage is idempotent: event_id gates processing, group upserts use deterministic keys, mark-read uses max(), and a push is keyed by (group_id, window_id, channel). As a last line of defence, APNs apns-collapse-id and FCM collapse_key make a repeated push replace the earlier one on the phone. Exactly-once delivery is a myth; exactly-once effect is achievable.

### 2. Aggregation windows: the defence against celebrity hot keys
Aggregate by (recipient, object, type). Likes get a leading-edge push for responsiveness, then a trailing window from 60 s to 30 minutes that grows with recent push volume, so a burst of 10,000 likes yields one push, and later windows at most one update each (for example at 100, 1K, 10K, 100K). A viral post at 2,000 likes/s lands on one Kafka partition; Redis increments absorb it and the Cassandra row is written every few seconds. Undo inside an open window decrements the count; a group at 0 is deleted.

### 3. Rate limits, bulkheads and stale-push expiry
A per-user, per-priority token bucket in Redis (one atomic Lua script): low priority holds 5 tokens and refills 1 every 10 minutes, plus a daily cap. A denied push is not lost; the notification stays in-app. A second limiter protects APNs and FCM. Each provider has its own queue and workers; calls time out at 2 s and retry 3 times with full jitter on 429 or 5xx only, then go to a dead-letter queue. Every job carries expires_at (like 1 h, mention 24 h), so recovery never floods users with stale pushes.

**Badge:** a Redis counter, a cache of the truth, recomputed on inbox open from rows newer than last_read_at.

**Data model:**
- **notification_group** (Cassandra): PRIMARY KEY ((recipient_id, bucket yyyymm), updated_at DESC, group_id); count, latest 3 actors, hidden flag; TTL 90 days.
- **notification_state** (Redis, hash tag {user}): unread, lastread, agg windows, idem keys (24 h TTL), rate-limit buckets.
- **preferences** (MySQL, user_id mod 64): muted types and objects, quiet hours, time zone, version.
- **device_token** (MySQL): unique token, index on user_id; marked invalid on APNs 410 or FCM UNREGISTERED.

**Key APIs:**
- `GET /v1/notifications?cursor=&limit=20`: opaque cursor, never offset; first page cached 60 s.
- `GET /v1/notifications/unread_count`: from Redis, shown as 99+ when capped.
- `POST /v1/notifications/read`: idempotent; last_read_at = max(existing, up_to).
- `POST /v1/devices`: upsert by token; one user, many devices.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Celebrity hot keys:** hashing spreads keys, not traffic; coalesce in the processor and Redis, write Cassandra every few seconds.
- **Processors:** stateless on Kubernetes, autoscaled on Kafka lag rather than CPU.
- **Kafka:** over-provision partitions (512) now, because adding them later reshuffles keys.
- **Inbox partitions:** monthly buckets keep each under about 100 MB.
- **Badge reads (200K/s):** Redis only, never Cassandra.

**Failure modes:**
- **Consumer lag grows:** autoscale; above 60 s shed like-pushes to in-app only; the high lane is unaffected.
- **Redis shard down:** replica promoted in seconds; high priority falls back to a Cassandra lightweight check, rare low-priority duplicates accepted, badge reconciles later.
- **Cassandra node down:** RF 3 with LOCAL_QUORUM keeps working; hinted handoff and repair restore it.
- **APNs outage for 40 minutes:** its breaker opens and its queue buffers with TTL; Android and the inbox are unaffected; stale like-pushes expire on recovery.
- **Bad config sets the window to 0:** config is validated and canaried to 1% of users; a per-type kill switch stops pushes in seconds.
- **Region loss:** inbox replicated asynchronously; users rerouted; in-flight events may be delayed, accepted for notifications.
- **Block during flight:** three gates (processor, router at send time against the authoritative store, render time).

**Trade-offs chosen:**
- **Fan-out on write over compute-on-read:** push needs a decision at event time, and each event has few recipients.
- **Aggregate in the processor over at read:** read-time grouping cannot reduce pushes.
- **Cassandra over sharded MySQL:** 25K-100K writes/s, TTL expiry, newest-first scans, no cross-row transactions.
- **Priority lanes over one topic:** a like storm must not delay mentions.
- **Build senders over a vendor:** at 200M pushes/day vendor cost is high and we need custom limits; keep the vendor as an option.
- **Expire stale pushes over delivering late:** a burst of late pushes is spam; the inbox keeps the information.

**What to measure:** action-to-push latency p50/p95/p99 by type and platform; Kafka lag per lane; provider success, 429 and 5xx rates and breaker state; duplicate push rate; pushes per user per day and share hitting caps; open, opt-out and 24-hour uninstall rates; inbox p99 and badge drift; DLQ size and age.

## Page 5. Say it in the interview

> "I will cover likes, comments, replies, mentions and follows, delivered to an in-app inbox and mobile push, for 300 million daily users and about 2 billion candidates a day. Mentions should land in a few seconds; likes can be batched. The naive design calls a notification service from the feed write, which couples feed latency to Apple and Google and falls over on a celebrity post. Instead, the feed writes an outbox row in the same transaction, and CDC puts it on Kafka keyed by recipient. Stateless processors dedupe, apply blocks and preferences, and aggregate by recipient, post and type, so forty likes become one updating notification. They upsert a Cassandra inbox, bump a Redis badge, and hand jobs to a router that applies quiet hours and rate limits before bulkheaded APNs and FCM senders. Spam, not throughput, is the real failure mode."

**Key points to land:**
- It is an event pipeline: outbox, Kafka by recipient, idempotent processors.
- The enemy is spam: aggregate by (recipient, object, type), rate-limit pushes, respect quiet hours.
- Separate lanes so likes never delay mentions and replies.
- Inbox in Cassandra by recipient with month buckets; badge in Redis, rebuilt from truth.
- At-least-once plus idempotency keys plus collapse ids gives effectively-once.
- Bulkhead each provider, retry with full jitter, expire stale pushes.
- Blocks are re-checked at send time against the authoritative store.
- Rate-limit the push, never the inbox record.
- Measure action-to-push latency, lag, provider errors and opt-out rate.

**Likely follow-ups:**
1. **5M likes in an hour on one post?** About 1,400/s on one key: batched per poll, coalesced in Redis, Cassandra written every few seconds, pushes only at milestones like 100, 1K, 10K.
2. **Never show a blocked user's notification?** Three gates: processor filter, send-time check against the strongly consistent block store, render-time filter.
3. **Why not WebSockets?** Use them for foregrounded apps when presence says so, but only APNs and FCM can wake a backgrounded phone.
4. **Add ML ranking?** A scoring step in the router: above a threshold push, else inbox only; rules stay as guardrails, A/B tested with opt-out as the guardrail metric.
5. **Test without spamming users?** Shadow mode logging would-send decisions, compare distributions, then canary by cohort with a kill switch.

**Director layer:**
- **Cost drivers:** 57 TB of replicated inbox, provider connection pools for 10K pushes/s at peak, and vendor fees avoided by building senders; target under 0.01 USD per 1,000.
- **Phasing:** rules first, with ML ranking and the email digest as hooks added later.
- **Team ownership:** feed (outbox), notification platform (processor, router, store), mobile (tokens, rendering), trust and safety (blocks, kill switch), SRE.
- **Top risks:** spam driving uninstalls, harassment via mass mentions (cap 10 per comment, trust gating), retry storms after provider outages, duplicate pushes after rebalances, and privacy rules such as India's DPDP Act.
