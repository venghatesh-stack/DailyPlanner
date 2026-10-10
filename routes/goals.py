"""
OKRs — 6-layer strategic hierarchy tied to the app's Project model.

    Project        (existing — the top container)
      └─ Objective        (strategic intent under a project)
           └─ Key Result  (measurable outcome proving the objective)
                └─ Initiative       (workstream grouping of tasks)
                     └─ Task        (project_tasks.initiative_id)
                          └─ Subtask (inherits parent task's initiative)

Design notes:
  * Objective.project_id is NULLABLE. Objectives without a project render
    in an "Unassigned" bucket on the /goals page for personal strategy.
  * Tasks now link to an Initiative (not directly to a KR). The task's
    KR and objective are resolved by walking up: task → initiative →
    key_result → objective. The legacy project_tasks.key_result_id
    column is preserved for backward compat but new code writes only
    initiative_id.
  * Progress is MANUAL for v1 — the user edits `current_value` on each
    KR. `progress_source` is reserved for a v2 auto roll-up.
  * Goal→Objective renaming: what earlier iterations called a "Goal" is
    now an "Objective" across the whole codebase. This route's file
    name is kept as routes/goals.py and its blueprint keeps the URL
    prefix "/goals" only so existing bookmarks and nav entries stay
    valid. Every internal noun is "objective".

─────────────────────────────────────────────────────────────────────
SCHEMA MIGRATION — run in Supabase
─────────────────────────────────────────────────────────────────────

-- Fresh install (no prior OKR schema present):

    create table if not exists objectives (
      id           uuid primary key default gen_random_uuid(),
      user_id      uuid not null,
      project_id   uuid references projects(project_id) on delete cascade,
      title        text not null,
      description  text,
      category     text,
      time_horizon text,                    -- annual | quarterly | monthly | ongoing
      start_date   date,
      target_date  date,
      status       text default 'active',   -- active | achieved | paused | abandoned
      color        text,
      order_index  int default 0,
      created_at   timestamptz default now()
    );
    create index if not exists objectives_user_idx    on objectives (user_id, status);
    create index if not exists objectives_project_idx on objectives (project_id);

    create table if not exists key_results (
      id              uuid primary key default gen_random_uuid(),
      user_id         uuid not null,
      objective_id    uuid not null references objectives(id) on delete cascade,
      title           text not null,
      metric_type     text,
      unit            text,
      start_value     numeric default 0,
      current_value   numeric default 0,
      target_value    numeric not null,
      direction       text default 'up',
      progress_source text default 'manual',
      order_index     int default 0,
      created_at      timestamptz default now()
    );
    create index if not exists kr_objective_idx on key_results (objective_id);

    create table if not exists initiatives (
      id            uuid primary key default gen_random_uuid(),
      user_id       uuid not null,
      key_result_id uuid not null references key_results(id) on delete cascade,
      title         text not null,
      description   text,
      status        text default 'active',
      order_index   int default 0,
      created_at    timestamptz default now()
    );
    create index if not exists initiatives_kr_idx on initiatives (key_result_id);

    alter table project_tasks
      add column if not exists initiative_id uuid references initiatives(id) on delete set null;
    create index if not exists project_tasks_initiative_idx on project_tasks (initiative_id);

    -- Legacy direct-KR column — kept for backward compat with earlier
    -- iterations. New code writes initiative_id, reads resolve the KR
    -- via the initiative. Safe to drop once no rows reference it:
    --   alter table project_tasks drop column if exists key_result_id;

-- Upgrading from the previous Project→Goal→KR schema (the one that had
-- a `goals` table with goal_id on key_results):

    -- 1) Rename goals table and its columns/indexes:
    alter table goals rename to objectives;
    alter index if exists goals_user_idx rename to objectives_user_idx;
    alter index if exists goals_project_idx rename to objectives_project_idx;

    -- 2) Rename key_results.goal_id → key_results.objective_id
    alter table key_results drop constraint if exists key_results_goal_fkey;
    alter table key_results rename column goal_id to objective_id;
    alter table key_results
      add constraint key_results_objective_fkey
      foreign key (objective_id) references objectives(id) on delete cascade;
    alter index if exists kr_goal_idx rename to kr_objective_idx;

    -- 3) Create initiatives table:
    create table if not exists initiatives (
      id            uuid primary key default gen_random_uuid(),
      user_id       uuid not null,
      key_result_id uuid not null references key_results(id) on delete cascade,
      title         text not null,
      description   text,
      status        text default 'active',
      order_index   int default 0,
      created_at    timestamptz default now()
    );
    create index if not exists initiatives_kr_idx on initiatives (key_result_id);

    -- 4) Add initiative_id to project_tasks:
    alter table project_tasks
      add column if not exists initiative_id uuid references initiatives(id) on delete set null;
    create index if not exists project_tasks_initiative_idx on project_tasks (initiative_id);

    -- 5) OPTIONAL data migration: if any tasks had a direct key_result_id,
    --    create a "General" initiative under each referenced KR and point
    --    those tasks at it. Skip if you want to manage the migration by hand.
    --
    --    insert into initiatives (user_id, key_result_id, title)
    --      select distinct user_id, key_result_id, 'General'
    --      from project_tasks
    --      where key_result_id is not null
    --      on conflict do nothing;
    --
    --    update project_tasks pt
    --       set initiative_id = (
    --         select id from initiatives i
    --          where i.key_result_id = pt.key_result_id and i.title = 'General'
    --          limit 1
    --       )
    --     where pt.initiative_id is null and pt.key_result_id is not null;

─────────────────────────────────────────────────────────────────────
"""

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, render_template, request, session

from config import SIMPLE_GOALS
from services.login_service import login_required
from supabase_client import get, post, update

logger = logging.getLogger("daily_plan")
goals_bp = Blueprint("goals", __name__)

_VALID_OBJECTIVE_STATUSES = {"active", "achieved", "paused", "abandoned"}
_VALID_HORIZONS = {"annual", "quarterly", "monthly", "ongoing"}
_VALID_DIRECTIONS = {"up", "down"}

# Every read filters this out. Every "delete" is a soft delete that
# flips this to true and stamps deleted_at. Restore is possible via
# the normal PATCH endpoint by sending {"is_deleted": false}.
_NOT_DELETED = {"is_deleted": "eq.false"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _soft_delete(table, params):
    """Soft-delete rows by flipping is_deleted=true and stamping deleted_at.

    Never falls back to a hard DELETE — if the schema is missing the
    soft-delete columns the exception will propagate and the caller
    returns a 500 with a real error message. The migration in the
    header docstring of this file must be run before soft-delete works.
    """
    update(table, params=params, json={"is_deleted": True, "deleted_at": _now_iso()})


# ──────────────────────────────────────────────────────────────────────
# PAGE RENDER
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/goals")
@login_required
def goals_page():
    # SIMPLE_GOALS was already True and already honoured by the project
    # tasks page, which hides the Epic and Initiative pickers. This page
    # never read it, so /goals was the one place still presenting the full
    # Project -> Objective -> Key Result -> Initiative -> Task ladder.
    return render_template("goals.html", simple_goals=SIMPLE_GOALS)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _task_progress(user_id, objective_ids):
    """Done-task share per objective, from project_tasks.objective_id.

    This is the progress that maintains itself. MIGRATION_TASK_OBJECTIVE
    put objective_id on project_tasks and backfilled it through the
    initiative -> key_result -> objective walk, so a goal already knows
    which tasks belong to it — there is no reason to make anyone type a
    percentage the app can count.

    "Done" is `status == "done"`, which is how the projects list computes
    completion_pct. Deliberately the same definition rather than a second
    one: three different answers to "what is finished" is a bug this
    codebase has paid for before.

    Returns {objective_id: (done, total)} and never raises — a goal page
    that 500s because this query failed would be a worse outcome than one
    showing no task figure. get() has no PGRST204 retry, unlike
    post/update, so a missing column here is a hard 400.
    """
    if not objective_ids:
        return {}
    try:
        rows = get("project_tasks", params={
            "user_id": f"eq.{user_id}",
            "objective_id": f"in.({','.join(objective_ids)})",
            "is_deleted": "eq.false",
            "select": "objective_id,status",
            "limit": 5000,
        }) or []
    except Exception as e:                                  # noqa: BLE001
        logger.warning("_task_progress failed, falling back: %s", e)
        return {}
    out = {}
    for r in rows:
        oid = r.get("objective_id")
        if not oid:
            continue
        done, total = out.get(oid, (0, 0))
        out[oid] = (done + (1 if r.get("status") == "done" else 0), total + 1)
    return out


def _kr_progress(kr):
    start = float(kr.get("start_value") or 0)
    current = float(kr.get("current_value") or 0)
    target = float(kr.get("target_value") or 0)
    direction = kr.get("direction", "up")
    if target == start:
        return 0.0
    if direction == "up":
        pct = (current - start) / (target - start)
    else:
        pct = (start - current) / (start - target)
    return max(0.0, min(1.0, pct)) * 100.0


def recompute_kr_auto_progress(user_id, kr_id):
    """When a KR has auto_progress=true, derive current_value from the
    share of completed project_tasks that ladder up to it.

      current_value = start + (target - start) * (done / total)

    Tasks linked to one of the KR's initiatives count. Tasks linked
    directly via key_result_id (legacy) also count.

    Silently no-ops if auto_progress is false or the column doesn't
    exist (pre-migration). Logs failures but never raises — task
    toggles must not be blocked by KR roll-up issues.
    """
    try:
        kr_rows = get(
            "key_results",
            params={
                "id": f"eq.{kr_id}",
                "user_id": f"eq.{user_id}",
                "select": "id,start_value,target_value,auto_progress",
            },
        ) or []
        if not kr_rows:
            return
        kr = kr_rows[0]
        if not kr.get("auto_progress"):
            return

        # Collect all initiative ids under this KR
        init_rows = get(
            "initiatives",
            params={
                "key_result_id": f"eq.{kr_id}",
                "user_id": f"eq.{user_id}",
                "select": "id",
            },
        ) or []
        init_ids = [r["id"] for r in init_rows]

        # Count tasks linked via initiative OR (legacy) directly via KR.
        # Two queries summed for clarity — both small (per-user scope).
        total_done = 0
        total_all = 0

        if init_ids:
            ids_csv = ",".join(str(i) for i in init_ids)
            t_rows = get(
                "project_tasks",
                params={
                    "user_id": f"eq.{user_id}",
                    "is_deleted": "eq.false",
                    "is_eliminated": "eq.false",
                    "initiative_id": f"in.({ids_csv})",
                    "select": "task_id,status",
                },
            ) or []
            total_all += len(t_rows)
            total_done += sum(1 for r in t_rows if r.get("status") == "done")

        # Legacy: tasks linked directly via key_result_id (no initiative)
        legacy_rows = get(
            "project_tasks",
            params={
                "user_id": f"eq.{user_id}",
                "is_deleted": "eq.false",
                "is_eliminated": "eq.false",
                "key_result_id": f"eq.{kr_id}",
                "initiative_id": "is.null",
                "select": "task_id,status",
            },
        ) or []
        total_all += len(legacy_rows)
        total_done += sum(1 for r in legacy_rows if r.get("status") == "done")

        if total_all == 0:
            new_current = float(kr.get("start_value") or 0)
        else:
            start = float(kr.get("start_value") or 0)
            target = float(kr.get("target_value") or 0)
            ratio = total_done / total_all
            new_current = start + (target - start) * ratio

        update(
            "key_results",
            params={"id": f"eq.{kr_id}", "user_id": f"eq.{user_id}"},
            json={"current_value": round(new_current, 2)},
        )
    except Exception as e:
        # Don't let KR roll-up break a task toggle. Log + move on.
        import logging
        logging.getLogger(__name__).warning(
            "recompute_kr_auto_progress(%s) failed: %s", kr_id, e
        )


def recompute_kr_auto_progress_for_task(user_id, project_task_id):
    """Resolve the KR(s) a project task ladders up to and recompute.

    A task may link via initiative_id (preferred) or legacy key_result_id.
    Either path triggers a recompute of the parent KR.
    """
    try:
        rows = get(
            "project_tasks",
            params={
                "task_id": f"eq.{project_task_id}",
                "user_id": f"eq.{user_id}",
                "select": "initiative_id,key_result_id",
            },
        ) or []
        if not rows:
            return
        r = rows[0]
        kr_id = r.get("key_result_id")
        if not kr_id and r.get("initiative_id"):
            init_rows = get(
                "initiatives",
                params={"id": f"eq.{r['initiative_id']}", "select": "key_result_id"},
            ) or []
            if init_rows:
                kr_id = init_rows[0].get("key_result_id")
        if kr_id:
            recompute_kr_auto_progress(user_id, kr_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "recompute_kr_auto_progress_for_task(%s) failed: %s", project_task_id, e
        )


def _project_map(user_id):
    rows = get(
        "projects",
        params={"user_id": f"eq.{user_id}", "select": "project_id,name"},
    ) or []
    return {r["project_id"]: r["name"] for r in rows}


# ──────────────────────────────────────────────────────────────────────
# PICKER — used by the task-card Initiative dropdown
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/api/goals/picker")
@login_required
def picker():
    """
    Return active objectives → KRs → initiatives, optionally scoped to a project.

    Query params:
      project_id=<uuid>       limit to one project
      include_unassigned=1    also include objectives with no project_id
    """
    user_id = session["user_id"]
    project_id = request.args.get("project_id")
    include_unassigned = request.args.get("include_unassigned") == "1"

    objectives = get(
        "objectives",
        params={
            "user_id": f"eq.{user_id}",
            "status": "eq.active",
            "is_deleted": "eq.false",
            "select": "id,project_id,title,color,category,target_date",
            "order": "order_index.asc,created_at.asc",
            "limit": 500,
        },
    ) or []

    if project_id:
        if include_unassigned:
            objectives = [o for o in objectives if o.get("project_id") in (project_id, None)]
        else:
            objectives = [o for o in objectives if o.get("project_id") == project_id]

    if not objectives:
        return jsonify({"objectives": []})

    objective_ids = [o["id"] for o in objectives]
    krs = get(
        "key_results",
        params={
            "user_id": f"eq.{user_id}",
            "objective_id": f"in.({','.join(objective_ids)})",
            "is_deleted": "eq.false",
            "select": "id,objective_id,title,unit,current_value,target_value,direction",
            "order": "order_index.asc,created_at.asc",
            "limit": 2000,
        },
    ) or []

    kr_ids = [k["id"] for k in krs]
    initiatives = []
    if kr_ids:
        initiatives = get(
            "initiatives",
            params={
                "user_id": f"eq.{user_id}",
                "key_result_id": f"in.({','.join(kr_ids)})",
                "status": "eq.active",
                "is_deleted": "eq.false",
                "select": "id,key_result_id,title",
                "order": "order_index.asc,created_at.asc",
                "limit": 5000,
            },
        ) or []

    result = []
    for o in objectives:
        obj_krs = [k for k in krs if k["objective_id"] == o["id"]]
        result.append({
            "id": o["id"],
            "title": o["title"],
            "project_id": o.get("project_id"),
            "color": o.get("color"),
            "category": o.get("category"),
            "target_date": o.get("target_date"),
            "key_results": [
                {
                    "id": kr["id"],
                    "title": kr["title"],
                    "unit": kr.get("unit"),
                    "current_value": kr.get("current_value"),
                    "target_value": kr.get("target_value"),
                    "direction": kr.get("direction", "up"),
                    "initiatives": [
                        {"id": i["id"], "title": i["title"]}
                        for i in initiatives if i["key_result_id"] == kr["id"]
                    ],
                }
                for kr in obj_krs
            ],
        })

    return jsonify({"objectives": result})


# ──────────────────────────────────────────────────────────────────────
# FULL TREE — used by the /goals (OKRs) page
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/api/goals", methods=["GET"])
@login_required
def list_objectives():
    """
    Return objectives with nested KRs, nested initiatives, and computed progress.

    Query params:
      project_id=<uuid>       filter to one project
      include_archived=1      also surface paused/abandoned/achieved
      include_unassigned=1    also include objectives with no project_id
    """
    user_id = session["user_id"]
    project_id = request.args.get("project_id")
    include_archived = request.args.get("include_archived") == "1"
    include_unassigned = request.args.get("include_unassigned") == "1"

    params = {
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "select": "*",
        "order": "order_index.asc,created_at.asc",
        "limit": 500,
    }
    if not include_archived:
        params["status"] = "eq.active"

    objectives = get("objectives", params=params) or []

    if project_id:
        if include_unassigned:
            objectives = [o for o in objectives if o.get("project_id") in (project_id, None)]
        else:
            objectives = [o for o in objectives if o.get("project_id") == project_id]

    pmap = _project_map(user_id)

    if not objectives:
        return jsonify({
            "objectives": [],
            "projects": sorted(pmap.items(), key=lambda x: x[1].lower()),
        })

    objective_ids = [o["id"] for o in objectives]
    krs = get(
        "key_results",
        params={
            "user_id": f"eq.{user_id}",
            "objective_id": f"in.({','.join(objective_ids)})",
            "is_deleted": "eq.false",
            "select": "*",
            "order": "order_index.asc,created_at.asc",
            "limit": 5000,
        },
    ) or []

    kr_ids = [k["id"] for k in krs]
    initiatives = []
    if kr_ids:
        initiatives = get(
            "initiatives",
            params={
                "user_id": f"eq.{user_id}",
                "key_result_id": f"in.({','.join(kr_ids)})",
                "is_deleted": "eq.false",
                "select": "*",
                "order": "order_index.asc,created_at.asc",
                "limit": 5000,
            },
        ) or []

    # Attach initiatives to their KRs, then compute progress bottom-up.
    for k in krs:
        k["initiatives"] = [i for i in initiatives if i["key_result_id"] == k["id"]]
        k["_progress"] = _kr_progress(k)

    task_counts = _task_progress(user_id, objective_ids)

    for o in objectives:
        o["key_results"] = [k for k in krs if k["objective_id"] == o["id"]]
        rolled = (
            sum(k["_progress"] for k in o["key_results"]) / len(o["key_results"])
            if o["key_results"] else 0
        )
        done, total = task_counts.get(o["id"], (0, 0))
        o["_task_done"], o["_task_total"] = done, total
        from_tasks = round(done / total * 100) if total else None
        # SAME PRECEDENCE AS THE PLANNER: a typed percentage wins, else the
        # key-result roll-up, else nothing. This endpoint used to return the
        # roll-up and only the roll-up, which meant /goals showed 0% for
        # every goal that had no key results — and measured on live data,
        # key results whose current_value had ever moved was 0 of 28. So the
        # progress bar on this page was permanently empty, and a percentage
        # typed on /goal-planner (which does honour manual_progress) was
        # invisible here. See _objective_progress() for the same rule.
        # PRECEDENCE: typed, then its own tasks, then key results, then nothing.
        #
        # Tasks come before key results because tasks are what this app
        # actually holds — 120 of them linked, against key results whose
        # current_value had ever moved being 0 of 28. A number the app can
        # count beats one somebody has to remember to update.
        #
        # A typed value still wins outright: they looked at the goal and
        # made a judgement, and overruling that would make the field
        # pointless. Clearing it drops back down this list.
        typed = o.get("manual_progress")
        if typed is not None:
            o["_progress"] = max(0, min(100, int(typed)))
            o["_progress_source"] = "manual"
        elif from_tasks is not None:
            o["_progress"] = from_tasks
            o["_progress_source"] = "tasks"
        elif o["key_results"]:
            o["_progress"] = round(rolled)
            o["_progress_source"] = "key_results"
        else:
            o["_progress"] = 0
            o["_progress_source"] = "none"
        # What the automatic sources say, so the UI can offer the way back
        # from a typed override instead of hiding the disagreement.
        o["_from_tasks"] = from_tasks
        # Kept alongside so the UI can show the disagreement rather than
        # hiding it when someone has typed over a live roll-up.
        o["_rolled_up"] = round(rolled)
        o["project_name"] = pmap.get(o.get("project_id")) if o.get("project_id") else None

    return jsonify({
        "objectives": objectives,
        "projects": sorted(pmap.items(), key=lambda x: x[1].lower()),
    })


# ──────────────────────────────────────────────────────────────────────
# OBJECTIVES CRUD
# Route paths kept under /api/goals/* for URL backward compat.
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/api/goals", methods=["POST"])
@login_required
def create_objective():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400

    horizon = (data.get("time_horizon") or "ongoing").strip().lower()
    if horizon not in _VALID_HORIZONS:
        horizon = "ongoing"

    payload = {
        "user_id": session["user_id"],
        "project_id": data.get("project_id") or None,
        "title": title,
        "description": (data.get("description") or "").strip() or None,
        "category": (data.get("category") or "").strip() or None,
        "time_horizon": horizon,
        "start_date": data.get("start_date") or None,
        "target_date": data.get("target_date") or None,
        "color": (data.get("color") or "").strip() or None,
        "status": "active",
    }
    rows = post("objectives", payload)
    return jsonify({"status": "ok", "objective": rows[0] if rows else None})


@goals_bp.route("/api/goals/<objective_id>", methods=["PATCH"])
@login_required
def update_objective(objective_id):
    data = request.get_json(force=True) or {}
    allowed = {
        "project_id", "title", "description", "category", "time_horizon",
        "start_date", "target_date", "status", "color", "order_index",
        "is_deleted",  # allow restore via PATCH {is_deleted: false}
        # A typed percentage. The planner could already write this; the OKR
        # page could not, so the only way to make a goal show progress there
        # was to create a key result and hand-edit its current value — which
        # the live data says nobody ever did.
        "manual_progress",
    }
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400

    if "manual_progress" in patch:
        cleaned, err = _clean_manual_progress(patch["manual_progress"])
        if err:
            return jsonify({"error": err}), 400
        patch["manual_progress"] = cleaned

    if "project_id" in patch and patch["project_id"] == "":
        patch["project_id"] = None
    if "status" in patch and patch["status"] not in _VALID_OBJECTIVE_STATUSES:
        return jsonify({"error": "invalid status"}), 400
    if "time_horizon" in patch and patch["time_horizon"] not in _VALID_HORIZONS:
        return jsonify({"error": "invalid time_horizon"}), 400

    # Clear deleted_at when restoring
    if patch.get("is_deleted") is False:
        patch["deleted_at"] = None

    update(
        "objectives",
        params={"id": f"eq.{objective_id}", "user_id": f"eq.{session['user_id']}"},
        json=patch,
    )
    return jsonify({"status": "ok"})


@goals_bp.route("/api/goals/<objective_id>", methods=["DELETE"])
@login_required
def delete_objective(objective_id):
    """
    Soft delete an objective. Cascades in application code to every
    KR under the objective and every initiative under those KRs.
    Row data is preserved — restore via PATCH {is_deleted: false}.
    """
    user_id = session["user_id"]

    try:
        # 1) Fetch live KRs under this objective so we can cascade
        #    the soft-delete down to initiatives.
        krs = get(
            "key_results",
            params={
                "user_id": f"eq.{user_id}",
                "objective_id": f"eq.{objective_id}",
                "is_deleted": "eq.false",
                "select": "id",
                "limit": 500,
            },
        ) or []
        kr_ids = [k["id"] for k in krs]

        # 2) Cascade: initiatives under those KRs
        if kr_ids:
            _soft_delete(
                "initiatives",
                params={
                    "user_id": f"eq.{user_id}",
                    "key_result_id": f"in.({','.join(kr_ids)})",
                },
            )
            # 3) Cascade: the KRs themselves
            _soft_delete(
                "key_results",
                params={
                    "user_id": f"eq.{user_id}",
                    "id": f"in.({','.join(kr_ids)})",
                },
            )

        # 4) Finally, the objective itself
        _soft_delete(
            "objectives",
            params={"id": f"eq.{objective_id}", "user_id": f"eq.{user_id}"},
        )
    except Exception as e:
        logger.exception("delete_objective failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500

    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────
# KEY RESULTS CRUD
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/api/key-results", methods=["POST"])
@login_required
def create_key_result():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    objective_id = data.get("objective_id")
    target_value = data.get("target_value")

    if not title or not objective_id:
        return jsonify({"error": "title and objective_id required"}), 400
    try:
        target_value = float(target_value)
    except (TypeError, ValueError):
        return jsonify({"error": "target_value must be a number"}), 400

    direction = (data.get("direction") or "up").strip().lower()
    if direction not in _VALID_DIRECTIONS:
        direction = "up"

    payload = {
        "user_id": session["user_id"],
        "objective_id": objective_id,
        "title": title,
        "metric_type": (data.get("metric_type") or "count").strip().lower() or "count",
        "unit": (data.get("unit") or "").strip() or None,
        "start_value": float(data.get("start_value") or 0),
        "current_value": float(data.get("current_value") or 0),
        "target_value": target_value,
        "direction": direction,
        "progress_source": "manual",
    }
    rows = post("key_results", payload)
    return jsonify({"status": "ok", "key_result": rows[0] if rows else None})


@goals_bp.route("/api/key-results/<kr_id>", methods=["PATCH"])
@login_required
def update_key_result(kr_id):
    data = request.get_json(force=True) or {}
    allowed = {
        "title", "metric_type", "unit",
        "start_value", "current_value", "target_value",
        "direction", "order_index",
        "is_deleted",
        "auto_progress",  # opt-in to KR roll-up from completed tasks
    }
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400

    for numeric_key in ("start_value", "current_value", "target_value"):
        if numeric_key in patch:
            try:
                patch[numeric_key] = float(patch[numeric_key])
            except (TypeError, ValueError):
                return jsonify({"error": f"{numeric_key} must be a number"}), 400

    if "direction" in patch and patch["direction"] not in _VALID_DIRECTIONS:
        return jsonify({"error": "invalid direction"}), 400

    if patch.get("is_deleted") is False:
        patch["deleted_at"] = None

    # A new current value is a check-in, wherever it was typed. Stamp it
    # and keep the history, so "last updated 9 days ago" on /goals/check-in
    # is true for edits made inline on /goals too.
    previous = None
    if "current_value" in patch:
        patch["last_checked_at"] = _now_iso()
        previous = _kr_snapshot(session["user_id"], kr_id)

    update(
        "key_results",
        params={"id": f"eq.{kr_id}", "user_id": f"eq.{session['user_id']}"},
        json=patch,
    )
    if "current_value" in patch:
        _log_checkin(session["user_id"], kr_id,
                     (previous or {}).get("objective_id"),
                     patch["current_value"],
                     (previous or {}).get("current_value"),
                     None)
    # If we just turned auto_progress on, recompute immediately so the
    # KR's current_value reflects today's task completions.
    if patch.get("auto_progress") is True:
        recompute_kr_auto_progress(session["user_id"], kr_id)
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────
# WEEKLY CHECK-IN
#
# One screen that walks every key result you have to update by hand, so
# the numbers get touched once a week instead of never. Measured before
# this existed: 0 of 28 key results had ever moved. The check-in does not
# make anyone keep key results — goals still count their tasks first
# (see list_objectives) — it makes the ones you DO keep cheap to update.
#
# Key results with auto_progress are shown but not asked about: their
# value comes from linked tasks, so typing over it would be overwritten by
# the next task toggle.
#
# Needs MIGRATION_KR_CHECKINS.sql for "last updated" and the history.
# Without it the check-in still saves values; the timestamp column is
# stripped by update()'s PGRST204 retry and the history insert is skipped.
# ──────────────────────────────────────────────────────────────────────

#: A hand-kept key result untouched for this long is flagged on the
#: check-in screen. A week, because the check-in is weekly.
_CHECKIN_STALE_DAYS = 7


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _kr_snapshot(user_id, kr_id):
    """The row as it is before an update — for previous_value. Never raises."""
    try:
        rows = get("key_results", params={
            "id": f"eq.{kr_id}",
            "user_id": f"eq.{user_id}",
            "select": "id,objective_id,current_value",
        }) or []
        return rows[0] if rows else None
    except Exception as e:                                  # noqa: BLE001
        logger.warning("kr snapshot failed: %s", e)
        return None


def _log_checkin(user_id, kr_id, objective_id, value, previous_value, note):
    """Append one history row. Best-effort: a missing kr_checkins table
    (migration not run yet) must cost the history, not the save."""
    try:
        post("kr_checkins", {
            "user_id": user_id,
            "key_result_id": kr_id,
            "objective_id": objective_id,
            "value": value,
            "previous_value": previous_value,
            "note": note or None,
        })
    except Exception as e:                                  # noqa: BLE001
        logger.info("kr_checkins insert skipped (run MIGRATION_KR_CHECKINS.sql?): %s", e)


@goals_bp.route("/goals/check-in")
@login_required
def checkin_page():
    return render_template("goals_checkin.html")


@goals_bp.route("/api/goals/check-in", methods=["GET"])
@login_required
def checkin_data():
    """Active goals that have key results, each key result with what the
    check-in needs: current value, unit, direction, whether it is filled
    in from tasks, and how long since it last moved."""
    user_id = session["user_id"]
    objectives = get("objectives", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "status": "eq.active",
        "select": "id,title,target_date,is_default",
        "order": "order_index.asc,created_at.asc",
        "limit": 500,
    }) or []
    objectives = [o for o in objectives if not o.get("is_default")]
    if not objectives:
        return jsonify({"goals": [], "to_update": 0, "stale_days": _CHECKIN_STALE_DAYS})

    krs = get("key_results", params={
        "user_id": f"eq.{user_id}",
        "objective_id": f"in.({','.join(o['id'] for o in objectives)})",
        "is_deleted": "eq.false",
        "select": "*",
        "order": "order_index.asc,created_at.asc",
        "limit": 5000,
    }) or []

    now = datetime.now(timezone.utc)
    goals, to_update = [], 0
    for o in objectives:
        mine = [k for k in krs if k.get("objective_id") == o["id"] and not k.get("is_default")]
        if not mine:
            continue
        rows = []
        for k in mine:
            checked = _parse_ts(k.get("last_checked_at"))
            days = (now - checked).days if checked else None
            auto = bool(k.get("auto_progress"))
            if not auto:
                to_update += 1
            rows.append({
                "id": k["id"],
                "title": k.get("title"),
                "unit": k.get("unit") or "",
                "direction": k.get("direction") or "up",
                "start_value": k.get("start_value"),
                "current_value": k.get("current_value"),
                "target_value": k.get("target_value"),
                "progress": round(_kr_progress(k)),
                "auto": auto,
                "last_checked_at": k.get("last_checked_at"),
                "days_since": days,
                "stale": (not auto) and days is not None and days >= _CHECKIN_STALE_DAYS,
            })
        goals.append({
            "id": o["id"],
            "title": o.get("title"),
            "target_date": o.get("target_date"),
            "progress": round(sum(r["progress"] for r in rows) / len(rows)),
            "key_results": rows,
        })
    return jsonify({"goals": goals, "to_update": to_update,
                    "stale_days": _CHECKIN_STALE_DAYS})


@goals_bp.route("/api/goals/check-in", methods=["POST"])
@login_required
def checkin_save():
    """Body: {"entries": [{"key_result_id", "value"}], "notes": {objective_id: text}}.

    Only key results that belong to this user and are kept by hand are
    written. A value equal to the current one still counts as checked —
    "no change" is an answer, and it resets the stale flag."""
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}
    entries = data.get("entries") or []
    notes = data.get("notes") or {}
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "nothing to save"}), 400

    cleaned = []
    for e in entries:
        kr_id = (e or {}).get("key_result_id")
        try:
            value = float((e or {}).get("value"))
        except (TypeError, ValueError):
            return jsonify({"error": "every value must be a number"}), 400
        if kr_id:
            cleaned.append((str(kr_id), value))
    if not cleaned:
        return jsonify({"error": "nothing to save"}), 400

    ids = ",".join(k for k, _ in cleaned)
    owned = get("key_results", params={
        "user_id": f"eq.{user_id}",
        "id": f"in.({ids})",
        "is_deleted": "eq.false",
        "select": "id,objective_id,current_value,auto_progress",
    }) or []
    by_id = {k["id"]: k for k in owned}

    saved = 0
    stamp = _now_iso()
    for kr_id, value in cleaned:
        k = by_id.get(kr_id)
        if not k or k.get("auto_progress"):
            continue
        update("key_results",
               params={"id": f"eq.{kr_id}", "user_id": f"eq.{user_id}"},
               json={"current_value": value, "last_checked_at": stamp})
        note = notes.get(k.get("objective_id")) if isinstance(notes, dict) else None
        _log_checkin(user_id, kr_id, k.get("objective_id"), value,
                     k.get("current_value"), (note or "").strip()[:2000] or None)
        saved += 1
    return jsonify({"status": "ok", "saved": saved})


@goals_bp.route("/api/key-results/<kr_id>", methods=["DELETE"])
@login_required
def delete_key_result(kr_id):
    """Soft delete. Cascades to initiatives under this KR."""
    user_id = session["user_id"]

    try:
        # Cascade to initiatives FIRST, then the KR itself.
        _soft_delete(
            "initiatives",
            params={
                "user_id": f"eq.{user_id}",
                "key_result_id": f"eq.{kr_id}",
            },
        )
        _soft_delete(
            "key_results",
            params={"id": f"eq.{kr_id}", "user_id": f"eq.{user_id}"},
        )
    except Exception as e:
        logger.exception("delete_key_result failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────
# INITIATIVES CRUD — new layer between KR and Task
# ──────────────────────────────────────────────────────────────────────

@goals_bp.route("/api/initiatives", methods=["POST"])
@login_required
def create_initiative():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    key_result_id = data.get("key_result_id")

    if not title or not key_result_id:
        return jsonify({"error": "title and key_result_id required"}), 400

    # Forbid attaching a new Initiative under the default OKR's KR.
    # The default tree is reserved as a catch-all for unclassified work;
    # real organisation goes under user-created OKRs. Walk KR → Objective
    # in one extra query.
    kr_rows = get(
        "key_results",
        params={
            "id":         f"eq.{key_result_id}",
            "user_id":    f"eq.{session['user_id']}",
            "is_deleted": "eq.false",
            "select":     "id,objective_id,objectives(is_default)",
            "limit":      1,
        },
    ) or []
    if not kr_rows:
        return jsonify({"error": "key result not found"}), 404
    parent_obj = (kr_rows[0].get("objectives") or {})
    if parent_obj.get("is_default"):
        return jsonify({
            "error": "Initiatives can't live under the default OKR. "
                     "Create a new OKR first, then add the Initiative under it."
        }), 422

    payload = {
        "user_id": session["user_id"],
        "key_result_id": key_result_id,
        "title": title,
        "description": (data.get("description") or "").strip() or None,
        "start_date":  data.get("start_date")  or None,
        "target_date": data.get("target_date") or None,
        "status": "active",
    }
    rows = post("initiatives", payload)
    return jsonify({"status": "ok", "initiative": rows[0] if rows else None})


@goals_bp.route("/api/initiatives/<initiative_id>", methods=["PATCH"])
@login_required
def update_initiative(initiative_id):
    data = request.get_json(force=True) or {}
    allowed = {"title", "description", "status", "order_index", "is_deleted",
               "start_date", "target_date"}
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400
    if "status" in patch and patch["status"] not in _VALID_OBJECTIVE_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    if patch.get("is_deleted") is False:
        patch["deleted_at"] = None

    update(
        "initiatives",
        params={"id": f"eq.{initiative_id}", "user_id": f"eq.{session['user_id']}"},
        json=patch,
    )
    return jsonify({"status": "ok"})


@goals_bp.route("/api/initiatives/<initiative_id>", methods=["DELETE"])
@login_required
def delete_initiative(initiative_id):
    """Soft delete a single initiative. Linked tasks keep their
    initiative_id pointer so that if the initiative is restored, the
    task linkage is automatically intact again."""
    try:
        _soft_delete(
            "initiatives",
            params={"id": f"eq.{initiative_id}", "user_id": f"eq.{session['user_id']}"},
        )
    except Exception as e:
        logger.exception("delete_initiative failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500
    return jsonify({"status": "ok"})


# ═════════════════════════════════════════════════════════════════
# EPICS — the layer between Initiative and Task (see MIGRATION_EPICS.sql)
# ═════════════════════════════════════════════════════════════════

@goals_bp.route("/api/epics", methods=["POST"])
@login_required
def create_epic():
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    initiative_id = data.get("initiative_id")
    if not title or not initiative_id:
        return jsonify({"error": "title and initiative_id required"}), 400

    # Forbid attaching a new Epic under the default Initiative — the
    # default chain is the catch-all and shouldn't grow children.
    init_rows = get(
        "initiatives",
        params={
            "id":         f"eq.{initiative_id}",
            "user_id":    f"eq.{session['user_id']}",
            "is_deleted": "eq.false",
            "select":     "id,is_default",
            "limit":      1,
        },
    ) or []
    if not init_rows:
        return jsonify({"error": "initiative not found"}), 404
    if init_rows[0].get("is_default"):
        return jsonify({
            "error": "Epics can't live under the default Initiative. "
                     "Create a new Initiative first, then add the Epic under it."
        }), 422

    payload = {
        "user_id": session["user_id"],
        "initiative_id": initiative_id,
        "title": title,
        "description": (data.get("description") or "").strip() or None,
        "start_date":  data.get("start_date")  or None,
        "target_date": data.get("target_date") or None,
        "status": "active",
    }
    rows = post("epics", payload)
    return jsonify({"status": "ok", "epic": rows[0] if rows else None})


@goals_bp.route("/api/epics/<epic_id>", methods=["PATCH"])
@login_required
def update_epic(epic_id):
    data = request.get_json(force=True) or {}
    allowed = {"title", "description", "status", "order_index", "is_deleted", "initiative_id",
               "start_date", "target_date"}
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400
    if patch.get("is_deleted") is False:
        patch["deleted_at"] = None
    update(
        "epics",
        params={"id": f"eq.{epic_id}", "user_id": f"eq.{session['user_id']}"},
        json=patch,
    )
    return jsonify({"status": "ok"})


@goals_bp.route("/api/epics/<epic_id>", methods=["DELETE"])
@login_required
def delete_epic(epic_id):
    """Soft delete an epic. Tasks keep their epic_id pointer so a
    restore re-links them — matches delete_initiative behavior."""
    try:
        _soft_delete(
            "epics",
            params={"id": f"eq.{epic_id}", "user_id": f"eq.{session['user_id']}"},
        )
    except Exception as e:
        logger.exception("delete_epic failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500
    return jsonify({"status": "ok"})


# ═════════════════════════════════════════════════════════════════
# HIERARCHY — one round trip returns the whole OKR > KR > Init > Epic
# tree for a single project. Used by the cascading filter on the
# project tasks page. We don't include task data here because the
# tasks endpoint already exists and the page paginates/filters it
# separately.
# ═════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════
# SPRINTS — per-project time-boxes that any task can opt into. See
# MIGRATION_SPRINTS.sql. Independent of the OKR tree: a task in
# epic X can belong to sprint Y, both nullable.
# ═════════════════════════════════════════════════════════════════

@goals_bp.route("/api/projects/<project_id>/sprints", methods=["GET"])
@login_required
def list_sprints(project_id):
    user_id = session["user_id"]
    rows = get(
        "sprints",
        params={
            "user_id":    f"eq.{user_id}",
            "project_id": f"eq.{project_id}",
            "is_deleted": "eq.false",
            "select":     "id,name,starts_on,ends_on,is_active,order_index,created_at",
            # Active first, then by date (most recent), then by manual order.
            "order":      "is_active.desc,starts_on.desc.nullslast,order_index.asc,created_at.desc",
        },
    ) or []
    return jsonify({"sprints": rows})


@goals_bp.route("/api/sprints", methods=["POST"])
@login_required
def create_sprint():
    data = request.get_json(force=True) or {}
    project_id = data.get("project_id")
    name = (data.get("name") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    # Default name = "Sprint N" where N is one more than the highest
    # number already used in a non-deleted sprint name matching
    # "Sprint <digits>". Skipping deleted rows + parsing the name
    # (instead of just counting) keeps the client's preview and the
    # server's fallback in sync, and naturally handles users who
    # have renamed some sprints to custom names.
    if not name:
        import re as _re
        existing = get(
            "sprints",
            params={
                "user_id":    f"eq.{session['user_id']}",
                "project_id": f"eq.{project_id}",
                "is_deleted": "eq.false",
                "select":     "name",
                "limit":      500,
            },
        ) or []
        max_n = 0
        for row in existing:
            m = _re.match(r"^\s*Sprint\s+(\d+)\s*$", row.get("name") or "", _re.I)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        name = f"Sprint {max_n + 1}"

    payload = {
        "user_id":    session["user_id"],
        "project_id": project_id,
        "name":       name[:80],
        "starts_on":  data.get("starts_on") or None,
        "ends_on":    data.get("ends_on") or None,
        "is_active":  bool(data.get("is_active", False)),
        "order_index": int(data.get("order_index") or 0),
    }
    rows = post("sprints", payload)
    return jsonify({"status": "ok", "sprint": rows[0] if rows else None})


@goals_bp.route("/api/sprints/<sprint_id>", methods=["PATCH"])
@login_required
def update_sprint(sprint_id):
    data = request.get_json(force=True) or {}
    allowed = {"name", "starts_on", "ends_on", "is_active", "order_index", "is_deleted"}
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields"}), 400
    if "name" in patch:
        patch["name"] = (patch["name"] or "").strip()[:80]
        if not patch["name"]:
            return jsonify({"error": "name cannot be blank"}), 400
    # Empty string → NULL for the date fields so the column drops cleanly.
    for d in ("starts_on", "ends_on"):
        if d in patch and patch[d] == "":
            patch[d] = None
    if patch.get("is_deleted") is False:
        patch["deleted_at"] = None
    update(
        "sprints",
        params={"id": f"eq.{sprint_id}", "user_id": f"eq.{session['user_id']}"},
        json=patch,
    )
    return jsonify({"status": "ok"})


@goals_bp.route("/api/sprints/<sprint_id>/stats", methods=["GET"])
@login_required
def sprint_stats(sprint_id):
    """Aggregate stats for a single sprint:

      {
        total: <int>,                 # not eliminated
        done:  <int>,                 # status = done
        open:  <int>,                 # total - done
        pct:   <float>,               # done / total
        by_day: [{date, done}, …]     # last 14 days, completion counts
      }

    Used by the sprint manager to render a tiny progress bar and a
    14-day burndown sparkline. Cheap — 1 query for the row set,
    bucketing done in Python.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    user_id = session["user_id"]
    rows = get(
        "project_tasks",
        params={
            "user_id":       f"eq.{user_id}",
            "sprint_id":     f"eq.{sprint_id}",
            "is_eliminated": "eq.false",
            "select":        "task_id,status,updated_at,created_at",
            "limit":         1000,
        },
    ) or []
    total = len(rows)
    done = sum(1 for r in rows if r.get("status") == "done")
    pct = (done / total) if total else 0.0

    # Bucket done tasks by date (last 14d). updated_at is a reasonable
    # proxy for "completed at" for tasks that are currently done.
    today = _dt.now(_tz.utc).date()
    days = [(today - _td(days=i)).isoformat() for i in range(13, -1, -1)]
    bucket = {d: 0 for d in days}
    for r in rows:
        if r.get("status") != "done":
            continue
        ts = r.get("updated_at") or r.get("created_at") or ""
        if not ts:
            continue
        try:
            d = ts[:10]  # YYYY-MM-DD prefix
        except Exception:
            continue
        if d in bucket:
            bucket[d] += 1

    return jsonify({
        "total": total,
        "done":  done,
        "open":  total - done,
        "pct":   round(pct, 3),
        "by_day": [{"date": d, "done": bucket[d]} for d in days],
    })


@goals_bp.route("/api/sprints/<sprint_id>/rollover", methods=["POST"])
@login_required
def rollover_sprint(sprint_id):
    """Move every unfinished task in this sprint into a target sprint.

    Body: {"target_sprint_id": "<uuid>"}   target may be null/missing to
    unassign (clears sprint_id on those tasks). Tasks already done
    (status=done) stay put — the source sprint keeps the historical
    record of what shipped in it.

    Returns: { moved: <n>, target_sprint_id }
    """
    data = request.get_json(force=True) or {}
    target = data.get("target_sprint_id")
    target = target if (target and str(target).strip() not in ("", "null")) else None
    user_id = session["user_id"]

    # Optional: validate target exists and belongs to the same project.
    # Read source first to learn the project_id; lets us validate the
    # target without trusting the client.
    src = get(
        "sprints",
        params={
            "id":         f"eq.{sprint_id}",
            "user_id":    f"eq.{user_id}",
            "is_deleted": "eq.false",
            "select":     "id,project_id",
            "limit":      1,
        },
    ) or []
    if not src:
        return jsonify({"error": "source sprint not found"}), 404
    project_id = src[0]["project_id"]

    if target:
        tgt_rows = get(
            "sprints",
            params={
                "id":         f"eq.{target}",
                "user_id":    f"eq.{user_id}",
                "is_deleted": "eq.false",
                "select":     "id,project_id",
                "limit":      1,
            },
        ) or []
        if not tgt_rows:
            return jsonify({"error": "target sprint not found"}), 404
        if tgt_rows[0]["project_id"] != project_id:
            return jsonify({"error": "target sprint belongs to a different project"}), 400

    # Find unfinished tasks in the source sprint. We then PATCH each
    # one — PostgREST allows a single bulk PATCH with a filter, so do
    # the whole sweep in one round trip.
    try:
        update(
            "project_tasks",
            params={
                "user_id":       f"eq.{user_id}",
                "sprint_id":     f"eq.{sprint_id}",
                "is_eliminated": "eq.false",
                "status":        "neq.done",
            },
            json={"sprint_id": target},
        )
    except Exception:
        logger.exception("rollover sprint %s → %s failed", sprint_id, target)
        return jsonify({"error": "Rollover failed"}), 500

    # Recount to report what moved (filter-based PATCH doesn't tell us).
    moved_rows = get(
        "project_tasks",
        params={
            "user_id":       f"eq.{user_id}",
            "sprint_id":     f"eq.{target}" if target else "is.null",
            "is_eliminated": "eq.false",
            "select":        "task_id",
            "limit":         1000,
        },
    ) or []
    return jsonify({"status": "ok", "target_sprint_id": target, "approx_in_target": len(moved_rows)})


@goals_bp.route("/api/sprints/<sprint_id>", methods=["DELETE"])
@login_required
def delete_sprint(sprint_id):
    """Soft delete. Tasks keep their sprint_id pointer so a restore
    re-links them (mirrors delete_initiative / delete_epic)."""
    try:
        _soft_delete(
            "sprints",
            params={"id": f"eq.{sprint_id}", "user_id": f"eq.{session['user_id']}"},
        )
    except Exception as e:
        logger.exception("delete_sprint failed")
        return jsonify({"error": f"Delete failed: {e}"}), 500
    return jsonify({"status": "ok"})


@goals_bp.route("/api/projects/<project_id>/hierarchy")
@login_required
def project_hierarchy(project_id):
    user_id = session["user_id"]
    # Pull active (non-deleted) rows at each level for this user, then
    # stitch in Python. Faster than 4 sequential round-trips and lets
    # us keep parents that have no children (so "+ Add" UI works).
    # NOTE: is_default is selected on every level so the client can
    # render badges + suppress "+ child" creators under default nodes
    # (Initiatives can't live under the default OKR's KR; Epics can't
    # live under the default Initiative — enforced server-side too).
    objectives = get(
        "objectives",
        params={
            "user_id":    f"eq.{user_id}",
            "project_id": f"eq.{project_id}",
            "is_deleted": "eq.false",
            "select":     "id,title,description,status,color,order_index,is_default,start_date,target_date,time_horizon",
            "order":      "is_default.asc,order_index.asc,created_at.asc",
        },
    ) or []
    # NOTE: objectives.start_date / target_date have shipped for a while
    # (MIGRATION_FRESH_INSTALL.sql ensures via add column if not exists).
    # The init/epic equivalents are newer — see hierarchy reads below.
    obj_ids = [o["id"] for o in objectives]

    key_results = []
    if obj_ids:
        key_results = get(
            "key_results",
            params={
                "user_id":      f"eq.{user_id}",
                "objective_id": f"in.({','.join(obj_ids)})",
                "is_deleted":   "eq.false",
                "select":       "id,objective_id,title,target_value,current_value,unit,direction,order_index,is_default",
                "order":        "is_default.asc,order_index.asc,created_at.asc",
            },
        ) or []
    kr_ids = [kr["id"] for kr in key_results]

    initiatives = []
    if kr_ids:
        initiatives = get(
            "initiatives",
            params={
                "user_id":       f"eq.{user_id}",
                "key_result_id": f"in.({','.join(kr_ids)})",
                "is_deleted":    "eq.false",
                # start_date/target_date columns ship in MIGRATION_INIT_EPIC_DATES.sql.
                # PostgREST 400s on unknown columns — keep this select aligned with
                # the migration state when you deploy. Roll back here if you ever
                # deploy backend code ahead of the migration.
                "select":        "id,key_result_id,title,description,status,order_index,is_default,start_date,target_date",
                "order":         "is_default.asc,order_index.asc,created_at.asc",
            },
        ) or []
    init_ids = [i["id"] for i in initiatives]

    epics = []
    if init_ids:
        epics = get(
            "epics",
            params={
                "user_id":       f"eq.{user_id}",
                "initiative_id": f"in.({','.join(init_ids)})",
                "is_deleted":    "eq.false",
                "select":        "id,initiative_id,title,description,status,order_index,is_default,start_date,target_date",
                "order":         "is_default.asc,order_index.asc,created_at.asc",
            },
        ) or []

    # Index children by parent id for the client.
    from collections import defaultdict
    krs_by_obj  = defaultdict(list)
    for kr in key_results:
        krs_by_obj[kr["objective_id"]].append(kr)
    inits_by_kr = defaultdict(list)
    for it in initiatives:
        inits_by_kr[it["key_result_id"]].append(it)
    epics_by_init = defaultdict(list)
    for ep in epics:
        epics_by_init[ep["initiative_id"]].append(ep)

    tree = []
    for o in objectives:
        krs = []
        for kr in krs_by_obj.get(o["id"], []):
            inits = []
            for it in inits_by_kr.get(kr["id"], []):
                inits.append(dict(it, epics=epics_by_init.get(it["id"], [])))
            krs.append(dict(kr, initiatives=inits))
        tree.append(dict(o, key_results=krs))

    # Lazy auto-archive: any sprint whose ends_on has passed AND is
    # still marked active gets quietly flipped to inactive. Cheap
    # filter-based PATCH; no-ops when there's nothing to update.
    from datetime import date as _date
    _today_iso = _date.today().isoformat()
    try:
        update(
            "sprints",
            params={
                "user_id":    f"eq.{user_id}",
                "project_id": f"eq.{project_id}",
                "is_active":  "eq.true",
                "is_deleted": "eq.false",
                "ends_on":    f"lt.{_today_iso}",
            },
            json={"is_active": False},
        )
    except Exception:
        logger.exception("auto-archive past sprints failed for project %s", project_id)

    # Sprints — orthogonal to the OKR tree but the UI fetches both
    # together to populate pickers + filter chips in one round trip.
    sprints = get(
        "sprints",
        params={
            "user_id":    f"eq.{user_id}",
            "project_id": f"eq.{project_id}",
            "is_deleted": "eq.false",
            "select":     "id,name,starts_on,ends_on,is_active,order_index",
            "order":      "is_active.desc,starts_on.desc.nullslast,order_index.asc,created_at.desc",
        },
    ) or []

    return jsonify({
        "project_id": project_id,
        "tree":       tree,
        "sprints":    sprints,
        "counts": {
            "objectives":  len(objectives),
            "key_results": len(key_results),
            "initiatives": len(initiatives),
            "epics":       len(epics),
            "sprints":     len(sprints),
        },
    })


# ══════════════════════════════════════════════════════════════════════
# GOAL PLANNER — the deadline / countdown view over the same objectives
#
# Deliberately NOT a second goals table. A goal entered here is an
# `objectives` row, so it shows up on /goals with its key results, and an
# objective created there counts down here the moment it gets a date.
#
# Every countdown column is optional: if MIGRATION_GOAL_COUNTDOWN.sql has
# not been run yet, the reads simply return None for those keys and the
# page falls back to `target_date` with the budget line hidden. Writes to
# the new columns are the only thing that hard-fails, and they say so.
# ══════════════════════════════════════════════════════════════════════

from services.goal_coach import coach as _goal_coach          # noqa: E402
from utils.countdown import summarise as _countdown           # noqa: E402
from utils.user_tz import user_now, user_tz                   # noqa: E402

#: Columns the planner is allowed to write. Anything else must go through
#: the existing objective PATCH so validation stays in one place.
_PLANNER_FIELDS = {
    "title", "target_at", "target_date", "start_date",
    "daily_commit_minutes", "effort_minutes", "flash_enabled",
    "manual_progress",
}


def _clean_manual_progress(value):
    """Validate a typed percentage. Returns (value_or_None, error_or_None).

    An empty string means "clear it" — the goal goes back to the key-result
    roll-up. Out-of-range numbers are CLAMPED rather than rejected: someone
    typing 150 obviously means "done", and refusing the input would be
    pedantic. Junk that is not a number at all is a real mistake and is
    rejected, since silently storing 0 would look like lost progress.
    """
    if value is None or value == "":
        return None, None
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        return None, "progress must be a number between 0 and 100"
    return max(0, min(100, pct)), None

#: Relative-deadline inputs, in the units the form offers.
_RELATIVE_UNITS = {"in_days": "days", "in_hours": "hours", "in_minutes": "minutes"}

#: A deadline further out than this is almost certainly a typo (someone
#: meaning 45 and typing 45000). Reject it rather than storing a year 4000
#: date that breaks every countdown on the page.
_MAX_RELATIVE_DAYS = 3650


def _resolve_relative_deadline(data):
    """Turn `in_days` / `in_hours` / `in_minutes` into an absolute target_at.

    Resolved SERVER-side against the user's own `now`: the browser clock can
    be wrong or in another timezone, and "45 days from now" has to mean 45
    days from the user's now, not the device's.

    Returns (iso_string_or_None, error_or_None). An explicit `target_at`
    always wins — if the caller sent one, the relative fields are ignored.
    """
    if data.get("target_at"):
        return None, None
    for field, unit in _RELATIVE_UNITS.items():
        raw = data.get(field)
        if raw in (None, ""):
            continue
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            return None, f"{field} must be a number"
        if amount <= 0:
            return None, f"{field} must be greater than zero"
        delta = timedelta(**{unit: amount})
        if delta > timedelta(days=_MAX_RELATIVE_DAYS):
            return None, (f"that deadline is over {_MAX_RELATIVE_DAYS // 365} years "
                          f"away — check the number")
        return (user_now() + delta).isoformat(), None
    return None, None


def _objective_progress(user_id, objectives):
    """Percent-complete per objective, with the SOURCE of the number.

    Precedence, and it is deliberate:

      1. `manual_progress`, when the user has typed one. It wins outright —
         they looked at the goal and made a judgement, and second-guessing
         that would make the field pointless.
      2. otherwise the average over the objective's key results, which is
         the honest default because a KR is a measurable claim.
      3. otherwise 0.

    `source` travels with the number so the UI can label it. Showing a
    typed 60% next to three key results averaging 20% without saying which
    is which would be the worst of both worlds. Clearing the field returns
    the goal to the roll-up, so the override is always reversible.

    Mirrors the roll-up in `list_objectives` rather than importing it, so
    the planner cannot be broken by a change to that endpoint's shape.
    """
    if not objectives:
        return {}
    ids = [o["id"] for o in objectives]
    krs = get("key_results", params={
        "user_id": f"eq.{user_id}",
        "objective_id": f"in.({','.join(ids)})",
        "is_deleted": "eq.false",
        "select": "id,objective_id,start_value,current_value,target_value,direction,due_at,title",
        "limit": 5000,
    }) or []
    out = {}
    for o in objectives:
        mine = [k for k in krs if k["objective_id"] == o["id"]]
        rolled = round(sum(_kr_progress(k) for k in mine) / len(mine)) if mine else 0
        typed = o.get("manual_progress")
        if typed is None:
            progress, source = rolled, ("key_results" if mine else "none")
        else:
            progress, source = max(0, min(100, int(typed))), "manual"
        out[o["id"]] = {
            "progress": progress,
            "source": source,
            # Kept alongside so the UI can show "you typed 60%, your key
            # results say 20%" rather than hiding the disagreement.
            "rolled_up": rolled,
            "kr_count": len(mine),
            "key_results": mine,
        }
    return out


def _next_checkpoint(krs, now):
    """The soonest not-yet-passed key-result due date, as {title, iso, days}.

    A six-month countdown is useless for five of those months; the next
    checkpoint is what makes a distant goal actionable this week.
    """
    upcoming = []
    for k in krs:
        raw = k.get("due_at")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=now.tzinfo)
        if when >= now:
            upcoming.append((when, k))
    if not upcoming:
        return None
    when, kr = min(upcoming, key=lambda p: p[0])
    return {"title": kr.get("title") or "Checkpoint",
            "iso": when.isoformat(),
            "days": (when - now).days}


@goals_bp.route("/goal-planner")
@login_required
def goal_planner_page():
    return render_template("goal_planner.html")


@goals_bp.route("/api/goal-planner", methods=["GET"])
@login_required
def goal_planner_data():
    """Every dated goal with its countdown, pace, budget and coach line.

    Sorted by urgency — soonest deadline first, undated goals last — so
    the top of the page is always the thing closest to being late.
    """
    user_id = session["user_id"]
    now = user_now()
    tz = user_tz()

    objectives = get("objectives", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "status": "eq.active",
        "select": "*",
        "order": "order_index.asc,created_at.asc",
        "limit": 500,
    }) or []

    prog = _objective_progress(user_id, objectives)
    goals, primary = [], None
    for o in objectives:
        p = prog.get(o["id"], {"progress": 0, "source": "none", "rolled_up": 0,
                               "kr_count": 0, "key_results": []})
        summary = _countdown(o, now, tz, progress_pct=p["progress"])
        message, tone = _goal_coach(summary, o.get("title") or "", p["progress"])
        row = {
            "id": o["id"],
            "title": o.get("title"),
            "description": o.get("description"),
            "status": o.get("status"),
            "start_date": o.get("start_date"),
            "target_date": o.get("target_date"),
            "target_at": o.get("target_at"),
            "daily_commit_minutes": o.get("daily_commit_minutes"),
            "effort_minutes": o.get("effort_minutes"),
            "flash_enabled": o.get("flash_enabled", True),
            "is_primary": bool(o.get("is_primary")),
            "progress": p["progress"],
            "progress_source": p["source"],
            "rolled_up_progress": p["rolled_up"],
            "manual_progress": o.get("manual_progress"),
            "kr_count": p["kr_count"],
            "next_checkpoint": _next_checkpoint(p["key_results"], now),
            "countdown": summary,
            "coach": {"message": message, "tone": tone},
        }
        goals.append(row)
        if row["is_primary"]:
            primary = row

    # Soonest deadline first; undated goals sink to the bottom, since a goal
    # with no date cannot be urgent by definition.
    goals.sort(key=lambda g: (
        not g["countdown"].get("has_deadline"),
        g["countdown"].get("breakdown", {}).get("total_seconds", 1 << 62),
    ))
    # Nothing pinned: the most urgent dated goal stands in, so the page has
    # a hero without forcing the user to choose one first.
    if primary is None:
        primary = next((g for g in goals if g["countdown"].get("has_deadline")), None)

    return jsonify({
        "goals": goals,
        "primary_id": primary["id"] if primary else None,
        "now": now.isoformat(),
        "counts": {
            "total": len(goals),
            "dated": sum(1 for g in goals if g["countdown"].get("has_deadline")),
            "overdue": sum(1 for g in goals
                           if g["countdown"].get("breakdown", {}).get("overdue")),
            "at_risk": sum(1 for g in goals if g["coach"]["tone"] in ("scold", "alarm")),
        },
    })


@goals_bp.route("/api/goal-planner/goals", methods=["POST"])
@login_required
def goal_planner_create():
    """Create a goal from the planner's one-line form.

    Only a title is required. Everything else sharpens the countdown, and
    the page nags for the missing pieces rather than blocking on them.
    """
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400

    payload = {
        "user_id": session["user_id"],
        "title": title,
        "description": (data.get("description") or "").strip() or None,
        "time_horizon": "ongoing",
        "status": "active",
        "start_date": data.get("start_date") or user_now().date().isoformat(),
        "target_date": data.get("target_date") or None,
    }
    relative, err = _resolve_relative_deadline(data)
    if err:
        return jsonify({"error": err}), 400
    if relative:
        payload["target_at"] = relative
    for field in ("target_at", "daily_commit_minutes", "effort_minutes"):
        if data.get(field) not in (None, ""):
            payload[field] = data[field]
    if data.get("manual_progress") not in (None, ""):
        cleaned, err = _clean_manual_progress(data["manual_progress"])
        if err:
            return jsonify({"error": err}), 400
        payload["manual_progress"] = cleaned
    try:
        rows = post("objectives", payload)
    except Exception as exc:
        return _planner_schema_error(exc)
    return jsonify({"status": "ok", "goal": rows[0] if rows else None})


@goals_bp.route("/api/goal-planner/goals/<goal_id>", methods=["PATCH"])
@login_required
def goal_planner_update(goal_id):
    """Update the countdown fields on one goal."""
    data = request.get_json(force=True) or {}
    patch = {k: v for k, v in data.items() if k in _PLANNER_FIELDS}
    if "manual_progress" in patch:
        cleaned, err = _clean_manual_progress(patch["manual_progress"])
        if err:
            return jsonify({"error": err}), 400
        patch["manual_progress"] = cleaned
    relative, err = _resolve_relative_deadline(data)
    if err:
        return jsonify({"error": err}), 400
    if relative:
        patch["target_at"] = relative
    if not patch:
        return jsonify({"error": "nothing to update"}), 400
    # Empty string means "clear it" — otherwise a cleared date would be
    # stored as "" and every parse downstream would have to defend itself.
    for k, v in list(patch.items()):
        if v == "":
            patch[k] = None
    try:
        update("objectives", params={
            "id": f"eq.{goal_id}", "user_id": f"eq.{session['user_id']}",
        }, json=patch)
    except Exception as exc:
        return _planner_schema_error(exc)
    return jsonify({"status": "ok"})


@goals_bp.route("/api/goal-planner/goals/<goal_id>/primary", methods=["POST"])
@login_required
def goal_planner_pin(goal_id):
    """Pin one goal as the hero countdown, unpinning whatever held it.

    Unpin first, then pin: the partial unique index in the migration
    allows only one primary per user, so doing it the other way round
    would collide.
    """
    user_id = session["user_id"]
    try:
        update("objectives", params={
            "user_id": f"eq.{user_id}", "is_primary": "eq.true",
        }, json={"is_primary": False})
        update("objectives", params={
            "id": f"eq.{goal_id}", "user_id": f"eq.{user_id}",
        }, json={"is_primary": True})
    except Exception as exc:
        return _planner_schema_error(exc)
    return jsonify({"status": "ok", "primary_id": goal_id})


def _planner_schema_error(exc):
    """Turn the Postgres 'column does not exist' 400 into a real instruction.

    Without this the page shows a bare 500 and the cause — an unrun
    migration — is invisible.
    """
    text = str(exc)
    if "column" in text and ("does not exist" in text or "schema cache" in text):
        logger.warning("goal planner: countdown columns missing - %s", text)
        return jsonify({
            "error": "The goal countdown columns are missing. Run "
                     "MIGRATION_GOAL_COUNTDOWN.sql in Supabase, then reload.",
            "migration": "MIGRATION_GOAL_COUNTDOWN.sql",
        }), 503
    raise exc
