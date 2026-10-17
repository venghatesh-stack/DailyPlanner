"""System design deep dives: BRD, PRD, HLD, LLD, edge cases, tech stack,
distributed-systems concepts with Q&A, and a choose-the-best-answer quiz,
one JSON file per design in sd_deep/. Format: sd_deep/SCHEMA.md.

The prompts are the Beyz system design question bank (55 prompts in nine
groups, answered with its Clarify -> Design -> Defend framework) plus
classic designs from the wider web, with Uber as the flagship.

    python3 sd_deep_bank.py --check sd_deep/uber.json   # validate files
    python3 sd_deep_bank.py --check                     # validate them all
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "sd_deep")
#: One 5-page summary per design: sd_deep/summaries/<slug>.md
SUMMARY_DIR = os.path.join(DIR, "summaries")


def summary_path(slug):
    return os.path.join(SUMMARY_DIR, slug + ".md")


def summary_text(slug):
    """The design's 5-page summary (Markdown), or None if it has none yet."""
    try:
        with open(summary_path(slug), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None

GROUPS = {
    "classic": "Core classic products",
    "feeds": "Feeds, ranking & recommendations",
    "search": "Search, indexing & discovery",
    "storage": "Storage, consistency & data modelling",
    "caching": "Caching, performance & latency",
    "messaging": "Messaging, streaming & async workflows",
    "reliability": "Reliability, operations & incidents",
    "security": "Security, abuse & trust",
    "realtime": "Real-time & collaboration",
    "web": "More classic designs",
}

FLAGSHIP = {"uber"}

# (path, standard minimum, flagship minimum)
_MINS = [
    ("framework.clarify", 6, 8), ("framework.design", 5, 8), ("framework.defend", 5, 8),
    ("brd.goals", 4, 6), ("brd.non_goals", 3, 4), ("brd.stakeholders", 3, 4),
    ("brd.success_metrics", 4, 6), ("brd.constraints", 3, 4), ("brd.risks", 3, 5),
    ("prd.personas", 2, 3), ("prd.user_stories", 6, 12), ("prd.functional", 6, 12),
    ("prd.non_functional", 5, 8), ("prd.capacity.assumptions", 3, 6), ("prd.capacity.math", 3, 8),
    ("prd.out_of_scope", 3, 4),
    ("hld.components", 6, 12), ("hld.flows", 2, 4),
    ("lld.apis", 4, 10), ("lld.data_model", 3, 7), ("lld.classes", 3, 8), ("lld.algorithms", 2, 5),
    ("edge_cases", 10, 25), ("tech_stack", 6, 12), ("concepts", 6, 14),
    ("tradeoffs", 5, 10), ("failure_modes", 5, 10), ("metrics", 5, 10),
    ("follow_ups", 6, 15), ("key_points", 6, 10), ("quiz", 20, 60), ("references", 2, 6),
]

_TEXT = ["title", "prompt", "summary", "framework.script", "brd.problem",
         "prd.capacity.summary", "hld.overview", "hld.diagram", "hld.data_flow", "lld.sequence"]

_ITEM_KEYS = {
    "brd.stakeholders": ("who", "needs"),
    "brd.success_metrics": ("metric", "target"),
    "brd.risks": ("risk", "mitigation"),
    "prd.personas": ("name", "needs"),
    "prd.non_functional": ("name", "target"),
    "hld.components": ("name", "responsibility"),
    "hld.flows": ("name", "steps"),
    "lld.apis": ("method", "path", "request", "response"),
    "lld.data_model": ("entity", "store", "fields", "keys"),
    "lld.classes": ("name", "responsibility", "methods"),
    "lld.algorithms": ("name", "explain", "pseudocode"),
    "edge_cases": ("case", "handling"),
    "tech_stack": ("name", "layer", "overview", "why", "alternatives"),
    "concepts": ("name", "explain", "in_this_design", "key_points", "qa"),
    "tradeoffs": ("decision", "options", "choice", "why"),
    "failure_modes": ("failure", "behavior"),
    "follow_ups": ("q", "a"),
    "quiz": ("q", "options", "answer", "why"),
    "references": ("title", "url"),
}


def _get(obj, path):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def validate(d, slug=None):
    """Every problem with one design, as a list of strings (empty = valid)."""
    errs = []
    slug = slug or d.get("slug")
    flagship = slug in FLAGSHIP
    if d.get("slug") != slug:
        errs.append(f"slug {d.get('slug')!r} does not match file name {slug!r}")
    if d.get("group") not in GROUPS:
        errs.append(f"group must be one of {sorted(GROUPS)}")
    if d.get("source") not in ("beyz", "web"):
        errs.append("source must be 'beyz' or 'web'")
    if d.get("difficulty") not in ("Medium", "Hard"):
        errs.append("difficulty must be Medium or Hard")
    if not isinstance(d.get("minutes"), int) or not 30 <= d["minutes"] <= 300:
        errs.append("minutes must be an int 30-300")
    for p in _TEXT:
        v = _get(d, p)
        if not isinstance(v, str) or len(v.strip()) < 20:
            errs.append(f"{p} missing or too short")
    for p, std, flag in _MINS:
        v = _get(d, p)
        need = flag if flagship else std
        if not isinstance(v, list) or len(v) < need:
            errs.append(f"{p}: need >= {need}, have {len(v) if isinstance(v, list) else 0}")
    for p, keys in _ITEM_KEYS.items():
        for i, it in enumerate(_get(d, p) or []):
            if not isinstance(it, dict):
                errs.append(f"{p}[{i}] is not an object")
                continue
            for k in keys:
                if it.get(k) in (None, "", []):
                    errs.append(f"{p}[{i}].{k} missing")
    for i, c in enumerate(d.get("concepts") or []):
        if len((c.get("explain") or "").split()) < 120:
            errs.append(f"concepts[{i}] ({c.get('name')}): explain under 120 words")
        if len(c.get("qa") or []) < 3:
            errs.append(f"concepts[{i}] ({c.get('name')}): need >= 3 qa")
        for j, qa in enumerate(c.get("qa") or []):
            if not (qa.get("q") and qa.get("a")):
                errs.append(f"concepts[{i}].qa[{j}] missing q or a")
    answers = []
    for i, q in enumerate(d.get("quiz") or []):
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4 or not all(isinstance(o, str) and o for o in opts):
            errs.append(f"quiz[{i}] needs exactly 4 non-empty options")
        if q.get("answer") not in (0, 1, 2, 3):
            errs.append(f"quiz[{i}].answer must be 0-3")
        else:
            answers.append(q["answer"])
    if len(answers) >= 8 and max(answers.count(k) for k in range(4)) > 0.5 * len(answers):
        errs.append("quiz answers are not spread across positions")
    for r in d.get("references") or []:
        if not str(r.get("url", "")).startswith("http"):
            errs.append(f"reference {r.get('title')!r} has no http url")
    for p in ("hld.diagram", "lld.sequence"):
        v = _get(d, p) or ""
        if any(len(line) > 100 for line in v.split("\n")):
            errs.append(f"{p} has a line over 100 columns")
    return errs


def _load_all():
    out = []
    for path in sorted(glob.glob(os.path.join(DIR, "*.json"))):
        slug = os.path.basename(path)[:-5]
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        if validate(d, slug):
            continue        # never serve a half-written design
        out.append(d)
    order = list(GROUPS)
    out.sort(key=lambda d: (d["slug"] not in FLAGSHIP, order.index(d["group"]), d["title"]))
    return out


DESIGNS = _load_all()
BY_SLUG = {d["slug"]: d for d in DESIGNS}
BY_TITLE = {d["title"]: d for d in DESIGNS}


def summary_list():
    """The thin list the page draws before a design is opened."""
    return [{
        "slug": d["slug"], "title": d["title"], "prompt": d["prompt"],
        "group": d["group"], "source": d["source"], "difficulty": d["difficulty"],
        "minutes": d["minutes"], "summary": d["summary"],
        "counts": {"concepts": len(d["concepts"]), "quiz": len(d["quiz"]),
                   "edge_cases": len(d["edge_cases"])},
        "concepts": [c["name"] for c in d["concepts"]],
        "has_summary": os.path.exists(summary_path(d["slug"])),
    } for d in DESIGNS]


def main(argv):
    if not argv or argv[0] != "--check":
        print(__doc__)
        return 2
    paths = argv[1:] or sorted(glob.glob(os.path.join(DIR, "*.json")))
    bad = 0
    for path in paths:
        slug = os.path.basename(path)[:-5]
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as exc:
            print(f"{slug}: cannot parse JSON - {exc}")
            bad += 1
            continue
        errs = validate(d, slug)
        words = len(json.dumps(d, ensure_ascii=False).split())
        if errs:
            bad += 1
            print(f"{slug}: {len(errs)} problem(s)")
            for e in errs:
                print("   -", e)
        else:
            print(f"{slug}: OK  ({words} words, {len(d['concepts'])} concepts, "
                  f"{len(d['quiz'])} quiz, {len(d['edge_cases'])} edge cases)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
