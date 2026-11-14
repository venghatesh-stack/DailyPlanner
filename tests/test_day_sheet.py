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


def test_clean_sheet_methods():
    from routes.day_sheet import _clean_sheet
    out = _clean_sheet({"template": "ivylee", "actual": {"9": "email", "99": "x"},
                        "lists": {"ivy": [{"text": f"t{i}"} for i in range(9)], "big": [{"text": "a"}, {"text": "b"}],
                                  "log": [{"text": "call", "kind": "event"}, {"text": "x", "kind": "bad", "moved": 1}],
                                  "hack": [{"text": "no"}]}})
    assert out["template"] == "ivylee" and out["actual"] == {"09": "email"}
    assert len(out["lists"]["ivy"]) == 6 and len(out["lists"]["big"]) == 1 and "hack" not in out["lists"]
    assert out["lists"]["log"] == [{"text": "call", "done": False, "kind": "event"}, {"text": "x", "done": False, "moved": True}]
    assert _clean_sheet({"template": "<script>"})["template"] == ""


def test_carry_to_tomorrow(auth_client, monkeypatch):
    import routes.day_sheet as ds
    sheets = {
        "2026-11-04": {"template": "ivylee", "top3": [{"text": "Ship", "done": False}, {"text": "Done one", "done": True}],
                       "lists": {"ivy": [{"text": "A", "done": True}, {"text": "B"}, {"text": "C"}, {"text": ""}],
                                 "log": [{"text": "task", "kind": "task"}, {"text": "meeting", "kind": "event"},
                                         {"text": "old", "kind": "task", "moved": True}]}},
        "2026-11-05": {"lists": {"ivy": [{"text": "X"}, {"text": "c"}]}},
    }
    posts = []
    monkeypatch.setattr(ds, "get", lambda t, params=None, **k: [{"data": sheets.get(params["sheet_date"][3:], {})}])
    monkeypatch.setattr(ds, "post", lambda t, row, **k: posts.append(row) or [row])

    j = auth_client.post("/api/day-sheet/carry", json={"date": "2026-11-04", "keys": ["ivy", "log", "top3", "evil"]}).get_json()
    assert j["ok"] and j["to"] == "2026-11-05"
    tomorrow, today = posts[0], posts[1]                       # tomorrow is written first
    assert tomorrow["sheet_date"] == "2026-11-05" and today["sheet_date"] == "2026-11-04"
    t = tomorrow["data"]
    assert [r["text"] for r in t["lists"]["ivy"]] == ["B", "X", "c"]      # carried first; "C" already there
    assert t["lists"]["log"] == [{"text": "task", "done": False, "kind": "task"}]   # tasks only, not moved ones
    assert t["top3"][0]["text"] == "Ship" and len(t["top3"]) == 3 and t["template"] == "ivylee"
    ivy = today["data"]["lists"]["ivy"]
    assert [bool(r.get("moved")) for r in ivy] == [False, True, True, False]
    assert j["moved"] == 3 and j["sheet"]["lists"]["ivy"][1]["moved"]
    assert auth_client.post("/api/day-sheet/carry", json={"date": "2026-11-04", "keys": ["evil"]}).status_code == 400


def test_carry_respects_caps(auth_client, monkeypatch):
    import routes.day_sheet as ds
    sheets = {"2026-11-04": {"lists": {"big": [{"text": "New big"}]}},
              "2026-11-05": {"lists": {"big": [{"text": "Already big"}]}}}
    posts = []
    monkeypatch.setattr(ds, "get", lambda t, params=None, **k: [{"data": sheets[params["sheet_date"][3:]]}])
    monkeypatch.setattr(ds, "post", lambda t, row, **k: posts.append(row) or [row])
    j = auth_client.post("/api/day-sheet/carry", json={"date": "2026-11-04", "keys": ["big"]}).get_json()
    assert j["moved"] == 0 and j["skipped"] == 1
    assert posts[0]["data"]["lists"]["big"] == [{"text": "Already big", "done": False}]
    assert not posts[1]["data"]["lists"]["big"][0].get("moved")      # not moved: it didn't fit


def test_page_has_methods(auth_client, monkeypatch):
    _fake_db(monkeypatch)
    html = auth_client.get("/day-sheet?date=2026-11-04").data
    assert b'id="ds-methods"' in html and b"Eisenhower" in html and b"/api/day-sheet/carry" in html


def test_scan_parser_js():
    """The paper-sheet line parser (static/js/day_sheet_scan.js), run in node."""
    import shutil, subprocess, pytest
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", "tests/js/day_sheet_scan.test.js"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_clean_sheet_photos():
    from routes.day_sheet import _clean_sheet
    good = "daysheet/test-user-id/" + "a" * 32 + ".jpg"
    out = _clean_sheet({"photos": [{"key": good, "at": "t"}, {"key": "thoughts/u/x.jpg"},
                                   {"key": "daysheet/u/../x.jpg"}, "junk"]})
    assert out["photos"] == [{"key": good, "at": "t"}]


class _Resp:
    def __init__(self, ok=True, content=b"img", ctype="image/jpeg"):
        self.ok, self.content, self.text, self.headers = ok, content, "", {"Content-Type": ctype}


def test_photo_upload_and_owner_only(auth_client, monkeypatch):
    import io, requests
    import routes.day_sheet as ds
    store, sent = {}, []
    monkeypatch.setattr(ds, "get", lambda t, params=None, **k: [{"data": store["d"]}] if "d" in store else [])
    monkeypatch.setattr(ds, "post", lambda t, row, **k: store.__setitem__("d", row["data"]) or [row])
    monkeypatch.setattr(requests, "post", lambda url, **k: sent.append(url) or _Resp())
    monkeypatch.setattr(requests, "get", lambda url, **k: _Resp(content=b"JPEGDATA"))
    monkeypatch.setattr(requests, "delete", lambda url, **k: sent.append("DEL " + url) or _Resp())

    r = auth_client.post("/api/day-sheet/photo", data={"date": "2026-11-14", "image": (io.BytesIO(b"x" * 10), "p.jpg", "image/jpeg")},
                         content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and len(j["photos"]) == 1
    key = j["photos"][0]["key"]
    assert key.startswith("daysheet/test-user-id/") and sent[0].endswith(key) and store["d"]["photos"][0]["key"] == key
    got = auth_client.get("/api/day-sheet/photo/" + key)
    assert got.status_code == 200 and got.data == b"JPEGDATA" and "private" in got.headers["Cache-Control"]
    other = "daysheet/someone-else/" + "b" * 32 + ".jpg"
    assert auth_client.get("/api/day-sheet/photo/" + other).status_code == 404
    assert auth_client.post("/api/day-sheet/photo/delete", json={"date": "2026-11-14", "key": other}).status_code == 404
    bad = auth_client.post("/api/day-sheet/photo", data={"image": (io.BytesIO(b"x"), "a.pdf", "application/pdf")},
                           content_type="multipart/form-data")
    assert bad.status_code == 400
    j = auth_client.post("/api/day-sheet/photo/delete", json={"date": "2026-11-14", "key": key}).get_json()
    assert j["photos"] == [] and sent[-1].startswith("DEL ") and store["d"]["photos"] == []


def test_csp_allows_wasm_only(client):
    csp = client.get("/login").headers.get("Content-Security-Policy", "")
    assert "'wasm-unsafe-eval'" in csp and "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")


def test_ocr_is_self_hosted():
    """Scanning must not call out to any service: the OCR engine, its core
    and the English data are served from this app."""
    import os
    base = os.path.join(os.path.dirname(__file__), "..", "static", "js", "vendor", "tesseract-7.0.0")
    for f in ("tesseract.min.js", "worker.min.js", "core/tesseract-core-lstm.wasm.js",
              "core/tesseract-core-simd-lstm.wasm.js", "lang/eng.traineddata.gz"):
        assert os.path.getsize(os.path.join(base, f)) > 10000, f
    src = open(os.path.join(os.path.dirname(__file__), "..", "static", "js", "day_sheet_scan.js")).read()
    assert "/static/js/vendor/tesseract-7.0.0" in src and "workerBlobURL: false" in src
    assert "api.anthropic" not in src and "generativelanguage" not in src and "fetch(" not in src
