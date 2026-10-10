"""Share to DailyPlanner: confirm before saving, and choose where it goes.

A link shared from another app used to be saved the instant it arrived,
always to the Inbox, with guessed labels. Now the first hit shows a
confirm page and saves nothing; the form on it saves to the chosen place.
"""
import re
import pytest


@pytest.fixture
def share(monkeypatch):
    import routes.inbox as ib
    saved = []
    monkeypatch.setattr(ib, "fetch_meta", lambda url: {"title": "Running on-call well", "description": "A talk", "duration_seconds": 1500})
    monkeypatch.setattr(ib, "post", lambda table, payload, **kw: saved.append((table, payload)) or [payload])
    return saved


def _token(client):
    body = client.get("/inbox/share?url=https://example.com/talk").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', body).group(1)


def test_a_share_shows_a_confirm_page_and_saves_nothing(auth_client, share):
    r = auth_client.post("/inbox/share", data={"url": "https://example.com/talk", "title": "x"})
    body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Save to DailyPlanner" in body and "Running on-call well" in body
    assert 'name="destination" value="travel"' in body
    assert share == [], "nothing may be saved before the user confirms"


def test_confirming_saves_to_the_inbox_with_chosen_labels(auth_client, share):
    tok = _token(auth_client)
    r = auth_client.post("/inbox/share", data={
        "csrf_token": tok, "confirm": "1", "url": "https://example.com/talk",
        "title": "Edited title", "category": "Learning",
        "labels": ["drivable", "not-a-label"], "destination": "inbox",
    })
    assert r.status_code == 302
    table, row = share[0]
    assert table == "inbox_links"
    assert row["title"] == "Edited title" and row["category"] == "Learning"
    assert row["labels"] == ["drivable"], "only known labels are kept"


def test_confirming_can_send_it_to_travelreads(auth_client, share):
    tok = _token(auth_client)
    auth_client.post("/inbox/share", data={
        "csrf_token": tok, "confirm": "1", "url": "https://example.com/talk",
        "title": "Talk", "destination": "travel", "duration_seconds": "1500",
    })
    table, row = share[0]
    assert table == "travel_reads" and row["duration_minutes"] == 25 and row["source"] == "example.com"


def test_confirming_can_send_it_to_references(auth_client, share):
    tok = _token(auth_client)
    auth_client.post("/inbox/share", data={
        "csrf_token": tok, "confirm": "1", "url": "https://example.com/talk",
        "title": "Talk", "description": "<script>x</script>Notes", "destination": "references",
    })
    table, row = share[0]
    assert table == "reference_links" and "<script>" not in row["description"]


def test_the_confirm_step_needs_its_token(auth_client, share):
    r = auth_client.post("/inbox/share", data={"confirm": "1", "url": "https://example.com/talk"})
    assert r.status_code == 400 and share == []


# ── Today: first run ───────────────────────────────────────────────────

def test_a_brand_new_account_sees_the_first_steps_on_today(auth_client, monkeypatch):
    import routes.planner as pl
    monkeypatch.setattr(pl, "get", lambda *a, **kw: [])
    body = auth_client.get("/summary?view=daily").get_data(as_text=True)
    assert "md-first-run" in body and 'href="/google-login"' in body


def test_an_account_with_tasks_never_sees_them(auth_client, monkeypatch):
    import routes.planner as pl
    monkeypatch.setattr(pl, "get", lambda table, params=None, **kw: [{"user_id": "x"}] if table == "project_tasks" else [])
    body = auth_client.get("/summary?view=daily").get_data(as_text=True)
    assert "md-first-run" not in body


def test_the_home_list_shows_a_loading_skeleton(auth_client):
    body = auth_client.get("/quick-bucket").get_data(as_text=True)
    assert 'class="qb-skeleton"' in body and 'aria-busy="true"' in body


def test_the_reminders_prompt_has_a_remembered_not_now():
    js = open("static/js/push.js", encoding="utf-8").read()
    tpl = open("templates/checklist.html", encoding="utf-8").read()
    assert 'id="cl-push-notnow"' in tpl and "SNOOZE_DAYS" in js and "localStorage" in js
