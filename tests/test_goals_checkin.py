"""Weekly check-in for key results (/goals/check-in).

What must hold:
  - only hand-kept key results are asked about; ones filled in from tasks
    are shown but never written, because the next task toggle would
    overwrite whatever was typed;
  - default ("Uncategorized" / "—") rows and goals without key results
    never appear;
  - a check-in writes the value, stamps last_checked_at, and appends a
    history row — and a missing history table (migration not run) costs
    the history, not the save;
  - an inline edit on /goals is a check-in too.
"""
from datetime import datetime, timedelta, timezone


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


OBJECTIVES = [
    {"id": "g1", "title": "Ship the sale event", "status": "active"},
    {"id": "g2", "title": "No key results here", "status": "active"},
    {"id": "g3", "title": "Uncategorized", "status": "active", "is_default": True},
]
KRS = [
    {"id": "k1", "objective_id": "g1", "title": "Sev-1 incidents", "start_value": 3,
     "current_value": 1, "target_value": 0, "direction": "down", "unit": "incidents",
     "last_checked_at": _iso(2)},
    {"id": "k2", "objective_id": "g1", "title": "Load test passes", "start_value": 0,
     "current_value": 70, "target_value": 100, "direction": "up", "unit": "%",
     "auto_progress": True, "last_checked_at": _iso(30)},
    {"id": "k3", "objective_id": "g1", "title": "p95 resolution", "start_value": 75,
     "current_value": 52, "target_value": 30, "direction": "down", "unit": "min",
     "last_checked_at": _iso(9)},
    {"id": "k4", "objective_id": "g3", "title": "—", "is_default": True,
     "start_value": 0, "current_value": 0, "target_value": 1},
]


def _fake_get(table, params=None, **kw):
    if table == "objectives":
        return OBJECTIVES
    if table == "key_results":
        ids = (params or {}).get("id", "")
        if ids.startswith("in.("):
            wanted = ids[4:-1].split(",")
            return [k for k in KRS if k["id"] in wanted]
        return KRS
    return []


def test_the_check_in_page_renders(auth_client):
    r = auth_client.get("/goals/check-in")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'id="ci-form"' in body
    assert "goals_checkin.js" in body


def test_goals_page_links_to_the_check_in(auth_client):
    body = auth_client.get("/goals").get_data(as_text=True)
    assert 'href="/goals/check-in"' in body


def test_check_in_lists_only_goals_with_real_key_results(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", _fake_get)
    data = auth_client.get("/api/goals/check-in").get_json()

    assert [g["id"] for g in data["goals"]] == ["g1"], \
        "goals without key results and default rows must not appear"
    krs = {k["id"]: k for k in data["goals"][0]["key_results"]}
    assert set(krs) == {"k1", "k2", "k3"}
    assert data["to_update"] == 2, "a key result filled in from tasks is not asked about"
    assert krs["k2"]["auto"] is True and krs["k2"]["stale"] is False, \
        "an automatic key result is never 'stale' — nobody is meant to type it"
    assert krs["k3"]["stale"] is True and krs["k3"]["days_since"] == 9
    assert krs["k1"]["stale"] is False
    assert krs["k1"]["progress"] == 67   # 3 -> 1 of a 3 -> 0 drop


def test_saving_writes_values_stamps_and_history(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", _fake_get)
    updates, posts = [], []
    monkeypatch.setattr(goals, "update", lambda t, params=None, json=None, **kw: updates.append((t, params, json)))
    monkeypatch.setattr(goals, "post", lambda t, payload, **kw: posts.append((t, payload)) or [payload])

    r = auth_client.post("/api/goals/check-in", json={
        "entries": [
            {"key_result_id": "k1", "value": 1},       # unchanged still counts
            {"key_result_id": "k2", "value": 99},      # auto: must be ignored
            {"key_result_id": "k3", "value": 48},
            {"key_result_id": "not-mine", "value": 5}, # not returned by the owner query
        ],
        "notes": {"g1": "Classifier v2 at 50% cut the queue"},
    })
    assert r.status_code == 200
    assert r.get_json()["saved"] == 2

    written = {p["id"][3:]: j for t, p, j in updates if t == "key_results"}
    assert set(written) == {"k1", "k3"}
    assert written["k3"]["current_value"] == 48
    assert "last_checked_at" in written["k3"]

    history = [p for t, p in posts if t == "kr_checkins"]
    assert {h["key_result_id"] for h in history} == {"k1", "k3"}
    k3 = next(h for h in history if h["key_result_id"] == "k3")
    assert k3["previous_value"] == 52 and k3["value"] == 48
    assert k3["note"] == "Classifier v2 at 50% cut the queue"


def test_a_missing_history_table_does_not_lose_the_check_in(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", _fake_get)
    updates = []
    monkeypatch.setattr(goals, "update", lambda t, params=None, json=None, **kw: updates.append(json))

    def boom(*a, **kw):
        raise RuntimeError('relation "kr_checkins" does not exist')
    monkeypatch.setattr(goals, "post", boom)

    r = auth_client.post("/api/goals/check-in",
                         json={"entries": [{"key_result_id": "k3", "value": 40}]})
    assert r.status_code == 200 and r.get_json()["saved"] == 1
    assert updates and updates[0]["current_value"] == 40


def test_a_value_that_is_not_a_number_is_refused(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", _fake_get)
    r = auth_client.post("/api/goals/check-in",
                         json={"entries": [{"key_result_id": "k3", "value": "lots"}]})
    assert r.status_code == 400


def test_an_inline_edit_on_goals_is_a_check_in_too(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", _fake_get)
    updates, posts = [], []
    monkeypatch.setattr(goals, "update", lambda t, params=None, json=None, **kw: updates.append(json))
    monkeypatch.setattr(goals, "post", lambda t, payload, **kw: posts.append((t, payload)) or [payload])

    r = auth_client.patch("/api/key-results/k3", json={"current_value": 45})
    assert r.status_code == 200
    assert "last_checked_at" in updates[0]
    assert posts and posts[0][0] == "kr_checkins"


def test_editing_a_title_alone_is_not_a_check_in(auth_client, monkeypatch):
    import routes.goals as goals
    updates, posts = [], []
    monkeypatch.setattr(goals, "update", lambda t, params=None, json=None, **kw: updates.append(json))
    monkeypatch.setattr(goals, "post", lambda t, payload, **kw: posts.append(t) or [payload])
    auth_client.patch("/api/key-results/k3", json={"title": "p95 time"})
    assert "last_checked_at" not in updates[0]
    assert not posts


def test_sprint_stats_return_a_burndown_over_the_sprint_dates(auth_client, monkeypatch):
    import routes.goals as goals
    from datetime import date, timedelta
    today = date.today()
    start, end = today - timedelta(days=2), today + timedelta(days=2)
    tasks = [
        {"task_id": "a", "status": "done", "completed_at": f"{start.isoformat()}T10:00:00Z", "updated_at": f"{today.isoformat()}T09:00:00Z"},
        {"task_id": "b", "status": "done", "completed_at": f"{(start + timedelta(days=1)).isoformat()}T10:00:00Z"},
        {"task_id": "c", "status": "open"},
        {"task_id": "d", "status": "open"},
    ]
    monkeypatch.setattr(goals, "get", lambda table, params=None, **kw:
                        tasks if table == "project_tasks"
                        else [{"starts_on": start.isoformat(), "ends_on": end.isoformat()}])
    bd = auth_client.get("/api/sprints/s1/stats").get_json()["burndown"]
    days = bd["days"]
    assert len(days) == 5 and bd["total"] == 4
    assert [d["remaining"] for d in days] == [3, 2, 2, None, None], \
        "completed_at decides the day — not updated_at — and the future is unknown"
    assert days[0]["ideal"] == 4 and days[-1]["ideal"] == 0


def test_sprint_stats_without_dates_have_no_burndown(auth_client, monkeypatch):
    import routes.goals as goals
    monkeypatch.setattr(goals, "get", lambda table, params=None, **kw: [] if table == "sprints" else [{"task_id": "a", "status": "open"}])
    assert auth_client.get("/api/sprints/s1/stats").get_json()["burndown"] is None
