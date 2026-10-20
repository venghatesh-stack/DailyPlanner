-- Undo MIGRATION_ENABLE_RLS_ALL.sql: turn row-level security OFF for every
-- table in public and remove the auto-enable trigger. Use this when the app
-- runs with Supabase's PUBLIC (anon) key and stops seeing its data (for
-- example, nobody can sign in). Safe to run again.
drop event trigger if exists rls_auto_enable;
drop function if exists public.rls_auto_enable();

do $$
declare r record;
begin
  for r in
    select c.relname from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
    where ns.nspname = 'public' and c.relkind in ('r', 'p') and c.relrowsecurity
  loop
    execute format('alter table public.%I disable row level security', r.relname);
  end loop;
end
$$;

-- Should return no rows:
select c.relname as table_still_with_rls
from pg_class c join pg_namespace ns on ns.oid = c.relnamespace
where ns.nspname = 'public' and c.relkind in ('r', 'p') and c.relrowsecurity;
