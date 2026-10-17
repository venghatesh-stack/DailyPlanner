"""Interview Prep Coach — a motivating, on-track interview tracker.

Built for a senior run (Senior Director / Head of Technical Program
Management): a readiness score, a curated syllabus with confidence
levels, a STAR story bank, a daily practice log driving a streak, and a
coach that celebrates when you're ahead and *scolds* when you skip a day
or fall behind pace.

Readiness and streak are computed on the fly from topics / stories /
sessions — nothing to keep in sync. Schema: MIGRATION_INTERVIEW_PREP.sql.
Soft-delete only (deleted_at).
"""
import io
import logging
import re
import threading
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from flask import (Blueprint, Response, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

from auth import login_required
from interview_question_bank import CATEGORIES as QUESTION_CATEGORIES, QUESTIONS
from tpm_round_bank import (ENTRIES as TPM_ROUND_ENTRIES, ROUNDS as TPM_ROUNDS,
                            ROUND_BRIEF as TPM_ROUND_BRIEF,
                            TOTAL_PREP_MINUTES as TPM_TOTAL_PREP_MINUTES)
from system_design_bank import (CATEGORIES as SD_CATEGORIES,
                                 DETAIL_ORDER as SD_DETAIL_ORDER,
                                 ENTRIES as SD_ENTRIES)
from ai_sde_bank import (CATEGORIES as AI_SDE_CATEGORIES,
                         ENTRIES as AI_SDE_ENTRIES)
# The module itself, for the module-level dedupe counters. Importing the
# names directly would freeze them at import time; the counters are computed
# during the bank's own import, so the module reference is the honest handle.
import ai_sde_bank as AI_SDE_BANK_MODULE
# Imported for the scheduler's bank registry only. java_bank is a plain
# data module — it imports no routes, so this cannot cycle.
import java_bank
import sd_deep_bank
import sql_bank
import ai_sde_recall
import ai_sde_summary
from services import loud
from services import thoughts_audio
from services import thoughts_service
from extensions import limiter
from supabase_client import get, post, update
from utils.user_tz import user_today

logger = logging.getLogger("daily_plan")
interview_prep_bp = Blueprint("interview_prep", __name__)

# Only the accounts in utils/prep_access.py may use these pages and APIs.
from utils.prep_access import guard_blueprint as _prep_guard  # noqa: E402
_prep_guard(interview_prep_bp)

DEFAULT_ROLE = "Senior Director, Technical Program Management"
DEFAULT_TARGET_DAYS = 42          # ~6 weeks out
STORY_TARGET = 6                  # rehearsed stories that = "story ready"
BEHAVIORAL_TARGET = 30             # practised behavioural questions that = "bank ready"
SYSDESIGN_TARGET = 20              # studied designs that = "bank ready"
DEEP_TARGET = 12                   # deep dives passed (quiz 80%+) that = "ready"
_MAX_TITLE = 140
_MAX_TEXT = 4000
_MAX_MINUTES = 24 * 60

CATEGORIES = ("behavioral", "system_design", "tpm", "executive", "domain")
CATEGORY_LABELS = {
    "behavioral": "Behavioral / STAR",
    "system_design": "System Design",
    "tpm": "TPM Competencies",
    "executive": "Executive / Leadership",
    "domain": "Domain / Role-specific",
    # The AI SDE track (see MIGRATION_AI_SDE_PREP_TRACK.sql). The coach is
    # shared by two very different runs — a senior TPM loop and a new-grad
    # AI/SDE loop — and without these its own category headings would show
    # raw keys like "dsa" on the student's page.
    "dsa": "Coding & DSA",
    "cs_fundamentals": "CS Fundamentals",
    "ml": "ML & AI Concepts",
    "ai_llm": "LLMs & Modern AI",
}

# Curated starter syllabus for a senior TPM / exec run. Seeded per-user on
# first visit, then fully editable (add / rename / delete / re-rate).
SEED_TOPICS = [
    ("behavioral", "Leading through ambiguity"),
    ("behavioral", "Influence without authority"),
    ("behavioral", "Cross-org conflict resolution"),
    ("behavioral", "Driving a company-scale program"),
    ("behavioral", "Recovering a failing program"),
    ("behavioral", "Managing up / disagreeing with an exec"),
    ("behavioral", "Hard prioritization & trade-off calls"),
    ("behavioral", "Building & scaling a team/org"),
    ("system_design", "Scalability: load balancing, caching, sharding"),
    ("system_design", "Reliability & resilience (redundancy, failover, SLAs)"),
    ("system_design", "Consistency & CAP trade-offs"),
    ("system_design", "Async & event-driven (queues, streams)"),
    ("system_design", "Data storage choices (SQL vs NoSQL, OLTP/OLAP)"),
    ("system_design", "Observability & incident management"),
    ("system_design", "Explaining technical trade-offs to execs"),
    ("tpm", "Program planning & roadmapping"),
    ("tpm", "Risk management (RAID) & mitigation"),
    ("tpm", "Dependency & critical-path management"),
    ("tpm", "Metrics, KPIs & OKRs"),
    ("tpm", "Operating cadence & governance"),
    ("tpm", "Executive status & escalation"),
    ("tpm", "Managing distributed / global teams"),
    ("executive", "Vision & strategy narrative"),
    ("executive", "Scope-of-impact stories (org / company-wide)"),
    ("executive", "Executive communication (concise, outcome-first)"),
    ("executive", "Business & financial acumen (budget, ROI)"),
    ("executive", "Talent development & culture"),
    ("executive", "\"Why you / why this role\" narrative"),
]

# STAR scaffolds so the story bank isn't a blank page.
SEED_STORIES = [
    ("Led through major ambiguity", "Ambiguity"),
    ("Recovered a failing program", "Recovery"),
    ("Influenced without authority", "Influence"),
    ("Resolved a cross-org conflict", "Conflict"),
    ("Delivered a company-scale program", "Delivery"),
    ("Made a hard prioritization call", "Prioritization"),
    ("Managed up / disagreed with a leader", "Managing up"),
    ("Built or scaled a team", "Talent"),
]

# Rotating grit / leadership quotes (deterministic pick by day).
QUOTES = [
    ("Amateurs sit and wait for inspiration; the rest of us just get up and go to work.", "Stephen King"),
    ("Discipline is choosing between what you want now and what you want most.", "Abraham Lincoln"),
    ("The will to win means nothing without the will to prepare.", "Juma Ikangaa"),
    ("Under pressure you don't rise to the occasion — you sink to your level of preparation.", "Anonymous"),
    ("Success is the sum of small efforts repeated day in and day out.", "Robert Collier"),
    ("Do the hard jobs first. The easy jobs will take care of themselves.", "Dale Carnegie"),
    ("You don't have to be great to start, but you have to start to be great.", "Zig Ziglar"),
    ("Hard choices, easy life. Easy choices, hard life.", "Jerzy Gregorek"),
    ("The expert in anything was once a beginner.", "Helen Hayes"),
    ("What you do every day matters more than what you do once in a while.", "Gretchen Rubin"),
]


def _today():
    try:
        return user_today()
    except Exception:
        return date.today()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _ensure_plan(user_id):
    """Return the user's plan row, creating it (and seeding the starter
    syllabus + story scaffolds) on first visit."""
    try:
        rows = get("interview_prep", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "*", "limit": "1",
        }) or []
    except Exception as e:
        logger.warning("interview_prep plan lookup failed (run migration?): %s", e)
        return None
    if rows:
        return rows[0]

    target = (_today() + timedelta(days=DEFAULT_TARGET_DAYS)).isoformat()
    try:
        created = post("interview_prep", {
            "user_id": user_id,
            "role_title": DEFAULT_ROLE,
            "target_date": target,
            "daily_goal_minutes": 45,
        })
    except Exception as e:
        logger.exception("interview_prep plan create failed: %s", e)
        return None

    # Seed the syllabus + story scaffolds (best-effort; page still works
    # if these fail — the user can add their own).
    try:
        post("interview_topics", [
            {"user_id": user_id, "category": c, "title": t, "position": i}
            for i, (c, t) in enumerate(SEED_TOPICS)
        ])
    except Exception:
        logger.exception("interview_prep seed topics failed")
    try:
        post("interview_stories", [
            {"user_id": user_id, "title": t, "competency": comp, "position": i}
            for i, (t, comp) in enumerate(SEED_STORIES)
        ])
    except Exception:
        logger.exception("interview_prep seed stories failed")

    return created[0] if created else None


def _streaks(by_day, goal, today):
    """(current_streak, best_streak) of consecutive days meeting the goal.
    A missed *today* doesn't zero a streak built through yesterday."""
    met = {d for d, m in by_day.items() if goal > 0 and m >= goal}
    # current
    cur = 0
    day = today if today.isoformat() in met else today - timedelta(days=1)
    while day.isoformat() in met:
        cur += 1
        day -= timedelta(days=1)
    # best
    best = run = 0
    prev = None
    for d in sorted(met):
        dd = date.fromisoformat(d)
        run = run + 1 if (prev and dd - prev == timedelta(days=1)) else 1
        best = max(best, run)
        prev = dd
    return cur, best


def _coach(readiness, days_left, expected, goal_met, minutes_today, goal, streak):
    """Pick a coach message + tone from the current state. Tones:
    scold (behind / skipping) · push (streak at risk) · cheer (on track)
    · celebrate (ahead / go-time)."""
    if days_left is not None and days_left < 0:
        return ("🎯 Interview time is here. You've done the reps — walk in as the "
                "calmest, best-prepared person in the room.", "celebrate")
    if days_left is not None and days_left <= 3 and readiness < 75:
        return (f"⏰ Only {days_left} day(s) left and you're at {readiness}%. This is "
                f"crunch time — kill the distractions and drill your weakest topics NOW.",
                "scold")
    if not goal_met:
        if streak > 0:
            return (f"🔥 Your {streak}-day streak is on the line and you're at "
                    f"{minutes_today}/{goal} min today. Don't you dare break the chain — "
                    f"finish it.", "push")
        return (f"🚫 {minutes_today}/{goal} minutes logged today. A Head-of-TPM seat "
                f"won't wait for someone who coasts. Sit down and put in the work — now.",
                "scold")
    gap = readiness - expected
    if gap < -12:
        return (f"📉 Goal met today — good. But you're behind pace at {readiness}% with "
                f"{days_left} day(s) left. You have ground to make up. Raise a weak topic "
                f"and rehearse a story tomorrow.", "scold")
    if gap > 10:
        return (f"🚀 Ahead of schedule at {readiness}% and goal met. This is exactly the "
                f"intensity that lands senior offers — keep it up.", "celebrate")
    return (f"✅ Goal met and on track at {readiness}%. Consistency like this is what gets "
            f"the offer. Same again tomorrow.", "cheer")


#: The hub's tabs. One menu item, one page: the overview, the case rounds
#: (formerly their own /tpm-rounds page), and the two big banks, each on its
#: own path so a link or the Day Board can land on the right tab.
PREP_TABS = ("overview", "cases", "behavioral", "design")


@interview_prep_bp.route("/interview-prep", methods=["GET"])
@login_required
def page():
    return render_template("interview_prep.html", initial_tab="overview")


@interview_prep_bp.route("/interview-prep/cases", methods=["GET"])
@login_required
def page_cases():
    return render_template("interview_prep.html", initial_tab="cases")


@interview_prep_bp.route("/interview-prep/behavioral", methods=["GET"])
@login_required
def page_behavioral():
    return render_template("interview_prep.html", initial_tab="behavioral")


@interview_prep_bp.route("/interview-prep/design", methods=["GET"])
@login_required
def page_design():
    return render_template("interview_prep.html", initial_tab="design")


@interview_prep_bp.route("/interview-prep/thoughts", methods=["GET"])
@login_required
def page_thoughts():
    return render_template("interview_prep.html", initial_tab="thoughts")


@interview_prep_bp.route("/ai-sde/thoughts", methods=["GET"])
@login_required
def ai_sde_thoughts_page():
    """Random thoughts for AI SDE Prep: its own shelf of questions, answered
    for a new-grad AI/ML SDE candidate rather than a Director loop."""
    return render_template("ai_sde_thoughts.html")


@interview_prep_bp.route("/interview-prep/design/<slug>", methods=["GET"])
@login_required
def page_design_deep(slug):
    """One deep dive opened directly (a shareable, bookmarkable link)."""
    if slug not in sd_deep_bank.BY_SLUG:
        return redirect("/interview-prep/design")
    return render_template("interview_prep.html", initial_tab="design", deep_slug=slug)


# Whitelisted markdown prep guides shipped in the repo, surfaced in-app.
_GUIDES = {
    "ai-sde": ("AI_SDE_INTERVIEW_PLAN.md",
               "AI SDE Interview Plan (Amazon/Google)"),
    "system-design": ("SYSTEM_DESIGN_ECOMMERCE_BANK.md",
                      "System Design Bank (reference)"),
    "system-design-summary": ("SYSTEM_DESIGN_5_PAGE_SUMMARY.md",
                              "System design in 5 pages"),
}


# ─────────── AI SDE prep bank (for the new-grad AI/ML SDE track) ──────

@interview_prep_bp.route("/ai-sde", methods=["GET"])
@login_required
def ai_sde_page():
    return render_template("ai_sde.html")


# ── The list payload, and why it is only a sliver of each entry ───────
#
# The bank is 1,120 entries and a written-up topic runs to ~16k characters
# across answer / walkthrough / plain_algo / code / examples. Serialising all
# of it produced a 3 MB JSON body on every single page load — and the list
# screen shows NONE of it, because every card is collapsed until clicked.
# Worse, the client rebuilt all 1,120 card bodies as one HTML string on every
# keystroke in the search box.
#
# So the list ships only what the collapsed header, the filters and the sort
# actually read. Everything else arrives per-card from /api/ai-sde/entry/<id>
# when the card is opened. 3 MB -> ~700 KB, and ~80 KB once gzipped.
_AI_SDE_LIST_FIELDS = (
    # Header
    "title", "cat", "difficulty", "priority", "priority_note", "prep_label",
    "tag_priority", "tag_subtopic", "tag_topic",
    # Filters
    "tag_level", "tag_format", "tag_stage", "tag_time", "tag_flag",
    # Sort, the effort line, and the "prep time & priority" line in the body
    "rank", "cat_rank", "prep_minutes", "priority_label", "priority_rank",
    "priority_total", "priority_minutes_total", "priority_minutes_cumulative",
    # Near-duplicate collapse. Only 18 of 1,120 rows carry duplicate_of, and
    # its value is a title string, so this costs ~1 KB — worth it to stop the
    # same topic being studied twice. See ai_sde_dupes.py.
    "duplicate_of",
)

#: Fields the list deliberately omits — the body of the card. Kept as an
#: explicit list rather than "everything not in _AI_SDE_LIST_FIELDS" so that
#: adding a field to the bank is a conscious decision about which side of the
#: line it falls on, not a silent 3 MB regression.
_AI_SDE_BODY_FIELDS = (
    "frequency", "answer", "walkthrough", "plain_algo", "code", "diagram",
    "example", "mnemonic", "complexity", "pitfalls", "followups", "tags",
)


def _build_ai_sde_list():
    """The thin list, built once at import rather than per request.

    The bank is a static Python literal — it cannot change between requests,
    so rebuilding 1,120 dicts on every call was pure waste (~27 ms of the
    response, before any network).
    """
    items = []
    for i, e in enumerate(AI_SDE_ENTRIES):
        item = {"id": f"ai{i}", "example_count": len(e.get("examples") or [])}
        for k in _AI_SDE_LIST_FIELDS:
            v = e.get(k)
            # Drop empties: across 1,120 entries the absent keys alone are
            # tens of kilobytes of `"field":null`.
            if v not in (None, "", [], {}):
                item[k] = v
        items.append(item)
    return items


def _build_ai_sde_search_index():
    """One lowercase haystack per entry, for server-side search.

    Held in the process (~1.2 MB) rather than shipped to every client. This
    also WIDENS search: it used to match title / answer / tags only, because
    those were the only fields the browser had. It now covers the worked
    walkthrough, the plain-English recipe, the code and the examples, which
    is what you actually want when hunting for where `heapq` or "monotonic"
    is discussed.
    """
    index = []
    for e in AI_SDE_ENTRIES:
        parts = [str(e.get("title") or "")]
        for k in _AI_SDE_BODY_FIELDS:
            v = e.get(k)
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (list, tuple)):
                parts.append(" ".join(str(x) for x in v))
        parts.extend(str(x) for x in (e.get("examples") or []))
        index.append(" ".join(parts).lower())
    return index


_AI_SDE_LIST = _build_ai_sde_list()
_AI_SDE_SEARCH = _build_ai_sde_search_index()

#: subtopic -> sibling titles, for the quiz's transfer question. Built once;
#: doing it per entry would be quadratic over 1,120 entries.
_AI_SDE_SIBLINGS = ai_sde_recall.build_sibling_index(AI_SDE_ENTRIES)

#: Built once at import, same reason as the list: the bank is a static
#: Python literal and cannot change between requests.
_AI_SDE_SUMMARIES = ai_sde_summary.build(AI_SDE_ENTRIES)
_AI_SDE_READING_COUNTS = ai_sde_summary.counts(AI_SDE_ENTRIES)


@interview_prep_bp.route("/api/ai-sde", methods=["GET"])
@login_required
def ai_sde_bank():
    """The AI SDE prep bank: DSA patterns (with worked code), ML/AI
    concepts, ML coding, ML system design, CS fundamentals, behavioral and
    company process — each explained in depth. Static reference content.

    Headers only — see _AI_SDE_LIST_FIELDS. Card bodies come from
    /api/ai-sde/entry/<id> as they are opened.
    """
    return jsonify({
        "categories": [{"key": k, "label": v} for k, v in AI_SDE_CATEGORIES.items()],
        "entries": _AI_SDE_LIST, "total": len(_AI_SDE_LIST),
        # The interview-tag vocabulary, so the filter dropdowns are built from
        # the single source of truth in ai_sde_tags.py rather than a hardcoded
        # copy in the template that would drift the moment a value is added.
        "tag_vocab": _ai_sde_tag_vocab(),
        # Near-duplicate topics. 18 pairs exist under two spellings and, because
        # the halves score alike, they land ADJACENT in the stack rank — so the
        # same topic gets met twice in a row and paid for twice. Nothing is
        # deleted: the shadow keeps its content and the page can still show it.
        "dupes": {
            "shadows": AI_SDE_BANK_MODULE.DUPLICATE_SHADOWS,
            "merge_pending": AI_SDE_BANK_MODULE.DUPLICATE_MERGE_PENDING,
            "total_minutes": AI_SDE_BANK_MODULE.TOTAL_PREP_MINUTES,
            "deduped_minutes": AI_SDE_BANK_MODULE.DEDUPED_PREP_MINUTES,
        },
        # The must-read / optional split. The RULE travels rather than the
        # answer, so the page filters on tag_priority — which it already
        # has for every row — instead of the list carrying a second field
        # per entry that says the same thing.
        "reading": {
            "mandatory_tag": ai_sde_summary.MANDATORY_TAG,
            "mandatory_priority": ai_sde_summary.MANDATORY_PRIORITY,
            "rule": ai_sde_summary.RULE_TEXT,
            "counts": _AI_SDE_READING_COUNTS,
        },
    })


@interview_prep_bp.route("/api/ai-sde/summaries", methods=["GET"])
@login_required
def ai_sde_summaries():
    """One line per topic, for skimming without opening anything.

    A SEPARATE request on purpose. Folded into /api/ai-sde these take the
    list from 57 KB gzipped to 135 KB — more than doubling the payload
    that page load actually waits on, to add a line she may not read on
    most rows. Fetched after the list has rendered, they cost nothing
    anyone is waiting for, and a page that never gets them is a page
    without summaries rather than a page that failed.
    """
    return jsonify({"summaries": _AI_SDE_SUMMARIES,
                    "total": len(_AI_SDE_SUMMARIES)})


@interview_prep_bp.route("/api/ai-sde/search", methods=["GET"])
@login_required
def ai_sde_search():
    """Ids of the entries matching `q`, for the client to intersect with its
    own filters.

    Search moved to the server when the card bodies stopped being shipped —
    the browser no longer holds the prose to search. Returning ids rather
    than entries keeps this a few kilobytes and leaves every other filter
    (category, difficulty, the six interview tags, unstudied) client-side and
    instant.

    Multiple words are ANDed, which matches how people narrow a list.
    """
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify({"q": "", "ids": None, "total": len(_AI_SDE_LIST)})
    terms = [t for t in q.split() if t][:8]      # a cap, so a pasted essay is cheap
    ids = [f"ai{i}" for i, hay in enumerate(_AI_SDE_SEARCH)
           if all(t in hay for t in terms)]
    return jsonify({"q": q, "ids": ids, "total": len(ids)})


#: Query-string name -> entry field, for the six filterable interview tags.
_AI_SDE_TAG_PARAMS = {
    "tpriority": "tag_priority", "ttopic": "tag_topic", "tsub": "tag_subtopic",
    "tformat": "tag_format", "tstage": "tag_stage", "ttime": "tag_time",
    "tlevel": "tag_level",
}


def _ai_sde_tag_vocab():
    """The controlled vocabulary, plus the per-topic subtopic map."""
    import ai_sde_tags as tags
    return {
        "topic": list(tags.TOPICS), "level": list(tags.LEVELS),
        "priority": list(tags.PRIORITIES), "format": list(tags.FORMATS),
        "stage": list(tags.STAGES), "time": list(tags.TIMES),
        "subtopics": {k: list(v) for k, v in tags.SUBTOPICS.items()},
    }


def _ai_sde_tag_select(items):
    """Narrow by the interview tags. Returns (items, [label bits]).

    Unknown values are ignored rather than returning an empty page, because a
    stale bookmark should degrade to a wider list, not to nothing.
    """
    vocab = _ai_sde_tag_vocab()
    legal = {
        "tag_topic": set(vocab["topic"]), "tag_level": set(vocab["level"]),
        "tag_priority": set(vocab["priority"]), "tag_format": set(vocab["format"]),
        "tag_stage": set(vocab["stage"]), "tag_time": set(vocab["time"]),
        "tag_subtopic": {s for subs in vocab["subtopics"].values() for s in subs},
    }
    bits = []
    for param, field in _AI_SDE_TAG_PARAMS.items():
        value = (request.args.get(param) or "").strip()
        if not value or value not in legal[field]:
            continue
        items = [it for it in items if it.get(field) == value]
        bits.append(value)
    return items, bits


@interview_prep_bp.route("/api/ai-sde/entry/<entry_id>", methods=["GET"])
@login_required
def ai_sde_entry(entry_id):
    """The whole body of one topic, fetched when its card is opened.

    This used to return only `examples`. It now carries every field in
    _AI_SDE_BODY_FIELDS as well, because the list endpoint stopped shipping
    them — one request per card actually opened, instead of 1,120 bodies on
    page load for the handful anyone reads.
    """
    try:
        idx = int(entry_id[2:]) if entry_id.startswith("ai") else -1
    except ValueError:
        idx = -1
    if not 0 <= idx < len(AI_SDE_ENTRIES):
        return jsonify({"error": "unknown entry"}), 404
    e = AI_SDE_ENTRIES[idx]
    body = {k: e[k] for k in _AI_SDE_BODY_FIELDS if e.get(k) not in (None, "", [], {})}
    body["id"] = entry_id
    body["examples"] = e.get("examples") or []
    # The recall quiz rides along with the body rather than costing a second
    # round trip — it is derived from these very fields, so it is already
    # paid for. See ai_sde_recall.py for why none of it is hand-written.
    body["quiz"] = ai_sde_recall.build(e, _AI_SDE_SIBLINGS)
    return jsonify(body)


# ══════════════════════════════════════════════════════════════════════
# AI SDE → CALENDAR — drop a topic onto a specific day
#
# The ask was a study plan you can *see*: pick a topic on /ai-sde, pick a
# day, and have it show up in the three places that already exist rather
# than in a fourth one invented for it —
#
#   * the AISDEPrep project, so the whole syllabus has one home;
#   * the calendar grid for that day;
#   * the Quick Bucket, so it is in front of her without opening the
#     calendar at all.
#
# WHY MIDNIGHT WHEN NO TIME IS GIVEN. planner_v2.js builds the grid with
# `for (let hour = 0; hour < 24; hour++)`, so hour 0 is the first row on
# the page. A 00:00 start therefore pins the topic to the very top of the
# day the way an all-day row does in Google Calendar — visible the moment
# the day opens, and out of the way of anything actually timed. It is a
# deliberate position, not a null standing in for one.
#
# WHY THIS DOES NOT POST TO /api/v2/events. That endpoint runs
# get_conflicts() and returns 409 unless the caller forces it. Stacking
# five topics at 00:00 on the same morning is the *intended* use here, so
# every one after the first would be rejected for overlapping the last.
# This writes the daily_events row directly, which is the same table the
# calendar reads.
#
# Three inserts, no transaction. If a later one fails the earlier ones
# survive, which is the right way round: the project task is the record
# of what she planned to study, and the other two are views onto it.
# ══════════════════════════════════════════════════════════════════════

#: The banks that can be scheduled onto a day, and the project each one
#: lands in. Looked up by name — there is no project id stored anywhere,
#: because the name IS the handle.
#:
#: Each bank names the list its entries come from, the FIELD that holds
#: the topic's text (the behavioural bank calls it `q`, the other two
#: `title`), and the prefix its ids carry. Keeping the three differences
#: in a table beats three near-identical endpoints: the scheduling itself
#: — get-or-create the project, write the task, the event, the bucket row,
#: mirror to Google — is the same work whichever bank asked for it.
PREP_BANKS = {
    "ai_sde": {
        "project": "AISDEPrep",
        "desc": "AI/SDE interview prep. Topics scheduled from /ai-sde land here.",
        "label": "AI/SDE prep",
        "page": "/ai-sde",
    },
    "java": {
        "project": "JavaPrep",
        "desc": "Java core interview prep. Topics scheduled from /java land here.",
        "label": "Java prep",
        "page": "/java",
    },
    "sql": {
        "project": "SQLPrep",
        "desc": "SQL interview prep. Topics scheduled from /sql land here.",
        "label": "SQL prep",
        "page": "/sql",
    },
    "behavioral": {
        "project": "InterviewPrep",
        "desc": "Behavioural / TPM interview prep. Questions scheduled from "
                "/interview-prep land here.",
        "label": "Interview prep",
        "page": "/interview-prep",
    },
    "tpm": {
        "project": "CaseRoundsPrep",
        "desc": "TPM / engineering-leadership case rounds. Cases scheduled "
                "from /interview-prep/cases land here.",
        "label": "Case rounds",
        "page": "/interview-prep/cases",
    },
    "sddeep": {
        "project": "SystemDesignPrep",
        "desc": "System design deep dives. Designs scheduled from "
                "/interview-prep/design land here.",
        "label": "System design",
        "page": "/interview-prep/design",
    },
}

#: bank key -> (entry list, the field holding the topic text, id prefix).
#: A callable for the list so the module-level import order cannot matter.
_BANK_SOURCES = {
    "ai_sde":     (lambda: AI_SDE_ENTRIES,     "title", "ai"),
    "java":       (lambda: java_bank.ENTRIES,  "title", "j"),
    "sql":        (lambda: sql_bank.ENTRIES,   "title", "sq"),
    "behavioral": (lambda: QUESTIONS,          "q",     "q"),
    "tpm":        (lambda: TPM_ROUND_ENTRIES,  "title", "t"),
    "sddeep":     (lambda: sd_deep_bank.DESIGNS, "title", "dd"),
}

# Kept as the old names because MIGRATION_AISDEPREP.sql seeds this one by
# name and the tests assert on it.
AI_SDE_PROJECT_NAME = PREP_BANKS["ai_sde"]["project"]
AI_SDE_PROJECT_DESC = PREP_BANKS["ai_sde"]["desc"]

AI_SDE_MIDNIGHT = "00:00"

#: Bounds on the calendar block. The floor stops a 5-minute topic from
#: rendering as an unclickable sliver; the ceiling stops a 6-hour one
#: from swallowing the whole day in a single bar. Anything longer is a
#: multi-session topic and wants more than one calendar entry anyway.
AI_SDE_MIN_BLOCK = 15
AI_SDE_MAX_BLOCK = 180
AI_SDE_DEFAULT_BLOCK = 30

_AI_SDE_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_AI_SDE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _pg_eq(value):
    """A PostgREST ``eq.`` filter for a free-text value.

    THIS USED TO WRAP THE VALUE IN DOUBLE QUOTES AND MATCHED NOTHING AT ALL.
    The reasoning was sound — 386 of the 1,120 topic titles contain a comma,
    a parenthesis or a colon, and PostgREST does read those as filter syntax
    — but the fix was already in place one layer down: supabase_client hands
    params to `requests`, which URL-encodes them, so a comma arrives as %2C
    and is decoded back into the value. The quotes were then matched
    LITERALLY, against values that contain no quotes.

    Measured against live data before and after: the quoted form returned 0
    rows for both a plain name ("SQLPrep") and a comma-bearing title ("ORDER
    BY, and where NULL sorts"); the plain form returned 10 and 1.

    WHAT IT COST, because a silently always-false filter is the worst kind.
    Every caller of this is an EXISTENCE check, so each one silently decided
    "not there" every single time:
      * _ensure_prep_project never found the bank's project, so every Plan
        click created a new one — ten SQLPrep projects for one user in four
        minutes.
      * the already-scheduled check never matched, so this endpoint's
        documented idempotence did nothing.
      * the Quick Bucket dedupe never matched either.
    """
    return "eq." + str(value)


def _get_optional(table, params, optional):
    """``get()`` that survives a filter column the install doesn't have yet.

    ``post()`` and ``update()`` already strip a column Supabase reports as
    missing and retry; ``get()`` does not, so a filter on a column added by
    a migration that hasn't been run raises 400 and the whole request
    500s. That is exactly what happened here: ``project_tasks.is_deleted``
    is in MIGRATION_ALL_TABLES.sql but an older install never got the
    line, and the dedupe lookup filters on it.

    Retries once with `optional` keys dropped. Dropping them widens the
    result — a soft-deleted row would come back — and for the two callers
    here that is the safe direction: it makes "already scheduled" more
    likely, and the failure mode of that is a no-op instead of a
    duplicate.
    """
    try:
        return get(table, params=params) or []
    except Exception:
        trimmed = {k: v for k, v in params.items() if k not in optional}
        if trimmed == params:
            raise
        logger.warning("%s: retrying lookup without %s — run MIGRATION_AISDEPREP.sql",
                       table, ", ".join(sorted(optional)))
        return get(table, params=trimmed) or []


def _ai_sde_clean_time(raw):
    """``"9:05"`` → ``"09:05"``; empty or unparseable → midnight.

    An unreadable time is not an error here. The caller asked to schedule
    a topic; refusing over a malformed time field would throw the whole
    request away to protect a field that has a documented default.
    """
    m = _AI_SDE_TIME_RE.match((raw or "").strip())
    if not m:
        return AI_SDE_MIDNIGHT
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _ai_sde_end_time(start, minutes):
    """End of the calendar block, clamped inside the same day.

    A block that would spill past midnight is cut to 23:59 rather than
    wrapping — wrapping would put half the study session on a day the
    user never picked, and the grid would draw it there.
    """
    try:
        length = int(minutes)
    except (TypeError, ValueError):
        length = AI_SDE_DEFAULT_BLOCK
    length = max(AI_SDE_MIN_BLOCK, min(length or AI_SDE_DEFAULT_BLOCK, AI_SDE_MAX_BLOCK))

    base = datetime.strptime(start, "%H:%M")
    end = base + timedelta(minutes=length)
    if end.day != base.day:          # crossed into tomorrow
        return "23:59"
    return end.strftime("%H:%M")


def _find_prep_project(user_id, bank):
    """The bank's project id, or None. NEVER creates one.

    _ensure_prep_project creates on miss, which is right when scheduling and
    wrong on a page load — merely opening /sql should not bring a SQLPrep
    project into existence.
    """
    rows = get("projects", params={
        "user_id": f"eq.{user_id}",
        "name": _pg_eq(PREP_BANKS[bank]["project"]),
        "is_archived": "eq.false",
        "select": "project_id",
        "order": "created_at.asc",
        "limit": "1",
    }) or []
    return rows[0]["project_id"] if rows else None


def _ensure_prep_project(user_id, bank):
    """Return the project id for this bank, creating it if it isn't there.

    Select-then-insert, and on an insert failure it selects again: the
    partial unique index from MIGRATION_AISDEPREP.sql turns a double-tap
    race into a constraint error, and the row the other request just
    created is exactly what this one wanted. Returns None if the project
    genuinely cannot be resolved, and the caller reports that rather than
    scattering tasks into a project that doesn't exist.
    """
    spec = PREP_BANKS[bank]
    name = spec["project"]

    # ONE lookup, shared with the read-only path. It used to be a private
    # copy here, which is how the two came to differ: this one had no
    # ordering, so with duplicates present it could return a different
    # project on each call and scatter one bank's tasks across several.
    def _find():
        return _find_prep_project(user_id, bank)

    found = _find()
    if found:
        return found

    # A miss here means the project does not exist yet — which is true
    # exactly ONCE per user per bank. If this line keeps firing for the same
    # pair, the LOOKUP is broken, not the data. That is precisely how ten
    # SQLPrep projects appeared in four minutes and nobody noticed.
    loud.created_what_should_exist(f"the {name} project",
                                   user_id=user_id, bank=bank)
    try:
        created = post("projects", {
            "user_id": user_id,
            "name": name,
            "description": spec["desc"],
            "is_archived": False,
        }, prefer="return=representation")
        if created:
            return created[0]["project_id"]
    except Exception:
        logger.warning("%s project insert failed; re-selecting", name, exc_info=True)

    return _find()


def _ensure_ai_sde_project(user_id):
    """Back-compat shim for the AI/SDE bank's own project."""
    return _ensure_prep_project(user_id, "ai_sde")


def _prep_lookup(bank, entry_id, title):
    """Resolve the topic being scheduled to (title, prep_minutes).

    The id is honoured when it still points at the same topic, but the
    TITLE is what decides — every one of these banks numbers its entries
    by POSITION (``ai42``, ``j7``, ``q19``), and a position shifts the
    moment an entry is added or deduped. It is the same reason progress
    and recall are keyed by title. A stale tab holding ``ai42`` must not
    schedule whatever moved into slot 42 since it loaded.

    Returns (None, None) when neither the id nor the title resolves, and
    the caller 404s rather than scheduling a guess.
    """
    source, field, prefix = _BANK_SOURCES[bank]
    entries = source()
    title = (title or "").strip()

    idx = -1
    if entry_id and entry_id.startswith(prefix):
        try:
            idx = int(entry_id[len(prefix):])
        except ValueError:
            idx = -1

    if 0 <= idx < len(entries):
        e = entries[idx]
        if not title or e[field] == title:
            return e[field], e.get("prep_minutes")

    # Id was missing, out of range, or has drifted — fall back to the title.
    for e in entries:
        if e[field] == title:
            return e[field], e.get("prep_minutes")
    return None, None


def _ai_sde_lookup(entry_id, title):
    """Back-compat shim for the AI/SDE bank."""
    return _prep_lookup("ai_sde", entry_id, title)


#: "AISDEPrep · Balanced Binary Tree" -> ("ai_sde", "Balanced Binary Tree").
#: The separator alone is not enough to recognise one of these: a bucket row
#: reading "Walking (Pomodoro · 25m)" contains it too. The PROJECT NAME
#: prefix is what identifies a prep row.
_BUCKET_SEP = " · "


def parse_bucket_text(text):
    """The bank and topic a Quick Bucket row came from, or (None, None).

    Exported because the bucket's own done/reopen endpoints need to walk
    this backwards — ticking a row there has to reach the topic it came
    from, not just the row.
    """
    text = (text or "").strip()
    for bank, spec in PREP_BANKS.items():
        prefix = spec["project"] + _BUCKET_SEP
        if text.startswith(prefix):
            title = text[len(prefix):].strip()
            return (bank, title) if title else (None, None)
    return (None, None)


def complete_prep_artifacts(user_id, bank, title, done, include_bucket=True):
    """Close (or reopen) everything a scheduled topic created.

    `include_bucket` exists to stop the two directions chasing each other.
    When the BUCKET is the thing being ticked, its own endpoint has already
    updated that row, so re-writing it here would be pointless work at best
    and a loop at worst.

    Returns a count per surface. Every failure is logged and swallowed: a
    tick that half-propagates is better than a tick that 500s.
    """
    if bank not in PREP_BANKS:
        return {}
    spec = PREP_BANKS[bank]
    touched = {"tasks": 0, "events": 0, "bucket": 0, "progress": 0}

    project_id = _find_prep_project(user_id, bank)
    if not project_id:
        # Not automatically wrong — most topics are never scheduled — but if
        # the caller is completing a topic that WAS on a day, this is where
        # the trail goes cold.
        loud.bailed("prep completion (task)", "no project for this bank",
                    bank=bank, user_id=user_id)
    if project_id:
        try:
            update("project_tasks",
                   params={"user_id": f"eq.{user_id}",
                           "project_id": f"eq.{project_id}",
                           "task_text": _pg_eq(title),
                           "is_deleted": "eq.false"},
                   json={"status": "done" if done else "open"})
            touched["tasks"] = 1
        except Exception:
            logger.warning("prep complete: task update failed for %r", title,
                           exc_info=True)

    try:
        rows = get("daily_events", params={
            "user_id": f"eq.{user_id}",
            "title": _pg_eq(title),
            "is_deleted": "eq.false",
            "select": "id,description",
            "limit": "200",
        }) or []
        for r in rows:
            # Only the rows the scheduler wrote. A real appointment that
            # happens to share a title is not this topic.
            if spec["page"] not in (r.get("description") or ""):
                continue
            update("daily_events",
                   params={"id": f"eq.{r['id']}", "user_id": f"eq.{user_id}"},
                   json={"status": "done" if done else "open"})
            touched["events"] += 1
    except Exception:
        logger.warning("prep complete: event update failed for %r", title,
                       exc_info=True)

    if include_bucket:
        bucket_text = f"{spec['project']}{_BUCKET_SEP}{title}"[:500]
        try:
            update("quick_bucket",
                   params={"user_id": f"eq.{user_id}",
                           "text": _pg_eq(bucket_text),
                           "is_deleted": "eq.false"},
                   json={"is_done": done,
                         "done_at": _iso_now() if done else None,
                         "top5_date": None, "top5_position": None})
            touched["bucket"] = 1
        except Exception:
            logger.warning("prep complete: bucket update failed for %r", title,
                           exc_info=True)

    # The STUDY record, so the bank page's own checkbox agrees. /ai-sde,
    # the case rounds and the behavioural bank keep this on the server;
    # /java and /sql hold it in
    # localStorage, which nothing here can reach — the client reconciles
    # those from the task status instead.
    if bank == "ai_sde" and title in _AI_SDE_TITLES:
        try:
            post("ai_sde_progress?on_conflict=user_id,entry_title",
                 {"user_id": user_id, "entry_title": title,
                  "studied": bool(done),
                  "studied_at": _iso_now() if done else None,
                  "updated_at": _iso_now()},
                 prefer="resolution=merge-duplicates,return=minimal")
            touched["progress"] = 1
        except Exception:
            logger.warning("prep complete: progress update failed for %r", title,
                           exc_info=True)
    # The case rounds and the behavioural bank keep theirs in prep_progress.
    elif bank in ("tpm", "behavioral") and title in _progress_maps(bank)[1]:
        try:
            post("prep_progress?on_conflict=user_id,bank,entry_title",
                 {"user_id": user_id, "bank": bank, "entry_title": title,
                  "done": bool(done), "done_at": _iso_now() if done else None,
                  "updated_at": _iso_now()},
                 prefer="resolution=merge-duplicates,return=minimal")
            touched["progress"] = 1
        except Exception:
            logger.warning("prep complete: progress update failed for %r", title,
                           exc_info=True)

    return touched


@interview_prep_bp.route("/api/prep/notes", methods=["GET"])
@login_required
def prep_notes_list():
    """Every note this user has for one bank. ``?bank=ai_sde``

    Returned as {title: note} in one request rather than a query per card:
    a bank page draws 1,120 cards, and a note lookup each would be absurd.
    """
    user_id = session["user_id"]
    bank = (request.args.get("bank") or "ai_sde").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400

    try:
        rows = get("prep_notes", params={
            "user_id": f"eq.{user_id}",
            "bank": _pg_eq(bank),
            "select": "entry_title,note,updated_at",
            "limit": "5000",
        }) or []
    except Exception as exc:
        text = str(exc)
        if "prep_notes" in text or "does not exist" in text or "schema cache" in text:
            # An unrun migration is a setup step, not an error. The page
            # hides the notes box rather than showing one that silently
            # throws away what she types into it.
            logger.warning("prep notes unavailable — run MIGRATION_PREP_NOTES.sql")
            return jsonify({"bank": bank, "notes": {}, "available": False,
                            "migration": "MIGRATION_PREP_NOTES.sql"}), 200
        raise

    notes = {}
    for r in rows:
        title = (r.get("entry_title") or "").strip()
        if title and (r.get("note") or "").strip():
            notes[title] = {"note": r["note"], "updated_at": r.get("updated_at") or ""}
    return jsonify({"bank": bank, "notes": notes, "available": True})


@interview_prep_bp.route("/api/prep/notes", methods=["POST"])
@login_required
def prep_notes_save():
    """Write one note. Body: ``{bank, title, note}``.

    UPSERT on (user_id, bank, entry_title), which the migration's unique
    index is what makes possible — without it a second save would create a
    second row and the first would silently become unreachable.

    AN EMPTY NOTE IS A DELETE, because that is what clearing the box means.
    Soft, per project convention: the row is kept with an empty note rather
    than removed, so nothing has to distinguish "never wrote one" from
    "cleared it" and an accidental clear is recoverable from the table.
    """
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}

    bank = (data.get("bank") or "").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    # Bounded, because this lands in a text column and the client is not
    # the only thing that can post here.
    note = (data.get("note") or "")[:20000]

    try:
        # ?on_conflict= NAMES THE TARGET, and without it this fails on the
        # SECOND save of any note. PostgREST infers the conflict target from
        # the PRIMARY KEY unless told otherwise, and the primary key here is
        # a generated uuid that never collides — so merge-duplicates had
        # nothing to merge on and returned 409. Caught by exercising the
        # real endpoint twice rather than once.
        post("prep_notes?on_conflict=user_id,bank,entry_title",
             {"user_id": user_id, "bank": bank, "entry_title": title,
              "note": note, "updated_at": _iso_now()},
             prefer="resolution=merge-duplicates,return=minimal")
    except Exception as exc:
        text = str(exc)
        if "prep_notes" in text or "does not exist" in text or "schema cache" in text:
            logger.warning("prep notes not saved — run MIGRATION_PREP_NOTES.sql")
            return jsonify({"error": "Notes are not set up yet. Run "
                                     "MIGRATION_PREP_NOTES.sql in Supabase.",
                            "migration": "MIGRATION_PREP_NOTES.sql"}), 503
        logger.warning("prep note save failed for %r", title, exc_info=True)
        return jsonify({"error": "Couldn't save that note — please retry."}), 502

    return jsonify({"status": "ok", "bank": bank, "title": title,
                    "length": len(note)})


@interview_prep_bp.route("/api/prep/complete", methods=["POST"])
@login_required
def prep_complete():
    """Mark everything a scheduled topic created as done — or undo it.

    Body: ``{bank, title, done}``

    WHY THIS EXISTS. Ticking a topic as studied used to update only the
    STUDY record (ai_sde_progress on /ai-sde, localStorage on /java and
    /sql). But scheduling a topic writes THREE other rows — a project task,
    a calendar event and a Quick Bucket line — and none of them heard about
    it. So the Day Board went on showing the topic as outstanding and the
    bucket went on listing it, after it had been done. The tick was true in
    one place and false in three.

    REVERSIBLE, because un-ticking has to work too. `done: false` puts all
    three back to open rather than leaving a topic permanently closed after
    a mis-click.

    SILENT WHEN NOTHING WAS SCHEDULED. Most topics are never put on a day,
    and ticking one of those is not an error — it just has nothing else to
    update.
    """
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}

    bank = (data.get("bank") or "ai_sde").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400
    done = bool(data.get("done", True))

    # The work itself is shared with the Quick Bucket's own done/reopen
    # endpoints, so a tick in either place lands in exactly the same rows.
    touched = complete_prep_artifacts(user_id, bank, title, done)

    return jsonify({"status": "ok", "bank": bank, "title": title,
                    "done": done, "touched": touched})


@interview_prep_bp.route("/api/prep/scheduled", methods=["GET"])
@login_required
def prep_scheduled():
    """When each topic of a bank is planned for. ``?bank=ai_sde``

    Returns ``{title: {plan_date, start_time, status}}`` so a bank page can
    say "Planned Fri 29 Aug, 09:00" on the card itself. Until now the only
    way to find out whether you had already scheduled something was to open
    the calendar, which is the wrong place to answer a question you are
    asking while looking at the topic.

    READ FROM project_tasks, NOT daily_events. The scheduler writes one task
    PER TOPIC even when a bulk selection collapses into a single calendar
    block, so the task is the only per-topic record of what was planned.

    WHETHER A DATE HAS ELAPSED IS THE CLIENT'S CALL. The comparison needs
    the reader's own clock, and the server's idea of "now" is a different
    machine's. So the raw date and time go over the wire and the page
    decides the colour.
    """
    user_id = session["user_id"]
    bank = (request.args.get("bank") or "ai_sde").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400

    project_id = _find_prep_project(user_id, bank)
    if not project_id:
        # No project means nothing has ever been scheduled for this bank.
        # That is an empty answer, not an error, and it must not CREATE the
        # project — a page load is not a reason to make one.
        return jsonify({"bank": bank, "scheduled": {}})

    try:
        rows = get("project_tasks", params={
            "user_id": f"eq.{user_id}",
            "project_id": f"eq.{project_id}",
            "is_deleted": "eq.false",
            "select": "task_text,plan_date,start_time,status",
            "limit": "2000",
        }) or []
    except Exception:
        logger.warning("prep scheduled read failed for %s", bank, exc_info=True)
        return jsonify({"bank": bank, "scheduled": {}})

    out = {}
    for r in rows:
        title = (r.get("task_text") or "").strip()
        if not title:
            continue
        plan_date = r.get("plan_date") or ""
        # Keep the EARLIEST plan for a topic scheduled more than once — that
        # is the commitment; a later one is a repeat, and showing the latest
        # would hide an overdue first attempt.
        prev = out.get(title)
        if prev and prev["plan_date"] and plan_date > prev["plan_date"]:
            continue
        out[title] = {
            "plan_date": plan_date,
            # "00:00:00" is the scheduler's stand-in for "no time given", so
            # it is reported as absent rather than as midnight — a card
            # reading "at 12:00 AM" would look like a real appointment.
            "start_time": (r.get("start_time") or "")[:5] if
                          (r.get("start_time") or "")[:5] not in ("", "00:00") else "",
            "status": (r.get("status") or "open"),
        }
    return jsonify({"bank": bank, "scheduled": out})


@interview_prep_bp.route("/api/prep/schedule-bulk", methods=["POST"])
@login_required
def prep_schedule_bulk():
    """Put SEVERAL topics from one bank into ONE study block.

    Body: ``{bank, topics: [{id?, title?}, ...], plan_date, start_time?,
    duration_min?, title?}``

    ONE CALENDAR EVENT, NOT ONE PER TOPIC. Selecting six topics for
    Saturday morning means one two-hour block on the calendar whose
    DESCRIPTION lists what is in it — not six stacked entries that make the
    day unreadable. This mirrors what the Quick Bucket bulk move does, for
    the same reason.

    THE PROJECT TASKS ARE STILL ONE PER TOPIC, because that is where
    progress is tracked: a single "study block" task cannot be half done.
    So the calendar gets the block and the project gets the topics.

    DURATION DEFAULTS TO THE SUM OF THE TOPICS' OWN prep_minutes, which is
    the whole reason that field exists — the bank already knows a
    six-topic session is 3h40m, and making the user work that out by hand
    would be asking them to re-derive something on the page in front of
    them.

    Topics already scheduled on that day are skipped rather than stacked,
    matching the single-topic endpoint's idempotence.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}

    bank = (data.get("bank") or "ai_sde").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400
    spec = PREP_BANKS[bank]

    plan_date = (data.get("plan_date") or "").strip()
    if not _AI_SDE_DATE_RE.match(plan_date):
        return jsonify({"error": "plan_date must be YYYY-MM-DD"}), 400
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return jsonify({"error": "plan_date is not a real date"}), 400

    raw_topics = data.get("topics") or []
    if not isinstance(raw_topics, list) or not raw_topics:
        return jsonify({"error": "Select at least one topic first."}), 400
    if len(raw_topics) > 60:
        # A cap with a reason: past this the description stops being
        # readable in a calendar cell and the block stops being a session.
        return jsonify({"error": "That is too many for one block — 60 max."}), 400

    resolved, unknown = [], []
    for t in raw_topics:
        if isinstance(t, str):
            t = {"title": t}
        title, mins = _prep_lookup(bank, (t or {}).get("id"), (t or {}).get("title"))
        if not title:
            unknown.append((t or {}).get("title") or (t or {}).get("id"))
            continue
        if any(r[0] == title for r in resolved):
            continue                       # the same topic picked twice
        resolved.append((title, mins or 0))

    if not resolved:
        return jsonify({"error": "None of those topics could be found."}), 404

    total_minutes = sum(m for _, m in resolved)
    try:
        duration = int(data.get("duration_min") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        duration = total_minutes or 30 * len(resolved)
    duration = max(5, min(12 * 60, duration))

    start_time = _ai_sde_clean_time(data.get("start_time"))
    end_time = _ai_sde_end_time(start_time, duration)

    project_id = _ensure_prep_project(user_id, bank)
    if not project_id:
        return jsonify({"error": f"could not open the {spec['project']} project"}), 500

    # ── 1. One project task per topic, skipping what is already there ──
    created, skipped = [], []
    epic_id = None
    try:
        from routes.projects import _default_epic_id
        epic_id = _default_epic_id(user_id, project_id)
    except Exception:
        logger.warning("%s: default epic unresolved, filing tasks flat",
                       spec["project"], exc_info=True)

    for title, mins in resolved:
        existing = _get_optional("project_tasks", {
            "user_id": f"eq.{user_id}",
            "project_id": f"eq.{project_id}",
            "plan_date": f"eq.{plan_date}",
            "task_text": _pg_eq(title),
            "is_deleted": "eq.false",
            "select": "task_id",
            "limit": "1",
        }, optional={"is_deleted"})
        if existing:
            skipped.append(title)
            continue

        payload = {
            "user_id": user_id,
            "project_id": project_id,
            "task_text": title,
            "status": "open",
            "priority": "medium",
            "plan_date": plan_date,
            "start_time": start_time,
            "due_date": plan_date,
            "notes": f"{spec['label']} topic · scheduled from {spec['page']}",
            "is_deleted": False,
        }
        if mins:
            payload["planned_hours"] = round(mins / 60.0, 2)
        if epic_id:
            payload["epic_id"] = epic_id
        try:
            post("project_tasks", payload, prefer="return=minimal")
            created.append(title)
        except Exception:
            logger.exception("%s: bulk task failed for %r", spec["project"], title)

    # ── 2. One calendar block, with the topics as its description ──────
    #
    # Written even when every topic was already scheduled: the user asked
    # for a block at this time, and refusing to create it because the tasks
    # exist would look like the button did nothing.
    lines = [f"• {t}" for t, _ in resolved]
    hours, rem = divmod(total_minutes, 60)
    effort = (f"{hours}h {rem}m" if hours and rem else
              f"{hours}h" if hours else f"{rem}m") if total_minutes else ""
    header = f"{spec['label']} · {len(resolved)} topic" + ("s" if len(resolved) != 1 else "")
    if effort:
        header += f" · {effort} of prep"
    description = header + "\n\n" + "\n".join(lines) + f"\n\nOpen them at {spec['page']}"

    block_title = (data.get("title") or "").strip()
    if not block_title:
        block_title = (resolved[0][0] if len(resolved) == 1
                       else f"{spec['label']}: {len(resolved)} topics")
    block_title = block_title[:200]

    event_id = None
    event_row = None
    try:
        ev = post("daily_events", {
            "user_id": user_id,
            "plan_date": plan_date,
            "start_time": start_time,
            "end_time": end_time,
            "title": block_title,
            "description": description,
            "priority": "medium",
            "reminder_minutes": 10,
            "is_deleted": False,
        }, prefer="return=representation")
        event_row = (ev or [None])[0]
        event_id = (event_row or {}).get("id")
    except Exception:
        logger.exception("%s: bulk calendar block failed on %s", spec["project"], plan_date)
        return jsonify({"error": "Couldn't create the calendar block."}), 502

    # ── 2b. Mirror to Google, off the request ──────────────────────────
    # Same shape as the single-topic path: a Google round trip is a second
    # or more and the in-app calendar is already correct.
    if event_row:
        try:
            connected = bool(get("user_google_tokens",
                                 params={"user_id": f"eq.{user_id}"}) or [])
        except Exception:
            connected = False
        if connected:
            def _mirror(row=event_row, uid=user_id):
                try:
                    from services import events_calendar_service as events_cal
                    gid = events_cal.sync_create(uid, row)
                    if gid:
                        update("daily_events",
                               params={"id": f"eq.{row['id']}", "user_id": f"eq.{uid}"},
                               json={"google_event_id": gid})
                except Exception:
                    logger.exception("Google mirror failed for %r", row.get("title"))
            threading.Thread(target=_mirror, daemon=True).start()

    return jsonify({
        "status": "ok",
        "bank": bank,
        "plan_date": plan_date,
        "start_time": start_time,
        "end_time": end_time,
        "event_id": event_id,
        "title": block_title,
        "count": len(resolved),
        "scheduled": created,
        "already_there": skipped,
        "unknown": [u for u in unknown if u],
        "total_minutes": total_minutes,
    })


@interview_prep_bp.route("/api/prep/schedule", methods=["POST"])
@interview_prep_bp.route("/api/ai-sde/schedule", methods=["POST"])
@login_required
def prep_schedule():
    """Put one topic from one bank on one day.

    Body: ``{bank?, id?, title?, plan_date, start_time?, duration_min?,
    quick_bucket?}``. ``bank`` is a key of PREP_BANKS and decides which
    project the topic lands in; it defaults to ``ai_sde`` so the older
    /api/ai-sde/schedule path keeps working for a page served from cache.
    Either ``id`` or ``title`` identifies the topic; ``plan_date`` is
    required; everything else has a default.

    Idempotent per (bank, topic, day): tapping Plan twice for the same
    topic on the same date reports what is already there instead of
    stacking a second copy of it in all three places.
    """
    user_id = session["user_id"]
    data = request.get_json(force=True) or {}

    bank = (data.get("bank") or "ai_sde").strip()
    if bank not in PREP_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400

    plan_date = (data.get("plan_date") or "").strip()
    if not _AI_SDE_DATE_RE.match(plan_date):
        return jsonify({"error": "plan_date must be YYYY-MM-DD"}), 400
    try:
        date.fromisoformat(plan_date)
    except ValueError:
        return jsonify({"error": "plan_date is not a real date"}), 400

    title, prep_minutes = _prep_lookup(bank, data.get("id"), data.get("title"))
    if not title:
        return jsonify({"error": "unknown topic"}), 404

    start_time = _ai_sde_clean_time(data.get("start_time"))
    end_time = _ai_sde_end_time(start_time, data.get("duration_min") or prep_minutes)
    untimed = start_time == AI_SDE_MIDNIGHT and not (data.get("start_time") or "").strip()

    spec = PREP_BANKS[bank]
    project_id = _ensure_prep_project(user_id, bank)
    if not project_id:
        return jsonify({"error": f"could not open the {spec['project']} project"}), 500

    # ── Already on this day? ────────────────────────────────────────
    existing = _get_optional("project_tasks", {
        "user_id": f"eq.{user_id}",
        "project_id": f"eq.{project_id}",
        "plan_date": f"eq.{plan_date}",
        "task_text": _pg_eq(title),
        "is_deleted": "eq.false",
        "select": "task_id",
        "limit": "1",
    }, optional={"is_deleted"})
    if existing:
        # The time comes from the daily_events row, not the task — the task
        # deliberately carries no start_time (see below) — and re-reading it
        # to echo it back is not worth a round trip. The day is the answer
        # she needs; the calendar shows the rest.
        return jsonify({
            "status": "already-scheduled",
            "project_id": project_id,
            "task_id": existing[0]["task_id"],
            "plan_date": plan_date,
            "message": f"Already on {plan_date}.",
        })

    # ── 1. The project task — the record of what she planned ────────
    #
    # THE TASK KEEPS ITS start_time. The calendar page draws BOTH sources -
    # planner_v2.js fetches /api/v2/events AND /api/v2/project-tasks - so
    # writing a time to both once drew the topic twice, which is what
    # "repeating twice in the calendar" was.
    #
    # The first fix was to strip start_time from the task. That removed the
    # duplicate and broke something else: the project list and the todo then
    # showed a scheduled topic with no time against it, which is not
    # actionable. So the duplicate is now removed where it is created - the
    # grid dedupes tasks against events by title and start time - and the
    # task keeps the time it needs.
    task_payload = {
        "user_id": user_id,
        "project_id": project_id,
        "task_text": title,
        "status": "open",
        "priority": "medium",
        "plan_date": plan_date,
        "start_time": start_time,
        "due_date": plan_date,
        "notes": f"{spec['label']} topic · scheduled from {spec['page']}",
        "is_deleted": False,
    }
    if prep_minutes:
        task_payload["planned_hours"] = round(prep_minutes / 60.0, 2)
    # Link it to the project's default epic when the OKR trio resolves, so
    # the task appears in the project tree rather than only in flat views.
    try:
        from routes.projects import _default_epic_id
        epic_id = _default_epic_id(user_id, project_id)
        if epic_id:
            task_payload["epic_id"] = epic_id
    except Exception:
        logger.warning("%s: default epic unresolved, filing task flat", spec["project"],
                       exc_info=True)

    task_rows = post("project_tasks", task_payload, prefer="return=representation")
    task_id = (task_rows or [{}])[0].get("task_id")

    # ── 2. The calendar row ─────────────────────────────────────────
    # Written straight to daily_events, not through POST /api/v2/events —
    # see the block comment above for why the conflict check would reject
    # the second topic stacked at midnight.
    event_id, event_row = None, None
    try:
        ev = post("daily_events", {
            "user_id": user_id,
            "plan_date": plan_date,
            "start_time": start_time,
            "end_time": end_time,
            "title": title,
            "description": f"{spec['label']} — open the topic at {spec['page']}",
            "priority": "medium",
            "reminder_minutes": 10,
            "is_deleted": False,
        }, prefer="return=representation")
        event_row = (ev or [None])[0]
        event_id = (event_row or {}).get("id")
    except Exception:
        logger.exception("%s: calendar row failed for %r on %s", spec["project"], title, plan_date)

    # ── 2b. Mirror it to Google Calendar ────────────────────────────
    # Same shape as POST /api/v2/events: fire and forget on a daemon
    # thread, then stamp the returned google_event_id back onto the row.
    # The reason it runs off the request is that a Google round trip is
    # a second or more, and she is standing in front of a card waiting
    # for it to say "added" — the in-app calendar is already correct by
    # the time this starts, so the mirror is allowed to be late.
    #
    # NOT mirrored from the Quick Bucket row as well. quick_bucket has
    # its own Google sync, and letting both fire would put the same
    # topic on the real calendar twice.
    gcal_connected = False
    if event_row:
        try:
            gcal_connected = bool(get("user_google_tokens",
                                      params={"user_id": f"eq.{user_id}"}) or [])
        except Exception:
            logger.warning("%s: could not check Google connection", spec["project"], exc_info=True)
    if event_row and gcal_connected:
        def _mirror(row=event_row, uid=user_id):
            try:
                # Imported here rather than at module scope so a broken or
                # absent Google client library cannot stop /ai-sde loading.
                from services import events_calendar_service as events_cal
                gid = events_cal.sync_create(uid, row)
                if gid:
                    update("daily_events",
                           params={"id": f"eq.{row['id']}", "user_id": f"eq.{uid}"},
                           json={"google_event_id": gid})
            except Exception:
                logger.exception("Google mirror failed for %r", row.get("title"))
        threading.Thread(target=_mirror, daemon=True).start()

    # ── 3. The Quick Bucket row ─────────────────────────────────────
    # Prefixed so a line in the bucket says where it came from; the
    # bucket is a flat list with no project column to say it otherwise.
    bucket_id = None
    bucket_text = f"{spec['project']} · {title}"[:500]
    if data.get("quick_bucket", True):
        try:
            dupes = _get_optional("quick_bucket", {
                "user_id": f"eq.{user_id}",
                "text": _pg_eq(bucket_text),
                "is_deleted": "eq.false",
                "is_done": "eq.false",
                "select": "id",
                "limit": "1",
            }, optional={"is_deleted", "is_done"})
            if dupes:
                bucket_id = dupes[0]["id"]
            else:
                # A topic with a real time gets a real deadline, which is
                # what drives the countdown pill. A midnight default does
                # not — a countdown to 00:00 would read as urgent when the
                # time only means "top of the day".
                due_at = None
                if not untimed:
                    due_at = f"{plan_date}T{start_time}:00"
                today = user_today().isoformat()
                qb = post("quick_bucket", {
                    "user_id": user_id,
                    "text": bucket_text,
                    "time_bucket": "at" if due_at else ("now" if plan_date <= today else "future"),
                    "due_at": due_at,
                    "position": 0,
                    "is_done": False,
                    "is_deleted": False,
                }, prefer="return=representation")
                bucket_id = (qb or [{}])[0].get("id")
        except Exception:
            logger.exception("%s: quick bucket row failed for %r", spec["project"], title)

    when = "12:00 AM (top of the day)" if untimed else start_time
    return jsonify({
        "status": "ok",
        "project_id": project_id,
        "task_id": task_id,
        "event_id": event_id,
        "quick_bucket_id": bucket_id,
        "title": title,
        "plan_date": plan_date,
        "start_time": start_time,
        "end_time": end_time,
        "untimed": untimed,
        "bank": bank,
        "project": spec["project"],
        # Kicked off, not confirmed — the mirror finishes after this
        # response, so the wording on the page has to stay honest about
        # that ("sending to Google", never "on Google").
        "gcal_syncing": bool(gcal_connected and event_row),
        "message": f"On the calendar for {plan_date} at {when}.",
    })


# ══════════════════════════════════════════════════════════════════════
# AI SDE PROGRESS — server-side, so study follows the user between devices
#
# Keyed by TITLE, never by the "ai{i}" id the list endpoint hands out: that
# id is the entry's INDEX in the bank, and the index shifts every time an
# entry is added or deduped. See MIGRATION_AI_SDE_PROGRESS.sql.
# ══════════════════════════════════════════════════════════════════════

_AI_SDE_TITLES = {e["title"] for e in AI_SDE_ENTRIES}


@interview_prep_bp.route("/api/ai-sde/progress", methods=["GET"])
@login_required
def ai_sde_progress():
    """Every topic this user has ticked or clocked time against.

    Returns titles, not ids, and the client maps them onto whatever the
    bank currently holds — so a topic that has since been renamed or
    removed simply drops out instead of silently marking its neighbour.
    """
    try:
        rows = get("ai_sde_progress", params={
            "user_id": f"eq.{session['user_id']}",
            "is_deleted": "eq.false",
            "select": "entry_title,studied,studied_at,minutes_focused",
            "limit": 5000,
        }) or []
    except Exception as exc:
        return _ai_sde_progress_schema_error(exc)

    studied, minutes = [], {}
    for r in rows:
        title = r.get("entry_title")
        if title not in _AI_SDE_TITLES:
            continue          # renamed or removed since it was recorded
        if r.get("studied"):
            studied.append(title)
        if r.get("minutes_focused"):
            minutes[title] = int(r["minutes_focused"])
    return jsonify({"studied": studied, "minutes": minutes,
                    "total_rows": len(rows)})


@interview_prep_bp.route("/api/ai-sde/progress", methods=["POST"])
@login_required
def ai_sde_progress_save():
    """Upsert one topic's progress. Body: {title, studied?, minutes?}."""
    data = request.get_json(force=True) or {}
    title = (data.get("title") or "").strip()
    if title not in _AI_SDE_TITLES:
        return jsonify({"error": "unknown topic"}), 400

    payload = {"user_id": session["user_id"], "entry_title": title,
               "updated_at": _iso_now()}
    if "studied" in data:
        payload["studied"] = bool(data["studied"])
        # Stamp the moment it was ticked; clear it when un-ticked so the
        # column never claims a date for something not actually done.
        payload["studied_at"] = _iso_now() if data["studied"] else None
    if "minutes" in data:
        try:
            payload["minutes_focused"] = max(0, int(data["minutes"]))
        except (TypeError, ValueError):
            return jsonify({"error": "minutes must be a number"}), 400
    if len(payload) <= 3:
        return jsonify({"error": "nothing to save"}), 400

    try:
        # Upsert on (user_id, entry_title) — the unique index in the
        # migration is what makes merge-duplicates the right resolution.
        # ?on_conflict= names the unique index. Without it PostgREST merges
        # on the uuid primary key, which never collides, so the SECOND save
        # of any topic failed with 409 - the same bug prep_notes once had.
        post("ai_sde_progress?on_conflict=user_id,entry_title", payload,
             prefer="resolution=merge-duplicates,return=minimal")
    except Exception as exc:
        return _ai_sde_progress_schema_error(exc)
    return jsonify({"status": "ok"})


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _ai_sde_progress_schema_error(exc):
    """A missing table should name the migration, not surface a bare 500."""
    text = str(exc)
    if "ai_sde_progress" in text or "does not exist" in text or "schema cache" in text:
        logger.warning("ai-sde progress: table missing - %s", text)
        return jsonify({
            "error": "Progress sync is not set up yet. Run "
                     "MIGRATION_AI_SDE_PROGRESS.sql in Supabase.",
            "migration": "MIGRATION_AI_SDE_PROGRESS.sql",
        }), 503
    raise exc


@interview_prep_bp.route("/ai-sde/pdf", methods=["GET"])
@login_required
def ai_sde_pdf():
    """Server PDF of the AI SDE bank (same ?cat/?tag/?q/?id filters)."""
    items = [{"id": f"ai{i}", **e} for i, e in enumerate(AI_SDE_ENTRIES)]
    selected, label = _bank_select(items, ("title", "answer", "pitfalls"),
                                   AI_SDE_CATEGORIES, "title")
    # ?pri=P0 narrows the export to one priority band, and the export always
    # comes out in stack-rank order so the PDF reads as a study plan.
    pri = (request.args.get("pri") or "").strip().upper()
    if pri:
        selected = [it for it in selected if it.get("priority") == pri]
        label = f"{label} — {pri}" if label else f"Priority {pri}"
    # The interview tags narrow it further, so "Must-Know / DSA / Graphs" on
    # the study page exports exactly the revision sheet you are looking at.
    selected, _tag_bits = _ai_sde_tag_select(selected)
    if _tag_bits:
        _tags = " · ".join(_tag_bits)
        label = f"{label} — {_tags}" if label else _tags
    # Near-duplicate topics are dropped from the export by default, matching
    # the study page's own default. Printing both halves is worse here than
    # on screen: on screen she can see they are the same topic and skip one,
    # on paper she just reads it twice. ?dupes=1 prints them.
    if (request.args.get("dupes") or "").strip() not in ("1", "true", "yes"):
        _before = len(selected)
        selected = [it for it in selected if not it.get("duplicate_of")]
        if len(selected) < _before:
            label = f"{label} — no duplicates" if label else "No duplicates"
    selected.sort(key=lambda it: it.get("rank") or 0)
    heading = label or "AI SDE Prep Bank"
    _mins = sum(it.get("prep_minutes") or 0 for it in selected)
    _effort = f"{_mins // 60}h {_mins % 60}m of prep" if _mins else ""
    subtitle = " | ".join(x for x in [
        f"{len(selected)} topic{'' if len(selected) == 1 else 's'}", _effort,
        "DailyPlanner Interview Prep", _today().isoformat()] if x)
    sections = []
    for it in selected:
        _diff_freq = " | ".join(x for x in [
            (f"Difficulty: {it['difficulty']}" if it.get("difficulty") else ""),
            (it.get("frequency") or "")] if x)
        # Planning line: how long this takes and where it sits in the study order.
        _plan = " | ".join(x for x in [
            (f"Prep time: {it['prep_label']}" if it.get("prep_label") else ""),
            (f"Stack rank #{it['rank']} of {len(items)}" if it.get("rank") else ""),
            # Rank within the band is the number you actually work from once
            # you have committed to finishing a priority level.
            (f"{it['priority_label']} in its band" if it.get("priority_label") else ""),
            (f"#{it['cat_rank']} within {AI_SDE_CATEGORIES.get(it.get('cat'), '')}"
             if it.get("cat_rank") else ""),
            (it.get("priority_note") or "")] if x)
        # The seven interview tags, on one line. This is the line you scan when
        # deciding whether a topic belongs in tonight's revision at all.
        _tags = " | ".join(x for x in [
            (f"{it['tag_priority']} for a new grad" if it.get("tag_priority") else ""),
            (f"{it['tag_topic']} / {it['tag_subtopic']}"
             if it.get("tag_topic") and it.get("tag_subtopic")
             else it.get("tag_topic") or ""),
            (it.get("tag_level") or ""),
            (f"{it['tag_format']} question" if it.get("tag_format") else ""),
            (f"{it['tag_stage']} round" if it.get("tag_stage") else ""),
            (f"{it['tag_time']} to answer" if it.get("tag_time") else "")] if x)
        if it.get("tag_flag"):
            _tags = f"{_tags}\nNote: {it['tag_flag']}" if _tags else f"Note: {it['tag_flag']}"
        fields = [("Prep time & priority", _plan or None),
                  ("Interview tags", _tags or None),
                  ("Difficulty & interview frequency", _diff_freq or None),
                  ("Answer / reasoning", it.get("answer")),
                  ("Explained step by step", it.get("walkthrough")),
                  # The plain-English recipe comes before the code in the PDF
                  # too — read the steps, then read the implementation.
                  ("How to code it — plain English, step by step",
                   it.get("plain_algo")),
                  # Several worked examples when the topic has them, else the
                  # original single-line example.
                  (f"Worked examples ({len(it['examples'])})" if it.get("examples") else "Example",
                   "\n\n".join(f"{n}. {x}" for n, x in enumerate(it["examples"], 1))
                   if it.get("examples") else it.get("example")),
                  ("How to remember", it.get("mnemonic")),
                  ("Complexity", it.get("complexity")),
                  ("Pitfalls", it.get("pitfalls")),
                  ("Follow-ups", it.get("followups"))]
        mono = [("Code", it.get("code"))] if it.get("code") else []
        if it.get("diagram"):
            mono.append(("Diagram", it.get("diagram")))
        sections.append({
            "title": it["title"],
            "cat": AI_SDE_CATEGORIES.get(it.get("cat"), it.get("cat", "")),
            "fields": fields, "arch": None, "mono_blocks": mono, "tags": it.get("tags"),
        })
    try:
        pdf = _pdf_bytes(heading, subtitle, sections, body_pt=_pdf_body_pt())
    except ImportError:
        return redirect(url_for("interview_prep.ai_sde_page"))
    fname = (selected[0]["id"] + ".pdf") if len(selected) == 1 else "ai-sde-bank.pdf"
    return _pdf_response(pdf, fname)


# ── AI SDE daily quiz (HackerRank-style multiple choice) ───────────────────
import hashlib as _hashlib
import random as _random

# Only these categories make good "identify the concept from its description"
# multiple-choice questions (they have a crisp term + explanation).
_QUIZ_CATS = ("glossary", "ml_concepts", "conceptual", "dsa", "ml_coding",
              "ml_system_design", "cs_fundamentals", "lld", "ai_llm", "ai_applied")


def _first_sentences(text, n=2, limit=460):
    """First n sentences of a field, capped, for a quiz prompt."""
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = " ".join(parts[:n]).strip()
    return (out[:limit] + "...") if len(out) > limit else out


def _mask_title(prompt, title):
    """Hide the answer's name (and its longer words) inside the prompt so the
    question isn't a giveaway."""
    masked = re.sub(re.escape(title), "____", prompt, flags=re.IGNORECASE)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]{4,}", title):
        masked = re.sub(r"\b" + re.escape(word) + r"\b", "____", masked,
                        flags=re.IGNORECASE)
    return masked


def _build_quiz(entries, mode, cat, n, seed):
    """Deterministic multiple-choice quiz. Each question shows a masked
    description and asks which topic it describes; distractors come from the
    same category. Same seed -> same quiz (so a 'daily set' is stable)."""
    rng = _random.Random(seed)
    pool = [e for e in entries if e.get("answer") and e["cat"] in _QUIZ_CATS]
    if mode == "topic" and cat:
        pool = [e for e in pool if e["cat"] == cat]
    by_cat = defaultdict(list)
    for e in pool:
        by_cat[e["cat"]].append(e)
    if len(pool) < 4:
        return []
    rng.shuffle(pool)
    chosen = pool[:min(n, len(pool))]
    questions = []
    for e in chosen:
        siblings = [s["title"] for s in by_cat[e["cat"]] if s["title"] != e["title"]]
        if len(siblings) < 3:
            siblings = [s["title"] for s in pool if s["title"] != e["title"]]
        distractors = rng.sample(siblings, 3) if len(siblings) >= 3 else siblings[:3]
        options = distractors + [e["title"]]
        rng.shuffle(options)
        prompt = _mask_title(_first_sentences(e.get("answer", "")), e["title"])
        questions.append({
            "id": e["id"],
            "prompt": prompt,
            "options": options,
            "answer": e["title"],
            "correct_index": options.index(e["title"]),
            "difficulty": e.get("difficulty", ""),
            "frequency": e.get("frequency", ""),
            "cat": e["cat"],
            "cat_label": AI_SDE_CATEGORIES.get(e["cat"], e["cat"]),
            "explain": e.get("answer", ""),
            "mnemonic": e.get("mnemonic", ""),
            "example": e.get("example", ""),
            "diagram": e.get("diagram", ""),
        })
    return questions


@interview_prep_bp.route("/ai-sde/quiz", methods=["GET"])
@login_required
def ai_sde_quiz_page():
    return render_template("ai_sde_quiz.html")


@interview_prep_bp.route("/api/ai-sde/quiz", methods=["GET"])
@login_required
def ai_sde_quiz():
    """Generate a multiple-choice quiz from the AI SDE bank.

    mode=mixed (default) -> a stable DAILY set of 25 across all areas, seeded by
    today's date. mode=topic&cat=<key> -> fresh practice from one area."""
    items = [{"id": f"ai{i}", **e} for i, e in enumerate(AI_SDE_ENTRIES)]
    mode = (request.args.get("mode") or "mixed").strip()
    cat = (request.args.get("cat") or "").strip()
    try:
        n = max(5, min(25, int(request.args.get("n", 25))))
    except (TypeError, ValueError):
        n = 25
    if mode == "mixed":
        seed = f"mixed-{_today().isoformat()}"          # stable for the day
    else:
        # topic practice: fresh each load
        seed = f"topic-{cat}-{request.args.get('nonce', '')}-{_today().isoformat()}"
    quiz = _build_quiz(items, mode, cat, n, seed)
    return jsonify({
        "mode": mode, "cat": cat, "date": _today().isoformat(),
        "count": len(quiz), "questions": quiz,
        "categories": [{"key": k, "label": v} for k, v in AI_SDE_CATEGORIES.items()
                       if k in _QUIZ_CATS],
    })


@interview_prep_bp.route("/interview-prep/guides", methods=["GET"])
@interview_prep_bp.route("/interview-prep/guides/<slug>", methods=["GET"])
@login_required
def guides(slug=None):
    """Render a shipped markdown prep guide (e.g. the AI SDE plan) as a
    readable in-app page. Defaults to the AI SDE plan."""
    import os
    from flask import current_app, abort
    slug = slug or "ai-sde"
    entry = _GUIDES.get(slug)
    if not entry:
        abort(404)
    filename, title = entry
    path = os.path.join(current_app.root_path, filename)
    if not os.path.exists(path):
        path = os.path.join(os.getcwd(), filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning("guide read failed for %s: %s", filename, e)
        content = f"# {title}\n\nCould not load this guide."
    return render_template(
        "prep_guide.html", content=content, title=title, slug=slug,
        guides=[{"slug": s, "title": t} for s, (_, t) in _GUIDES.items()],
    )


def _guide_text(slug):
    """(title, markdown) of a shipped guide, or (None, None)."""
    import os
    from flask import current_app
    entry = _GUIDES.get(slug)
    if not entry:
        return None, None
    filename, title = entry
    for path in (os.path.join(current_app.root_path, filename), os.path.join(os.getcwd(), filename)):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return title, f.read()
    return title, None


#: Guides are short documents read on a phone: 14pt body by default (the
#: banks' 26pt default suits one-entry-per-page exports, not a 5-page read).
_GUIDE_PDF_PT = 14


def _guide_pdf_bytes(title, md, body_pt=_GUIDE_PDF_PT):
    """A shipped Markdown guide as a PDF: headings, paragraphs, bullet and
    numbered lists, **bold** lead-ins, block quotes and code fences. Raises
    ImportError if fpdf2 isn't installed."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    NX, NY = XPos.LMARGIN, YPos.NEXT
    body_pt = max(9, min(_PDF_MAX_PT, float(body_pt or _GUIDE_PDF_PT)))
    MARGIN = 14
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    SANS, MONO, unicode_ok = _pdf_register_fonts(pdf)
    txt = (lambda t: t or "") if unicode_ok else _latin1
    pdf.set_title(title or "Interview prep guide")
    pdf.set_lang("en")
    pdf.add_page()

    def lh(size, k=1.32):
        return size * 0.3528 * k

    def para(text, size=body_pt, style="", indent=0, gap=1.6, bullet=None):
        text = re.sub(r"`([^`]+)`", r"\1", text.strip())
        pdf.set_font(SANS, style, size)
        if bullet:
            pdf.set_x(MARGIN + indent)
            bw = pdf.get_string_width(bullet + " ") + 1
            y = pdf.get_y()
            pdf.cell(bw, lh(size), txt(bullet))
            pdf.set_xy(MARGIN + indent + bw, y)
            pdf.multi_cell(pdf.w - MARGIN - (MARGIN + indent + bw), lh(size), txt(text),
                           markdown=True, align="L", new_x=NX, new_y=NY)
        else:
            pdf.set_x(MARGIN + indent)
            pdf.multi_cell(pdf.w - MARGIN - (MARGIN + indent), lh(size), txt(text),
                           markdown=True, align="L", new_x=NX, new_y=NY)
        pdf.ln(gap)

    lines = md.replace("\r", "").split("\n")
    i, buf = 0, []
    seen_h2 = False

    def flush():
        if buf:
            para(" ".join(x.strip() for x in buf))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        st = line.strip()
        if st.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            pdf.set_font(MONO, "", body_pt * 0.72)
            pdf.set_fill_color(242, 242, 238)
            pdf.multi_cell(0, lh(body_pt * 0.72, 1.25), txt("\n".join(code)), fill=True, new_x=NX, new_y=NY)
            pdf.ln(2)
        elif not st:
            flush()
        elif st.startswith("# "):
            flush(); para(st[2:], size=body_pt * 1.7, style="B", gap=2.5)
        elif st.startswith("## "):
            flush()
            # A guide whose sections are its pages ("## Page 2. ...") starts
            # each on a fresh page; otherwise only avoid an orphaned heading.
            if (re.match(r"^## Page \d", st) and seen_h2) or pdf.get_y() > pdf.h - MARGIN - lh(body_pt) * 6:
                pdf.add_page()
            seen_h2 = True
            pdf.ln(2)
            para(st[3:], size=body_pt * 1.25, style="B", gap=1)
            pdf.set_draw_color(200, 200, 195)
            pdf.line(MARGIN, pdf.get_y(), pdf.w - MARGIN, pdf.get_y())
            pdf.ln(2.5)
        elif st.startswith("### "):
            flush(); para(st[4:], size=body_pt * 1.08, style="B", gap=1)
        elif re.match(r"^[-*]\s+", st):
            flush(); para(re.sub(r"^[-*]\s+", "", st), indent=2, bullet="\u2022" if unicode_ok else "-", gap=1.2)
        elif re.match(r"^\d+[.)]\s+", st):
            flush(); n = re.match(r"^(\d+)[.)]\s+", st).group(1)
            para(re.sub(r"^\d+[.)]\s+", "", st), indent=2, bullet=n + ".", gap=1.2)
        elif st.startswith("> "):
            flush(); para(st[2:], indent=4, gap=1.6)
        else:
            buf.append(line)
        i += 1
    flush()
    return bytes(pdf.output())


@interview_prep_bp.route("/interview-prep/guides/<slug>/pdf", methods=["GET"])
@login_required
def guide_pdf(slug):
    """A shipped guide as a PDF (14pt body by default; ?fs= to change)."""
    from flask import abort
    title, md = _guide_text(slug)
    if not md:
        abort(404)
    raw = (request.args.get("fs") or "").strip()
    try:
        pt = float(raw) if raw else _GUIDE_PDF_PT
    except ValueError:
        pt = _GUIDE_PDF_PT
    try:
        pdf = _guide_pdf_bytes(title, md, body_pt=pt)
    except ImportError:
        return redirect(f"/interview-prep/guides/{slug}")
    return _pdf_response(pdf, slug + ".pdf")


@interview_prep_bp.route("/api/interview-prep", methods=["GET"])
@login_required
def dashboard():
    """Everything the page needs in one payload: plan, computed stats +
    coach message, topics, stories, and recent sessions."""
    user_id = session["user_id"]
    plan = _ensure_plan(user_id)
    if plan is None:
        return jsonify({"migration_pending": True,
                        "plan": {"role_title": DEFAULT_ROLE, "target_date": None,
                                 "daily_goal_minutes": 45},
                        "stats": {}, "topics": [], "stories": [], "sessions": []})

    today = _today()
    goal = int(plan.get("daily_goal_minutes") or 0)

    try:
        topics = get("interview_topics", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "id,category,title,confidence,notes,position",
            "order": "category.asc,position.asc,created_at.asc", "limit": "500",
        }) or []
    except Exception:
        topics = []
    try:
        stories = get("interview_stories", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "id,title,competency,situation,task,action,result,rehearsed,position",
            "order": "position.asc,created_at.asc", "limit": "300",
        }) or []
    except Exception:
        stories = []
    try:
        sessions = get("interview_sessions", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "id,practiced_on,minutes,focus,reflection",
            "order": "practiced_on.desc,created_at.desc", "limit": "400",
        }) or []
    except Exception:
        sessions = []

    # ── Scores ──
    if topics:
        topic_score = sum(int(t.get("confidence") or 0) for t in topics) / (4.0 * len(topics))
    else:
        topic_score = 0.0
    rehearsed = sum(1 for s in stories if s.get("rehearsed"))
    story_score = min(rehearsed, STORY_TARGET) / float(STORY_TARGET)

    by_day = defaultdict(int)
    for s in sessions:
        by_day[s.get("practiced_on")] += int(s.get("minutes") or 0)
    week_ago = (today - timedelta(days=6)).isoformat()
    days_practiced_7 = sum(1 for d, m in by_day.items() if d and d >= week_ago and m > 0)
    consistency = min(days_practiced_7, 7) / 7.0

    # ── The banks: case rounds, behavioural, system design ──
    # Read from prep_progress. Before it existed readiness was syllabus,
    # stories and consistency only, so a week rehearsing case rounds - where
    # a Director loop is usually decided - moved the number not at all.
    case_score = bank_score = None
    next_cases = []
    try:
        prog = _progress_rows(user_id, done_only=True)
    except Exception:
        prog = None
    if prog is not None:
        done_by_bank = defaultdict(set)
        for r in prog:
            done_by_bank[r.get("bank")].add(r.get("entry_title"))
        tpm_done = done_by_bank["tpm"]
        weights = {"P0": 3, "P1": 2, "P2": 1}
        total_w = sum(weights[e["priority"]] for e in TPM_ROUND_ENTRIES) or 1
        case_score = sum(weights[e["priority"]] for e in TPM_ROUND_ENTRIES
                         if e["title"] in tpm_done) / float(total_w)
        beh = len(done_by_bank["behavioral"] & {q["q"] for q in QUESTIONS})
        sd = len(done_by_bank["sysdesign"] & {e["title"] for e in SD_ENTRIES})
        deep = len(done_by_bank["sddeep"] & set(sd_deep_bank.BY_TITLE))
        bank_score = (min(beh, BEHAVIORAL_TARGET) / float(BEHAVIORAL_TARGET)
                      + min(sd, SYSDESIGN_TARGET) / float(SYSDESIGN_TARGET)
                      + min(deep, DEEP_TARGET) / float(DEEP_TARGET)) / 3.0
        next_cases = [
            {"id": f"t{i}", "title": e["title"], "priority": e["priority"],
             "round": TPM_ROUNDS.get(e["round"], e["round"])}
            for i, e in sorted(enumerate(TPM_ROUND_ENTRIES),
                               key=lambda ie: ie[1]["rank"])
            if e["title"] not in tpm_done
        ][:3]

    if case_score is None:
        readiness = round((0.55 * topic_score + 0.25 * story_score
                           + 0.20 * consistency) * 100)
    else:
        readiness = round((0.35 * topic_score + 0.20 * story_score
                           + 0.20 * case_score + 0.10 * bank_score
                           + 0.15 * consistency) * 100)
    cur_streak, best_streak = _streaks(by_day, goal, today)
    minutes_today = by_day.get(today.isoformat(), 0)
    goal_met = goal > 0 and minutes_today >= goal

    # ── Pace vs target date ──
    days_left = expected = None
    target = plan.get("target_date")
    if target:
        try:
            tdate = date.fromisoformat(target)
            days_left = (tdate - today).days
            start = date.fromisoformat((plan.get("created_at") or "")[:10]) if plan.get("created_at") else today
            total = max(1, (tdate - start).days)
            elapsed = max(0, min(total, (today - start).days))
            expected = round(elapsed / total * 100)
        except Exception:
            days_left = expected = None

    msg, tone = _coach(readiness, days_left,
                       expected if expected is not None else readiness,
                       goal_met, minutes_today, goal, cur_streak)
    quote_text, quote_by = QUOTES[today.toordinal() % len(QUOTES)]

    # ── Today's focus: weakest topics + stories still to rehearse ──
    weakest = sorted(
        ({"id": t["id"], "title": t["title"],
          "category": CATEGORY_LABELS.get(t.get("category"), t.get("category")),
          "confidence": int(t.get("confidence") or 0)} for t in topics),
        key=lambda t: (t["confidence"], t["title"].lower()),
    )[:3]
    to_rehearse = [
        {"id": s["id"], "title": s["title"], "competency": s.get("competency") or ""}
        for s in stories if not s.get("rehearsed")
    ][:2]

    return jsonify({
        "plan": {
            "role_title": plan.get("role_title") or DEFAULT_ROLE,
            "target_date": target,
            "daily_goal_minutes": goal,
        },
        "stats": {
            "readiness": readiness,
            "expected": expected,
            "days_left": days_left,
            "streak": cur_streak,
            "best_streak": best_streak,
            "minutes_today": minutes_today,
            "goal_met": goal_met,
            "topic_score": round(topic_score * 100),
            "story_score": round(story_score * 100),
            "consistency": round(consistency * 100),
            "case_score": None if case_score is None else round(case_score * 100),
            "bank_score": None if bank_score is None else round(bank_score * 100),
            "next_cases": next_cases,
            "rehearsed": rehearsed,
            "story_target": STORY_TARGET,
            "topics_total": len(topics),
            "topics_mastered": sum(1 for t in topics if int(t.get("confidence") or 0) >= 4),
            "coach": msg,
            "tone": tone,
            "quote": quote_text,
            "quote_by": quote_by,
            "weakest": weakest,
            "to_rehearse": to_rehearse,
        },
        "categories": [{"key": k, "label": CATEGORY_LABELS[k]} for k in CATEGORIES],
        "topics": topics,
        "stories": stories,
        "sessions": sessions[:30],
    })


# ─────────── plan settings ───────────────────────────────────

def _valid_qid(qid):
    """True if qid is a real bank id like 'q17'."""
    if not (isinstance(qid, str) and qid.startswith("q")):
        return False
    try:
        return 0 <= int(qid[1:]) < len(QUESTIONS)
    except ValueError:
        return False


# Bank field -> override column. The bank uses short keys (s/t/a/r); the
# table stores full names.
_OVERRIDE_MAP = {"q": "question", "s": "situation", "t": "task",
                 "a": "action", "r": "result", "tip": "tip"}


@interview_prep_bp.route("/tpm-rounds", methods=["GET"])
@login_required
def tpm_rounds_page():
    """The case rounds now live inside the Interview Prep hub. Kept as a
    redirect so bookmarks, old Day Board links and the service worker's
    cached nav all still land somewhere useful, with ?topic= intact."""
    qs = request.query_string.decode("utf-8", "ignore")
    return redirect("/interview-prep/cases" + ("?" + qs if qs else ""), code=301)


def _tpm_items():
    return [{"id": f"t{i}", **e} for i, e in enumerate(TPM_ROUND_ENTRIES)]


@interview_prep_bp.route("/api/tpm-rounds", methods=["GET"])
@login_required
def tpm_rounds_api():
    """Case-round bank: framework, worked answer, strong-vs-weak contrast,
    interviewer probes and pitfalls per question. Static reference content."""
    items = _tpm_items()
    return jsonify({
        "rounds": [{"key": k, "label": v} for k, v in TPM_ROUNDS.items()],
        "briefs": TPM_ROUND_BRIEF,
        "entries": items,
        "total": len(items),
        "total_minutes": TPM_TOTAL_PREP_MINUTES,
    })


@interview_prep_bp.route("/interview-prep/cases/pdf", methods=["GET"])
@login_required
def tpm_rounds_pdf():
    """The case rounds as a phone-readable PDF. Filters: ?round= ?priority=
    ?q= ?id=tN (any combination), the same ones the page offers."""
    rnd = (request.args.get("round") or "").strip()
    pri = (request.args.get("priority") or "").strip().upper()
    q = (request.args.get("q") or "").strip().lower()
    one = (request.args.get("id") or "").strip()
    items = _tpm_items()
    if one:
        items = [e for e in items if e["id"] == one]
    else:
        items = [e for e in items
                 if (not rnd or e["round"] == rnd)
                 and (not pri or e["priority"] == pri)
                 and (not q or q in (e["title"] + " " + e["framework"] + " "
                                     + " ".join(e["tags"])).lower())]
    items.sort(key=lambda e: e["rank"])
    if not items:
        return jsonify({"error": "No cases match that filter."}), 404
    if one:
        heading = items[0]["title"][:80]
    else:
        heading = TPM_ROUNDS.get(rnd) or "Case Rounds"
        if pri:
            heading += f" - {pri}"
    mins = sum(e["prep_minutes"] for e in items)
    subtitle = " | ".join(x for x in [
        f"{len(items)} case{'' if len(items) == 1 else 's'}",
        f"{mins // 60}h {mins % 60}m of rehearsal" if mins else "",
        "DailyPlanner Interview Prep", _today().isoformat()] if x)
    sections = [{
        "title": e["title"],
        "cat": f"{TPM_ROUNDS.get(e['round'], e['round'])} | {e['priority']} | "
               f"{e['difficulty']} | {e['prep_label']}",
        "fields": [("What they are testing", e["what_they_test"]),
                   ("How often", e["frequency"]),
                   ("Framework", e["framework"]),
                   ("Worked answer", e["worked"]),
                   ("Strong vs weak", e["strong_weak"]),
                   ("They will push back",
                    "\n".join(f"{n}. {p}" for n, p in enumerate(e["probes"], 1))),
                   ("Pitfalls", e["pitfalls"])],
        "arch": None, "tags": e["tags"],
    } for e in items]
    try:
        pdf = _pdf_bytes(heading, subtitle, sections, body_pt=_pdf_body_pt())
    except ImportError:
        return jsonify({"error": "PDF export needs fpdf2 on the server."}), 503
    fname = (items[0]["id"] + ".pdf") if one else "case-rounds.pdf"
    return _pdf_response(pdf, fname)


# ─────────── Random thoughts ───────────────────────────────────────
#
# Questions that come to mind while preparing, answered in depth by the
# app so they can be understood, kept, and revisited. The answer is written
# in a background thread (services/thoughts_service.py) and the page polls.

_THOUGHT_COLS = ("id,parent_id,root_id,question,context,answer,status,model,error,"
                 "understood,pinned,tags,images,notes,highlight,created_at,updated_at,"
                 "review_stage,next_review_at,last_reviewed_at,review_count,audio")

# Columns added by later sections of the migration. A table that predates
# one still loads; the column is just left out of the select.
_THOUGHT_LATE_COLS = ("notes", "images", "highlight", "audio")


def _thought_get(params, shelf=None, dropped=None):
    """get() on prep_thoughts that tolerates a table created before the
    images or notes column existed (earlier versions of the migration).
    With a shelf, only that shelf's rows (Interview Prep or AI SDE Prep).
    Columns it had to leave out are appended to `dropped`."""
    def run(p):
        if shelf is None:
            return get(thoughts_service.TABLE, p) or []
        return thoughts_service.get_shelved(p, shelf)
    # Older tables may lack the images or notes column or the spaced-
    # repetition columns (added by later runs of MIGRATION_PREP_THOUGHTS.sql):
    # drop them from the select and retry.
    for _ in range(4):
        try:
            return run(params)
        except Exception as exc:
            if "select" not in params:
                raise
            cols = params["select"].split(",")
            if thoughts_service.review_missing(exc):
                keep = [c for c in cols if c not in thoughts_service.REVIEW_COLS]
            else:
                late = [c for c in _THOUGHT_LATE_COLS if c in cols and c in thoughts_service.err_text(exc)][:1]
                keep = [c for c in cols if c not in late]
                if late and dropped is not None:
                    dropped.append(late[0])
            if keep == cols:
                raise
            params = dict(params, select=",".join(keep))
    return run(params)


def _shelf_arg(data=None):
    """Which Random thoughts shelf a request is for: ?shelf= or a body field."""
    raw = request.args.get("shelf") or (data or {}).get("shelf")
    return thoughts_service.clean_shelf(raw)


def _shelf_not_ready_resp():
    return jsonify({"error": f"Random thoughts on AI SDE Prep need the latest "
                             f"{thoughts_service.MIGRATION} run in Supabase (it adds "
                             f"the shelf column; safe to re-run).",
                    "migration": thoughts_service.MIGRATION}), 503


def _read_images(files):
    """Validate uploaded images -> [(bytes, mime, name)] or raise ValueError."""
    out = []
    for f in files[:thoughts_service.MAX_IMAGES]:
        if not f or not f.filename:
            continue
        mime = (f.mimetype or "").lower()
        if mime not in thoughts_service.IMAGE_MIMES:
            raise ValueError("Only PNG, JPG, WebP or GIF images can be attached.")
        data = f.read()
        if not data:
            continue
        if len(data) > thoughts_service.MAX_IMAGE:
            raise ValueError("Each image must be 5 MB or smaller.")
        out.append((data, "image/jpeg" if mime == "image/jpg" else mime, f.filename[:120]))
    return out


def _store_images(user_id, files):
    stored = []
    for data, mime, name in files:
        key = thoughts_service.store_image(user_id, data, mime)
        stored.append({"key": key, "mime": mime, "name": name, "size": len(data)})
    return stored


def _thoughts_missing(exc):
    # The body, not str(exc): the URL in str(exc) names prep_thoughts on every
    # failure, which sent any error to the read-only "seed-N" list.
    t = thoughts_service.err_text(exc)
    return "PGRST205" in t or "42P01" in t or ("prep_thoughts" in t and "does not exist" in t)


def _thought_missing_resp():
    return jsonify({"error": f"Random thoughts are not set up yet. Run "
                             f"{thoughts_service.MIGRATION} in Supabase.",
                    "migration": thoughts_service.MIGRATION}), 503


def _clean_tags(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw[:8]:
        t = re.sub(r"[^a-z0-9 +#.-]", "", str(t).lower()).strip()[:30]
        if t and t not in out:
            out.append(t)
    return out


@interview_prep_bp.route("/api/prep/thoughts", methods=["GET"])
@login_required
def thoughts_list():
    shelf = _shelf_arg()
    seed_error = None
    try:
        try:
            thoughts_service.ensure_seeds(session["user_id"], shelf)
        except Exception as exc:
            if _thoughts_missing(exc) or isinstance(exc, thoughts_service.ShelfNotReady):
                raise
            logger.warning("thoughts: could not add the starter questions", exc_info=True)
            seed_error = thoughts_service.err_text(exc)[:300]
        dropped = []
        rows = _thought_get({
            "user_id": f"eq.{session['user_id']}", "deleted_at": "is.null",
            "select": _THOUGHT_COLS, "order": "created_at.desc", "limit": "500",
        }, shelf, dropped)
    except Exception as exc:
        if _thoughts_missing(exc) or isinstance(exc, thoughts_service.ShelfNotReady):
            # Show the shipped answers read-only until the table exists.
            items = [{"id": f"seed-{i}", "root_id": f"seed-{i}", "parent_id": None,
                      "question": sd["question"], "answer": sd["answer"], "status": "ready",
                      "tags": sd.get("tags") or [], "understood": False, "pinned": False,
                      "created_at": None, "seed": True}
                     for i, sd in enumerate(thoughts_service.seeds())
                     if shelf in thoughts_service.seed_shelves(sd)]
            return jsonify({"available": False, "items": thoughts_service.annotate(items),
                            "categories": thoughts_service.CATEGORIES,
                            "migration": thoughts_service.MIGRATION})
        raise
    for r in rows:
        r["notes"] = _live_notes(r.get("notes"))
    # AN EMPTY LIST MUST SAY WHY. Every user has the shipped questions, so
    # none at all means the reads or the inserts are failing quietly.
    empty_reason = None
    if not rows:
        if thoughts_service.key_kind() == "public":
            empty_reason = thoughts_service.PUBLIC_KEY_MSG
        elif seed_error:
            empty_reason = "The starter questions could not be added: " + seed_error
        if empty_reason:
            loud.bailed("Random thoughts", "empty list", reason=empty_reason[:120])
    return jsonify({"available": True, "items": thoughts_service.annotate(rows),
                    "empty_reason": empty_reason,
                    "categories": thoughts_service.CATEGORIES,
                    "notes_available": "notes" not in dropped,
                    "highlights_available": "highlight" not in dropped,
                    "provider": thoughts_service.any_provider()})


@interview_prep_bp.route("/api/prep/thoughts", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def thoughts_ask():
    """Body: {question, context?, parent_id?}. Saves it and starts the answer."""
    user_id = session["user_id"]
    # JSON, or multipart when images are attached (fields + files "images").
    if request.files:
        data = {k: request.form.get(k) for k in ("question", "context", "parent_id")}
        data["tags"] = [t for t in (request.form.get("tags") or "").split(",") if t.strip()]
        try:
            files = _read_images(request.files.getlist("images"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    else:
        data = request.get_json(silent=True) or {}
        files = []
    question = (data.get("question") or "").strip()[:thoughts_service.MAX_QUESTION]
    context = (data.get("context") or "").strip()[:thoughts_service.MAX_CONTEXT]
    shelf = _shelf_arg(data if not request.files else {"shelf": request.form.get("shelf")})
    # A highlight: a passage of the parent's answer the question is about.
    # Saved as a hint on that answer (a follow-up row with `highlight`).
    highlight = thoughts_service.clean_highlight(data.get("highlight")) if not request.files else None
    if data.get("highlight") is not None and not request.files:
        if not highlight:
            return jsonify({"error": "Select a few words to highlight first."}), 400
        if not data.get("parent_id"):
            return jsonify({"error": "A highlight belongs to an answer."}), 400
        question = question or "Explain this part simply, with a small example."
    if not question:
        return jsonify({"error": "Write the question first."}), 400
    parent = None
    try:
        if data.get("parent_id"):
            parent = thoughts_service.parent_of(user_id, str(data["parent_id"]))
            if not parent:
                return jsonify({"error": "That thread no longer exists."}), 404
        row = {"user_id": user_id, "question": question, "context": context or None,
               "status": "pending", "tags": _clean_tags(data.get("tags"))}
        if parent:
            row["parent_id"] = parent["id"]
            row["root_id"] = parent.get("root_id") or parent["id"]
        if highlight:
            row["highlight"] = highlight
            row["context"] = highlight["quote"]
        if shelf != thoughts_service.DEFAULT_SHELF:
            row["shelf"] = shelf
        created = post(thoughts_service.TABLE, row)
    except Exception as exc:
        if highlight and "highlight" in str(exc):
            return jsonify({"error": "Highlights need the latest MIGRATION_PREP_THOUGHTS.sql run "
                                     "in Supabase (it adds the highlight column; safe to re-run).",
                            "migration": thoughts_service.MIGRATION}), 503
        if thoughts_service.shelf_missing(exc):
            return _shelf_not_ready_resp()
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    item = (created or [{}])[0]
    if not item.get("id"):
        return jsonify({"error": "Could not save the question."}), 502
    if not parent:
        # A thread's root points at itself, so one query fetches a thread.
        try:
            update(thoughts_service.TABLE, params={"id": f"eq.{item['id']}", "user_id": f"eq.{user_id}"},
                   json={"root_id": item["id"]})
            item["root_id"] = item["id"]
        except Exception:
            pass
    if files:
        try:
            item["images"] = _store_images(user_id, files)
            update(thoughts_service.TABLE, params={"id": f"eq.{item['id']}", "user_id": f"eq.{user_id}"},
                   json={"images": item["images"]})
        except Exception:
            logger.warning("thoughts: image upload failed", exc_info=True)
            item["images"] = []
            item["image_error"] = ("The question was saved, but the images could not be "
                                   "stored. Check that the user-photos storage bucket exists "
                                   "(see MIGRATION_USER_PHOTOS.sql) and attach them again.")
    thoughts_service.answer_in_background(item["id"], user_id, question, context, parent,
                                          item.get("images") or None, shelf=shelf,
                                          highlight=highlight)
    return jsonify({"item": item}), 201


@interview_prep_bp.route("/api/prep/thoughts/<tid>", methods=["POST"])
@login_required
def thoughts_edit(tid):
    """Body: any of {understood, pinned, question, answer, tags, context}."""
    data = request.get_json(silent=True) or {}
    patch = {}
    for k in ("understood", "pinned"):
        if k in data:
            patch[k] = bool(data[k])
    if "question" in data:
        q = (data.get("question") or "").strip()[:thoughts_service.MAX_QUESTION]
        if not q:
            return jsonify({"error": "The question can't be empty."}), 400
        patch["question"] = q
    if "answer" in data:
        patch["answer"] = (data.get("answer") or "")[:60000]
        patch["status"] = "ready"
        # Marks it as yours, so a later improvement to a shipped answer
        # never overwrites your edit.
        patch["model"] = "edited by you"
    if "context" in data:
        patch["context"] = (data.get("context") or "").strip()[:thoughts_service.MAX_CONTEXT] or None
    if "tags" in data:
        patch["tags"] = _clean_tags(data.get("tags"))
    if not patch:
        return jsonify({"error": "nothing to save"}), 400
    patch["updated_at"] = _now_iso()
    where = {"id": f"eq.{tid}", "user_id": f"eq.{session['user_id']}"}
    try:
        update(thoughts_service.TABLE, params=where, json=patch)
    except Exception as exc:
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    out = {"status": "ok"}
    if "answer" in patch or patch.get("understood"):
        # An edited answer is re-spoken; a question marked studied gets its
        # audio for revision (both only where audio is wanted - see
        # thoughts_audio.start_if_wanted).
        try:
            out["audio"] = thoughts_audio.start_if_wanted(tid, session["user_id"])
        except Exception:
            logger.warning("thoughts: audio not queued", exc_info=True)
    if "understood" in patch:
        # Studied -> first review tomorrow. Unmarked -> out of the review cycle.
        if patch["understood"]:
            _, nxt = thoughts_service.next_review(0, "hard")
            sched = {"review_stage": 0, "next_review_at": nxt.isoformat()}
        else:
            sched = {"review_stage": 0, "next_review_at": None}
        try:
            update(thoughts_service.TABLE, params=where, json=sched)
            out.update(sched)
        except Exception as exc:
            if not thoughts_service.review_missing(exc):
                raise
            out["review_unavailable"] = True
    return jsonify(out)


@interview_prep_bp.route("/api/prep/thoughts/quiz/<int:step>", methods=["GET"])
@login_required
def thoughts_quiz(step):
    """The "choose the best answer" questions for one shipped answer, by its
    study step. Loaded when the quiz is opened, so the list stays light."""
    question, items = thoughts_service.quiz_for_step(step)
    if not question:
        return jsonify({"error": "Not found."}), 404
    resp = jsonify({"step": step, "question": question, "items": items})
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@interview_prep_bp.route("/api/prep/thoughts/<tid>/review", methods=["POST"])
@login_required
def thoughts_review(tid):
    """Body: {rating: again|hard|good|easy}. Records a spaced-repetition review
    and schedules the next one."""
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    if rating not in ("again", "hard", "good", "easy"):
        return jsonify({"error": "rating must be again, hard, good or easy"}), 400
    where = {"id": f"eq.{tid}", "user_id": f"eq.{session['user_id']}"}
    try:
        rows = get(thoughts_service.TABLE, dict(where, select="id,review_stage,review_count", limit="1")) or []
    except Exception as exc:
        if thoughts_service.review_missing(exc):
            return jsonify({"error": "Spaced reviews need the latest MIGRATION_PREP_THOUGHTS.sql run in Supabase (safe to re-run).",
                            "migration": thoughts_service.MIGRATION}), 503
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    if not rows:
        return jsonify({"error": "Not found."}), 404
    stage, nxt = thoughts_service.next_review(rows[0].get("review_stage"), rating)
    now = _now_iso()
    sched = {"review_stage": stage, "next_review_at": nxt.isoformat(), "last_reviewed_at": now,
             "review_count": int(rows[0].get("review_count") or 0) + 1, "understood": True, "updated_at": now}
    update(thoughts_service.TABLE, params=where, json=sched)
    return jsonify({"status": "ok", **sched})


@interview_prep_bp.route("/api/prep/thoughts/<tid>/retry", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def thoughts_retry(tid):
    """Write the answer again (after a failure, or to get a fresh take)."""
    user_id = session["user_id"]
    try:
        rows = _thought_get({"id": f"eq.{tid}", "user_id": f"eq.{user_id}",
                             "deleted_at": "is.null", "select": _THOUGHT_COLS, "limit": "1"})
        if not rows:
            return jsonify({"error": "Not found."}), 404
        t = rows[0]
        parent = thoughts_service.parent_of(user_id, t["parent_id"]) if t.get("parent_id") else None
        update(thoughts_service.TABLE, params={"id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
               json={"status": "pending", "error": None, "updated_at": _now_iso()})
    except Exception as exc:
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    thoughts_service.answer_in_background(tid, user_id, t["question"], t.get("context") or "",
                                          parent, t.get("images") or None, shelf=_shelf_arg(),
                                          highlight=thoughts_service.clean_highlight(t.get("highlight")))
    return jsonify({"status": "pending"})


@interview_prep_bp.route("/api/prep/thoughts/<tid>/images", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def thoughts_add_images(tid):
    """Attach images (multipart "images") to an existing question."""
    user_id = session["user_id"]
    try:
        files = _read_images(request.files.getlist("images"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not files:
        return jsonify({"error": "Choose an image first."}), 400
    rows = _thought_get({"id": f"eq.{tid}", "user_id": f"eq.{user_id}",
                         "deleted_at": "is.null", "select": "id,images", "limit": "1"})
    if not rows:
        return jsonify({"error": "Not found."}), 404
    have = rows[0].get("images") or []
    if len(have) + len(files) > thoughts_service.MAX_IMAGES:
        return jsonify({"error": f"Up to {thoughts_service.MAX_IMAGES} images per question."}), 400
    try:
        images = have + _store_images(user_id, files)
        update(thoughts_service.TABLE, params={"id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
               json={"images": images, "updated_at": _now_iso()})
    except Exception:
        logger.warning("thoughts: image upload failed", exc_info=True)
        return jsonify({"error": "Could not store the image. Check that the user-photos "
                                 "storage bucket exists (see MIGRATION_USER_PHOTOS.sql)."}), 502
    return jsonify({"images": images})


@interview_prep_bp.route("/api/prep/thoughts/<tid>/images/delete", methods=["POST"])
@login_required
def thoughts_remove_image(tid):
    """Body: {key}. Removes one attached image."""
    user_id = session["user_id"]
    key = ((request.get_json(silent=True) or {}).get("key") or "").strip()
    rows = _thought_get({"id": f"eq.{tid}", "user_id": f"eq.{user_id}",
                         "select": "id,images", "limit": "1"})
    if not rows:
        return jsonify({"error": "Not found."}), 404
    images = [im for im in (rows[0].get("images") or []) if im.get("key") != key]
    update(thoughts_service.TABLE, params={"id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
           json={"images": images, "updated_at": _now_iso()})
    if key.startswith(thoughts_service.owner_prefix(user_id)):
        thoughts_service.remove_image(key)
    return jsonify({"images": images})


# ── Spoken summaries (services/thoughts_audio.py) ──

def _audio_stale(a):
    """A build that has said "pending" for 10 minutes died with its process."""
    if (a or {}).get("status") != "pending":
        return False
    try:
        at = datetime.fromisoformat((a.get("at") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - at).total_seconds() > 600


@interview_prep_bp.route("/api/prep/thoughts/<tid>/audio", methods=["POST"])
@login_required
@limiter.limit("120 per hour")
def thoughts_audio_make(tid):
    """Make the question's audio if it has none or it is out of date.
    Body {force: true} remakes it anyway (a new take on the script)."""
    data = request.get_json(silent=True) or {}
    user_id = session["user_id"]
    try:
        rows = _thought_get({"id": f"eq.{tid}", "user_id": f"eq.{user_id}", "deleted_at": "is.null",
                             "select": "id,parent_id,question,answer,status,audio", "limit": "1"})
    except Exception as exc:
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    if not rows:
        return jsonify({"error": "Not found."}), 404
    t = rows[0]
    if "audio" not in t:
        return jsonify({"error": f"Audio needs the latest {thoughts_service.MIGRATION} run in "
                                 f"Supabase (it adds prep_thoughts.audio and the thought-audio "
                                 f"bucket; safe to re-run)."}), 503
    if t.get("parent_id") or t.get("status") != "ready":
        return jsonify({"error": "Audio is made once the answer is ready."}), 409
    force = bool(data.get("force"))
    if not force and thoughts_audio.is_current(t) and not _audio_stale(t.get("audio")):
        return jsonify({"audio": t["audio"]})
    return jsonify({"audio": thoughts_audio.start(tid, user_id, force=force)})


@interview_prep_bp.route("/interview-prep/thoughts/audio/<tid>", methods=["GET"])
@login_required
def thoughts_audio_file(tid):
    """The MP3, to its owner only, with Range support (iOS needs it to play)."""
    rows = get(thoughts_service.TABLE, {"id": f"eq.{tid}", "user_id": f"eq.{session['user_id']}",
                                        "select": "audio", "limit": "1"}) or []
    a = (rows[0].get("audio") if rows else None) or {}
    key = a.get("key") or ""
    if a.get("status") != "ready" or not key.startswith(thoughts_audio.owner_prefix(session["user_id"])):
        return jsonify({"error": "Not found."}), 404
    data = thoughts_audio.fetch(key)
    if data is None:
        return jsonify({"error": "Not found."}), 404
    resp = send_file(io.BytesIO(data), mimetype="audio/mpeg", conditional=True,
                     etag=a.get("hash") or key, max_age=31536000,
                     download_name=f"thought-{tid}.mp3")
    resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return resp


@interview_prep_bp.route("/interview-prep/thoughts/img/<path:key>", methods=["GET"])
@login_required
def thoughts_image(key):
    """Serve an attached image to its owner only (the bucket is private)."""
    if not key.startswith(thoughts_service.owner_prefix(session["user_id"])) or ".." in key:
        return jsonify({"error": "Not found."}), 404
    data, ctype = thoughts_service.fetch_image(key)
    if data is None:
        return jsonify({"error": "Not found."}), 404
    return Response(data, mimetype=ctype, headers={
        # Keys embed a random id and never change, so the browser can keep them.
        "Cache-Control": "private, max-age=31536000, immutable"})


# ── Your notes on a question ──
# Kept on the question's own row as a jsonb list, so the list endpoint
# returns them with no second query and search on the page covers them.
# Deleting one stamps deleted_at and keeps it (never a hard delete).

_MAX_NOTE = 5000
_MAX_NOTES = 200


def _live_notes(notes):
    """The notes the page shows: not deleted, oldest first."""
    return [n for n in (notes if isinstance(notes, list) else [])
            if isinstance(n, dict) and not n.get("deleted_at")]


def _notes_missing_resp():
    return jsonify({"error": "Notes need the latest MIGRATION_PREP_THOUGHTS.sql run in "
                             "Supabase (it adds the notes column; safe to re-run).",
                    "migration": thoughts_service.MIGRATION}), 503


def _notes_change(tid, change):
    """Load one question's notes, apply `change(notes) -> error or None`,
    save, and answer with the notes the page should now show."""
    user_id = session["user_id"]
    dropped = []
    try:
        rows = _thought_get({"id": f"eq.{tid}", "user_id": f"eq.{user_id}",
                             "deleted_at": "is.null", "select": "id,notes", "limit": "1"},
                            dropped=dropped)
    except Exception as exc:
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    if "notes" in dropped:
        return _notes_missing_resp()
    if not rows:
        return jsonify({"error": "That question no longer exists."}), 404
    notes = [n for n in (rows[0].get("notes") or []) if isinstance(n, dict)]
    err = change(notes)
    if err:
        return jsonify({"error": err[0]}), err[1]
    try:
        update(thoughts_service.TABLE, params={"id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
               json={"notes": notes})
    except Exception as exc:
        if "notes" in str(exc):
            return _notes_missing_resp()
        logger.warning("thoughts: note save failed for %s", tid, exc_info=True)
        return jsonify({"error": "Couldn't save that note - please retry."}), 502
    return jsonify({"notes": _live_notes(notes)})


def _note_text():
    return ((request.get_json(silent=True) or {}).get("text") or "").strip()[:_MAX_NOTE]


@interview_prep_bp.route("/api/prep/thoughts/<tid>/notes", methods=["POST"])
@login_required
def thoughts_note_add(tid):
    """Body: {text}. Adds a note to a question or follow-up."""
    text = _note_text()
    if not text:
        return jsonify({"error": "Write the note first."}), 400

    def add(notes):
        if len(_live_notes(notes)) >= _MAX_NOTES:
            return (f"Up to {_MAX_NOTES} notes per question.", 400)
        now = _now_iso()
        notes.append({"id": uuid.uuid4().hex[:12], "text": text,
                      "created_at": now, "updated_at": now})
    return _notes_change(tid, add)


@interview_prep_bp.route("/api/prep/thoughts/<tid>/notes/<nid>", methods=["POST"])
@login_required
def thoughts_note_edit(tid, nid):
    """Body: {text}. Rewrites one note."""
    text = _note_text()
    if not text:
        return jsonify({"error": "A note can't be empty - delete it instead."}), 400

    def edit(notes):
        for n in _live_notes(notes):
            if n.get("id") == nid:
                n["text"] = text
                n["updated_at"] = _now_iso()
                return None
        return ("That note no longer exists.", 404)
    return _notes_change(tid, edit)


@interview_prep_bp.route("/api/prep/thoughts/<tid>/notes/<nid>/delete", methods=["POST"])
@login_required
def thoughts_note_delete(tid, nid):
    """Soft delete: the note is stamped deleted_at and kept in the row."""
    def drop(notes):
        for n in _live_notes(notes):
            if n.get("id") == nid:
                n["deleted_at"] = _now_iso()
                return None
        return ("That note no longer exists.", 404)
    return _notes_change(tid, drop)


@interview_prep_bp.route("/api/prep/thoughts/<tid>/delete", methods=["POST"])
@login_required
def thoughts_delete(tid):
    """Soft delete; deleting a thread's first question removes the thread."""
    user_id = session["user_id"]
    now = _now_iso()
    try:
        update(thoughts_service.TABLE, params={"id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
               json={"deleted_at": now})
        update(thoughts_service.TABLE, params={"root_id": f"eq.{tid}", "user_id": f"eq.{user_id}"},
               json={"deleted_at": now})
    except Exception as exc:
        if _thoughts_missing(exc):
            return _thought_missing_resp()
        raise
    return jsonify({"status": "ok"})


@interview_prep_bp.route("/interview-prep/thoughts/<tid>/pdf", methods=["GET"])
@login_required
def thoughts_pdf(tid):
    """One thread (the question and its follow-ups) as a phone-readable PDF."""
    user_id = session["user_id"]
    rows = _thought_get({"root_id": f"eq.{tid}", "user_id": f"eq.{user_id}",
                         "deleted_at": "is.null", "select": _THOUGHT_COLS,
                         "order": "created_at.asc", "limit": "50"})
    if not rows:
        return jsonify({"error": "Not found."}), 404
    sections = [{
        "title": (("Hint: " if r.get("highlight") else "Follow-up: ") if r.get("parent_id") else "") + r["question"],
        "cat": (r.get("created_at") or "")[:10],
        "fields": [("Highlighted" if r.get("highlight") else "What prompted it", r.get("context")),
                   ("Images", (f"{len(r['images'])} image(s) attached - view them in the app"
                               if r.get("images") else None)),
                   ("Answer", _md_plain(r.get("answer") or r.get("error") or "Not answered yet.")),
                   ("Your notes", "\n\n".join(
                       f"{(n.get('created_at') or '')[:10]}: {n.get('text') or ''}"
                       for n in _live_notes(r.get("notes"))) or None)],
        "arch": None, "tags": r.get("tags") or None,
    } for r in rows]
    try:
        pdf = _pdf_bytes("Random thoughts", rows[0]["question"][:90], sections, body_pt=_pdf_body_pt())
    except ImportError:
        return jsonify({"error": "PDF export needs fpdf2 on the server."}), 503
    return _pdf_response(pdf, "random-thought.pdf")


def _md_plain(text):
    """Markdown answer -> plain text for the PDF: headings in capitals,
    emphasis markers and code fences dropped, lists kept."""
    out = []
    in_mermaid = False
    for line in (text or "").split("\n"):
        st = line.strip()
        if st.startswith("```mermaid"):
            in_mermaid = True
            out.append("[Diagram - open this question in the app to see it]")
            continue
        if in_mermaid:
            if st.startswith("```"):
                in_mermaid = False
            continue
        if st.startswith("```"):
            continue
        m = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if m:
            out.append("")
            out.append(m.group(1).upper())
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"^\s*[-*]\s+", "* ", line)
        out.append(line)
    return "\n".join(out).strip()


# ─────────── System design deep dives ───────────────────────────────
#
# BRD, PRD, HLD, LLD, edge cases, tech stack, distributed-systems concepts
# with Q&A, and a choose-the-best-answer quiz per design: the Beyz question
# bank's 55 prompts (Clarify -> Design -> Defend) plus classic designs from
# the wider canon, Uber as the flagship. Content: sd_deep/*.json.

BEYZ_FRAMEWORK = [
    {"step": "Clarify", "points": [
        "Who are the users, and what does success mean?",
        "What does 'fast' mean here - which latency, at which percentile?",
        "What breaks first, and which trade-off matters most?",
        "State your assumptions out loud in the first minute."]},
    {"step": "Design", "points": [
        "Build the baseline first, before any optimisation.",
        "Name the core components and define the APIs.",
        "Walk the critical path end to end."]},
    {"step": "Defend", "points": [
        "Name the bottleneck - the first resource to saturate.",
        "Scale reads: caching, replication, precomputation, staleness.",
        "Scale writes: partitioning, batching, async, idempotency.",
        "Failure: timeouts, retries with jitter, fallbacks, bulkheads, degradation.",
        "Close with what you would measure."]},
]


def _deep_list():
    out = sd_deep_bank.summary_list()
    for i, d in enumerate(out):
        d["id"] = f"dd{i}"
    return out


@interview_prep_bp.route("/api/sd-deep", methods=["GET"])
@login_required
def sd_deep_list():
    return jsonify({
        "groups": [{"key": k, "label": v} for k, v in sd_deep_bank.GROUPS.items()],
        "framework": BEYZ_FRAMEWORK,
        "designs": _deep_list(),
        "total": len(sd_deep_bank.DESIGNS),
    })


@interview_prep_bp.route("/api/sd-deep/<slug>", methods=["GET"])
@login_required
def sd_deep_one(slug):
    d = sd_deep_bank.BY_SLUG.get(slug)
    if not d:
        return jsonify({"error": "Unknown design"}), 404
    resp = jsonify(d)
    # Static content that changes only on deploy; the SW revalidates.
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


def _bullets(items):
    return "\n".join(f"* {x}" for x in items if x) or None


@interview_prep_bp.route("/interview-prep/design/<slug>/pdf", methods=["GET"])
@login_required
def sd_deep_pdf(slug):
    """One deep dive as a phone-readable PDF, quiz answers at the end."""
    d = sd_deep_bank.BY_SLUG.get(slug)
    if not d:
        return jsonify({"error": "Unknown design"}), 404
    fw, brd, prd, hld, lld = d["framework"], d["brd"], d["prd"], d["hld"], d["lld"]
    S = lambda title, fields, arch=None, cat="": {
        "title": title, "cat": cat, "fields": fields, "arch": arch, "tags": None}
    sections = [
        S("Overview", [("Prompt", d["prompt"]), ("Summary", d["summary"]),
                       ("Say this out loud", _bullets(d["key_points"]))]),
        S("Clarify -> Design -> Defend", [
            ("Clarify", _bullets(fw["clarify"])), ("Design", _bullets(fw["design"])),
            ("Defend", _bullets(fw["defend"])), ("Spoken opener", fw["script"])]),
        S("BRD - business requirements", [
            ("Problem", brd["problem"]), ("Goals", _bullets(brd["goals"])),
            ("Non-goals", _bullets(brd["non_goals"])),
            ("Stakeholders", _bullets(f"{x['who']}: {x['needs']}" for x in brd["stakeholders"])),
            ("Success metrics", _bullets(f"{x['metric']}: {x['target']}" for x in brd["success_metrics"])),
            ("Constraints", _bullets(brd["constraints"])),
            ("Risks", _bullets(f"{x['risk']} -> {x['mitigation']}" for x in brd["risks"]))]),
        S("PRD - product requirements", [
            ("Personas", _bullets(f"{x['name']}: {x['needs']}" for x in prd["personas"])),
            ("User stories", _bullets(prd["user_stories"])),
            ("Functional", _bullets(prd["functional"])),
            ("Non-functional", _bullets(f"{x['name']}: {x['target']}" for x in prd["non_functional"])),
            ("Capacity assumptions", _bullets(prd["capacity"]["assumptions"])),
            ("Back of the envelope", _bullets(prd["capacity"]["math"])),
            ("Capacity summary", prd["capacity"]["summary"]),
            ("Out of scope", _bullets(prd["out_of_scope"]))]),
        S("HLD - high-level design", [
            ("Overview", hld["overview"]),
            ("Components", _bullets(f"{x['name']}: {x['responsibility']}" for x in hld["components"])),
            ("Data flow", hld["data_flow"])], arch=hld["diagram"]),
    ]
    for f in hld["flows"]:
        sections.append(S(f"Flow: {f['name']}", [("Steps", "\n".join(
            f"{i}. {x}" for i, x in enumerate(f["steps"], 1)))]))
    sections.append(S("LLD - APIs", [(f"{a['method']} {a['path']}", "\n".join(x for x in [
        f"Request: {a['request']}", f"Response: {a['response']}",
        (f"Notes: {a['notes']}" if a.get("notes") else "")] if x)) for a in lld["apis"]]))
    sections.append(S("LLD - data model", [(f"{m['entity']} ({m['store']})", "\n".join(x for x in [
        "Fields: " + ", ".join(m["fields"]), f"Keys: {m['keys']}",
        (f"Notes: {m['notes']}" if m.get("notes") else "")] if x)) for m in lld["data_model"]]))
    sections.append(S("LLD - classes", [(c["name"], c["responsibility"] + "\n" + _bullets(c["methods"]))
                                        for c in lld["classes"]]))
    for a in lld["algorithms"]:
        sections.append(S(f"Algorithm: {a['name']}", [("How it works", a["explain"])], arch=a["pseudocode"]))
    sections.append(S("Sequence: the critical path", [], arch=lld["sequence"]))
    sections.append(S("Edge cases", [(e["case"], e["handling"]) for e in d["edge_cases"]]))
    sections.append(S("Tech stack", [(f"{t['name']} ({t['layer']})", "\n".join([
        t["overview"], f"Why here: {t['why']}", f"Alternatives: {t['alternatives']}"])) for t in d["tech_stack"]]))
    for c in d["concepts"]:
        sections.append(S(f"Concept: {c['name']}", [
            ("Explained", c["explain"]), ("In this design", c["in_this_design"]),
            ("Key points", _bullets(c["key_points"]))]
            + [(f"Q: {qa['q']}", qa["a"]) for qa in c["qa"]]))
    sections.append(S("Trade-offs", [(t["decision"], f"Options: {t['options']}\nChoice: {t['choice']}\nWhy: {t['why']}")
                                     for t in d["tradeoffs"]]))
    sections.append(S("Failure modes", [(f["failure"], f["behavior"]) for f in d["failure_modes"]]
                      + [("What to measure", _bullets(d["metrics"]))]))
    sections.append(S("Interviewer follow-ups", [(f"Q: {x['q']}", x["a"]) for x in d["follow_ups"]]))
    sections.append(S("Quiz - choose the best answer", [(f"{i}. {q['q']}", "\n".join(
        f"{'ABCD'[j]}) {o}" for j, o in enumerate(q["options"]))) for i, q in enumerate(d["quiz"], 1)]))
    sections.append(S("Quiz answers", [(f"{i}. {'ABCD'[q['answer']]}", q["why"])
                                       for i, q in enumerate(d["quiz"], 1)]))
    sections.append(S("References", [(r["title"], r["url"]) for r in d["references"]]))
    subtitle = " | ".join([d["prompt"], f"{d['minutes']} min", "DailyPlanner Interview Prep",
                           _today().isoformat()])
    try:
        pdf = _pdf_bytes(d["title"], subtitle, sections, body_pt=_pdf_body_pt())
    except ImportError:
        return jsonify({"error": "PDF export needs fpdf2 on the server."}), 503
    return _pdf_response(pdf, f"{slug}.pdf")


# ─────────── Rehearsal progress, saved server-side ──────────────────
#
# The banks used to keep "rehearsed" ticks in localStorage, keyed by each
# entry's POSITION (t4, q19, sd7). Two problems: ticks on the phone never
# reached the laptop, and inserting one entry shifted every position after
# it, so the wrong cases showed as rehearsed. Rows here are keyed by the
# entry's TITLE, and ids are worked out from the bank as it is now.

#: bank -> (entries, field holding the title, id prefix)
_PROGRESS_BANKS = {
    "tpm":        (lambda: TPM_ROUND_ENTRIES, "title", "t"),
    "behavioral": (lambda: QUESTIONS,         "q",     "q"),
    "sysdesign":  (lambda: SD_ENTRIES,        "title", "sd"),
    "sddeep":     (lambda: sd_deep_bank.DESIGNS, "title", "dd"),
}
PROGRESS_MIGRATION = "MIGRATION_PREP_PROGRESS.sql"


def _progress_maps(bank):
    entries, field, prefix = _PROGRESS_BANKS[bank]
    es = entries()
    by_id = {f"{prefix}{i}": e[field] for i, e in enumerate(es)}
    return by_id, {t: i for i, t in by_id.items()}


def _progress_missing(exc):
    text = str(exc)
    return ("prep_progress" in text or "does not exist" in text
            or "schema cache" in text)


def _progress_rows(user_id, bank=None, done_only=False):
    params = {"user_id": f"eq.{user_id}",
              "select": "bank,entry_title,done,done_at,mock_attempts,"
                        "mock_last_score,mock_best_score,mock_last_at,quiz_best_pct",
              "limit": "5000"}
    if bank:
        params["bank"] = _pg_eq(bank)
    if done_only:
        params["done"] = "eq.true"
    try:
        return get("prep_progress", params=params) or []
    except Exception as exc:
        # The table predates quiz_best_pct if the migration was run before
        # that column was added; read without it rather than lose the ticks.
        if "quiz_best_pct" not in str(exc):
            raise
        params["select"] = params["select"].replace(",quiz_best_pct", "")
        return get("prep_progress", params=params) or []


@interview_prep_bp.route("/api/prep/progress", methods=["GET"])
@login_required
def prep_progress_get():
    """{done: [ids], mock: {id: {...}}} for one bank. ``?bank=tpm``"""
    bank = (request.args.get("bank") or "").strip()
    if bank not in _PROGRESS_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400
    try:
        rows = _progress_rows(session["user_id"], bank)
    except Exception as exc:
        if _progress_missing(exc):
            logger.warning("prep progress unavailable - run %s", PROGRESS_MIGRATION)
            return jsonify({"bank": bank, "available": False, "done": [],
                            "mock": {}, "migration": PROGRESS_MIGRATION})
        raise
    _, by_title = _progress_maps(bank)
    done, mock, quiz = [], {}, {}
    for r in rows:
        eid = by_title.get(r.get("entry_title"))
        if not eid:
            continue          # renamed or removed since it was recorded
        if r.get("done"):
            done.append(eid)
        if r.get("quiz_best_pct") is not None:
            quiz[eid] = r["quiz_best_pct"]
        if r.get("mock_attempts"):
            mock[eid] = {"attempts": r["mock_attempts"],
                         "last": r.get("mock_last_score"),
                         "best": r.get("mock_best_score"),
                         "at": r.get("mock_last_at")}
    return jsonify({"bank": bank, "available": True, "done": done, "mock": mock,
                    "quiz": quiz})


@interview_prep_bp.route("/api/prep/progress", methods=["POST"])
@login_required
def prep_progress_save():
    """Body: ``{bank, id, done}`` to tick or untick one entry;
    ``{bank, ids: [...]}`` to import ticks in bulk (the one-off move from
    localStorage); ``{bank, id, mock_score: 1-4}`` to record a mock run."""
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    bank = (data.get("bank") or "").strip()
    if bank not in _PROGRESS_BANKS:
        return jsonify({"error": f"unknown bank {bank!r}"}), 400
    by_id, _ = _progress_maps(bank)
    now = _iso_now()
    target = "prep_progress?on_conflict=user_id,bank,entry_title"

    def _row(title, **extra):
        return {"user_id": user_id, "bank": bank, "entry_title": title,
                "updated_at": now, **extra}

    try:
        if isinstance(data.get("ids"), list):
            titles = [by_id[i] for i in data["ids"][:2000] if i in by_id]
            if titles:
                post(target, [_row(t, done=True, done_at=now) for t in titles],
                     prefer="resolution=merge-duplicates,return=minimal")
            return jsonify({"status": "ok", "imported": len(titles)})

        title = by_id.get((data.get("id") or "").strip())
        if not title:
            return jsonify({"error": "unknown entry"}), 400

        if "quiz_pct" in data:
            try:
                pct = int(data["quiz_pct"])
            except (TypeError, ValueError):
                return jsonify({"error": "quiz_pct must be 0-100"}), 400
            if not 0 <= pct <= 100:
                return jsonify({"error": "quiz_pct must be 0-100"}), 400
            prev = (get("prep_progress", params={
                "user_id": f"eq.{user_id}", "bank": _pg_eq(bank),
                "entry_title": _pg_eq(title),
                "select": "quiz_best_pct,done", "limit": "1",
            }) or [{}])[0]
            best = max(pct, int(prev.get("quiz_best_pct") or 0))
            row = _row(title, quiz_best_pct=best)
            # 80%+ on the quiz is what "studied" means for a deep dive.
            if pct >= 80 and not prev.get("done"):
                row.update(done=True, done_at=now)
            post(target, row, prefer="resolution=merge-duplicates,return=minimal")
            return jsonify({"status": "ok", "best": best,
                            "done": bool(row.get("done") or prev.get("done"))})

        if "mock_score" in data:
            try:
                score = int(data["mock_score"])
            except (TypeError, ValueError):
                return jsonify({"error": "mock_score must be 1-4"}), 400
            if not 1 <= score <= 4:
                return jsonify({"error": "mock_score must be 1-4"}), 400
            prev = (get("prep_progress", params={
                "user_id": f"eq.{user_id}", "bank": _pg_eq(bank),
                "entry_title": _pg_eq(title),
                "select": "mock_attempts,mock_best_score,done", "limit": "1",
            }) or [{}])[0]
            row = _row(title,
                       mock_attempts=int(prev.get("mock_attempts") or 0) + 1,
                       mock_last_score=score,
                       mock_best_score=max(score, int(prev.get("mock_best_score") or 0)),
                       mock_last_at=now)
            # A run scored 3+ out loud IS a rehearsal; a weak run does not
            # untick one that was already done.
            if score >= 3 and not prev.get("done"):
                row.update(done=True, done_at=now)
            post(target, row, prefer="resolution=merge-duplicates,return=minimal")
            return jsonify({"status": "ok", "attempts": row["mock_attempts"],
                            "best": row["mock_best_score"],
                            "done": bool(row.get("done") or prev.get("done"))})

        if "done" not in data:
            return jsonify({"error": "nothing to save"}), 400
        done = bool(data["done"])
        post(target, _row(title, done=done, done_at=now if done else None),
             prefer="resolution=merge-duplicates,return=minimal")
        return jsonify({"status": "ok", "done": done})
    except Exception as exc:
        if _progress_missing(exc):
            return jsonify({"error": f"Progress sync is not set up yet. Run "
                                     f"{PROGRESS_MIGRATION} in Supabase.",
                            "migration": PROGRESS_MIGRATION}), 503
        raise


@interview_prep_bp.route("/api/interview-prep/questions", methods=["GET"])
@login_required
def question_bank():
    """The behavioral question bank: 100+ common questions with STAR model
    answers, grouped by competency. Static reference content, with each
    answer overlaid by the user's own edits (interview_question_overrides)
    when present, so edits persist across deploys."""
    user_id = session["user_id"]
    return jsonify({
        "categories": [{"key": k, "label": v} for k, v in QUESTION_CATEGORIES.items()],
        "questions": _beh_merged_items(user_id),
        "total": len(QUESTIONS),
    })


def _beh_merged_items(user_id):
    """Behavioral bank with the user's edits merged over the originals.
    Shared by the JSON API and the printable view."""
    items = [{"id": f"q{i}", **q, "edited": False} for i, q in enumerate(QUESTIONS)]
    try:
        overrides = get("interview_question_overrides", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "question_id,question,situation,task,action,result,tip",
            "limit": "1000",
        }) or []
    except Exception:
        overrides = []
    ovmap = {o.get("question_id"): o for o in overrides}
    for it in items:
        o = ovmap.get(it["id"])
        if not o:
            continue
        if (o.get("question") or "").strip():
            it["q"] = o["question"]
        for short, col in _OVERRIDE_MAP.items():
            if short == "q":
                continue
            if o.get(col) is not None:
                it[short] = o[col]
        it["edited"] = True
    return items


@interview_prep_bp.route("/interview-prep/behavioral/print", methods=["GET"])
@login_required
def behavioral_print():
    """Print-optimised page for the behavioral bank (browser Save-as-PDF).
    Filters: ?cat=<key>  ?tag=<tag>  ?q=<text>  ?id=qN."""
    user_id = session["user_id"]
    items = _beh_merged_items(user_id)
    cat = (request.args.get("cat") or "").strip()
    tag = (request.args.get("tag") or "").strip().lower()
    q = (request.args.get("q") or "").strip().lower()
    one = (request.args.get("id") or "").strip()

    def _match(it):
        if one:
            return it["id"] == one
        if cat and it.get("cat") != cat:
            return False
        if tag and tag not in [t.lower() for t in (it.get("tags") or [])]:
            return False
        if q:
            hay = (it.get("q", "") + " " + " ".join(it.get("tags") or [])).lower()
            if q not in hay:
                return False
        return True

    selected = [it for it in items if _match(it)]
    label = "Behavioral Question Bank"
    if one and selected:
        label = selected[0]["q"][:80]
    elif cat:
        label = QUESTION_CATEGORIES.get(cat, cat)
    elif tag:
        label = f"Tag: #{tag}"
    elif q:
        label = f"Search: {q}"

    return render_template(
        "behavioral_print.html",
        questions=selected,
        category_labels=QUESTION_CATEGORIES,
        heading=label, count=len(selected), today=_today().isoformat(),
    )


@interview_prep_bp.route("/interview-prep/behavioral/pdf", methods=["GET"])
@login_required
def behavioral_pdf():
    """Server-generated PDF of the behavioral bank (STAR answers), same
    filters. Falls back to the print view if fpdf2 is unavailable."""
    user_id = session["user_id"]
    selected, label = _bank_select(
        _beh_merged_items(user_id), ("q",), QUESTION_CATEGORIES, "q")
    selected.sort(key=lambda it: it.get("rank") or 0)
    heading = label or "Behavioral Question Bank"
    _mins = sum(it.get("prep_minutes") or 0 for it in selected)
    subtitle = " | ".join(x for x in [
        f"{len(selected)} question{'' if len(selected) == 1 else 's'}",
        (f"{_mins // 60}h {_mins % 60}m of prep" if _mins else ""),
        "DailyPlanner Interview Prep", _today().isoformat()] if x)
    sections = [{
        "title": it["q"],
        "cat": QUESTION_CATEGORIES.get(it.get("cat"), it.get("cat", "")),
        # Planning line first, then STAR, then the two coaching blocks: what
        # separates a hire on this question, and the follow-ups they will push.
        "fields": [(" ".join(x for x in [
                        f"Prep time & priority",
                    ] if x),
                    " | ".join(x for x in [
                        (f"{it['prep_label']}" if it.get("prep_label") else ""),
                        (f"Stack rank #{it['rank']}" if it.get("rank") else ""),
                        (f"Story: {it['story_label']}" if it.get("story_label") else ""),
                        (it.get("priority_note") or "")] if x) or None),
                   ("Situation", it.get("s")), ("Task", it.get("t")),
                   ("Action", it.get("a")), ("Result", it.get("r")),
                   ("Tip", it.get("tip")),
                   ("Strong vs weak", it.get("strong_weak")),
                   ("They will push back",
                    "\n".join(f"{n}. {p}" for n, p in
                              enumerate(it.get("probes") or [], 1)) or None)],
        "arch": None, "tags": it.get("tags"),
    } for it in selected]
    try:
        pdf = _pdf_bytes(heading, subtitle, sections, body_pt=_pdf_body_pt())
    except ImportError:
        return redirect(url_for("interview_prep.behavioral_print", **request.args.to_dict()))
    fname = (selected[0]["id"] + ".pdf") if len(selected) == 1 else "behavioral-bank.pdf"
    return _pdf_response(pdf, fname)


@interview_prep_bp.route("/api/interview-prep/questions/<qid>", methods=["POST"])
@login_required
def save_question_override(qid):
    """Upsert the user's edited copy of a bank question."""
    user_id = session["user_id"]
    if not _valid_qid(qid):
        return jsonify({"error": "Unknown question"}), 404
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()[:_MAX_TEXT]
    if not question:
        return jsonify({"error": "The question can't be empty"}), 400
    payload = {
        "user_id": user_id,
        "question_id": qid,
        "question": question,
        "situation": (data.get("situation") or "").strip()[:_MAX_TEXT] or None,
        "task": (data.get("task") or "").strip()[:_MAX_TEXT] or None,
        "action": (data.get("action") or "").strip()[:_MAX_TEXT] or None,
        "result": (data.get("result") or "").strip()[:_MAX_TEXT] or None,
        "tip": (data.get("tip") or "").strip()[:_MAX_TEXT] or None,
        "deleted_at": None,          # revive if it was previously reset
        "updated_at": _now_iso(),
    }
    try:
        post("interview_question_overrides?on_conflict=user_id,question_id",
             payload, prefer="resolution=merge-duplicates")
    except Exception as e:
        logger.exception("save question override failed: %s", e)
        return jsonify({"error": "Couldn't save — run MIGRATION_INTERVIEW_QUESTION_OVERRIDES.sql?"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/questions/<qid>/reset", methods=["POST"])
@login_required
def reset_question_override(qid):
    """Soft-delete the override so the original bank answer shows again."""
    user_id = session["user_id"]
    if not _valid_qid(qid):
        return jsonify({"error": "Unknown question"}), 404
    try:
        update("interview_question_overrides",
               params={"user_id": f"eq.{user_id}", "question_id": f"eq.{qid}"},
               json={"deleted_at": _now_iso()})
    except Exception as e:
        logger.exception("reset question override failed: %s", e)
        return jsonify({"error": "Couldn't reset"}), 502
    return jsonify({"ok": True})


# ─────────── system design bank ─────────────────────────────

_SD_FIELDS = ("title", "problem", "answer", "example", "use_cases",
              "arch", "disadvantages", "competing")


def _valid_sid(eid):
    if not (isinstance(eid, str) and eid.startswith("sd")):
        return False
    try:
        return 0 <= int(eid[2:]) < len(SD_ENTRIES)
    except ValueError:
        return False


# ─────────── PDF generation (server-side, pure Python) ──────

# Map the Unicode we use (box-drawing, arrows, smart punctuation) to ASCII
# so fpdf2's built-in latin-1 core fonts can render it without a bundled
# TTF. Anything still outside latin-1 is replaced rather than erroring.
_UNI_MAP = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    "→": "->", "←": "<-", "↑": "^", "↓": "v",
    "⇄": "<->", "▶": ">", "◀": "<", "▲": "^", "▼": "v",
    "─": "-", "━": "-", "│": "|", "┌": "+", "┐": "+",
    "└": "+", "┘": "+", "├": "+", "┤": "+", "┬": "+",
    "┴": "+", "┼": "+", "⬇": "v", "‹": "<", "›": ">",
    "✓": "[ok]", "≤": "<=", "≥": ">=", "²": "2",
    "₹": "Rs ", "″": '"', "′": "'",
}


def _latin1(s):
    if not s:
        return ""
    for k, v in _UNI_MAP.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


#: Where to look for a real Unicode font. Debian/Ubuntu (and Render's
#: images) ship fonts-dejavu-core; if none of these exist the renderer
#: falls back to fpdf2's built-in core fonts and _latin1() transliteration,
#: which is what the export did before — degraded, never broken.
_PDF_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf",
     "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/TTF/DejaVuSansMono.ttf"),
)

#: Body size, in points. 26 was asked for explicitly, and it is also the
#: right answer: on A4 with 12 mm margins it yields ~40 characters per
#: line, which is the measure a phone shows comfortably when the page is
#: fitted to width. A PDF's point size means nothing on its own — what a
#: reader actually experiences is CHARACTERS PER LINE after fit-to-width.
_PDF_BODY_PT = 26
_PDF_MIN_PT, _PDF_MAX_PT = 12, 40

#: Never shrink a monospace block below this. Under it, the block goes on
#: its own LANDSCAPE page, where the column is 273 mm instead of 186 and
#: the same content lands ~47% larger.
_PDF_MONO_FLOOR_PT = 8.25


def _pdf_body_pt():
    """?fs= lets the reader pick a body size; 26pt is the default.

    26pt on A4 gives ~40 characters per line, which is what a phone shows
    comfortably when the page is fitted to width. Someone reading on a
    laptop wants more text per page, so the knob is worth having — but the
    DEFAULT is the phone, because that is where prep actually gets read.
    """
    raw = (request.args.get("fs") or "").strip()
    if not raw:
        return _PDF_BODY_PT
    try:
        return max(_PDF_MIN_PT, min(_PDF_MAX_PT, float(raw)))
    except ValueError:
        return _PDF_BODY_PT


def _pdf_register_fonts(pdf):
    """Register DejaVu if the system has it. Returns (sans, mono, unicode?).

    With a real Unicode font the box-drawing characters, arrows and smart
    punctuation in the bank render as themselves. Without one they are
    transliterated to ASCII by _latin1(), which is why the old export
    turned diagrams into noise.
    """
    import os
    for regular, bold, mono in _PDF_FONT_CANDIDATES:
        if not (os.path.exists(regular) and os.path.exists(mono)):
            continue
        try:
            pdf.add_font("dj", "", regular)
            pdf.add_font("dj", "B", bold if os.path.exists(bold) else regular)
            pdf.add_font("djm", "", mono)
            return "dj", "djm", True
        except Exception as exc:                      # pragma: no cover
            logger.warning("PDF: could not load %s (%s)", regular, exc)
            break
    logger.info("PDF: no Unicode font found; falling back to core fonts")
    return "Helvetica", "Courier", False


#: Characters that only ever appear in drawn art, never in prose.
_PDF_BOX_CHARS = frozenset("─│┌┐└┘├┤┬┴┼━┏┓┗┛┣┫┳┻╋╔╗╚╝║═╠╣╦╩╬")
_PDF_RULE_RE = re.compile(r"^[\s|+\-=_.·]{8,}$")
#: Column alignment, distinguished from an accidental double space after a
#: full stop: either a deliberate 3+ space gap, or two separate 2+ space
#: gaps on one line (which is a table row, not a sentence).
_PDF_ALIGN_WIDE_RE = re.compile(r"\S {3,}\S")
_PDF_ALIGN_RE = re.compile(r"\S {2,}\S")


def _pdf_is_fixed_width(line):
    """True if `line` must keep its exact spacing, None if it is blank.

    The bank's worked examples interleave prose with drawn tables and
    hand-traces in the SAME string. Rendering the whole block as prose
    wraps the tables into noise — which is what the export used to do —
    and rendering it all as monospace shrinks the prose to 8pt for no
    reason. So each line is judged on its own and consecutive verdicts
    are grouped into runs.
    """
    if not line.strip():
        return None                       # blank: inherits its neighbours
    if any(c in _PDF_BOX_CHARS for c in line):
        return True
    if _PDF_RULE_RE.match(line):
        return True
    if line.startswith(("    ", "\t")):   # indented code or a variable trace
        return True
    if _PDF_ALIGN_WIDE_RE.search(line):
        return True
    # A single 2-space gap is usually "end.  Next sentence"; two or more on
    # one line is a table row. Length is not the discriminator — a SHORT
    # table row must not be split away from the wide rows under it.
    return len(_PDF_ALIGN_RE.findall(line)) >= 2


def _pdf_runs(text):
    """Split `text` into [(is_fixed_width, "chunk"), ...] preserving order.

    Measured over the whole bank: 41% of example lines are fixed-width and
    59% are prose. Isolating them matters — the fixed-width RUNS are only
    106 columns at p99, against 107 for the blocks they sit in, so nearly
    all of them fit portrait instead of being rotated or shrunk.
    """
    runs, cur, kind = [], [], None
    for line in (text or "").split("\n"):
        k = _pdf_is_fixed_width(line)
        if k is None:
            cur.append(line)
            continue
        if kind is None:
            kind = k
        if k != kind:
            runs.append((kind, "\n".join(cur).strip("\n")))
            cur, kind = [], k
        cur.append(line)
    if cur:
        runs.append((bool(kind), "\n".join(cur).strip("\n")))
    return [(k, t) for k, t in runs if t.strip()]


def _pdf_bytes(heading, subtitle, sections, body_pt=_PDF_BODY_PT):
    """Build a PDF from sections. Each section:
    {title, cat, fields:[(label,text)...], arch, tags}. Raises ImportError
    if fpdf2 isn't installed (caller falls back to the print view).

    THE TENSION THIS RESOLVES. The body is set large (26pt) so it can be
    read on a phone. But the bank's worked examples are pre-wrapped ASCII
    drawn to a MEASURED median of 101 columns (p99 = 107) — code to 76,
    diagrams to 68. A 105-column block cannot be shown at 26pt on any page
    that also gives prose a sane measure; that is arithmetic, not a bug.

    The old renderer fed those blocks through multi_cell at a fixed 8pt on
    a 182 mm column, so every line that overflowed HARD-WRAPPED and the art
    became noise. Here each monospace block is measured and scaled so its
    widest line fits the column exactly — small, but intact and zoomable.
    Blocks that would fall under _PDF_MONO_FLOOR_PT get their own landscape
    page instead, where they land ~47% larger.

    NOT DONE, and not doable here: true reflow ("Adobe liquid mode") needs
    a tagged PDF with a structure tree over the paragraphs. fpdf2 2.8.x
    builds a structure tree for outlines and links only and exposes no
    public API to tag body text, so this sets the document language and
    title — which is what helps a reader — and stops short of claiming
    reflow it does not provide.
    """
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    NX, NY = XPos.LMARGIN, YPos.NEXT  # each line returns to the left margin

    body_pt = max(_PDF_MIN_PT, min(_PDF_MAX_PT, float(body_pt or _PDF_BODY_PT)))
    scale = body_pt / 10.0            # every other size is relative to the body

    MARGIN = 12
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    SANS, MONO, unicode_ok = _pdf_register_fonts(pdf)
    # With a real font the text is kept as written; without one it is
    # transliterated, which is the pre-existing behaviour.
    txt = (lambda s: s or "") if unicode_ok else _latin1
    pdf.set_title(heading or "Interview prep")
    pdf.set_lang("en")
    pdf.add_page()

    portrait_col = pdf.w - 2 * MARGIN
    landscape_col = 297 - 2 * MARGIN

    def line_h(size):
        """Leading for a given point size, in mm. 1pt = 0.3528mm."""
        return size * 0.3528 * 1.22

    def cell(size, text, style="", h=None):
        pdf.set_font(SANS, style, size)
        pdf.multi_cell(0, h or line_h(size), txt(text), new_x=NX, new_y=NY)

    # Millimetres of advance per point of font size, for ONE monospace
    # character. Measured from the font actually in use rather than
    # assumed, so it stays correct under the core-font fallback too.
    pdf.set_font(MONO, "", 10)
    mono_mm_per_pt = pdf.get_string_width("M") / 10.0

    def mono_block(text, col_mm):
        """Size a monospace block so its WIDEST line fits `col_mm` exactly."""
        lines = (text or "").split("\n")
        cols = max((len(l) for l in lines), default=1) or 1
        fitted = col_mm / (cols * mono_mm_per_pt)
        # Never bigger than the body, never so small it is decorative only.
        return max(4.0, min(body_pt, fitted)), cols

    def draw_mono(text, label=None):
        """Draw a monospace block, rotating to landscape if it must."""
        size, cols = mono_block(text, portrait_col)
        if size < _PDF_MONO_FLOOR_PT:
            land_size, _ = mono_block(text, landscape_col)
            if land_size > size:
                pdf.add_page(orientation="L")
                if label:
                    pdf.set_font(SANS, "B", max(7, 7.5 * scale))
                    pdf.set_text_color(107, 114, 128)
                    pdf.multi_cell(0, line_h(7.5 * scale), txt(label.upper()),
                                   new_x=NX, new_y=NY)
                    pdf.set_text_color(17, 24, 39)
                pdf.set_font(MONO, "", land_size)
                pdf.set_fill_color(245, 246, 250)
                pdf.multi_cell(0, line_h(land_size), txt(text),
                               new_x=NX, new_y=NY, fill=True)
                pdf.add_page()          # back to portrait for the prose
                return
        if label:
            pdf.set_font(SANS, "B", max(7, 7.5 * scale))
            pdf.set_text_color(107, 114, 128)
            pdf.multi_cell(0, line_h(7.5 * scale), txt(label.upper()),
                           new_x=NX, new_y=NY)
            pdf.set_text_color(17, 24, 39)
        pdf.set_font(MONO, "", size)
        pdf.set_fill_color(245, 246, 250)
        pdf.multi_cell(0, line_h(size), txt(text), new_x=NX, new_y=NY, fill=True)

    cell(min(_PDF_MAX_PT, body_pt * 1.35), heading, style="B")
    pdf.set_text_color(120, 120, 120)
    cell(body_pt * 0.62, subtitle)
    pdf.set_text_color(20, 20, 20)
    pdf.ln(2)

    for sec in sections:
        pdf.set_text_color(67, 56, 202)
        cell(max(7, body_pt * 0.46), (sec.get("cat") or "").upper(), style="B")
        pdf.set_text_color(17, 24, 39)
        cell(body_pt * 1.05, sec["title"], style="B")
        pdf.ln(0.5)
        for label, text in sec.get("fields", []):
            if not text:
                continue
            pdf.set_text_color(107, 114, 128)
            cell(max(7, body_pt * 0.46), label.upper(), style="B")
            pdf.set_text_color(17, 24, 39)
            # A field is not uniformly prose: the worked examples carry drawn
            # tables and hand-traces inline. Prose wraps at the body size,
            # fixed-width runs are scaled to fit whole.
            for is_fixed, chunk in _pdf_runs(text):
                if is_fixed:
                    draw_mono(chunk)
                else:
                    cell(body_pt, chunk)
            pdf.ln(0.4)
        if sec.get("arch"):
            draw_mono(sec["arch"])
        for label, text in sec.get("mono_blocks", []):
            if not text:
                continue
            draw_mono(text, label)
        if sec.get("tags"):
            pdf.set_text_color(67, 56, 202)
            # No italic face is registered for the Unicode font, and asking
            # fpdf2 for a style it has no file for raises.
            cell(body_pt * 0.62, "  ".join("#" + t for t in sec["tags"]))
            pdf.set_text_color(17, 24, 39)
        pdf.ln(3.5)

    return bytes(pdf.output())


def _bank_select(items, text_fields, categories, title_key):
    """Apply ?cat/?tag/?q/?id filters (from request.args) and return
    (selected_items, human_label)."""
    cat = (request.args.get("cat") or "").strip()
    tag = (request.args.get("tag") or "").strip().lower()
    q = (request.args.get("q") or "").strip().lower()
    one = (request.args.get("id") or "").strip()

    def _match(it):
        if one:
            return it["id"] == one
        if cat and it.get("cat") != cat:
            return False
        if tag and tag not in [t.lower() for t in (it.get("tags") or [])]:
            return False
        if q:
            hay = " ".join(str(it.get(f) or "") for f in text_fields).lower()
            hay += " " + " ".join(it.get("tags") or [])
            if q not in hay:
                return False
        return True

    selected = [it for it in items if _match(it)]
    label = None
    if one and selected:
        label = str(selected[0].get(title_key, ""))[:80]
    elif cat:
        label = categories.get(cat, cat)
    elif tag:
        label = f"Tag: #{tag}"
    elif q:
        label = f"Search: {q}"
    return selected, label


def _pdf_response(pdf, filename):
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{filename}"',
    })


def _sd_merged_items(user_id):
    """The full system-design bank with the user's edits merged over the
    static originals. Shared by the JSON API and the printable view."""
    items = [{"id": f"sd{i}", **e, "edited": False} for i, e in enumerate(SD_ENTRIES)]
    try:
        overrides = get("system_design_overrides", {
            "user_id": f"eq.{user_id}", "deleted_at": "is.null",
            "select": "entry_id,title,problem,answer,example,use_cases,arch,disadvantages,competing",
            "limit": "1000",
        }) or []
    except Exception:
        overrides = []
    ovmap = {o.get("entry_id"): o for o in overrides}
    for it in items:
        o = ovmap.get(it["id"])
        if not o:
            continue
        if (o.get("title") or "").strip():
            it["title"] = o["title"]
        for f in _SD_FIELDS:
            if f == "title":
                continue
            if o.get(f) is not None:
                it[f] = o[f]
        it["edited"] = True
    return items


@interview_prep_bp.route("/api/interview-prep/system-design", methods=["GET"])
@login_required
def system_design_bank():
    """The system-design knowledge bank: building blocks, data stores,
    data platforms, analytics, data modeling, classic (Alex Xu) designs,
    AI solutions, information security and e-commerce scenarios — each
    with problem/answer/example/architecture/disadvantages/competing tech
    and tags. User edits (system_design_overrides) merged in."""
    user_id = session["user_id"]
    return jsonify({
        "categories": [{"key": k, "label": v} for k, v in SD_CATEGORIES.items()],
        "entries": _sd_merged_items(user_id),
        "total": len(SD_ENTRIES),
    })


@interview_prep_bp.route("/interview-prep/system-design/print", methods=["GET"])
@login_required
def system_design_print():
    """A clean, print-optimised page for the bank — one entry per section
    with every field. The browser's 'Save as PDF' turns it into a PDF
    (no server-side PDF library, no blobs in the DB). Filters:
    ?cat=<key>  ?tag=<tag>  ?q=<text>  ?id=sdN  (any combination)."""
    user_id = session["user_id"]
    items = _sd_merged_items(user_id)

    cat = (request.args.get("cat") or "").strip()
    tag = (request.args.get("tag") or "").strip().lower()
    q = (request.args.get("q") or "").strip().lower()
    one = (request.args.get("id") or "").strip()

    def _match(it):
        if one:
            return it["id"] == one
        if cat and it.get("cat") != cat:
            return False
        if tag and tag not in [t.lower() for t in (it.get("tags") or [])]:
            return False
        if q:
            hay = " ".join(str(it.get(f) or "") for f in
                           ("title", "answer", "problem", "competing")).lower()
            hay += " " + " ".join(it.get("tags") or [])
            if q not in hay:
                return False
        return True

    selected = [it for it in items if _match(it)]

    # Human title for the header / filename hint.
    label = "System Design Bank"
    if one and selected:
        label = selected[0]["title"]
    elif cat:
        label = SD_CATEGORIES.get(cat, cat)
    elif tag:
        label = f"Tag: #{tag}"
    elif q:
        label = f"Search: {q}"

    return render_template(
        "system_design_print.html",
        entries=selected,
        category_labels=SD_CATEGORIES,
        detail_order=SD_DETAIL_ORDER,
        heading=label,
        count=len(selected),
        today=_today().isoformat(),
    )


@interview_prep_bp.route("/interview-prep/system-design/pdf", methods=["GET"])
@login_required
def system_design_pdf():
    """Server-generated PDF of the system-design bank (same ?cat/?tag/?q/?id
    filters, user edits merged). Falls back to the print view if fpdf2 is
    unavailable."""
    user_id = session["user_id"]
    selected, label = _bank_select(
        _sd_merged_items(user_id),
        ("title", "answer", "problem", "competing"), SD_CATEGORIES, "title")
    heading = label or "System Design Bank"
    subtitle = (f"{len(selected)} entr{'y' if len(selected) == 1 else 'ies'} "
                f"| DailyPlanner Interview Prep | {_today().isoformat()}")
    sections = []
    for it in selected:
        fields = [("Problem it solves", it.get("problem")),
                  ("Approach", it.get("answer")),
                  ("Example", it.get("example")),
                  ("Use cases", it.get("use_cases")),
                  ("Disadvantages", it.get("disadvantages")),
                  ("Competing technologies", it.get("competing"))]
        mono_blocks = []
        detail = it.get("detail")
        if detail:
            for key, label, is_mono in SD_DETAIL_ORDER:
                val = detail.get(key)
                if not val:
                    continue
                if is_mono:
                    mono_blocks.append((label, val))
                else:
                    fields.append((label, val))
        sections.append({
            "title": it["title"],
            "cat": SD_CATEGORIES.get(it.get("cat"), it.get("cat", "")),
            "fields": fields, "arch": it.get("arch"),
            "mono_blocks": mono_blocks, "tags": it.get("tags"),
        })
    try:
        pdf = _pdf_bytes(heading, subtitle, sections, body_pt=_pdf_body_pt())
    except ImportError:
        return redirect(url_for("interview_prep.system_design_print", **request.args.to_dict()))
    fname = (selected[0]["id"] + ".pdf") if len(selected) == 1 else "system-design-bank.pdf"
    return _pdf_response(pdf, fname)


# ─────────── integration: pull related material from the user's library ──

_KW_STOP = {"design", "system", "service", "distributed", "scale", "real",
            "time", "with", "and", "the", "for", "your", "using", "based"}


def _entry_keywords(title, tags):
    kws = {t.lower() for t in (tags or []) if isinstance(t, str)}
    for w in re.split(r"[^a-z0-9+]+", (title or "").lower()):
        if len(w) > 3 and w not in _KW_STOP:
            kws.add(w)
    return kws


@interview_prep_bp.route("/api/interview-prep/system-design/<eid>/related", methods=["GET"])
@login_required
def system_design_related(eid):
    """Pull items from the user's own References and Travel Reads that
    relate to this design (by tag overlap / keyword), so the bank is
    seamlessly connected to their saved knowledge."""
    user_id = session["user_id"]
    if not _valid_sid(eid):
        return jsonify({"references": [], "travel_reads": []})
    entry = SD_ENTRIES[int(eid[2:])]
    kws = _entry_keywords(entry["title"], entry.get("tags"))
    long_kws = {k for k in kws if len(k) > 4}

    references = []
    try:
        rows = get("reference_links", {
            "user_id": f"eq.{user_id}",
            "select": "id,title,description,url,tags,category", "limit": "1000",
        }) or []
        scored = []
        for r in rows:
            rtags = {t.lower() for t in (r.get("tags") or []) if isinstance(t, str)}
            text = f"{r.get('title') or ''} {r.get('description') or ''}".lower()
            score = 2 * len(rtags & kws) + sum(1 for k in long_kws if k in text)
            if score:
                scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        references = [{"title": r.get("title") or r.get("url"), "url": r.get("url"),
                       "category": r.get("category"), "tags": r.get("tags") or []}
                      for _, r in scored[:6]]
    except Exception as e:
        logger.warning("related references lookup failed: %s", e)

    travel_reads = []
    try:
        rows = get("travel_reads", {
            "user_id": f"eq.{user_id}", "archived_at": "is.null",
            "select": "id,title,description,url,source,kind,status", "limit": "500",
        }) or []
        scored = []
        for t in rows:
            text = f"{t.get('title') or ''} {t.get('description') or ''} {t.get('source') or ''}".lower()
            score = sum(1 for k in long_kws if k in text)
            if score:
                scored.append((score, t))
        scored.sort(key=lambda x: -x[0])
        travel_reads = [{"title": t.get("title") or t.get("url"), "url": t.get("url"),
                         "source": t.get("source"), "kind": t.get("kind")}
                        for _, t in scored[:5]]
    except Exception as e:
        logger.warning("related travel_reads lookup failed: %s", e)

    # Knowledge Base: match PDF filenames in the user's Drive KB folder.
    # Best-effort — only if Drive is connected and the folder already
    # exists (we never create it here).
    knowledge_base = []
    try:
        from routes.knowledgebase import (_load_token_row, _row_has_drive_scope,
                                          _credentials_from_row, _refresh_if_needed,
                                          _build_drive)
        row = _load_token_row(user_id)
        folder = (row or {}).get("kb_folder_id")
        if row and folder and _row_has_drive_scope(row):
            service = _build_drive(_refresh_if_needed(_credentials_from_row(row), user_id))
            listed = service.files().list(
                q=f"'{folder}' in parents and mimeType='application/pdf' and trashed=false",
                fields="files(id,name,webViewLink)", pageSize=200,
            ).execute().get("files", [])
            scored = []
            for f in listed:
                name = (f.get("name") or "").lower()
                score = sum(1 for k in long_kws if k in name)
                if score:
                    scored.append((score, f))
            scored.sort(key=lambda x: -x[0])
            knowledge_base = [{"title": f.get("name"), "url": f.get("webViewLink")}
                              for _, f in scored[:5]]
    except Exception as e:
        logger.warning("related KB lookup failed: %s", e)

    return jsonify({"references": references, "travel_reads": travel_reads,
                    "knowledge_base": knowledge_base})


@interview_prep_bp.route("/api/interview-prep/system-design/<eid>/save-reference", methods=["POST"])
@login_required
def system_design_save_reference(eid):
    """Push a design into the user's References library (two-way link) so
    it's searchable alongside their saved articles."""
    user_id = session["user_id"]
    if not _valid_sid(eid):
        return jsonify({"error": "Unknown entry"}), 404
    items = _sd_merged_items(user_id)
    entry = next((it for it in items if it["id"] == eid), None)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    desc = (entry.get("problem") or "")
    if entry.get("answer"):
        desc = (desc + " — " + entry["answer"])[:600]
    payload = {
        "user_id": user_id,
        "title": entry["title"],
        "description": desc or None,
        "url": url_for("interview_prep.system_design_pdf", id=eid, _external=False),
        "tags": entry.get("tags") or [],
        "category": "System Design",
    }
    try:
        post("reference_links", payload)
    except Exception as e:
        logger.exception("save design to references failed: %s", e)
        return jsonify({"error": "Couldn't save to References"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/system-design/<eid>", methods=["POST"])
@login_required
def save_system_design_override(eid):
    user_id = session["user_id"]
    if not _valid_sid(eid):
        return jsonify({"error": "Unknown entry"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:_MAX_TITLE]
    if not title:
        return jsonify({"error": "The title can't be empty"}), 400
    payload = {"user_id": user_id, "entry_id": eid, "title": title,
               "deleted_at": None, "updated_at": _now_iso()}
    for f in _SD_FIELDS:
        if f == "title":
            continue
        payload[f] = (data.get(f) or "").strip()[:_MAX_TEXT] or None
    try:
        post("system_design_overrides?on_conflict=user_id,entry_id",
             payload, prefer="resolution=merge-duplicates")
    except Exception as e:
        logger.exception("save system design override failed: %s", e)
        return jsonify({"error": "Couldn't save — run MIGRATION_SYSTEM_DESIGN_OVERRIDES.sql?"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/system-design/<eid>/reset", methods=["POST"])
@login_required
def reset_system_design_override(eid):
    user_id = session["user_id"]
    if not _valid_sid(eid):
        return jsonify({"error": "Unknown entry"}), 404
    try:
        update("system_design_overrides",
               params={"user_id": f"eq.{user_id}", "entry_id": f"eq.{eid}"},
               json={"deleted_at": _now_iso()})
    except Exception as e:
        logger.exception("reset system design override failed: %s", e)
        return jsonify({"error": "Couldn't reset"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/plan", methods=["POST"])
@login_required
def update_plan():
    user_id = session["user_id"]
    _ensure_plan(user_id)
    data = request.get_json(silent=True) or {}
    patch = {}
    if "role_title" in data:
        patch["role_title"] = (data.get("role_title") or "").strip()[:_MAX_TITLE] or DEFAULT_ROLE
    if "target_date" in data:
        patch["target_date"] = (data.get("target_date") or "").strip() or None
    if "daily_goal_minutes" in data:
        try:
            g = int(data.get("daily_goal_minutes"))
            patch["daily_goal_minutes"] = max(0, min(_MAX_MINUTES, g))
        except (TypeError, ValueError):
            return jsonify({"error": "Enter a valid number of minutes"}), 400
    if not patch:
        return jsonify({"ok": True, "noop": True})
    patch["updated_at"] = _now_iso()
    try:
        update("interview_prep", params={"user_id": f"eq.{user_id}"}, json=patch)
    except Exception as e:
        logger.exception("interview_prep plan update failed: %s", e)
        return jsonify({"error": "Couldn't save"}), 502
    return jsonify({"ok": True})


# ─────────── topics ──────────────────────────────────────────

@interview_prep_bp.route("/api/interview-prep/topics", methods=["POST"])
@login_required
def add_topic():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:_MAX_TITLE]
    if not title:
        return jsonify({"error": "Give the topic a title"}), 400
    cat = (data.get("category") or "domain").strip().lower()
    if cat not in CATEGORIES:
        cat = "domain"
    try:
        rows = post("interview_topics", {
            "user_id": user_id, "category": cat, "title": title,
            "position": int(data.get("position") or 999),
        })
    except Exception as e:
        logger.exception("interview_prep add topic failed: %s", e)
        return jsonify({"error": "Couldn't add"}), 502
    return jsonify({"item": rows[0] if rows else None})


@interview_prep_bp.route("/api/interview-prep/topics/<item_id>", methods=["POST"])
@login_required
def update_topic(item_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    patch = {}
    if "confidence" in data:
        try:
            patch["confidence"] = max(0, min(4, int(data.get("confidence"))))
        except (TypeError, ValueError):
            return jsonify({"error": "Bad confidence"}), 400
    if "title" in data:
        v = (data.get("title") or "").strip()[:_MAX_TITLE]
        if not v:
            return jsonify({"error": "Title required"}), 400
        patch["title"] = v
    if "notes" in data:
        patch["notes"] = (data.get("notes") or "").strip()[:_MAX_TEXT] or None
    if "category" in data:
        c = (data.get("category") or "").strip().lower()
        if c in CATEGORIES:
            patch["category"] = c
    if not patch:
        return jsonify({"ok": True, "noop": True})
    patch["updated_at"] = _now_iso()
    try:
        update("interview_topics",
               params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, json=patch)
    except Exception as e:
        logger.exception("interview_prep update topic failed: %s", e)
        return jsonify({"error": "Couldn't save"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/topics/<item_id>/delete", methods=["POST"])
@login_required
def delete_topic(item_id):
    user_id = session["user_id"]
    try:
        update("interview_topics",
               params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
               json={"deleted_at": _now_iso()})
    except Exception as e:
        logger.exception("interview_prep delete topic failed: %s", e)
        return jsonify({"error": "Couldn't delete"}), 502
    return jsonify({"ok": True})


# ─────────── stories (STAR bank) ─────────────────────────────

@interview_prep_bp.route("/api/interview-prep/stories", methods=["POST"])
@login_required
def add_story():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:_MAX_TITLE] or "New story"
    payload = {
        "user_id": user_id, "title": title,
        "competency": (data.get("competency") or "").strip()[:_MAX_TITLE] or None,
        "position": 999,
    }
    # Optional STAR prefill (used by "Use as my story" from the question bank).
    for f in ("situation", "task", "action", "result"):
        if data.get(f):
            payload[f] = str(data.get(f)).strip()[:_MAX_TEXT] or None
    try:
        rows = post("interview_stories", payload)
    except Exception as e:
        logger.exception("interview_prep add story failed: %s", e)
        return jsonify({"error": "Couldn't add"}), 502
    return jsonify({"item": rows[0] if rows else None})


@interview_prep_bp.route("/api/interview-prep/stories/<item_id>", methods=["POST"])
@login_required
def update_story(item_id):
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    patch = {}
    if "title" in data:
        v = (data.get("title") or "").strip()[:_MAX_TITLE]
        if not v:
            return jsonify({"error": "Title required"}), 400
        patch["title"] = v
    if "competency" in data:
        patch["competency"] = (data.get("competency") or "").strip()[:_MAX_TITLE] or None
    for f in ("situation", "task", "action", "result"):
        if f in data:
            patch[f] = (data.get(f) or "").strip()[:_MAX_TEXT] or None
    if "rehearsed" in data:
        patch["rehearsed"] = bool(data.get("rehearsed"))
    if not patch:
        return jsonify({"ok": True, "noop": True})
    patch["updated_at"] = _now_iso()
    try:
        update("interview_stories",
               params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"}, json=patch)
    except Exception as e:
        logger.exception("interview_prep update story failed: %s", e)
        return jsonify({"error": "Couldn't save"}), 502
    return jsonify({"ok": True})


@interview_prep_bp.route("/api/interview-prep/stories/<item_id>/delete", methods=["POST"])
@login_required
def delete_story(item_id):
    user_id = session["user_id"]
    try:
        update("interview_stories",
               params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
               json={"deleted_at": _now_iso()})
    except Exception as e:
        logger.exception("interview_prep delete story failed: %s", e)
        return jsonify({"error": "Couldn't delete"}), 502
    return jsonify({"ok": True})


# ─────────── practice sessions ───────────────────────────────

@interview_prep_bp.route("/api/interview-prep/sessions", methods=["POST"])
@login_required
def add_session():
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        minutes = int(data.get("minutes"))
    except (TypeError, ValueError):
        return jsonify({"error": "Enter minutes practiced"}), 400
    if minutes <= 0 or minutes > _MAX_MINUTES:
        return jsonify({"error": "Minutes must be between 1 and 1440"}), 400
    payload = {
        "user_id": user_id,
        "practiced_on": (data.get("practiced_on") or "").strip() or _today().isoformat(),
        "minutes": minutes,
        "focus": (data.get("focus") or "").strip()[:_MAX_TITLE] or None,
        "reflection": (data.get("reflection") or "").strip()[:_MAX_TEXT] or None,
    }
    try:
        rows = post("interview_sessions", payload)
    except Exception as e:
        logger.exception("interview_prep add session failed: %s", e)
        return jsonify({"error": "Couldn't log — please try again"}), 502
    return jsonify({"item": rows[0] if rows else payload})


@interview_prep_bp.route("/api/interview-prep/sessions/<item_id>/delete", methods=["POST"])
@login_required
def delete_session(item_id):
    user_id = session["user_id"]
    try:
        update("interview_sessions",
               params={"id": f"eq.{item_id}", "user_id": f"eq.{user_id}"},
               json={"deleted_at": _now_iso()})
    except Exception as e:
        logger.exception("interview_prep delete session failed: %s", e)
        return jsonify({"error": "Couldn't delete"}), 502
    return jsonify({"ok": True})
