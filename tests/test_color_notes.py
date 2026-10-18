"""Color Notes: API, trash/purge rules, and reminder firing."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from requests.exceptions import HTTPError


def _match(row, params):
    for k, v in (params or {}).items():
        if k in ("select", "order", "limit"):
            continue
        val = row.get(k)
        if v == "is.null":
            if val is not None:
                return False
        elif v == "not.is.null":
            if val is None:
                return False
        elif v == "is.false":
            if val:
                return False
        elif v.startswith("eq."):
            if str(val) != v[3:] and not (isinstance(val, bool) and str(val).lower() == v[3:]):
                return False
        elif v.startswith("lte."):
            if val is None or val > v[4:]:
                return False
    return True


@pytest.fixture
def notes(monkeypatch):
    import routes.color_notes as cn
    rows = []

    def fake_get(table, params=None, **kw):
        return [dict(r) for r in rows if _match(r, params)]

    def fake_post(table, payload, **kw):
        row = dict({"is_pinned": False, "is_archived": False, "remind_at": None, "remind_repeat": "none",
                    "deleted_at": None, "purged_at": None, "created_at": "2026-10-19T00:00:00+00:00",
                    "updated_at": "2026-10-19T00:00:00+00:00"}, **payload, id=f"n{len(rows) + 1}")
        rows.append(row)
        return [dict(row)]

    def fake_update(table, params=None, json=None, **kw):
        for r in rows:
            if _match(r, params):
                r.update(json)

    monkeypatch.setattr(cn, "get", fake_get)
    monkeypatch.setattr(cn, "post", fake_post)
    monkeypatch.setattr(cn, "update", fake_update)
    return rows


def test_page_renders_and_is_in_the_menu(auth_client):
    r = auth_client.get("/color-notes")
    assert r.status_code == 200
    assert b"Color Notes" in r.data and b"color_notes.js" in r.data
    assert b'href="/color-notes"' in auth_client.get("/color-notes").data


def test_create_edit_and_list(auth_client, notes):
    r = auth_client.post("/api/color-notes", json={"kind": "checklist", "title": " Groceries ", "color": "green",
                                                   "items": [{"id": "a", "text": "Milk"}, {"text": "Eggs", "done": True}, "junk"]})
    assert r.status_code == 201
    item = r.get_json()["item"]
    assert item["title"] == "Groceries" and item["color"] == "green" and item["user_id"] == "test-user-id"
    assert [i["text"] for i in item["items"]] == ["Milk", "Eggs"] and item["items"][1]["done"] is True
    assert item["items"][1]["id"]                       # an id is given to items that had none
    nid = item["id"]
    r = auth_client.post(f"/api/color-notes/{nid}", json={"color": "blue", "is_pinned": True, "user_id": "someone-else"})
    assert r.status_code == 200 and r.get_json()["item"]["color"] == "blue" and r.get_json()["item"]["is_pinned"] is True
    assert notes[0]["user_id"] == "test-user-id"        # unknown fields are ignored
    assert len(auth_client.get("/api/color-notes").get_json()["items"]) == 1


def test_validation(auth_client, notes):
    assert auth_client.post("/api/color-notes", json={"color": "pink"}).status_code == 400
    assert auth_client.post("/api/color-notes", json={"kind": "drawing"}).status_code == 400
    nid = auth_client.post("/api/color-notes", json={"title": "x"}).get_json()["item"]["id"]
    assert auth_client.post(f"/api/color-notes/{nid}", json={"remind_at": "tomorrow"}).status_code == 400
    assert auth_client.post(f"/api/color-notes/{nid}", json={"remind_at": "2026-10-20T09:00:00"}).status_code == 400  # no timezone
    assert auth_client.post(f"/api/color-notes/{nid}", json={"remind_repeat": "hourly"}).status_code == 400
    r = auth_client.post(f"/api/color-notes/{nid}", json={"remind_at": "2026-10-20T09:00:00+05:30", "remind_repeat": "weekly"})
    assert r.get_json()["item"]["remind_at"] == "2026-10-20T03:30:00+00:00"   # stored in UTC
    assert auth_client.post("/api/color-notes/nope", json={"title": "y"}).status_code == 404


def test_other_users_notes_are_invisible(auth_client, notes):
    notes.append({"id": "theirs", "user_id": "other", "title": "secret", "purged_at": None, "deleted_at": None})
    assert auth_client.get("/api/color-notes").get_json()["items"] == []
    assert auth_client.post("/api/color-notes/theirs", json={"title": "mine now"}).status_code == 404
    assert auth_client.post("/api/color-notes/theirs/trash").status_code == 404
    assert notes[0]["title"] == "secret"


def test_trash_restore_purge_and_empty(auth_client, notes):
    a = auth_client.post("/api/color-notes", json={"title": "a", "is_pinned": True}).get_json()["item"]["id"]
    b = auth_client.post("/api/color-notes", json={"title": "b"}).get_json()["item"]["id"]
    # Delete forever only from Trash.
    assert auth_client.post(f"/api/color-notes/{a}/purge").status_code == 409
    item = auth_client.post(f"/api/color-notes/{a}/trash").get_json()["item"]
    assert item["deleted_at"] and item["is_pinned"] is False
    assert auth_client.post(f"/api/color-notes/{a}/restore").get_json()["item"]["deleted_at"] is None
    auth_client.post(f"/api/color-notes/{a}/trash")
    assert auth_client.post(f"/api/color-notes/{a}/purge").status_code == 200
    ids = [n["id"] for n in auth_client.get("/api/color-notes").get_json()["items"]]
    assert ids == [b]
    assert len(notes) == 2                              # soft delete: the row is kept
    auth_client.post(f"/api/color-notes/{b}/trash")
    auth_client.post("/api/color-notes/trash/empty")
    assert auth_client.get("/api/color-notes").get_json()["items"] == []


def test_missing_table_is_reported(auth_client, monkeypatch):
    import routes.color_notes as cn

    def boom(*a, **k):
        raise Exception('relation "color_notes" does not exist')
    monkeypatch.setattr(cn, "get", boom)
    j = auth_client.get("/api/color-notes").get_json()
    assert j == {"items": [], "migration_pending": True}


# ── reminders ───────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")


def test_next_occurrence_keeps_the_local_time():
    from services.color_note_reminders import next_occurrence
    when = datetime(2026, 1, 31, 9, 0, tzinfo=IST).astimezone(timezone.utc)
    now = datetime(2026, 1, 31, 9, 0, 30, tzinfo=IST).astimezone(timezone.utc)
    assert next_occurrence(when, "daily", now, IST).astimezone(IST) == datetime(2026, 2, 1, 9, 0, tzinfo=IST)
    assert next_occurrence(when, "weekly", now, IST).astimezone(IST) == datetime(2026, 2, 7, 9, 0, tzinfo=IST)
    # 31 Jan monthly -> 28 Feb (clamped), not 3 March
    assert next_occurrence(when, "monthly", now, IST).astimezone(IST) == datetime(2026, 2, 28, 9, 0, tzinfo=IST)
    assert next_occurrence(when, "yearly", now, IST).astimezone(IST) == datetime(2027, 1, 31, 9, 0, tzinfo=IST)
    assert next_occurrence(when, "none", now, IST) is None
    # Several days late: jumps past now, does not replay every missed day.
    later = now + timedelta(days=3, hours=2)
    assert next_occurrence(when, "daily", later, IST).astimezone(IST) == datetime(2026, 2, 4, 9, 0, tzinfo=IST)


def test_preview_text_and_checklist():
    from services.color_note_reminders import preview
    assert preview({"kind": "text", "body": "Call  the\nplumber"}) == "Call the plumber"
    items = [{"text": "Milk", "done": False}, {"text": "Eggs", "done": True}, {"text": "Bread", "done": False}]
    assert preview({"kind": "checklist", "items": items}) == "Milk · Bread"
    assert preview({"kind": "checklist", "items": [{"text": "x", "done": True}]}) == "All items checked"
    assert len(preview({"kind": "text", "body": "word " * 100})) <= 140


@pytest.fixture
def remind(monkeypatch):
    from services import color_note_reminders as cr
    rows, sent, claims = [], [], set()

    def fake_get(table, params=None, **kw):
        return [dict(r) for r in rows if _match(r, params)]

    def fake_update(table, params=None, json=None, **kw):
        for r in rows:
            if _match(r, params):
                r.update(json)

    def fake_post(table, payload, **kw):
        key = (payload["item_id"], payload["sent_date"])
        if key in claims:
            err = HTTPError("dup")
            err.response = type("R", (), {"status_code": 409})()
            raise err
        claims.add(key)
        return []

    monkeypatch.setattr(cr, "get", fake_get)
    monkeypatch.setattr(cr, "update", fake_update)
    monkeypatch.setattr(cr, "post", fake_post)
    monkeypatch.setattr(cr.push_service, "send_to_user",
                        lambda uid, **kw: sent.append((uid, kw)) or (1, 0))
    return cr, rows, sent


def _note(**kw):
    base = {"id": "n1", "user_id": "u1", "kind": "text", "title": "Pay rent", "body": "Before the 5th",
            "items": [], "remind_repeat": "none", "deleted_at": None, "purged_at": None, "is_archived": False}
    base.update(kw)
    return base


def test_one_off_reminder_fires_once_and_clears(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 9, 0, 20, tzinfo=IST)
    rows.append(_note(remind_at=datetime(2026, 10, 19, 9, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()))
    assert cr.fire("u1", now) == ["n1"]
    uid, kw = sent[0]
    assert uid == "u1" and kw["title"] == "📝 Pay rent" and kw["body"] == "Before the 5th"
    assert kw["url"] == "/color-notes?open=n1"
    assert rows[0]["remind_at"] is None and rows[0]["last_reminded_at"]
    assert cr.fire("u1", now + timedelta(minutes=1)) == []          # nothing left
    assert len(sent) == 1


def test_repeating_reminder_moves_on(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 21, 0, 10, tzinfo=IST)
    rows.append(_note(remind_at=datetime(2026, 10, 19, 21, 0, tzinfo=IST).astimezone(timezone.utc).isoformat(),
                      remind_repeat="daily"))
    assert cr.fire("u1", now) == ["n1"]
    assert datetime.fromisoformat(rows[0]["remind_at"]).astimezone(IST) == datetime(2026, 10, 20, 21, 0, tzinfo=IST)


def test_not_sent_twice_by_two_workers(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 9, 0, 20, tzinfo=IST)
    at = datetime(2026, 10, 19, 9, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()
    rows.append(_note(remind_at=at))
    cr._claim("u1", "n1", at, "2026-10-19")                          # another worker won
    assert cr.fire("u1", now) == [] and sent == []


def test_old_missed_reminders_are_skipped_quietly(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 9, 0, tzinfo=IST)
    rows.append(_note(remind_at=(now - timedelta(days=2)).astimezone(timezone.utc).isoformat(), remind_repeat="weekly"))
    assert cr.fire("u1", now) == [] and sent == []
    assert datetime.fromisoformat(rows[0]["remind_at"]) > now      # moved to the next week


def test_trashed_or_archived_notes_do_not_remind(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 9, 0, 20, tzinfo=IST)
    at = datetime(2026, 10, 19, 9, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()
    rows.append(_note(id="t", remind_at=at, deleted_at="2026-10-18T00:00:00+00:00"))
    rows.append(_note(id="a", remind_at=at, is_archived=True))
    assert cr.fire("u1", now) == [] and sent == []


def test_scheduler_calls_color_note_reminders():
    import inspect
    from services import push_scheduler
    assert "color_note_reminders.fire(user_id, now_local)" in inspect.getsource(push_scheduler.tick)


def test_pin_to_notification_bar(auth_client, notes, monkeypatch):
    from services import push_service
    sent = []
    monkeypatch.setattr(push_service, "send_to_user", lambda uid, **kw: sent.append(kw) or (1, 0))
    nid = auth_client.post("/api/color-notes", json={"kind": "checklist", "title": "Shop",
                                                      "items": [{"text": "Milk"}, {"text": "Eggs", "done": True}]}).get_json()["item"]["id"]
    j = auth_client.post(f"/api/color-notes/{nid}/notify", json={"on": True}).get_json()
    assert j["on"] is True and j["sent"] == 1 and j["item"]["notify_pinned"] is True
    kw = sent[-1]
    assert kw["title"] == "\U0001F4CC Shop" and kw["body"] == "☐ Milk\n☑ 1 done"
    assert kw["tag"] == f"cnote-pin-{nid}" and kw["extra"]["silent"] is True and kw["extra"]["requireInteraction"] is True
    # Off: no push, flag cleared. Trash also clears it.
    j = auth_client.post(f"/api/color-notes/{nid}/notify", json={"on": False}).get_json()
    assert j["item"]["notify_pinned"] is False and len(sent) == 1
    auth_client.post(f"/api/color-notes/{nid}/notify", json={"on": True})
    assert auth_client.post(f"/api/color-notes/{nid}/trash").get_json()["item"]["notify_pinned"] is False
    assert auth_client.post(f"/api/color-notes/{nid}/notify", json={"on": True}).status_code == 409


def test_shade_text_limits():
    from routes.color_notes import shade_text
    many = [{"text": f"item {i}"} for i in range(14)]
    out = shade_text({"kind": "checklist", "items": many})
    assert out.count("☐") == 10 and out.endswith("+4 more")
    assert shade_text({"kind": "text", "body": ""}) == "Tap to open"
    assert len(shade_text({"kind": "text", "body": "x" * 1000})) == 400
