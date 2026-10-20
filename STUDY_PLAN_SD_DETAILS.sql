-- System design bootcamp: fill in every task field. Run after STUDY_PLAN_SD_5DAY.sql.
-- PART 3: fill in every field of the bootcamp tasks: a sprint per day,
-- due time, planned hours, Eisenhower = Do, and notes with tappable links.
-- Also sets the goal daily commitment (14 h) and deadline. Safe to run again.

drop table if exists _d;
create temp table _d(k text, kind text, arg text, due time, planned numeric, sp int);
insert into _d values
  ('url-shortener','card','','10:45',1.12,1),
  ('unique-id-generator','card','','10:45',1.12,1),
  ('api-rate-limiter','card','','13:15',1.12,1),
  ('distributed-cache','card','','13:15',1.12,1),
  ('read-heavy-cache','card','','16:15',0.75,1),
  ('cache-invalidation','card','','16:15',0.75,1),
  ('hot-key-counter','card','','16:15',0.75,1),
  ('distributed-kv-store','card','','18:45',2.25,1),
  ('object-storage-s3','card','','10:45',1.12,2),
  ('file-storage','card','','10:45',1.12,2),
  ('events-table-partitioning','card','','13:15',0.75,2),
  ('time-range-queries','card','','13:15',0.75,2),
  ('audit-log','card','','13:15',0.75,2),
  ('autocomplete','card','','16:15',1.12,2),
  ('ecommerce-search','card','','16:15',1.12,2),
  ('web-crawler','card','','18:45',1.12,2),
  ('geo-search-nearby','card','','18:45',1.12,2),
  ('distributed-message-queue','card','','10:45',1.12,3),
  ('idempotent-processing','card','','10:45',1.12,3),
  ('job-queue','card','','13:15',0.75,3),
  ('pubsub-notifications','card','','13:15',0.75,3),
  ('backpressure-pipeline','card','','13:15',0.75,3),
  ('order-processing-workflow','card','','16:15',1.12,3),
  ('payment-system','card','','16:15',1.12,3),
  ('messaging-app','card','','18:45',0.75,3),
  ('chat-presence','card','','18:45',0.75,3),
  ('websocket-scaling','card','','18:45',0.75,3),
  ('uber','card','','10:45',1.12,4),
  ('google-maps-navigation','card','','10:45',1.12,4),
  ('food-delivery','card','','13:15',1.12,4),
  ('news-feed','card','','13:15',1.12,4),
  ('follower-fanout','card','','16:15',0.75,4),
  ('ranked-timeline','card','','16:15',0.75,4),
  ('feed-notifications','card','','16:15',0.75,4),
  ('video-streaming','card','','18:45',0.75,4),
  ('media-cdn','card','','18:45',0.75,4),
  ('image-sharing','card','','18:45',0.75,4),
  ('flash-sale','card','','10:45',1.12,5),
  ('ticket-booking','card','','10:45',1.12,5),
  ('leaderboard','card','','13:15',0.75,5),
  ('ad-click-aggregation','card','','13:15',0.75,5),
  ('stock-exchange','card','','13:15',0.75,5),
  ('multi-region-dr','card','','16:15',0.38,5),
  ('retries-circuit-breakers','card','','16:15',0.38,5),
  ('graceful-degradation','card','','16:15',0.38,5),
  ('canary-deployments','card','','16:15',0.38,5),
  ('auth-sessions','card','','16:15',0.38,5),
  ('rbac-authorization','card','','16:15',0.38,5),
  ('Mock 1:','mock','url-shortener','20:15',0.75,1),
  ('Mock 2:','mock','autocomplete,ecommerce-search','20:15',0.75,2),
  ('Mock 3:','mock','messaging-app,chat-presence','20:15',0.75,3),
  ('Mock 4:','mock','uber,food-delivery','20:15',0.75,4),
  ('Mock 5:','mock','','17:45',1.0,5),
  ('Mock 6:','mock','payment-system,idempotent-processing','18:45',0.75,5),
  ('Concepts 1 to','concepts','1 to 10 (Scaling and traffic, caching)','08:00',0.5,1),
  ('Memory session 1 ','memory','1|url-shortener','07:30',1.5,1),
  ('Concepts 11 to','concepts','11 to 20 (Caching, databases, replication)','08:00',0.5,2),
  ('Memory session 2 ','memory','2|url-shortener,unique-id-generator,api-rate-limiter,distributed-cache,read-heavy-cache,cache-invalidation,hot-key-counter,distributed-kv-store','07:30',1.5,2),
  ('Concepts 21 to','concepts','21 to 30 (Consistency, consensus, messaging)','08:00',0.5,3),
  ('Memory session 3 ','memory','3|object-storage-s3,file-storage,events-table-partitioning,time-range-queries,audit-log,autocomplete,ecommerce-search,web-crawler,geo-search-nearby','07:30',1.5,3),
  ('Concepts 31 to','concepts','31 to 40 (Messaging, data flow, resilience)','08:00',0.5,4),
  ('Memory session 4 ','memory','4|distributed-message-queue,idempotent-processing,job-queue,pubsub-notifications,backpressure-pipeline,order-processing-workflow,payment-system,messaging-app,chat-presence,websocket-scaling','07:30',1.5,4),
  ('Concepts 41 to','concepts','41 to 50 (Resilience, observability, deployment, estimation)','08:00',0.5,5),
  ('Memory session 5 ','memory','5|','07:30',1.5,5);
drop table if exists _s;
create temp table _s(n int, name text, day date);
insert into _s values
  (1,'Day 1: Foundations and caching','2026-10-21'),
  (2,'Day 2: Storage and search','2026-10-22'),
  (3,'Day 3: Messaging and real time','2026-10-23'),
  (4,'Day 4: Classic products','2026-10-24'),
  (5,'Day 5: High-stakes systems and reliability','2026-10-25');

do $det$
declare
  b text := 'https://dailyplanner-zus3.onrender.com/interview-prep';
  nl text := chr(10);
  uid text; pid uuid; oid uuid; sid uuid; tid uuid;
  r record; s record; txt text; p text; ttl text;
  has_spr boolean := to_regclass('public.sprints') is not null
    and exists (select 1 from information_schema.columns where table_name = 'project_tasks' and column_name = 'sprint_id');
  sprint_ids uuid[] := array[]::uuid[];
begin
  select id::text into uid from users where email = 'venghatesh@gmail.com';
  select project_id into pid from projects where user_id = uid and name = 'System design bootcamp (21-25 Oct)'
    and coalesce(is_archived, false) = false limit 1;
  if pid is null then raise exception 'Run STUDY_PLAN_SD_5DAY.sql first: the bootcamp project is missing'; end if;

  if has_spr then
    for s in select * from _s order by n loop
      execute 'select id from sprints where user_id = $1 and project_id = $2 and name = $3 and coalesce(is_deleted,false) = false limit 1'
        into sid using uid, pid, s.name;
      if sid is null then
        execute 'insert into sprints (user_id, project_id, name, starts_on, ends_on, is_active, order_index) values ($1,$2,$3,$4,$4,$5,$6) returning id'
          into sid using uid, pid, s.name, s.day, s.n = 1, s.n;
      end if;
      sprint_ids := sprint_ids || sid;
    end loop;
  end if;

  for r in select * from _d loop
    if r.kind = 'card' then
      select task_id into tid from project_tasks where user_id = uid and project_id = pid
        and task_text like 'Recall card green:%' and notes like '%/design/' || r.k || '/recall%' limit 1;
      txt := 'Say the card from memory in P-N-H-B-D-F-C order in 3 minutes, then check it.' || nl
          || 'Card: ' || b || '/design/' || r.k || '/recall' || nl
          || 'Summary: ' || b || '/design/' || r.k || '/summary';
    else
      select task_id into tid from project_tasks where user_id = uid and project_id = pid
        and task_text like r.k || '%' limit 1;
      if r.kind = 'mock' then
        txt := 'Set a timer and design it out loud, following What to say: ' || b || '/guides/system-design-phrases' || nl
            || 'Afterwards compare with the card and write down 3 gaps.' || nl;
        if r.arg = '' then
          txt := txt || nl || 'Pick a design you have not studied: ' || b || '/design';
        else
          foreach p in array string_to_array(r.arg, ',') loop
            select substring(task_text from 'Recall card green: (.*)') into ttl from project_tasks
              where user_id = uid and project_id = pid and notes like '%/design/' || p || '/recall%' limit 1;
            txt := txt || nl || coalesce(ttl, p) || nl
                || '  Card: ' || b || '/design/' || p || '/recall' || nl
                || '  Summary: ' || b || '/design/' || p || '/summary';
          end loop;
        end if;
        txt := txt || nl || nl || 'All recall cards: ' || b || '/recall-cards';
      elsif r.kind = 'concepts' then
        txt := 'Concepts ' || r.arg || '. Read each one, cover it, say its Say it line aloud.' || nl
            || 'Open the guide: ' || b || '/guides/system-design-concepts' || nl
            || 'PDF for your phone: ' || b || '/guides/system-design-concepts/pdf';
      else
        txt := '1. Copy the Session ' || split_part(r.arg, '|', 1) || ' prompt: ' || b || '/guides/memory-techniques' || nl
            || '2. Download the cards and attach them to a new Claude chat: ' || b || '/recall-cards.pdf'
            || case when split_part(r.arg, '|', 2) <> '' then '?slugs=' || split_part(r.arg, '|', 2) else '' end || nl
            || '3. Paste the prompt and answer out loud.' || nl
            || 'New chat: https://claude.ai/new';
      end if;
    end if;
    if tid is null then
      raise notice 'Task not found for %', r.k;
      continue;
    end if;
    update project_tasks set due_time = r.due, planned_hours = r.planned, actual_hours = coalesce(actual_hours, 0),
           duration_days = 0, quadrant = 'do', priority = 'high', is_recurring = false,
           status = coalesce(nullif(status, ''), 'open'), notes = txt
     where task_id = tid;
    if has_spr then
      execute 'update project_tasks set sprint_id = $1 where task_id = $2' using sprint_ids[r.sp], tid;
    end if;
  end loop;

  select id into oid from objectives where user_id = uid and project_id = pid limit 1;
  if oid is not null then
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'daily_commit_minutes') then
      execute 'update objectives set daily_commit_minutes = 840 where id = $1' using oid;
    end if;
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'effort_minutes') then
      execute 'update objectives set effort_minutes = 4200 where id = $1' using oid;
    end if;
    if exists (select 1 from information_schema.columns where table_name = 'objectives' and column_name = 'target_at') then
      execute 'update objectives set target_at = ''2026-10-25 22:30:00+05:30'' where id = $1' using oid;
    end if;
  end if;
end
$det$;

-- Check: should show 64 tasks, 64 with links, 64 with a due time.
select count(*) as tasks,
       count(*) filter (where t.notes like '%https://%') as with_links,
       count(*) filter (where t.due_time is not null) as with_due_time
from project_tasks t join projects p on p.project_id = t.project_id
where p.name = 'System design bootcamp (21-25 Oct)';
