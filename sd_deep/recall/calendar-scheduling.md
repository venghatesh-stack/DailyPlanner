# Calendar scheduling system (Google Calendar / Outlook): recall card

> **Hook:** Store series as RRULE in local time → Event plus outbox in one transaction → Book rooms by unique slot rows → Fan out to agendas → Fire reminders from timer wheels

**P · Problem:** It's really a time and coordination problem: recurrence across zones, room conflicts and on-time timers.

**N · Numbers:**
1. About 60k view reads/s at peak, so serve views from a pre-expanded per-user agenda index.
2. Attendee fan-out reaches about 50k/s at peak, so fan out asynchronously, never in the organiser's request.
3. Reminders spike to 150k/s in a top-of-hour minute, so preload buckets and absorb bursts.

**H · Hard part:** Keeping recurring events right across DST and zones, and never double-booking a room.

**B · Boxes:** `Client → API Gateway → Event service → Event DB + outbox → Kafka → Fan-out → Agenda index`

Side path: `Kafka → Reminder scheduler → Notification service → push, email, SMS`.

**D · Decisions:**
1. Rules plus a materialised 18-month agenda over storing every instance, because series stay compact and editable while reads stay fast.
2. Unique slot rows over application locks, because the database enforces correctness with contention scoped to one room.
3. Async fan-out over synchronous attendee writes, because the organiser gets a fast response and seconds of attendee lag are fine.

**F · Failures:**
1. Reminder worker crash → lease expires in about 10 s, the bucket reloads, reminders fire a few seconds late, no doubles.
2. Fan-out lag → the organiser sees the event at once, attendees late; autoscale and prioritise small meetings.

**C · Close:** "I change the naive events table in three places. A recurring event is stored once as a rule with exceptions, in local time and zone so DST never moves it, and expanded into a per-user agenda. Creating a meeting writes the event and an outbox row in one transaction, books rooms with unique slot keys, and fans out invites asynchronously. Reminders run on a sharded, time-bucketed scheduler with timer wheels."

**Quiz yourself:**
1. Why store local time plus IANA zone? → A UTC offset is not a time zone; 9:00 New York must stay 9:00 across DST.
2. Why doesn't check-then-insert work for rooms? → It is write skew, which snapshot isolation does not stop.
3. How do you avoid duplicate reminders? → Insert a fired marker keyed by event, instance, user and method; skip if it exists.
