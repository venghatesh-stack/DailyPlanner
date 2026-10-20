-- ════════════════════════════════════════════════════════════════════
--  Turn on row-level security (RLS) for EVERY table in the public schema.
--
--  BEFORE YOU RUN THIS: the app must use Supabase's SECRET key
--  (service_role, starts with sb_secret_ or a JWT whose role is
--  service_role). That key bypasses RLS, so the app keeps working.
--  Check: open /admin/usage in the app. It must say
--  "Server key: secret (service role)". If it says public or unknown,
--  put the secret key in SUPABASE_KEY on Render and redeploy first.
--
--  What this does:
--    1. Enables RLS on every table (and partition) in public that lacks it.
--    2. Adds NO policies, so the public (anon) and authenticated keys can
--       read or write nothing. This app never talks to Supabase from the
--       browser, so nothing else needs them.
--    3. Tries to install an event trigger so tables created later get RLS
--       automatically. If your project does not allow event triggers it
--       just prints a notice; re-run this file after future migrations.
--    4. Lists any table still without RLS (should be none).
--
--  Safe to run again. To undo for one table:
--    alter table <name> disable row level security;
-- ════════════════════════════════════════════════════════════════════

-- 1. Enable RLS on every table in public that does not have it yet.
do $$
declare
  r record;
  n int := 0;
begin
  for r in
    select c.relname
    from pg_class c
    join pg_namespace ns on ns.oid = c.relnamespace
    where ns.nspname = 'public'
      and c.relkind in ('r', 'p')          -- tables and partitioned tables
      and not c.relrowsecurity
    order by c.relname
  loop
    execute format('alter table public.%I enable row level security', r.relname);
    n := n + 1;
    raise notice 'RLS enabled: %', r.relname;
  end loop;
  raise notice 'Done: RLS turned on for % table(s).', n;
end
$$;

-- 2. Future tables: enable RLS automatically when a table is created.
create or replace function public.rls_auto_enable()
returns event_trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
  cmd record;
begin
  for cmd in
    select * from pg_event_trigger_ddl_commands()
    where command_tag in ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      and object_type in ('table', 'partitioned table')
      and schema_name = 'public'
  loop
    execute format('alter table %s enable row level security', cmd.object_identity);
  end loop;
end
$$;

do $$
begin
  if not exists (select 1 from pg_event_trigger where evtname = 'rls_auto_enable') then
    create event trigger rls_auto_enable
      on ddl_command_end
      when tag in ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      execute function public.rls_auto_enable();
  end if;
exception when others then
  raise notice 'Could not create the auto-enable trigger (%). Re-run this file after adding tables.', sqlerrm;
end
$$;

-- 3. Check: this should return no rows.
select c.relname as table_without_rls
from pg_class c
join pg_namespace ns on ns.oid = c.relnamespace
where ns.nspname = 'public'
  and c.relkind in ('r', 'p')
  and not c.relrowsecurity
order by 1;
