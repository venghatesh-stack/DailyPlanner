-- ════════════════════════════════════════════════════════════════════
--  Color Notes: ColorNote-style sticky notes (text or checklist), each
--  with a colour, pin, reminder (optional repeat), archive and trash.
--
--  Run once in the Supabase SQL editor. Safe to re-run.
--
--  Deleting is soft, as everywhere in the app:
--    deleted_at  set  -> the note is in Trash (restorable)
--    purged_at   set  -> "Delete forever": hidden everywhere, row kept
--
--  Reminders: remind_at is an absolute time (timestamptz). The push
--  scheduler sends a notification when it passes; a repeating reminder
--  then moves remind_at to the next occurrence, a one-off clears it.
--  Dedupe uses the existing checklist_reminder_log table, so no other
--  table is needed.
-- ════════════════════════════════════════════════════════════════════

create table if not exists color_notes (
  id               uuid primary key default gen_random_uuid(),
  user_id          text not null,
  kind             text not null default 'text',      -- 'text' | 'checklist'
  title            text not null default '',
  body             text not null default '',          -- text notes
  items            jsonb not null default '[]'::jsonb, -- checklist: [{id, text, done}]
  color            text not null default 'yellow',    -- red|orange|yellow|green|blue|purple|black|gray|white
  is_pinned        boolean not null default false,
  is_archived      boolean not null default false,
  remind_at        timestamptz,
  remind_repeat    text not null default 'none',      -- none|daily|weekly|monthly|yearly
  last_reminded_at timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  purged_at        timestamptz
);

create index if not exists color_notes_user_idx
  on color_notes (user_id, updated_at desc)
  where purged_at is null;

create index if not exists color_notes_remind_idx
  on color_notes (user_id, remind_at)
  where remind_at is not null and deleted_at is null and purged_at is null;

alter table color_notes enable row level security;
