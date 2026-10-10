-- ============================================================
--  DailyPlanner — WEEKLY CHECK-IN FOR KEY RESULTS
--
--  Added 2026-10-11 with the redesign's check-in screen
--  (/goals/check-in). Two things the app could not answer before:
--
--    1. "When did this number last move?"  key_results had no
--       timestamp of its own, so a key result nobody had touched in
--       a month looked exactly like one updated this morning. That is
--       the gap MIGRATION_TASK_OBJECTIVE measured: 0 of 28 key results
--       had ever moved, and nothing on screen said so.
--       → key_results.last_checked_at
--
--    2. "What was it last week, and why did it change?"  Updating
--       current_value overwrote the old one. A check-in now also writes
--       one row per key result to kr_checkins: the value, the value it
--       replaced, and an optional note.
--       → kr_checkins
--
--  The app works before this runs: the PATCH that sets last_checked_at
--  strips unknown columns and retries (supabase_client.update), and the
--  history insert is best-effort, so a check-in still saves the new
--  values. You just get no "last updated" and no history until it runs.
--
--  Safe to re-run.
-- ============================================================

create extension if not exists pgcrypto;

alter table if exists key_results
    add column if not exists last_checked_at timestamptz;

create table if not exists kr_checkins (
    id              uuid primary key default gen_random_uuid(),
    user_id         text not null,
    key_result_id   uuid not null references key_results(id) on delete cascade,
    objective_id    uuid references objectives(id) on delete cascade,
    value           numeric not null,
    previous_value  numeric,
    note            text,
    created_at      timestamptz default now()
);

-- "This key result's history, newest first" and "everything I checked
-- in this week" are the two reads.
create index if not exists ix_kr_checkins_kr_created
    on kr_checkins (key_result_id, created_at desc);
create index if not exists ix_kr_checkins_user_created
    on kr_checkins (user_id, created_at desc);

-- Same posture as every other table (MIGRATION_ENABLE_RLS.sql): RLS on,
-- no policies, the server talks to it with the service key.
alter table kr_checkins enable row level security;

-- Backfill: give existing key results a starting point so the check-in
-- screen does not flag every one of them as "never updated" on day one.
-- created_at is the honest choice — it is the last time the value was
-- definitely set.
update key_results
   set last_checked_at = created_at
 where last_checked_at is null;
