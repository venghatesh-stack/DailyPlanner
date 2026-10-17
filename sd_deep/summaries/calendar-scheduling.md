# Design a calendar scheduling system (Google Calendar / Outlook): the 5-page summary

A calendar looks like CRUD on events, but the hard parts are time and coordination: recurrence across time zones, free/busy across many people, rooms that must never be double-booked, and reminders that fire once, on time. The key idea: store recurring events as rules in local time plus zone, derive everything else as rebuildable views, and keep hard consistency only for rooms.

## Page 1. The problem, scope and numbers

**Pitch:** make scheduling a few clicks: find a common free slot, book a room, track who accepted and remind everyone on time, while interoperating with other calendar systems.

**Who uses it:** managers, executive assistants (many calendars), remote staff (correct times across zones), facilities admins (rooms) and enterprise IT (policy, audit, CalDAV).

**In scope:**
- **Events and calendars:** CRUD, all-day and multi-day events, sharing and delegation.
- **Recurring events:** RRULE (the iCalendar RFC 5545 rule format), per-instance exceptions, "this / this and following / all" edits.
- **Invitations:** RSVP (accepted, declined, tentative); organiser updates propagate to attendees.
- **Free/busy and find a time:** across attendees and rooms, respecting working hours.
- **Rooms, reminders, sync:** conflict-free room booking; push, email, SMS reminders; sync tokens, CalDAV and email invites.

**Out of scope:** video conferencing (we only attach a link), task management, travel, ML scheduling, paid booking pages.

**Non-functional targets:**
- **Latency:** day/week view p95 under 200 ms; free/busy for 20 attendees x 1 week p95 under 300 ms.
- **Availability and durability:** 99.95% reads, 99.9% writes; no event loss, 3 replicas, 30-day point-in-time recovery.
- **Consistency:** read-your-writes for the organiser; eventual (under 5 s) for attendees; linearizable per room.
- **Reminders and time:** 99.9% within 30 s, duplicates under 0.01%; zero DST-induced shifts.

**Capacity math (500M users, 100M DAU):**
- **View reads:** 100M x 10 / 86,400 = about 11.6k/s, 60k/s peak. So serve views from a pre-expanded per-user index.
- **Event writes:** 100M x 2 / 86,400 = about 2.3k/s, 12k/s peak. Modest, so spend it on correctness (transactions, outbox).
- **Attendee fan-out:** 2.3k x 4 attendees = about 9.3k/s, about 50k/s peak. So fan out asynchronously, never in the organiser's request.
- **Free/busy:** 20M actions x 3 queries = 700/s, x 10 calendars = 7k range reads/s. So precompute busy intervals.
- **Storage:** events 500M x 500/yr x 2 KB = 500 TB/yr; agenda 500M x 1,500 instances x 200 B = 150 TB, the largest hot store. So partition it by user.
- **Reminders:** 300M/day = about 3.5k/s average, up to 150k/s in a top-of-hour minute. So preload and absorb bursts.

## Page 2. The architecture

```
 Web / Mobile / CalDAV clients / Email (iMIP)
              v
 API Gateway: OAuth, rate limit, idempotency keys, CalDAV translation
    |                  |                          |
    v                  v                          v
 Event service     Free/Busy service ------> Agenda index (Cassandra)
    |   +--> Booking service: insert (roomId, slot)  ^ (userId, startUtc)
    v                                             |
 Event DB (Postgres/Spanner, by calendarId) + outbox row
    |  CDC                                        |
    v                                             |
 Kafka (partition by eventId) --> Fan-out service +--> Search, Sync/CalDAV
    v
 Reminder scheduler (minute buckets, timer wheels) -> Notification svc
                                         -> APNs/FCM, email, SMS
```

- **API Gateway:** auth, per-user rate limits, idempotency keys, CalDAV translation.
- **Event service:** source of truth for series and exceptions; writes event plus outbox row atomically.
- **Booking service:** conflict-free room booking with unique (roomId, slot) rows.
- **Fan-out service:** writes attendee copies and agenda instances; batches large guest lists.
- **Agenda index:** per-user expanded instances for 18 months; powers views and free/busy.
- **Free/Busy service:** merges busy intervals, applies working hours, suggests slots; 60 s cache.
- **Reminder scheduler:** minute buckets, leased shards, in-memory timer wheels, dedupe markers.
- **Notification service:** push, email, SMS with retries and provider failover.
- **Sync service:** sync tokens, webhooks, CalDAV and ICS import and export.

**Flow A: create a meeting with a room**
1. POST with Idempotency-Key: 10:00 Asia/Kolkata, 60 min, 6 attendees, room R12.
2. Booking service inserts R12's four 15-minute slots in one transaction; a clash returns 409 with alternatives.
3. Event row plus EventCreated outbox row commit on the organiser's shard; 201 to the organiser.
4. CDC to Kafka; Fan-out upserts attendee copies and agenda rows; Scheduler writes reminder jobs.

**Flow B: fire a reminder**
1. At T-2 minutes a worker loads the 09:50 bucket into a timer wheel.
2. At 09:50:00 it checks the event is not cancelled, then inserts a fired marker if absent.
3. Notification sends via FCM, retrying then failing over; lateness is recorded.

## Page 3. The core deep dives

### 1. Recurrence and time zones
Store a series once: startLocal, IANA zone and RRULE, plus exceptions keyed by RECURRENCE-ID (the original start of the instance). Expansion generates occurrences in local wall time, then converts each to UTC. A weekly 9:00 America/New_York meeting is 13:00 UTC before the DST change and 14:00 UTC after, but always 9:00 local; attendees in India correctly see it move. A UTC offset is not a time zone. "This and following" splits the series: the old RRULE gets UNTIL the day before, a new series starts with a parent link. Cap expansion (for example 5,000 instances) and reject MINUTELY or SECONDLY rules from untrusted clients. When governments change DST rules, ship new tzdata and re-expand affected series and reminders.

### 2. No double-booked room
Check-then-insert races are write skew, which snapshot isolation does not stop. So make the conflict a unique key: one RoomSlot row per 15-minute slot with key (roomId, slotStart), all inserted in one transaction. If Shreya books R12 10:00-11:00 and Sethu books 10:30-11:30 at the same instant, both try the 10:30 and 10:45 rows; one commit wins, the other gets 409 with alternative rooms and times. On Postgres an exclusion constraint on a time range does the same at any precision. Contention is per room, so it scales.

### 3. Reminders as a distributed timer
ReminderJob rows are partitioned by (bucketMinute, shardId) across 1,024 shards, so "what is due" is a cheap lookup. Workers lease shard ranges and preload the next 2 minutes into a 1-second-tick timer wheel (a circular array of slots, O(1) insert and fire). Before firing, a worker inserts a marker keyed by hash(eventId, instanceStart, userId, method); if it exists, it skips. A dead worker's lease expires in about 10 s and a new one fires late but within the 30 s SLO.

### 4. Fan-out, outbox and free/busy
The event and its outbox row commit together, avoiding lost dual writes; consumers are at-least-once, so they upsert by (calendarId, eventId) with version numbers. Events over 5,000 attendees and public calendars are merged at read time, not copied. Free/busy fetches intervals in parallel with a 150 ms per-call timeout, sorts and merges them, then sweeps gaps inside working hours, O(N log N); slow calendars come back as "unknown".

**Data model:**
- **Event** (Postgres/Spanner): PK (calendarId, eventId); startLocal, timeZone, rrule, exdates, sequence, etag.
- **EventException**: PK (calendarId, eventId, originalStart); overrides or cancelled.
- **AttendeeCopy**: PK (attendee calendarId, eventId); RSVP and personal reminders.
- **AgendaInstance** (Cassandra): partition userId (plus year bucket), clustered by startUtc.
- **RoomSlot**: PK (roomId, slotStart); **ReminderJob**: partition (bucketMinute, shardId).

**Key APIs:**
- `POST /v1/calendars/{id}/events`: idempotent create; 409 ROOM_CONFLICT with suggestions.
- `PATCH /v1/events/{id}`: If-Match etag; scope this, following or all.
- `POST /v1/events/{id}/rsvp`: updates the attendee copy, propagates to the organiser.
- `POST /v1/freebusy`: busy blocks plus suggestions; partial results allowed.
- `GET /v1/calendars/{id}/events?syncToken=`: changes only; 410 GONE forces full resync.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Big meetings:** batch fan-out of 500 with backpressure; invite a group address; merge giant events and public calendars at read time.
- **Free/busy across many calendars:** read the compact busy projection, parallel calls, 60 s cache invalidated on change.
- **Event writes:** shard by hash of calendarId; a series is one write, not 250 instance rows.
- **Heavy users:** partition the agenda by userId plus year bucket; views read only the window.
- **Top-of-hour reminders:** preload buckets, spread sends within the 30 s window, rate limit per provider, use several vendors.

**Failure modes:**
- **Fan-out lag:** the organiser sees the event at once, attendees late; autoscale, prioritise small meetings, alert above 30 s lag.
- **Reminder worker crash:** lease expires in about 10 s, the bucket reloads, reminders fire a few seconds late, no doubles.
- **Push provider outage:** circuit breaker, backoff with jitter, fall back to email or SMS for high-priority reminders.
- **Event DB primary fails:** failover to a synchronous replica in about 30 s; writes fail fast and retry; agenda reads unaffected.
- **Agenda partition down:** expand on the fly from the Event DB at higher latency; free/busy marks those calendars "unknown".
- **Bad tzdata deploy:** canary it, diff expansions for a sample of series, keep rollback.

**Trade-offs chosen:**
- **Rules plus a materialised 18-month agenda over storing every instance:** compact, editable series and fast reads; the cache is rebuildable.
- **Async fan-out over synchronous attendee writes:** fast organiser response; seconds of attendee lag are acceptable.
- **Unique slot rows over application locks:** the database enforces correctness, contention scoped to one room.
- **Bucketed store plus leased timer wheels over a cron or a queue of delays:** scales to hundreds of millions of jobs and supports edits and cancels.
- **Strong for rooms and the organiser, eventual for attendees:** rooms are the one place correctness is absolute; personal overlaps only warn.

**What to measure:** week view p95 and errors, free/busy p95 and per-calendar timeout rate, fan-out lag p99 (outbox commit to agenda), reminder lateness histogram and percent within 30 s, duplicate reminder rate, provider errors, room 409 rate, outbox and CDC lag, sync 410 rate.

## Page 5. Say it in the interview

> "I will assume Google Calendar scale, about 100 million daily users, with events, invites, RSVPs, recurring events, reminders, free/busy and rooms. Attendees can see invites a few seconds late, but rooms must never be double-booked and reminders must fire within about 30 seconds. I change the naive events table in three places. First, a recurring event is stored once as an RFC 5545 rule with exceptions, in the organiser's local time and zone so DST never moves it, and expanded into a per-user agenda index for fast views and free/busy. Second, creating a meeting writes the event and an outbox record in one transaction, books rooms with unique slot keys, and fans out invites asynchronously and idempotently. Third, reminders run on a sharded, time-bucketed scheduler with timer wheels. Then I will defend big-meeting fan-out, the room race, DST and scheduler failover."

**Key points to land:**
- Recurring events: RRULE plus exceptions, local wall time plus IANA zone.
- A bounded, materialised agenda per user; the rule stays the truth.
- Rooms are the only hard-consistency spot: unique slot keys or an exclusion constraint.
- Personal calendars may overlap: warn, do not block.
- Outbox plus CDC for fan-out, with idempotent, versioned consumers.
- Fan-out on write for normal meetings, on read for huge events and public calendars.
- Reminders: time buckets, leased shards, timer wheels, insert-if-absent dedupe.
- Plan for the top-of-hour spike: preload and spread within the SLO.
- Idempotency keys for creates, etags for updates, SEQUENCE for interop.

**Likely follow-ups:**
1. **Find a time for 30 people in 3 zones?** Fetch busy intervals in parallel, convert to UTC, intersect each person's working hours, sweep for windows where all required (and most optional) are free, rank by earliest and fewest conflicts.
2. **A public holiday calendar with 1 million subscribers?** Never fan out: merge it at read time, cache expanded instances per window, store per-user overrides.
3. **Sync with Outlook or CalDAV?** Sync tokens or ctags for incremental pulls, map iCalUID to eventId, order by SEQUENCE, push with If-Match etags.
4. **Rooms booked but nobody shows up?** Require check-in within 10 minutes; the reminder scheduler releases the slots and notifies the organiser.
5. **India-resident enterprise tenant?** Pin the tenant's shard, agenda, Kafka and scheduler to the India region; cross-region free/busy exposes only busy intervals.

**Director layer:**
- **Cost drivers:** the 150 TB agenda index, about 500 TB/yr of events, reminder burst capacity and multi-vendor push, email and SMS.
- **Phasing:** start with events, invites and a simple agenda; then recurrence edits, rooms, the reminder scheduler, then CalDAV interop and residency.
- **Team ownership:** events and recurrence, scheduling (free/busy, rooms), reminders and notifications, sync and interop, SRE.
- **Top risks:** DST or tzdata shifts, top-of-hour reminder storms, all-hands fan-out spikes, invite spam (only auto-add from known senders).
