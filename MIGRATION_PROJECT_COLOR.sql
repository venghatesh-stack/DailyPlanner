-- ============================================================
--  DailyPlanner — PROJECT COLOUR
--
--  Added 2026-10-11 with the redesign. The new-project form always
--  showed a row of colour swatches, but they were <div>s that were never
--  submitted and there was no column to keep the answer in. Now the
--  choice is saved and used for the project's card on /projects.
--
--  Values are plain '#rrggbb' — routes/projects.py rejects anything else
--  on the way in AND on the way out, because the colour is written into
--  an inline style.
--
--  Before this runs, creating a project still works: post() strips the
--  unknown column and retries. Projects just have no colour.
--
--  Safe to re-run.
-- ============================================================

alter table if exists projects
    add column if not exists color text;

-- Only hex colours, so a hand-edited row cannot put anything else into
-- the page. NOT VALID skips checking existing rows (there are none with a
-- colour yet) and keeps the statement instant on a big table.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'projects_color_is_hex'
  ) then
    alter table projects
      add constraint projects_color_is_hex
      check (color is null or color ~ '^#[0-9a-fA-F]{6}$') not valid;
  end if;
end $$;
