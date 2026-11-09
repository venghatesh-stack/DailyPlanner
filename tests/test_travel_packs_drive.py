"""Ready-made TravelReads packs and the Drive Queue playlist mode."""
import json


def _pack(tmp_path, monkeypatch):
    import routes.travel_reads as tr
    d = tmp_path / "packs"; d.mkdir()
    (d / "demo.json").write_text(json.dumps({"title": "Demo", "items": [
        {"url": "https://www.youtube.com/watch?v=aaaAAA11111", "minutes": 10, "title": "01 · A", "notes": "**Big idea** A"},
        {"url": "https://www.youtube.com/watch?v=bbbBBB22222", "minutes": 5, "title": "02 · B", "notes": "B notes"},
    ]}))
    monkeypatch.setattr(tr, "_PACK_DIR", str(d))
    return tr


def test_pack_list_and_add(auth_client, monkeypatch, tmp_path):
    tr = _pack(tmp_path, monkeypatch)
    saved, patched = [], []
    monkeypatch.setattr(tr, "get", lambda *a, **k: [{"id": "x1", "url": "https://www.youtube.com/watch?v=bbbBBB22222", "notes": ""}])
    monkeypatch.setattr(tr, "post", lambda t, row, **k: saved.append(row) or [row])
    monkeypatch.setattr(tr, "update", lambda t, f, patch, **k: patched.append(patch) or [patch])
    j = auth_client.get("/api/travel-reads/packs").get_json()
    assert j["packs"] == [{"slug": "demo", "title": "Demo", "description": "", "count": 2, "minutes": 15}]
    j = auth_client.post("/api/travel-reads/packs/demo/add", json={}).get_json()
    assert j == {"ok": True, "added": 1, "notes_filled": 1}
    assert saved[0]["title"] == "01 · A" and "drivable" in saved[0]["labels"] and saved[0]["notes"].startswith("**Big")
    assert patched == [{"notes": "B notes"}]
    assert auth_client.post("/api/travel-reads/packs/../x/add", json={}).status_code == 404
    assert auth_client.post("/api/travel-reads/packs/nope/add", json={}).status_code == 404


def test_shipped_ted_pack_is_valid():
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "travel_packs", "ted-drive.json")
    pk = json.load(open(p, encoding="utf-8"))
    items = pk["items"]
    assert len(items) == 33 and len({i["url"] for i in items}) == 33
    assert all(i["url"].startswith("https://www.youtube.com/watch?v=") and 0 < i["minutes"] <= 30 for i in items)
    assert all(len(i["notes"]) > 200 for i in items)


def test_drive_queue_queue_order(auth_client, monkeypatch):
    import routes.inbox as ib

    def fake_get(table, params=None, **k):
        if table == "travel_reads":
            return [{"id": f"t{n}", "url": f"https://www.youtube.com/watch?v=vid{n:08d}", "title": f"T{n}",
                     "duration_minutes": m, "labels": ["drivable"], "notes": "n"} for n, m in ((1, 5), (2, 30), (3, 20))]
        return [{"id": "i1", "url": "https://x.com/a", "title": "I", "duration_seconds": 3600, "labels": ["drivable"]}]
    monkeypatch.setattr(ib, "get", fake_get)
    j = auth_client.get("/api/drive-queue?minutes=40&order=queue").get_json()
    assert [i["id"] for i in j["items"]] == ["t1", "t2", "t3"]   # queue order, stops once 40 min is reached
    assert j["items"][0]["notes"] == "n"
    j = auth_client.get("/api/drive-queue?minutes=600&order=queue").get_json()
    assert j["target_minutes"] == 600 and [i["id"] for i in j["items"]] == ["t1", "t2", "t3", "i1"]
    page = auth_client.get("/drive-queue").data
    assert b"Play all" in page and b"8 hr trip" in page


def test_every_pack_is_valid():
    import os, re
    d = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "travel_packs")
    for f in os.listdir(d):
        pk = json.load(open(os.path.join(d, f), encoding="utf-8"))
        assert re.fullmatch(r"[a-z0-9-]{1,60}\.json", f) and pk["title"] and pk["items"], f
        urls = [i["url"] for i in pk["items"]]
        assert len(urls) == len(set(urls)), f
        for i in pk["items"]:
            assert re.fullmatch(r"https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}", i["url"]), (f, i["url"])
            assert i["title"] and int(i["minutes"]) > 0
