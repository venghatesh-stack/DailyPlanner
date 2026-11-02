"""Day Sheet: the planner-template page, wired to existing data."""


def test_clean_sheet():
    from routes.day_sheet import _clean_sheet
    out = _clean_sheet({"top3": [{"text": "A", "done": 1}], "todos": [{"text": "x" * 500}] * 40,
                        "energy": 9, "hours": {"7": "gym", "25": "bad", "x": "bad", "08": " "},
                        "notes": "n", "junk": 1})
    assert len(out["top3"]) == 3 and out["top3"][0] == {"text": "A", "done": True}
    assert len(out["todos"]) == 30 and len(out["todos"][0]["text"]) == 300
    assert out["energy"] == 5 and out["hours"] == {"07": "gym"} and "junk" not in out


def _fake_db(monkeypatch, sheet_rows=None, sheet_missing=False):
    import routes.day_sheet as ds
    calls = {"post": [], "update": []}

    def fake_get(table, params=None, **k):
        if table == "day_sheets":
            if sheet_missing:
                raise RuntimeError("relation does not exist")
            return sheet_rows or []
        if table == "daily_meta":
            return [{"daily_intent": "Ship it", "reflection": "good", "gratitude": "family", "user_id": "u"}]
        if table == "habit_master":
            return [{"id": "h1", "name": "Walk", "goal": 5000, "habit_type": "number", "unit": "STEPS"},
                    {"id": "h2", "name": "Read", "goal": 1, "habit_type": "boolean"}]
        if table == "habit_entries":
            return [{"habit_id": "h1", "plan_date": "2026-11-02", "value": 6000},
                    {"habit_id": "h2", "plan_date": "2026-11-03", "value": 1}]
        return []
    monkeypatch.setattr(ds, "get", fake_get)
    def fake_post(t, row, **k):
        if t.startswith("day_sheets") and sheet_missing:
            raise RuntimeError('relation "day_sheets" does not exist')
        calls["post"].append((t, row))
        return [row]
    monkeypatch.setattr(ds, "post", fake_post)
    monkeypatch.setattr(ds, "update", lambda t, params=None, json=None, **k: calls["update"].append((t, json)) or [json])
    monkeypatch.setattr(ds, "fetch_events", lambda u, d: [
        {"title": "Standup", "time": "09:30", "end_time": "10:00", "source": "event"}])
    monkeypatch.setattr(ds, "fetch_matrix_items", lambda u, d: [
        {"title": "Pay bill", "time": None, "source": "matrix", "status": "done"}])
    monkeypatch.setattr(ds, "fetch_project_items", lambda u, due_on=None: [])
    monkeypatch.setattr(ds, "fetch_bucket_items", lambda u, d: ([], []))
    return ds, calls


def test_load(auth_client, monkeypatch):
    _fake_db(monkeypatch, sheet_rows=[{"data": {"top3": [{"text": "One"}], "energy": 3}}])
    j = auth_client.get("/api/day-sheet?date=2026-11-04").get_json()
    assert j["available"] and j["week"][0] == "2026-11-02" and j["week"][-1] == "2026-11-08"
    assert j["sheet"]["top3"][0]["text"] == "One" and j["sheet"]["energy"] == 3 and len(j["sheet"]["top3"]) == 3
    assert j["meta"] == {"focus": "Ship it", "reflection": "good", "gratitude": "family"}
    assert j["timed"][0]["title"] == "Standup" and j["untimed"][0]["done"] is True
    walk, read = j["habits"]
    assert walk["days"][0]["done"] and not walk["days"][1]["done"] and read["days"][1]["done"]
    assert auth_client.get("/api/day-sheet?date=nope").status_code == 400


def test_save_routes_fields(auth_client, monkeypatch):
    ds, calls = _fake_db(monkeypatch)
    reads = []
    real_get = ds.get
    monkeypatch.setattr(ds, "get", lambda t, params=None, **k: reads.append(t) or real_get(t, params))
    r = auth_client.post("/api/day-sheet", json={"date": "2026-11-04", "focus": "Focus!", "gratitude": "",
                                                 "sheet": {"energy": 4, "notes": "n", "todos": [{"text": "t", "done": True}]}})
    assert r.status_code == 200
    assert calls["update"] == [("daily_meta", {"daily_intent": "Focus!", "gratitude": None})]
    table, row = calls["post"][0]
    assert table.startswith("day_sheets") and row["data"]["notes"] == "n" and row["data"]["energy"] == 4
    assert "day_sheets" not in reads          # whole sheet sent: no read before the write


def test_save_without_table(auth_client, monkeypatch):
    _fake_db(monkeypatch, sheet_missing=True)
    j = auth_client.get("/api/day-sheet").get_json()
    assert j["available"] is False and j["migration"] == "MIGRATION_DAY_SHEETS.sql"
    assert auth_client.post("/api/day-sheet", json={"sheet": {"notes": "x"}}).status_code == 409
    assert auth_client.post("/api/day-sheet", json={"focus": "still works"}).status_code == 200


def test_tick_habit(auth_client, monkeypatch):
    ds, calls = _fake_db(monkeypatch)
    monkeypatch.setattr(ds, "get", lambda t, params=None, **k: [{"goal": 5000, "habit_type": "number"}])
    j = auth_client.post("/api/day-sheet/habit", json={"habit_id": "h1", "date": "2026-11-04", "done": True}).get_json()
    assert j["value"] == 5000.0 and calls["post"][-1][1]["value"] == 5000.0
    j = auth_client.post("/api/day-sheet/habit", json={"habit_id": "h1", "date": "2026-11-04", "done": False}).get_json()
    assert j["value"] == 0.0


def test_reads_run_in_parallel(auth_client, monkeypatch):
    """Eight reads, each 0.2 s: one after another would take 1.6 s."""
    import time
    ds, _ = _fake_db(monkeypatch)
    slow = lambda fn: (lambda *a, **k: (time.sleep(0.2), fn(*a, **k))[1])
    for name in ("get", "fetch_events", "fetch_matrix_items", "fetch_project_items", "fetch_bucket_items"):
        monkeypatch.setattr(ds, name, slow(getattr(ds, name)))
    t = time.perf_counter()
    j = auth_client.get("/api/day-sheet?date=2026-11-04").get_json()
    assert time.perf_counter() - t < 0.8 and j["timed"][0]["title"] == "Standup"


def test_page(auth_client, monkeypatch):
    _fake_db(monkeypatch)
    html = auth_client.get("/day-sheet?date=2026-11-04").data
    assert b'id="ds-data"' in html and b"Standup" in html          # data embedded, no second request
    assert b"Top 3 priorities" in html and b'data-date="2026-11-04"' in html and b"/day-sheet" in html
    assert auth_client.get("/day-sheet?date=bad").status_code == 302
