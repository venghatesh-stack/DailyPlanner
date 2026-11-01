-- Day Sheet (/day-sheet): the printable-planner style page for one day.
-- Run once in the Supabase SQL editor. Safe to run again.
--
-- Only the parts that are new live here: Top 3, to-dos, energy, notes,
-- the free-text line per hour and "do differently tomorrow". Everything
-- else on the page already has a home and is reused:
--   Today's focus     -> daily_meta.daily_intent (the One Big Thing)
--   Reflection        -> daily_meta.reflection
--   Grateful for      -> daily_meta.gratitude
--   Habits            -> habit_master + habit_entries
--   Schedule entries  -> your events, tasks and project tasks
-- Row-level security is on with no policies: only the server's secret key
-- can read or write it, like every other table.

create table if not exists day_sheets (
  user_id     text not null,
  sheet_date  date not null,
  data        jsonb not null default '{}'::jsonb,
  updated_at  timestamptz not null default now(),
  primary key (user_id, sheet_date)
);

alter table day_sheets enable row level security;
