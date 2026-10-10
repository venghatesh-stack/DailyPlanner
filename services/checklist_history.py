"""Adherence over time: what was due, what was ticked, day by day.

The ticks were always stored per date (`checklist_ticks.tick_date`) but
nothing ever read them for any day but today, so the record existed and
was invisible. This turns it into the two things it can answer:

  * "did I miss anything yesterday?" — one line on today's list
  * "how am I actually doing?" — the history page

DONE MEANS THE SAME THING HERE AS ON THE PAGE. An item with three reminder
times is done only when ALL THREE are ticked (`_serialize` decides it that
way and this must not disagree, or the two screens would report different
numbers for the same day). An item with no reminder rows uses the legacy
NULL-keyed tick.

DUE-NESS COMES FROM services/checklist_schedule.py, the same function the
push scheduler uses to decide whether to remind you. A "you missed this"
that disagreed with the reminder would be telling you two stories about
one day.
"""

import logging
from datetime import timedelta

from services import checklist_schedule
from supabase_client import get

logger = logging.getLogger("daily_plan")

#: Hard ceiling on a history window. Each extra day is only arithmetic —
#: the rows are fetched once — but an unbounded ?days= is still a way to
#: ask the database for everything.
MAX_DAYS = 365


def _tick_index(rows):
    """{(item_id, tick_date): {reminder_time_or_None, ...}}"""
    idx = {}
    for r in rows or []:
        key = (r.get("item_id"), r.get("tick_date"))
        idx.setdefault(key, set()).add(r.get("reminder_time"))
    return idx


def _is_done(item, day_iso, tick_idx, times_by_item):
    """Was this item completed on this day?

    A LEGACY NULL-KEYED TICK COUNTS ON ITS OWN, whatever reminder times the
    item carries now. This is not a shortcut — it is the only correct
    reading of the data. Ticks recorded before an item gained reminder
    times are stored with a NULL time; requiring today's reminder rows to
    be ticked would mark those days MISSED for items the user demonstrably
    ticked. Real example from this database: every tick on 2026-04-26 is
    NULL-keyed, and all seven of those items were given reminder times
    later — so the strict rule reported 0 of 10 done on a day with seven
    ticks on it.

    Configuring a reminder in August cannot un-tick April. Where an item
    does have reminder rows and per-time ticks, all of them must be ticked,
    which is what `_serialize` uses for the live page.
    """
    ticked = tick_idx.get((item["id"], day_iso))
    if not ticked:
        return False
    if None in ticked:
        return True                      # whole-item tick: unambiguous
    wanted = times_by_item.get(item["id"]) or []
    if not wanted:
        return bool(ticked)
    return all(t in ticked for t in wanted)


def load(user_id, end_date, days, today=None):
    """Per-day adherence ending on `end_date` (inclusive).

    `today` (a date) is the user's current day. It is not over yet, so an
    unfinished today neither counts towards the streak nor breaks it.

    Returns a dict with `days` (newest first), `items` (per-item totals)
    and the overall counts. One query per table regardless of the window —
    the arithmetic is local, so a year costs the same three round trips as
    a week.
    """
    days = max(1, min(MAX_DAYS, int(days or 30)))
    start_date = end_date - timedelta(days=days - 1)

    items = get("checklist_items", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "eq.false",
        "order": "position.asc,created_at.asc",
    }) or []

    times = get("checklist_reminder_times", params={
        "user_id": f"eq.{user_id}",
        "order": "position.asc,reminder_time.asc",
    }) or []
    times_by_item = {}
    for t in times:
        times_by_item.setdefault(t["item_id"], []).append(t.get("reminder_time"))

    ticks = get("checklist_ticks", params={
        "user_id": f"eq.{user_id}",
        "tick_date": f"gte.{start_date.isoformat()}",
        "limit": "20000",
    }) or []
    # A second bound in Python rather than a second PostgREST filter: the
    # column is compared as text and an upper bound is only needed for a
    # window that ends in the past, which is rare.
    ticks = [t for t in ticks if (t.get("tick_date") or "") <= end_date.isoformat()]
    tick_idx = _tick_index(ticks)

    out_days = []
    per_item = {i["id"]: {"id": i["id"], "name": i.get("name") or "",
                          "due": 0, "done": 0} for i in items}

    cursor = end_date
    while cursor >= start_date:
        iso = cursor.isoformat()
        due = [i for i in items if checklist_schedule.is_due(i, cursor)]
        done = [i for i in due if _is_done(i, iso, tick_idx, times_by_item)]
        for i in due:
            per_item[i["id"]]["due"] += 1
        for i in done:
            per_item[i["id"]]["done"] += 1
        out_days.append({
            "date": iso,
            "label": cursor.strftime("%a %d %b"),
            "due": len(due),
            "done": len(done),
            "missed": len(due) - len(done),
            "pct": round(100.0 * len(done) / len(due)) if due else None,
            "missed_names": [i.get("name") or "" for i in due
                             if i not in done][:12],
        })
        cursor -= timedelta(days=1)

    total_due = sum(d["due"] for d in out_days)
    total_done = sum(d["done"] for d in out_days)

    # Days with nothing due are not misses and must not drag the rate down —
    # a weekend with no weekday items is not a failure.
    active = [d for d in out_days if d["due"]]
    # Streak counts back from the most recent day that had anything due.
    # TODAY IS NOT OVER: with items still open this evening it used to read
    # "0 days in a row" all day, every day, until the last tick — a streak
    # that resets every morning measures nothing. An unfinished today is
    # skipped; a finished today counts.
    today_iso = today.isoformat() if today else None
    streak = 0
    for d in active:
        if d["missed"] == 0:
            streak += 1
        elif d["date"] == today_iso:
            continue
        else:
            break

    ranked = sorted((v for v in per_item.values() if v["due"]),
                    key=lambda v: (v["done"] / v["due"], -v["due"]))

    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days": out_days,
        "items": ranked,
        "total_due": total_due,
        "total_done": total_done,
        "pct": round(100.0 * total_done / total_due) if total_due else None,
        "active_days": len(active),
        "streak": streak,
        "window": days,
    }


def yesterday_summary(user_id, today):
    """The one line today's checklist shows about the day before.

    Deliberately about YESTERDAY and not "the last few days": a checklist
    is a daily loop, and the only feedback that changes behaviour is about
    the loop you just finished.
    """
    y = today - timedelta(days=1)
    try:
        data = load(user_id, y, 1)
    except Exception:
        logger.warning("checklist yesterday summary failed", exc_info=True)
        return None
    day = (data.get("days") or [None])[0]
    if not day or not day["due"]:
        return None          # nothing was due — there is nothing to say
    return {
        "date": day["date"],
        "label": day["label"],
        "due": day["due"],
        "done": day["done"],
        "missed": day["missed"],
        "names": day["missed_names"],
    }
