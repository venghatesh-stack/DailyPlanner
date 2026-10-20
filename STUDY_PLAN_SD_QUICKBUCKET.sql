-- System design bootcamp: put the 64 tasks in the Quick Bucket.
-- Today's tasks go in "Now"; each later day's tasks wait in "Future" and
-- move to "Now" on their own day (needs app v346). Ticking one in the
-- bucket also ticks the project task. Safe to run again: no duplicates.

alter table quick_bucket add column if not exists source_task_id uuid;
alter table quick_bucket add column if not exists backlog_due date;

do $qb$
declare
  uid text; pid uuid; t record; n int := 0;
  today date := (now() at time zone 'Asia/Kolkata')::date;
  has_pm boolean := exists (select 1 from information_schema.columns
                            where table_name = 'quick_bucket' and column_name = 'planned_minutes');
begin
  select id::text into uid from users where email = 'venghatesh@gmail.com';
  select project_id into pid from projects where user_id = uid
    and name = 'System design bootcamp (21-25 Oct)' and coalesce(is_archived, false) = false limit 1;
  if pid is null then raise exception 'Bootcamp project not found: run STUDY_PLAN_SD_5DAY.sql first'; end if;

  for t in
    select task_id, task_text, due_date, due_time, planned_hours,
           row_number() over (order by due_date, due_time, task_text) as pos
    from project_tasks
    where user_id = uid and project_id = pid and coalesce(status, 'open') <> 'done'
      and coalesce(is_eliminated, false) = false
  loop
    if exists (select 1 from quick_bucket where source_task_id = t.task_id and coalesce(is_deleted, false) = false) then
      continue;
    end if;
    execute 'insert into quick_bucket (user_id, text, time_bucket, is_done, is_deleted, position, source_task_id, backlog_due'
         || case when has_pm then ', planned_minutes' else '' end || ') values ($1::uuid, $2, $3, false, false, $4, $5, $6'
         || case when has_pm then ', $7' else '' end || ')'
      using uid, left(t.task_text, 500),
            case when t.due_date <= today then 'now' else 'future' end,
            t.pos, t.task_id, t.due_date, round(coalesce(t.planned_hours, 0) * 60)::int;
    n := n + 1;
  end loop;
  raise notice 'Added % task(s) to the Quick Bucket', n;
end
$qb$;

-- Check: today's tasks in Now, the rest in Future.
select time_bucket, count(*) from quick_bucket q
join project_tasks t on t.task_id = q.source_task_id
join projects p on p.project_id = t.project_id
where p.name = 'System design bootcamp (21-25 Oct)' and coalesce(q.is_deleted, false) = false
group by 1 order by 1;
