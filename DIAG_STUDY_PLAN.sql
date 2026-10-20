-- Diagnostic for the System design bootcamp. Read-only: changes nothing.
-- Run in the Supabase SQL editor and send the one row it returns.
with u as (select id::text as uid from users where email = 'venghatesh@gmail.com'),
p as (select project_id, user_id from projects where name = 'System design bootcamp (21-25 Oct)')
select
  (select uid from u)                                                          as my_user_id,
  (select count(*) from p)                                                     as bootcamp_projects,
  (select string_agg(distinct user_id, ',') from p)                            as project_owner,
  (select count(*) from project_tasks t where t.project_id in (select project_id from p)) as tasks,
  (select count(*) from project_tasks t where t.project_id in (select project_id from p) and t.due_time is not null) as with_due_time,
  (select count(*) from project_tasks t where t.project_id in (select project_id from p) and t.notes like '%Card: https%') as with_new_links,
  (select count(*) from project_tasks t where t.project_id in (select project_id from p) and coalesce(t.is_eliminated, false) = false) as not_eliminated,
  (select count(*) from project_tasks t where t.project_id in (select project_id from p) and t.user_id = (select uid from u)) as owned_by_me,
  (select count(*) from daily_events e where e.user_id = (select uid from u) and e.plan_date between '2026-10-21' and '2026-10-25'
      and (e.title like '📚 %' or e.title like '🧠 %') and coalesce(e.is_deleted, false) = false) as calendar_blocks,
  (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind in ('r','p') and c.relrowsecurity) as tables_with_rls;
