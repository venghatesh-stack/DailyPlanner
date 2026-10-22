"""Prescriptions: private uploads (MIGRATION_PRESCRIPTIONS.sql)."""
import io

import pytest


@pytest.fixture
def rx(monkeypatch):
    import routes.prescriptions as p
    rows, stored, removed = [], {}, []

    def get(t, params=None, **k):
        out = [r for r in rows if r["user_id"] == params["user_id"][3:] and not r["is_deleted"]]
        if "id" in params:
            out = [r for r in out if r["id"] == params["id"][3:]]
        return [dict(r) for r in out]

    def post(t, row, **k):
        r = {"id": f"p{len(rows) + 1}", "is_deleted": False, "created_at": "2026-10-22T10:00:00Z",
             "title": "", "patient": "", "doctor": "", "clinic": "", "notes": "", "prescribed_on": None, **row}
        rows.append(r)
        return [dict(r)]

    def update(t, params, changes, **k):
        for r in rows:
            if r["id"] == params["id"][3:]:
                r.update(changes)

    class R:
        def __init__(self, ok=True, content=b"", status=200):
            self.ok, self.content, self.status_code, self.text, self.headers = ok, content, status, "", {}

    def rpost(url, headers=None, data=None, **k):
        stored[url.split("/prescriptions/", 1)[1]] = data
        return R()

    def rget(url, headers=None, **k):
        key = url.split("/prescriptions/", 1)[1]
        return R(content=stored[key]) if key in stored else R(ok=False, status=404)

    def rdelete(url, headers=None, json=None, **k):
        removed.extend(json["prefixes"])
        return R()

    monkeypatch.setattr(p, "get", get)
    monkeypatch.setattr(p, "post", post)
    monkeypatch.setattr(p, "update", update)
    monkeypatch.setattr(p.requests, "post", rpost)
    monkeypatch.setattr(p.requests, "get", rget)
    monkeypatch.setattr(p.requests, "delete", rdelete)
    return {"rows": rows, "stored": stored, "removed": removed}


def test_prescription_upload_view_edit_delete(auth_client, rx):
    c = auth_client
    assert c.get("/prescriptions").status_code == 200
    assert b"/prescriptions" in c.get("/health").data
    assert c.post("/api/prescriptions", data={"title": "x"}).status_code == 400   # no file
    bad = c.post("/api/prescriptions", data={"files": (io.BytesIO(b"MZ"), "virus.exe")},
                 content_type="multipart/form-data")
    assert bad.status_code == 400
    r = c.post("/api/prescriptions", data={
        "title": "Fever", "patient": "Amma", "doctor": "Dr. Rao", "prescribed_on": "2026-10-20",
        "notes": "Paracetamol 650, 3 days",
        "files": [(io.BytesIO(b"\xff\xd8jpegdata"), "rx.jpg"), (io.BytesIO(b"%PDF-1.4"), "rx.pdf")],
    }, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    item = r.get_json()["item"]
    assert item["patient"] == "Amma" and len(item["files"]) == 2
    assert all(k.startswith("test-user-id/") for k in rx["stored"])
    # Private: streamed to the owner, never cached, no public URL anywhere.
    f = c.get(item["files"][0]["url"])
    assert f.status_code == 200 and f.data == b"\xff\xd8jpegdata"
    assert "no-store" in f.headers["Cache-Control"] and f.mimetype == "image/jpeg"
    assert "/object/public/" not in str(c.get("/api/prescriptions").get_json())
    assert c.get(f"/api/prescriptions/{item['id']}/file/9").status_code == 404
    # Another user cannot see or fetch it.
    rx["rows"][0]["user_id"] = "someone-else"
    assert c.get(item["files"][0]["url"]).status_code == 404
    assert c.get("/api/prescriptions").get_json()["items"] == []
    rx["rows"][0]["user_id"] = "test-user-id"
    # Edit details and remove a page.
    e = c.post(f"/api/prescriptions/{item['id']}", data={"doctor": "Dr. Meena", "prescribed_on": "bad"})
    assert e.status_code == 400
    e = c.post(f"/api/prescriptions/{item['id']}", data={"doctor": "Dr. Meena"})
    assert e.get_json()["item"]["doctor"] == "Dr. Meena"
    d = c.post(f"/api/prescriptions/{item['id']}/file/1/delete")
    assert len(d.get_json()["item"]["files"]) == 1 and rx["removed"]
    assert c.post(f"/api/prescriptions/{item['id']}/file/0/delete").status_code == 400
    # Soft delete.
    assert c.post(f"/api/prescriptions/{item['id']}/delete").get_json()["ok"]
    assert c.get("/api/prescriptions").get_json()["items"] == []
    assert rx["rows"][0]["is_deleted"] is True
