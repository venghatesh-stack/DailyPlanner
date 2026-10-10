"""Project colour: the new-project swatches are saved, and only a plain
#rrggbb ever reaches the page (the card writes it into an inline style)."""


def _capture_post(monkeypatch):
    import routes.projects as pr
    seen = []
    monkeypatch.setattr(pr, "post", lambda table, payload, **kw: seen.append((table, payload)) or [{"project_id": "p1", **payload}])
    monkeypatch.setattr(pr, "_ensure_default_okr_trio", lambda *a, **kw: None)
    return seen


def test_the_new_project_form_submits_a_colour(auth_client):
    body = auth_client.get("/projects/new").get_data(as_text=True)
    assert 'type="radio" name="color" value="#4447e5"' in body
    assert "pickColor" not in body, "the old picker was never submitted"


def test_a_chosen_colour_is_saved(auth_client, monkeypatch):
    seen = _capture_post(monkeypatch)
    r = auth_client.post("/projects/new", json={"name": "Sale event", "color": "#0F7C74"})
    assert r.status_code == 200
    assert seen[0][1]["color"] == "#0f7c74"
    assert r.get_json()["project"]["color"] == "#0f7c74"


def test_anything_but_a_hex_colour_is_dropped(auth_client, monkeypatch):
    seen = _capture_post(monkeypatch)
    auth_client.post("/projects/new", json={"name": "X", "color": "red;background:url(x)"})
    assert "color" not in seen[0][1]


def test_the_list_never_renders_an_unsafe_colour(auth_client, monkeypatch):
    import routes.projects as pr
    rows = [{"project_id": "p1", "name": "Good", "color": "#c2417f"},
            {"project_id": "p2", "name": "Bad", "color": "#fff;background:url(x)"}]
    monkeypatch.setattr(pr, "get", lambda table, params=None, **kw: rows if table == "projects" else [])
    body = auth_client.get("/projects").get_data(as_text=True)
    assert "background:#c2417f" in body
    assert "url(x)" not in body


def test_roadmap_cards_carry_their_project_colour(auth_client, monkeypatch):
    import routes.timeline as tl
    monkeypatch.setattr(tl, "get", lambda table, params=None, **kw:
                        [{"project_id": "p1", "name": "Sale", "color": "#0f7c74"},
                         {"project_id": "p2", "name": "Bad", "color": "red;x:url(y)"}])
    monkeypatch.setattr(tl, "load_timeline_tasks", lambda u, project_id=None: [
        {"task_id": "t1", "task_text": "Load test", "project_id": "p1", "project_name": "Sale", "due_date": "2026-10-12"},
        {"task_id": "t2", "task_text": "Other", "project_id": "p2", "project_name": "Bad", "due_date": "2026-10-12"},
    ])
    body = auth_client.get("/projects/timeline").get_data(as_text=True)
    assert "inset 4px 0 0 #0f7c74" in body
    assert "url(y)" not in body


def test_reschedule_only_touches_the_callers_own_task(auth_client, monkeypatch):
    import routes.timeline as tl
    calls = []
    monkeypatch.setattr(tl, "update", lambda t, params=None, json=None, **kw: calls.append(params))
    r = auth_client.post("/api/timeline/reschedule", json={"task_id": "t1", "new_date": "2026-10-20"})
    assert r.status_code == 200
    assert calls[0]["user_id"] == "eq.test-user-id", "must be scoped to the signed-in user"
    assert auth_client.post("/api/timeline/reschedule", json={"task_id": "t1", "new_date": "soon"}).status_code == 400
