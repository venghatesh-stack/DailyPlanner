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
                    "checklist_item_id": None, "notify_pinned": False,
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


@pytest.fixture
def widget(monkeypatch, notes):
    import routes.color_notes as cn
    tokens = []
    real_get, real_post, real_update = cn.get, cn.post, cn.update

    def g(table, params=None, **kw):
        if table == "widget_tokens":
            return [dict(t) for t in tokens if _match(t, params)]
        return real_get(table, params, **kw)

    def p(table, payload, **kw):
        if table == "widget_tokens":
            row = dict(payload, id=f"t{len(tokens) + 1}", revoked_at=None, created_at="x", last_used_at=None)
            tokens.append(row)
            return [dict(row)]
        return real_post(table, payload, **kw)

    def u(table, params=None, json=None, **kw):
        if table == "widget_tokens":
            for t in tokens:
                if _match(t, params):
                    t.update(json)
            return None
        return real_update(table, params, json, **kw)

    monkeypatch.setattr(cn, "get", g)
    monkeypatch.setattr(cn, "post", p)
    monkeypatch.setattr(cn, "update", u)
    return tokens


def test_widget_token_flow(auth_client, client, widget, notes):
    auth_client.post("/api/color-notes", json={"title": "Pinned list", "kind": "checklist", "is_pinned": True,
                                               "items": [{"id": "i1", "text": "Milk"}]})
    auth_client.post("/api/color-notes", json={"title": "Other", "body": "x"})
    j = auth_client.post("/api/color-notes/widget-token", json={"label": "Pixel"}).get_json()
    token = j["token"]
    assert token.startswith("dpw_") and j["connect_url"].startswith("dpnotes://connect?server=")
    assert widget[0]["token_hash"] != token and len(widget[0]["token_hash"]) == 64   # only the hash is stored
    assert [t["label"] for t in auth_client.get("/api/color-notes/widget-tokens").get_json()["items"]] == ["Pixel"]

    H = {"Authorization": f"Bearer {token}"}
    with client.session_transaction() as s:      # the widget has no login cookie
        s.clear()
    assert client.get("/api/widget/notes").status_code == 401
    assert client.get("/api/widget/notes", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/api/widget/notes", headers=H).get_json()
    assert r["scope"] == "pinned" and [n["title"] for n in r["notes"]] == ["Pinned list"]
    r = client.get("/api/widget/notes?scope=all", headers=H).get_json()
    assert len(r["notes"]) == 2
    nid = r["notes"][0]["id"] if r["notes"][0]["title"] == "Pinned list" else r["notes"][1]["id"]
    r = client.post(f"/api/widget/notes/{nid}/toggle", json={"item_id": "i1"}, headers=H)
    assert r.status_code == 200 and r.get_json()["note"]["items"][0]["done"] is True
    assert client.post(f"/api/widget/notes/{nid}/toggle", json={"item_id": "zz"}, headers=H).status_code == 404
    assert widget[0]["last_used_at"]
    # Revoked tokens stop working.
    with client.session_transaction() as s:
        s.update({"user_id": "test-user-id", "_user_id": "test-user-id", "_fresh": True, "authenticated": True})
    assert auth_client.post(f"/api/color-notes/widget-token/{widget[0]['id']}/revoke").get_json()["ok"]
    assert client.get("/api/widget/notes", headers=H).status_code == 401


# ── reminders -> Daily Checklist (-> Google Calendar) ───────────────────
def test_plan_maps_repeats_to_checklist_schedules():
    from services.color_note_links import plan
    base = {"id": "n", "title": "Pay rent", "kind": "text", "body": "Before the 5th"}
    at = datetime(2026, 10, 19, 9, 30, tzinfo=IST).astimezone(timezone.utc).isoformat()   # a Monday
    p = plan(dict(base, remind_at=at, remind_repeat="none"), IST)
    assert p["schedule"] == "once" and p["schedule_days"] == "2026-10-19"
    assert p["reminder_time"] == "09:30:00" and p["time_of_day"] == "morning"
    assert p["name"] == "\U0001F4DD Pay rent" and p["group_name"] == "Color Notes" and "Before the 5th" in p["notes"]
    assert plan(dict(base, remind_at=at, remind_repeat="daily"), IST)["schedule"] == "daily"
    w = plan(dict(base, remind_at=at, remind_repeat="weekly"), IST)
    assert (w["schedule"], w["schedule_days"]) == ("custom", "1")                 # Monday, Sun=0
    mo = plan(dict(base, remind_at=at, remind_repeat="monthly"), IST)
    assert (mo["schedule"], mo["schedule_days"]) == ("monthly_dom", "19")
    assert plan(dict(base, remind_at=at, remind_repeat="yearly"), IST)["schedule"] == "once"
    # No checklist item without a reminder, or for archived / trashed notes.
    assert plan(base, IST) is None
    assert plan(dict(base, remind_at=at, is_archived=True), IST) is None
    assert plan(dict(base, remind_at=at, deleted_at="x"), IST) is None
    # Untitled notes are named from their text or first item.
    assert plan({"id": "n", "kind": "checklist", "items": [{"text": "Milk"}], "remind_at": at}, IST)["name"] == "\U0001F4DD Milk"


@pytest.fixture
def linked(monkeypatch, notes):
    """Notes + a fake checklist table, with Calendar calls recorded."""
    import routes.checklist as ck
    import routes.color_notes as cn
    from services import color_note_links as cl
    import services.push_scheduler as ps
    items, times, cal = [], [], []

    def table(t):
        return {"checklist_items": items, "checklist_reminder_times": times}.get(t)

    note_get, note_post, note_update = cn.get, cn.post, cn.update

    def g(t, params=None, **kw):
        rows = table(t)
        if rows is None:
            return note_get(t, params, **kw)
        return [dict(r) for r in rows if _match(r, params)]

    def p(t, payload, **kw):
        rows = table(t)
        if rows is None:
            return note_post(t, payload, **kw)
        row = dict(payload, id=f"{t[:2]}{len(rows) + 1}")
        rows.append(row)
        return [dict(row)]

    def u(t, params=None, json=None, **kw):
        rows = table(t)
        if rows is None:
            return note_update(t, params, json, **kw)
        for r in rows:
            if _match(r, params):
                r.update(json)

    def d(t, params=None, **kw):
        rows = table(t)
        rows[:] = [r for r in rows if not _match(r, params)]

    for mod in (cl, ck):
        monkeypatch.setattr(mod, "get", g)
        monkeypatch.setattr(mod, "post", p)
        monkeypatch.setattr(mod, "update", u)
    monkeypatch.setattr(cl, "sb_delete", d)
    monkeypatch.setattr(ck, "sb_delete", d)
    monkeypatch.setattr(cn, "get", g)
    monkeypatch.setattr(cn, "update", u)
    monkeypatch.setattr(ps, "_user_tz_name", lambda uid: "Asia/Kolkata")
    monkeypatch.setattr(ck, "_sync_children_calendar_async", lambda uid, row, a, r: cal.append(("sync", row["name"], [x["reminder_time"] for x in a], len(r))))
    monkeypatch.setattr(ck, "_resync_all_children_calendar_async", lambda uid, row: cal.append(("resync", row["name"])))
    monkeypatch.setattr(ck.cal_sync, "delete_from_calendar", lambda uid, ev: cal.append(("delete", ev)))
    return {"items": items, "times": times, "cal": cal, "notes": notes}


def test_reminder_creates_and_follows_a_checklist_item(auth_client, linked):
    items, times, cal = linked["items"], linked["times"], linked["cal"]
    r = auth_client.post("/api/color-notes", json={"title": "Pay rent", "body": "Before the 5th",
                                                   "remind_at": "2026-10-20T09:00:00+05:30"})
    note = r.get_json()["item"]
    assert note["checklist_item_id"] == items[0]["id"]
    assert items[0]["schedule"] == "once" and items[0]["schedule_days"] == "2026-10-20"
    assert [t["reminder_time"] for t in times] == ["09:00:00"]
    assert cal[-1] == ("sync", "\U0001F4DD Pay rent", ["09:00:00"], 0)          # Google Calendar event
    nid = note["id"]
    # Move the time and make it weekly: same item, new time and schedule.
    auth_client.post(f"/api/color-notes/{nid}", json={"remind_at": "2026-10-21T18:15:00+05:30", "remind_repeat": "weekly"})
    assert len([i for i in items if not i.get("is_deleted")]) == 1
    assert (items[0]["schedule"], items[0]["schedule_days"], items[0]["time_of_day"]) == ("custom", "3", "evening")
    assert [t["reminder_time"] for t in times] == ["18:15:00"]
    # Renaming the note renames the item and its Calendar event.
    auth_client.post(f"/api/color-notes/{nid}", json={"title": "Pay house rent"})
    assert items[0]["name"] == "\U0001F4DD Pay house rent" and cal[-1] == ("resync", "\U0001F4DD Pay house rent")
    # Body edits alone do not touch the checklist or Calendar.
    n_cal = len(cal)
    auth_client.post(f"/api/color-notes/{nid}", json={"body": "edited"})
    assert len(cal) == n_cal
    # Removing the reminder removes the item and its Calendar events.
    times[0]["google_event_id"] = "gev1"
    auth_client.post(f"/api/color-notes/{nid}", json={"remind_at": None})
    assert items[0]["is_deleted"] is True and times == []
    assert linked["notes"][0]["checklist_item_id"] is None


def test_trash_and_archive_take_the_item_away(auth_client, linked):
    items = linked["items"]
    nid = auth_client.post("/api/color-notes", json={"title": "A", "remind_at": "2026-10-20T09:00:00+05:30",
                                                     "remind_repeat": "daily"}).get_json()["item"]["id"]
    auth_client.post(f"/api/color-notes/{nid}/trash")
    assert items[-1]["is_deleted"] is True
    auth_client.post(f"/api/color-notes/{nid}/restore")                         # back again
    live = [i for i in items if not i.get("is_deleted")]
    assert len(live) == 1 and live[0]["schedule"] == "daily"
    auth_client.post(f"/api/color-notes/{nid}", json={"is_archived": True})
    assert not [i for i in items if not i.get("is_deleted")]


def test_add_to_checklist_without_a_reminder(auth_client, linked):
    nid = auth_client.post("/api/color-notes", json={"kind": "checklist", "title": "Packing",
                                                     "items": [{"text": "Charger"}]}).get_json()["item"]["id"]
    j = auth_client.post(f"/api/color-notes/{nid}/checklist").get_json()
    assert j["ok"] and j["timed"] is False
    item = linked["items"][-1]
    assert item["schedule"] == "once" and item["time_of_day"] == "anytime" and item["name"] == "\U0001F4DD Packing"
    assert linked["times"] == []                                                  # no time, so no push or Calendar


def test_fired_one_off_keeps_its_checklist_item(auth_client, linked):
    items = linked["items"]
    nid = auth_client.post("/api/color-notes", json={"title": "Call", "remind_at": "2026-10-20T09:00:00+05:30"}).get_json()["item"]["id"]
    linked["notes"][0]["remind_at"] = None                                      # the scheduler fired and cleared it
    auth_client.post(f"/api/color-notes/{nid}", json={"title": "Call bank"})
    assert items[0].get("is_deleted") is not True


def test_linked_notes_are_not_pushed_twice(remind):
    cr, rows, sent = remind
    now = datetime(2026, 10, 19, 9, 0, 20, tzinfo=IST)
    rows.append(_note(remind_at=datetime(2026, 10, 19, 9, 0, tzinfo=IST).astimezone(timezone.utc).isoformat(),
                      checklist_item_id="ci1"))
    assert cr.fire("u1", now) == ["n1"]
    assert sent == []                                   # the checklist item announces it instead
    assert rows[0]["remind_at"] is None                 # but the note still moves on


def test_missing_new_column_does_not_break_notes_or_reminders(auth_client, monkeypatch, remind):
    """v336 went live before its SQL was run: Supabase answered 42703 for
    checklist_item_id and every reminder stopped. Reads must fall back."""
    import routes.color_notes as cn
    from requests.exceptions import HTTPError

    def missing(params):
        if "checklist_item_id" in (params.get("select") or "") or "notify_pinned" in (params.get("select") or ""):
            err = HTTPError("400 Client Error")
            err.response = type("R", (), {"status_code": 400, "text": '{"code":"42703","message":"column color_notes.checklist_item_id does not exist"}'})()
            raise err

    store = [{"id": "a", "user_id": "test-user-id", "title": "Old", "kind": "text", "purged_at": None, "deleted_at": None}]

    def g(table, params=None, **kw):
        missing(params or {})
        return [dict(r) for r in store if _match(r, params)]
    monkeypatch.setattr(cn, "get", g)
    j = auth_client.get("/api/color-notes").get_json()
    assert [n["title"] for n in j["items"]] == ["Old"]

    cr, rows, sent = remind
    real = cr.get
    monkeypatch.setattr(cr, "get", lambda t, params=None, **kw: (missing(params), real(t, params))[1])
    now = datetime(2026, 10, 19, 9, 0, 20, tzinfo=IST)
    rows.append(_note(remind_at=datetime(2026, 10, 19, 9, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()))
    assert cr.fire("u1", now) == ["n1"] and len(sent) == 1          # the reminder still goes out


def test_widget_can_create_and_edit_notes(auth_client, client, widget, notes):
    j = auth_client.post("/api/color-notes/widget-token", json={"label": "Phone"}).get_json()
    H = {"Authorization": f"Bearer {j['token']}"}
    with client.session_transaction() as s:
        s.clear()
    assert client.post("/api/widget/notes", json={"title": "x"}).status_code == 401
    r = client.post("/api/widget/notes", headers=H, json={"kind": "checklist", "title": "Shop", "color": "green",
                                                         "items": [{"id": "a", "text": "Milk"}], "user_id": "hacker"})
    assert r.status_code == 201
    note = r.get_json()["note"]
    assert note["title"] == "Shop" and note["color"] == "green" and notes[-1]["user_id"] == "test-user-id"
    r = client.post(f"/api/widget/notes/{note['id']}", headers=H,
                    json={"items": [{"id": "a", "text": "Milk"}, {"id": "b", "text": "Eggs"}], "remind_at": "2030-01-01T00:00:00Z",
                          "deleted_at": "now"})
    out = r.get_json()["note"]
    assert [i["text"] for i in out["items"]] == ["Milk", "Eggs"]
    assert out["remind_at"] is None and not out.get("deleted_at")          # reminders/trash stay in the planner
    assert client.post(f"/api/widget/notes/{note['id']}", headers=H, json={"color": "pink"}).status_code == 400
    assert client.post("/api/widget/notes/nope", headers=H, json={"title": "y"}).status_code == 404
