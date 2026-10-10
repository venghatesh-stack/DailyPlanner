-- ============================================================
--  SCHEMA SNAPSHOT — run in each Supabase project's SQL editor,
--  then compare the two results with scripts/compare_schema.py.
--
--  Read-only: selects from the catalogs, changes nothing.
--  Returns ONE row, ONE column ("snapshot") of JSON covering the
--  public schema: tables, columns (type / null / default), primary,
--  unique, foreign-key and check constraints, indexes, RLS on/off and
--  policies, triggers, functions, views, and installed extensions.
--
--  In the Supabase SQL editor: run, click the result cell, copy, and
--  save it as e.g. schema_A.json (and schema_B.json for the other).
-- ============================================================

select jsonb_pretty(jsonb_build_object(
  'tables', (
    select coalesce(jsonb_object_agg(c.relname, jsonb_build_object(
      'rls', c.relrowsecurity,
      'columns', (
        select jsonb_object_agg(a.attname, jsonb_build_object(
          'type', format_type(a.atttypid, a.atttypmod),
          'not_null', a.attnotnull,
          'default', pg_get_expr(d.adbin, d.adrelid)))
        from pg_attribute a
        left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
        where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped),
      'constraints', (
        select coalesce(jsonb_object_agg(con.conname, pg_get_constraintdef(con.oid)), '{}'::jsonb)
        from pg_constraint con where con.conrelid = c.oid),
      'indexes', (
        select coalesce(jsonb_object_agg(i.indexname, i.indexdef), '{}'::jsonb)
        from pg_indexes i where i.schemaname = 'public' and i.tablename = c.relname),
      'policies', (
        select coalesce(jsonb_object_agg(p.policyname, jsonb_build_object(
          'cmd', p.cmd, 'roles', p.roles, 'using', p.qual, 'check', p.with_check)), '{}'::jsonb)
        from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname),
      'triggers', (
        select coalesce(jsonb_object_agg(t.tgname, pg_get_triggerdef(t.oid)), '{}'::jsonb)
        from pg_trigger t where t.tgrelid = c.oid and not t.tgisinternal)
    )), '{}'::jsonb)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('r', 'p')),
  'views', (
    select coalesce(jsonb_object_agg(v.viewname, v.definition), '{}'::jsonb)
    from pg_views v where v.schemaname = 'public'),
  'functions', (
    select coalesce(jsonb_object_agg(p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')',
                                     md5(pg_get_functiondef(p.oid))), '{}'::jsonb)
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prokind in ('f', 'p')),
  'extensions', (
    select coalesce(jsonb_object_agg(e.extname, e.extversion), '{}'::jsonb)
    from pg_extension e)
)) as snapshot;
