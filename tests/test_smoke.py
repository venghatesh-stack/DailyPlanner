"""
tests/test_smoke.py
──────────────────
Smoke tests — the "does the house still have a roof" layer. Runs in
seconds, catches the regressions users actually hit:

  • App boots without error
  • Every registered blueprint exposes at least one route
  • Every registered route resolves for unauth GET (302 to /login or 200)
  • Every page template renders without Jinja errors
  • Auth-required pages return redirects when unauthed (302)
  • Protected pages return 200 with a seeded session

Run with:  python -m pytest tests/test_smoke.py -v
"""
import inspect
import re

import pytest


# ═══════════════════════════════════════════════════
# 1. Boot / import chain
# ═══════════════════════════════════════════════════

def test_app_factory_runs(app):
    """create_app() must return a Flask instance with url rules registered."""
    assert app is not None
    assert len(app.url_map._rules) > 0, "no routes registered — blueprint wiring broken"


def test_all_expected_blueprints_present(app):
    """If someone removes a blueprint by accident, this catches it.

    Blueprint NAMES (what flask stores in app.blueprints.keys()) can
    differ from the Python variable name — e.g. inbox_bp is named
    "inbox_bp" via `Blueprint("inbox_bp", __name__)`. We check what
    Flask actually registers, not the variable name."""
    expected = {
        "auth", "planner", "todo", "projects", "health", "habits",
        "references", "ai", "events", "timeline", "notes", "system",
        "inbox_bp", "refcards", "portfolio", "goals", "reports",
    }
    registered = set(app.blueprints.keys())
    missing = expected - registered
    assert not missing, f"blueprints missing: {missing} (registered: {sorted(registered)})"


# ═══════════════════════════════════════════════════
# 2. Core page routes render without error
# ═══════════════════════════════════════════════════

PUBLIC_ROUTES = [
    "/login",
    "/health_check",   # if it exists; the test is resilient
]


@pytest.mark.parametrize("path", PUBLIC_ROUTES)
def test_public_routes_respond(client, path):
    r = client.get(path, follow_redirects=False)
    # 200 for pages that render, 302 for redirects, 404 if optional route missing.
    assert r.status_code in (200, 301, 302, 404), f"{path} unexpected status {r.status_code}"


PROTECTED_PAGES = [
    "/",
    "/todo",
    "/calendar",
    "/inbox",
    "/projects",
    "/projects/timeline",
    "/goals",
    "/summary?view=daily",
    "/summary?view=weekly",
    "/reports",
    "/notes/scribble",
    "/references",
    "/refcards",
    "/portfolio",
    "/health",
]


@pytest.mark.parametrize("path", PROTECTED_PAGES)
def test_protected_pages_redirect_when_unauth(client, path):
    """Every protected page must 302-redirect when no session is active."""
    r = client.get(path, follow_redirects=False)
    # Some pages may return 401/403 directly; all non-2xx is fine here
    # so long as they don't return 500 (template/route bug).
    assert r.status_code < 500, (
        f"{path} returned {r.status_code} unauthed — possible template or "
        f"route bug. Response excerpt: {r.data[:300]!r}"
    )


@pytest.mark.parametrize("path", PROTECTED_PAGES)
def test_protected_pages_render_when_authed(auth_client, path):
    """With a seeded session, pages should render (200) or redirect
    sensibly (302 — e.g., /health may redirect based on mode). No 500s.

    Templates must not throw Jinja errors on empty data — all the
    supabase stubs return []."""
    r = auth_client.get(path, follow_redirects=False)
    assert r.status_code < 500, (
        f"{path} returned {r.status_code} — template or route bug. "
        f"Response excerpt: {r.data[:400]!r}"
    )


# ═══════════════════════════════════════════════════
# 3. Agenda service — pure logic, no side effects
# ═══════════════════════════════════════════════════

def test_agenda_service_build_dashboard_shape():
    """The morning-dashboard payload shape must not change — the UI
    depends on exactly these keys."""
    from datetime import date
    from services.agenda_service import build_dashboard
    d = build_dashboard("test-user", date(2026, 4, 18))
    assert isinstance(d, dict)
    assert set(d.keys()) >= {"today_items", "overdue", "habits", "counts"}
    assert set(d["counts"].keys()) >= {"meetings", "tasks", "habits", "habits_done", "overdue"}


def test_the_dashboard_reads_run_concurrently_not_one_after_another():
    """Reported 2026-08-30: "clicking todays plan is very slow".

    Measured: sixteen Supabase round trips, one after another, with every
    table EMPTY — so the page cost the sum of them before Jinja saw a
    byte. None of the ten fetchers depends on another, so the sum was
    never necessary: the page only ever needed the slowest one.

    This drives real threads against a stubbed client that sleeps, and
    fails if the total ever creeps back towards the serial sum. It is a
    timing test, so the margin is deliberately wide — it is there to
    catch a `for` loop reappearing, not to measure milliseconds.
    """
    import time
    from datetime import date
    from unittest.mock import patch
    import services.agenda_service as a

    DELAY = 0.05
    calls = []

    def _slow_get(table, params=None):
        calls.append(table)
        time.sleep(DELAY)
        return []

    with patch.object(a, "get", _slow_get):
        t0 = time.perf_counter()
        d = a.build_dashboard("test-user", date(2026, 4, 18))
        elapsed = time.perf_counter() - t0

    assert d["today_items"] == []
    serial = len(calls) * DELAY
    assert elapsed < serial / 2, (
        f"{len(calls)} reads took {elapsed:.2f}s; serial would be "
        f"{serial:.2f}s — the fan-out is gone")


def test_one_broken_table_cannot_take_the_dashboard_down():
    """The fetchers were guarded individually before the fan-out; running
    them in threads must not lose that. A future that raises has to come
    back as an empty section, not a 500 on the morning page."""
    from datetime import date
    from unittest.mock import patch
    import services.agenda_service as a

    def _broken_get(table, params=None):
        if table == "todo_matrix":
            raise RuntimeError("PostgREST is having a day")
        return []

    with patch.object(a, "get", _broken_get):
        d = a.build_dashboard("test-user", date(2026, 4, 18))

    assert d["today_items"] == []
    assert d["counts"]["tasks"] == 0
    assert set(d.keys()) >= {"today_items", "overdue", "habits", "counts"}


def test_agenda_habits_template_contract():
    """Regression: Today's Plan (summary.html) reads `h.name`, `h.value`,
    `h.goal`, `h.unit`, `h.habit_type`, `h.progress_pct` directly. If the
    agenda service stops returning any of these keys, the template fails
    with a Jinja `|format` TypeError at render time (undefined → %g).

    Seen in prod on Render: line 234 of summary.html would crash when a
    user with habits loaded the morning dashboard."""
    from datetime import date
    from unittest.mock import patch
    import services.agenda_service as a

    def _fake_get(table, **kw):
        if table == "habit_master":
            return [{"id": 7, "name": "water", "unit": "L", "goal": 2.0,
                     "habit_type": "number", "position": 0}]
        if table == "habit_entries":
            return [{"habit_id": 7, "value": "1.2"}]
        return []

    with patch.object(a, "get", side_effect=_fake_get):
        items = a.fetch_habits("test-user", date(2026, 4, 18))

    assert len(items) == 1
    h = items[0]
    # These are the EXACT keys summary.html reads — changing any breaks
    # the template. If you must rename, update the template too.
    for required in ("name", "value", "goal", "unit", "habit_type",
                     "progress_pct", "done"):
        assert required in h, f"habit item missing '{required}' — summary.html will crash"
    assert h["name"] == "water"
    assert h["value"] == 1.2
    assert h["goal"] == 2.0
    assert h["unit"] == "L"


def test_agenda_sort_timed_then_untimed():
    """Items with a time come first, untimed items last. Crucial for the
    morning dashboard's chronological layout."""
    from services.agenda_service import _sort_timed_then_untimed
    items = [
        {"time": None, "title": "Untimed A", "priority": "medium"},
        {"time": "09:00", "title": "Morning meeting", "priority": "medium"},
        {"time": None, "title": "Untimed B", "priority": "medium"},
        {"time": "14:00", "title": "Afternoon", "priority": "medium"},
    ]
    _sort_timed_then_untimed(items)
    titles = [it["title"] for it in items]
    assert titles[0] == "Morning meeting"
    assert titles[1] == "Afternoon"
    assert set(titles[2:]) == {"Untimed A", "Untimed B"}


# ═══════════════════════════════════════════════════
# 4. Reports service — range parsing + aggregation contracts
# ═══════════════════════════════════════════════════

def test_reports_productivity_empty_safe():
    """On a user with zero tasks, the productivity report returns a
    zero-filled payload, not a crash."""
    from datetime import date
    from services.reports_service import productivity_report
    r = productivity_report("test-user", date(2026, 4, 1), date(2026, 4, 7))
    assert r["totals"]["total"] == 0
    assert r["totals"]["rate"] == 0
    assert len(r["daily"]) == 7


def test_reports_financial_empty_safe():
    """Financial snapshot on an empty vault → zeros, no division by zero."""
    from datetime import date
    from services.reports_service import financial_report
    r = financial_report("test-user", date(2026, 4, 18))
    assert r["portfolio"]["invested"] == 0
    assert r["portfolio"]["market_value"] == 0
    assert r["bills"]["monthly_equivalent"] == 0


# ═══════════════════════════════════════════════════
# 5. Vault password lifecycle — without real Supabase
# ═══════════════════════════════════════════════════

def test_vault_status_unconfigured(auth_client, monkeypatch):
    """Vault not set up → configured=False, unlocked=False. UI uses this
    to show the setup screen."""
    import routes.refcards as rc
    monkeypatch.setattr(rc, "_vault_row", lambda _: None)
    r = auth_client.get("/api/refcards/vault/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["configured"] is False
    assert body["unlocked"] is False


# ═══════════════════════════════════════════════════
# 6. Encryption round-trip
# ═══════════════════════════════════════════════════

def test_copy_prev_route_is_gone(client):
    """Regression: /todo/copy-prev was retired. If somebody restores the
    route without also restoring proper user scoping + undo UX, this
    test fires a warning bell. 404 is the expected status.

    Context: the previous impl had a NameError and a missing user_id
    filter (data leak). Morning Dashboard replaces the feature."""
    r = client.post("/todo/copy-prev", follow_redirects=False)
    assert r.status_code in (404, 405), (
        f"/todo/copy-prev returned {r.status_code} — it was retired. "
        f"See Morning Dashboard for the replacement read-through view."
    )


def test_copy_prev_service_import_is_gone():
    """The service function copy_open_tasks_from_previous_day was
    retired along with the route. Re-introducing it without the fixes
    (user scoping, undo, audit) would re-introduce a data-leak bug."""
    import services.eisenhower_service as es
    assert not hasattr(es, "copy_open_tasks_from_previous_day"), (
        "copy_open_tasks_from_previous_day should stay retired — see "
        "the comment block where it used to live in eisenhower_service.py"
    )


def test_encryption_roundtrip():
    from utils.encryption import encrypt, decrypt
    secret = "ABCDE1234F"   # a PAN-shaped string
    cipher = encrypt(secret)
    assert cipher != secret
    assert decrypt(cipher) == secret


def test_encryption_handles_empty():
    from utils.encryption import encrypt, decrypt
    assert encrypt("") == ""
    assert decrypt("") == ""
    assert decrypt(None) is None


# ── AI SDE prep bank content invariants ────────────────────────────────────
# The bank patches worked examples onto entries by TITLE, through the _EX_*
# dicts in ai_sde_bank.py. A typo in a key fails silently — the entry simply
# never receives its examples — which is how "Raising the bar on hiring or
# quality" sat empty while the batch was reported as complete. These turn both
# content invariants into failing tests instead of something you notice later.

def test_ai_sde_example_keys_all_match_a_real_entry():
    import ai_sde_bank as bank
    titles = {e["title"] for e in bank.ENTRIES}
    orphans = []
    for name in dir(bank):
        if not name.startswith("_EX_"):
            continue
        table = getattr(bank, name)
        if isinstance(table, dict):
            orphans += [(name, key) for key in table if key not in titles]
    assert not orphans, (
        "these worked-example keys match no entry title, so their examples are "
        f"silently dropped: {orphans}"
    )


def test_ai_sde_p0_entries_all_carry_worked_examples():
    """P0 is the 'do these first' band, and the standing bar is 5+ varied
    worked examples per entry. Adding entries moves the P0 percentile cut, so
    this can regress without anyone touching the band deliberately."""
    import ai_sde_bank as bank
    short = [e["title"] for e in bank.ENTRIES
             if e["priority"] == "P0" and len(e.get("examples") or []) < 5]
    assert not short, (
        f"{len(short)} P0 entries have fewer than 5 worked examples: "
        f"{short[:5]}{'...' if len(short) > 5 else ''}"
    )


def test_ai_sde_list_payload_excludes_the_heavy_examples():
    """The list endpoint must stay light. A fully written-up topic carries
    ~16k characters of worked examples; shipping every topic's examples on
    every page load put the payload on course for ~10MB. The list sends a
    count instead, and the bodies come from /api/ai-sde/entry/<id>."""
    import json
    import ai_sde_bank as bank
    items = [{k: v for k, v in e.items() if k != "examples"}
             for e in bank.ENTRIES]
    assert all("examples" not in it for it in items)
    size_mb = len(json.dumps(items)) / 1e6
    assert size_mb < 6, (
        f"the AI SDE list payload is {size_mb:.1f}MB even without examples; "
        "another field has grown and needs the same lazy-load treatment"
    )


def test_ai_sde_tags_use_only_the_controlled_vocabulary():
    """Every tag value must come from the six fixed lists, and every key in
    TAGS must match a real entry title. A mis-keyed title silently drops its
    tags with no error - exactly the trap that cost a wrong 'complete' claim
    with the example dicts - so it is checked rather than assumed."""
    import ai_sde_bank as bank
    import ai_sde_tags
    ai_sde_tags.validate(bank.ENTRIES)


def test_ai_sde_tagged_entries_carry_all_six_dimensions():
    """No blanks: an entry is either untagged or has all six columns."""
    import ai_sde_bank as bank
    partial = [e["title"] for e in bank.ENTRIES
               if any("tag_" + d in e for d in ai_sde_dims())
               and not all("tag_" + d in e for d in ai_sde_dims())]
    assert not partial, f"entries tagged on some dimensions but not all: {partial[:5]}"


def ai_sde_dims():
    import ai_sde_tags
    return ai_sde_tags.DIMENSIONS


def test_ai_sde_tag_priority_is_not_a_rubber_stamp():
    """If Must-Know swallows the bank the tagging is worthless. Guard the
    calibration itself: once a decent slice is tagged, Must-Know must stay a
    minority and Rare must be genuinely used."""
    import ai_sde_bank as bank
    import ai_sde_tags
    if bank.TAGGED_COUNT < 100:
        return  # too early in the tagging pass to judge the distribution
    c = ai_sde_tags.counts(bank.ENTRIES)["priority"]
    total = sum(c.values())
    assert c["Must-Know"] / total < 0.40, (
        f"Must-Know is {c['Must-Know'] / total:.0%} of tagged entries - "
        "the priority dimension has stopped discriminating"
    )
    assert c["Rare"] / total > 0.10, (
        f"Rare is only {c['Rare'] / total:.0%} of tagged entries - "
        "nothing is being marked genuinely infrequent"
    )


def test_ai_sde_every_tagged_entry_has_a_legal_subtopic():
    """SUBTOPIC is the seventh column and is scoped per topic - a DSA subtopic
    on an NLP-LLM row is a mis-tag, not a free-text note. `validate` checks the
    pairing; this checks nothing was left blank, since a blank subtopic makes
    the study-page filter silently lose the entry."""
    import ai_sde_bank as bank
    blank = [e["title"] for e in bank.ENTRIES
             if "tag_topic" in e and not e.get("tag_subtopic")]
    assert not blank, (
        f"{len(blank)} tagged entries have no subtopic: "
        f"{blank[:5]}{'...' if len(blank) > 5 else ''}"
    )


def test_ai_sde_api_ships_the_tag_vocabulary_and_per_entry_tags(auth_client):
    """The filter dropdowns are built from the vocabulary the API serves, so a
    value added to ai_sde_tags.py appears in the UI without touching the
    template. If this payload loses tag_vocab the tag row silently goes empty."""
    r = auth_client.get("/api/ai-sde")
    assert r.status_code == 200
    body = r.get_json()
    vocab = body.get("tag_vocab") or {}
    for key in ("topic", "level", "priority", "format", "stage", "time", "subtopics"):
        assert vocab.get(key), f"tag_vocab is missing {key}"
    untagged = [e["title"] for e in body["entries"] if "tag_priority" not in e]
    assert not untagged, f"{len(untagged)} entries reach the page untagged: {untagged[:5]}"


def test_ai_sde_tag_filters_narrow_and_ignore_junk(app):
    """?tpriority/?ttopic/?tsub narrow the export. An unknown value must widen
    to everything rather than returning an empty page, so a stale bookmark
    degrades gracefully instead of looking like a broken bank."""
    import routes.interview_prep as ip
    from ai_sde_bank import ENTRIES
    items = [{"id": f"ai{i}", **e} for i, e in enumerate(ENTRIES)]

    with app.test_request_context("/?tpriority=Must-Know&ttopic=DSA&tsub=Graphs"):
        narrowed, bits = ip._ai_sde_tag_select(items)
    assert bits == ["Must-Know", "DSA", "Graphs"]
    assert narrowed and len(narrowed) < len(items)
    assert all(e["tag_priority"] == "Must-Know" and e["tag_subtopic"] == "Graphs"
               for e in narrowed)

    with app.test_request_context("/?tpriority=NotAValue"):
        wide, bits = ip._ai_sde_tag_select(items)
    assert len(wide) == len(items) and bits == []


def _pdf_text(data):
    """The visible text of a PDF built by _pdf_bytes().

    The export embeds a real Unicode font, so box-drawing and arrows survive
    instead of being transliterated to ASCII by _latin1(). The cost is that
    the content streams now hold two-byte GLYPH IDS rather than readable
    characters, and each of the three embedded fonts numbers its glyphs
    independently — so the old "decompress and grep for ASCII" only ever
    worked because the core fonts wrote latin-1 directly.

    Decoding that correctly means resolving each font's /ToUnicode CMap and
    tracking which font is selected at every Tf. pypdf already does exactly
    that, and a hand-rolled version in a test would be a second PDF parser
    to maintain. Skips rather than silently passing when pypdf is absent.

    Whitespace is COLLAPSED. Body text is 26pt, so a phrase routinely breaks
    across lines, and justified output extracts with doubled spaces — an
    assertion about content should not fail over either. This helper is
    therefore for "is it in there", never for layout.
    """
    import io
    import re
    pypdf = pytest.importorskip(
        "pypdf", reason="pypdf not installed; cannot decode embedded-font text")
    reader = pypdf.PdfReader(io.BytesIO(data))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", raw)


def test_ai_sde_pdf_carries_the_interview_tags(auth_client):
    """The exported sheet must show the tags, not just filter by them."""
    pytest.importorskip("fpdf", reason="fpdf2 not installed; PDF route falls back to a redirect")
    r = auth_client.get("/ai-sde/pdf?tpriority=Must-Know&ttopic=DSA&tsub=Graphs")
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"

    text = _pdf_text(r.get_data())
    assert "INTERVIEW TAGS" in text, "the PDF lost the Interview tags field"
    assert "Must-Know for a new grad" in text
    assert "DSA / Graphs" in text
    # The heading names the filter, so the sheet says what it is.
    assert "Must-Know" in text[:400]


# ═══════════════════════════════════════════════════
# Goal planner — countdown maths, coach calibration, page
# ═══════════════════════════════════════════════════

def _tz_and_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Kolkata")
    return tz, datetime(2026, 8, 15, 9, 0, tzinfo=tz)


def test_countdown_resolves_a_bare_date_to_end_of_day():
    """A date means "by the end of that day". Treating it as midnight would
    silently steal the last 24 hours of every goal."""
    from utils.countdown import resolve_target
    tz, _ = _tz_and_now()
    got = resolve_target(None, "2026-08-20", tz)
    assert (got.hour, got.minute, got.second) == (23, 59, 59)
    # An explicit moment must win over the date and keep its own time.
    exact = resolve_target("2026-08-20T14:30:00+05:30", "2026-08-20", tz)
    assert (exact.hour, exact.minute) == (14, 30)


def test_countdown_unit_escalates_towards_the_deadline():
    """The headline unit getting finer IS the urgency signal, so nothing has
    to flash while a goal is still weeks away. Also pins the tick rate: a
    per-second redraw six weeks out is pure battery burn."""
    from datetime import timedelta
    from utils.countdown import breakdown, display, TICK_SECOND, TICK_HOUR
    _, now = _tz_and_now()
    far = display(breakdown(now + timedelta(days=45), now))
    near = display(breakdown(now + timedelta(hours=12), now))
    assert (far["unit"], far["tone"], far["tick"]) == ("weeks", "calm", TICK_HOUR)
    assert near["tone"] == "urgent" and near["tick"] == TICK_SECOND
    late = display(breakdown(now - timedelta(days=2), now))
    assert late["tone"] == "overdue" and late["value"] == 2


def test_countdown_split_is_complementary():
    """16 days must read "2w 2d", never "2w 16d" — the parts sum to the whole."""
    from datetime import timedelta
    from utils.countdown import breakdown
    _, now = _tz_and_now()
    b = breakdown(now + timedelta(days=16), now)
    assert (b["weeks"], b["days"]) == (2, 2)
    assert b["total_days"] == 16


def test_countdown_working_days_excludes_weekends():
    """"44 days" quietly includes a dozen days nobody was going to work."""
    from datetime import date
    from utils.countdown import working_days
    # Mon 17 Aug 2026 → Fri 28 Aug is 12 calendar days, 10 working.
    assert working_days(date(2026, 8, 17), date(2026, 8, 28)) == 10
    assert working_days(date(2026, 8, 15), date(2026, 8, 16)) == 0   # a weekend
    assert working_days(date(2026, 8, 20), date(2026, 8, 10)) == 0   # end before start
    # A six-day study week loses only the Sunday.
    assert working_days(date(2026, 8, 17), date(2026, 8, 28), (0, 1, 2, 3, 4, 5)) == 11


def test_countdown_budget_flags_an_impossible_goal():
    """The most valuable number on the page: whether the remaining time can
    physically hold the remaining work, while re-scoping is still cheap."""
    from utils.countdown import budget
    # `days_left`, not `working_days_left` — a "per day" commitment is taken
    # at its word; see test_budget_takes_a_daily_commitment_at_its_word.
    b = budget(days_left=31, daily_commit_minutes=120, effort_minutes=139 * 60)
    assert b["feasible"] is False
    assert b["shortfall_minutes"] == 139 * 60 - 31 * 120
    assert b["required_daily_minutes"] == round(139 * 60 / 31)
    # Without both halves the answer would be a guess, so there isn't one.
    assert budget(31, 120, None) is None
    assert budget(31, None, 8340) is None


def test_goal_coach_judges_slippage_relatively_not_in_raw_points():
    """14 points behind at 24% expected means only 40% of the work is done —
    serious. The same 14 points at 90% expected is a rounding error. Absolute
    gaps get this backwards, which is why severity is a ratio."""
    from utils.countdown import summarise
    from services.goal_coach import coach
    tz, now = _tz_and_now()
    goal = {"title": "T", "start_date": "2026-08-01",
            "target_at": "2026-09-28T18:00:00+05:30"}
    early_bad = coach(summarise(goal, now, tz, progress_pct=10), "T", 10)
    assert early_bad[1] == "scold"
    late = {"title": "T", "start_date": "2026-01-01",
            "target_at": "2026-09-01T18:00:00+05:30"}
    late_slip = coach(summarise(late, now, tz, progress_pct=76), "T", 76)
    assert late_slip[1] == "push", "a late-stage 14-point gap is not a scolding"
    # Day one of a long goal must not be scolded for 0% against 0% expected.
    fresh = {"title": "T", "start_date": "2026-08-14",
             "target_at": "2027-08-14T18:00:00+05:30"}
    assert coach(summarise(fresh, now, tz, progress_pct=0), "T", 0)[1] == "cheer"


def test_goal_coach_puts_infeasibility_above_being_on_pace():
    """Being "on pace" for something arithmetically impossible is the most
    dangerous state a plan can be in, so the budget alarm outranks pace."""
    from utils.countdown import summarise
    from services.goal_coach import coach
    tz, now = _tz_and_now()
    goal = {"title": "T", "start_date": "2026-08-01",
            "target_at": "2026-09-28T18:00:00+05:30",
            "daily_commit_minutes": 120, "effort_minutes": 139 * 60}
    msg, tone = coach(summarise(goal, now, tz, progress_pct=33), "T", 33)
    assert tone == "alarm" and "short" in msg


def test_goal_planner_page_and_api(auth_client, monkeypatch):
    """The page renders and the API shapes one goal per objective, sorted by
    urgency with undated goals last."""
    import routes.goals as goals

    objectives = [
        {"id": "g1", "title": "Dated", "status": "active", "start_date": "2026-08-01",
         "target_at": "2036-09-28T18:00:00+05:30", "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "g2", "title": "Undated", "status": "active",
         "created_at": "2026-08-01T00:00:00+00:00"},
    ]
    krs = [{"id": "k1", "objective_id": "g1", "start_value": 0, "current_value": 5,
            "target_value": 10, "direction": "up", "title": "Half done"}]
    monkeypatch.setattr(goals, "get", lambda table, params=None, **kw:
                        objectives if table == "objectives"
                        else (krs if table == "key_results" else []))

    assert auth_client.get("/goal-planner").status_code == 200
    body = auth_client.get("/api/goal-planner").get_json()
    assert [g["title"] for g in body["goals"]] == ["Dated", "Undated"], \
        "undated goals must sink below dated ones — they cannot be urgent"
    dated = body["goals"][0]
    assert dated["progress"] == 50, "progress must roll up from key results"
    assert dated["countdown"]["has_deadline"] is True
    assert body["goals"][1]["countdown"]["has_deadline"] is False
    assert dated["coach"]["message"]


def test_countdown_widget_is_wired_into_goals_and_interview_prep(auth_client):
    """The ticker is shared by three pages. These assertions are the contract
    between countdown.js and its hosts: the script must load, and each page
    must expose the mount points it reads ([data-cd-big] / [data-cd-unit]).
    Rename one of those hooks and the countdown silently shows nothing, which
    is exactly the kind of breakage nobody notices until a deadline passes."""
    for path, hooks in (
        # The planner hero shows the full DAYS : HRS : MINS readout...
        ("/goal-planner", ("data-cd-d", "data-cd-h", "data-cd-m", "data-cd-detail")),
        # ...while dense surfaces use the one-line form of the same thing.
        ("/interview-prep", ("data-cd-compact",)),
    ):
        html = auth_client.get(path).get_data(as_text=True)
        assert "js/countdown.js" in html, f"{path} does not load countdown.js"
        for hook in hooks:
            assert hook in html, f"{path} is missing the {hook} mount point"

    # /goals builds its cards in static/goals.js, so the hooks live there.
    goals_html = auth_client.get("/goals").get_data(as_text=True)
    assert "js/countdown.js" in goals_html, "/goals does not load countdown.js"
    with open("static/goals.js", encoding="utf-8") as fh:
        js = fh.read()
    assert "data-cd-compact" in js and "renderDueBlock" in js
    assert "Countdown.mountAll" in js, "goals.js never mounts the tickers it renders"
    # Re-rendering the list must drop the old instances or detached nodes keep
    # ticking; that leak is invisible until the page has been open for hours.
    assert "Countdown.clear()" in js


def test_countdown_hosts_degrade_without_the_script(auth_client):
    """Every host must guard `typeof Countdown` — the ticker is an
    enhancement, and a failed script load must not blank the page. This
    already happened once on the planner during development."""
    with open("templates/goal_planner.html", encoding="utf-8") as fh:
        planner = fh.read()
    with open("templates/interview_prep.html", encoding="utf-8") as fh:
        prep = fh.read()
    with open("static/goals.js", encoding="utf-8") as fh:
        goals_js = fh.read()
    for name, src in (("goal_planner.html", planner),
                      ("interview_prep.html", prep),
                      ("goals.js", goals_js)):
        # Either spelling of the guard is fine (=== undefined, or !== to take
        # the happy path); what matters is that the reference is guarded at
        # all rather than assumed.
        assert 'typeof Countdown' in src, \
            f"{name} uses Countdown without guarding for it being absent"


def test_relative_deadlines_resolve_server_side(app):
    """A deadline can be given as a duration ("in 45 days") or as a date.
    Durations are resolved against the USER's now, not the browser's — a
    device clock in the wrong timezone must not shift the deadline. Junk and
    obvious typos are rejected rather than stored as a year-4000 date that
    would break every countdown on the page."""
    import routes.goals as goals
    from datetime import datetime
    from utils.user_tz import user_now

    with app.test_request_context():
        now = user_now()
        for payload, unit_seconds in (({"in_days": 45}, 45 * 86400),
                                      ({"in_hours": 36}, 36 * 3600),
                                      ({"in_minutes": 90}, 90 * 60)):
            iso, err = goals._resolve_relative_deadline(payload)
            assert err is None and iso
            delta = (datetime.fromisoformat(iso) - now).total_seconds()
            assert abs(delta - unit_seconds) < 5, f"{payload} landed at {iso}"

        # An explicit moment always wins; the relative field is ignored.
        iso, err = goals._resolve_relative_deadline(
            {"target_at": "2026-09-28T18:00", "in_days": 999})
        assert iso is None and err is None

        for bad in ({"in_days": 0}, {"in_days": -5}, {"in_days": "abc"},
                    {"in_days": 45000}):
            iso, err = goals._resolve_relative_deadline(bad)
            assert iso is None and err, f"{bad} should have been rejected"


def test_countdown_flash_flag_is_permission_not_current_state():
    """`flash` must mean "this goal is ALLOWED to flash", never "it is
    flashing right now".

    It used to be `flash_enabled AND tone is urgent`, which reads as
    equivalent and is not: the client freezes the value at mount, so a page
    opened 30 hours before a deadline was served flash=False and then never
    started flashing when it crossed into its last day. Since the planner is
    meant to sit open all day — on a phone especially — that silently killed
    the whole feature. `flash_now` carries the render-time state instead."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from utils.countdown import summarise
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 8, 15, 9, 0, tzinfo=tz)

    far = summarise({"title": "T", "flash_enabled": True,
                     "target_at": (now + timedelta(hours=30)).isoformat()}, now, tz)
    assert far["flash"] is True, "permission must not depend on how far away it is"
    assert far["flash_now"] is False, "30h out is not yet flashing"

    near = summarise({"title": "T", "flash_enabled": True,
                      "target_at": (now + timedelta(hours=5)).isoformat()}, now, tz)
    assert near["flash"] is True and near["flash_now"] is True

    # An explicit opt-out switches both off at every distance.
    off = summarise({"title": "T", "flash_enabled": False,
                     "target_at": (now + timedelta(hours=5)).isoformat()}, now, tz)
    assert off["flash"] is False and off["flash_now"] is False


def test_flash_survives_reduced_motion_and_paused_animations():
    """The blink must not be a CSS animation alone.

    iOS Low Power Mode pauses CSS animations and Reduce Motion suppresses
    them, and the first version's fallback was `animation: none` — i.e. no
    indication at all on exactly the phones where a deadline matters most.
    countdown.js therefore toggles a class, and pins it ON (rather than
    blinking) when the user has asked for reduced motion."""
    with open("static/js/countdown.js", encoding="utf-8") as fh:
        js = fh.read()
    assert "flash-on" in js, "the blink is not driven from JS"
    assert "prefers-reduced-motion" in js, "reduced motion is not detected in JS"
    assert "clearInterval(flashTimer)" in js, "the flash timer is never stopped"

    for name in ("templates/goal_planner.html", "templates/interview_prep.html"):
        with open(name, encoding="utf-8") as fh:
            css = fh.read()
        assert ".flash-on" in css, f"{name} has no styling for the JS flash state"
        # The old failure mode: an animation with a reduced-motion opt-out
        # that left nothing visible behind it.
        assert "animation: none" not in css, (
            f"{name} still disables the flash outright under reduced motion")


def test_typed_progress_wins_over_the_key_result_rollup(monkeypatch):
    """A goal created on the planner has no key results, so it scored 0 for
    ever and the coach scolded it permanently with no way to answer back.
    A typed percentage overrides the roll-up, and the SOURCE travels with the
    number so a typed 60% next to key results averaging 20% can be labelled
    rather than silently conflated. Clearing it restores the roll-up."""
    import routes.goals as goals
    krs = [{"id": "k1", "objective_id": "withkr", "start_value": 0,
            "current_value": 2, "target_value": 10, "direction": "up"},
           {"id": "k2", "objective_id": "both", "start_value": 0,
            "current_value": 2, "target_value": 10, "direction": "up"}]
    monkeypatch.setattr(goals, "get",
                        lambda table, params=None, **kw: krs if table == "key_results" else [])
    objectives = [
        {"id": "withkr", "title": "rollup only"},
        {"id": "both", "title": "typed beats rollup", "manual_progress": 60},
        {"id": "bare", "title": "nothing"},
        {"id": "typed", "title": "typed only", "manual_progress": 40},
    ]
    out = goals._objective_progress("u1", objectives)
    assert (out["withkr"]["progress"], out["withkr"]["source"]) == (20, "key_results")
    assert (out["both"]["progress"], out["both"]["source"]) == (60, "manual")
    assert out["both"]["rolled_up"] == 20, "the roll-up must stay visible alongside"
    assert (out["bare"]["progress"], out["bare"]["source"]) == (0, "none")
    assert (out["typed"]["progress"], out["typed"]["source"]) == (40, "manual")


def test_typed_progress_is_clamped_and_clearable():
    """150 obviously means "done", so clamp rather than reject — refusing it
    would be pedantic. An empty value clears the override. Genuine junk IS
    rejected, because silently storing 0 would look like lost progress."""
    import routes.goals as goals
    assert goals._clean_manual_progress(55) == (55, None)
    assert goals._clean_manual_progress("55") == (55, None)
    assert goals._clean_manual_progress(150)[0] == 100
    assert goals._clean_manual_progress(-20)[0] == 0
    assert goals._clean_manual_progress(33.7)[0] == 34
    assert goals._clean_manual_progress("") == (None, None)
    assert goals._clean_manual_progress(None) == (None, None)
    value, err = goals._clean_manual_progress("abc")
    assert value is None and err


def test_goal_planner_progress_control_is_a_visible_slider(auth_client):
    """Progress was first a number input styled to look like plain text until
    hovered. It worked perfectly and was unusable: nothing said it could be
    edited, so the reported bug was "not able to enter %". A range input is
    self-evidently draggable, on a phone as much as a desktop.

    Saving must happen on `change` (release) and never on `input`, or one
    drag becomes a hundred PATCHes and a hundred re-renders."""
    html = auth_client.get("/goal-planner").get_data(as_text=True)
    assert 'type="range"' in html, "the progress control is not a slider"
    assert "pctrange" in html and "data-pctout" in html, "no live readout beside the slider"
    assert "data-pct" in html and "savePct" in html
    # The readout updates on input; only change() persists.
    assert 'addEventListener("input"' in html, "readout does not follow the drag"
    assert "preventScroll" in html, "re-render steals focus and jumps the page"


def test_pinned_goal_without_a_deadline_still_renders_a_hero(auth_client, monkeypatch):
    """Found on live data: a goal was pinned with no target date, so the hero
    rendered EMPTY while three dated goals sat in the list below it — the page
    looked broken. Honour the pin either way: show the goal and ask for the
    missing date, rather than blanking or silently substituting another goal."""
    import routes.goals as goals
    objectives = [
        {"id": "pinned", "title": "No date", "status": "active", "is_primary": True,
         "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "dated", "title": "Has a date", "status": "active",
         "target_at": "2036-12-31T18:00:00+05:30", "created_at": "2026-08-01T00:00:00+00:00"},
    ]
    monkeypatch.setattr(goals, "get",
                        lambda table, params=None, **kw: objectives if table == "objectives" else [])
    body = auth_client.get("/api/goal-planner").get_json()
    assert body["primary_id"] == "pinned", "the pin must be respected, not overridden"

    html = auth_client.get("/goal-planner").get_data(as_text=True)
    assert "heroNoDateHTML" in html, "no fallback hero for a pinned goal with no deadline"
    assert "h-set" in html, "the undated hero offers no way to add the missing deadline"


def test_ai_sde_progress_is_keyed_by_title_not_the_positional_id(auth_client, monkeypatch):
    """The list endpoint hands out ids as "ai0", "ai1", ... derived from the
    entry's INDEX in the bank. That index shifts whenever a topic is added or
    deduped — and the bank grew from ~500 to 1,120 entries with 57 duplicates
    folded out, so anything stored against those ids now points at a
    different topic. Progress is therefore stored by title, and a title the
    bank no longer has is DROPPED rather than mapped onto its neighbour."""
    import routes.interview_prep as ip
    real = next(iter(ip._AI_SDE_TITLES))
    rows = [
        {"entry_title": real, "studied": True, "minutes_focused": 25},
        {"entry_title": "A topic that was renamed away", "studied": True,
         "minutes_focused": 99},
    ]
    monkeypatch.setattr(ip, "get", lambda table, params=None, **kw: rows)
    body = auth_client.get("/api/ai-sde/progress").get_json()
    assert body["studied"] == [real]
    assert body["minutes"] == {real: 25}
    assert body["total_rows"] == 2, "the stale row is dropped from the answer, not the count"


def test_ai_sde_progress_rejects_unknown_topics(auth_client, monkeypatch):
    """A title that is not in the bank is a bug or a stale client, never
    something to store — otherwise the table slowly fills with orphans."""
    import routes.interview_prep as ip
    monkeypatch.setattr(ip, "post", lambda *a, **kw: [{}])
    r = auth_client.post("/api/ai-sde/progress", json={"title": "nope", "studied": True})
    assert r.status_code == 400

    real = next(iter(ip._AI_SDE_TITLES))
    saved = {}
    monkeypatch.setattr(ip, "post",
                        lambda table, payload, **kw: saved.update(payload) or [{}])
    r = auth_client.post("/api/ai-sde/progress", json={"title": real, "studied": True})
    assert r.status_code == 200
    assert saved["entry_title"] == real and saved["studied"] is True
    assert saved["studied_at"], "ticking must stamp when it happened"


def test_ai_sde_page_persists_by_title_and_survives_a_missing_table(auth_client):
    """The page must keep working when progress sync is unavailable — the
    localStorage mirror is what makes a tick feel instant, and a 503 from an
    unrun migration must not take the study page down with it."""
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    assert "ai_sde_studied_titles" in html, "still keying local storage on positional ids"
    assert "pushProgress" in html and "syncStudied" in html
    # Union, not replace: an offline tick must not be erased by an older
    # server row when the two are reconciled.
    assert "!studied.has(id)" in html, "server sync overwrites local state instead of merging"


def test_interview_coach_labels_the_ai_sde_categories():
    """The coach is shared by two very different runs — a senior TPM loop and
    a new-grad AI/SDE loop. MIGRATION_AI_SDE_PREP_TRACK.sql seeds the student
    account with dsa / cs_fundamentals / ml / ai_llm categories; without a
    label each the page prints the raw key as a section heading."""
    from routes.interview_prep import CATEGORY_LABELS
    for key in ("dsa", "cs_fundamentals", "ml", "ai_llm"):
        assert key in CATEGORY_LABELS, f"{key} would render as a raw key"


def test_ai_sde_prep_track_migration_is_derived_and_safe():
    """The student's syllabus must come FROM the tagged bank, so the study
    plan and the content cannot drift apart, and it must not hard-delete the
    TPM rows it replaces."""
    import re
    with open("MIGRATION_AI_SDE_PREP_TRACK.sql", encoding="utf-8") as fh:
        sql = fh.read()
    assert "delete from" not in sql.lower(), "house rule: soft delete only"
    assert "set deleted_at = now()" in sql, "the replaced TPM rows are not retired"
    assert "venghateshshreya@gmail.com" in sql, "not scoped to the student account"

    # Every seeded topic must name a real subtopic from the tag vocabulary.
    import ai_sde_tags
    known = {s.replace("-", " ") for subs in ai_sde_tags.SUBTOPICS.values() for s in subs}
    seeded = re.findall(r"'(?:DSA|Core-CS|Python|Classical-ML|Deep-Learning|"
                        r"Math-Stats|NLP-LLM|System-Design|MLOps|Behavioral) — "
                        r"([A-Za-z ]+?) \(\d+ must-know\)'", sql)
    assert seeded, "no derived topics found in the migration"
    unknown = [s for s in seeded if s not in known]
    assert not unknown, f"seeded topics not in the tag vocabulary: {unknown[:5]}"


def test_budget_measures_the_work_that_is_LEFT():
    """Comparing the time remaining against the WHOLE job means the alarm can
    never clear: a goal at 50% reported the full shortfall and shouted just as
    loudly as on day one. An alarm that doing the work cannot silence is one
    you learn to ignore, which defeats the point of having it."""
    from utils.countdown import budget
    # 100 days x 90 min = 150h available, against a 200h job.
    at_zero = budget(100, 90, 200 * 60, progress_pct=0)
    assert at_zero["feasible"] is False
    assert at_zero["needed_minutes"] == 200 * 60

    half = budget(100, 90, 200 * 60, progress_pct=50)
    assert half["needed_minutes"] == 100 * 60, "half done means half the work left"
    assert half["feasible"] is True, "the alarm must clear once the work is done"
    assert half["total_effort_minutes"] == 200 * 60, "the whole job stays visible"

    assert budget(100, 90, 200 * 60, progress_pct=100)["needed_minutes"] == 0


def test_budget_takes_a_daily_commitment_at_its_word():
    """"90 minutes a day" means per DAY. Multiplying it by working days
    quietly assumes weekends off, which understated a student's available
    time by a third and made a workable plan look impossible."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from utils.countdown import summarise
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 8, 15, 9, 0, tzinfo=tz)
    goal = {"title": "T", "start_date": "2026-08-15",
            "target_at": "2026-11-15T09:00:00+05:30",
            "daily_commit_minutes": 90, "effort_minutes": 17065}
    s = summarise(goal, now, tz, progress_pct=0)
    # 92 calendar days, not the 65 working ones.
    assert s["budget"]["available_minutes"] == 92 * 90
    assert s["working_days_left"] == 65, "working days stay reported separately"


def test_ai_sde_tag_filters_do_not_depend_on_the_server_vocabulary(auth_client):
    """The dropdowns are built from `tag_vocab`, but must not REQUIRE it. A
    payload cached from before that field existed left every dropdown empty,
    which presents as "tag filtering is broken" — with no options there is
    nothing to select. The vocabulary is recoverable from the entries, which
    each carry their own tag values."""
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    assert "function tagVocab()" in html, "no fallback when tag_vocab is absent"
    assert "BANK.entries.map(e => e[field])" in html, "vocabulary is not derived from entries"
    # And an untagged bank should hide the row rather than show dead controls.
    assert 'row.style.display = "none"' in html


def test_mobile_layout_cannot_be_cut_off(auth_client):
    """Reported as "in mobile the UI is cutting". Two causes, both real:

    1. .q-head is a flex row that now carries six chips (priority, time,
       frequency, sub-area, difficulty, category) — two of which the tagging
       work added. They are all flex:none, so without wrapping they cannot
       shrink and the row is clipped off the side of the screen.
    2. The worked examples are white-space:pre-wrap and contain ASCII tables
       with unbreakable runs, which widen the card past the viewport unless
       they get their own scroller."""
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    import re
    head = re.search(r"^\s*\.q-head \{[^}]*\}", html, re.M).group(0)
    assert "flex-wrap: wrap" in head, "the six-chip card header cannot wrap"
    for block in (r"^\s*\.ex \.body \{[^}]*\}", r"^\s*\.fld\.deep \{[^}]*\}",
                  r"^\s*\.fld\.recipe \{[^}]*\}"):
        rule = re.search(block, html, re.M).group(0)
        assert "pre-wrap" in rule and "overflow-x: auto" in rule, \
            f"pre-wrap block without a scroller: {rule[:60]}"
    assert "overflow-x: hidden" in html, "the page itself can still scroll sideways"

    planner = auth_client.get("/goal-planner").get_data(as_text=True)
    # Anchored: an unanchored ".row {" also matches "input.pctrange.row {".
    row = re.search(r"^\s*\.row \{[^}]*\}", planner, re.M).group(0)
    assert "flex-wrap: wrap" in row, "planner rows cannot wrap on a phone"


def test_card_title_is_not_sliced_off_on_a_phone(auth_client):
    """Reported as "question is getting cut off". The mobile rule gave the
    title `order: -1` so it took its own line, then pulled it back up beside
    the checkbox with `margin-top: -24px` — a 24px lift into 11px of padding,
    inside a card with overflow: hidden, so the top of every question was
    sliced. The chips now sit in their own wrapper instead, which is what lets
    them drop to a second row without moving the title at all."""
    import re
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    for rule in re.findall(r"^\s*\.q-head \.q-text \{[^}]*\}", html, re.M):
        assert "margin-top: -" not in rule, f"title lifted by a negative margin: {rule}"
        assert "order:" not in rule, f"title reordered away from the checkbox: {rule}"
    assert '<span class="q-chips">' in html, "the header chips have no wrapper to wrap as a group"
    mobile = re.search(r"@media \(max-width: 640px\) \{.*?\n  \}", html, re.S).group(0)
    assert ".q-head .q-chips" in mobile, "the chips never move to their own row on a phone"


def test_card_chips_line_up_between_cards_on_desktop(auth_client):
    """Reported as "misaligned among different cards, hard to read".

    The desktop rule was `display: contents`, which dissolved the wrapper so
    the six chips became plain flex children trailing a flex:1 title, each at
    its natural width. The content varies far too much for that to line up:
    the category label runs 12 to 27 characters, the sub-area 3 to 19. Every
    card put its priority, its time and its difficulty at a different x, so
    reading down a column of cards meant re-finding each chip on every row.

    A fixed-track grid is the fix, and this test is here because
    `display: contents` is the tidier-looking rule and would be easy to
    restore by accident."""
    import re
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    rules = re.findall(r"\.q-head \.q-chips \{[^}]*\}", html)
    assert rules, "no desktop rule for the header chips"
    desktop = rules[0]
    assert "display: contents" not in desktop, (
        "chips back to display: contents — they will not align between cards")
    assert "display: grid" in desktop and "grid-template-columns" in desktop, desktop
    # Fixed tracks, not auto/min-content: a track sized to its content is a
    # track that moves when the content changes, which is the whole bug.
    cols = re.search(r"grid-template-columns:\s*([^;]+);", desktop).group(1)
    assert "auto" not in cols and "min-content" not in cols and "max-content" not in cols, cols
    assert len(cols.split()) >= 6, f"a track per chip is what keeps them aligned: {cols}"
    # A chip whose value overruns must shorten, not widen its track.
    assert "text-overflow: ellipsis" in html


def test_a_timed_task_draws_on_its_own_day_only():
    """A task scheduled for 9am Monday drew a chip at 9am on Tuesday,
    Wednesday and every day after, until it was marked done.

    /api/v2/project-tasks filters `due_date is null OR due_date <= date`,
    which is the right question for the unscheduled backlog panel and the
    wrong one for the grid. drag-to-schedule already writes plan_date
    beside start_time, so the day was recorded — the grid just never
    looked at it, and the endpoint did not even return it."""
    import re
    js = open("static/v2/planner_v2.js", encoding="utf-8").read()
    grid = re.search(r"const timedTasks = taskData\.filter\((.*?)\);", js, re.S).group(1)
    assert "plan_date" in grid, "the grid still ignores which day a task belongs to"
    assert "start_time" in grid
    # ...and it dedupes against the events, because a scheduled prep topic
    # writes both rows on purpose and both need their time.
    assert "evKeys" in grid, "the grid no longer dedupes tasks against events"
    # ...and the endpoint has to actually send it.
    py = open("routes/projects.py", encoding="utf-8").read()
    sel = re.search(r'"select": "task_id,task_text,priority,project_id,[^"]*"'
                    r'(?:\s*"[^"]*")*', py).group(0)
    assert "plan_date" in sel, "plan_date is not in the calendar task payload"
    # A task given a day but no clock time is scheduled, not floating — it
    # must not reappear in the "unscheduled" panel as a second copy.
    floating = re.search(r"const unscheduled = \(tasks \|\| \[\]\)\.filter\((.*?)\);",
                         js, re.S).group(1)
    assert "plan_date" in floating, "a task with a day still lists as unscheduled"


def test_quick_bucket_top5_wraps_instead_of_truncating(auth_client):
    """Today's five are the tasks she actually reads, so a long one must WRAP.
    It used to be white-space: nowrap with an ellipsis, which meant identifying
    a task required clicking it - the opposite of what the panel is for."""
    import re
    html = auth_client.get("/quick-bucket").get_data(as_text=True)
    rule = re.search(r"^\s*\.qb-top5-text \{[^}]*\}", html, re.M)
    assert rule, "no .qb-top5-text rule"
    body = rule.group(0)
    assert "nowrap" not in body and "text-overflow" not in body, f"still truncating: {body}"
    assert "overflow-wrap: anywhere" in body, "a long unbroken string could widen the panel"
    item = re.search(r"^\s*\.qb-top5-item \{[^}]*\}", html, re.M).group(0)
    assert "align-items: flex-start" in item, \
        "with wrapped text, centring floats the rank badge to the middle of the row"


def test_answer_field_keeps_its_line_breaks(auth_client):
    """The answer is the field read under time pressure, and it is now written
    headline-first with short labelled lines under it. That shape only exists
    if the line breaks survive - `.fld.answer` had no `white-space: pre-wrap`
    (unlike `.fld.deep` and `.fld.recipe`), so every rewritten answer would have
    collapsed straight back into the paragraph it came from."""
    import re
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    rule = re.search(r"^\s*\.fld\.answer \{[^}]*\}", html, re.M)
    assert rule, "no .fld.answer block rule at all"
    assert "pre-wrap" in rule.group(0) and "overflow-x: auto" in rule.group(0)
    # The first line is lifted out as a heading, so it reads as one.
    assert "function answerHTML(val)" in html
    assert 'class="head"' in html
    # The quiz shows the same text; it must not collapse it either.
    quiz = auth_client.get("/ai-sde/quiz").get_data(as_text=True)
    for sel in (r"^\s*\.qprompt \{[^}]*\}", r"^\s*\.explain \{[^}]*\}"):
        block = re.search(sel, quiz, re.M)
        assert block and "pre-wrap" in block.group(0), f"quiz rule collapses newlines: {sel}"


def test_rewritten_answers_all_match_a_real_entry(auth_client):
    """Same trap as the `_EX_*` dicts: a mis-keyed title in _ANSWER_V2 rewrites
    nothing at all, silently, and the entry keeps its old prose."""
    import ai_sde_bank as bank
    assert bank.ANSWERS_REWRITTEN == bank.ANSWERS_DECLARED, (
        f"{bank.ANSWERS_DECLARED - bank.ANSWERS_REWRITTEN} rewritten answers are "
        "keyed to a title that does not exist"
    )
    # And every rewritten answer really is headline-first.
    for e in bank.ENTRIES:
        if e["title"] in bank._ANSWER_V2:
            body = e["answer"]
            head, sep, rest = body.partition("\n")
            assert sep, f"{e['title']}: rewritten answer has no headline line"
            assert len(head) <= 160, f"{e['title']}: headline is a paragraph, not a line"
            assert "·" in rest, f"{e['title']}: no labelled points under the headline"


def test_card_body_is_collapsible_and_the_answer_can_be_re_hidden(auth_client):
    """Two requests, one cause: a written-up topic is ~16k characters and every
    section rendered flat, so the card was a wall to scroll past — and the quiz
    reveal was one-way, so an answer once shown could not be put away without
    reloading, which turns the next attempt into re-reading."""
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    assert "function sec(cls, label, inner, opts)" in html, "no collapsible section helper"
    assert '<details class="sec sec-' in html, "sections are not <details>"
    assert '<details class="ex">' in html, "worked examples are not individually collapsible"
    assert "function exSummary(text)" in html, "no summary line for a worked example"
    assert "data-expand" in html, "no expand-all control"
    # The reveal button must survive being pressed, and say so.
    assert '"Hide the answer" : "Show the answer"' in html, "reveal does not toggle back"
    assert ".qi.shown .reveal { display: none; }" not in html, "reveal is still hidden once used"
    review = auth_client.get("/study/review").get_data(as_text=True)
    assert "function hideAnswer()" in review, "study review answer cannot be re-hidden"


def test_the_mobile_day_page_renders_and_carries_the_reflection(auth_client):
    """The day view is a LIST, not the calendar's 24-hour grid.

    Reported twice, from the same root cause: on a phone the grid's chips
    are unreadable slivers, and anything scheduled before its initial
    7am scroll position is off-screen and looks like it does not exist.

    This page has to hold three things together — the timed items, the
    UNTIMED ones (which the grid cannot show at all), and the reflection
    in the same scroll rather than on another page."""
    r = auth_client.get("/day")
    assert r.status_code == 200, r.get_data()[:300]
    html = r.get_data(as_text=True)
    assert "On the clock" in html
    assert "No time set" in html, "untimed items need their own group, not a gap"
    assert 'id="reflection"' in html and 'id="gratitude"' in html
    assert "/api/v2/daily-reflection" in html
    # A phone leaves a page by being backgrounded, not by blurring a field.
    assert "pagehide" in html and "sendBeacon" in html, (
        "typing is lost when the tab is backgrounded mid-edit")
    # Date navigation, so it is usable as a day view and not just as today.
    assert "Previous day" in html and "Next day" in html


def test_the_day_page_survives_a_bad_date(auth_client):
    """A malformed date in a shared link is a bad link, not something to
    show the user a 400 over."""
    r = auth_client.get("/day?date=not-a-date", follow_redirects=False)
    assert r.status_code in (301, 302), r.status_code
    r2 = auth_client.get("/day?date=2026-08-17")
    assert r2.status_code == 200
    assert "17 August 2026" in r2.get_data(as_text=True)


def test_the_calendar_scrolls_to_the_earliest_event_not_a_fixed_hour(auth_client):
    """The grid used to scroll to a hard-coded 7am on load, which put
    anything earlier — study topics booked at 00:00, deliberately, so they
    sit at the top of the day — seven hours above the fold. The page
    looked empty while the entries were there the whole time."""
    import re
    js = open("static/v2/planner_v2.js", encoding="utf-8").read()
    fn = re.search(r"function scrollTo7AM\(\) \{(.*?)\n\}", js, re.S).group(1)
    assert "7 * HOUR_HEIGHT - 20" not in fn, "still hard-scrolling past early events"
    assert "earliest" in fn and "eventsMap" in fn, (
        "the scroll position must be derived from what the day actually holds")


def test_every_question_bank_shows_a_card_summary(auth_client):
    """Reported as "keep card summary for all question banks to be few
    lines, instead of single sentence".

    Four banks, one rule: a few lines of what the entry actually says, on
    the collapsed card, so the list can be skimmed without opening
    anything. The AI/SDE page derives it server-side from the answer; the
    language banks derive it from their plain-English answer; the
    behavioural bank builds it from the coaching tip plus the Situation.
    All four pack WHOLE SENTENCES under a cap, so none is cut mid-clause."""
    for path in ("/ai-sde", "/java", "/sql", "/interview-prep"):
        html = auth_client.get(path).get_data(as_text=True)
        assert 'class="q-sum"' in html, f"{path} has no card summary"
        # And no line-clamp anywhere: the length is bounded at the source,
        # so clamping would reintroduce the cut-off the report was about.
        assert "-webkit-line-clamp" not in html, (
            f"{path} clamps the summary — it will be cut off again")


def test_ai_sde_duplicate_map_is_keyed_to_real_titles():
    """A mis-keyed title in ai_sde_dupes.py silently does nothing at all.

    Same trap as the _EX_* example dicts and ai_sde_tags.py: the key is a
    title string, so a typo produces no error and no effect. validate()
    also rejects a self-reference and a shadow pointing at another shadow.
    """
    import ai_sde_bank as bank
    import ai_sde_dupes
    ai_sde_dupes.validate(bank.ENTRIES)


def test_ai_sde_dedupe_changes_nothing_that_already_existed():
    """The dedupe pass is ADDITIVE. Nothing is dropped and nothing renumbered.

    prep_minutes feeds the stack-rank score and the P0-P3 band cut, so
    zeroing a shadow's minutes there would re-band and renumber all 1,120
    entries. The deduped figure lives in prep_minutes_effective instead,
    and this pins that separation.
    """
    import ai_sde_bank as bank
    assert len(bank.ENTRIES) == 1120, "an entry was dropped"
    assert bank.TOTAL_PREP_MINUTES == sum(e["prep_minutes"] for e in bank.ENTRIES)
    assert bank.DEDUPED_PREP_MINUTES < bank.TOTAL_PREP_MINUTES
    for e in bank.ENTRIES:
        if e.get("duplicate_of"):
            assert e["prep_minutes"] > 0, "the shadow's own minutes were zeroed"
            assert e["prep_minutes_effective"] == 0, "shadow still counted"
            assert e.get("answer"), "the shadow lost its content — nothing is deleted"
        else:
            assert e["prep_minutes_effective"] == e["prep_minutes"]


def test_ai_sde_duplicate_pairs_point_at_the_richer_entry():
    """The canonical must not be the emptier half of the pair.

    The selection rule is: the deep dive wins, else more content wins. A
    pair that fails this is one where the rule was applied backwards and
    she would be sent to the thinner entry.
    """
    import ai_sde_bank as bank
    import ai_sde_dupes
    by_title = {e["title"]: e for e in bank.ENTRIES}
    weight = lambda e: (len(e.get("examples") or []) >= 10,
                        len(e.get("answer") or "") + len(e.get("code") or ""))
    for shadow, (canonical, note) in ai_sde_dupes.DUPES.items():
        s, c = by_title[shadow], by_title[canonical]
        if weight(c) < weight(s):
            assert "RULE OVERRIDDEN" in note, (
                f"{canonical!r} is thinner than the {shadow!r} it supersedes, "
                "with no note explaining why")


def test_ai_sde_merge_pending_pairs_are_not_silently_collapsed():
    """A pair whose rule would shadow the RICHER entry stays open.

    Collapsing it either way destroys the better teaching material, so it
    is flagged as merge-pending rather than resolved wrongly. Both halves
    keep their full prep_minutes because neither has been superseded yet.
    """
    import ai_sde_bank as bank
    import ai_sde_dupes
    by_title = {e["title"]: e for e in bank.ENTRIES}
    assert bank.DUPLICATE_MERGE_PENDING == len(ai_sde_dupes.MERGE_PENDING)
    for a, (b, _note) in ai_sde_dupes.MERGE_PENDING.items():
        for t in (a, b):
            assert by_title[t]["prep_minutes_effective"] == by_title[t]["prep_minutes"]
            assert by_title[t].get("duplicate_merge_pending"), f"{t} not marked"


def test_ai_sde_page_offers_to_hide_duplicate_topics(auth_client):
    """18 topics exist twice, and the two halves land ADJACENT in the study
    order because they score alike — so she meets the same thing twice in a
    row. The page hides them by default and says what that saves.

    The control is revealed by paintDupes() only when the payload actually
    reports shadows, so a bank with no duplicates shows no dead checkbox.
    """
    html = auth_client.get("/ai-sde").get_data(as_text=True)
    assert 'id="hidedupes"' in html, "no way to hide the duplicated topics"
    assert 'checked' in html.split('id="hidedupes"')[1][:40], (
        "duplicates must be hidden by DEFAULT — that is the whole point")
    assert "paintDupes" in html, "the control is never revealed"
    assert "q-dup" in html, "no chip marks which half is the duplicate"

    payload = auth_client.get("/api/ai-sde").get_json()
    assert payload["dupes"]["shadows"] == 18
    assert payload["dupes"]["deduped_minutes"] < payload["dupes"]["total_minutes"]
    shadows = [e for e in payload["entries"] if e.get("duplicate_of")]
    assert len(shadows) == 18, "the list payload cannot collapse what it cannot see"
    titles = {e["title"] for e in payload["entries"]}
    for e in shadows:
        assert e["duplicate_of"] in titles, (
            f"{e['title']!r} points at a canonical that is not in the list")


def test_ai_sde_pdf_does_not_print_the_same_topic_twice(auth_client):
    """On screen she can see two rows are the same topic and skip one. On
    paper she just reads it twice, so the export drops shadows by default.
    ?dupes=1 puts them back."""
    pytest.importorskip("fpdf", reason="fpdf2 not installed; PDF route falls back to a redirect")
    import routes.interview_prep as ip
    src = inspect.getsource(ip.ai_sde_pdf)
    assert 'request.args.get("dupes")' in src, "no escape hatch to print duplicates"
    assert 'it.get("duplicate_of")' in src, "the export still prints both halves"


def test_ai_sde_clocked_minutes_reach_the_server(auth_client, monkeypatch):
    """Pomodoro effort was localStorage-only, so the hours she actually put
    in never left the device — and `minutes_focused` sat unwritten.

    The route already accepted minutes; nothing called it. This pins the
    contract the client now uses: minutes are saved BY TITLE, because the
    "ai{i}" id is the entry's index in the bank and shifts under it.
    """
    import routes.interview_prep as ip
    saved = []
    monkeypatch.setattr(ip, "post", lambda table, payload, **kw: saved.append((table, payload)))

    title = ip.AI_SDE_ENTRIES[0]["title"]
    r = auth_client.post("/api/ai-sde/progress", json={"title": title, "minutes": 42})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert saved, "nothing was written"
    table, payload = saved[-1]
    assert table == "ai_sde_progress"
    assert payload["entry_title"] == title, "keyed on something other than the title"
    assert payload["minutes_focused"] == 42
    assert "ai0" not in str(payload), "a positional id leaked into the row"

    # A title the bank does not hold must be refused, not stored — otherwise
    # a renamed topic accumulates effort nobody can ever read back.
    r = auth_client.post("/api/ai-sde/progress", json={"title": "nope", "minutes": 5})
    assert r.status_code == 400


def test_ai_sde_page_pulls_and_pushes_clocked_effort():
    """Both directions, and the loop-breaker between them.

    Pull: server minutes seed the timers. Push: a changed card is sent
    back. Without the `seeded` guard every page load would echo straight
    back what it had just read.
    """
    html = open("templates/ai_sde.html", encoding="utf-8").read()
    assert "Pomodoro.seed" in html, "server minutes never reach the timers"
    assert "queueEffort" in html, "clocked effort is never sent back"
    assert "detail.seeded" in html or "ev.detail && ev.detail.seeded" in html, (
        "no guard against echoing a server-seeded change back at the server")
    # Sent by title, never by the positional card id.
    push = html.split("async function flushEffort")[1].split("function queueEffort")[0]
    assert "titleOf(id)" in push and "title: title" in push, "pushed by id, not title"
    # A tab-hide is how a page ends on a phone; a 4s debounce would not survive it.
    assert "keepalive" in push, "the last minutes are lost when the tab closes"


def test_pomodoro_seed_unions_by_max_and_never_overwrites_local_time():
    """Time clocked offline has not reached the server yet, so taking the
    server's smaller number would silently delete it. Same union rule the
    studied-set sync follows."""
    js = open("static/js/pomodoro.js", encoding="utf-8").read()
    body = js.split("Controller.prototype.seed = function")[1].split("};")[0]
    assert "> this.logged(id)" in body, (
        "seed() does not compare against the local log — it can overwrite it")
    assert "this.emit(null, true)" in body, "a seeded change is not marked as seeded"


def test_ai_sde_awards_notes_by_title_not_by_positional_id():
    """Sadhana XP is DERIVED from studied topics + clocked minutes, so once
    both sync the bar rebuilds on any device — no table of its own needed.

    But the derivation was keyed on the "ai{i}" id, which is the entry's
    index in the bank. A reshuffle meant the backfill no longer recognised
    topics already paid for and awarded them again. Now keyed on title,
    with a one-time carry-over of the old keys.
    """
    html = open("templates/ai_sde.html", encoding="utf-8").read()
    assert "Gamify.studied(gkey(" in html, "notes are still awarded on the raw id"
    assert "id: gkey(x.title)" in html, "the backfill still keys on the positional id"
    assert "Gamify.rekeyTopics" in html, "no carry-over — existing topics get re-paid"
    assert "ai_sde_gamify_titlekeys_v1" in html, "the carry-over is not guarded, so it can re-run"

    js = open("static/js/gamify.js", encoding="utf-8").read()
    body = js.split("rekeyTopics: function (map)")[1].split("\n    reset:")[0]
    # A rename must not touch the balance — the notes are already banked.
    assert "award(" not in body, "rekeyTopics awards notes; it must only rename keys"


def test_pdf_splits_prose_from_drawn_tables():
    """The worked examples interleave prose with drawn tables in ONE string.

    Rendering the whole thing as prose wraps the tables into noise — which
    is exactly what the export used to do, and the reported complaint.
    Rendering it all as monospace shrinks the prose for no reason. So each
    line is judged and consecutive verdicts are grouped into runs.
    """
    import routes.interview_prep as ip
    text = (
        "Here is the idea in a sentence.\n"
        "\n"
        "┌─ STEP 1 ─────────────┐\n"
        "│ clarify the scope    │\n"
        "└──────────────────────┘\n"
        "\n"
        "And a closing thought that should wrap like prose does.\n"
    )
    runs = ip._pdf_runs(text)
    kinds = [k for k, _ in runs]
    assert True in kinds and False in kinds, f"nothing was split: {kinds}"
    drawn = [t for k, t in runs if k]
    assert any("┌" in t for t in drawn), "the box was not treated as fixed-width"
    prose = " ".join(t for k, t in runs if not k)
    assert "idea in a sentence" in prose and "closing thought" in prose

    # A column-aligned table with no box characters still counts.
    assert ip._pdf_is_fixed_width("name        count      pct") is True
    assert ip._pdf_is_fixed_width("    indented_code = True") is True
    assert ip._pdf_is_fixed_width("-----+------+-----") is True
    # An ordinary sentence does not.
    assert ip._pdf_is_fixed_width("This is a normal line of prose text.") is False
    # A blank line inherits its neighbours rather than breaking the run.
    assert ip._pdf_is_fixed_width("   ") is None


def test_pdf_keeps_unicode_instead_of_mangling_it():
    """_latin1() turned '┌─ CLARIFY ──┐ → ≤' into '+- CLARIFY --+ -> <='.

    With a real embedded font the characters survive, which is the whole
    reason the drawn diagrams were unreadable in the export.
    """
    pytest.importorskip("fpdf", reason="fpdf2 not installed")
    import routes.interview_prep as ip

    art = "┌─────────────┐\n│ scope first │\n└─────────────┘"
    data = ip._pdf_bytes("Unicode check", "one topic", [
        {"title": "Box drawing", "cat": "test",
         "fields": [("Diagram", art)], "mono_blocks": [], "tags": []}])
    text = _pdf_text(data)
    if "+-" in text and "─" not in text:
        pytest.skip("no Unicode font on this box; core-font fallback in use")
    assert "─" in text, "box-drawing was transliterated away"
    assert "│" in text


def test_pdf_falls_back_to_core_fonts_when_no_unicode_font_exists():
    """Render must degrade, never 500. Production images do not all ship
    DejaVu, and the export is not worth a crash."""
    pytest.importorskip("fpdf", reason="fpdf2 not installed")
    import routes.interview_prep as ip

    original = ip._PDF_FONT_CANDIDATES
    try:
        ip._PDF_FONT_CANDIDATES = (("/nope/a.ttf", "/nope/b.ttf", "/nope/c.ttf"),)
        data = ip._pdf_bytes("Fallback", "sub", [
            {"title": "Em dash — and an arrow →", "cat": "test",
             "fields": [("Answer", "value ≤ limit — always")],
             "mono_blocks": [], "tags": []}])
    finally:
        ip._PDF_FONT_CANDIDATES = original
    assert data.startswith(b"%PDF"), "the fallback did not produce a PDF"
    assert len(data) > 800


def test_pdf_body_size_defaults_to_26pt_and_is_clamped(app):
    """26pt was asked for, and on A4 it yields ~40 characters per line —
    the measure a phone shows when the page is fitted to width. ?fs= is
    for reading on a laptop, and must not be able to produce a broken page."""
    import routes.interview_prep as ip
    assert ip._PDF_BODY_PT == 26
    with app.test_request_context("/ai-sde/pdf"):
        assert ip._pdf_body_pt() == 26
    with app.test_request_context("/ai-sde/pdf?fs=14"):
        assert ip._pdf_body_pt() == 14
    for bad in ("0", "999", "-5", "abc", ""):
        with app.test_request_context(f"/ai-sde/pdf?fs={bad}"):
            got = ip._pdf_body_pt()
            assert ip._PDF_MIN_PT <= got <= ip._PDF_MAX_PT, f"fs={bad} gave {got}"


# ═══════════════════════════════════════════════════
# Day Board — click through to the section, and back
# ═══════════════════════════════════════════════════

def test_day_board_rows_link_to_the_section_that_owns_them(auth_client, monkeypatch):
    """The board began look-only. Asked for: tapping a row should open the
    section it belongs to, and bring you back.

    The three destinations disagree about how a date is spelled — /day takes
    an ISO `date`, /todo takes year/month/day, /checklist takes none — so the
    URLs are built in Python rather than scattered across the template.
    """
    import routes.day_board as db
    from utils.user_tz import user_today
    today = user_today().isoformat()

    monkeypatch.setattr(db, "_events_for", lambda u, d: [
        {"id": "E1", "title": "Standup", "start_time": "09:00", "end_time": "09:30"},
        {"id": "E2", "title": "Read paper", "start_time": None, "end_time": None},
    ])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [
        {"id": "T1", "task_text": "Ship the thing", "quadrant": "Q1", "task_time": "14:00"},
    ])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [
        {"id": "C1", "title": "Vitamins", "done": False},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])

    html = auth_client.get("/day-board").get_data(as_text=True)

    # The event focus id is PREFIXED, because that is what the day view calls
    # its event rows. Sending the raw id lands on the right page with nothing
    # highlighted, which reads as a broken link.
    assert f"/day?date={today}&amp;focus=ev-E1" in html
    assert "focus=ev-E2" in html, "the untimed event is not linked"
    assert "/todo?year=" in html and "focus=T1" in html
    assert "/checklist?date=" in html and "focus=C1" in html
    # Every link carries the way home.
    assert html.count("from=board") >= 4
    # Events are anchors; list rows get a full-cell overlay instead, because
    # wrapping a flex row's children would change the height the fit pass
    # measures.
    assert '<a class="ev' in html
    assert 'class="hit"' in html


def test_day_board_links_the_checklist_to_the_day_it_is_showing(auth_client, monkeypatch):
    """This was previously left UNLINKED on any non-today board, because
    /checklist took no date and would have landed on today's list while
    appearing to open that day's. The page now takes ?date=, so the link
    carries the board's day.
    """
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [
        {"id": "C1", "title": "Vitamins", "done": False},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board?date=2020-01-01").get_data(as_text=True)
    assert "Vitamins" in html
    assert "/checklist?date=2020-01-01" in html, "the link lost the board's day"


def test_checklist_shows_another_day_read_only(auth_client):
    """Ticks are the record of a day. Showing them for another date is
    useful; letting them be CHANGED from there is not — back-filling
    "slept at 10.30" for last Tuesday is self-deception, and a checklist
    you can edit backwards stops being a record of what happened.
    """
    # Assert on the class ATTRIBUTE, not the name: the rule ships in the
    # page's stylesheet either way, so the bare string always matches.
    today = auth_client.get("/checklist").get_data(as_text=True)
    assert 'class="cl-readonly"' not in today, "today must stay editable"
    assert "Back to today" not in today

    other = auth_client.get("/checklist?date=2026-08-01").get_data(as_text=True)
    assert 'class="cl-readonly"' in other, "another day is editable"
    assert "2026-08-01" in other and "Back to today" in other

    # A bad date is a bad link, not an error the user can act on.
    bad = auth_client.get("/checklist?date=not-a-date")
    assert bad.status_code == 200
    assert 'class="cl-readonly"' not in bad.get_data(as_text=True), (
        "a bad date should fall back to today, not render a read-only page")


def test_arriving_from_the_board_offers_one_tap_back(auth_client):
    """Without a way back the board is a one-way trip, which is worse than
    not linking at all — you arrive somewhere and have to find your way home
    through the menu.

    The chip lives in _top_nav.html because all the destinations already
    include it, so one chip covers every page the board can reach, including
    any added later.
    """
    # Assert on the ELEMENT, not the class name: the rule ships in the shared
    # partial's stylesheet on every page, so the bare string always matches.
    plain = auth_client.get("/todo").get_data(as_text=True)
    assert 'class="back-board"' not in plain, (
        "the chip shows when it was not asked for")

    import re
    for path in ("/todo", "/checklist", "/day"):
        html = auth_client.get(f"{path}?from=board&bd=2026-08-22").get_data(as_text=True)
        assert 'class="back-board"' in html, f"no way back from {path}"
        # The board answers on both /day-board and /board, and url_for picks
        # whichever rule registered last — so assert the PROPERTY (it goes to
        # the board, carrying the date you came from) rather than a spelling.
        href = re.search(r'class="back-board"\s+href="([^"]+)"', html)
        if href is None:
            href = re.search(r'href="([^"]+)"[^>]*class="back-board"', html)
        assert href, f"{path} renders the chip without an href"
        target = href.group(1)
        assert "board" in target, f"{path} chip does not point at the board: {target}"
        assert "date=2026-08-22" in target, (
            f"{path} loses the board's date on the way back: {target}")


def test_focus_landing_survives_a_list_that_renders_later():
    """Most of these pages build their lists in JavaScript after their own
    fetch, so the row is not in the DOM at DOMContentLoaded. The landing
    retries via MutationObserver, and gives up rather than observing forever.

    A missing id is a NORMAL outcome — the task was completed and filtered
    out, or the item was deleted — so it must stay silent instead of
    reporting a failure the user can already see.
    """
    js = open("static/js/global.js", encoding="utf-8").read()
    block = js.split("ARRIVING FROM THE DAY BOARD")[1]
    assert "MutationObserver" in block, "gives up before a JS-rendered list appears"
    assert "DEADLINE" in block and "disconnect()" in block, "observes forever"
    assert "CSS.escape" in block, "the id comes from the URL and is not escaped"
    # Both hooks: data-focus-id is explicit, data-id is what the existing
    # task and checklist markup already carries.
    assert "data-focus-id" in block and "data-id" in block
    # Esc returns to the board, and must not eat an editor's escape.
    assert "Escape" in block and "TEXTAREA" in block


def test_day_page_rows_carry_a_focus_id(auth_client):
    """The landing needs something to find. /todo and /checklist already
    emit data-id; the day view emitted nothing."""
    html = open("templates/day.html", encoding="utf-8").read()
    assert html.count('data-focus-id="{{ i.id }}"') == 3, (
        "not every day-view item block is addressable")


# ═══════════════════════════════════════════════════
# Sign-in history — IST, location, failed attempts
# ═══════════════════════════════════════════════════

def test_login_history_shows_utc_rows_in_the_users_own_timezone(auth_client, monkeypatch):
    """Asked for: sign-in history "in IST Time along with location".

    Rows are stored in UTC because that is the only representation that
    survives a timezone change; the conversion happens in the view, once.
    09:15 UTC is 14:45 IST, and that arithmetic is the whole point of the
    page — a history showing UTC would be read wrong every single time.
    """
    import routes.settings as st
    rows = [
        {"at": "2026-08-22T09:15:00+00:00", "ip": "49.207.1.2",
         "user_agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit Chrome/120 Mobile Safari",
         "city": "Chennai", "region": "Tamil Nadu", "country": "India",
         "location_status": "ok", "outcome": "success"},
        {"at": "2026-08-21T18:40:00+00:00", "ip": "192.168.1.5",
         "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/605",
         "location_status": "private", "outcome": "failed"},
    ]
    monkeypatch.setattr(st, "get", lambda *a, **kw: rows)
    html = auth_client.get("/settings/login-history").get_data(as_text=True)

    assert "02:45 PM" in html, "UTC was not converted to the user's zone"
    assert "IST" in html, "the page does not say which zone it is showing"
    assert "Chennai, Tamil Nadu, India" in html
    # location_status distinguishes three states an empty cell would flatten
    # into one that looks like a bug.
    assert "On this network" in html
    assert "Chrome on Android" in html and "Safari on Mac" in html
    # A history of successes alone cannot show someone trying to get in.
    assert "failed attempt" in html


def test_login_history_names_the_migration_instead_of_500ing(auth_client, monkeypatch):
    """An unrun migration is a setup step, not an error. The page says which
    file closes it — and says the earlier sign-ins cannot be backfilled,
    because they were never stored."""
    import routes.settings as st

    def missing(*a, **kw):
        raise Exception('relation "login_events" does not exist')

    monkeypatch.setattr(st, "get", missing)
    r = auth_client.get("/settings/login-history")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "MIGRATION_LOGIN_HISTORY.sql" in html
    assert "backfilled" in html


def test_login_geolocation_is_honest_about_what_it_cannot_know():
    """`location_status` carries WHY a row has no city, so the page can say
    "on this network" rather than showing a blank that reads as a bug.

    A private address is detected rather than sent to the geo provider: the
    lookup would fail anyway, and the answer is more useful.
    """
    from services import login_history_service as svc
    assert svc.locate("127.0.0.1")["location_status"] == "private"
    assert svc.locate("192.168.1.5")["location_status"] == "private"
    assert svc.locate("10.0.0.9")["location_status"] == "private"
    assert svc.locate(None)["location_status"] == "unknown"
    assert svc.locate("not-an-ip")["location_status"] in ("failed", "unknown")


def test_login_history_prefers_the_forwarded_address(monkeypatch):
    """Behind a proxy, remote_addr is the PROXY. The real client is the
    left-most entry of X-Forwarded-For — trusted for "roughly where", never
    for anything security-critical, because the header is client-settable."""
    from services import login_history_service as svc

    class Req:
        def __init__(self, headers, remote):
            self.headers = headers
            self.remote_addr = remote

    assert svc.client_ip(Req({"X-Forwarded-For": "203.0.113.9, 70.41.3.18"},
                             "10.0.0.1")) == "203.0.113.9"
    assert svc.client_ip(Req({}, "203.0.113.9")) == "203.0.113.9"
    # Nothing available must be None, not a placeholder that later looks
    # like real data.
    assert svc.client_ip(Req({}, "")) is None


def test_a_failed_sign_in_is_recorded_against_the_targeted_account():
    """Half the point of the page is showing attempts that were not you.

    Nothing is recorded for an unknown email — there is no account to show
    it to, and writing one would let a stranger fill the table.
    """
    import inspect
    import routes.auth as auth
    src = inspect.getsource(auth.login)
    assert 'outcome="failed"' in src, "failed attempts are not recorded"
    assert "if user:" in src, "a failure for an unknown email would be stored"


# ═══════════════════════════════════════════════════
# Quick Bucket — bulk select into one calendar slot
# ═══════════════════════════════════════════════════

def _qb_stub(monkeypatch, rows):
    import routes.quick_bucket as qb
    sent = {"posted": [], "updated": []}
    monkeypatch.setattr(qb, "get",
                        lambda t, params=None, **k: rows if t == "quick_bucket" else [])
    monkeypatch.setattr(qb, "post",
                        lambda t, p, **k: sent["posted"].append((t, p)) or [{"id": "EV1", **p}])
    monkeypatch.setattr(qb, "update",
                        lambda t, params=None, json=None, **k: sent["updated"].append((t, json)))
    return sent


def test_bulk_selection_becomes_one_slot_with_the_items_in_the_description(auth_client, monkeypatch):
    """Asked for: bulk select bucket items, move them to a calendar slot,
    and have them appear in the description.

    ONE EVENT, NOT ONE PER ITEM. Five tasks become five lines in one slot,
    which is what "move them to a slot" means and the only version that
    stays readable on a week view.
    """
    sent = _qb_stub(monkeypatch, [{"id": "B", "text": "Call the bank"},
                                  {"id": "A", "text": "Book flights"}])
    r = auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A", "B"], "date": "2026-08-25", "start": "15:00", "duration": 45})
    assert r.status_code == 200, r.get_data(as_text=True)

    assert len(sent["posted"]) == 1, "one slot, not one event per item"
    table, ev = sent["posted"][0]
    assert table == "daily_events"
    assert ev["end_time"] == "15:45"
    assert "From Quick Bucket:" in ev["description"]
    assert "• Book flights" in ev["description"] and "• Call the bank" in ev["description"]
    # The order the user selected, not whatever the database returned.
    assert ev["description"].index("Book flights") < ev["description"].index("Call the bank")


def test_a_paragraph_is_read_into_candidates_and_nothing_is_written(auth_client, monkeypatch):
    """Asked 2026-08-30: "Is there a way i can type something like a
    paragraph. Code can decipher and create tasks on quickbucket."

    The preview endpoint must be READ-ONLY. A parse is a guess, and a
    guess that writes rows before you have seen it is how a bucket fills
    up with half-sentences nobody can undo.
    """
    sent = _qb_stub(monkeypatch, [])
    r = auth_client.post("/api/quick-bucket/interpret", json={
        "text": "I need to call the plumber tomorrow at 9am and pay the "
                "electricity bill before Friday. Book the flight, urgent.",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    titles = " ".join(i["text"].lower() for i in body["items"])
    assert "plumber" in titles and "electricity" in titles and "flight" in titles
    assert body["used_ai"] is False, "the model must be opt-in per request"
    assert sent["posted"] == [] and sent["updated"] == [], \
        "the preview wrote to the database"
    # Every candidate has to be able to justify itself on screen.
    for it in body["items"]:
        assert it["why"], it


def test_the_reader_is_actually_wired_to_the_page(auth_client):
    """Eight source-string guards once passed for a week while the time
    announcer was mute, so this checks the two halves AGREE rather than
    that either contains a word: every #qb-read-* the script reaches for
    has to exist in the template, and vice versa."""
    import re as _re
    html = auth_client.get("/quick-bucket").get_data(as_text=True)
    js = open("static/js/quick_bucket.js", encoding="utf-8").read()
    in_page = set(_re.findall(r'id="(qb-read[^"]*)"', html))
    in_js = set(_re.findall(r'\$\("#(qb-read[^"]*)"\)', js))
    assert in_js, "the paragraph reader is gone from quick_bucket.js"
    assert in_js - in_page == set(), f"script reaches for missing ids: {in_js - in_page}"
    assert in_page - in_js == set(), f"page has dead reader markup: {in_page - in_js}"
    assert "/api/quick-bucket/interpret" in js


def test_an_empty_dump_is_a_400_not_an_empty_bucket(auth_client, monkeypatch):
    _qb_stub(monkeypatch, [])
    assert auth_client.post("/api/quick-bucket/interpret",
                            json={"text": "   "}).status_code == 400


def test_a_confirmed_candidate_keeps_the_time_it_was_shown_with(auth_client, monkeypatch):
    """The preview resolved the time and the user saw it. Re-parsing the
    title on the way in would be a second opinion about the same
    sentence, and the one on screen would lose."""
    sent = _qb_stub(monkeypatch, [])
    r = auth_client.post("/api/quick-bucket", json={
        "text": "Drop Shreya at school",
        "time_bucket": "at",
        "due_at": "2026-09-01T02:30:00+00:00",
        "planned_minutes": 30,
        "backlog_due": "2026-09-04",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    row = [p for t, p in sent["posted"] if t == "quick_bucket"][0]
    assert row["due_at"].startswith("2026-09-01T02:30")
    assert row["time_bucket"] == "at"
    assert row["planned_minutes"] == 30
    assert row["backlog_due"] == "2026-09-04"


def test_an_unparseable_due_at_is_refused_not_stored(auth_client, monkeypatch):
    """A junk timestamp in the column renders as an alarm at an unknown
    time, which is worse than no alarm at all."""
    sent = _qb_stub(monkeypatch, [])
    auth_client.post("/api/quick-bucket",
                     json={"text": "Pay rent", "due_at": "next tuesday-ish"})
    row = [p for t, p in sent["posted"] if t == "quick_bucket"][0]
    assert row["due_at"] is None
    assert row["time_bucket"] == "now"


def test_scheduling_neither_deletes_the_items_nor_marks_them_done(auth_client, monkeypatch):
    """Deleting loses them; marking them done is a lie, because they are
    scheduled rather than finished. They are LINKED to the slot instead,
    which is reversible and lets the bucket show where a row went."""
    sent = _qb_stub(monkeypatch, [{"id": "A", "text": "Book flights"}])
    auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A"], "date": "2026-08-25", "start": "09:00"})
    link = [j for t, j in sent["updated"] if t == "quick_bucket"][0]
    assert link["scheduled_event_id"] == "EV1"
    assert link["scheduled_for"] == "2026-08-25"
    assert "is_done" not in link and "is_deleted" not in link


def test_one_item_names_the_slot_after_itself(auth_client, monkeypatch):
    """A slot holding five tasks cannot be titled with all five — a calendar
    cell has no room. One item keeps its own name; several become a count."""
    sent = _qb_stub(monkeypatch, [{"id": "A", "text": "Book flights"}])
    auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A"], "date": "2026-08-25", "start": "09:00"})
    assert sent["posted"][0][1]["title"] == "Book flights"

    sent = _qb_stub(monkeypatch, [{"id": "A", "text": "a"}, {"id": "B", "text": "b"}])
    auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A", "B"], "date": "2026-08-25", "start": "09:00"})
    assert sent["posted"][0][1]["title"] == "2 bucket tasks"


def test_a_late_slot_does_not_wrap_past_midnight(auth_client, monkeypatch):
    """An event that wrapped would render at the top of the day and look
    like it happens in the morning."""
    sent = _qb_stub(monkeypatch, [{"id": "A", "text": "x"}])
    auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A"], "date": "2026-08-25", "start": "23:40", "duration": 120})
    assert sent["posted"][0][1]["end_time"] == "23:59"


def test_scheduling_into_an_existing_slot_rewrites_only_its_own_block(auth_client, monkeypatch):
    """A second bulk-move into the same hour should add to that slot, not
    duplicate the list — and must not eat a note the user typed above it."""
    import routes.quick_bucket as qb
    existing = {"id": "EV1", "description": "Bring the folder.\n\nFrom Quick Bucket:\n• old one"}
    sent = {"updated": []}
    monkeypatch.setattr(qb, "get", lambda t, params=None, **k:
                        [{"id": "A", "text": "Book flights"}] if t == "quick_bucket" else [existing])
    monkeypatch.setattr(qb, "post", lambda *a, **k: [{}])
    monkeypatch.setattr(qb, "update",
                        lambda t, params=None, json=None, **k: sent["updated"].append((t, json)))
    auth_client.post("/api/quick-bucket/schedule", json={
        "ids": ["A"], "date": "2026-08-25", "start": "09:00", "event_id": "EV1"})
    desc = [j for t, j in sent["updated"] if t == "daily_events"][0]["description"]
    assert desc.startswith("Bring the folder."), "the user's own note was destroyed"
    assert desc.count("From Quick Bucket:") == 1, "the block was duplicated"
    assert "old one" not in desc, "the block was appended instead of rewritten"
    assert "• Book flights" in desc


def test_schedule_rejects_input_it_cannot_honour(auth_client, monkeypatch):
    import routes.quick_bucket as qb
    monkeypatch.setattr(qb, "get", lambda *a, **k: [])
    for body in ({"ids": [], "date": "2026-08-25", "start": "09:00"},
                 {"ids": ["A"], "date": "nope", "start": "09:00"},
                 {"ids": ["A"], "date": "2026-08-25", "start": "9am"}):
        assert auth_client.post("/api/quick-bucket/schedule", json=body).status_code == 400


def test_quick_bucket_list_degrades_when_the_migration_is_not_run():
    """A column that has not been migrated makes the WHOLE query 400 and
    renders the page empty — which has happened here before. Each rung of
    the select ladder drops the newest fields."""
    import inspect
    import routes.quick_bucket as qb
    src = inspect.getsource(qb.list_items)
    assert "select_scheduled" in src
    assert "for sel in (select_scheduled, select_effort" in src, (
        "the new columns are not the first rung, or the ladder was not extended")


# ═══════════════════════════════════════════════════
# Prep banks — bulk-add topics as one study block
# ═══════════════════════════════════════════════════

def _bulk_prep_stub(monkeypatch):
    import routes.interview_prep as ip
    posted = []
    monkeypatch.setattr(ip, "post",
                        lambda t, p, **k: posted.append((t, p)) or [{"id": "EV1", "task_id": "T1", **p}])
    monkeypatch.setattr(ip, "update", lambda *a, **k: None)
    monkeypatch.setattr(ip, "get", lambda *a, **k: [])
    monkeypatch.setattr(ip, "_get_optional", lambda *a, **k: [])
    monkeypatch.setattr(ip, "_ensure_prep_project", lambda u, b: "PROJ")
    return posted


def test_bulk_prep_makes_one_block_with_the_topics_in_the_description(auth_client, monkeypatch):
    """Asked for: bulk-add topics from the prep pages to the calendar.

    ONE calendar block, not one event per topic — six topics on a Saturday
    morning is one session, and six stacked entries make the day
    unreadable. But the PROJECT still gets one task per topic, because that
    is where progress is tracked and a single "study block" task cannot be
    half done.
    """
    import ai_sde_bank as bank
    posted = _bulk_prep_stub(monkeypatch)
    picked = bank.ENTRIES[:3]
    titles = [e["title"] for e in picked]

    r = auth_client.post("/api/prep/schedule-bulk", json={
        "bank": "ai_sde", "plan_date": "2026-08-29", "start_time": "09:00",
        "topics": [{"title": t} for t in titles]})
    assert r.status_code == 200, r.get_data(as_text=True)

    events = [p for t, p in posted if t == "daily_events"]
    tasks = [p for t, p in posted if t == "project_tasks"]
    assert len(events) == 1, "one block, not one event per topic"
    assert len(tasks) == 3, "the project must still get one task per topic"
    for title in titles:
        assert "• " + title in events[0]["description"]


def test_bulk_prep_duration_defaults_to_the_topics_own_prep_time(auth_client, monkeypatch):
    """The bank already knows how long each topic takes. Making the user
    add that up by hand would be asking them to re-derive a number that is
    on the page in front of them."""
    import ai_sde_bank as bank
    posted = _bulk_prep_stub(monkeypatch)
    picked = bank.ENTRIES[:3]
    total = sum(e["prep_minutes"] for e in picked)

    r = auth_client.post("/api/prep/schedule-bulk", json={
        "bank": "ai_sde", "plan_date": "2026-08-29", "start_time": "09:00",
        "topics": [{"title": e["title"]} for e in picked]})
    j = r.get_json()
    assert j["total_minutes"] == total
    # 09:00 + the summed prep time, not a fixed guess.
    end_h, end_m = divmod(9 * 60 + total, 60)
    assert j["end_time"] == f"{end_h:02d}:{end_m:02d}"


def test_bulk_prep_collapses_repeats_and_reports_what_it_could_not_find(auth_client, monkeypatch):
    """A title that resolves to nothing must be REPORTED, not silently
    dropped — otherwise a stale tab schedules four of five topics and says
    it did all five."""
    import ai_sde_bank as bank
    _bulk_prep_stub(monkeypatch)
    t0 = bank.ENTRIES[0]["title"]
    r = auth_client.post("/api/prep/schedule-bulk", json={
        "bank": "ai_sde", "plan_date": "2026-08-29",
        "topics": [{"title": t0}, {"title": t0}, {"title": "no such topic"}]})
    j = r.get_json()
    assert j["count"] == 1, "the same topic picked twice must collapse"
    assert j["unknown"] == ["no such topic"]


def test_bulk_prep_rejects_input_it_cannot_honour(auth_client):
    for body in ({"bank": "nope", "plan_date": "2026-08-29", "topics": [{"title": "x"}]},
                 {"bank": "ai_sde", "plan_date": "bad", "topics": [{"title": "x"}]},
                 {"bank": "ai_sde", "plan_date": "2026-08-29", "topics": []}):
        assert auth_client.post("/api/prep/schedule-bulk", json=body).status_code == 400


def test_every_prep_bank_can_be_bulk_scheduled(auth_client, monkeypatch):
    """All four banks, because the ask named AI SDE, Java and SQL — and
    leaving the behavioural one out would be an odd gap."""
    import routes.interview_prep as ip
    for bank_key in ("ai_sde", "java", "sql", "behavioral"):
        posted = _bulk_prep_stub(monkeypatch)
        source, field, _prefix = ip._BANK_SOURCES[bank_key]
        first = source()[0][field]
        r = auth_client.post("/api/prep/schedule-bulk", json={
            "bank": bank_key, "plan_date": "2026-08-29",
            "topics": [{"title": first}]})
        assert r.status_code == 200, f"{bank_key}: {r.get_data(as_text=True)}"
        assert [p for t, p in posted if t == "daily_events"], f"{bank_key} made no block"


def test_bulk_select_needs_no_per_page_markup():
    """The prep pages disagree about their card structure — the title is
    .q-text on one and .t on another. Selection keys off the Plan button's
    own data attributes, which every schedulable card already carries, so
    all four pages get this without a template change.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    block = js.split("BULK: several topics into ONE study block")[1]
    assert "[data-prep-plan]" in block, "bulk reads page-specific markup"
    assert "mountBulk(root)" in js, "attach() does not wire bulk"
    # The pages re-render their list on filter changes, which would wipe
    # the injected checkboxes.
    assert "MutationObserver" in js and "paintBoxes()" in js


# ═══════════════════════════════════════════════════
# Time announcer — spoken on the quarter hour
# ═══════════════════════════════════════════════════

def test_time_announcer_is_loaded_on_every_page(auth_client):
    """Asked for: announce the time every 15 minutes, with pause and stop.

    It lives in the shared nav because it is an AMBIENT setting: it has to
    survive moving between pages, and its control belongs somewhere every
    page can reach.
    """
    assert "time-announcer.js" in open("templates/_top_nav.html", encoding="utf-8").read()
    for path in ("/todo", "/checklist", "/ai-sde"):
        assert "time-announcer.js" in auth_client.get(path).get_data(as_text=True), path


def test_time_announcer_never_reads_out_a_time_that_has_passed():
    """A laptop that slept through 14:15 and woke at 14:41 must not then
    say "quarter past two". That is worse than silence, because you would
    believe it. Late announcements are SKIPPED, never queued.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "GRACE_MS" in js, "no bound on how late an announcement may be"
    # The lateness rule itself is exercised for real in
    # tests/js/time_announcer.test.js ("2m late is skipped") rather than
    # asserted as a source string — the previous version of this test pinned
    # one exact LINE, which made moving the check into dueSlot() look like a
    # regression while proving nothing about the behaviour either way.
    assert "lateBy" in js and "dueSlot" in js
    # Aligned to the clock, not to when you pressed start — otherwise 3:07
    # and 3:22 would be "every fifteen minutes" and useless.
    assert "Math.floor(mins / state.every) * state.every" in js
    # Two open tabs must not both announce. There are now TWO dedupe paths —
    # the repeating interval keyed on its slot, and each named announcement
    # keyed on (id, date, time) — and both re-read from storage first so
    # whichever tab gets there wins.
    # Both paths re-read from storage before speaking. Asserted on the
    # RE-READ rather than on an exact comparison expression, because that
    # expression has now moved twice (once for named announcements, once
    # again for per-slot keys) and each time this guard failed for a change
    # that was correct. What matters is that `fresh` is consulted.
    assert "var fresh = load();" in js, "no re-read; sibling tabs will double-announce"
    assert "fresh.lastSlot" in js, "the interval does not check for a sibling tab"
    assert "fresh.said[" in js, "scheduled items do not check for a sibling tab"
    # A queued backlog read out in sequence is the failure mode people
    # remember, so anything pending is cancelled first — but ONLY when
    # something really is in flight. cancel() followed by speak() in the same
    # task is a Chrome bug that swallows the utterance, and doing it
    # unconditionally is why announcements went mute.
    assert "speechSynthesis.cancel()" in js
    assert "synth.speaking || synth.pending" in js, \
        "cancel() is unconditional again — Chrome will swallow the speech"


def test_time_announcer_offers_pause_and_stop_separately():
    """The ask named both. They differ: pause keeps the interval and the
    intent, stop clears the slot so restarting announces cleanly."""
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert 'data-ta-mode="paused"' in js and 'data-ta-mode="off"' in js
    assert "pause: function" in js and "stop:  function" in js
    assert "state.lastSlot = null" in js, "stop does not reset the slot"


# ═══════════════════════════════════════════════════
# Checklist — yesterday's misses, and the history browser
# ═══════════════════════════════════════════════════

def test_schedule_logic_is_shared_with_the_thing_that_reminds_you():
    """The Day Board had its own copy with NO branch for `weekdays` or
    `weekends`, so both fell through to "show it" and those items appeared
    on the board every day of the week. Measured against live data: three
    weekday items and one weekend item, on all seven days.

    Anything saying "you missed this" has to agree with the thing that
    reminded you, so the reminder's logic is now the only copy.
    """
    from datetime import date
    from services.checklist_schedule import applies_on, is_due

    sat, sun, mon = date(2026, 8, 22), date(2026, 8, 23), date(2026, 8, 24)
    assert [applies_on("weekdays", "", d) for d in (sat, sun, mon)] == [False, False, True]
    assert [applies_on("weekends", "", d) for d in (sat, sun, mon)] == [True, True, False]
    # `custom` stores Sun=0..Sat=6 as NUMBERS, not three-letter names — the
    # Day Board compared them as names and so matched nothing.
    assert applies_on("custom", "6", sat) is True
    assert applies_on("custom", "6", mon) is False
    assert applies_on("once", "2026-08-22", sat) is True
    assert applies_on("monthly_dom", "22", sat) is True

    # An item cannot be due before it existed, or a checklist started last
    # week shows months of "missed" behind it.
    assert is_due({"schedule": "daily", "created_at": "2026-08-30T00:00:00Z"}, sat) is False
    # recurrence_end stops it without deleting the history.
    assert is_due({"schedule": "daily", "recurrence_end": "2026-08-01"}, sat) is False
    assert is_due({"schedule": "daily", "is_deleted": True}, sat) is False


def test_push_scheduler_behaviour_is_unchanged_by_the_extraction():
    """The logic moved out of push_scheduler, which decides whether a
    reminder actually fires. Moving it must not change a single answer."""
    from datetime import date, timedelta
    from services.push_scheduler import _schedule_applies_today as sched
    from services.checklist_schedule import applies_on

    cases = [("daily", ""), ("weekdays", ""), ("weekends", ""), ("custom", "0,6"),
             ("custom", "1,2,3,4,5"), ("monthly_dow", "1:1"), ("monthly_dow", "-1:6"),
             ("monthly_dom", "1"), ("monthly_dom", "-1"), ("once", "2026-03-15"),
             ("", ""), ("bogus", "")]
    d, checked = date(2026, 1, 1), 0
    while d < date(2027, 1, 1):
        for s, days in cases:
            assert sched(s, days, d.weekday(), d) == applies_on(s, days, d), (s, days, d)
            checked += 1
        d += timedelta(days=1)
    assert checked > 4000


def test_a_legacy_whole_item_tick_still_counts_as_done():
    """Ticks recorded before an item gained reminder times are stored with
    a NULL time. Requiring today's reminder rows to be ticked would mark
    those days MISSED for items the user demonstrably ticked.

    Real case from this database: every tick on 2026-04-26 is NULL-keyed
    and all seven of those items were given reminder times later, so the
    strict rule reported 0 of 10 done on a day with seven ticks on it.
    Configuring a reminder in August cannot un-tick April.
    """
    from services.checklist_history import _is_done
    item = {"id": "i1"}
    times = {"i1": ["06:00:00", "22:00:00"]}
    day = "2026-04-26"

    legacy = {("i1", day): {None}}
    assert _is_done(item, day, legacy, times) is True, "a whole-item tick was ignored"

    partial = {("i1", day): {"06:00:00"}}
    assert _is_done(item, day, partial, times) is False, "one of two reminders is not done"

    both = {("i1", day): {"06:00:00", "22:00:00"}}
    assert _is_done(item, day, both, times) is True
    assert _is_done(item, day, {}, times) is False


def test_checklist_shows_yesterdays_misses(auth_client, monkeypatch):
    """The ticks were always stored per date and never read for any day but
    today, so the miss was invisible — and a loop with no feedback is how a
    checklist quietly stops being used."""
    import routes.checklist as cl

    monkeypatch.setattr(cl.checklist_history, "yesterday_summary",
                        lambda u, t: {"date": "2026-08-21", "label": "Fri 21 Aug",
                                      "due": 16, "done": 9, "missed": 7,
                                      "names": ["Drink water", "Ram"]})
    html = auth_client.get("/checklist").get_data(as_text=True)
    assert "Yesterday: missed 7 of 16." in html
    assert "Drink water" in html

    monkeypatch.setattr(cl.checklist_history, "yesterday_summary",
                        lambda u, t: {"date": "x", "label": "y", "due": 9,
                                      "done": 9, "missed": 0, "names": []})
    assert "Yesterday: all 9 done." in auth_client.get("/checklist").get_data(as_text=True)

    # Nothing due yesterday means no line: "0 of 0" is not a result.
    monkeypatch.setattr(cl.checklist_history, "yesterday_summary", lambda u, t: None)
    body = auth_client.get("/checklist").get_data(as_text=True).split("</style>")[-1]
    assert "cl-yday" not in body

    # And never on a historical view — it would be about a day two before
    # the one being read.
    monkeypatch.setattr(cl.checklist_history, "yesterday_summary",
                        lambda u, t: {"date": "x", "label": "y", "due": 9,
                                      "done": 1, "missed": 8, "names": ["a"]})
    assert "Yesterday: missed" not in auth_client.get(
        "/checklist?date=2026-08-01").get_data(as_text=True)


def test_checklist_history_page(auth_client, monkeypatch):
    """A day counts only what was DUE on it, so a weekend with no weekday
    items is not a failure — the empty cell says "nothing due", not 0%."""
    import routes.checklist as cl
    fake = {
        "start": "2026-08-09", "end": "2026-08-22", "window": 14,
        "days": [
            {"date": "2026-08-22", "label": "Sat 22 Aug", "due": 14, "done": 14,
             "missed": 0, "pct": 100, "missed_names": []},
            {"date": "2026-08-21", "label": "Fri 21 Aug", "due": 16, "done": 9,
             "missed": 7, "pct": 56, "missed_names": ["Drink water"]},
            {"date": "2026-08-20", "label": "Thu 20 Aug", "due": 0, "done": 0,
             "missed": 0, "pct": None, "missed_names": []},
            {"date": "2026-08-19", "label": "Wed 19 Aug", "due": 16, "done": 1,
             "missed": 15, "pct": 6, "missed_names": ["Ram"]},
        ],
        "items": [{"id": "i1", "name": "Drink water", "due": 14, "done": 2}],
        "total_due": 46, "total_done": 24, "pct": 52, "active_days": 3, "streak": 1,
    }
    monkeypatch.setattr(cl.checklist_history, "load", lambda u, e, d, **kw: fake)
    html = auth_client.get("/checklist/history?days=14").get_data(as_text=True)
    assert "52%" in html and "24 of 46 ticked" in html
    assert "Drink water" in html and "2/14" in html
    # Every cell links to that day's read-only checklist.
    assert "/checklist?date=2026-08-22" in html
    # The four bands plus "nothing due" are all distinguishable.
    for cls in ("ch-cell full", "ch-cell some", "ch-cell bad", "ch-cell none"):
        assert cls in html, cls


def test_history_window_is_bounded(auth_client, monkeypatch):
    """An unbounded ?days= is a way to ask the database for everything."""
    import routes.checklist as cl
    seen = {}
    monkeypatch.setattr(cl.checklist_history, "load",
                        lambda u, e, d, **kw: seen.setdefault("days", d) or
                        {"days": [], "items": [], "total_due": 0, "total_done": 0,
                         "pct": None, "active_days": 0, "streak": 0,
                         "start": "", "end": "", "window": d})
    auth_client.get("/checklist/history?days=99999")
    assert seen["days"] <= cl.checklist_history.MAX_DAYS
    seen.clear()
    auth_client.get("/checklist/history?days=nonsense")
    assert seen["days"] == 30


def test_announcer_survives_a_throttled_background_timer():
    """"Will it work when the window is minimised?"

    A hidden tab has its timers clamped — Chrome to once per MINUTE after
    about five minutes. Simulated against this logic: a 60s tick still
    catches every one of the 96 quarter-hours in a day, from any starting
    phase, because the grace window is 90s. At a 120s clamp it would start
    missing half, which is why the window is not tightened.
    """
    import re
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    grace_ms = int(re.search(r"GRACE_MS\s*=\s*(\d+)\s*\*\s*1000", js).group(1)) * 1000
    tick_ms = int(re.search(r"TICK_MS\s*=\s*(\d+)\s*\*\s*1000", js).group(1)) * 1000
    every = 15

    def announced(tick, phase):
        seen = set()
        t = phase
        while t < 24 * 3600 * 1000:
            mins, secs = divmod(t // 1000, 60)
            late = (mins % every) * 60000 + secs * 1000
            if late <= grace_ms:
                seen.add((mins // every) * every)
            t += tick
        return len(seen)

    expected = 24 * 60 // every
    for clamp in (tick_ms, 60_000):
        worst = min(announced(clamp, p) for p in range(0, clamp, 1000))
        assert worst == expected, (
            f"a {clamp // 1000}s tick misses {expected - worst} of {expected} "
            "quarter-hours in the worst phase")


def test_announcer_keepalive_is_opt_in_and_not_actually_silent():
    """Chrome may FREEZE a background tab, and a frozen page runs no timers
    at all — the difference between "late" and "stopped". Tabs playing
    audio are exempt, so the keep-alive holds an audio node open.

    OPT-IN, because it costs battery and puts an "audio playing" mark on
    the tab; someone using this at a visible desk should not pay for that.
    And the gain is NOT zero: a muted graph is exactly what a browser is
    entitled to optimise away, and an optimised-away graph stops counting
    as playback, which would silently undo the whole point.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "keepaliveOn" in js and "data-ta-keep" in js
    # It now defaults ON, asked for on 2026-08-23 because browser storage
    # eviction was silently turning it off. What still matters — and is
    # what this test was really protecting — is that it only HOLDS audio
    # while announcements are running, so the default costs an idle device
    # nothing. That is asserted below.
    assert "keepalive: true" in js
    # Only held while announcements are actually due to happen.
    body = js.split("function applyKeepalive()")[1].split("}")[0]
    assert 'state.mode === "on"' in body and "state.keepalive" in body
    # The limits are stated to the USER, not buried in a source comment:
    # what it costs, and that a fully closed app cannot be rescued.
    # Case-insensitive: the copy emphasises words in caps, and this
    # assertion is about the CLAIM being present, not its typography.
    assert "battery" in js.lower() and "fully closed" in js.lower()
    # ...and the panel must now also say what DOES survive that, because
    # "nothing works once closed" stopped being true when announcements
    # started firing as push notifications. Copy that is out of date with
    # the feature is worse than no copy.
    # The panel must not imply a closed app hears nothing at all — the
    # notifications still arrive, and saying otherwise sends the reader
    # hunting for a workaround to a problem they do not have. The wording
    # is now one line rather than three paragraphs (asked for: the panel
    # was "cluttered"), so this asserts the CLAIM rather than a sentence.
    assert "notifications still arrive" in js, \
        "the panel implies a closed app hears nothing at all"
    assert "best-effort" in js.lower(), (
        "the locked-phone case is presented as certain when it is not")


def test_announcer_recommends_the_keepalive_to_installed_app_users():
    """Asked: "I have the PWA, can it not announce even when minimised?"

    Installing changes nothing about what the platform ALLOWS — an
    installed app is still a document, and a minimised window is still
    hidden and freezable. What it changes is the advice: someone who
    installed the app is far more likely to leave it minimised and expect
    it to keep working, which is exactly what the keep-alive is for. So the
    recommendation is surfaced there instead of buried in a paragraph.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "display-mode: standalone" in js
    # iOS reports installed-ness its own way.
    assert "navigator.standalone" in js
    assert "ta-tip" in js
    # Shown only when it would actually help: installed AND not already on.
    assert "isInstalled() && !state.keepalive" in js


def test_periodic_background_sync_cannot_drive_a_15_minute_announcement():
    """The obvious "surely the service worker can do it" answer, closed off
    in the codebase itself: the app already registers periodicSync, at a
    TWELVE HOUR interval, and the service worker's own comment records that
    the browser fires it "usually closer to once per day".

    Nowhere near 15 minutes — and a service worker cannot speak anyway,
    since speechSynthesis is a window API with no worker equivalent.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    pwa = open("static/js/pwa.js", encoding="utf-8").read()
    assert "periodicsync" in sw
    assert "12h interval" in sw or "12 * 60" in pwa or "43200" in pwa, (
        "the periodic sync interval is no longer documented as coarse")
    # And nothing should ever try to speak from the worker.
    assert "speechSynthesis" not in sw, (
        "a service worker has no speechSynthesis — this cannot work")


def test_announcer_keepalive_uses_real_media_not_web_audio():
    """Asked: "voice even when the phone is locked."

    On a locked phone the page is suspended and nothing in an ordinary web
    page survives it. The single exception is MEDIA: a page holding an
    active media session keeps running with the screen off, which is how a
    music PWA keeps playing in your pocket. A Web Audio oscillator — what
    the first version used — is not treated as playback and does not
    qualify, so the keep-alive is a real looping <audio> element.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert 'createElement("audio")' in js, "still using Web Audio, which will not survive lock"
    assert "audio-keepalive.wav" in js
    assert "el.loop = true" in js
    # A MUTED element holds no audio focus, so the OS keeps nothing alive.
    # Check the ASSIGNMENT, not the word — the comment explaining this says
    # "muted" and an earlier version of this test matched its own docs.
    assert "el.volume" in js
    assert "el.muted = true" not in js and "muted: true" not in js
    # The lock screen entry must be labelled, and its buttons must work —
    # a control that looks like it stops something has to stop it.
    assert "mediaSession" in js and "MediaMetadata" in js
    assert 'setActionHandler("pause"' in js and 'setActionHandler("stop"' in js
    import os
    assert os.path.exists("static/audio-keepalive.wav"), "the track is missing"
    # SIZE BOUND RAISED FROM 20KB. The track had to grow from 1s to 15s so
    # Chrome would surface lock-screen controls for it (it treats anything
    # under ~5s as a sound effect, not playback), and 8kHz mono 8-bit for 15s
    # is ~120KB. Fetched once and cached by the service worker.
    assert os.path.getsize("static/audio-keepalive.wav") < 200000
    # Precached: the moment it is needed is exactly when the network is
    # least likely to be there.
    assert "audio-keepalive.wav" in open("static/service-worker.js", encoding="utf-8").read()


def test_push_subscription_self_heals_when_the_server_deactivated_it():
    """A silent, invisible failure, found in live data: six push
    subscriptions for the same Android phone, EVERY one is_active=false,
    the newest already a month old.

    The cause is a one-way drift. The server flips is_active=false the
    moment a send returns 404/410, and never tells the browser. The UI only
    checked whether the BROWSER still held a subscription, so it reported
    "notifications are on" while nothing would ever be delivered — which is
    the likeliest reason nothing on that checklist had been ticked in four
    months.

    Re-registering is idempotent (the endpoint upserts and sets
    is_active=true), so doing it on load repairs the drift silently.
    """
    js = open("static/js/push.js", encoding="utf-8").read()
    heal = js.split("SELF-HEAL")[1].split("enableBtn")[0]
    assert "/api/push/subscribe" in heal, "nothing re-registers the subscription"
    # The server reads data["subscription"] — a flat body is a 400.
    assert "subscription: sub.toJSON()" in heal
    assert "X-CSRFToken" in heal
    # Only when the browser actually has one; re-registering nothing is
    # a guaranteed 400 on every page load.
    assert "if (on)" in heal


def test_push_deactivation_is_only_for_a_gone_subscription():
    """is_active=false must mean "the push service says this endpoint no
    longer exists", not "a send failed once" — otherwise a transient error
    silently switches someone's reminders off for good."""
    src = open("services/push_service.py", encoding="utf-8").read()
    assert "status in (404, 410)" in src
    block = src.split("status in (404, 410)")[1].split("else:")[0]
    assert "_deactivate" in block
    # A non-410 failure warns and leaves the subscription alone.
    after = src.split("status in (404, 410)")[1].split("else:")[1][:200]
    assert "_deactivate" not in after


def test_day_board_sends_a_prep_topic_to_its_own_bank_page(auth_client, monkeypatch):
    """Reported: clicking an AI SDE prep question on the board should open
    that specific topic, not the day view.

    Before this it went to /day, which showed the same one-line title you
    had just clicked — a round trip to no new information. Live data had 12
    such rows, including SQL topics scheduled for today.

    Matched on the DESCRIPTION, because that is the only durable signal: the
    prep scheduler writes "{label} — open the topic at {page}" into the row
    it creates, while the title is the topic itself and says nothing about
    which bank it came from.
    """
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [
        {"id": "E1", "title": "SELECT ... WHERE — the shape of every query",
         "description": "SQL prep — open the topic at /sql",
         "start_time": "19:00", "end_time": "19:30"},
        {"id": "E2", "title": "Balanced Binary Tree",
         "description": "AI/SDE prep — open the topic at /ai-sde",
         "start_time": None, "end_time": None},
        {"id": "E3", "title": "Dentist", "description": "bring the referral letter",
         "start_time": "10:00", "end_time": "10:30"},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board").get_data(as_text=True)

    assert "/sql?" in html and "topic=SELECT" in html
    assert "/ai-sde?" in html and "topic=Balanced" in html
    # An ordinary calendar entry still goes to the day view.
    assert "/day?date=" in html and "focus=ev-E3" in html
    # And the way home is still carried.
    assert html.count("from=board") >= 3


def test_prep_page_match_is_longest_first():
    """"/interview-prep" contains no shorter page path, but the check has to
    be ordered anyway — a future "/sql-advanced" would be swallowed by
    "/sql" and silently route to the wrong bank."""
    import routes.day_board as db
    assert db._prep_target({"description": "Interview prep — open the topic at /interview-prep"}) \
        == "/interview-prep"
    assert db._prep_target({"description": "SQL prep — open the topic at /sql"}) == "/sql"
    assert db._prep_target({"description": "bring the referral letter"}) is None
    assert db._prep_target({"description": ""}) is None
    assert db._prep_target({}) is None
    src = __import__("inspect").getsource(db._prep_target)
    assert "key=len, reverse=True" in src, "shortest path could win"


def test_day_board_has_a_home_button(auth_client, monkeypatch):
    """Asked for. Home and the menu are different destinations — home is the
    app's start page, the menu is the daily summary — and only one of them
    existed."""
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board").get_data(as_text=True)
    assert 'href="/" title="Home"' in html
    assert "/summary?view=daily" in html, "the menu was replaced instead of joined"


def test_topic_landing_matches_on_title_and_clicks_rather_than_forcing_open():
    """Every one of these banks numbers entries by POSITION (ai42, j7, sq3),
    and a position shifts the moment an entry is added or deduped — so a
    link made last week would open whatever moved into that slot. Titles are
    stable, and the Plan button already carries one.

    And it CLICKS the card: /ai-sde fills the body lazily on first open, so
    forcing the class would reveal an empty card.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    block = js.split("ARRIVING FROM THE DAY BOARD ON A SPECIFIC TOPIC")[1]
    assert 'getAttribute("data-title")' in block, "matching on something other than the title"
    assert "head.click()" in block, "forces .open and would show an empty lazy card"
    assert "MutationObserver" in block, "these lists are fetched, not inline"
    assert "landOnTopic(root)" in js, "never wired into attach()"


# ═══════════════════════════════════════════════════
# Prep cards — "Planned on …", green ahead, red elapsed
# ═══════════════════════════════════════════════════

def test_scheduled_endpoint_reports_when_each_topic_is_planned(auth_client, monkeypatch):
    """Asked for: a scheduled prep item should say "Planned on <date> at
    <time>", red once that has elapsed and green while it has not.

    Read from project_tasks, not daily_events: the scheduler writes one task
    PER TOPIC even when a bulk selection collapses into one calendar block,
    so the task is the only per-topic record of what was planned.
    """
    import routes.interview_prep as ip
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: "PROJ")
    monkeypatch.setattr(ip, "get", lambda t, params=None, **k: [
        {"task_text": "ORDER BY, and where NULL sorts", "plan_date": "2026-08-22",
         "start_time": "19:00:00", "status": "open"},
        {"task_text": "Untimed one", "plan_date": "2026-08-16",
         "start_time": "00:00:00", "status": "open"},
        {"task_text": "Repeat", "plan_date": "2026-09-01",
         "start_time": "10:00:00", "status": "open"},
        {"task_text": "Repeat", "plan_date": "2026-08-05",
         "start_time": "08:00:00", "status": "open"},
    ])
    s = auth_client.get("/api/prep/scheduled?bank=sql").get_json()["scheduled"]

    assert s["ORDER BY, and where NULL sorts"]["start_time"] == "19:00"
    # 00:00 is the scheduler's stand-in for "no time given". Reported as
    # absent, or the card would read "at 12:00 AM" like a real appointment.
    assert s["Untimed one"]["start_time"] == ""
    # A topic scheduled twice keeps the EARLIEST — that is the commitment,
    # and showing the later one would hide an overdue first attempt.
    assert s["Repeat"]["plan_date"] == "2026-08-05"


def test_opening_a_bank_page_never_creates_its_project(auth_client, monkeypatch):
    """_ensure_prep_project creates on miss, which is right when scheduling
    and wrong on a page load — merely opening /java should not bring a
    JavaPrep project into existence. Hence a read-only sibling."""
    import routes.interview_prep as ip
    created = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: None)
    monkeypatch.setattr(ip, "post", lambda *a, **k: created.append(a) or [{}])
    r = auth_client.get("/api/prep/scheduled?bank=java")
    assert r.status_code == 200
    assert r.get_json()["scheduled"] == {}
    assert not created, "a page load created a project"
    assert auth_client.get("/api/prep/scheduled?bank=nope").status_code == 400


def test_pg_eq_no_longer_quotes_itself_into_matching_nothing():
    """THE BUG THIS FIXES was silent and expensive. _pg_eq wrapped values in
    double quotes, which PostgREST matched LITERALLY — so every existence
    check built on it answered "not there", always.

    Measured on live data: the quoted form returned 0 rows for both a plain
    name and a comma-bearing title; plain returned 10 and 1. The visible
    damage was ten SQLPrep projects created for one user in four minutes,
    one per Plan click, because the project lookup never found the one it
    had just made.

    The quoting was solving a real problem — commas in titles — that
    supabase_client already solves by handing params to `requests`, which
    URL-encodes them.
    """
    from routes.interview_prep import _pg_eq
    assert _pg_eq("SQLPrep") == "eq.SQLPrep"
    assert '"' not in _pg_eq("ORDER BY, and where NULL sorts")
    assert _pg_eq("A (paren), a colon: and a comma") == \
        "eq.A (paren), a colon: and a comma"


def test_prep_project_lookup_is_deterministic():
    """Where duplicates already exist, an unordered limit:1 can return a
    different row each call and scatter one bank's tasks across several
    projects — which is exactly how the damage compounded."""
    import inspect
    import routes.interview_prep as ip
    assert "created_at.asc" in inspect.getsource(ip._find_prep_project)
    # And the creating path must not keep its own copy of the lookup — that
    # divergence is how the two came to disagree in the first place.
    ensure = inspect.getsource(ip._ensure_prep_project)
    assert "_find_prep_project(user_id, bank)" in ensure
    # The FILTER form specifically — the create payload legitimately sets
    # is_archived, so a bare substring match flags its own insert.
    assert '"is_archived": "eq.false"' not in ensure, (
        "a second, unordered lookup crept back in")


def test_the_schedule_mark_goes_on_the_title_itself():
    """Asked for as "(Planned on X Date at that time)" — parenthesised, on
    the title. It reads better there than as a separate chip: the schedule
    is a fact ABOUT this topic, so it belongs in the sentence naming it
    rather than in the row of category chips beside it.

    The four pages disagree about their title element (.q-text on /ai-sde
    and /interview-prep, .t on /java and /sql), and /java's card body
    contains another .t — so the lookup is scoped to the card HEADER.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    assert "function titleElOf" in js
    lookup = js.split("function titleElOf")[1].split("}")[0]
    assert '".q-head"' in lookup, "an unscoped search would hit a .t in the body"
    assert '".q-text, .t"' in lookup
    paint = js.split("function paintScheduled")[1].split("function loadScheduled")[0]
    assert "titleEl.appendChild(mark)" in paint
    assert '" (" +' in paint, "not parenthesised"
    # A page with an unrecognised title shape must not silently lose it.
    assert "else btn.parentElement.insertBefore(mark, btn)" in paint
    # Inline text, not a pill: a bordered chip mid-sentence breaks the line.
    assert ".prep-when{font-size:.86em" in js
    assert "border-radius:999px;padding:5px 9px" not in js


def test_planned_pill_elapses_at_the_end_of_an_untimed_day():
    """The scheduler stores 00:00 for "no time given". Treating that
    literally would paint TODAY's untimed plan red all day, which is the
    opposite of what it means — an untimed plan for today has not been
    missed at 00:01."""
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    block = js.split("function deadlineOf")[1].split("function paintScheduled")[0]
    assert "23, 59, 59, 999" in block, "an untimed day elapses at midnight"
    # The comparison must happen on the CLIENT: "has it elapsed" needs the
    # reader's clock, and the server is a different machine.
    assert "/api/prep/scheduled" in js
    paint = js.split("function paintScheduled")[1].split("function loadScheduled")[0]
    assert "new Date()" in paint and "late" in paint and "soon" in paint


# ═══════════════════════════════════════════════════
# Missed slots — shaded red once the moment has passed
# ═══════════════════════════════════════════════════

def _day_html(auth_client, monkeypatch, items, on="2026-08-22"):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import routes.day as d
    now = datetime(2026, 8, 22, 19, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr(d, "user_now", lambda: now)
    monkeypatch.setattr(d, "user_today", lambda: now.date())
    monkeypatch.setattr(d, "_meta", lambda u, pd: {})
    monkeypatch.setattr(d, "build_dashboard", lambda u, pd: {"today_items": items})
    return auth_client.get(f"/day?date={on}").get_data(as_text=True)


def _classes_for(html, title):
    """The class list of the .item block containing `title`."""
    import re
    idx = html.find(">" + title + "<")
    assert idx != -1, f"{title!r} is not on the page"
    before = html[:idx]
    m = None
    for m in re.finditer(r'<div class="item([^"]*)"', before):
        pass
    return m.group(1) if m else ""


def test_day_view_shades_a_missed_slot(auth_client, monkeypatch):
    """Asked for: shade it red once the date/time has been missed.

    MEASURED FROM THE END, not the start. An event running 19:00-20:00 is
    not missed at 19:01; it is missed at 20:00. Anything else marks things
    red the moment they begin, which is when you are most likely doing them.
    """
    html = _day_html(auth_client, monkeypatch, [
        {"id": "a", "title": "Ended earlier", "time": "18:00", "end_time": "19:00", "status": "open"},
        {"id": "b", "title": "Running now", "time": "19:00", "end_time": "20:00", "status": "open"},
        {"id": "c", "title": "Later today", "time": "21:00", "end_time": "22:00", "status": "open"},
        {"id": "d", "title": "Past but done", "time": "09:00", "end_time": "10:00",
         "status": "done", "done": True},
    ])
    assert "missed" in _classes_for(html, "Ended earlier")
    assert "missed" not in _classes_for(html, "Running now"), "marked red while in progress"
    assert "missed" not in _classes_for(html, "Later today")
    # Done is done — a completed slot is never a miss, however late it is.
    assert "missed" not in _classes_for(html, "Past but done")


def test_an_untimed_item_is_only_missed_once_its_whole_day_is_past(auth_client, monkeypatch):
    """"No time set" cannot be late at 9am on the day itself — it has all
    day to happen. It becomes a miss when the day is behind us."""
    item = [{"id": "e", "title": "Read the paper", "time": None, "status": "open"}]
    today = _day_html(auth_client, monkeypatch, item, on="2026-08-22")
    assert "missed" not in _classes_for(today, "Read the paper")
    past = _day_html(auth_client, monkeypatch, item, on="2026-08-20")
    assert "missed" in _classes_for(past, "Read the paper")


def test_calendar_grid_uses_the_same_missed_rule():
    """A day that reads "missed" on the list and fine on the grid is worse
    than neither showing it, so both surfaces share the rule: measured from
    the END, and `done` is the only status that counts as complete."""
    js = open("static/v2/planner_v2.js", encoding="utf-8").read()
    block = js.split("MISSED:")[1].split("// Position")[0]
    assert "ev.end_time || ev.start_time" in block, "measured from the start"
    assert '(ev.status || "open") !== "done"' in block
    assert "is-missed" in block

    css = open("static/v2/planner_v2.css", encoding="utf-8").read()
    assert ".event-chip.is-missed" in css
    # A tint and an edge, not a solid repaint: these chips already carry a
    # priority colour and a meaningful fill, and a busy past day would
    # become an unreadable wall of red.
    assert "repeating-linear-gradient" in css.split(".event-chip.is-missed")[1][:400]
    assert "html.dark .event-chip.is-missed" in css, "unreadable in dark mode"


def test_prep_features_do_not_assume_the_list_already_exists():
    """A BUG THAT SHIPPED, and the reason it got through.

    Every bank page calls PrepScheduler.attach() synchronously while its
    list is fetched over the network and rendered in a .then() — so at the
    moment attach runs there is not a single card in the container.

    Both the bulk-select bar and the "Planned on …" pill opened with a
    "no cards? nothing to do" guard, which was true every single time. Both
    features were dead on every page, and the jsdom harnesses missed it
    because they inserted cards BEFORE calling attach — the opposite of what
    the pages do. A test that sets up the world in the wrong order can only
    ever confirm the wrong order works.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    assert "function whenCardsReady" in js, "nothing waits for the list"
    # The two features that need a card must go through the waiter.
    attach = js.split("attach: function (root)")[1].split("_bulk:")[0]
    assert "whenCardsReady(root, function ()" in attach
    body = attach.split("whenCardsReady(root, function ()")[1][:220]
    assert "mountBulk(root)" in body and "loadScheduled(root)" in body
    # It must give up eventually rather than observing for the life of the
    # page on a bank that is genuinely empty.
    waiter = js.split("function whenCardsReady")[1].split("function bulkButtons")[0]
    assert "disconnect()" in waiter and "setTimeout" in waiter


def test_day_board_strikes_out_anything_completed(auth_client, monkeypatch):
    """Asked for. Tasks and checklist rows already did; EVENTS did not —
    neither the timed chips on the rail nor the untimed ones in the list.

    Struck through and stood down rather than REMOVED: the board is a record
    of the day as much as a plan for it, and a completed morning that
    disappears reads as a morning where nothing happened.
    """
    import re
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [
        {"id": "E1", "title": "Standup done", "start_time": "09:00",
         "end_time": "09:30", "status": "done"},
        {"id": "E2", "title": "Standup open", "start_time": "10:00",
         "end_time": "10:30", "status": "open"},
        {"id": "E3", "title": "Untimed done", "start_time": None,
         "end_time": None, "status": "done"},
        {"id": "E4", "title": "Untimed open", "start_time": None,
         "end_time": None, "status": "open"},
    ])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [
        {"id": "T1", "task_text": "Task done", "quadrant": "Q1", "is_done": True},
        {"id": "T2", "task_text": "Task open", "quadrant": "Q1", "is_done": False},
    ])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [
        {"id": "C1", "title": "Check done", "done": True},
        {"id": "C2", "title": "Check open", "done": False},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board").get_data(as_text=True)

    def marked_done(title):
        """Is the CONTAINER wrapping `title` flagged done?

        Matches the <li> or the rail <a> specifically. A bare "last class
        before the title" search picks up the ✓ span's own class instead,
        which is how the first version of this test reported a false miss.
        """
        i = html.find(title)
        assert i != -1, f"{title!r} is not on the board"
        seg = html[max(0, i - 600):i]
        m = None
        for m in re.finditer(r'<(?:li|a) class="([^"]*)"', seg):
            pass
        return "done" in (m.group(1) if m else "")

    for title in ("Standup done", "Untimed done", "Task done", "Check done"):
        assert marked_done(title), f"{title} is not struck out"
    for title in ("Standup open", "Untimed open", "Task open", "Check open"):
        assert not marked_done(title), f"{title} was struck out while still open"

    # Both shapes need the rule that actually draws the line.
    assert ".ev.done .ttl{text-decoration:line-through}" in html
    assert "li.done .txt{text-decoration:line-through}" in html
    # Done is dimmed, not hidden.
    assert ".ev.done{opacity:.55" in html


# ═══════════════════════════════════════════════════
# Ticking a topic studied completes what it scheduled
# ═══════════════════════════════════════════════════

def test_marking_a_topic_studied_closes_its_task_event_and_bucket_row(auth_client, monkeypatch):
    """Reported: ticking the checkbox on a prep page did not mark the item
    complete on the Day Board or in the Quick Bucket.

    It never could. The tick updated the STUDY record only, while scheduling
    a topic writes three OTHER rows — a project task, a calendar event and a
    bucket line — and none of them heard about it. The topic read done in
    one place and outstanding in three.
    """
    import routes.interview_prep as ip
    updates = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: "PROJ")
    monkeypatch.setattr(ip, "get", lambda t, params=None, **k: (
        [{"id": "EV1", "description": "AI/SDE prep — open the topic at /ai-sde"},
         {"id": "EV2", "description": "Dentist, nothing to do with prep"}]
        if t == "daily_events" else []))
    monkeypatch.setattr(ip, "update",
                        lambda t, params=None, json=None, **k: updates.append((t, params, json)))

    r = auth_client.post("/api/prep/complete", json={
        "bank": "ai_sde", "title": "Balanced Binary Tree", "done": True})
    assert r.status_code == 200, r.get_data(as_text=True)

    tables = [t for t, _p, _j in updates]
    assert "project_tasks" in tables and "daily_events" in tables and "quick_bucket" in tables

    task = next(j for t, _p, j in updates if t == "project_tasks")
    assert task["status"] == "done"
    bucket = next(j for t, _p, j in updates if t == "quick_bucket")
    assert bucket["is_done"] is True
    # Clearing the Top-5 pins matches what the bucket's own done endpoint
    # does — otherwise the row stays pinned and crossed out in today's panel.
    assert bucket["top5_date"] is None and bucket["top5_position"] is None

    # ONLY the prep-created calendar row. A real appointment that happens to
    # share a title must be left alone.
    ev_updates = [p for t, p, _j in updates if t == "daily_events"]
    assert len(ev_updates) == 1
    assert "EV1" in ev_updates[0]["id"]


def test_unticking_a_topic_reopens_all_three(auth_client, monkeypatch):
    """Un-ticking has to work, or a mis-click closes a topic for good."""
    import routes.interview_prep as ip
    updates = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: "PROJ")
    monkeypatch.setattr(ip, "get", lambda t, params=None, **k: (
        [{"id": "EV1", "description": "SQL prep — open the topic at /sql"}]
        if t == "daily_events" else []))
    monkeypatch.setattr(ip, "update",
                        lambda t, params=None, json=None, **k: updates.append((t, params, json)))
    auth_client.post("/api/prep/complete", json={
        "bank": "sql", "title": "ORDER BY, and where NULL sorts", "done": False})

    assert next(j for t, _p, j in updates if t == "project_tasks")["status"] == "open"
    assert next(j for t, _p, j in updates if t == "daily_events")["status"] == "open"
    b = next(j for t, _p, j in updates if t == "quick_bucket")
    assert b["is_done"] is False and b["done_at"] is None


def test_completing_a_never_scheduled_topic_is_not_an_error(auth_client, monkeypatch):
    """Most topics are never put on a day. Ticking one of those has nothing
    else to update, and must not create a project to find that out."""
    import routes.interview_prep as ip
    created = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: None)
    monkeypatch.setattr(ip, "get", lambda *a, **k: [])
    monkeypatch.setattr(ip, "update", lambda *a, **k: None)
    monkeypatch.setattr(ip, "post", lambda *a, **k: created.append(a) or [{}])
    r = auth_client.post("/api/prep/complete", json={
        "bank": "java", "title": "HashMap internals", "done": True})
    assert r.status_code == 200
    assert r.get_json()["touched"]["tasks"] == 0
    assert not created, "completing a topic created a project"

    assert auth_client.post("/api/prep/complete",
                            json={"bank": "java", "title": ""}).status_code == 400
    assert auth_client.post("/api/prep/complete",
                            json={"bank": "nope", "title": "x"}).status_code == 400


def test_the_studied_checkbox_is_wired_without_hijacking_the_page():
    """The pages disagree about the studied box (.q-prac on /ai-sde, a bare
    input elsewhere), so it is matched by "a checkbox in a card that also has
    a Plan button" — which is also how the bank and title are known.

    Bound on CHANGE, not in the capture-phase click handler: that one stops
    propagation and would prevent each page's own tick handler ever running.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    assert "syncCompletion" in js
    handler = js.split('root.addEventListener("change"')[1].split("});")[0]
    assert 'box.type !== "checkbox"' in handler
    # Our own bulk box must never be mistaken for the studied one.
    assert 'classList.contains("prep-pickbox")' in handler
    assert "stopPropagation" not in handler, "would break the page's own tick"


def test_quick_bucket_tick_reaches_the_topic_it_came_from(auth_client, monkeypatch):
    """Reported: un-ticking a row in the Quick Bucket left the prep page and
    the day planner still showing it done.

    The link existed in ONE direction — scheduling a topic wrote a bucket
    row, but the row knew nothing about where it came from. Both endpoints
    now walk it back.
    """
    import routes.quick_bucket as qb
    import routes.interview_prep as ip
    calls = []
    monkeypatch.setattr(qb, "update", lambda *a, **k: None)
    monkeypatch.setattr(qb, "_fetch_event_id", lambda u, i: None)
    monkeypatch.setattr(qb, "get", lambda t, params=None, **k:
                        [{"text": "AISDEPrep · Balanced Binary Tree"}]
                        if t == "quick_bucket" else [])
    monkeypatch.setattr(ip, "complete_prep_artifacts",
                        lambda u, b, t, d, include_bucket=True:
                        calls.append((b, t, d, include_bucket)) or {})

    auth_client.post("/api/quick-bucket/X/done")
    # include_bucket=False: the caller has already written that row, and
    # re-writing it would be pointless work at best and a fight at worst.
    assert calls == [("ai_sde", "Balanced Binary Tree", True, False)]

    calls.clear()
    auth_client.post("/api/quick-bucket/X/reopen")
    assert calls == [("ai_sde", "Balanced Binary Tree", False, False)]


def test_an_ordinary_bucket_row_is_not_mistaken_for_a_prep_one(auth_client, monkeypatch):
    """The separator alone cannot identify one: a row reading
    "Walking (Pomodoro · 25m)" contains it too. The PROJECT NAME prefix is
    what marks a prep row."""
    import routes.quick_bucket as qb
    import routes.interview_prep as ip
    from routes.interview_prep import parse_bucket_text

    assert parse_bucket_text("AISDEPrep · Balanced Binary Tree") == \
        ("ai_sde", "Balanced Binary Tree")
    assert parse_bucket_text("SQLPrep · ORDER BY, and where NULL sorts") == \
        ("sql", "ORDER BY, and where NULL sorts")
    for text in ("Walking (Pomodoro · 25m)", "buy milk", "Something · else",
                 "AISDEPrep · ", ""):
        assert parse_bucket_text(text) == (None, None), text

    calls = []
    monkeypatch.setattr(qb, "update", lambda *a, **k: None)
    monkeypatch.setattr(qb, "_fetch_event_id", lambda u, i: None)
    monkeypatch.setattr(qb, "get", lambda t, params=None, **k:
                        [{"text": "Walking (Pomodoro · 25m)"}] if t == "quick_bucket" else [])
    monkeypatch.setattr(ip, "complete_prep_artifacts",
                        lambda *a, **k: calls.append(a) or {})
    auth_client.post("/api/quick-bucket/X/done")
    assert not calls


def test_ai_sde_study_record_follows_a_tick_made_elsewhere(auth_client, monkeypatch):
    """/ai-sde keeps studied state on the server, so closing a topic from
    the bucket has to update it or the page disagrees on reload.

    /java and /sql keep theirs in localStorage, which nothing server-side
    can reach — those are reconciled on the client from the task status.
    """
    import routes.interview_prep as ip
    posted = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: None)
    monkeypatch.setattr(ip, "get", lambda *a, **k: [])
    monkeypatch.setattr(ip, "update", lambda *a, **k: None)
    monkeypatch.setattr(ip, "post", lambda t, p, **k: posted.append((t, p)) or [{}])

    title = ip.AI_SDE_ENTRIES[0]["title"]
    ip.complete_prep_artifacts("u1", "ai_sde", title, True)
    prog = [p for t, p in posted if t == "ai_sde_progress"]
    assert prog and prog[0]["studied"] is True and prog[0]["entry_title"] == title

    posted.clear()
    ip.complete_prep_artifacts("u1", "ai_sde", title, False)
    prog = [p for t, p in posted if t == "ai_sde_progress"]
    assert prog and prog[0]["studied"] is False and prog[0]["studied_at"] is None

    # A bank with no server-side study record must not invent one.
    posted.clear()
    ip.complete_prep_artifacts("u1", "sql", "ORDER BY, and where NULL sorts", True)
    assert not [p for t, p in posted if t == "ai_sde_progress"]


def test_the_checkbox_is_reconciled_without_echoing_back():
    """/java and /sql hold studied state in localStorage, so a tick made in
    the bucket can only reach them on the client. The reconciler dispatches
    a real change event — each page persists its own progress in its own
    handler, and simply setting .checked would leave the tick undone on the
    next reload — and guards against that event returning as a fresh
    completion.
    """
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    assert "function reconcileChecked" in js
    body = js.split("function reconcileChecked")[1].split("function syncCompletion")[0]
    assert "reconciling = true" in body and "reconciling = false" in body
    assert 'new Event("change"' in body, "the page would never persist the tick"
    # Only topics that are actually scheduled — an unscheduled one has no
    # task to disagree with.
    assert "if (!info) return" in body
    assert "if (reconciling) return;" in js.split("function syncCompletion")[1][:200]


# ═══════════════════════════════════════════════════
# Making silent failure audible
# ═══════════════════════════════════════════════════

def test_loud_warns_on_a_miss_and_then_shuts_up(caplog):
    """Four faults this month were invisible because a broken thing looked
    exactly like an empty one. These make the difference audible — while
    THROTTLING, because a warning on every request is noise, and noise is
    how the last round of silence got established.
    """
    import logging
    from services import loud
    loud._last.clear()

    with caplog.at_level(logging.WARNING, logger="daily_plan"):
        assert loud.expect([], "the SQLPrep project", user_id="u1") == []
        loud.expect([{"id": 1}], "something present", user_id="u1")   # silent
        loud.bailed("prep bulk bar", "no cards yet", page="/sql")
        loud.created_what_should_exist("the SQLPrep project", user_id="u1")

    text = caplog.text
    assert "SILENT-MISS" in text and "the SQLPrep project" in text
    assert "FEATURE-INERT" in text and "prep bulk bar" in text
    assert "CREATED-AFTER-MISS" in text
    assert text.count("SILENT-MISS") == 1, "a present row should log nothing"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="daily_plan"):
        loud.expect([], "the SQLPrep project", user_id="u1")
    assert "SILENT-MISS" not in caplog.text, "the same warning repeated"


def test_the_duplicate_project_bug_would_now_announce_itself(caplog):
    """The find-or-create that made ten SQLPrep projects in four minutes.
    A miss is legitimate exactly ONCE per user per bank; if it repeats for
    the same pair, the lookup is broken rather than the data missing."""
    import inspect
    import routes.interview_prep as ip
    src = inspect.getsource(ip._ensure_prep_project)
    assert "created_what_should_exist" in src
    # It must sit BEFORE the insert, or it only reports after the damage.
    assert src.index("created_what_should_exist") < src.index('post("projects"')


def test_dead_push_subscriptions_are_reported(caplog):
    """A user with no ACTIVE subscription receives nothing, silently and
    forever, while the browser still says notifications are on. That is the
    likeliest reason this household's reminders died in April and it was
    found in August."""
    import inspect
    from services import push_service
    src = inspect.getsource(push_service._active_subscriptions)
    assert "loud.bailed" in src
    # It distinguishes "never subscribed" from "all expired" — those need
    # different actions, and a single message would hide the second.
    assert "INACTIVE" in src and "no subscription at all" in src


def test_a_browser_feature_can_report_that_it_did_nothing(auth_client, caplog):
    """A console warning does not help: nobody has the console open on their
    phone. An inert feature reports itself into the server log instead."""
    import logging
    from services import loud
    loud._last.clear()
    with caplog.at_level(logging.WARNING, logger="daily_plan"):
        r = auth_client.post("/api/client-inert", json={
            "feature": "prep-scheduler", "why": "no card appeared within 15s",
            "page": "/sql"})
    assert r.status_code == 200
    assert "FEATURE-INERT" in caplog.text
    assert "prep-scheduler" in caplog.text and "/sql" in caplog.text

    # A blank report is dropped rather than logging an empty line.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="daily_plan"):
        auth_client.post("/api/client-inert", json={})
    assert "FEATURE-INERT" not in caplog.text


def test_the_guards_that_hid_the_dead_features_now_speak_up():
    """whenCardsReady is the exact guard both dead features sat behind.
    Waiting the whole window without a card means they are not running."""
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    waiter = js.split("function whenCardsReady")[1].split("function inert")[0]
    assert "if (!fired) inert(" in waiter, "a silent timeout is still silent"
    assert 'inert("no MutationObserver")' in waiter
    assert "window.dpInert" in js

    g = open("static/js/global.js", encoding="utf-8").read()
    assert "window.dpInert" in g and "/api/client-inert" in g
    # Once per reason per page load: a signal, not telemetry.
    assert "reported[key]" in g
    # keepalive, because a navigation is exactly when this fires.
    assert "keepalive: true" in g


# ═══════════════════════════════════════════════════
# Her own notes on a prep question
# ═══════════════════════════════════════════════════

def test_a_note_can_be_saved_and_read_back_per_bank(auth_client, monkeypatch):
    """A bank entry is written material — an answer, a walkthrough, worked
    examples. What it never had is somewhere for the READER's thinking: what
    she got wrong, what finally made it click, what an interviewer actually
    asked. That is the note most worth keeping.
    """
    import routes.interview_prep as ip
    posted = []
    monkeypatch.setattr(ip, "post", lambda t, p, **k: posted.append((t, p, k)) or [{}])
    monkeypatch.setattr(ip, "get", lambda t, params=None, **k: [
        {"entry_title": "ORDER BY, and where NULL sorts",
         "note": "I got the NULL ordering backwards", "updated_at": "2026-08-22"},
        {"entry_title": "Empty one", "note": "   ", "updated_at": "2026-08-22"},
    ])

    j = auth_client.get("/api/prep/notes?bank=sql").get_json()
    assert j["available"] is True
    assert j["notes"]["ORDER BY, and where NULL sorts"]["note"] == \
        "I got the NULL ordering backwards"
    # A blank note is not a note — it would draw an empty box for nothing.
    assert "Empty one" not in j["notes"]

    r = auth_client.post("/api/prep/notes", json={
        "bank": "sql", "title": "ORDER BY, and where NULL sorts",
        "note": "Ask about NULLS FIRST vs LAST"})
    assert r.status_code == 200
    table, payload, kwargs = posted[-1]
    assert table.startswith("prep_notes")
    assert payload["entry_title"] == "ORDER BY, and where NULL sorts"
    assert payload["bank"] == "sql"
    # UPSERT, not insert. Without merge-duplicates a second save creates a
    # second row and the first silently becomes unreachable.
    assert "merge-duplicates" in kwargs.get("prefer", "")
    # AND the conflict target must be named. PostgREST infers it from the
    # PRIMARY KEY unless told, and this table's key is a generated uuid that
    # never collides — so without ?on_conflict= there is nothing to merge on
    # and the SECOND save of any note returns 409. Verified against the live
    # database, not assumed.
    assert "on_conflict=user_id,bank,entry_title" in table, (
        "the second edit of a note will fail with a conflict")


def test_notes_are_keyed_by_title_not_by_a_positional_id(auth_client, monkeypatch):
    """Every bank numbers its entries by POSITION — ai42, j7, sq3 — and a
    position shifts the moment an entry is added or deduped. The AI SDE bank
    went from ~500 to 1,120 entries with 57 duplicates folded out."""
    import routes.interview_prep as ip
    posted = []
    monkeypatch.setattr(ip, "post", lambda t, p, **k: posted.append(p) or [{}])
    auth_client.post("/api/prep/notes",
                     json={"bank": "ai_sde", "title": "Two Sum", "note": "n"})
    assert posted[-1]["entry_title"] == "Two Sum"
    assert not any(k in posted[-1] for k in ("entry_id", "id", "index"))

    assert auth_client.post("/api/prep/notes",
                            json={"bank": "ai_sde", "title": "", "note": "x"}).status_code == 400
    assert auth_client.post("/api/prep/notes",
                            json={"bank": "nope", "title": "t", "note": "x"}).status_code == 400


def test_notes_degrade_when_the_migration_has_not_been_run(auth_client, monkeypatch):
    """The page must HIDE the box rather than offer one that silently throws
    away everything typed into it."""
    import routes.interview_prep as ip

    def missing(*a, **k):
        raise Exception('relation "prep_notes" does not exist')

    monkeypatch.setattr(ip, "get", missing)
    j = auth_client.get("/api/prep/notes?bank=java").get_json()
    assert j["available"] is False and j["migration"] == "MIGRATION_PREP_NOTES.sql"

    monkeypatch.setattr(ip, "post", missing)
    r = auth_client.post("/api/prep/notes",
                         json={"bank": "java", "title": "t", "note": "n"})
    assert r.status_code == 503
    assert "MIGRATION_PREP_NOTES.sql" in r.get_json()["error"]


def test_the_notes_box_is_injected_on_open_not_on_render():
    """A bank page draws over a thousand cards; a textarea in every one is
    waste. And /ai-sde fills its body LAZILY on first open, so anything
    added earlier is thrown away by that fetch — hence watching for the
    class change rather than hooking any one page's toggle."""
    js = open("static/js/prep-scheduler.js", encoding="utf-8").read()
    assert "function ensureNote" in js
    # The body lookup is its own function, so check it there rather than
    # inside ensureNote — an earlier version of this test looked in the
    # wrong place and failed on working code.
    host = js.split("function noteHostFor")[1].split("}")[0]
    assert ".q-body" in host, "the note is not placed in the card body"
    body = js.split("function ensureNote")[1].split("function autoGrow")[0]
    assert "noteHostFor(card)" in body
    assert 'querySelector(".prep-note")' in body, "would stack a second box"
    # Saved on a debounce AND on blur: the debounce has not fired when you
    # close the card.
    assert 'addEventListener("blur", save)' in body
    # Typing must not reach the page's own card toggle.
    assert "stopPropagation" in body
    assert 'attributeFilter: ["class"]' in js, "a lazy re-render would lose it"


# ═══════════════════════════════════════════════════
# App health — silent failures surfaced where they'll be seen
# ═══════════════════════════════════════════════════

def test_settings_surfaces_silent_failures(auth_client):
    """Logging a problem only helps if someone reads the log. Four faults
    were live for weeks precisely because nothing crashed — so the same
    reports now appear on a page that gets opened.

    NOTE ON ASSERTIONS HERE: match the class ATTRIBUTE, not the bare class
    NAME. The stylesheet ships on every render, so `"health-row" in html` is
    true even with an empty list — a trap that has already produced three
    false results in this suite.
    """
    import re
    from services import loud
    loud.clear()

    html = auth_client.get("/settings").get_data(as_text=True)
    assert "Nothing has reported a problem" in html
    assert 'class="health-row' not in html, "an empty list rendered rows"

    for _ in range(7):
        loud.expect([], "the SQLPrep project", user_id="u1", bank="sql")
    loud.bailed("web push", "every subscription is INACTIVE", user_id="u1")

    html = auth_client.get("/settings").get_data(as_text=True)
    assert "App health" in html
    # Aggregated, not one line per occurrence: the COUNT is the signal.
    assert "&times;7" in html
    assert "the SQLPrep project" in html and "web push" in html
    # It says which user/bank, or the report is unactionable.
    assert "bank=&#39;sql&#39;" in html or "bank='sql'" in html

    # One occurrence is weak evidence; a run of them is not — so only the
    # repeated one is called out.
    rows = re.findall(r'class="health-row([^"]*)"',
                      html.split('class="health-list"')[1])
    assert any("is-loud" in r for r in rows), "a repeated fault is not flagged"
    assert any("is-loud" not in r for r in rows), "a single report is over-flagged"

    loud.clear()


def test_health_list_can_be_cleared(auth_client):
    """The list stops being useful the moment it is mostly things already
    dealt with."""
    from services import loud
    loud.clear()
    loud.expect([], "something", user_id="u1")
    assert loud.recent()

    assert auth_client.post("/api/settings/health/clear").status_code == 200
    assert not loud.recent()


def test_health_counts_stay_true_while_the_log_is_throttled():
    """The log line is throttled to once per five minutes so it does not
    become noise — but the COUNT must not be, or the page would report a
    hourly fault as having happened once."""
    from services import loud
    loud.clear()
    for _ in range(40):
        loud.expect([], "a broken filter", user_id="u1")
    rows = loud.recent()
    assert len(rows) == 1 and rows[0]["count"] == 40
    loud.clear()


def test_health_buffer_is_bounded():
    """A burst of new problems must not push out the one still happening."""
    from services import loud
    loud.clear()
    loud.expect([], "the important recurring one", user_id="u1")
    for i in range(loud._RECORD_MAX + 50):
        loud.expect([], f"noise {i}", user_id="u1")
    # Keep it alive: eviction is least-recently-SEEN, not oldest-first.
    loud.expect([], "the important recurring one", user_id="u1")
    assert len(loud.recent()) <= loud._RECORD_MAX
    assert any("the important recurring one" in r["message"] for r in loud.recent())
    loud.clear()


def test_quick_bucket_accepts_a_pasted_list(auth_client):
    """Asked: is there somewhere to dump a laundry list of items?

    The Quick Bucket is exactly that surface — and its capture field is
    already a textarea — but everything typed into it became ONE row, so
    pasting twenty things to get them out of your head produced one item
    containing twenty lines. That is the opposite of what a bucket is for.
    """
    js = open("static/js/quick_bucket.js", encoding="utf-8").read()
    assert "const addLines" in js
    block = js.split("const addLines")[1].split("// SW reports back")[0]
    assert "split(/\\r?\\n/)" in block, "windows line endings would not split"
    assert "filter(Boolean)" in block, "blank lines would become empty items"
    # One line must behave exactly as before — no summary toast, no change.
    assert "if (lines.length <= 1)" in block
    # Each line goes through addItem, so "@1h" and "tomorrow" still parse and
    # the offline queue and client-id dedupe still apply. A bulk endpoint
    # would have to reimplement all of it.
    assert "await addItem(line" in block
    # Sequential on purpose: the priority badge is derived from the rows
    # already present, so parallel adds would collide on the number.
    assert "for (const line of lines)" in block

    html = open("templates/quick_bucket.html", encoding="utf-8").read()
    # maxlength caps the whole BOX, not one item. At 500 a pasted list was
    # truncated at roughly eight lines.
    assert 'maxlength="20000"' in html
    assert "one item per line" in html

    # The server still bounds each individual item.
    import routes.quick_bucket as qb
    assert qb._MAX_TEXT_LEN == 500


def test_quick_bucket_can_show_one_group_at_a_time(auth_client):
    """Asked for as "a filter to show only Future".

    Future IS the backlog bucket, and it is unreadable sitting underneath
    everything due now. Built as a focus on any single group rather than a
    Future-only toggle: it is the same control, and it also answers "what is
    due now" and "what did I finish", which are the other two questions this
    list gets asked.
    """
    html = auth_client.get("/quick-bucket").get_data(as_text=True)
    assert 'id="qb-groupfilter"' in html

    js = open("static/js/quick_bucket.js", encoding="utf-8").read()
    assert "GROUP_FILTERS" in js and "paintGroupFilter" in js
    # Every group, plus an explicit All.
    for key in ('""', '"now"', '"today"', '"future"', '"done"'):
        assert key in js.split("const GROUP_FILTERS")[1].split("];")[0]

    paint = js.split("const paintGroupFilter")[1].split("const wireGroupFilter")[0]
    # The count is half the point: the chip must say how much is in Future
    # while you are looking at Now, so it is computed from ALL groups.
    assert "VISIBLE_GROUPS.reduce" in paint
    # An empty Future bucket is a fact worth looking at, not a dead button.
    # Match the ATTRIBUTE, not the word — the comment explaining this says
    # "disabled", and matching prose is a mistake this suite keeps making.
    assert "disabled>" not in paint and 'disabled="' not in paint

    wire = js.split("const wireGroupFilter")[1].split("// ───")[0]
    # Pressing the active chip returns to All, so the filter is never a state
    # you have to hunt for the way out of.
    assert "groupFilter === next" in wire
    # Persisted: a backlog review is a mode you stay in for a few minutes.
    assert "GROUP_FILTER_KEY" in wire

    # The default is everything — the everyday view must not change.
    state = js.split("let groupFilter =")[1][:40]
    assert '""' in state


# ═══════════════════════════════════════════════════
# /backlog — one view over two lists that stay put
# ═══════════════════════════════════════════════════

def _backlog_stub(monkeypatch, bucket=None, tasks=None, projects=None):
    import routes.backlog as bk

    def fake_get(table, params=None, **k):
        if table == "quick_bucket":
            return bucket or []
        if table == "project_tasks":
            return tasks or []
        if table == "projects":
            return projects or []
        return []

    monkeypatch.setattr(bk, "get", fake_get)


def test_backlog_shows_both_lists_without_moving_anything(auth_client, monkeypatch):
    """Asked for after the alternative — relocating project tasks into the
    bucket — turned out to be destructive: project_tasks carries 40 columns
    to quick_bucket's 21, and moving one drops its project, key result,
    initiative, epic, sprint, priority and ordering. Project progress is
    computed from live task counts too, so the move would silently change
    the completion figure on every project involved.

    It was a READING problem, so this reads both and writes nothing.
    """
    _backlog_stub(
        monkeypatch,
        bucket=[{"id": "b1", "text": "Renew passport", "time_bucket": "future",
                 "due_at": None, "created_at": "2026-08-01"}],
        tasks=[{"task_id": "t1", "task_text": "Revise the BCP/DR documentation",
                "status": "open", "project_id": "p1", "due_date": "2026-04-06",
                "created_at": "2026-01-01", "plan_date": None, "start_time": None}],
        projects=[{"project_id": "p1", "name": "Office"}],
    )
    html = auth_client.get("/backlog").get_data(as_text=True)

    assert "Renew passport" in html
    assert "Revise the BCP/DR documentation" in html
    # Grouped by project, and linking back to it — the grouping is the whole
    # reason these stay where they are.
    assert "Office" in html and "/projects/p1/tasks" in html

    # Both lists are routable now — the page became the capture inbox —
    # so the old "this writes nothing at all" pin no longer describes it.
    # What survives is the narrower rule it existed to protect: a PROJECT
    # task is never relocated. It is dated and pointed at, never rewritten
    # into another table and never hard-deleted.
    assert html.count("data-bk-send") >= 2

    import inspect
    import routes.backlog as bk
    src = inspect.getsource(bk)
    assert "delete(" not in src, "the backlog must never hard delete"


def test_backlog_never_relocates_a_project_task(auth_client, monkeypatch):
    """The one destructive move, refused at the door.

    Filing a project task under a DIFFERENT project, or turning it into a
    note, would strip the key result, initiative, epic, sprint and ordering
    that only project_tasks carries, and would change the completion figure
    on the project it left. Promotion is the single route it accepts, and
    even that writes a POINTER rather than a copy.
    """
    import routes.backlog as bk
    _backlog_stub(
        monkeypatch,
        tasks=[{"task_id": "t1", "task_text": "Revise the BCP/DR documentation",
                "status": "open", "project_id": "p1", "plan_date": None,
                "start_time": None}],
        projects=[{"project_id": "p1", "name": "Office"}],
    )
    posted, updated = [], []
    monkeypatch.setattr(bk, "post",
                        lambda t, j, **k: posted.append((t, j)) or [{"id": "new"}])
    monkeypatch.setattr(bk, "update",
                        lambda t, params, j, **k: updated.append((t, params, j)))

    for dest in ("project", "note", "reference", "inbox"):
        r = auth_client.post("/api/backlog/send",
                             json={"kind": "task", "id": "t1", "to": dest})
        assert r.status_code == 400, f"a project task was sent to {dest}"
    assert not posted and not updated

    r = auth_client.post("/api/backlog/send",
                         json={"kind": "task", "id": "t1", "to": "quick"})
    assert r.status_code == 200

    # A POINTER, not a copy: without this the planner counts one piece of
    # work twice and ticking either leaves the other open.
    assert posted and posted[0][0] == "quick_bucket"
    assert posted[0][1]["source_task_id"] == "t1"

    # Dated, not moved — the task keeps its project.
    assert updated and updated[0][0] == "project_tasks"
    assert set(updated[0][2]) == {"plan_date"}, updated[0][2]


def test_backlog_capture_takes_a_pasted_list(auth_client, monkeypatch):
    """"one source stop for capturing all the laundry list of my tasks" —
    so a pasted block is many items, not one item with newlines in it.

    Captured rows land in the FUTURE bucket, which is what makes them
    backlog rather than work already prioritised.
    """
    import routes.backlog as bk
    made = []
    monkeypatch.setattr(bk, "post",
                        lambda t, j, **k: made.append((t, j)) or [{"id": "x"}])

    r = auth_client.post("/api/backlog/capture",
                         json={"text": "Renew passport\n\n  Book dentist  \nFix tap"})
    assert r.status_code == 200
    assert [j["text"] for _, j in made] == ["Renew passport", "Book dentist", "Fix tap"]
    assert all(j["time_bucket"] == "future" for _, j in made)
    assert all(t == "quick_bucket" for t, _ in made)

    made.clear()
    assert auth_client.post("/api/backlog/capture",
                            json={"text": "   \n  "}).status_code == 400
    assert not made


def test_backlog_excludes_finished_and_scheduled_work(auth_client, monkeypatch):
    """A backlog is what is outstanding and undated. Anything closed, already
    put on a day, or already in the project's recycle bin is not."""
    tasks = [
        {"task_id": "a", "task_text": "Open and undated", "status": "open",
         "project_id": "p1", "created_at": "1", "plan_date": None, "start_time": None},
        {"task_id": "b", "task_text": "Already done", "status": "done",
         "project_id": "p1", "created_at": "1", "plan_date": None, "start_time": None},
        {"task_id": "c", "task_text": "Has a day", "status": "open",
         "project_id": "p1", "created_at": "1", "plan_date": "2026-08-22", "start_time": None},
        {"task_id": "d", "task_text": "Has a time", "status": "open",
         "project_id": "p1", "created_at": "1", "plan_date": None, "start_time": "09:00"},
        {"task_id": "e", "task_text": "Backlog status counts", "status": "backlog",
         "project_id": "p1", "created_at": "1", "plan_date": None, "start_time": None},
    ]
    _backlog_stub(monkeypatch, tasks=tasks,
                  projects=[{"project_id": "p1", "name": "Office"}])
    html = auth_client.get("/backlog").get_data(as_text=True)

    assert "Open and undated" in html
    assert "Backlog status counts" in html
    assert "Already done" not in html
    assert "Has a day" not in html
    assert "Has a time" not in html

    # is_eliminated is the flag the projects UI treats as removed — the task
    # list does not even filter on is_deleted.
    import inspect
    import routes.backlog as bk
    src = inspect.getsource(bk._undated_project_tasks)
    assert '"is_eliminated": "eq.false"' in src
    assert "is_deleted" not in src.split('"""')[2]


def test_backlog_agrees_with_the_bucket_page_about_future(auth_client, monkeypatch):
    """quick_bucket.js puts an "at" item into Future when its pinned time is
    beyond today. This copies that rule rather than inventing one — three
    divergent copies of the checklist schedule rule already cost this
    codebase a bug that ran for months."""
    from datetime import timedelta
    from utils.user_tz import user_today
    today = user_today()
    _backlog_stub(monkeypatch, bucket=[
        {"id": "1", "text": "Deferred outright", "time_bucket": "future",
         "due_at": None, "created_at": "3"},
        {"id": "2", "text": "Pinned next week", "time_bucket": "at",
         "due_at": (today + timedelta(days=7)).isoformat() + "T09:00:00+00:00",
         "created_at": "2"},
        {"id": "3", "text": "Pinned today", "time_bucket": "at",
         "due_at": today.isoformat() + "T09:00:00+00:00", "created_at": "1"},
        {"id": "4", "text": "Due in an hour", "time_bucket": "1h",
         "due_at": None, "created_at": "0"},
    ])
    html = auth_client.get("/backlog").get_data(as_text=True)

    assert "Deferred outright" in html
    assert "Pinned next week" in html, "a future-dated pin belongs in the backlog"
    assert "Pinned today" not in html, "today's work is not backlog"
    assert "Due in an hour" not in html, "a deadline bucket is not backlog"


def test_a_trashed_project_task_is_not_also_in_the_live_list(auth_client, monkeypatch):
    """The project's task list filtered ONLY on is_eliminated, while its
    recycle bin selects `status in (deleted, skipped, not_required) OR
    is_eliminated`. Setting a task to "deleted" happens to flip
    is_eliminated too, so that case looked fine — but "skipped" does not, so
    a skipped task appeared in the project AND in its own bin at once.

    Fixed on the STATUS rather than by making every writer remember a second
    flag: two flags kept in sync by convention is precisely how they drift.
    """
    import routes.projects as pr

    live = pr._live_status_filter()
    for s in ("deleted", "skipped", "not_required"):
        assert s in live, f"{s} is in the bin but not excluded from the list"
    assert "done" not in live, "completed work is still live unless hidden"

    # `status` is a single query parameter, so a second assignment would
    # silently replace the first — hence one combined filter.
    both = pr._live_status_filter(also_hide_done=True)
    assert "done" in both and "skipped" in both

    captured = {}

    def fake_get(table, params=None, **k):
        if table == "project_tasks" and params and "order" in params:
            captured["params"] = params
        if table == "projects":
            return [{"project_id": "p1", "name": "Office", "user_id": "u"}]
        return []

    monkeypatch.setattr(pr, "get", fake_get)
    auth_client.get("/projects/p1/tasks")
    assert "status" in captured.get("params", {}), "the list has no status filter"
    assert "skipped" in captured["params"]["status"]


def test_project_progress_excludes_binned_work(auth_client, monkeypatch):
    """A completion percentage that counts tasks the user has explicitly put
    in the bin is reporting on work that no longer exists.

    Driven through the route rather than by reading the source for a
    literal: the select string it used to grep for changed the moment the
    card started showing due dates, and the test failed while the
    behaviour it guards was untouched.
    """
    import routes.projects as pr
    captured = {}

    def fake_get(table, params=None, **k):
        if table == "projects":
            return [{"project_id": "p1", "name": "Office", "user_id": "u"}]
        if table == "project_tasks":
            captured["params"] = params or {}
        return []

    monkeypatch.setattr(pr, "get", fake_get)
    assert auth_client.get("/projects").status_code == 200
    status = captured.get("params", {}).get("status", "")
    assert status, "the count query has no status filter at all"
    for binned in pr._PT_TRASHED_STATUSES:
        assert binned in status, f"{binned} work still counts in the denominator"


def test_day_board_shows_quick_bucket_items_for_that_day(auth_client, monkeypatch):
    """Reported: bucket items never appeared on the Day Board.

    They could not — the board read daily_events, todo_matrix and
    checklist_items, and never looked at quick_bucket at all. So anything
    captured in the bucket, which is most of what actually gets typed on a
    given day, was invisible on the screen meant to show the day.

    The FUTURE bucket is deliberately still excluded: that is the backlog,
    and this board's premise is one day on one screen. /backlog is for those.
    """
    from datetime import timedelta
    import re
    import routes.day_board as db
    from utils.user_tz import user_today
    today = user_today()

    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "get", lambda t, params=None, **k: ([
        {"id": "1", "text": "Due at three", "time_bucket": "3h", "is_done": False,
         "due_at": today.isoformat() + "T15:00:00+00:00"},
        {"id": "2", "text": "Do it now", "time_bucket": "now",
         "is_done": False, "due_at": None},
        {"id": "3", "text": "Someday backlog", "time_bucket": "future",
         "is_done": False, "due_at": None},
        {"id": "4", "text": "Due tomorrow", "time_bucket": "5h", "is_done": False,
         "due_at": (today + timedelta(days=1)).isoformat() + "T09:00:00+00:00"},
        {"id": "5", "text": "Already ticked", "time_bucket": "now",
         "is_done": True, "due_at": None},
        {"id": "6", "text": "Finished in May", "time_bucket": "now",
         "is_done": True, "due_at": None, "done_at": "2026-05-11T02:19:58"},
        {"id": "7", "text": "Finished today", "time_bucket": "now",
         "is_done": True, "due_at": None,
         "done_at": today.isoformat() + "T09:12:00"},
    ] if t == "quick_bucket" else []))

    html = auth_client.get("/day-board").get_data(as_text=True)
    assert "Due at three" in html          # a deadline today
    assert "Do it now" in html             # undated, and today is today
    assert "Already ticked" in html        # done, struck out rather than hidden
    assert "Someday backlog" not in html, "the backlog leaked onto the board"
    assert "Due tomorrow" not in html, "another day's deadline is not today's"

    # ── FINISHED WORK BELONGS TO THE DAY IT WAS FINISHED ──────────────
    # A "now" row carries no date, so every one ever created landed on
    # every board forever. Measured on real data 2026-08-23: 61 rows in To
    # do, 53 of them closed in May and July. The COUNT filtered done, so it
    # said 8 while the list underneath was 87% archive — reported as "it
    # does not take into account completed tasks".
    assert "Finished in May" not in html, "months-old work is still on today's board"
    assert "Finished today" in html, "what you got through today is today's business"

    # Done rows are struck out, consistent with every other row on the board.
    seg = html[max(0, html.find("Already ticked") - 500):html.find("Already ticked")]
    m = None
    for m in re.finditer(r'<li class="([^"]*)"', seg):
        pass
    assert m and "done" in m.group(1)

    # A "now" item carries no date, so it is not a past day's business.
    past = auth_client.get("/day-board?date=2020-01-01").get_data(as_text=True)
    assert "Do it now" not in past


# ── TIME ANNOUNCER: behaviour, not source strings ──────────────────────
def test_time_announcer_scheduling_behaviour():
    """Run the announcer module and assert what it actually does.

    Reported 2026-08-22: "announce the time why 15 min, 30 min, 45 min,
    60 min is not working". 45 was never an option, and the speaking path
    had no error handler, no voice priming and a cancel()-then-speak() in
    one task, which Chrome drops. None of that was visible to the source
    assertions above it.
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", "tests/js/time_announcer.test.js"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


def test_the_roadmap_says_what_is_late():
    """The roadmap's date maths, run against the shipped file.

    Reported 2026-10-04: these pages needed to be usable on a phone. Two
    things were wrong on this one and both are date logic, so both are
    checked here rather than by eye:

    - The page never said whether a row was late. Every block rendered
      identically, so a task three weeks overdue looked like one due next
      month. The block labels now carry "3 days late" / "Today" /
      "in 2 weeks", computed from each block's own date against the
      user's timezone.
    - Rescheduling was HTML5 drag-and-drop ONLY, which fires no events at
      all on a touch screen, so the page was read-only on a phone. The
      reschedule sheet offers Today / Tomorrow / Next Monday / In a week,
      and "Next Monday" has to be strictly in the future on all seven
      weekdays — the off-by-one there would silently schedule work into
      the past on a Monday.

    Month ends, year ends and a leap day are included because the helper
    does its arithmetic in UTC to avoid a DST shift moving a date by one.
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", "tests/js/timeline_dates.test.js"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


# ── THE CHAIN (services/streak.py) ─────────────────────────────────────
# Asked for 2026-08-22: "can you gamify something which will make me
# motivated". Calibrated against the real numbers, which were 9 checklist
# ticks out of 926 due over 60 days — so the bar is low and the streak
# does not die at midnight. Both of those are load-bearing, hence tests.

def _streak_with(monkeypatch, per_day):
    """Stub every source so `per_day` is what each day's tally becomes."""
    from services import streak as st

    def fake_get(table, params=None, **kw):
        if table != "checklist_ticks":
            return []
        col = "tick_date"
        return [{col: d} for d, n in per_day.items() for _ in range(n)]

    monkeypatch.setattr(st, "get", fake_get)
    return st


def test_chain_counts_back_from_today_when_today_qualifies(monkeypatch):
    import datetime as dtm
    st = _streak_with(monkeypatch, {"2026-08-22": 6, "2026-08-21": 5,
                                    "2026-08-20": 9})
    r = st.compute("u", dtm.date(2026, 8, 22))
    assert r["ok"] and r["met"] and r["streak"] == 3


def test_chain_survives_a_morning_with_nothing_done_yet(monkeypatch):
    """The streak must NOT read 0 every morning until you have done five
    things. It counts back from yesterday while yesterday still qualifies —
    a chain that resets at midnight is a nag, not a chain.
    """
    import datetime as dtm
    st = _streak_with(monkeypatch, {"2026-08-21": 7, "2026-08-20": 7})
    r = st.compute("u", dtm.date(2026, 8, 22))
    assert r["today"] == 0 and r["met"] is False
    assert r["streak"] == 2, "the streak died at midnight"


def test_chain_breaks_only_after_a_whole_day_under_the_bar(monkeypatch):
    import datetime as dtm
    st = _streak_with(monkeypatch, {"2026-08-21": 1, "2026-08-20": 9,
                                    "2026-08-19": 9})
    r = st.compute("u", dtm.date(2026, 8, 22))
    assert r["streak"] == 0
    assert r["best"] == 2, "the earlier run should still be the best"


def test_chain_never_raises_and_never_breaks_the_board(monkeypatch):
    """A broken game is not an outage. The board renders regardless."""
    import datetime as dtm
    from services import streak as st

    def boom(*a, **k):
        raise RuntimeError("postgrest is down")

    monkeypatch.setattr(st, "get", boom)
    r = st.compute("u", dtm.date(2026, 8, 22))
    assert r["ok"] is False and r["streak"] == 0


def test_chain_says_something_true_when_there_is_no_history(monkeypatch):
    import datetime as dtm
    st = _streak_with(monkeypatch, {})
    r = st.compute("u", dtm.date(2026, 8, 22))
    assert r["line"] and str(r["window"]) in r["line"]


def test_day_board_phone_layout_lets_the_page_scroll():
    """The no-scroll contract is right for a desk monitor and wrong for a
    phone: three panels crushed into 640px is unreadable or truncated to
    "+11 more". Below 720px the page scrolls and the fit pass stands down.
    """
    html = open("templates/day_board.html", encoding="utf-8").read()
    assert "@media (max-width: 720px)" in html
    assert "function isPhone()" in html and "function phoneU()" in html
    # .rail is height:100%, which collapses to zero once the page may grow.
    assert ".panel.cal .body{height:" in html, \
        "the timeline has no explicit height on a phone and will vanish"


# ── 2026-08-22 round three: highlight, phone truncation, iOS install ───
def test_announcer_interval_buttons_can_actually_highlight():
    """Reported: "15m, 30m, 45m, 60m not getting highlighted".

    paint() had always set .on on the right button. The STYLE for .on was
    scoped to `.ta-row button.on`, and the interval buttons live in
    `.ta-int` — so the class landed on an element no rule could reach.
    A selector that styles nothing is the hardest kind of dead code to see.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert ".ta-int button.on" in js, "the selected interval cannot highlight"
    # ...and the buttons need their base look from the same shared rule.
    assert ".ta-row button,.ta-int button{" in js


def test_announcer_says_that_it_autosaves():
    """Asked: "is there a save button or it is autosaved?"

    It always autosaved. Nothing said so, and silent persistence is
    indistinguishable from none — which is why the question came up.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "data-ta-saved" in js and "savedFlash" in js
    assert "saves as you type" in js
    # A confirmation that fires for some controls and not others teaches
    # people to distrust it, so every control that persists must flash.
    assert js.count("savedFlash();") >= 4, \
        "some controls save without confirming it"
    # And a standing read-back of what is actually stored — the flash proves
    # the last keystroke landed, this proves the SETTING did, which is the
    # question that was asked.
    assert "data-ta-now" in js and "Saved & running: " in js


def test_day_board_phone_breakpoint_is_declared_once():
    """CSS owns the breakpoint; JS reads it back.

    The first version tested `max-width: 720px` in a matchMedia call AND in
    a media query. Two copies of a breakpoint are one breakpoint and one
    future bug — they drift the first time either is tuned.
    """
    html = open("templates/day_board.html", encoding="utf-8").read()
    assert "--phone: 0;" in html and "#board{--phone:1}" in html
    assert 'getPropertyValue("--phone")' in html
    # A landscape phone is short, not narrow: 390px of height sends the fit
    # pass to its floor and then truncates half the day.
    assert "(max-height: 560px)" in html


def test_day_board_does_not_clamp_titles_on_a_phone():
    """The two-line clamp is right on a fixed-height board and wrong on one
    that scrolls — there it hides words for nothing, and "truncated on
    mobile" means that as much as it means a shortened list."""
    html = open("templates/day_board.html", encoding="utf-8").read()
    assert "-webkit-line-clamp:none" in html


def test_ios_install_hint_detects_ipados():
    """iPadOS 13+ reports itself as "Macintosh". Without the touch-point
    check an iPad never sees the hint — on the one platform where the hint
    IS the only way to install."""
    js = open("static/js/pwa.js", encoding="utf-8").read()
    assert "maxTouchPoints" in js and "MacIntel" in js
    assert "dpShowInstallHelp" in js, "no on-demand route to the steps"


def test_settings_explains_ios_install(auth_client):
    html = auth_client.get("/settings").get_data(as_text=True)
    assert "Add to Home Screen" in html
    assert "dpShowInstallHelp" in html


def test_session_outlives_a_week_for_installed_apps():
    """An installed iOS PWA has its own cookie jar, so a 7-day session meant
    signing in again about weekly on the phone — the single thing that makes
    an installed PWA feel broken and stop being opened."""
    import datetime as dtm
    from settings import BaseConfig
    assert BaseConfig.PERMANENT_SESSION_LIFETIME >= dtm.timedelta(days=30)


def test_keepalive_track_is_long_enough_for_a_lock_screen_notification():
    """Reported: "keep going when minimised is checked, but pause button not
    appearing in the lock screen".

    Chrome does not create a media notification for media shorter than about
    five seconds — it classifies short clips as sound effects rather than
    playback. The track was ONE second. Audio focus was held either way, so
    the page stayed awake and the announcements worked; there were simply no
    controls anywhere, which is the hardest kind of half-working.
    """
    import wave
    with wave.open("static/audio-keepalive.wav", "rb") as w:
        seconds = w.getnframes() / float(w.getframerate())
    assert seconds >= 10, (
        f"keep-alive is {seconds:.1f}s; Chrome will not show lock-screen "
        "controls for anything under ~5s"
    )
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # Metadata set once playback has really started: play() is async, and a
    # session described while the element is still loading gets discarded.
    # The media session is described once playback has really started —
    # play() is async and a session described mid-load is discarded. The
    # call now sits inside the "playing" handler alongside the flag that
    # tracks real playback, so this asserts the pairing rather than one
    # exact call form.
    assert 'addEventListener("playing"' in js and "setMediaSession()" in js
    # A blocked play() must not be swallowed — that is how "keep going when
    # minimised" ends up ticked and doing nothing. The wording changed when
    # the message started saying what to DO about it, so this asserts the
    # message exists and names the remedy rather than one exact sentence.
    assert "keep-alive audio is blocked until you tap" in js


def test_announcer_supports_multiple_named_announcements_with_dates():
    """Asked 2026-08-23: several announcements, each with its own text, an
    optional date, and its own stop.

    The behaviour is exercised for real in tests/js/time_announcer.test.js
    (13 assertions covering undated-repeats-daily, dated-fires-once,
    never-before, never-after, individually-stopped, two-at-once, and the
    already-said guard). These pin the parts that live in the UI.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # Each announcement is its own record, not a shared label over a time list.
    assert "state.items" in js and "function dueItems" in js
    # A date window. The single optional-date field this originally checked
    # for became a start/end pair when recurrence landed, so the assertion
    # follows the feature rather than pinning a field name that moved.
    assert "function isYMD" in js
    assert "data-ta-new-start" in js and "data-ta-new-end" in js
    # Its own on/off switch, separate from the global stop.
    assert "data-ta-toggle" in js and "if (!it.on) continue" in js
    # An expired one-off is SHOWN as expired rather than silently kept —
    # a dead row that still looks armed is worse than no row.
    assert "expired" in js
    # Several landing on the same minute are combined into one utterance
    # rather than queued, or they talk over each other.
    assert "parts.join" in js
    # The old settings must survive the upgrade.
    assert "MIGRATION" in js


def test_announcer_panel_close_and_inside_click_guards_are_present():
    """The source half of the delete-closes-the-panel fix, and of the modal.

    Kept separate from the jsdom test below so it REPORTS as passing rather
    than being swallowed by that test's skip — a guard that silently does not
    run is the thing this whole file keeps learning about.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # It is a MODAL now, so there is no outside-click listener left to be
    # fooled by a detached node — the delete bug cannot recur because the
    # mechanism that caused it is gone. What must not come back is a
    # document-level click handler that hides the panel.
    assert 'aria-modal", "true"' in js, "the panel is not a modal"
    assert "ta-backdrop" in js
    assert "function closePanel" in js and "function openPanel" in js
    # A handled click still stops propagating, so nothing downstream can act
    # on a row this function is about to remove.
    assert "ev.stopPropagation()" in js
    # The close control that was missing entirely.
    assert "data-ta-close" in js
    # Only a deliberate press ON the backdrop closes it. Using "click" here
    # would reintroduce exactly the reported bug: a drag that starts inside
    # and finishes outside fires a click whose target is the page.
    assert 'backdrop.addEventListener("mousedown"' in js, \
        "a drag ending outside will close the dialog again"


def test_announcer_recurrence_rules():
    """Asked 2026-08-23: daily / weekly / once / monthly / yearly / custom
    days per announcement, with a start and an end.

    The rules are exercised for real in tests/js/time_announcer.test.js —
    35 assertions including the two clamping cases that decide whether a
    reminder fires at all in a short month. These pin that the pieces exist.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    for rule in ("once", "daily", "weekly", "monthly", "yearly", "custom"):
        assert '"' + rule + '"' in js, f"{rule} recurrence missing"
    assert "function matchesOn" in js
    # The window. `start` defaults to today; `end` null means forever.
    assert "it.start" in js and "it.end" in js
    # THE CLAMPS. A monthly reminder set on the 31st must still fire in
    # February, and a yearly one on 29 Feb must fire in a common year —
    # skipping is defensible and is not what someone setting a reminder
    # wants. Both are Math.min against the month's real length.
    assert "daysInMonth(t.y, t.m)" in js, "monthly does not clamp to short months"
    assert "daysInMonth(t.y, s.m)" in js, "yearly does not clamp 29 February"
    # Two states that would create a row that looks armed and never fires.
    assert "the end date is before the start date" in js
    assert "pick at least one day" in js


def test_announcer_panel_survives_its_own_delete():
    """Reported 2026-08-23: "if i delete something it goes to home page."

    It was not navigating — the panel was closing itself, leaving the page
    behind it on screen. Deleting rebuilds the list with innerHTML, which
    DETACHES the clicked button, and the outside-click listener then ran
    closest(".ta-pop") on a node no longer in the document, got null, and
    concluded the click had been outside the panel.

    Reproducing it FULLY needs a real DOM, so the behavioural half runs under
    jsdom and skips where jsdom is absent (it is not a repo dependency —
    `npm i jsdom` in the repo root enables it). The source guards below run
    everywhere, because a test that only runs on one machine protects only
    that machine.
    """
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    r = subprocess.run(["node", "tests/js/ta_panel.test.js"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


def test_announcer_supports_a_daily_time_window():
    """Asked 2026-08-23, clarified as TIME rather than date: "start at and
    ends at timing so that based on recurring option and time it can
    announce".

    One announcement can now speak repeatedly through the day between two
    times — 8am to 8pm every 60 minutes is one row, not thirteen. The slot
    arithmetic is exercised in tests/js/time_announcer.test.js.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "function slotsFor" in js
    assert "data-ta-new-until" in js and "data-ta-new-mins" in js
    # Each slot settles on its own, or the first announcement of the day
    # would silence the rest of the window.
    assert 'minsToHHMM(slots[k])' in js, "slots share one key and will silence each other"
    # Half a window is always a mistake, so it is refused rather than guessed.
    assert "add how often to repeat between those times" in js
    assert "add a time to repeat until" in js
    # A step of 1 across a whole day is 1440 slots; anything past that is a
    # bug rather than a schedule.
    assert "out.length < 1441" in js, "no bound on the generated slot list"


def test_announcer_has_an_am_pm_chooser():
    """Asked 2026-08-23: "i will manually enter time but provide facility to
    choose am or pm."

    The chooser supplies the meridiem only when the typed text does not —
    typing "5pm" or "17:00" beats clicking, and the buttons grey out to say
    so. Precedence is exercised in tests/js/time_announcer.test.js.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert 'data-ta-mer="at"' in js and 'data-ta-mer="until"' in js, \
        "no AM/PM control on both time fields"
    assert "function merApplies" in js
    # Only a bare 1-12 is ambiguous; 0 and 13-23 are already 24-hour and the
    # chooser must not override them.
    assert "h >= 1 && h <= 12" in js, "the chooser will override a 24-hour time"
    # A control that cannot affect the result must not look like it can.
    assert '"moot"' in js
    # And the resolved time is shown as it is typed, so nothing is guessed.
    assert "data-ta-preview" in js


def test_push_scheduler_skips_muted_items():
    """Asked 2026-08-23: "per item notification mutes ... is needed."

    A muted item KEEPS its reminder times and simply does not push, so
    unmuting restores the exact schedule. That is the whole difference from
    the old advice, which was to delete the times.
    """
    src = open("services/push_scheduler.py", encoding="utf-8").read()
    assert 'it.get("notify_muted")' in src, "the scheduler ignores mutes"
    # Filtered in PYTHON, not in the PostgREST query. get() has no PGRST204
    # retry, so naming a column the live database has not got yet would 400
    # and silence every reminder for everyone until the migration is run.
    assert "notify_muted" not in src.split("items = get(")[1].split(") or []")[0], \
        "the mute filter is in the query and will 400 before the migration"


def test_checklist_mute_api_exists_and_never_deletes_times():
    routes = open("routes/checklist.py", encoding="utf-8").read()
    assert '"/api/checklist/mutes"' in routes
    assert '"/api/checklist/mutes/<item_id>"' in routes
    # It sets a flag. If this ever becomes a delete of reminder_times, the
    # mute stops being reversible and becomes destructive.
    #
    # The ARGUMENT ORDER is asserted too, and not idly: update() takes
    # (table, FILTERS, PAYLOAD), the payload was passed first, and the
    # resulting ValueError was caught by the route's own except and
    # returned as a plausible "migration may not have been run yet". The
    # switch failed for days behind an error message that sounded right.
    # The earlier version of this assertion passed throughout, because it
    # only checked the payload dict appeared SOMEWHERE in the call.
    assert '}, {"notify_muted": muted})' in routes, \
        "update() is being called payload-first and will always fail"
    assert "checklist_reminder_times" not in routes.split(
        "def set_checklist_mute")[1].split("def ")[0], \
        "muting is touching the reminder times themselves"


def test_announcer_mute_switch_is_reversible_in_the_ui():
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "data-ta-mute" in js and "function toggleMute" in js
    # Loaded only when the dialog opens: this file runs on every page and
    # must not add a request to every page load.
    assert "loadMutes()" in js and "mutesState" in js
    # An optimistic switch that fails must go back, or it lies about saving.
    assert "row.muted = !want;" in js


def test_announcer_mutes_migration_is_additive_and_rerunnable():
    sql = open("MIGRATION_ANNOUNCER_MUTES.sql", encoding="utf-8").read().upper()
    assert "ADD COLUMN IF NOT EXISTS NOTIFY_MUTED" in sql
    assert "DEFAULT FALSE" in sql, "existing items would default to muted"
    assert "DROP" not in sql, "a migration for a new flag should drop nothing"


# ── ANNOUNCEMENTS SYNC TO THE SERVER ───────────────────────────────────
def test_announcer_state_degrades_instead_of_erroring(auth_client, monkeypatch):
    """Before MIGRATION_ANNOUNCER_SYNC.sql is run the tables do not exist.

    That must be a DEGRADED read — the panel keeps working from its local
    cache — rather than a 500 that looks like a broken app. It must also
    not be silent: the announcer is the feature people notice stopping.
    """
    import routes.announcer as an

    def missing(*a, **k):
        raise RuntimeError("404 Client Error: Not Found")

    monkeypatch.setattr(an, "get", missing)
    r = auth_client.get("/api/announcer/state")
    assert r.status_code == 503, r.status_code
    assert r.get_json()["ok"] is False


def test_announcer_state_returns_the_client_shape(auth_client, monkeypatch):
    """The stored columns must come back in the exact shape the browser
    already uses, or the sync silently replaces every announcement with a
    malformed one."""
    import routes.announcer as an

    rows = [{
        "client_id": "i1-123", "at_time": "08:00", "until_time": "20:00",
        "every_mins": 60, "repeat_rule": "custom", "days": [1, 3],
        "start_date": "2026-08-01", "end_date": None,
        "say_text": "Drink water", "is_on": True,
    }]
    monkeypatch.setattr(an, "get", lambda t, *a, **k:
                        rows if t == "announcer_items" else
                        [{"every_mins": 45, "label": "Stretch"}])
    body = auth_client.get("/api/announcer/state").get_json()
    assert body["every"] == 45 and body["label"] == "Stretch"
    it = body["items"][0]
    assert it == {
        "id": "i1-123", "at": "08:00", "until": "20:00", "mins": 60,
        "repeat": "custom", "days": [1, 3], "start": "2026-08-01",
        "end": None, "text": "Drink water", "on": True,
    }


def test_announcer_rejects_an_announcement_that_could_never_fire(monkeypatch):
    """A bad repeat rule would be stored and then never match a day, which
    is worse than refusing it — the row sits there looking armed."""
    import routes.announcer as an
    assert an._clean({"id": "x", "at": "09:00", "repeat": "fortnightly"})[
        "repeat_rule"] == "daily"
    assert an._clean({"id": "x", "at": "nonsense"}) is None
    assert an._clean({"id": "x", "at": "09:00", "mins": 99999})["every_mins"] == 720
    assert an._clean({"id": "x", "at": "09:00", "days": [9, 1, 1, -2]})["days"] == [1]


def test_announcer_delete_is_soft(monkeypatch):
    src = open("routes/announcer.py", encoding="utf-8").read()
    assert '{"is_deleted": True}' in src, "announcements are being hard deleted"
    assert "sb_delete" not in src and "delete(" not in src.replace(
        "def delete_item", "")


def test_announcer_writes_are_idempotent_upserts():
    """A phone on a flaky connection retries. Without on_conflict every retry
    creates a duplicate announcement, and the original becomes unreachable."""
    src = open("routes/announcer.py", encoding="utf-8").read()
    assert "on_conflict=user_id,client_id" in src
    assert "on_conflict=user_id" in src
    assert "resolution=merge-duplicates" in src
    sql = open("MIGRATION_ANNOUNCER_SYNC.sql", encoding="utf-8").read().lower()
    # The upsert target must actually be unique or on_conflict cannot work.
    assert "create unique index" in sql and "(user_id, client_id)" in sql


def test_announcer_sync_keeps_runtime_state_local():
    """Mode, keep-alive and the said-marks must NOT sync. Pausing on the
    phone must not silence the laptop you are sitting at, and a synced
    `said` would mean the first device to speak silences all the others."""
    src = open("routes/announcer.py", encoding="utf-8").read()
    for local in ("keepalive", '"said"', "lastSlot"):
        assert local not in src, f"{local} is being synced and should not be"
    sql = open("MIGRATION_ANNOUNCER_SYNC.sql", encoding="utf-8").read().lower()
    assert "keepalive" not in sql and "last_slot" not in sql


def test_announcer_first_sync_does_not_wipe_existing_local_schedule():
    """Someone upgrading has announcements in localStorage and nothing on the
    server. Overwriting theirs with the empty server list is the one outcome
    that must not happen."""
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "if (!j.items.length && state.items.length)" in js, \
        "an upgrade will wipe the schedule already on the device"


def test_announcements_and_reminders_can_be_edited():
    """Asked 2026-08-23: "should be able to edit notifications."

    Both lists in the dialog were add-only: changing an announcement meant
    deleting it and retyping every field, and changing a reminder's times
    meant leaving for the Checklist page. Behaviour is exercised in
    tests/js/ta_panel.test.js; these pin the pieces.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()

    # ONE form does both add and edit. A separate edit dialog would
    # duplicate every field and every validation rule, and they would drift.
    assert "var editingId = null;" in js
    assert "function startEdit" in js and "function cancelEdit" in js
    assert 'editingId ? "Save" : "Add"' in js, "the form does not say which job it is doing"

    # Editing replaces IN PLACE, keeping the id — so the server sees an
    # update rather than a delete plus an insert, and the on/off state
    # (which is not part of the form) survives.
    assert "x.id === editingId ? updated : x" in js
    assert "on: was ? was.on : true" in js, "editing resets the on/off switch"
    # Its slots have moved, so the already-said marks are about times that
    # may no longer exist.
    assert "delete state.said[editingId]" in js

    # Reminder times are edited through the EXISTING checklist PATCH, which
    # already diffs desired against stored, preserves ticks for times that
    # survive, and keeps the legacy single-time column in step. A second
    # implementation here would be a second source of truth.
    assert "function saveMuteTimes" in js
    assert '"/api/checklist/items/" + encodeURIComponent(id)' in js
    assert '"PATCH"' in js
    assert "reminder_times: times" in js
    # An optimistic edit that fails must go back, not lie about saving.
    assert "row.times = before;" in js


def test_no_supabase_update_is_called_payload_first():
    """update(table, FILTERS, PAYLOAD). Passing the payload second raises a
    ValueError, which routes with a try/except turn into a 500 that sounds
    like something else entirely.

    That is exactly what happened: the mute switch and the announcement
    delete both shipped with the arguments the wrong way round, and the
    failure surfaced as "MIGRATION_ANNOUNCER_MUTES.sql may not have been run
    yet" — a message that was wrong and completely believable. A whole-repo
    sweep is cheap and this class of bug is invisible in review.
    """
    import pathlib
    import re
    suspect = []
    for f in sorted(pathlib.Path(".").glob("**/*.py")):
        if "node_modules" in str(f) or f.name.startswith("test_"):
            continue
        src = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'\bupdate\(\s*"([a-z_]+)"\s*,\s*\{(.{0,140}?)\}',
                             src, re.S):
            # A filter value carries a PostgREST operator; a payload does not.
            if not re.search(r'"(eq|gt|lt|gte|lte|neq|in|is|not)\.',
                             m.group(2)):
                line = src[:m.start()].count("\n") + 1
                suspect.append(f"{f}:{line} update({m.group(1)!r}, ...)")
    assert not suspect, "payload passed as the filter argument:\n" + \
        "\n".join(suspect)


def test_user_guide_is_reachable_from_inside_the_app(auth_client):
    """A guide nobody can find is a guide nobody reads.

    Linked from the avatar menu (where people already go for Settings) and
    from Settings itself. The URL is a config value, not a literal in two
    templates, so moving it is one edit — and it can be pointed elsewhere
    per environment without a code change.
    """
    from settings import BaseConfig
    url = BaseConfig.USER_GUIDE_URL
    assert url.startswith("https://"), url

    nav = open("templates/_top_nav.html", encoding="utf-8").read()
    assert "config.USER_GUIDE_URL" in nav, "not linked from the avatar menu"
    # An external link opened in a new tab needs noopener, or the opened page
    # gets a handle on this one through window.opener.
    assert 'rel="noopener noreferrer"' in nav

    html = auth_client.get("/settings").get_data(as_text=True)
    assert url in html, "not linked from Settings"
    assert "Open the user guide" in html


# ── ANNOUNCEMENTS REACH A LOCKED PHONE ─────────────────────────────────
def _ann(**kw):
    base = {"client_id": "i1", "at_time": "08:00", "until_time": None,
            "every_mins": 0, "repeat_rule": "daily", "days": [],
            "start_date": "2026-08-01", "end_date": None, "say_text": "",
            "is_on": True, "is_deleted": False, "notify": True}
    base.update(kw)
    return base


def test_announcement_push_rules_match_the_javascript():
    """Reported 2026-08-23: announcements do not work on a locked screen.

    They cannot — browsers suspend speech when the screen is off, which no
    application can change. So each announcement also fires as a PUSH,
    which does reach a locked phone.

    That means the recurrence rules now exist twice, in JavaScript and in
    Python. If they ever disagree the user hears one thing and reads
    another, so these are the same cases tests/js/time_announcer.test.js
    runs, asserted against the Python side.
    """
    import datetime as dtm
    from services import announcer_push as ap

    sunday = dtm.date(2026, 8, 23)
    assert ap.matches_on(_ann(), sunday)
    assert ap.matches_on(_ann(repeat_rule="once", start_date="2026-08-23"), sunday)
    assert not ap.matches_on(_ann(repeat_rule="once", start_date="2026-08-22"), sunday)
    assert ap.matches_on(_ann(repeat_rule="weekly", start_date="2026-08-16"), sunday)
    assert not ap.matches_on(_ann(repeat_rule="weekly", start_date="2026-08-17"), sunday)
    # The client uses Sun=0; Python's weekday() is Mon=0. That conversion is
    # exactly the kind of thing that silently fires on the wrong day.
    assert ap.matches_on(_ann(repeat_rule="custom", days=[0]), sunday)
    assert not ap.matches_on(_ann(repeat_rule="custom", days=[1]), sunday)
    # Both clamps, which decide whether a reminder happens at all in a
    # short month or a common year.
    assert ap.matches_on(_ann(repeat_rule="monthly", start_date="2026-01-31"),
                         dtm.date(2026, 2, 28))
    assert ap.matches_on(_ann(repeat_rule="yearly", start_date="2024-02-29"),
                         dtm.date(2027, 2, 28))
    assert not ap.matches_on(_ann(end_date="2026-08-22"), sunday)


def test_announcement_push_slots_match_the_javascript():
    from services import announcer_push as ap
    assert ap.slots_for(_ann()) == [480]
    assert ap.slots_for(_ann(until_time="12:00", every_mins=60)) == [
        480, 540, 600, 660, 720]
    # A reversed window must not loop; it degrades to a single slot.
    assert ap.slots_for(_ann(until_time="06:00", every_mins=30)) == [480]
    # And the list is bounded, exactly as the client bounds it.
    assert len(ap.slots_for(_ann(at_time="00:00", until_time="23:59",
                                 every_mins=1))) <= 1441


def test_announcement_push_respects_the_switches(monkeypatch):
    import datetime as dtm
    from zoneinfo import ZoneInfo
    from services import announcer_push as ap

    now = dtm.datetime(2026, 8, 23, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert ap.due_now([_ann()], now)
    assert not ap.due_now([_ann(is_on=False)], now), "a stopped one still pushed"
    assert not ap.due_now([_ann(notify=False)], now), "opt-out ignored"
    assert not ap.due_now([_ann(is_deleted=True)], now)
    # An ABSENT notify column must read as True, so this keeps working
    # before MIGRATION_ANNOUNCER_PUSH.sql is run.
    no_col = {k: v for k, v in _ann().items() if k != "notify"}
    assert ap.due_now([no_col], now)
    # The grace window: a minute late still fires, five minutes does not,
    # so a restart cannot replay the morning.
    assert ap.due_now([_ann()], now.replace(minute=2))
    assert not ap.due_now([_ann()], now.replace(minute=5))


def test_announcement_push_failure_cannot_stop_checklist_reminders():
    """The announcement block sits in its own try inside the scheduler.

    Checklist reminders are the notifications with an actual deadline; a
    missing table or a bad row in the newer feature must not take them
    down with it.
    """
    src = open("services/push_scheduler.py", encoding="utf-8").read()
    block = src.split("announcer_push.fires_for_user")[0]
    assert block.rstrip().endswith("try:") or "try:" in block[-400:], \
        "the announcement push is not wrapped in its own try"
    assert "announcement push skipped" in src


def test_announcement_push_claim_is_unique_per_slot():
    """Several gunicorn workers tick at the same second. Without a unique
    index they all insert and the phone buzzes four times."""
    sql = open("MIGRATION_ANNOUNCER_PUSH.sql", encoding="utf-8").read().lower()
    assert "create unique index" in sql
    assert "(user_id, client_id, fire_date, fire_time)" in sql, \
        "the claim is not keyed per SLOT; a windowed announcement fires once a day"
    assert "add column if not exists notify" in sql


def test_announcer_panel_shows_the_list_and_hides_the_rest():
    """Reported twice: "UX is not friendly", then "very clumsy, cluttered
    and hard to navigate".

    The panel had accumulated one control at a time across a day and ended
    up showing everything at once: three status lines, four tabs, a
    seven-field form and eight paragraphs.

    The rebuild follows one rule — show the LIST, hide everything else.
    Opening this panel is almost always about seeing or changing an
    announcement.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    for pane in ("items", "clock", "notify", "device", "diag"):
        assert 'data-ta-pane="' + pane + '"' in js

    # THE FORM IS HIDDEN until asked for, so the resting state is a list
    # rather than a form nobody requested. This is the biggest single
    # change and the one the complaint was really about.
    assert "data-ta-form" in js and "data-ta-new>" in js
    assert "function openForm" in js and "function closeForm" in js

    # TABS ARE GONE. A tab hides its contents completely, so you had to
    # open all four to see what was configured. Collapsed rows state their
    # VALUE on the summary line instead.
    assert "data-ta-tab=" not in js, "tabs are back"
    assert "ta-fold" in js
    for summary in ("data-ta-sum-clock", "data-ta-sum-notify",
                    "data-ta-sum-device", "data-ta-build-sum"):
        assert summary in js, f"{summary} does not state its value"

    # DIAGNOSTICS ARE NOT SETTINGS. They answer "why did nothing happen",
    # which is a different question from "what should happen", and mixing
    # them is most of why this felt cluttered.
    diag = js.split('data-ta-pane="diag"')[1]
    for probe in ("data-ta-health", "data-ta-hold", "data-ta-fire",
                  "data-ta-build"):
        assert probe in diag, f"{probe} is not in the diagnostics section"

    # The master controls and the status line stay outside every fold —
    # they are what the panel is opened to check.
    head = js.split('data-ta-pane="items"')[0]
    assert 'data-ta-mode="on"' in head, "Start/Pause/Stop got buried"
    assert "data-ta-now" in head, "the status line got buried"


def test_client_and_server_recurrence_rules_agree_exactly():
    """The recurrence rules exist in TWO languages, and this is what makes
    that safe.

    The client decides when to SPEAK; the server decides when to PUSH. They
    run independently — the client offline with no network, the server with
    no browser — so neither can call the other. What they must never do is
    DISAGREE: a reminder that speaks but never buzzes, or buzzes on the
    wrong day, is worse than one that does neither, because you stop
    trusting all of them.

    So this generates a few thousand (announcement, date) combinations,
    asks the JavaScript what it thinks, asks the Python, and fails on any
    difference. It covers every rule, both clamps, the window bounds, the
    Sun=0/Mon=0 weekday conversion, and month lengths across a leap year.
    """
    import datetime as dtm
    import json
    import shutil
    import subprocess
    import tempfile
    from services import announcer_push as ap

    if not shutil.which("node"):
        pytest.skip("node not installed")

    # Dates chosen to hit the awkward edges: month ends, February in a leap
    # and a common year, and a full week of weekdays.
    dates = []
    for iso in ("2026-01-31", "2026-02-27", "2026-02-28", "2026-03-01",
                "2026-03-30", "2026-03-31", "2026-04-30", "2027-02-28",
                "2028-02-28", "2028-02-29", "2028-03-01"):
        dates.append(iso)
    d0 = dtm.date(2026, 8, 17)          # a Monday
    dates += [(d0 + dtm.timedelta(days=i)).isoformat() for i in range(14)]

    starts = ["2026-01-29", "2026-01-30", "2026-01-31", "2024-02-29",
              "2026-08-17", "2026-08-23", None]
    rules = ["once", "daily", "weekly", "monthly", "yearly", "custom"]
    day_sets = [[], [0], [1, 3], [0, 6], [0, 1, 2, 3, 4, 5, 6]]
    ends = [None, "2026-08-20", "2028-01-01"]
    windows = [(None, 0), ("12:00", 60), ("12:00", 90), ("06:00", 30),
               ("23:59", 1)]

    cases = []
    for rule in rules:
        for start in starts:
            for days in (day_sets if rule == "custom" else [[]]):
                for end in ends:
                    for until, mins in windows:
                        cases.append({
                            "item": {
                                "at": "08:00", "until": until, "mins": mins,
                                "repeat": rule, "days": days,
                                "start": start, "end": end,
                            },
                            "dates": dates,
                        })

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cases, f)
        path = f.name
    r = subprocess.run(["node", "tests/js/rules_dump.js", path],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    js_out = json.loads(r.stdout)

    mismatches = []
    for case, js in zip(cases, js_out):
        it = case["item"]
        py_item = {
            "at_time": it["at"], "until_time": it["until"],
            "every_mins": it["mins"], "repeat_rule": it["repeat"],
            "days": it["days"], "start_date": it["start"],
            "end_date": it["end"],
        }
        py_slots = ap.slots_for(py_item)
        if py_slots != js["slots"]:
            mismatches.append(f"slots {it} -> py={py_slots} js={js['slots']}")
        for iso, js_m in zip(case["dates"], js["matches"]):
            py_m = ap.matches_on(py_item, dtm.date.fromisoformat(iso))
            if py_m != js_m:
                mismatches.append(f"{iso} {it} -> py={py_m} js={js_m}")

    checked = len(cases) * len(dates)
    assert not mismatches, (
        f"{len(mismatches)} of {checked} disagreed:\n" +
        "\n".join(mismatches[:15]))
    assert checked > 2000, f"only {checked} combinations checked"


def test_push_subscription_repairs_itself_on_load():
    """A push subscription dies on its own — rotated by the browser,
    invalidated by an OS update, or 410'd by the push service, after which
    the server correctly marks the row inactive.

    Nothing then brought it back. The browser still had a working
    subscription, the server believed it had none, and the interface went
    on showing notifications as enabled. Measured on 2026-08-23: six of
    seven subscriptions inactive, every one of them the phone. That is why
    the reminders stopped, and nobody could have known.
    """
    js = open("static/js/push.js", encoding="utf-8").read()
    assert "function healSubscription" in js or "healSubscription" in js
    # IT MUST NEVER PROMPT. The permission check has to come before any
    # subscribe call, or a page load produces a dialog nobody asked for.
    heal = js.split("async function healSubscription")[1].split("\n  }")[0]
    perm = heal.index('Notification.permission !== "granted"')
    assert perm < heal.index("pushManager.subscribe"), \
        "it may prompt for permission on page load"
    # The payload is NESTED under `subscription`; the server reads
    # data["subscription"] and a flat body 400s every time.
    assert "subscription: sub.toJSON()" in js
    # Throttled, so it is one small POST a day rather than one per page.
    assert "HEAL_EVERY_MS" in js
    # And it runs on load, not only when someone opens Settings.
    assert ".then(healSubscription)" in js


def test_a_rotated_subscription_is_re_registered_without_a_page_load():
    """Asked 2026-08-30: "this was enabled and it became disabled
    automatically after sometime \u2014 why?", with the announcer panel
    showing "this device is not registered with the server".

    The browser replaces a push subscription whenever it likes. Until now
    the ONLY thing that told the server about the new endpoint was
    push.js::healSubscription, which runs on page LOAD \u2014 so an app left
    open (a PWA, a pinned tab) drifted into "not registered" and stayed
    there. `pushsubscriptionchange` is the event that fires at the moment
    it happens, and there was no handler for it.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    assert 'addEventListener("pushsubscriptionchange"' in sw, \
        "a browser-rotated subscription reaches the server only on a page load"
    handler = sw.split('addEventListener("pushsubscriptionchange"')[1] \
                .split("\n});")[0]
    # It must REGISTER the replacement, nested the way the server reads it.
    assert "/api/push/subscribe" in handler
    assert "subscription: sub.toJSON()" in handler
    # ...and retire the endpoint it replaced, or the dead rows pile up
    # exactly as they did on the phone.
    assert "/api/push/unsubscribe" in handler
    assert "oldSubscription" in handler

    # The panel must repair itself too, and must not claim notifications
    # are ON before the server has answered \u2014 that flip, green tick to
    # orange warning a second later, is what read as "it turned itself off".
    ta = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "repairPush" in ta and "healSubscription" in ta
    granted = ta.split('if (st === "granted")')[1].split("} else if (st ===")[0]
    tick = granted.index("Notifications are on for this device")
    ok = granted.index('pushReach === "ok"')
    assert ok < tick, "the tick is shown before the reach is known"


def test_announcement_chime_is_real_audio_and_on_by_default():
    """Reported 2026-08-23: "audio notifications are not working".

    Three separate things were true. The server WAS sending (two fires
    logged that day). The phone had no active subscription, so nothing
    arrived there. And even when a notification does arrive, its SOUND
    belongs to the operating system — a web app cannot supply one.

    Speech cannot fill that gap: browsers suspend the Web Speech API with
    the screen off. MEDIA PLAYBACK is permitted there, which is the same
    fact the keep-alive already relies on. So an announcement plays a real
    audio file, and that is the only sound this app can make when locked.
    """
    import os
    import wave
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "function playChime" in js and "data-ta-chime" in js
    # ON by default: it is the only audible thing on a locked phone, so
    # defaulting it off would ship the reported bug.
    assert "chime: true" in js
    # A real <audio> element, not Web Audio — Web Audio is not treated as
    # playback and is exactly what a locked phone declines to run.
    # Slicing the function body broke as soon as neighbouring code moved.
    # These two facts are what matter and they are unambiguous in the file:
    # a real <audio> element (Web Audio is not treated as playback and is
    # exactly what a locked phone declines to run) pointed at a real file.
    # ONE ELEMENT for the chime and the words. Android unlocks an audio
    # element the first time it is played during a user GESTURE, and it
    # unlocks that ELEMENT rather than the page — so a second, never-tapped
    # element is refused forever on a locked screen. Measured exactly that
    # way: "chime played, speech: audio blocked".
    assert 'soundEl.id = "ta-sound"' in js
    assert '"/static/audio-chime.wav"' in js
    assert "function playThrough" in js
    assert 'soundEl = document.createElement("audio")' in js
    # ── ONE ELEMENT WAS THE OLD FIX; IT WAS THE WRONG HALF ────────────
    # A second element WAS the bug, because Android grants playback per
    # ELEMENT and one nobody ever tapped stays refused forever. Sharing one
    # element then produced the next failure: the chime ends, its handler
    # assigns a new src and calls play() again, and that second call is
    # refused mid-load — measured as "chime: played, speech: audio blocked,
    # rendered audio: cached".
    #
    # So the rule is not "one element". It is that every element used for
    # an announcement must be unlocked by the SAME gesture. Then neither
    # has to swap a source out from under a playing stream.
    assert "function unlockAudio" in js
    unlock = js.split("function unlockAudio")[1].split("\n  }")[0]
    assert "sound(), speechSound()" in unlock, \
        "an announcement element is not unlocked with the others"
    # Chime BEFORE speak, so it cannot wait behind a speech call that may
    # never start. Asserted on the ORDER of the two calls rather than on
    # the exact lines around them, which now carry the per-fire recording.
    # The words are now joined before the branch that chooses audio vs
    # speech, so the assertion follows the chime against whichever of the
    # two actually carries them.
    # The words now follow the chime's `ended` event on the same element,
    # so the ordering is structural rather than two calls in sequence.
    assert "playChime(function () {" in js
    # Sliced to the end of the callback, not to a character count: the
    # explanation inside this branch has grown three times now, and each
    # time a fixed window silently stopped covering the code it guards.
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]
    assert "playSpeech(words" in fire and "sayIt()" in fire, \
        "the words are not chained to the end of the chime"

    with wave.open("static/audio-chime.wav", "rb") as w:
        seconds = w.getnframes() / float(w.getframerate())
        rate = w.getframerate()
    assert 0.2 < seconds < 3, f"chime is {seconds:.2f}s"
    # Asked for the aeroplane seatbelt chime, which is a descending two-tone
    # with a long bell decay — it needs a real sample rate to sound like one
    # rather than like a beep, so the size bound accommodates that.
    assert rate >= 16000, "too low a sample rate for a bell tone"
    assert os.path.getsize("static/audio-chime.wav") < 80000


def test_announcer_never_picks_a_network_voice():
    """Reported 2026-08-23: "i used to get announcement with my text message
    also when the phone is locked. this is possible."

    Correct, and it was my regression. The original speak() set NO voice,
    so the platform used its own default — on Android a LOCAL, offline
    engine. I added "pick the first voice matching the language", which on
    Android is frequently a NETWORK voice. A network voice needs a live
    request at the moment of speaking, and a backgrounded page on a locked
    screen does not get one. It worked at the desk and silently stopped in
    a pocket.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    body = js.split("function speak(text, isRetry)")[1].split("\n  function ")[0]
    assert "localService" in body, "a network voice can be selected again"
    # And when no LOCAL voice exists, none is set at all — letting the
    # platform choose is precisely the behaviour that used to work.
    assert "x.localService" in body
    # One retry with no voice, because an unreachable voice is the likeliest
    # cause of both a refusal and an accepted-but-silent utterance.
    assert "noVoice = true" in body and "speak(text, true)" in body
    # The utterance is held, or Chrome can collect it mid-sentence.
    assert "speaking = u;" in body


def test_panel_warns_when_this_device_is_not_announcing():
    """Start/Pause/Stop is per-device by design — pausing on the phone must
    not silence the laptop. The cost is a trap: an announcement created on
    the phone SYNCS everywhere and then says nothing there, because Start
    was never pressed on the phone. The schedule looks right and the device
    is silent, so it reads as a broken feature rather than a switch.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "data-ta-idle" in js
    assert "this device is " in js
    # It must only appear when there is something that WOULD have spoken.
    assert "live > 0 && !willSpeak" in js


def test_a_notification_that_reached_nobody_is_reported():
    """Reported 2026-08-23: "2.50 pm srirenga did not fire."

    It DID fire — the claim row was written at 14:50:05 IST. What it did
    not do was reach anything, because the only active push subscription
    was a Windows desktop and every Android one was dead.

    The claim row proves the SCHEDULER ran. It proves nothing about
    delivery, and I had been treating the two as the same thing: the send
    result was discarded, so a fire that reached zero devices looked
    exactly like one that worked. That is the silent-failure pattern this
    codebase keeps relearning, and I reintroduced it.
    """
    src = open("services/push_scheduler.py", encoding="utf-8").read()
    block = src.split("announcer_push.fires_for_user")[1].split("except Exception")[0]
    assert "sent, failed = push_service.send_to_user" in block, \
        "the send result is discarded again"
    assert "if not sent:" in block
    assert "loud.bailed" in block, "a delivery to nobody is not surfaced"


def test_panel_states_the_notification_permission():
    """The self-heal deliberately never prompts, so on a device where
    permission was never granted it does nothing — correctly, and
    silently. Nothing anywhere said which of the three states a device was
    in, so a phone can receive nothing for a day while every other part of
    the interface looks correctly configured."""
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "data-ta-perm" in js
    for state in ("granted", "denied", "unsupported"):
        assert '"' + state + '"' in js, f"the {state} state is not distinguished"
    # 'denied' cannot be recovered by asking again, so it must say so
    # rather than offering a button that does nothing.
    assert "cannot ask again once blocked" in js
    # And the un-granted state offers the one action that changes it.
    assert "data-ta-perm-on" in js and "ClPush.subscribe" in js


def test_keepalive_defaults_on_and_survives_storage_eviction():
    """Asked 2026-08-23: "keep going when minimised or locked sometimes gets
    cleared. it should be on by default."

    The clearing has a cause worth recording. The flag is device-local by
    design — holding audio open is a battery decision belonging to the
    device making it — and a browser may evict site data: Android under
    storage pressure, iOS after a stretch of not opening the app. The
    ANNOUNCEMENTS survive that now, because they moved server-side; the
    device flags do not. So an eviction silently turned this off and left
    everything else looking correct.

    Defaulting it on means an eviction restores the useful state rather
    than the useless one.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "keepalive: true" in js, "still defaults off"
    # A stored false from BEFORE this change must not pin it off, or the
    # new default reaches nobody — everyone is currently stored as false.
    assert "raw.keepaliveSet" in js
    # But a deliberate choice has to stick.
    assert "state.keepaliveSet = true;" in js
    # And it must still only hold audio while announcements are running,
    # or an on-by-default flag would cost battery on an idle device.
    body = js.split("function applyKeepalive()")[1].split("}")[0]
    assert 'state.mode === "on"' in body


def test_keepalive_flag_follows_reality_not_intent():
    """Reported 2026-08-23: voice works on iPhone, not on Android.

    One cause found in the process: keepCtx was set whether or not play()
    succeeded, and keepaliveOn() returns early when it is set. On a fresh
    page load autoplay is ALWAYS blocked until the user touches something,
    so the first attempt failed, the flag said "held", and it never tried
    again. The checkbox was ticked, the panel said on, and the page had no
    audio focus at all — which means the OS freezes it the moment the
    screen locks, and a frozen page speaks nothing.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # The flag is set by the element REPORTING playback, not by asking.
    assert 'addEventListener("playing", function () {' in js
    assert 'addEventListener("pause", function () {' in js
    # The first gesture retries what autoplay refused.
    assert "try { applyKeepalive(); } catch (e) {}" in js
    # And a watchdog restarts it: Android pauses this element for its own
    # reasons — a call, another app taking audio focus, the media
    # notification's pause button — and a paused element is a freezable page.
    assert "function keepaliveWatch" in js
    assert "setInterval(keepaliveWatch" in js
    # The panel must show what is TRUE, not what was asked for.
    assert "data-ta-hold" in js and "Holding audio" in js


def test_announcer_reports_its_build_and_last_tick():
    """An installed PWA can serve a cached script for a long time, and every
    diagnosis after that is worthless if the device is running old code.

    And a page the OS has FROZEN keeps all its settings and simply stops
    reading the clock — the panel looks perfect and nothing fires. "Last
    check 14 minutes ago" is the whole diagnosis, and there was no way to
    see it.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    sw = open("static/service-worker.js", encoding="utf-8").read()
    import re
    build = re.search(r'var BUILD = "(v\d+)"', js)
    assert build, "no build marker"
    cache = re.search(r'CACHE_VERSION = "(v\d+)', sw)
    assert cache, "no cache version"
    # They must agree, or the number shown on the device is a lie about
    # which deploy it came from — which is worse than showing nothing.
    assert build.group(1) == cache.group(1), (
        f"BUILD {build.group(1)} != CACHE_VERSION {cache.group(1)}; "
        "bump both together")
    assert "lastTick = Date.now();" in js
    assert "this page was asleep" in js


def test_settings_shows_server_and_device_build(auth_client):
    """Asked 2026-08-23: put a build mark on Settings so the app version can
    be confirmed.

    TWO numbers, and the gap between them is the point. The SERVER build is
    what has been deployed; THIS DEVICE is what the browser actually
    executed. An installed PWA can serve a cached script for a long time,
    and until you know those match, no other diagnosis on this page means
    anything — which is exactly the position we were in when an
    announcement did not fire and nothing could say why.
    """
    from settings import BaseConfig
    build = BaseConfig.APP_BUILD
    assert build and build != "unknown", "the build could not be read"
    # It comes from the service worker's CACHE_VERSION, which already has
    # to change on every deploy. A second, separately-maintained version
    # string would give two answers to one question.
    sw = open("static/service-worker.js", encoding="utf-8").read()
    assert f'CACHE_VERSION = "{build}"' in sw

    html = auth_client.get("/settings").get_data(as_text=True)
    assert build in html, "the server build is not shown"
    assert 'id="ver-device"' in html, "the device build is not shown"
    # A mismatch must be stated, not left for the reader to spot by
    # comparing two strings.
    assert 'id="ver-warn"' in html
    # ...and there must be a way to act on it from the page.
    assert 'id="ver-update"' in html and "SKIP_WAITING" in html


def test_push_delivery_failures_are_visible_not_just_logged():
    """Measured on 2026-08-23: of this account's push subscriptions,
    Android is 0 of 7 active while Windows is 1 of 1 — on the SAME FCM
    host, which rules out a VAPID key problem and makes it specific to
    that device.

    None of that was visible anywhere. A subscription dying is normal; a
    subscription dying repeatedly on ONE device is a diagnosis, and it can
    only be spotted if each failure is recorded where the user looks rather
    than in a log only the author reads. That is why this took a day to
    find and why the same class of bug has now cost months of missed
    reminders.
    """
    src = open("services/push_service.py", encoding="utf-8").read()
    assert "from services import loud" in src
    # A 410 deactivation is reported, WITH which device it was.
    assert 'loud.bailed("push delivery"' in src
    assert "subscription rejected and deactivated" in src
    assert "device=device" in src, "the failure does not say which device"
    # A non-410 failure does not deactivate, so without its own report it
    # is invisible forever — the row stays active and never delivers.
    assert "send failed (HTTP" in src
    # And an unexpected exception is not swallowed either.
    assert 'loud.bailed("push delivery", "send raised unexpectedly"' in src


def test_each_fire_records_visibility_chime_and_speech():
    """Reported 2026-08-23: the clock speaks on iPhone locked OR unlocked;
    on Android it speaks only while the app is visible.

    Two causes produce exactly that and they need OPPOSITE fixes:

      (a) the PAGE is frozen when hidden — nothing runs, and even the
          chime is silent. The fix is the keep-alive.
      (b) the page runs but SPEECH is gated on visibility — the chime
          plays and only the words are missing. The fix is pre-rendered
          audio, because no amount of work on the browser API will make
          it speak.

    From the outside those are indistinguishable, and guessing wrong means
    building the wrong thing. So every fire records which state the page
    was in and what each half of the attempt did.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "lastFire = {" in js
    assert "document.visibilityState" in js, "visibility is not recorded"
    # Both halves report their own outcome, because it is the DIFFERENCE
    # between them that identifies the cause.
    assert 'lastFire.chime = "played"' in js and 'lastFire.chime = "blocked"' in js
    assert 'lastFire.spoke = "spoke"' in js
    assert 'lastFire.spoke = "accepted but silent"' in js
    assert "data-ta-fire" in js
    # The label changed deliberately: "while visible" read as "the screen
    # was on", and a locked phone keeps the page visible — which is exactly
    # how the locked-Android fault was misdiagnosed for days.
    assert "page hidden" in js and "locked screen counts" in js


def test_words_are_rendered_as_audio_for_a_hidden_page(auth_client, monkeypatch):
    """Reported 2026-08-23: "in android only get the chime sound, not the
    text when the phone is locked."

    That is the decisive measurement. The chime PLAYED, so the page was
    awake and background media playback was permitted; the words did not,
    so Android Chrome refuses speechSynthesis while the page is hidden.
    iPhone speaks fine in the same state.

    No amount of work on the Web Speech API fixes that. Words have to
    arrive as AUDIO, through the same element the chime already proves can
    play in the background.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # Rendered audio is used when the page is HIDDEN, and speech otherwise —
    # speech is better when it works, and on iOS it always does.
    assert "playSpeech(words, sayIt)" in js
    # THE FALLBACK MUST SURVIVE A REFUSED PLAY. play() is asynchronous, so
    # starting it is not the same as being heard. The first version treated
    # a started request as success and skipped speak() entirely — so
    # whenever a hidden page refused the audio, which it frequently does,
    # NOTHING was said. That silenced both phones, including iPhone where
    # speech had been working.
    assert "if (onFail) onFail();" in js, \
        "a refused audio play will silence the announcement again"
    assert "var spokeYet = false;" in js, "the fallback can double-speak"
    # PREFETCHED, or the sound waits on a network round trip at the exact
    # moment it is due — and a phone that dropped offline would be silent.
    assert "function prefetchNext" in js and "prefetchSpeech" in js
    assert "90 * 1000" in js, "the prefetch has no lead time"

    routes = open("routes/announcer.py", encoding="utf-8").read()
    assert '"/api/announcer/say"' in routes
    # A missing or failing TTS must degrade to "no audio this time", never
    # to an application error — it is an unofficial upstream.
    assert "tts unavailable" in routes and "tts failed" in routes
    assert 'loud.bailed("announcer speech"' in routes
    # Cached both server-side and in the browser: the same words always
    # sound the same, so re-rendering them is pure waste.
    assert "_SAY_CACHE" in routes and "Cache-Control" in routes
    assert "_SAY_CACHE_MAX" in routes, "an unbounded cache in a long-lived worker"


def test_say_endpoint_degrades_when_tts_is_missing(auth_client, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_gtts(name, *a, **k):
        if name == "gtts":
            raise ImportError("not installed")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_gtts)
    r = auth_client.get("/api/announcer/say?text=hello")
    assert r.status_code == 503, r.status_code
    assert r.get_json()["error"] == "tts unavailable"


# ── MOBILE FIT AND TOUCH TARGETS ───────────────────────────────────────
def test_the_page_can_never_be_wider_than_the_screen():
    """Reported 2026-08-23: "in mobile the screen should fit to size.
    currently i can swipe right left and it pathetically awful."

    No element in this codebase sets a hard pixel width larger than a
    phone — checked — so the overflow came from the two things that always
    cause it: flex children default to min-width:auto and therefore refuse
    to shrink below their content, and unbreakable strings have no break
    opportunity. This app is built almost entirely from flex rows, so one
    long label is enough to make the whole page pannable.

    Fixed globally rather than page by page, because the failure is
    systemic and a per-page fix gets re-broken by the next page anyone
    adds.
    """
    css = open("static/design-system.css", encoding="utf-8").read()
    assert "overflow-x: hidden" in css
    assert "overflow-wrap: break-word" in css
    # The actual fix, not just the guard: flex/grid children must be
    # allowed to shrink.
    assert "min-width: 0;" in css
    # Media and wide content constrained rather than allowed to widen the
    # page.
    assert "max-width: 100%" in css
    assert "pre, code { overflow-x: auto" in css


def test_touch_targets_are_finger_sized_on_touch_devices():
    """Same day: icons "so small and hard to click with fingers".

    44px is the figure Apple and Google both publish. Keyed off POINTER
    TYPE rather than screen width, because a tablet is wide and still
    operated with a thumb, and a small desktop window is narrow and still
    has a mouse.
    """
    css = open("static/design-system.css", encoding="utf-8").read()
    assert "@media (pointer: coarse)" in css
    assert "min-height: 44px" in css and "min-width: 44px" in css
    # Inline links in prose are exempt — they are read, not aimed at, and
    # padding them out wrecks the paragraph.
    assert "p a, li a, td a" in css

    board = open("templates/day_board.html", encoding="utf-8").read()
    assert "@media (pointer: coarse)" in board, \
        "the Day Board has its own CSS and does not load the design system"
    assert "min-width:44px" in board
    # The board's icons were sized in --u, which the fit pass SHRINKS to
    # make a busy day fit — so the controls got smaller exactly when there
    # was more to tap. The minimum has to be absolute, not a multiple of --u.
    coarse = board.split("@media (pointer: coarse)")[1][:400]
    assert "var(--u)" not in coarse.split("min-width:44px")[0], \
        "the touch minimum still scales with the fit pass"


def test_the_menu_can_be_closed_from_anywhere_in_it():
    """Reported: "when i scroll to knowledge base, references etc, i have
    no other option to scroll all the way back to close that menu".

    Correct — the only close button sat at the top of a drawer long enough
    to need scrolling, and the strip of overlay beside a 288px drawer is
    easy to miss on a phone.
    """
    nav = open("templates/_top_nav.html", encoding="utf-8").read()
    header = nav.split(".sidebar-header{")[1].split("}")[0]
    assert "position:sticky" in header, "Close scrolls out of reach again"
    assert "top:0" in header
    # Opaque, or the list scrolls visibly underneath it. Asserted on the
    # PROPERTY, not on a literal #ffffff: the nav is token-driven now, and
    # --color-surface is just as opaque while also being right in dark
    # mode, where the old literal was wrong. A transparent background, or
    # none at all, is the regression this guards.
    assert "background:" in header, "no background — the list shows through Close"
    assert "transparent" not in header, "a see-through sticky header is the bug"
    assert ".sidebar-close{min-width:44px" in nav
    # Escape must still work, for the desktop half of the same problem.
    assert 'e.key === "Escape"' in nav and "closeSidebar()" in nav


# ── ARCHIVE ────────────────────────────────────────────────────────────
def test_archive_page_renders_and_groups_by_day(auth_client, monkeypatch):
    """Asked 2026-08-23: "all the tasks done move it to archivedtasks and
    keep all the history there."

    Completed work accumulated in the live tables and never left — 66
    finished Quick Bucket items were loaded into the bucket page on every
    visit, ordered done-last, forever. Ticking things off made the page
    longer.
    """
    import routes.archive as ar

    def fake_get(table, params=None, **kw):
        if table == "quick_bucket":
            return [{"text": "Pay rent", "done_at": "2026-08-23T09:00:00Z"},
                    {"text": "Call bank", "done_at": "2026-08-22T11:00:00Z"}]
        if table == "todo_matrix":
            return [{"category": "Ship the board",
                     "updated_at": "2026-08-23T10:00:00Z"}]
        return []

    monkeypatch.setattr(ar, "get", fake_get)
    html = auth_client.get("/archive").get_data(as_text=True)
    assert "Pay rent" in html and "Call bank" in html
    assert "Ship the board" in html
    # Grouped by the day it was finished, newest first — that is the
    # question this page answers.
    assert html.index("Pay rent") < html.index("Call bank")
    assert "Today" in html


def test_archive_moves_nothing(monkeypatch):
    """A VIEW, not a move. project_tasks carries 40 columns, and project
    progress is computed from live task counts — so archiving by moving
    would silently change the completion figure on every project the tasks
    came from, for a reason nothing on screen would explain. That argument
    settled /backlog and applies harder here.
    """
    src = open("routes/archive.py", encoding="utf-8").read()
    for writer in ("post(", "update(", "delete(", "sb_delete"):
        assert writer not in src, f"the archive writes: {writer}"


def test_archive_excludes_binned_work():
    """'skipped' and 'not_required' are closed, not achieved. Counting them
    as done would make this page flatter the reader."""
    src = open("routes/archive.py", encoding="utf-8").read()
    assert 'DONE_STATUSES = ("done", "completed")' in src
    assert "skipped" in src and "not_required" in src, \
        "the exclusion is not documented where the next person will look"


def test_bucket_page_stops_carrying_old_completions():
    """Today's completions STAY — unticking a mistake has to be possible
    without going hunting. Everything older is read in place by /archive.
    """
    src = open("routes/quick_bucket.py", encoding="utf-8").read()
    assert '"or": f"(is_done.eq.false,done_at.gte.{_today_iso})"' in src
    # Pinned as a REGEX, not a literal line: the point is that "today"
    # comes from the user's timezone and never from the server's clock,
    # and that survives another name joining the same import.
    assert re.search(r"from utils\.user_tz import [\w,\s]*\buser_today\b", src), \
        "quick_bucket stopped importing user_today"


def test_archive_is_reachable_from_the_menu():
    nav = open("templates/_top_nav.html", encoding="utf-8").read()
    assert 'href="/archive"' in nav, "a page nobody can find"


def test_speech_audio_failure_is_visible_and_recoverable():
    """Reported 2026-08-23: Android still silent when locked, iPhone fine.

    iPhone works because it uses the speech API, which iOS permits on a
    hidden page. Android does not permit it, so the ONLY way words reach a
    locked Android is the rendered audio — which means whether that audio
    is reachable IS the feature working or not.

    It was being fetched silently and failing silently: a 503 from the
    render endpoint, or a missed prefetch, produced exactly the same
    outcome as everything working, which is nothing.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # The failure reason is kept and shown rather than swallowed.
    assert "var sayState" in js
    assert '"server said " + r.status' in js
    assert "data-ta-say" in js and "Spoken audio unavailable" in js

    # AND IT RECOVERS. A missed prefetch used to fall through to
    # speechSynthesis, which on a hidden Android page is silence. Fetching
    # at fire time is a second late and heard, which beats on time and
    # silent.
    assert "function fetchSpeech" in js
    # Sliced to the end of the callback rather than a fixed character
    # count — the explanation above this branch has grown twice now, and a
    # window measured in characters silently stops covering the code.
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]
    assert "fetchSpeech(words)" in fire, \
        "a missed prefetch still means silence on Android"
    # The prefetch also runs when the panel opens, so the first slot after
    # enabling is not automatically a miss.
    assert "try { prefetchNext(new Date()); } catch (e) {}" in js


def test_day_board_lets_a_todo_be_tagged_with_a_time(auth_client, monkeypatch):
    """Asked for as "i requested to tag time in to do in day board".

    The board already SHOWED task_time and already sorted by it, so the one
    column deciding where a task sits in the day was the one thing that
    could only be set on another page.

    A real <input type="time">, not a chip wired to a custom picker: the
    native control is what puts the phone's own time wheel one tap away.
    """
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [
        {"id": "T1", "task_text": "Call the bank", "quadrant": "Q1",
         "is_done": False, "task_time": "14:30"},
        {"id": "T2", "task_text": "Untagged one", "quadrant": "Q2",
         "is_done": False, "task_time": None},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board").get_data(as_text=True)

    assert 'data-task-time="T1"' in html and 'data-task-time="T2"' in html
    assert 'type="time"' in html
    assert 'value="14:30"' in html
    # An untagged task still gets a control — otherwise the only tasks you
    # could tag would be the ones already tagged.
    # Match the ATTRIBUTE with its value — a bare "data-task-time" count
    # also picks up the two references in the delegated change handler.
    assert html.count('data-task-time="') == 2

    # .hit covers the whole row at z-index 2. A control underneath it can
    # never be tapped, which is the bug this ordering exists to prevent.
    css = html.split("<style>")[1].split("</style>")[0]
    settime = css.split(".settime{")[1].split("}")[0]
    assert "z-index:3" in settime.replace(" ", "")


def test_day_board_task_time_endpoint_validates_and_clears(auth_client, monkeypatch):
    """A wrong time is worse than none, because the board SORTS by it — so
    clearing has to be reachable, and nonsense has to be refused."""
    import routes.day_board as db
    saved = []
    monkeypatch.setattr(db, "get", lambda *a, **k: [{"id": "T1"}])
    monkeypatch.setattr(db, "update",
                        lambda t, params, j, **k: saved.append((t, params, j)))

    r = auth_client.post("/api/day-board/task-time",
                         json={"id": "T1", "time": "14:30"})
    assert r.status_code == 200
    assert saved[-1][0] == "todo_matrix"
    assert saved[-1][2] == {"task_time": "14:30"}

    # Empty CLEARS rather than storing "".
    auth_client.post("/api/day-board/task-time", json={"id": "T1", "time": ""})
    assert saved[-1][2] == {"task_time": None}

    saved.clear()
    for bad in ("25:00", "9:5", "half past", "14:60", "14:30:00"):
        r = auth_client.post("/api/day-board/task-time",
                             json={"id": "T1", "time": bad})
        assert r.status_code == 400, f"{bad} was accepted"
    assert not saved

    # Someone else's task is a 404, not a silent write.
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    r = auth_client.post("/api/day-board/task-time",
                         json={"id": "T1", "time": "14:30"})
    assert r.status_code == 404
    assert not saved


def test_day_board_scrolls_a_long_list_instead_of_hiding_its_tail():
    """Asked for as "it should be scrollable on desktop also".

    The page still cannot scroll — that contract is what keeps the header,
    the columns and the timeline in place. What changed is the overflow
    endgame: the list scrolls inside its own panel rather than hiding rows
    behind "+7 more". Nothing is out of reach any more, so the counter has
    nothing left to count.
    """
    html = open("templates/day_board.html", encoding="utf-8").read()
    css = html.split("<style>")[1].split("</style>")[0]

    # There are two [data-fit] rules — the desktop scroller and the phone
    # override that turns it off. Take the one that scrolls, by content,
    # rather than by position: the phone media query is declared first.
    blocks = [b.split("}")[0].replace(" ", "").replace("\n", "")
              for b in css.split("[data-fit]{")[1:]]
    fit = [b for b in blocks if "max-height:100%" in b]
    assert fit, blocks
    fit = fit[0]
    assert "overflow-y:auto" in fit
    # A nested scroller must not trap the finger inside the list.
    assert "overscroll-behavior:contain" in fit

    # The page-level contract is untouched.
    assert "html,body{height:100%;overflow:hidden" in css.replace(" ", "")

    # The truncation loop is gone — not merely unreachable.
    script = html.split("<script>")[-1]
    assert "TRUNCATE HONESTLY" not in html
    assert "hiddenCount" not in script

    # On a phone the PAGE scrolls, so the nested scroller is turned off.
    phone = html.split("@media (max-width: 720px)")[1].split("\n}")[0]
    assert "[data-fit]{max-height:none; overflow:visible}" in phone


def test_day_board_script_actually_parses(auth_client, monkeypatch):
    """The board's JavaScript lives inside the Jinja template, so nothing
    else in this suite ever executes it — every other board test asserts on
    rendered HTML and would pass just as happily over a syntax error.

    That is not hypothetical: this file has had blocks spliced into the
    middle of a function twice, and a stray brace there takes out the fit
    pass, the clock and the time tagging in one go, silently.

    Skipped rather than failed when node is missing, so the suite still
    runs on a machine without it.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):
        pytest.skip("node not installed")

    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])

    html = auth_client.get("/day-board").get_data(as_text=True)
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert blocks, "the board rendered with no inline script at all"

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        # Separated, because they are separate scripts in the document and
        # joining them bare could invent a syntax error that is not there.
        fh.write("\n;\n".join(blocks))
        path = fh.name

    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_day_board_prep_bucket_row_opens_its_bank_not_the_bucket(auth_client,
                                                                 monkeypatch):
    """Reported: "todo when i click it goes to quick bucket instead of AISDE
    Prep link etc. It should go to the place where details are there."

    Every Quick Bucket row on the board linked to /quick-bucket. For a
    scheduled prep topic that is a page showing the same one line that was
    just clicked — the answer to "what is this" is in the bank. Events have
    followed this rule since the click-through work; bucket rows were simply
    never given it.
    """
    import routes.day_board as db
    from routes.interview_prep import _BUCKET_SEP

    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_bucket_for", lambda u, d, t: [
        {"id": "B1", "title": "AISDEPrep" + _BUCKET_SEP + "Two-pointer technique",
         "at": None, "done": False},
        {"id": "B2", "title": "SQLPrep" + _BUCKET_SEP + "Window functions",
         "at": None, "done": False},
        {"id": "B3", "title": "Buy milk", "at": None, "done": False},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])
    html = auth_client.get("/day-board").get_data(as_text=True)

    assert "/ai-sde?" in html and "topic=Two-pointer" in html.replace("+", " ")
    assert "/sql?" in html and "Window" in html
    # An ordinary line still goes where it always did.
    assert "/quick-bucket" in html

    # The routing prefix is not shown: it is repeated on every prep row and
    # spends the width the actual topic needs on a one-screen board.
    assert "AISDEPrep" not in html.split("<body")[1]
    assert "Two-pointer technique" in html
    # The bank survives as a chip, so which bank it is is still readable.
    assert "AI/SDE prep" in html and "SQL prep" in html


def test_backlog_page_router_runs_in_a_real_dom(auth_client, monkeypatch):
    """The capture box and the Send → dialog, driven for real.

    Renders the page through Flask and runs the actual static/js/backlog.js
    against that HTML, so the TEMPLATE and the SCRIPT are checked together.
    A selector only one of them knows about is exactly the break that
    source-reading assertions cannot see — and this page is nothing but
    selectors shared between the two.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")

    _backlog_stub(
        monkeypatch,
        bucket=[{"id": "b1", "text": "Renew passport", "time_bucket": "future",
                 "due_at": None, "created_at": "2026-08-01"}],
        tasks=[{"task_id": "t1", "task_text": "Revise the BCP/DR documentation",
                "status": "open", "project_id": "p1", "due_date": None,
                "created_at": "2026-01-01", "plan_date": None,
                "start_time": None}],
        projects=[{"project_id": "p1", "name": "Office"}],
    )
    html = auth_client.get("/backlog").get_data(as_text=True)

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(html)
        path = fh.name

    r = subprocess.run(["node", "tests/js/backlog.test.js", path],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


def _node_dom_test(script, html, *, timeout=180):
    """Run one tests/js/*.test.js against a page Flask actually rendered.

    Skips rather than fails where node or jsdom is absent, which is the
    same bargain the backlog harness above makes: these check the
    TEMPLATE and the SCRIPT agree, and a machine without node can still
    run everything else.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("node"):
        pytest.skip("node not installed")
    # PROBE FROM tests/js, NOT FROM THE REPO ROOT. jsdom is installed
    # beside the test scripts (node resolves it by walking up from the
    # FILE, so the scripts themselves are fine) — probing with `node -e`
    # from the root looks in the wrong place and skipped every DOM test
    # on a machine that had jsdom the whole time.
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed (cd tests/js && npm install jsdom)")

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(html)
        path = fh.name
    r = subprocess.run(["node", script, path],
                       capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout
    return r.stdout


def test_the_reader_dialog_runs_in_a_real_dom(auth_client, monkeypatch):
    """Asked 2026-08-30: "hope once i press the add, it pops up and i am
    able to correct it if needed before saving to quick bucket."

    That is a behaviour and not a string. Press Add on a paragraph and a
    dialog has to appear; correct a row and the CORRECTION has to be what
    is saved; close it and the paragraph has to still be in the box so it
    can be fixed by hand. All of that lives in the template and the script
    together, which is where source-reading tests are blind.
    """
    import routes.quick_bucket as qb
    monkeypatch.setattr(qb, "get", lambda *a, **k: [])
    _node_dom_test("tests/js/quick_bucket_read.test.js",
                   auth_client.get("/quick-bucket").get_data(as_text=True))


def test_the_projects_list_finds_and_orders_in_a_real_dom(auth_client, monkeypatch):
    """Asked 2026-08-30: "make it more user friendly. UX also clean."

    Measured first: 23 projects, 15 of them with no tasks at all, ordered
    by creation date forever, with no search — and 55 overdue tasks the
    page could not mention. A project at 3% because it is a month late
    looked exactly like one that started yesterday.

    Sorting and filtering are DOM reordering, so this drives the page's
    own script over rows shaped like the real ones.
    """
    import routes.projects as pr

    tasks = (
        # 30 tasks, 1 done, 29 long overdue — the real shape of the worst
        # project on the page.
        [{"project_id": "p1", "status": "done", "due_date": "2026-01-01",
          "revised_due_date": None}]
        + [{"project_id": "p1", "status": "open", "due_date": "2026-01-05",
            "revised_due_date": None} for _ in range(29)]
        # Office: 18 tasks, 11 done, 7 open, none late, one due soon.
        + [{"project_id": "p2", "status": "done", "due_date": None,
            "revised_due_date": None} for _ in range(11)]
        + [{"project_id": "p2", "status": "open", "due_date": None,
            "revised_due_date": "2099-01-01"} for _ in range(7)]
        # Shipped thing: everything done.
        + [{"project_id": "p3", "status": "done", "due_date": None,
            "revised_due_date": None} for _ in range(4)]
        # p4 has no tasks at all.
        # A revised date in the future must RESCUE an original in the past,
        # or "I moved it" means nothing.
        + [{"project_id": "p2", "status": "open", "due_date": "2020-01-01",
            "revised_due_date": "2099-06-01"}]
    )

    def fake_get(table, params=None, **k):
        if table == "projects":
            return [
                {"project_id": "p1", "name": "Cloudera Architect Certification",
                 "description": "", "is_archived": False},
                {"project_id": "p2", "name": "Office", "description": "",
                 "is_archived": False},
                {"project_id": "p3", "name": "Shipped Thing", "description": "",
                 "is_archived": False},
                {"project_id": "p4", "name": "Brand New Idea", "description": "",
                 "is_archived": False},
            ]
        if table == "project_tasks":
            return tasks
        return []

    monkeypatch.setattr(pr, "get", fake_get)
    html = auth_client.get("/projects").get_data(as_text=True)
    _node_dom_test("tests/js/projects_list.test.js", html)


def _node_only_test(script, timeout=120):
    """Run a tests/js suite that needs no rendered page."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    r = subprocess.run(["node", script], capture_output=True, text=True,
                       timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


def _inbox_share_stub(monkeypatch, shares=None, item_owner="test-user-id"):
    import routes.inbox as ix
    store = {"shares": list(shares or []), "deleted": []}
    users = [
        {"id": "test-user-id", "email": "me@x.com", "display_name": "Me", "is_active": True},
        {"id": "u2", "email": "shreya@x.com", "display_name": "Shreya", "is_active": True},
        {"id": "u3", "email": "gone@x.com", "display_name": "Gone", "is_active": False},
    ]

    def fake_get(table, params=None, **k):
        params = params or {}
        if table == "users":
            return users
        if table == "shared_items":
            rows = list(store["shares"])
            if params.get("shared_with"):
                rows = [s for s in rows if s["shared_with"] == params["shared_with"][3:]]
            if params.get("owner_id"):
                rows = [s for s in rows if s["owner_id"] == params["owner_id"][3:]]
            if params.get("item_ref"):
                rows = [s for s in rows if s["item_ref"] == params["item_ref"][3:]]
            return rows
        if table == "inbox_links":
            if params.get("id", "").startswith("in."):
                return [{"id": "shared1", "url": "https://x/a", "title": "Theirs",
                         "user_id": "owner9", "status": "Unread", "labels": [],
                         "created_at": "2026-08-01"}]
            if params.get("user_id") == "eq.test-user-id":
                return ([{"id": "mine1", "url": "https://x/b", "title": "Mine",
                          "status": "Unread", "labels": [], "created_at": "2026-08-02"}]
                        if item_owner == "test-user-id" else [])
            return []
        return []

    # Three modules read the same tables now — the inbox page, the share
    # blueprint's ownership check, and the shared-items service. Patching
    # only the first is how the first run of this test 404'd on an item
    # the stub was quite sure existed.
    import routes.shared as sh
    import services.shared_items_service as svc
    for mod in (ix, sh, svc):
        if hasattr(mod, "get"):
            monkeypatch.setattr(mod, "get", fake_get)
        if hasattr(mod, "post"):
            # The real table assigns an id on insert and the service
            # reads it back to update or revoke a grant. A stub that
            # skips it fails with a KeyError two calls later.
            def _post(t, d, _s=store, **k):
                row = dict(d, id=f"g{len(_s['shares']) + 1}")
                _s["shares"].append(row)
                return [row]
            monkeypatch.setattr(mod, "post", _post)
        if hasattr(mod, "update"):
            monkeypatch.setattr(mod, "update", lambda *a, **k: None)
        if hasattr(mod, "delete"):
            monkeypatch.setattr(mod, "delete",
                                lambda t, p: store["deleted"].append(p))
    return store


def test_shared_inbox_items_appear_for_the_recipient(auth_client, monkeypatch):
    """Asked 2026-08-30: "make specific inbox items to be shared with
    multiple users. when they log in it should appear there also."

    One row, many viewers — not a copy each, or the moment the owner
    fixes a title the two disagree and nothing can say which is real.
    """
    _inbox_share_stub(monkeypatch, shares=[
        {"id": "g1", "kind": "inbox", "item_ref": "shared1", "owner_id": "owner9",
         "shared_with": "test-user-id"},
    ])
    rows = auth_client.get("/api/inbox").get_json()
    ids = [r["id"] for r in rows]
    assert "mine1" in ids and "shared1" in ids
    got = [r for r in rows if r["id"] == "shared1"][0]
    assert got["shared_by"], "the card cannot say who sent it"
    assert got["can_edit"] is False
    assert "user_id" not in got, "another user's id leaked to the client"


def test_a_recipient_cannot_edit_or_delete_what_was_shared(auth_client, monkeypatch):
    """The write filters already matched nothing for a non-owner, which is
    correct and silent: it answered {"success": true} to an edit that
    changed no rows. Being told is the difference between a read-only
    item and a broken one."""
    _inbox_share_stub(monkeypatch, item_owner="someone-else")
    r = auth_client.patch("/api/inbox/shared1", json={"title": "hijacked"})
    assert r.status_code == 403, r.get_data(as_text=True)
    assert "owner" in r.get_json()["error"].lower()
    d = auth_client.delete("/api/inbox/shared1")
    assert d.status_code == 403


def test_only_the_owner_can_share_an_item(auth_client, monkeypatch):
    """Without this check anyone who knew an id could share someone
    else's item with themselves and read it. The whole feature turns on
    it."""
    _inbox_share_stub(monkeypatch, item_owner="someone-else")
    r = auth_client.post("/api/shared/share", json={
        "kind": "inbox", "item_ref": "notmine", "user_ids": ["u2"]})
    assert r.status_code == 404


def test_sharing_takes_the_whole_set_and_ignores_strangers(auth_client, monkeypatch):
    """The full list is sent, not a delta, so a retry or a replayed
    offline write cannot double-share. Ids that are not accounts on this
    instance are dropped rather than stored."""
    store = _inbox_share_stub(monkeypatch)
    r = auth_client.post("/api/shared/share", json={
        "kind": "inbox", "item_ref": "mine1",
        "user_ids": ["u2", "u3", "nobody-at-all"]})
    assert r.status_code == 200
    # u3 is inactive and "nobody-at-all" does not exist.
    assert r.get_json()["user_ids"] == ["u2"]
    assert [s["shared_with"] for s in store["shares"]] == ["u2"]

    r2 = auth_client.post("/api/shared/share", json={
        "kind": "inbox", "item_ref": "mine1", "user_ids": ["u2"]})
    assert r2.get_json()["count"] == 1
    assert len(store["shares"]) == 1, "re-sharing the same person duplicated the grant"


def test_the_people_picker_never_lists_you_or_your_email(auth_client, monkeypatch):
    """Picking a person needs a name. The rest is somebody's personal
    data and does not belong in a page payload."""
    _inbox_share_stub(monkeypatch)
    people = auth_client.get("/api/people").get_json()["people"]
    names = [p["name"] for p in people]
    assert "Shreya" in names
    assert "Me" not in names, "you can share with yourself"
    assert "Gone" not in names, "an inactive account is offered"
    assert not any("@" in str(v) for p in people for v in p.values())


def test_a_task_can_be_filed_straight_against_a_goal(auth_client, monkeypatch):
    """Asked 2026-08-30: "make the projects simpler. I want to attach
    just goals to tasks. dont want all this intiative,epic hierarchy."

    A goal is an OBJECTIVE — routes/goals.py says so in its own header:
    "what earlier iterations called a Goal is now an Objective". So the
    task carries objective_id and skips Key Result and Initiative.
    """
    import routes.projects as pr
    made = {}

    def fake_get(table, params=None, **k):
        if table == "projects":
            return [{"project_id": "p1", "name": "Office"}]
        if table == "objectives":          # the goal is the caller's own
            return [{"id": "obj-7"}]
        return []

    def fake_post(table, payload, **k):
        made.update(payload)
        return [dict(payload, task_id="t1", status="open", priority="medium",
                     start_date="2026-08-30")]

    monkeypatch.setattr(pr, "get", fake_get)
    monkeypatch.setattr(pr, "post", fake_post)
    monkeypatch.setattr(pr, "_default_epic_id", lambda *a, **k: "epic-default")

    r = auth_client.post("/projects/p1/tasks/add-ajax", json={
        "task_text": "Draft the deck", "objective_id": "obj-7",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert made["objective_id"] == "obj-7"
    # The tree is still fed behind the scenes: project progress is
    # computed from it, so dropping the default epic would silently
    # change every project's completion figure.
    assert made["epic_id"] == "epic-default"


def test_adding_a_task_still_works_before_the_migration_runs(auth_client, monkeypatch):
    """A migration file in the repo is not a column in production — this
    codebase has been caught by exactly that before. The goal is simply
    not recorded until the migration runs; the task still gets added."""
    import routes.projects as pr
    attempts = []

    def fake_post(table, payload, **k):
        attempts.append(dict(payload))
        if "objective_id" in payload:
            raise RuntimeError("PGRST204: column project_tasks.objective_id does not exist")
        return [dict(payload, task_id="t1", status="open", priority="medium",
                     start_date="2026-08-30")]

    monkeypatch.setattr(pr, "get", lambda t, params=None, **k:
                        [{"project_id": "p1", "name": "Office"}] if t == "projects"
                        else ([{"id": "obj-7"}] if t == "objectives" else []))
    monkeypatch.setattr(pr, "post", fake_post)
    monkeypatch.setattr(pr, "_default_epic_id", lambda *a, **k: None)

    r = auth_client.post("/projects/p1/tasks/add-ajax", json={
        "task_text": "Draft the deck", "objective_id": "obj-7",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert len(attempts) == 2, "it did not retry without the new column"
    assert "objective_id" not in attempts[1]


def test_a_directly_filed_goal_is_not_overwritten_by_the_old_walk():
    """_stamp_okr_ids resolves objective_id by walking task → initiative
    → key result → objective. It used to assign unconditionally, which
    set the field back to None for every task filed the simple way —
    the walk finds nothing because there is no initiative to walk from,
    which is the whole point of filing it directly."""
    import routes.projects as pr
    tasks = [
        {"task_id": "a", "objective_id": "obj-7"},          # filed directly
        {"task_id": "b", "initiative_id": None, "key_result_id": None},
    ]
    pr._stamp_okr_ids(tasks, "u1")
    assert tasks[0]["objective_id"] == "obj-7", "the direct goal was wiped"
    assert tasks[1]["objective_id"] is None


def test_the_goal_picker_offers_goals_and_not_the_whole_ladder(auth_client, monkeypatch):
    """The Objective › Key Result › Initiative labels the old picker
    built are the shape being hidden, so the simple feed does not build
    them. Cross-cutting goals with no project are included, as the old
    picker allowed via include_unassigned."""
    import routes.projects as pr
    monkeypatch.setattr(pr, "get", lambda t, params=None, **k: [
        {"id": "o1", "title": "Pass the certification", "project_id": "p1"},
        {"id": "o2", "title": "Learning", "project_id": None},
    ] if t == "objectives" else [])
    goals = auth_client.get("/api/goals/simple?project_id=p1").get_json()["goals"]
    assert [g["title"] for g in goals] == ["Pass the certification", "Learning"]
    assert all("\u203a" not in g["title"] and " > " not in g["title"] for g in goals)


def test_the_hierarchy_is_hidden_not_deleted():
    """"disable for the timebeing" — a flag, not a deletion. Flipping it
    off has to bring the old pickers back, so the markup and the columns
    must both still be there."""
    from config import SIMPLE_GOALS
    assert SIMPLE_GOALS is True
    page = open("templates/project_tasks.html", encoding="utf-8").read()
    assert "add-task-epic" in page, "the epic picker was removed rather than hidden"
    assert "add-task-initiative" in page
    assert "{% if simple_goals %}" in page, "the goal picker is not behind the flag"
    sql = open("MIGRATION_TASK_OBJECTIVE.sql", encoding="utf-8").read().lower()
    assert "drop column" not in sql and "delete from" not in sql


def test_a_shared_item_carries_its_day_and_time_and_can_be_ticked(auth_client, monkeypatch):
    """Asked 2026-08-30: "It should appear in chat space under a section
    called calendar where they know which item has been tagged them to
    read at what day and time. They should be able to mark it as
    completed ... It should tell me who has completed it and the date in
    which it was completed."
    """
    store = _inbox_share_stub(monkeypatch)

    r = auth_client.post("/api/shared/share", json={
        "kind": "prep", "item_ref": "Two-pointer technique",
        "title": "Two-pointer technique", "bank": "ai-sde",
        "user_ids": ["u2"], "due_date": "2026-09-02", "due_time": "07:00",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    row = store["shares"][0]
    assert row["due_date"] == "2026-09-02" and row["due_time"] == "07:00"
    assert row["kind"] == "prep" and row["bank"] == "ai-sde"
    # A prep topic is identified by TITLE — bank entry ids are positional
    # and shift whenever a bank is edited.
    assert row["item_ref"] == "Two-pointer technique"


def test_a_half_typed_time_is_dropped_not_stored(auth_client, monkeypatch):
    """A time nobody can parse, sitting in a calendar, is worse than no
    time — it reads as a commitment that was never made."""
    store = _inbox_share_stub(monkeypatch)
    auth_client.post("/api/shared/share", json={
        "kind": "prep", "item_ref": "T", "user_ids": ["u2"],
        "due_date": "not-a-date", "due_time": "25:99",
    })
    assert store["shares"][0]["due_date"] is None
    assert store["shares"][0]["due_time"] is None


def test_only_the_person_it_was_shared_with_can_tick_it(auth_client, monkeypatch):
    _inbox_share_stub(monkeypatch, shares=[
        {"id": "g9", "kind": "prep", "item_ref": "T", "owner_id": "owner9",
         "shared_with": "somebody-else"},
    ])
    r = auth_client.post("/api/shared/g9/complete", json={"done": True})
    assert r.status_code == 403
    assert "shared with you" in r.get_json()["error"].lower()


def test_the_calendar_lists_what_was_shared_with_me(auth_client, monkeypatch):
    _inbox_share_stub(monkeypatch, shares=[
        {"id": "g1", "kind": "prep", "item_ref": "Two-pointer technique",
         "bank": "ai-sde", "item_title": "Two-pointer technique",
         "owner_id": "owner9", "shared_with": "test-user-id",
         "due_date": "2026-09-02", "due_time": "07:00", "completed_at": None},
    ])
    items = auth_client.get("/api/shared/mine").get_json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["item_title"] == "Two-pointer technique"
    assert it["due_date"] == "2026-09-02" and it["due_time"] == "07:00"
    assert it["from_name"], "the calendar cannot say who sent it"
    assert "owner_id" not in it, "another user's id leaked to the client"


def test_the_sender_sees_who_finished_and_when(auth_client, monkeypatch):
    """One row per (item, person), so completion is naturally per person —
    two people given the same article finish it on different days."""
    _inbox_share_stub(monkeypatch, shares=[
        {"id": "g1", "kind": "inbox", "item_ref": "mine1", "item_title": "A link",
         "owner_id": "test-user-id", "shared_with": "u2",
         "completed_at": "2026-08-29T10:00:00+00:00", "created_at": "2026-08-01"},
        {"id": "g2", "kind": "inbox", "item_ref": "mine1", "item_title": "A link",
         "owner_id": "test-user-id", "shared_with": "u3",
         "completed_at": None, "created_at": "2026-08-01"},
    ])
    items = auth_client.get("/api/shared/sent").get_json()["items"]
    assert len(items) == 1, "two grants for one item should read as one line"
    it = items[0]
    assert it["total"] == 2 and it["done_count"] == 1
    done = [p for p in it["people"] if p["completed_at"]]
    assert done and done[0]["completed_at"].startswith("2026-08-29")
    assert done[0]["name"], "cannot say WHO finished it"


def test_resharing_does_not_unfinish_what_someone_already_did(auth_client, monkeypatch):
    """Adding a second person, or moving the day, must not quietly wipe
    the first person's completion."""
    store = _inbox_share_stub(monkeypatch, shares=[
        {"id": "g1", "kind": "prep", "item_ref": "T", "owner_id": "test-user-id",
         "shared_with": "u2", "completed_at": "2026-08-29T10:00:00+00:00"},
    ])
    auth_client.post("/api/shared/share", json={
        "kind": "prep", "item_ref": "T", "user_ids": ["u2"],
        "due_date": "2026-09-09",
    })
    assert store["shares"][0]["completed_at"] == "2026-08-29T10:00:00+00:00"


def test_chat_messages_carry_a_date_not_only_a_time():
    """Asked 2026-08-30: "chats tag it with dates and time. not only time."

    The formatter's own comment promised weekday and date forms and the
    body returned toLocaleTimeString alone. Which day a message belonged
    to came only from the day-separator chips — and those are hidden
    under any filter, so a filtered room was a wall of bare clock times.
    """
    _node_only_test("tests/js/chat_timestamps.test.js")


def test_read_aloud_speaks_and_can_be_stopped():
    """Asked 2026-08-30: "implement read-aloud feature for the entire
    planner. Please put in areas where there is textual content."

    Speech synthesis fails SILENTLY — five days of wrong diagnoses on the
    time announcer are the evidence — so the rules borrowed from it are
    asserted rather than trusted: a local voice over a network one,
    resume() after speak(), never cancel-and-speak in the same task, and
    long text chunked so the browser cannot cut it off part-way.
    """
    _node_only_test("tests/js/read_aloud.test.js")


def test_read_aloud_is_loaded_everywhere_the_nav_is():
    """It is a select-anything-and-hear-it feature, so it cannot live on
    one page. The nav is the one thing every page includes."""
    nav = open("templates/_top_nav.html", encoding="utf-8").read()
    assert "read-aloud.js" in nav


def test_adding_a_task_no_longer_reloads_the_project_page():
    """Asked 2026-08-30: "what about creation of tasks in project".

    The add bar was already one field and Enter. The cost was afterwards:
    addTask() ended with location.reload(), so five tasks meant five full
    page loads of a page that issues a dozen queries — while the server
    was already rendering the new row and the client threw it away.

    It threw it away for a reason: add-ajax rendered
    _project_task_card.html, a CARD, for a page built out of table ROWS.
    Both now render _project_task_row.html, so the added row is by
    construction the row a refresh would draw.
    """
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    r = subprocess.run(["node", "tests/js/project_add_task.test.js"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout, r.stdout


def test_the_added_row_is_the_same_row_the_list_draws(auth_client, monkeypatch):
    """One partial, two callers. A lookalike row would drift from the real
    one silently — the add path is the one nobody looks at twice."""
    import routes.projects as pr

    made = [{"task_id": "t9", "task_text": "Write the brief", "status": "open",
             "priority": "high", "start_date": "2026-08-30", "project_id": "p1",
             "order_index": 1, "is_pinned": False}]
    monkeypatch.setattr(pr, "get", lambda t, params=None, **k:
                        [{"project_id": "p1", "name": "X"}] if t == "projects" else [])
    monkeypatch.setattr(pr, "post", lambda t, p, **k: made)
    monkeypatch.setattr(pr, "_default_epic_id", lambda *a, **k: None)

    r = auth_client.post("/projects/p1/tasks/add-ajax",
                         json={"task_text": "Write the brief"})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["html"].lstrip().startswith("<tr"), \
        "the add path returns markup the task table cannot use"
    assert 'class="task-row' in body["html"]
    # The section is decided by the SAME grouper the page uses; letting the
    # client guess is how a task sits under Today until you refresh.
    assert body["group"], "no group, so the client cannot place the row"
    assert f'data-group="{body["group"]}"' in body["html"]


def test_no_card_grid_is_wider_than_the_phone_it_is_on():
    """`repeat(auto-fill, minmax(340px, 1fr))` overflows a 360px phone.

    The minimum in minmax() is a HARD floor: the track is at least 340px
    whatever the container is, so inside a 14px-padded phone column the
    grid is wider than the screen. body has overflow-x:hidden, so it does
    not pan — it CLIPS, and the right edge of every card is simply gone,
    which is far harder to notice than a scrollbar.

    Reported 2026-10-04 as the Work pages not being usable on a phone;
    24 grids across the app had it, Programs at 340px being the worst.
    The fix is to let the floor collapse to the container:
    minmax(min(340px, 100%), 1fr).

    Guarded here because the broken form is the one every snippet and
    every habit reaches for, so it comes back unless something objects.
    """
    import glob
    import re

    bad = []
    pattern = re.compile(r"repeat\(\s*auto-(?:fill|fit)\s*,\s*minmax\(\s*(\d+)px")
    for path in (glob.glob("templates/*.html") + glob.glob("static/*.css")
                 + glob.glob("static/v2/*.css")):
        text = open(path, encoding="utf-8").read()
        for m in pattern.finditer(text):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"{path}:{line} minmax({m.group(1)}px, …) — use minmax(min({m.group(1)}px, 100%), …)")
    assert not bad, (
        "these grid tracks have a hard pixel floor and will clip on a narrow "
        "screen:\n  " + "\n  ".join(bad)
    )


def test_a_goal_is_a_sentence_a_date_and_a_bar_you_can_drag(auth_client, monkeypatch):
    """Reported 2026-10-04: "UX is very cumbersome for OKR."

    It was, in three ways that are all measurable rather than matters of
    taste, and the DOM test asserts each:

    - ADDING one cost a nine-field modal, when /api/goals has only ever
      required a title. A one-field composer now posts the title alone.
    - PROGRESS COULD NOT BE SET. /api/goals derived it from key results
      only, and on live data no key result's current_value had ever moved
      (0 of 28, which is why config.SIMPLE_GOALS exists), so the bar read
      0% on every goal and there was no way to change it. Dragging now
      writes manual_progress — the field /goal-planner already wrote, so a
      percentage set in either place finally shows in both.
    - EIGHTEEN CONTROLS sat on one objective with two key results carrying
      two initiatives each. Three icon buttons per row became one menu and
      the key results fold away.

    SIMPLE_GOALS was already True and already honoured by the project
    tasks page; /goals was the one surface still presenting the full
    Project -> Objective -> Key Result -> Initiative -> Task ladder.
    """
    monkeypatch.setattr("routes.goals.get", lambda *a, **k: [])
    _node_dom_test("tests/js/goals_panel.test.js",
                   auth_client.get("/goals").get_data(as_text=True))


def test_goal_progress_prefers_a_typed_percentage_over_the_rollup(auth_client, monkeypatch):
    """/goals and /goal-planner must agree on what progress means.

    They did not. The planner honoured `manual_progress` and this endpoint
    ignored it, so a percentage typed on one page was invisible on the
    other, and a goal with no key results was pinned at 0% here forever.
    Same precedence as _objective_progress now: typed wins, else the
    key-result roll-up, else nothing — and `_rolled_up` rides along so the
    UI can show the disagreement rather than silently picking a side.
    """
    import routes.goals as G

    objectives = [
        {"id": "o1", "title": "Typed over live KRs", "project_id": None,
         "status": "active", "manual_progress": 60, "target_date": None},
        {"id": "o2", "title": "Roll-up only", "project_id": None,
         "status": "active", "manual_progress": None, "target_date": None},
        {"id": "o3", "title": "Neither", "project_id": None,
         "status": "active", "manual_progress": None, "target_date": None},
    ]
    krs = [
        # 40 of 200 = 20%
        {"id": "k1", "objective_id": "o1", "title": "a", "start_value": 0,
         "current_value": 40, "target_value": 200, "direction": "up"},
        # 50 of 100 = 50%
        {"id": "k2", "objective_id": "o2", "title": "b", "start_value": 0,
         "current_value": 50, "target_value": 100, "direction": "up"},
    ]

    def fake_get(table, params=None, **kw):
        if table == "objectives":
            return [dict(o) for o in objectives]
        if table == "key_results":
            return [dict(k) for k in krs]
        return []

    monkeypatch.setattr(G, "get", fake_get)
    body = auth_client.get("/api/goals").get_json()
    by_id = {o["id"]: o for o in body["objectives"]}

    assert by_id["o1"]["_progress"] == 60
    assert by_id["o1"]["_progress_source"] == "manual"
    # The roll-up travels alongside so the UI can offer "key results say 20%".
    assert by_id["o1"]["_rolled_up"] == 20

    assert by_id["o2"]["_progress"] == 50
    assert by_id["o2"]["_progress_source"] == "key_results"

    assert by_id["o3"]["_progress"] == 0
    assert by_id["o3"]["_progress_source"] == "none"


def test_a_goal_counts_its_own_tasks_before_asking_anyone(auth_client, monkeypatch):
    """Progress that maintains itself, now that objective_id is populated.

    MIGRATION_TASK_OBJECTIVE (applied 2026-10-04) put objective_id on
    project_tasks and backfilled it through the initiative -> key_result ->
    objective walk, so a goal already knows which tasks are its own. Making
    anyone type a percentage the app can count was the remaining piece of
    the "cumbersome" complaint.

    Precedence is typed -> its own tasks -> key results -> nothing. Tasks
    beat key results because tasks are what this app actually holds: 120
    linked, against key results whose current_value had ever moved being
    0 of 28. A typed value still wins, because that is a human judgement.

    "Done" is status == "done", the same definition the projects list uses
    for completion_pct — deliberately not a second one.
    """
    import routes.goals as G

    objectives = [
        {"id": "o1", "title": "typed beats its tasks", "project_id": None,
         "status": "active", "manual_progress": 60, "target_date": None},
        {"id": "o2", "title": "3 of 8 tasks done", "project_id": None,
         "status": "active", "manual_progress": None, "target_date": None},
        {"id": "o3", "title": "tasks beat key results", "project_id": None,
         "status": "active", "manual_progress": None, "target_date": None},
    ]
    # o3 has BOTH: tasks at 100% and a key result at 0%. Tasks must win.
    krs = [{"id": "k3", "objective_id": "o3", "title": "c", "start_value": 0,
            "current_value": 0, "target_value": 100, "direction": "up"}]
    tasks = (
        [{"objective_id": "o1", "status": "done"}] * 2
        + [{"objective_id": "o1", "status": "todo"}] * 2
        + [{"objective_id": "o2", "status": "done"}] * 3
        + [{"objective_id": "o2", "status": "todo"}] * 5
        + [{"objective_id": "o3", "status": "done"}] * 2
    )

    def fake_get(table, params=None, **kw):
        return {"objectives": [dict(o) for o in objectives],
                "key_results": [dict(k) for k in krs],
                "project_tasks": [dict(t) for t in tasks]}.get(table, [])

    monkeypatch.setattr(G, "get", fake_get)
    by_id = {o["id"]: o for o in auth_client.get("/api/goals").get_json()["objectives"]}

    # A typed percentage still wins, but the task figure rides along so the
    # UI can offer "2 of 4 tasks done = 50% — use that".
    assert by_id["o1"]["_progress"] == 60
    assert by_id["o1"]["_progress_source"] == "manual"
    assert by_id["o1"]["_from_tasks"] == 50
    assert (by_id["o1"]["_task_done"], by_id["o1"]["_task_total"]) == (2, 4)

    # 3 of 8 = 38%, counted rather than typed.
    assert by_id["o2"]["_progress"] == 38
    assert by_id["o2"]["_progress_source"] == "tasks"

    # Tasks outrank key results: 100% from tasks, not 0% from the KR.
    assert by_id["o3"]["_progress"] == 100
    assert by_id["o3"]["_progress_source"] == "tasks"


def test_the_goals_page_survives_a_task_query_that_fails(auth_client, monkeypatch):
    """A broken task count must cost the task figure, not the page.

    get() has no PGRST204 retry, unlike post/update, so a missing or
    renamed column is a hard 400 — the trap that once 400'd the whole task
    page for selecting objective_id before its migration had run. The task
    count is therefore wrapped: the page falls back down the precedence
    and still renders.
    """
    import routes.goals as G

    objectives = [
        {"id": "o1", "title": "has key results", "project_id": None,
         "status": "active", "manual_progress": None, "target_date": None},
    ]
    krs = [{"id": "k1", "objective_id": "o1", "title": "a", "start_value": 0,
            "current_value": 50, "target_value": 100, "direction": "up"}]

    def fake_get(table, params=None, **kw):
        if table == "project_tasks":
            raise RuntimeError("column project_tasks.objective_id does not exist")
        return {"objectives": [dict(o) for o in objectives],
                "key_results": [dict(k) for k in krs]}.get(table, [])

    monkeypatch.setattr(G, "get", fake_get)
    r = auth_client.get("/api/goals")
    assert r.status_code == 200, "a failed task count must not take the page down"
    o = r.get_json()["objectives"][0]
    assert o["_progress"] == 50
    assert o["_progress_source"] == "key_results"
    assert (o["_task_done"], o["_task_total"]) == (0, 0)


def test_goal_progress_can_be_set_and_cleared_from_the_okr_page(auth_client, monkeypatch):
    """The OKR page could not write the field that drives its own bar.

    PATCH /api/goals/<id> had no `manual_progress` in its allowlist, so the
    only way to make a goal show progress was to create a key result and
    hand-edit its current value. Validation reuses _clean_manual_progress,
    which clamps rather than rejects an out-of-range number (150 obviously
    means done) and treats "" as "go back to the roll-up".
    """
    import routes.goals as G

    wrote = []
    monkeypatch.setattr(G, "update",
                        lambda table, params=None, json=None, **k: wrote.append(dict(json or {})) or [{}])

    def patch_progress(value):
        wrote.clear()
        r = auth_client.patch("/api/goals/o1", json={"manual_progress": value})
        return r, (wrote[0].get("manual_progress") if wrote else "<no write>")

    r, stored = patch_progress(65)
    assert r.status_code == 200 and stored == 65

    # Empty means clear, which returns the goal to its key results.
    r, stored = patch_progress("")
    assert r.status_code == 200 and stored is None

    # Clamped, not refused.
    r, stored = patch_progress(150)
    assert r.status_code == 200 and stored == 100
    r, stored = patch_progress(-20)
    assert r.status_code == 200 and stored == 0

    # Junk is a real mistake: storing 0 would look like lost progress.
    r, stored = patch_progress("abc")
    assert r.status_code == 400, "junk must be rejected, not silently stored as 0"
    assert stored == "<no write>"


def test_the_roadmap_can_be_rescheduled_without_a_mouse(auth_client, monkeypatch):
    """Asked 2026-10-04: make the Work pages usable on a phone.

    The Roadmap was the one that genuinely was not. Its only way to move a
    task was HTML5 drag-and-drop, which fires no dragstart and no drop on
    a touch screen — so on a phone you could read the plan and not change
    it. It also never said what was late: every block rendered the same,
    so three weeks overdue looked like due next month.

    Both fixes are behaviour, not markup, so they are checked by running
    the real static JS against the page Flask renders. Three blocks are
    seeded either side of a fixed today so late / today / ahead are all
    exercised, and the fixture's own dates are what the assertions use.
    """
    import routes.timeline as T
    tasks = [
        {"task_id": "late-1", "project_id": "p1", "project_name": "Platform",
         "task_text": "Apply the RLS migration", "status": "todo",
         "due_date": "2026-09-20"},
        {"task_id": "today-1", "project_id": "p1", "project_name": "Platform",
         "task_text": "Rotate the Supabase key", "status": "in progress",
         "due_date": "2026-10-04"},
        {"task_id": "ahead-1", "project_id": "p2", "project_name": "Interview prep",
         "task_text": "Finish the P1 examples", "status": "todo",
         "due_date": "2026-10-18"},
    ]
    monkeypatch.setattr(T, "load_timeline_tasks", lambda *a, **k: tasks)
    monkeypatch.setattr(T, "get", lambda *a, **k: [
        {"project_id": "p1", "name": "Platform"},
        {"project_id": "p2", "name": "Interview prep"},
    ])
    _node_dom_test("tests/js/roadmap_panel.test.js",
                   auth_client.get("/projects/timeline").get_data(as_text=True))


def test_the_sidebar_collapses_in_a_real_dom(auth_client, monkeypatch):
    """Asked 2026-08-30: "the left side bar menu collapsable. it is too
    much scrolling."

    nav-groups.js does nothing but move real nodes — it replaces every
    heading and re-parents every link — so the only way to know it worked
    is to run it and count the links afterwards. It also has one rule
    that matters more than the rest: the group holding the page you are
    on never hides, whatever was saved.
    """
    import routes.quick_bucket as qb
    monkeypatch.setattr(qb, "get", lambda *a, **k: [])
    _node_dom_test("tests/js/nav_groups.test.js",
                   auth_client.get("/quick-bucket").get_data(as_text=True))


def test_app_code_is_served_network_first():
    """Reported as "check in desktop addition. Mobile seems to be working."

    Three unrelated controls appeared broken on one device and fine on
    another, running identical code. They were not broken: /static/ was
    served stale-while-revalidate, which hands back the PREVIOUS copy and
    fetches the new one for next time — so every deploy was one reload
    behind. A phone hides that (the PWA is killed and reopened constantly);
    a desktop tab left open for days does not.

    JS and CSS are small and have a cache fallback, so there is nothing to
    buy by serving them stale. Images, fonts and the keep-alive audio keep
    stale-while-revalidate: big, unchanging, and harmless a version behind.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    # The third argument turns on revalidation — without it "network
    # first" never reaches the network, because Flask's 30-day max-age
    # means the browser answers from its own HTTP cache.
    assert "networkFirst(req, STATIC_CACHE, true)" in sw, \
        "app code is still served from cache first"
    assert "staleWhileRevalidate(req, STATIC_CACHE)" in sw, \
        "images and audio should stay stale-while-revalidate"
    branch = sw.split("const isCode")[1].split(";")[0]
    assert "js" in branch and "css" in branch

    # Offline, an uncached script must NOT be answered with the offline
    # HTML page — that throws a syntax error at line 1 and takes the whole
    # file with it.
    nf = sw.split("async function networkFirst")[1].split("\n}")[0]
    assert 'req.destination === "script"' in nf


def test_push_status_reports_what_the_server_can_reach(auth_client, monkeypatch):
    """A device can sit at Notification.permission === "granted" for months
    while its row here is is_active=false — one 404/410 from the push
    service retires it — and every screen still says notifications are on.

    That gap is the whole diagnosis for a phone that receives nothing with
    the app closed, and it was visible nowhere.
    """
    import routes.push as pu

    monkeypatch.setattr(pu, "get", lambda *a, **k: [
        {"endpoint": "https://fcm.example/abc", "is_active": False}])
    r = auth_client.post("/api/push/status", json={"endpoint": "https://fcm.example/abc"})
    assert r.status_code == 200
    assert r.get_json() == {"known": True, "active": False}

    monkeypatch.setattr(pu, "get", lambda *a, **k: [
        {"endpoint": "https://fcm.example/abc", "is_active": True}])
    assert auth_client.post("/api/push/status",
                            json={"endpoint": "https://fcm.example/abc"}
                            ).get_json() == {"known": True, "active": True}

    # Never registered at all is a different problem with a different fix.
    monkeypatch.setattr(pu, "get", lambda *a, **k: [])
    assert auth_client.post("/api/push/status",
                            json={"endpoint": "https://fcm.example/zzz"}
                            ).get_json() == {"known": False, "active": False}

    # No endpoint is not an error — the browser may have no subscription.
    assert auth_client.post("/api/push/status", json={}).status_code == 200

    # And the panel must actually USE it, or the gap stays invisible.
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "/api/push/status" in js
    assert "pushReach" in js
    assert "cannot reach this device" in js


def test_checklist_view_mode_does_not_swallow_a_tap_on_a_field():
    """Reported as "checklist not able to edit time", on desktop AND phone.

    Tapping a row opens the modal read-only, and a disabled
    <input type="time"> is the worst thing to meet there: it takes the tap,
    does nothing, shows no cursor and says nothing. The Edit button was
    right there, but the field is what you reach for.

    A disabled control fires no click of its own — the event still reaches
    the form — which is why one listener on #cl-form covers every field.
    """
    js = open("static/checklist.js", encoding="utf-8").read()
    handler = js.split('$("#cl-form").addEventListener("click"')[1].split("});")[0]
    assert 'dataset.mode !== "view"' in handler, "it must only act in view mode"
    assert 'setModalMode("edit"' in handler
    # Buttons already say what they do; hijacking them would break Close.
    assert 'e.target.closest("button")' in handler
    # The tap has to reach the field it was aimed at, or it looks half fixed.
    assert ".focus()" in handler


def _chain_stub(**over):
    base = {"ok": True, "streak": 0, "best": 0, "today": 0, "bar": 5,
            "met": False, "active": 0, "window": 30,
            "days": [{"date": f"2026-08-{23 - n:02d}", "n": 0} for n in range(30)]}
    base.update(over)
    return base


def test_day_board_appreciation_never_invents_praise():
    """Asked for as "appreciate something about the person to motivate".

    Every line has to be a fact the chain already computed. Generic praise
    on a board that can see you did nothing for a week is worse than
    silence: it tells you the app is not really looking, and after that
    nothing it says counts for anything.
    """
    import routes.day_board as db

    # Nothing done, never active — say so, and say what would change it.
    line = db._appreciation(_chain_stub(), True)
    assert "5 things starts a chain" in line
    for word in ("great", "amazing", "well done", "proud", "crushing"):
        assert word not in line.lower(), f"invented praise: {line}"

    # Idle today but active before — that is a real fact, and a kinder one.
    line = db._appreciation(_chain_stub(active=3), True)
    assert "3 of the last 30 days" in line

    # Part-way through: say how much is left, not how well it is going.
    line = db._appreciation(_chain_stub(today=2), True)
    assert "2 done so far" in line and "3 more" in line

    # Cleared the bar.
    line = db._appreciation(_chain_stub(today=6, met=True), True)
    assert "Today is done" in line and "6 finished" in line

    # A run, and a personal best is worth naming.
    line = db._appreciation(_chain_stub(today=6, met=True, streak=4, best=4), True)
    assert "4 days running" in line and "best run" in line

    # A run that is NOT a best does not claim to be one.
    line = db._appreciation(_chain_stub(today=6, met=True, streak=2, best=9), True)
    assert "best run" not in line

    # No data at all, and any day that is not today, stay quiet.
    assert db._appreciation({"ok": False}, True) == ""
    assert db._appreciation(_chain_stub(today=6, met=True), False) == ""


def test_day_board_performance_reads_the_last_seven_days():
    """"dayboard reporting should be there on how i am performing."

    Built from the chain's own tally rather than a second query: it already
    counts exactly what "done" means here, and a second definition of done
    is how two screens end up disagreeing about the same day.
    """
    import routes.day_board as db
    days = [{"date": "2026-08-23", "n": 6}, {"date": "2026-08-22", "n": 0},
            {"date": "2026-08-21", "n": 5}, {"date": "2026-08-20", "n": 2},
            {"date": "2026-08-19", "n": 0}, {"date": "2026-08-18", "n": 1},
            {"date": "2026-08-17", "n": 0}]
    perf = db._performance(_chain_stub(days=days, streak=1, best=3))

    assert perf["total"] == 14
    assert perf["hit"] == 2                     # only the 6 and the 5 clear 5
    assert perf["peak"] == 6
    assert perf["avg"] == 2.0
    # Oldest first, so the chart reads left to right like a week does.
    assert [d["n"] for d in perf["days"]] == [0, 1, 0, 2, 5, 0, 6]
    assert perf["days"][-1]["met"] is True
    # Heights are relative to the best day, so a quiet week still has shape
    # instead of collapsing to a flat line.
    assert perf["days"][-1]["pct"] == 100
    assert perf["days"][3]["pct"] == 33

    assert db._performance({"ok": False}) is None


def test_day_board_greets_by_name_and_shows_the_report(auth_client, monkeypatch):
    """Name, appreciation, animation and report are one overlay.

    An overlay and not a panel because the board's contract is one screen
    with no scrolling — a permanent report would have to come out of the
    day itself.
    """
    import routes.day_board as db
    monkeypatch.setattr(db, "_events_for", lambda u, d: [])
    monkeypatch.setattr(db, "_checklist_for", lambda u, d: [])
    monkeypatch.setattr(db, "_tasks_for", lambda u, d: [])
    monkeypatch.setattr(db, "_bucket_for", lambda u, d, t: [])
    monkeypatch.setattr(db, "get", lambda *a, **k: [
        {"display_name": "Venghatesh Kumar", "email": "v@example.com"}])
    monkeypatch.setattr(db.streak_service, "compute",
                        lambda u, d, **k: _chain_stub(today=6, met=True, streak=3,
                                                      best=3, active=9))
    html = auth_client.get("/day-board").get_data(as_text=True)

    # First name only — this is a greeting, not an address label.
    assert "Venghatesh" in html and "Venghatesh Kumar" not in html
    assert "3 days running" in html
    assert 'id="welcome"' in html and 'id="howami"' in html
    assert "wc-chart" in html

    # It must NOT replay: the board reloads itself on a timer, so a welcome
    # tied to page load would fire at the user all day.
    assert "dp-board-welcome" in html
    assert "seen !== today" in html

    # An email address is never shown as a name.
    monkeypatch.setattr(db, "get", lambda *a, **k: [
        {"display_name": "", "email": "venghatesh@gmail.com"}])
    html = auth_client.get("/day-board").get_data(as_text=True)
    assert "venghatesh@gmail.com" not in html
    assert "venghatesh" in html


def test_finished_things_get_a_clap():
    """"clap on items which are finished on the inteview prep pages and also
    on dayboard."

    One module, matched by SHAPE rather than by editing five templates: every
    bank marks a topic studied with a checkbox inside a .q-card, .q-prac on
    some pages and a bare box carrying data-title on others. A new bank gets
    the clap for free, and there is one celebration instead of five that
    drift apart.
    """
    js = open("static/js/celebrate.js", encoding="utf-8").read()
    assert "window.dpClap" in js
    assert '.closest(".q-card")' in js
    assert 'classList.contains("q-prac")' in js and 'hasAttribute("data-title")' in js
    # Unticking is a correction, not an achievement.
    assert "!box.checked" in js
    # ── REDUCED MOTION SILENCES THE MOVEMENT, NOT THE CELEBRATION ─────
    # Returning early on prefers-reduced-motion meant a phone with Reduce
    # Motion turned on — an ordinary setting, and the reason "in mobile
    # completing the task is not showing claps and dancing" — got nothing
    # at all. Someone asking for less movement has not asked to stop being
    # told they finished something.
    assert "prefers-reduced-motion" in js
    assert "if (!reduced()) burst(el)" in js, \
        "reduced motion still swallows the whole celebration"
    assert "dp-still" in js, "the card has no held-still variant"
    body = js.split("window.dpClap = function")[1]
    assert "if (reduced()) return" not in body.split("};")[0], \
        "the celebration still returns early under reduced motion"
    # It must never block a click or break the thing it celebrates.
    assert "pointer-events:none" in js

    # Loaded where things get finished: the shared nav covers the banks and
    # the checklist, /java and the board carry their own include.
    for tpl in ("_top_nav.html", "java.html", "day_board.html"):
        assert "celebrate.js" in open(f"templates/{tpl}", encoding="utf-8").read(), tpl

    # ── "clap when something is closed in ANY of the screens" ──────────
    # Every place that closes a task, not just the ones that were easy.
    for tpl, why in (
        ("todo.html", "the Eisenhower matrix"),
        ("family_tasks.html", "family tasks"),
        ("summary.html", "the summary's peek panel"),
    ):
        body = open(f"templates/{tpl}", encoding="utf-8").read()
        assert "dpParty" in body, f"nothing claps in {why}"
        assert "_top_nav.html" in body, f"{why} never loads celebrate.js"

    # Skipping and deleting are not achievements — they close a row without
    # the work having happened, and applauding those teaches you to ignore
    # the applause.
    todo = open("templates/todo.html", encoding="utf-8").read()
    seg = todo.split("window.dpParty")[0][-260:]
    assert 'status === "done"' in seg, "the matrix claps for skipped/deleted too"


def test_backlog_capture_takes_effort_and_a_deadline(auth_client, monkeypatch):
    """"when i add to backlog it should capture the planned minutes" and
    "has to do by X days (take the current date as the baseline)".

    Counted from today rather than asked for as a date: while emptying your
    head onto a page, "3 days" is what you know and "the 26th" is
    arithmetic you have to stop and do.
    """
    from datetime import timedelta
    import routes.backlog as bk
    from utils.user_tz import user_today

    made = []
    monkeypatch.setattr(bk, "post",
                        lambda t, j, **k: made.append(j) or [{"id": "x"}])

    r = auth_client.post("/api/backlog/capture",
                         json={"text": "Renew passport\nBook dentist",
                               "minutes": 25, "days": 3})
    assert r.status_code == 200
    want = (user_today() + timedelta(days=3)).isoformat()
    # Applied to EVERY line of a pasted block — the common case is a list
    # of similar small jobs.
    assert [j["planned_minutes"] for j in made] == [25, 25]
    assert [j["backlog_due"] for j in made] == [want, want]

    # Both optional, and absent rather than zero — a 0-minute estimate is
    # not the same as no estimate.
    made.clear()
    auth_client.post("/api/backlog/capture", json={"text": "Just a thought"})
    assert "planned_minutes" not in made[0] and "backlog_due" not in made[0]

    # Nonsense must not become a date in the year 4000.
    made.clear()
    auth_client.post("/api/backlog/capture",
                     json={"text": "x", "days": 99999, "minutes": -5})
    assert made[0]["backlog_due"] <= (user_today() + timedelta(days=3650)).isoformat()
    assert "planned_minutes" not in made[0]


def test_backlog_puts_missed_deadlines_first(auth_client, monkeypatch):
    """"Highlight things which have missed the date."

    Sorted late-first, then by how little time is left. A backlog ordered
    purely by capture date buries the thing that is already overdue under
    everything typed since — which is the one item that needed to be seen.
    """
    from datetime import timedelta
    from utils.user_tz import user_today
    today = user_today()

    _backlog_stub(
        monkeypatch,
        bucket=[
            {"id": "b1", "text": "Captured just now", "time_bucket": "future",
             "due_at": None, "created_at": "2026-08-23", "backlog_due": None},
            {"id": "b2", "text": "Was due last week", "time_bucket": "future",
             "due_at": None, "created_at": "2026-08-01",
             "backlog_due": (today - timedelta(days=7)).isoformat()},
            {"id": "b3", "text": "Due in two days", "time_bucket": "future",
             "due_at": None, "created_at": "2026-08-02",
             "backlog_due": (today + timedelta(days=2)).isoformat()},
        ],
    )
    html = auth_client.get("/backlog").get_data(as_text=True)

    # Overdue first, then soonest, then the undated capture.
    order = [html.index(t) for t in
             ("Was due last week", "Due in two days", "Captured just now")]
    assert order == sorted(order), "the overdue item is not at the top"

    assert "7 days late" in html
    # Count the class ON A ROW, not the string — the stylesheet declares
    # `.bk-item.is-late` too, and matching that made the count read 2.
    assert html.count('class="bk-item is-late"') == 1, \
        "exactly one row should be marked missed"
    # "Due in 2 days" must not be painted the same as "already missed", or
    # the colour stops meaning anything.
    assert "bk-tag soon" in html


def test_top5_panel_drop_is_wired_once_not_once_per_render():
    """Reported: "when i am dragging and dropping in quick bucket..if i try
    to drag again it looks like it is going in continous loop."

    renderTop5() replaces the panel's CHILDREN via innerHTML, so the row
    listeners die with the rows. The panel itself survives — and its
    dragover/dragleave/drop handlers were being added again on every
    render. After ten renders one drop ran the drop handler ten times, each
    saving and re-rendering and adding ten more.

    The "a single drag can fire the drop handler several times in some
    browsers" comment in that same function was this bug seen from the
    outside; the toast debounce underneath it was hiding the symptom.
    """
    js = open("static/js/quick_bucket.js", encoding="utf-8").read()
    body = js.split("const wireTop5Rows")[1].split("const wireDragDrop")[0]

    assert 'panel.dataset.dropWired' in body, "the panel is still rebound per render"
    # The guard has to sit BEFORE the panel handlers and AFTER the row loop:
    # rows are new every render and must keep being wired.
    guard = body.index("dropWired")
    assert guard < body.index('panel.addEventListener("dragover"')
    assert guard > body.index('.qb-top5-item'), \
        "the guard also skips wiring the freshly rendered rows"


def test_announcer_speaks_the_slot_not_the_moment_it_noticed():
    """Two faults behind "speech: audio blocked" on a locked Android.

    The words were built from `now`, but the grace window is 90 seconds —
    so a fire could land in the minute AFTER the slot it belongs to, and
    phrase() is minute-precise. It then asked for "It's 7:15 PM" while the
    prefetch had cached "It's 7:14 PM", missed, and fell through to
    speechSynthesis, which a hidden Android refuses. Intermittent, and only
    on fires that ran late.

    And the words shared ONE audio element with the chime: the chime ended,
    its handler assigned a new src to the same element and called play()
    again, and that second call was refused mid-load. Two elements, both
    unlocked by the same gesture, means neither ever swaps a source out
    from under a playing stream.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()

    assert "var slotAt = new Date(now.getTime())" in js
    assert "wordsFor(slotAt, items)" in js, "the words still come from `now`"

    assert "function speechSound" in js and 'ta-speech' in js
    assert "function unlockAudio" in js
    # Android grants the permission per ELEMENT, so a speech element nobody
    # ever tapped is refused forever — both must be unlocked together.
    unlock = js.split("function unlockAudio")[1].split("\n  }")[0]
    assert "sound(), speechSound()" in unlock
    # volume, NOT muted: muted playback is permitted by the autoplay policy
    # anyway, so a muted play grants none of the permission it exists to buy.
    assert "el.volume = 0" in unlock, "the unlock must be inaudible"
    assert "muted" not in unlock, "a muted play unlocks nothing"

    # Loaded before it is due: a play() against a src assigned microseconds
    # earlier can be rejected while the source is still loading, which looks
    # exactly like an autoplay block and is not one.
    assert "function preloadSpeech" in js

    # And when it IS refused, say which refusal it was — NotAllowedError and
    # AbortError have opposite fixes.
    assert 'lastFire.spoke = "audio refused ("' in js


def test_backlog_promotes_itself_before_the_deadline(monkeypatch):
    """"it should move it in to quick bucket one day before the duration
    expires automatically."

    A deadline you have to notice yourself is a deadline you will miss —
    which is the whole reason the backlog needed dates. This is the half
    that makes capturing them worth anything.
    """
    from datetime import timedelta
    import routes.backlog as bk
    from utils.user_tz import user_today
    today = user_today()

    asked = {}
    monkeypatch.setattr(bk, "get",
                        lambda t, params=None, **k: asked.update(params or {})
                        or [{"id": "b1"}, {"id": "b2"}])
    moved = []
    monkeypatch.setattr(bk, "update",
                        lambda t, params, j, **k: moved.append((params, j)))

    assert bk.promote_due("u1", today) == 2

    # Only FUTURE, open, undeleted rows, and only those due within a day.
    assert asked["time_bucket"] == "eq.future"
    assert asked["is_done"] == "eq.false"
    assert asked["is_deleted"] == "eq.false"
    assert asked["backlog_due"] == "lte." + (today + timedelta(days=1)).isoformat()

    # Promoted into the working list, and NOT given a due_at — this is a
    # deadline, not a countdown, and writing one starts a calendar alarm
    # nobody asked for. backlog_due is kept so the date still shows and
    # still goes red if it is missed.
    assert all(j == {"time_bucket": "now"} for _p, j in moved)

    # The column arrives with the migration; until then this is a feature
    # that does not exist yet, not an error that takes the page down.
    def boom(*a, **k):
        raise RuntimeError("column backlog_due does not exist")
    monkeypatch.setattr(bk, "get", boom)
    assert bk.promote_due("u1", today) == 0


def test_backlog_shows_effort_and_time_remaining(auth_client, monkeypatch):
    """"it should show duration and do it with in ... x days and it should
    also show how many days are left based on when it was entered."
    """
    from datetime import timedelta
    from utils.user_tz import user_today
    today = user_today()

    _backlog_stub(monkeypatch, bucket=[
        {"id": "b1", "text": "Renew passport", "time_bucket": "future",
         "due_at": None, "created_at": "2026-08-20", "planned_minutes": 45,
         "backlog_due": (today + timedelta(days=5)).isoformat()},
    ])
    html = auth_client.get("/backlog").get_data(as_text=True)
    assert "45 min" in html
    assert "5 days left" in html


def test_every_posting_client_carries_a_csrf_token(app):
    """The bug this whole suite is structurally blind to.

    CSRF is enabled in production and DISABLED in TestingConfig, so a POST
    that would 400 for the user passes here without a murmur. That is how
    the entire Backlog router and the day board's time tagging shipped
    dead: neither blueprint is csrf-exempt and neither client sent a token.

    Most API blueprints here opt out with csrf.exempt(). The ones that do
    NOT must send X-CSRFToken from every client that posts to them, and the
    page must carry the meta tag to read it from. This checks both halves
    for each such endpoint.
    """
    import os
    import re
    from extensions import csrf

    exempt = set()
    for attr in ("_exempt_blueprints", "_exempt_views"):
        for v in getattr(csrf, attr, set()) or set():
            exempt.add(getattr(v, "name", v))

    # Every POST endpoint whose blueprint has NOT opted out.
    guarded = {}
    for rule in app.url_map.iter_rules():
        if "POST" not in (rule.methods or set()):
            continue
        bp = (rule.endpoint.split(".", 1)[0]) if "." in rule.endpoint else ""
        if not bp or bp in exempt:
            continue
        # Blueprint objects register under their name; the exempt set may
        # hold either, so check the module path too.
        view = app.view_functions.get(rule.endpoint)
        if view and f"{view.__module__}.{view.__name__}" in exempt:
            continue
        if str(rule).startswith("/api/"):
            guarded.setdefault(bp, set()).add(str(rule))

    # Which files mention those paths, and do they send the header?
    roots = []
    for base in ("static", "templates"):
        for dirpath, _dirs, files in os.walk(base):
            if "node_modules" in dirpath:
                continue
            for f in files:
                if f.endswith((".js", ".html")):
                    roots.append(os.path.join(dirpath, f))

    offenders = []
    for path in roots:
        try:
            body = open(path, encoding="utf-8").read()
        except Exception:
            continue
        if "method: \"POST\"" not in body and "method:\"POST\"" not in body:
            continue
        for bp, rules in guarded.items():
            for r in rules:
                # Compare on the literal prefix before any <param>.
                stem = re.split(r"<", r)[0].rstrip("/")
                if len(stem) < 8 or stem not in body:
                    continue
                if "X-CSRFToken" not in body:
                    offenders.append(f"{path} posts to {stem} ({bp}) "
                                     f"without X-CSRFToken")
    assert not offenders, "\n".join(sorted(set(offenders)))


def test_pages_that_post_carry_the_token_to_read(auth_client, monkeypatch):
    """A client that sends the header still needs somewhere to read it from.

    The day board is standalone — it does not include the shared nav that
    carries this tag on every other page — so it sent an empty token and
    was rejected just the same.
    """
    import routes.day_board as db
    for name in ("_events_for", "_checklist_for", "_tasks_for"):
        monkeypatch.setattr(db, name, lambda u, d: [])
    monkeypatch.setattr(db, "_bucket_for", lambda u, d, t: [])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])

    for path in ("/backlog", "/day-board", "/quick-bucket"):
        html = auth_client.get(path).get_data(as_text=True)
        assert 'name="csrf-token"' in html, f"{path} has no token to post with"


def test_backlog_shows_which_items_speak(auth_client, monkeypatch):
    """"some backlog items, i want to make it as announcement."

    An announcement is not a destination — it is something the item now
    DOES — so the row stays put and gains a chip. Sending it away would
    leave you being reminded, out loud, about a task no longer on any list.

    Matched by TEXT, the same rule progress, notes and effort all follow
    here: an announcement carries no reference back to the row, and adding
    one would mean a column and a migration to show a chip. A rename simply
    drops the chip rather than corrupting anything.
    """
    import routes.backlog as bk

    def fake_get(table, params=None, **k):
        if table == "quick_bucket":
            return [
                {"id": "b1", "text": "Tell slokas", "time_bucket": "future",
                 "due_at": None, "created_at": "2026-08-01"},
                {"id": "b2", "text": "Renew passport", "time_bucket": "future",
                 "due_at": None, "created_at": "2026-08-02"},
            ]
        if table == "announcer_items":
            return [
                {"say_text": "Tell slokas", "at_time": "19:45",
                 "repeat_rule": "daily", "is_on": True},
                # Switched off speaks for nobody, so it must not show a chip.
                {"say_text": "Renew passport", "at_time": "09:00",
                 "repeat_rule": "once", "is_on": False},
            ]
        return []

    monkeypatch.setattr(bk, "get", fake_get)
    html = auth_client.get("/backlog").get_data(as_text=True)

    assert "7:45 PM every day" in html, "the announced item shows no time"
    assert "9:00 AM" not in html, "a switched-off announcement still shows"

    # 24-hour storage, 12-hour display — the panel reads times back the
    # same way, and two screens disagreeing about 19:45 is its own bug.
    assert "19:45" not in html.split("<body")[1]

    # The table arrives with MIGRATION_ANNOUNCER_SYNC.sql; before that this
    # is a feature that does not exist yet, not a page that 500s.
    def boom(table, params=None, **k):
        if table == "announcer_items":
            raise RuntimeError("relation announcer_items does not exist")
        return fake_get(table, params, **k)
    monkeypatch.setattr(bk, "get", boom)
    assert auth_client.get("/backlog").status_code == 200


def test_backlog_has_its_own_menu_entry(auth_client):
    """Asked for directly. It was reachable only by typing the URL, which
    for the page meant to be the first stop for every loose thought is the
    same as not existing."""
    html = auth_client.get("/quick-bucket").get_data(as_text=True)
    nav = html.split("HELP_PAGES")[0]
    assert 'href="/backlog"' in nav, "no Backlog link in the menu"
    assert "data-match=\"^/backlog\"" in nav, "the entry never highlights itself"
    # The help button is per-page and would otherwise open the wrong page's
    # help, which is worse than none.
    assert "/^\\/backlog/" in html, "no contextual help entry for /backlog"


def test_day_board_bucket_row_links_to_the_row_not_the_page(auth_client,
                                                            monkeypatch):
    """Reported: "if i click a item in dayboard which belongs to quickbucket
    it does go to quickbucket but not to the specific item which i clicked".

    The bucket is long enough that landing at the top of it is barely better
    than not linking at all — you still have to find the thing you were
    already looking at.
    """
    import routes.day_board as db
    for name in ("_events_for", "_checklist_for", "_tasks_for"):
        monkeypatch.setattr(db, name, lambda u, d: [])
    monkeypatch.setattr(db, "_bucket_for", lambda u, d, t: [
        {"id": "B7", "title": "Call the bank", "at": None, "done": False},
    ])
    monkeypatch.setattr(db, "get", lambda *a, **k: [])

    html = auth_client.get("/day-board").get_data(as_text=True)
    assert "focus=B7" in html, "the link does not name the row"

    # And the bucket page must act on it, or the parameter is decoration.
    js = open("static/js/quick_bucket.js", encoding="utf-8").read()
    assert "revealFocused" in js
    reveal = js.split("const revealFocused")[1].split("\n  };")[0]
    assert 'get("focus")' in reveal
    assert "scrollIntoView" in reveal
    # A collapsed group hides the row, and scrolling to something hidden
    # lands nowhere.
    assert "group.open = true" in reveal
    # Marked, then unmarked: this says "here", not "this row is special".
    assert 'classList.remove("is-focused")' in reveal


def test_day_board_shows_planned_against_spent(auth_client, monkeypatch):
    """"in dayboard we should show the planned hours in bracket and how much
    we have spent etc."

    Only the bucket carries these figures — the Eisenhower rows have no
    effort columns at all — so the total says what it covers rather than
    implying it covers the whole day.
    """
    import routes.day_board as db
    for name in ("_events_for", "_checklist_for", "_tasks_for"):
        monkeypatch.setattr(db, name, lambda u, d: [])
    monkeypatch.setattr(db, "get", lambda t, params=None, **k: ([
        {"id": "1", "text": "Long one", "time_bucket": "now", "is_done": False,
         "due_at": None, "planned_minutes": 90, "actual_minutes": 25},
        {"id": "2", "text": "Short one", "time_bucket": "now", "is_done": False,
         "due_at": None, "planned_minutes": 45, "actual_minutes": 0},
    ] if t == "quick_bucket" else []))

    html = auth_client.get("/day-board").get_data(as_text=True)

    # Hours once it is worth saying in hours — "135m" is a number you have
    # to do arithmetic on, and this board is read from across a room.
    assert "1h30" in html, "90 minutes is not shown as 1h30"
    assert "45m" in html
    assert "2h15" in html, "the planned total is wrong or missing"
    assert "25m spent" in html


def test_day_board_effort_formatter():
    """The rounding rules, stated once."""
    import routes.day_board as db
    assert db._hm(45) == "45m"
    assert db._hm(60) == "1h"
    assert db._hm(90) == "1h30"
    assert db._hm(125) == "2h05", "single-digit minutes must not read as 2h5"
    # Nothing to say is said with nothing, not with "0m".
    assert db._hm(0) == "" and db._hm(None) == "" and db._hm("x") == ""


def test_moving_to_the_bucket_carries_the_estimate(auth_client, monkeypatch):
    """"planned minutes in quick bucket should get the data from backlog
    when it is moved from there."

    It travels because it IS the same row — only the bucket changes — but
    it is offered again on the move, because that is the moment you
    actually know how long something takes, and an item captured without an
    estimate would otherwise never get one.
    """
    import routes.backlog as bk
    monkeypatch.setattr(bk, "get", lambda t, params=None, **k:
                        [{"id": "b1", "text": "Renew passport",
                          "time_bucket": "future", "is_deleted": False}])
    saved = []
    monkeypatch.setattr(bk, "update",
                        lambda t, params, j, **k: saved.append(j))

    r = auth_client.post("/api/backlog/send",
                         json={"kind": "bucket", "id": "b1", "to": "quick",
                               "bucket": "1h", "minutes": 45})
    assert r.status_code == 200
    assert saved[-1]["planned_minutes"] == 45
    assert saved[-1]["time_bucket"] == "1h"

    # Cleared explicitly, rather than stored as a meaningless zero.
    saved.clear()
    auth_client.post("/api/backlog/send",
                     json={"kind": "bucket", "id": "b1", "to": "quick",
                           "minutes": 0})
    assert saved[-1]["planned_minutes"] is None

    # Untouched when the client says nothing about it.
    saved.clear()
    auth_client.post("/api/backlog/send",
                     json={"kind": "bucket", "id": "b1", "to": "quick"})
    assert "planned_minutes" not in saved[-1]


def test_keepalive_is_restored_the_moment_playback_ends():
    """"it used to work even when android phone was kept locked", with the
    8:45pm announcement finally arriving the moment the app was opened at
    8:53 — the signature of a page frozen since the last thing it played.

    The keep-alive track is what stops Android freezing the tab, and the
    watchdog that repairs it is a setInterval — which a frozen page does
    not run. So it can only ever fix a keep-alive that stopped while the
    page was still awake, and the twenty-second gap is exactly when
    freezing happens: right after playback ended and the screen went dark.

    Every announcement plays on OTHER elements, and starting them can take
    audio focus from this one. So it is put back the instant an
    announcement finishes, not at the next tick.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "function nudgeKeepalive" in js

    nudge = js.split("function nudgeKeepalive")[1].split("\n  }")[0]
    # Immediately AND after — a pause often lands just after the sound
    # stops, as the OS tidies up behind it.
    assert "keepaliveWatch()" in nudge
    assert "setTimeout" in nudge

    # Every outcome of an announcement, not just the happy one: a blocked
    # chime leaves the page just as freezable as a played one.
    for marker in ('lastFire.chime = "played"',
                   'lastFire.chime = "blocked"',
                   'lastFire.spoke = "played (audio)"',
                   'lastFire.spoke = "spoke"'):
        seg = js.split(marker)[1][:300]
        assert "nudgeKeepalive()" in seg, f"no nudge after {marker}"

    # The unlock plays two other elements on the same gesture that started
    # the keep-alive, so it has to put it back too.
    unlock = js.split("function unlockAudio")[1].split("\n  }")[0]
    assert "nudgeKeepalive()" in unlock


def test_announcer_never_decides_by_visibility():
    """The bug that kept a locked Android silent for days.

    Measured 2026-08-23: "Last fired 21.00 while visible. Chime: played,
    speech: refused, synthesis failed" — with the phone locked throughout.

    A locked screen does NOT make a page hidden. Chrome keeps
    visibilityState at "visible" when the display merely switches off, so
    the fire path took the "visible" branch and called speechSynthesis,
    which a locked Android refuses — while the rendered audio that would
    have played sat in the cache untouched. An earlier reading said
    "rendered audio: cached" right next to a speech failure for exactly
    this reason: it was there and never reached.

    The rendered audio now goes first in every case. It works in both
    states and its refusal path still falls through to speechSynthesis.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    # Sliced to the end of the callback. It used to cut at the first
    # "paint();", which the recovery step added later sits above — a window
    # that stops covering the code it guards is the recurring failure of
    # these source tests.
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]

    # The audio attempt must come before any speechSynthesis fallback, and
    # must not sit behind a visibility test. Asserted on the CALL, not on
    # the name of its failure handler — that handler is now a recovery step
    # rather than a straight fall-through to speech.
    assert "playSpeech(words," in fire
    assert "if (!hidden) { sayIt(); return; }" not in fire, \
        "the fire path still decides by visibility"
    # ORDERING IS NOT READABLE FROM THE TEXT any more, and pretending
    # otherwise produced two false failures: the recovery helper is DEFINED
    # above the call it serves and mentions both sayIt() and fetchSpeech()
    # inside itself, so index comparisons compare a definition against a
    # call. What IS checkable, and is the regression that mattered, is that
    # no statement at the top level of this callback reaches speech
    # directly — every route to it is inside a failure handler.
    top = [ln for ln in fire.splitlines()
           if ln.startswith("      ") and not ln.startswith("       ")]
    for ln in top:
        assert "sayIt()" not in ln, \
            f"speech is reached unconditionally: {ln.strip()}"

    # The flag is still RECORDED — it turned out to be the diagnosis — but
    # the label must not read as "the screen was on".
    assert "lastFire" in js and "hidden:" in js
    # Checked on the line the panel BUILDS, not on the file — the comment
    # above the fix quotes the original report verbatim.
    where = js.split("var where = lastFire.hidden")[1].split(";")[0]
    assert "while visible" not in where, \
        "the diagnostics still call a locked screen 'visible'"
    assert "locked screen" in where, "the label does not warn about this"


def test_a_late_announcement_says_it_is_late():
    """Reported as "strange. In android, when i open the app, then a
    announcement which was past the time gets fired and i hear the sound."

    The catch-up is deliberate — a reminder the phone slept through is
    worth hearing — but it read out the time of the SLOT, so at 8:10 it
    announced "It's 7:45 PM". That is simply untrue, and is most of why it
    felt wrong rather than helpful.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "This was due at " in js, "a late fire still claims the slot's time"

    late = js.split("A LATE ANNOUNCEMENT MUST SAY THAT IT IS LATE")[1][:900]
    # Only past the ordinary grace window — a fire 20 seconds late is not
    # late, it is on time, and saying so would be noise on every slot.
    assert "lateBy > GRACE_MS" in late
    # And only for NAMED announcements: the repeating clock is not caught
    # up at all, so it can never reach here.
    assert "items.length" in late


def test_push_diagnose_reports_each_devices_status(auth_client, monkeypatch):
    """Seven of one phone's subscriptions were retired over months and
    nothing recorded WHY.

    A subscription is deactivated on 404/410, but 403 (the signing keys
    changed since it was registered), 401, 429 and a plain network failure
    all look identical from outside: reminders simply stop. Those have
    completely different fixes.

    It runs on the server because that is where VAPID_PRIVATE_KEY already
    is — so nothing secret has to be copied anywhere to answer the question.
    """
    import services.push_service as ps

    subs = [
        {"endpoint": "https://fcm.googleapis.com/x/ANDROIDENDPOINT1",
         "p256dh": "k", "auth": "a", "is_active": False,
         "user_agent": "Mozilla/5.0 (Linux; Android 10; K)"},
        {"endpoint": "https://web.push.apple.com/y/IPHONEENDPOINT9",
         "p256dh": "k", "auth": "a", "is_active": True,
         "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7)"},
    ]
    monkeypatch.setattr(ps, "get", lambda *a, **k: subs)
    monkeypatch.setattr(ps, "_private_key", lambda: "key")
    monkeypatch.setattr(ps, "_vapid_claims", lambda: {"sub": "mailto:x@y.z"})

    class Resp:
        status_code = 403
        text = "the key in the token does not match"

    class Boom(Exception):
        response = Resp()

    import sys
    import types
    fake = types.ModuleType("pywebpush")
    fake.WebPushException = Boom

    def webpush(**kw):
        if "fcm.googleapis.com" in kw["subscription_info"]["endpoint"]:
            raise Boom()
        return True

    fake.webpush = webpush
    monkeypatch.setitem(sys.modules, "pywebpush", fake)

    r = auth_client.post("/api/push/diagnose")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    by = {x["device"]: x for x in body["results"]}

    # THE RETIRED ONE IS INCLUDED — it is the one under suspicion. Testing
    # only the live subscriptions would answer a question nobody asked.
    assert by["Android"]["was_active"] is False
    assert by["Android"]["status"] == 403
    assert "VAPID keys changed" in by["Android"]["outcome"]
    assert "does not match" in by["Android"]["detail"]

    assert by["iPhone"]["status"] == 201

    # The endpoint is a credential; only enough of its tail is returned to
    # tell two registrations on the same phone apart.
    for row in body["results"]:
        assert len(row["tail"]) <= 12
        assert "https://" not in row["tail"]

    # And nothing is deactivated or revived: a diagnostic that changes the
    # thing it measures cannot be run twice.
    monkeypatch.setattr(ps, "update", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("diagnose must not write")))
    auth_client.post("/api/push/diagnose")


def test_push_diagnose_says_when_it_cannot_run(auth_client, monkeypatch):
    """A blank result would read as "all your devices are fine"."""
    import sys
    import types
    import services.push_service as ps

    # pywebpush is checked first and is genuinely absent on this machine,
    # so stub it to reach the case under test rather than asserting on
    # whichever guard happens to fire first.
    fake = types.ModuleType("pywebpush")
    fake.WebPushException = type("E", (Exception,), {})
    fake.webpush = lambda **k: True
    monkeypatch.setitem(sys.modules, "pywebpush", fake)

    monkeypatch.setattr(ps, "_private_key", lambda: None)
    body = auth_client.post("/api/push/diagnose").get_json()
    assert body["ok"] is False and "VAPID_PRIVATE_KEY" in body["note"]

    # And with keys but no devices, say THAT rather than nothing.
    monkeypatch.setattr(ps, "_private_key", lambda: "key")
    monkeypatch.setattr(ps, "_vapid_claims", lambda: {"sub": "mailto:x@y.z"})
    monkeypatch.setattr(ps, "get", lambda *a, **k: [])
    body = auth_client.post("/api/push/diagnose").get_json()
    assert body["ok"] is True and "no push subscriptions" in body["note"]


def test_the_words_do_not_wait_forever_on_the_chime():
    """"in android only get the chime sound, not the text when the phone is
    locked" — the same shape, twice now.

    The announcement is chained to the chime's `ended` event, and if that
    event never arrives the words never start. `ended` is genuinely
    unreliable here: a stalled element, an interrupted stream, or the OS
    pausing playback part-way all leave it pending forever, and the chime
    is the half that was always audible.

    The chime is 1.34 seconds; after four, stop waiting and speak.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    chime = js.split("function playChime")[1].split("\n  }")[0]

    assert "setTimeout(go, 4000)" in chime, \
        "the words still wait on `ended` with no way out"
    # Both paths must go through the same guard, or a chime that ends
    # normally AND trips the timeout says everything twice.
    assert "if (went) return;" in chime
    assert chime.count("go();") >= 2, "a path still calls onDone directly"


def test_each_fire_records_whether_it_could_have_worked():
    """Every wrong diagnosis in this saga came from assuming one of two
    facts that were never recorded.

    Whether the keep-alive was holding at the moment of the fire separates
    "the page was asleep" from "the page was awake and something refused".
    Whether the speech element had ever been unlocked decides whether the
    rendered-audio path could have played at all — Android grants that per
    element, on a gesture.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    block = js.split("lastFire = {")[1].split("};")[0]
    assert "keep: !!keepCtx" in block
    assert "dataset.unlocked" in block

    line = js.split('fire.textContent = "Last fired "')[1].split(";")[0]
    assert "keep-alive" in line and "speech audio" in line
    # Stated as the alarming case, not as a neutral flag — "false" in a
    # diagnostics line is read as "fine" as often as not.
    assert "NOT holding" in line and "NEVER UNLOCKED" in line


def test_rendered_speech_is_cached_as_a_self_contained_url():
    """Measured on a locked Android, 2026-08-23:

        "(page hidden) Chime: Played. Speech audio refused (not supported
         error), rendered audio: cached"

    NotSupportedError means the element could not decode its source — and
    the source was a blob: URL created before Android froze the page. A
    frozen or discarded page has its object URLs released while the
    JavaScript string naming them survives in the cache. The announcement
    looked cached right up to the moment it was needed, then pointed at
    nothing.

    A data: URL cannot be invalidated: it IS the audio.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    fetch_fn = js.split("function fetchSpeech")[1].split("\n  }")[0]

    assert "readAsDataURL" in fetch_fn, "speech is still cached as a blob URL"
    # createObjectURL survives only as the fallback for a FileReader that
    # fails — losing the audio entirely would be worse than a fragile URL.
    assert fetch_fn.count("createObjectURL") <= 2
    assert "fr.onerror" in fetch_fn

    # AND IT HEALS. A cached entry that will not play is worse than no
    # cache, because it stops us fetching one that would.
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]
    assert "var recover" in fire
    assert "delete sayCache[words]" in fire
    # Exactly once per fire, or a source that never decodes loops until the
    # slot has passed.
    assert "if (retried) { sayIt(); return; }" in fire


def test_a_revoked_subscription_is_replaced_not_resent():
    """Diagnosed 2026-08-23 by /api/push/diagnose: one phone reported 410,
    "the subscription was revoked by the browser or device", while the
    other two devices delivered normally. Seven of that phone's
    registrations had accumulated and died the same way.

    getSubscription() keeps handing back a subscription the push service
    has already revoked, so the heal re-posted it, the server marked it
    active again, the next send got another 410 and retired it again. Only
    unsubscribe() then subscribe() produces a fresh endpoint — and the
    server is the only party that ever sees the 410, so it has to be asked.
    """
    js = open("static/js/push.js", encoding="utf-8").read()
    heal = js.split("async function healSubscription")[1].split("\n  }")[0]

    assert "/api/push/status" in heal, "the heal never asks whether it is dead"
    assert "sub.unsubscribe()" in heal, "a revoked subscription is still re-sent"
    assert "st.known && !st.active" in heal

    # NEVER PROMPTS: the permission check comes first, so a page load
    # cannot produce a permission dialog nobody asked for.
    assert heal.index('Notification.permission !== "granted"') < \
           heal.index("/api/push/status")

    # And this case is deliberately not throttled — waiting up to twelve
    # hours to retry means twelve hours of silence.
    assert "throttled = false" in heal


def test_code_is_fetched_past_the_browsers_own_cache():
    """Reported: a phone still showing v262 while the server served v265.

    /static is sent with SEND_FILE_MAX_AGE_DEFAULT = 30 days, so every
    script carries max-age=2592000. A plain fetch() consults the browser's
    HTTP cache before the network, finds a fresh entry and returns it — no
    request is made at all. So switching these files to network-first
    changed nothing for the files it was added for, and a device stayed on
    a build for as long as its HTTP cache held it.

    cache: "no-cache" does not mean "do not cache" — it means always
    revalidate, which sends If-None-Match and usually gets a 304 back.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    nf = sw.split("async function networkFirst")[1].split("\n}")[0]
    assert 'cache: "no-cache"' in nf, \
        "network-first still asks the HTTP cache first"
    assert "new Request(req," in nf

    # Only for code. Media is big, unchanging, and being a version behind
    # on an icon costs nothing.
    assert "networkFirst(req, STATIC_CACHE, true)" in sw
    assert "staleWhileRevalidate(req, STATIC_CACHE)" in sw

    # The 30-day header this works around is real; if it ever goes away
    # this test should be revisited rather than silently kept.
    app = open("app.py", encoding="utf-8").read()
    assert "SEND_FILE_MAX_AGE_DEFAULT" in app


def test_speech_element_is_unlocked_without_waiting_for_a_tap():
    """Measured on a locked Android at v265:

        "keep-alive: holding, speech audio: NEVER UNLOCKED"

    unlockAudio() was wired to the first pointerdown only, and the app had
    been opened and locked without the screen being touched — while the
    keep-alive started anyway, because Chrome permits autoplay on a site it
    considers engaged. So the page was wide awake, holding audio focus,
    with the one element the words needed still locked.

    The keep-alive playing IS the proof that audio is permitted, so that is
    where the unlock now also happens.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()

    playing = js.split('el.addEventListener("playing"')[1].split("});")[0]
    assert "unlockAudio()" in playing, \
        "the keep-alive starting does not unlock the announcement elements"

    start = js.split("function start() {")[1].split("\n  }")[0]
    assert "unlockAudio()" in start

    # It must stay retryable: marking it done on a FAILED attempt would
    # make one bad moment permanent for the whole page load.
    unlock = js.split("function unlockAudio")[1].split("\n  }")[0]
    body = unlock.split("var settle")[1]
    assert 'dataset.unlocked = "1"' in body.split("catch")[0], \
        "the unlock is marked done outside the success path"


def test_the_words_retry_on_the_element_that_just_worked():
    """The chime had played a second earlier through the OTHER audio
    element, on the same locked phone, in the same instant.

    That is not a theory about what Android permits — it is a
    demonstration. So a refused announcement tries the element that has
    just proved itself before re-rendering anything.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]

    assert "triedChimeEl" in fire
    assert "sound())" in fire, "the retry does not target the chime's element"
    # Once only, or a source that never decodes ping-pongs between the two
    # elements until the slot has passed.
    assert "if (!triedChimeEl" in fire
    # And it is tried BEFORE spending a network round trip re-rendering.
    assert fire.index("triedChimeEl = true") < fire.index("retried = true")


def test_an_announcement_that_cannot_be_spoken_still_arrives():
    """Every audio path can fail on a locked phone, and the failure is
    silence — which is indistinguishable from the announcement never having
    been scheduled at all.

    A notification is the one thing that definitely reaches a locked
    Android: it buzzes, it stays on screen, and it does not care whether
    audio was permitted. The server sends one too, but only to a device
    with a live push subscription — which is exactly what had been broken
    for months on the phone this is for. This one needs nothing but the
    page being alive, which is the case being rescued.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    assert "function notifyInstead" in js

    fn = js.split("function notifyInstead")[1].split("\n  }")[0]
    # Never prompts, and never assumes: a page that asked for permission
    # here would be asking at the worst possible moment.
    assert 'Notification.permission !== "granted"' in fn
    assert "showNotification" in fn
    # It has to be noticeable on a locked screen, or it is silence with
    # extra steps.
    assert "vibrate" in fn and "requireInteraction: true" in fn
    assert "silent: false" in fn

    # Reached from the dead ends, not from the happy path.
    assert js.count("notifyInstead(") >= 3
    for marker in ('lastFire.spoke = "refused: "',
                   'lastFire.spoke = "accepted but silent"'):
        seg = js.split(marker)[1][:220]
        assert "notifyInstead" in seg, f"no fallback after {marker}"

    # And the log says so, or "you were told" looks like silence.
    assert "fell back to a notification" in js


def test_the_words_play_from_a_plain_http_url():
    """The decisive measurement, on a locked Android 2026-08-24:

    the words were refused with NotSupportedError from a blob: URL, then
    from a data: URL, and then from the SAME element that had played the
    chime one second earlier. Same element, same instant, same locked
    screen — one source played and the other did not.

    So it was never the element, and never the autoplay permission. It was
    the URL scheme: Android Chrome will not decode a blob:/data: source on
    a media element. The chime works because it is an ordinary HTTP URL.
    """
    js = open("static/js/time-announcer.js", encoding="utf-8").read()

    play = js.split("function playSpeech")[1].split("\n  }")[0]
    assert "sayUrl(text)" in play, "the element is still handed cached bytes"
    assert "createObjectURL" not in play and "data:" not in play

    pre = js.split("function preloadSpeech")[1].split("\n  }")[0]
    assert "sayUrl(text)" in pre

    # The retry on the chime's element must use the same source, or it
    # re-tests the thing that already failed.
    fire = js.split("playChime(function () {")[1].split("\n    });")[0]
    assert "playThrough(sayUrl(words)" in fire

    # The fetch is still worth doing — it warms the caches so the source is
    # local by the time it is needed.
    assert "function fetchSpeech" in js
    assert "sayCache[text]" in play, "nothing checks that it was warmed"


def test_rendered_speech_is_cached_by_the_service_worker():
    """It has to be playable on a phone that is locked, frozen and possibly
    off the network — precisely when a request is least likely to succeed.

    /api/announcer/say returns the same audio for the same words forever,
    so it is cached by URL. It is deliberately the ONE exception above the
    /api/ early-return; everything else under /api/ must stay live.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    assert "async function cacheFirst" in sw
    assert '"/api/announcer/say"' in sw

    body = sw.split('addEventListener("fetch"')[1]
    say_at = body.index('/api/announcer/say')
    api_at = body.index('url.pathname.startsWith("/api/")')
    assert say_at < api_at, \
        "the /api/ early-return runs first, so the audio is never cached"


def test_say_endpoint_never_answers_with_html(client):
    # NOTE: deliberately does NOT request auth_client — that fixture seeds a
    # session into this very client, so asking for both makes the "signed
    # out" request signed in, and the test passes for the wrong reason.
    """The announcement audio URL is the `src` of an <audio> element.

    @login_required answers a signed-out request with a 302 to the login
    PAGE, and fetch() follows redirects — so a lapsed session arrived at the
    browser as a cheerful 200 of text/html. A media element cannot decode
    that (NotSupportedError), and a cache will store it under the
    announcement's URL forever, which makes one expired session a permanent
    silence.

    401, and no body a decoder could mistake for audio.
    """
    r = client.get("/api/announcer/say?text=hello")
    assert r.status_code == 401, "a signed-out request is still redirected"
    assert "text/html" not in (r.headers.get("Content-Type") or "")
    assert b"<html" not in r.data.lower()

    # And it still refuses to be an open text-to-speech proxy: no audio
    # came back, whatever else happened.
    assert not (r.headers.get("Content-Type") or "").startswith("audio/")


def test_only_audio_is_ever_cached_as_an_announcement():
    """Both ends check the CONTENT TYPE, not the status.

    An `ok` response is not proof of audio — a followed redirect to the
    login page is a 200 too. Caching that put the login page in the cache
    under the announcement's URL, permanently.
    """
    sw = open("static/service-worker.js", encoding="utf-8").read()
    cf = sw.split("async function cacheFirst")[1].split("\n}")[0]
    assert 'get("content-type")' in cf
    assert "audio" in cf, "the service worker caches whatever came back"

    js = open("static/js/time-announcer.js", encoding="utf-8").read()
    fetch_fn = js.split("function fetchSpeech")[1].split("\n  }")[0]
    assert "content-type" in fetch_fn
    assert "not signed in" in fetch_fn, \
        "a signed-out render is still reported as ready"


def test_the_fire_log_records_whether_anything_received_it(monkeypatch):
    """A claim row proves the SCHEDULER ran. It proves nothing about
    delivery, and treating the two as the same has cost several nights of
    testing: there is a claim for every slot, including the ones where no
    device made a sound and no notification appeared.

    The send outcome was recorded only through services/loud.py, which is
    in memory and lost on every restart — so by the time anyone looked at a
    silent announcement, the one fact that mattered was gone.
    """
    from services import announcer_push as ap

    wrote = []
    monkeypatch.setattr(ap, "update",
                        lambda t, params, json, **k: wrote.append((t, params, json)))
    ap.record_delivery("u1", "i1-9", "2026-08-24", "01:05", 2, 1)

    table, params, body = wrote[0]
    assert table == "announcer_fire_log"
    # Keyed on the whole claim, or it would stamp the wrong row.
    assert params["client_id"] == "eq.i1-9"
    assert params["fire_date"] == "eq.2026-08-24"
    assert params["fire_time"] == "eq.01:05"
    assert body == {"sent": 2, "failed": 1}

    # NEVER RAISES. The announcement has already gone out or not; failing
    # to write a note about it must not become an error.
    def boom(*a, **k):
        raise RuntimeError("column sent does not exist")
    monkeypatch.setattr(ap, "update", boom)
    ap.record_delivery("u1", "i1-9", "2026-08-24", "01:05", 0, 0)

    # And the scheduler actually calls it.
    sched = open("services/push_scheduler.py", encoding="utf-8").read()
    assert "announcer_push.record_delivery(" in sched


def test_announcements_are_mirrored_into_google_calendar():
    """"can you not make it as system notification since calendar
    notification in android did not work. i had to create it in samsung
    calender or google calendar to make it work."

    Right, and this codebase already had the evidence — the checklist
    mirror's own docstring says Samsung and most Android OEMs suppress
    heads-up banners from generic Web Push while Google Calendar popups are
    treated as first-class by the OS. Measured here: a push scheduled for
    01:05 arrived when the screen was next unlocked. A calendar popup goes
    through the exact-alarm path and is not deferred by Doze.
    """
    from services import announcer_calendar_service as acs

    # T-0 popup is the whole point; anything earlier is a different
    # announcement from the one that was asked for.
    body = acs._event_body(
        {"at_time": "07:45", "say_text": "Tell slokas",
         "repeat_rule": "daily", "start_date": "2026-08-24"}, "Asia/Kolkata")
    assert body["reminders"]["overrides"] == [{"method": "popup", "minutes": 0}]
    assert body["reminders"]["useDefault"] is False
    assert body["start"]["dateTime"].endswith("T07:45:00")
    assert body["start"]["timeZone"] == "Asia/Kolkata"
    assert body["recurrence"] == ["RRULE:FREQ=DAILY"]

    # A one-off must NOT recur, and must anchor on its own date.
    once = acs._event_body(
        {"at_time": "21:08", "say_text": "x", "repeat_rule": "once",
         "start_date": "2026-08-24"}, "UTC")
    assert "recurrence" not in once
    assert once["start"]["dateTime"].startswith("2026-08-24")

    # Sunday is 0 in this app and SU in Google's vocabulary; getting the
    # offset wrong moves every reminder by a day.
    custom = acs._rrule({"repeat_rule": "custom", "days": [0, 6]})
    assert custom == "RRULE:FREQ=WEEKLY;BYDAY=SU,SA"
    # "Chosen days" with nothing chosen fires never, so it must not become
    # a weekly event on an arbitrary day.
    assert acs._rrule({"repeat_rule": "custom", "days": []}) is None

    assert acs._rrule({"repeat_rule": "once"}) is None
    assert "UNTIL=20261231" in acs._rrule(
        {"repeat_rule": "daily", "end_date": "2026-12-31"})


def test_the_calendar_mirror_is_removed_with_the_announcement():
    """A mirror that keeps ringing for a deleted announcement is the worst
    way for one to fail — so the event id is read BEFORE the soft delete,
    while the row still has it."""
    src = open("routes/announcer.py", encoding="utf-8").read()
    delete_fn = src.split("def delete_item")[1].split("\ndef ")[0]
    assert "google_event_id" in delete_fn
    assert delete_fn.index("google_event_id") < delete_fn.index('"is_deleted": True'), \
        "the id is read after the row is already flagged deleted"
    assert "remove=True" in delete_fn

    # Switching one OFF must also silence the calendar, not just the voice.
    save_fn = src.split("def save_items")[1].split("\ndef ")[0]
    assert 'remove=(c.get("is_on") is False)' in save_fn
    # Off the request thread: saving must never wait on Google.
    assert "sync_async" in save_fn


def test_p3_glossary_batches_are_all_attached():
    """A mis-keyed title in an _EX_* dict is a SILENT no-op — the entry keeps
    its empty examples list and the only symptom is a number that never
    moves. The file's own comments warn about it twice, so it is pinned.

    Also pins the shape the rewrite promised: at least five worked examples,
    a plain-English opening before any jargon, and a closing section that
    walks the code back to the trace.
    """
    import ai_sde_bank as bank

    by_title = {e["title"]: e for e in bank.ENTRIES}
    # Discovered, not listed. A hardcoded list silently stops covering the
    # batch someone adds next, which is the same class of silent gap the
    # test exists to catch.
    names = sorted(n for n in dir(bank)
                   if n.startswith("_EX_P3") and isinstance(getattr(bank, n), dict))
    assert len(names) >= 4, f"only found {names}"
    for name in names:
        d = getattr(bank, name)
        assert d, f"{name} is empty"
        for title, examples in d.items():
            entry = by_title.get(title)
            assert entry is not None, f"{name} key matches no entry: {title!r}"
            assert len(examples) >= 5, f"{title!r} has only {len(examples)}"
            assert entry["examples"] is examples, \
                f"{title!r} declared but never attached"

            # The agreed shape: everyday example first, jargon after.
            first = examples[0]
            assert "THE GOAL" in first, f"{title!r} does not open with the goal"
            assert "plain English" in first or "plain english" in first.lower()
            # And a closing walkthrough with the mistakes named.
            last = examples[-1]
            assert "TAKEAWAY" in last, f"{title!r} has no takeaway"
            assert "MISTAKE" in last, f"{title!r} names no common mistake"


def test_p3_progress_is_reported_honestly():
    """Two numbers rather than one, for the same reason ANSWERS_REWRITTEN
    and ANSWERS_DECLARED are pinned equal: a count computed from the dicts
    would keep rising even if nothing attached."""
    import ai_sde_bank as bank

    p3 = [e for e in bank.ENTRIES if e.get("priority") == "P3"]
    done = [e for e in p3 if len(e.get("examples") or []) >= 5]
    # Ratchet: this only ever goes up. If a change drops it, that change
    # detached something.
    assert len(done) >= 100, f"P3 completed fell to {len(done)}"
    assert len(p3) == 336
