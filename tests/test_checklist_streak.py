"""The checklist streak must not reset every morning.

/checklist/history read "0 days in a row" all day until the last item was
ticked, because today — with items still legitimately open — was treated
as a missed day. Today is not over: unfinished, it is skipped; finished,
it counts. A real miss on any earlier day still breaks the streak.
"""
from datetime import date, timedelta


TODAY = date(2026, 10, 11)


def _load(monkeypatch, ticked_days, today=TODAY):
    import services.checklist_history as ch
    items = [{"id": "a", "name": "Walk"}, {"id": "b", "name": "Vitamins"}]
    ticks = [{"item_id": i, "tick_date": d.isoformat(), "reminder_time": None}
             for d, ids in ticked_days.items() for i in ids]

    def fake_get(table, params=None, **kw):
        return {"checklist_items": items, "checklist_ticks": ticks}.get(table, [])
    monkeypatch.setattr(ch, "get", fake_get)
    monkeypatch.setattr(ch.checklist_schedule, "is_due", lambda item, day: True)
    return ch.load("u1", TODAY, 14, today=today)


def _days(n):
    return [TODAY - timedelta(days=k) for k in range(n)]


def test_an_unfinished_today_does_not_zero_the_streak(monkeypatch):
    ticked = {d: ["a", "b"] for d in _days(6)[1:]}   # five full days before today
    ticked[TODAY] = ["a"]                             # today half done
    assert _load(monkeypatch, ticked)["streak"] == 5


def test_a_finished_today_counts(monkeypatch):
    ticked = {d: ["a", "b"] for d in _days(6)}
    assert _load(monkeypatch, ticked)["streak"] == 6


def test_a_real_miss_yesterday_still_breaks_it(monkeypatch):
    ticked = {d: ["a", "b"] for d in _days(6)[2:]}
    ticked[TODAY - timedelta(days=1)] = ["a"]         # yesterday missed one
    ticked[TODAY] = ["a", "b"]
    assert _load(monkeypatch, ticked)["streak"] == 1


def test_without_today_the_old_strict_rule_applies(monkeypatch):
    """Callers that do not pass `today` (e.g. a past window) are unchanged."""
    ticked = {d: ["a", "b"] for d in _days(6)[1:]}
    ticked[TODAY] = ["a"]
    assert _load(monkeypatch, ticked, today=None)["streak"] == 0
