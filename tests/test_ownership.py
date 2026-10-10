"""Writes are scoped to the signed-in user.

The app talks to Supabase with the service key, so Postgres row-level
security protects nothing: every route has to filter on the caller's
user_id itself. An audit (2026-10-11) found 26 writes keyed on a row id
alone — any signed-in user could edit, eliminate or soft-delete another
user's project tasks, matrix tasks, subtasks and habit order by posting
that id. These tests pin the fix for the main shapes.
"""
import pytest

ME = "eq.test-user-id"


@pytest.fixture
def writes(monkeypatch):
    import routes.projects as pr
    import routes.todo as td
    import routes.habits as hb
    seen = []
    rec = lambda table, params=None, json=None, **kw: seen.append((table, dict(params or {})))
    for mod in (pr, td, hb):
        monkeypatch.setattr(mod, "update", rec)
    return seen


@pytest.mark.parametrize("path,body", [
    ("/projects/tasks/update-date", {"task_id": "t9", "date": "2026-10-20"}),
    ("/projects/tasks/eliminate", {"id": "t9"}),
    ("/projects/tasks/pin", {"task_id": "t9", "is_pinned": True}),
    ("/projects/tasks/update-priority", {"task_id": "t9", "priority": "high"}),
])
def test_project_task_writes_filter_on_the_caller(auth_client, writes, path, body):
    auth_client.post(path, json=body)
    task_writes = [p for t, p in writes if t == "project_tasks"]
    for p in task_writes:
        assert p.get("user_id") == ME, f"{path} wrote {p} without the owner filter"


def test_matrix_move_filters_on_the_caller(auth_client, writes):
    auth_client.post("/todo/move", json={"id": "m1", "quadrant": "do"})
    assert writes and all(p.get("user_id") == ME for t, p in writes if t == "todo_matrix")


def test_toggle_done_on_someone_elses_task_does_nothing(auth_client, writes, monkeypatch):
    import routes.todo as td
    # The scoped fetch finds nothing: the row is not the caller's.
    monkeypatch.setattr(td, "get", lambda *a, **kw: [])
    r = auth_client.post("/todo/toggle-done", json={"id": "m1", "status": "deleted"})
    assert r.status_code == 404
    assert not writes, "nothing may be written for a task that is not yours"


def test_subtask_toggle_checks_the_parent_tasks_owner(auth_client, writes, monkeypatch):
    import routes.projects as pr

    def fake_get(table, params=None, **kw):
        if table == "project_subtasks":
            return [{"parent_task_id": "t9"}]
        if table == "project_tasks":
            return []        # parent is not the caller's
        return []
    monkeypatch.setattr(pr, "get", fake_get)
    r = auth_client.post("/subtask/toggle", json={"id": 5, "is_done": True})
    assert r.status_code == 404
    assert not [t for t, _ in writes if t == "project_subtasks"]


def test_subtask_toggle_still_works_for_the_owner(auth_client, writes, monkeypatch):
    import routes.projects as pr
    monkeypatch.setattr(pr, "get", lambda table, params=None, **kw:
                        [{"parent_task_id": "t1"}] if table == "project_subtasks" else [{"task_id": "t1"}])
    r = auth_client.post("/subtask/toggle", json={"id": 5, "is_done": True})
    assert r.status_code == 204
    assert [t for t, _ in writes] == ["project_subtasks"]


def test_habit_reorder_filters_on_the_caller(auth_client, writes):
    auth_client.post("/api/habits/reorder", json={"habit_id": "h1", "position": 2})
    assert writes and writes[0][1].get("user_id") == ME
