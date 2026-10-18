"""The Interview Prep hub: case rounds merged in, server-side progress,
readiness that counts the case rounds, the case-round PDF, and the bank's
ranking."""
import pytest


@pytest.fixture
def db(monkeypatch):
    """A tiny in-memory prep_progress table behind get/post."""
    import routes.interview_prep as ip
    rows = {}
    posts = []

    def fake_get(table, params=None, **kw):
        params = params or {}
        if table != "prep_progress":
            return []
        out = []
        for (u, b, t), r in rows.items():
            if params.get("user_id") not in (None, f"eq.{u}"):
                continue
            if "bank" in params and params["bank"].split(".", 1)[1].strip('"') != b:
                continue
            if "entry_title" in params and params["entry_title"].split(".", 1)[1].strip('"') != t:
                continue
            if params.get("done") == "eq.true" and not r.get("done"):
                continue
            out.append(dict(r))
        return out

    def fake_post(path, payload, **kw):
        posts.append((path, payload))
        table = path.split("?")[0]
        if table != "prep_progress":
            return []
        assert "on_conflict=user_id,bank,entry_title" in path, "second save would 409"
        for row in payload if isinstance(payload, list) else [payload]:
            key = (row["user_id"], row["bank"], row["entry_title"])
            rows[key] = {**rows.get(key, {}), **row}
        return []

    monkeypatch.setattr(ip, "get", fake_get)
    monkeypatch.setattr(ip, "post", fake_post)
    return {"rows": rows, "posts": posts}


def test_old_tpm_page_redirects_into_the_hub_keeping_the_topic(auth_client):
    r = auth_client.get("/tpm-rounds?topic=Should%20we%20kill%20this%20program%3F")
    assert r.status_code == 301
    assert r.headers["Location"].startswith("/interview-prep/cases?topic=Should")


@pytest.mark.parametrize("path,tab", [
    ("/interview-prep", "overview"), ("/interview-prep/cases", "cases"),
    ("/interview-prep/behavioral", "behavioral"), ("/interview-prep/design", "design"),
])
def test_each_tab_has_its_own_path(auth_client, path, tab):
    r = auth_client.get(path)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert f'data-initial-tab="{tab}"' in html
    assert "prep_cases.js" in html and "prep_hub.js" in html


def test_nav_has_one_interview_prep_item():
    nav = open("templates/_top_nav.html", encoding="utf-8").read()
    assert 'href="/tpm-rounds"' not in nav
    assert nav.count('href="/interview-prep"') == 1
    assert "tpm-rounds)" in nav, "the old path should still light the item"


def test_progress_is_keyed_by_title_and_mapped_back_to_ids(auth_client, db):
    import routes.interview_prep as ip
    r = auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t4", "done": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    (key, row), = db["rows"].items()
    assert key[2] == ip.TPM_ROUND_ENTRIES[4]["title"]
    assert "t4" not in str(row), "a positional id leaked into the row"
    got = auth_client.get("/api/prep/progress?bank=tpm").get_json()
    assert got["available"] and got["done"] == ["t4"]


def test_bulk_import_of_old_local_ticks(auth_client, db):
    r = auth_client.post("/api/prep/progress",
                         json={"bank": "behavioral", "ids": ["q0", "q1", "nope"]})
    assert r.get_json()["imported"] == 2
    got = auth_client.get("/api/prep/progress?bank=behavioral").get_json()
    assert sorted(got["done"]) == ["q0", "q1"]


def test_unknown_bank_or_entry_is_refused(auth_client, db):
    assert auth_client.post("/api/prep/progress", json={"bank": "x", "id": "t1", "done": True}).status_code == 400
    assert auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t9999", "done": True}).status_code == 400


def test_mock_score_counts_attempts_and_rehearses_on_three(auth_client, db):
    r = auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t2", "mock_score": 2}).get_json()
    assert r["attempts"] == 1 and r["best"] == 2 and not r["done"]
    r = auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t2", "mock_score": 3}).get_json()
    assert r["attempts"] == 2 and r["best"] == 3 and r["done"]
    r = auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t2", "mock_score": 1}).get_json()
    assert r["best"] == 3 and r["done"], "a weak run must not untick a rehearsed case"
    assert auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t2", "mock_score": 7}).status_code == 400
    got = auth_client.get("/api/prep/progress?bank=tpm").get_json()
    assert got["mock"]["t2"]["attempts"] == 3


def test_progress_degrades_when_the_table_is_missing(auth_client, monkeypatch):
    import routes.interview_prep as ip

    def boom(*a, **k):
        raise Exception('relation "prep_progress" does not exist')
    monkeypatch.setattr(ip, "get", boom)
    monkeypatch.setattr(ip, "post", boom)
    got = auth_client.get("/api/prep/progress?bank=tpm").get_json()
    assert got["available"] is False and got["migration"] == "MIGRATION_PREP_PROGRESS.sql"
    r = auth_client.post("/api/prep/progress", json={"bank": "tpm", "id": "t1", "done": True})
    assert r.status_code == 503


def test_case_pdf_filters_and_renders(auth_client):
    r = auth_client.get("/interview-prep/cases/pdf?round=engineering")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert r.data[:4] == b"%PDF"
    assert auth_client.get("/interview-prep/cases/pdf?id=t9999").status_code == 404


def test_tpm_bank_can_be_scheduled_and_noted():
    import routes.interview_prep as ip
    assert "tpm" in ip.PREP_BANKS and "tpm" in ip._BANK_SOURCES
    title = ip.TPM_ROUND_ENTRIES[0]["title"]
    assert ip._prep_lookup("tpm", "t0", title)[0] == title
    # The page path is used as a plain prefix by the Day Board, so no query.
    assert "?" not in ip.PREP_BANKS["tpm"]["page"]


def test_ticking_a_case_elsewhere_updates_its_progress(monkeypatch):
    import routes.interview_prep as ip
    posted = []
    monkeypatch.setattr(ip, "_find_prep_project", lambda u, b: None)
    monkeypatch.setattr(ip, "get", lambda *a, **k: [])
    monkeypatch.setattr(ip, "update", lambda *a, **k: None)
    monkeypatch.setattr(ip, "post", lambda t, p, **k: posted.append((t, p)) or [{}])
    title = ip.TPM_ROUND_ENTRIES[3]["title"]
    ip.complete_prep_artifacts("u1", "tpm", title, True)
    prog = [p for t, p in posted if t.startswith("prep_progress")]
    assert prog and prog[0]["done"] is True and prog[0]["entry_title"] == title


def test_readiness_counts_the_case_rounds(auth_client, monkeypatch):
    import routes.interview_prep as ip
    p0 = [e["title"] for e in ip.TPM_ROUND_ENTRIES if e["priority"] == "P0"]

    def fake_get(table, params=None, **kw):
        if table == "interview_prep":
            return [{"id": "p", "role_title": "x", "daily_goal_minutes": 45,
                     "target_date": None, "created_at": None}]
        if table == "prep_progress":
            return [{"bank": "tpm", "entry_title": t, "done": True} for t in p0]
        return []
    monkeypatch.setattr(ip, "get", fake_get)
    s = auth_client.get("/api/interview-prep").get_json()["stats"]
    assert s["case_score"] > 0
    assert s["readiness"] == round(0.20 * s["case_score"]), "only the case rounds are done"
    # Next up skips what is already rehearsed.
    assert all(c["title"] not in p0 for c in s["next_cases"])


def test_bank_ranking_and_priorities():
    import tpm_round_bank as t
    by = {e["title"]: e for e in t.ENTRIES}
    assert len(t.ENTRIES) == 34 and len(by) == 34
    # Every must-rehearse case is P0; P0s outrank everything else.
    for title in t._MUST_REHEARSE:
        assert by[title]["priority"] == "P0", title
    ranked = sorted(t.ENTRIES, key=lambda e: e["rank"])
    order = [e["priority"] for e in ranked]
    assert order == sorted(order), "a lower priority ranked above a higher one"
    # "Asked in most TPM loops" used to rank dead last.
    pm = by["How do you work with a PM when you disagree about priority or scope?"]
    assert pm["priority"] != "P2"
    assert "engineering" in t.ROUNDS and "engineering" in t.ROUND_BRIEF
    # New cases are appended, never inserted: older saved ids stay valid.
    assert t.ENTRIES[21]["round"] == "close"


def test_ai_sde_progress_upsert_names_its_conflict_target(auth_client, monkeypatch):
    import routes.interview_prep as ip
    saved = []
    monkeypatch.setattr(ip, "post", lambda path, payload, **kw: saved.append(path))
    ip_title = ip.AI_SDE_ENTRIES[0]["title"]
    auth_client.post("/api/ai-sde/progress", json={"title": ip_title, "studied": True})
    assert saved and saved[-1] == "ai_sde_progress?on_conflict=user_id,entry_title"


# ── System design deep dives ───────────────────────────────────────────

def test_every_deep_dive_file_is_complete():
    """A half-written file is skipped at load; this makes sure none is."""
    import glob, json, os
    import sd_deep_bank as b
    files = sorted(glob.glob("sd_deep/*.json"))
    assert len(files) >= 70
    for path in files:
        slug = os.path.basename(path)[:-5]
        errs = b.validate(json.load(open(path, encoding="utf-8")), slug)
        assert not errs, f"{slug}: {errs[:5]}"
    assert len(b.DESIGNS) == len(files)
    # All 55 Beyz prompts are covered, plus the classics, Uber first.
    assert sum(1 for d in b.DESIGNS if d["source"] == "beyz") == 55
    assert b.DESIGNS[0]["slug"] == "uber"
    uber = b.BY_SLUG["uber"]
    assert len(uber["quiz"]) >= 60 and len(uber["concepts"]) >= 14


def test_deep_dive_list_and_detail(auth_client):
    j = auth_client.get("/api/sd-deep").get_json()
    assert j["total"] >= 70 and [s["step"] for s in j["framework"]] == ["Clarify", "Design", "Defend"]
    first = j["designs"][0]
    assert first["slug"] == "uber" and first["id"] == "dd0"
    assert "brd" not in first, "the list should stay thin"
    d = auth_client.get("/api/sd-deep/uber").get_json()
    for k in ("brd", "prd", "hld", "lld", "edge_cases", "tech_stack", "concepts", "quiz"):
        assert d[k]
    assert auth_client.get("/api/sd-deep/nope").status_code == 404


def test_deep_dive_has_its_own_page_and_pdf(auth_client):
    r = auth_client.get("/interview-prep/design/uber")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'data-deep="uber"' in html and "prep_deep.js" in html
    assert auth_client.get("/interview-prep/design/not-a-design").status_code == 302
    pdf = auth_client.get("/interview-prep/design/url-shortener/pdf")
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"


def test_quiz_score_keeps_the_best_and_marks_studied_at_80(auth_client, db):
    r = auth_client.post("/api/prep/progress", json={"bank": "sddeep", "id": "dd0", "quiz_pct": 60}).get_json()
    assert r["best"] == 60 and not r["done"]
    r = auth_client.post("/api/prep/progress", json={"bank": "sddeep", "id": "dd0", "quiz_pct": 85}).get_json()
    assert r["best"] == 85 and r["done"]
    r = auth_client.post("/api/prep/progress", json={"bank": "sddeep", "id": "dd0", "quiz_pct": 40}).get_json()
    assert r["best"] == 85 and r["done"]
    got = auth_client.get("/api/prep/progress?bank=sddeep").get_json()
    assert got["done"] == ["dd0"] and got["quiz"]["dd0"] == 85
    assert auth_client.post("/api/prep/progress", json={"bank": "sddeep", "id": "dd0", "quiz_pct": 101}).status_code == 400


def test_deep_dives_can_be_scheduled():
    import routes.interview_prep as ip
    import sd_deep_bank as b
    assert "?" not in ip.PREP_BANKS["sddeep"]["page"]
    assert ip._prep_lookup("sddeep", "dd0", b.DESIGNS[0]["title"])[0] == b.DESIGNS[0]["title"]


def test_push_prune_removes_only_retired_rows(auth_client, monkeypatch):
    import routes.push as rp
    calls = []
    monkeypatch.setattr(rp, "get", lambda t, p=None, **k: [{"endpoint": "a"}, {"endpoint": "b"}])
    monkeypatch.setattr(rp, "delete", lambda t, p: calls.append((t, p)))
    j = auth_client.post("/api/push/prune").get_json()
    assert j["removed"] == 2
    (table, params), = calls
    assert table == "push_subscriptions"
    assert params == {"user_id": "eq.test-user-id", "is_active": "eq.false"}


# ── Random thoughts ────────────────────────────────────────────────────

@pytest.fixture
def thoughts(monkeypatch):
    import routes.interview_prep as ip
    from services import thoughts_service as ts
    rows, started = [], []

    def fake_get(table, params=None, **kw):
        params = params or {}
        out = [r for r in rows if params.get("user_id") in (None, f"eq.{r['user_id']}")]
        if "question" in params:
            out = [r for r in out if f"eq.{r['question']}" == params["question"]]
        if "id" in params:
            out = [r for r in out if f"eq.{r['id']}" == params["id"]]
        if params.get("deleted_at") == "is.null":
            out = [r for r in out if not r.get("deleted_at")]
        if "shelf" in params:
            out = [r for r in out if f"eq.{r.get('shelf', 'tpm')}" == params["shelf"]]
        if "model" in params:
            out = [r for r in out if f"eq.{r.get('model')}" == params["model"]]
        return [dict(r) for r in out]

    def fake_post(table, payload, **kw):
        row = dict(payload, id=f"t{len(rows) + 1}")
        rows.append(row)
        return [dict(row)]

    def fake_update(table, params=None, json=None, **kw):
        for r in rows:
            if all(f"eq.{r.get(k)}" == v for k, v in params.items()):
                r.update(json)

    from services import thoughts_audio as ta
    for mod in (ip, ts, ta):
        monkeypatch.setattr(mod, "get", fake_get)
        monkeypatch.setattr(mod, "update", fake_update)
    monkeypatch.setattr(ip, "post", fake_post)
    # Audio builds never run in tests: record what would have been queued.
    monkeypatch.setattr(ta, "start", lambda tid, uid, force=False: started.append(("audio", tid)) or {"status": "pending"})
    monkeypatch.setattr("supabase_client.post", fake_post)
    monkeypatch.setattr(ts, "answer_in_background", lambda *a, **k: started.append(a))
    ts._seeded.clear()
    return {"rows": rows, "started": started}


def test_thoughts_tab_has_its_own_path(auth_client):
    html = auth_client.get("/interview-prep/thoughts").get_data(as_text=True)
    assert 'data-initial-tab="thoughts"' in html and "prep_thoughts.js" in html


def test_the_tail_inventory_question_is_added_once(auth_client, thoughts):
    items = auth_client.get("/api/prep/thoughts").get_json()["items"]
    assert any("tail inventory" in t["question"] for t in items)
    seeded = [r for r in thoughts["rows"] if "tail inventory" in r["question"]]
    assert len(seeded) == 1 and seeded[0]["status"] == "ready"
    assert len(seeded[0]["answer"].split()) > 1500
    for h in ("## The short answer", "## The intuition", "## How it actually works",
              "## A worked example", "## Common misconceptions",
              "## How to say it in an interview", "## Key takeaways", "## Check yourself"):
        assert h in seeded[0]["answer"], h
    # Deleting it must not bring it back on the next load or next process.
    seeded[0]["deleted_at"] = "2026-10-11"
    from services import thoughts_service as ts
    ts._seeded.clear()
    auth_client.get("/api/prep/thoughts")
    assert len([r for r in thoughts["rows"] if "tail inventory" in r["question"]]) == 1


def test_asking_saves_pending_and_starts_the_answer(auth_client, thoughts):
    r = auth_client.post("/api/prep/thoughts", json={"question": "Why is Kafka ordered per partition?",
                                                      "tags": ["Kafka", "  "]})
    assert r.status_code == 201, r.get_data(as_text=True)
    item = r.get_json()["item"]
    assert item["status"] == "pending" and item["root_id"] == item["id"]
    assert thoughts["started"] and thoughts["started"][-1][2] == "Why is Kafka ordered per partition?"
    # A follow-up joins the same thread and carries the parent as context.
    r2 = auth_client.post("/api/prep/thoughts", json={"question": "Simpler?", "parent_id": item["id"]})
    child = r2.get_json()["item"]
    assert child["root_id"] == item["id"] and child["parent_id"] == item["id"]
    assert thoughts["started"][-1][4]["id"] == item["id"]
    assert auth_client.post("/api/prep/thoughts", json={"question": "  "}).status_code == 400


def test_thoughts_show_the_shipped_answer_before_the_migration(auth_client, monkeypatch):
    import routes.interview_prep as ip
    from services import thoughts_service as ts

    def boom(*a, **k):
        raise Exception('relation "prep_thoughts" does not exist')
    monkeypatch.setattr(ip, "get", boom)
    monkeypatch.setattr(ts, "get", boom)
    ts._seeded.clear()
    j = auth_client.get("/api/prep/thoughts").get_json()
    assert j["available"] is False and j["migration"] == "MIGRATION_PREP_THOUGHTS.sql"
    assert j["items"] and j["items"][0]["status"] == "ready"


def test_generate_falls_through_providers(monkeypatch):
    from services import thoughts_service as ts
    calls = []
    def a(p): calls.append("a"); return None, None
    def b(p): calls.append("b"); raise RuntimeError("down")
    def c(p): calls.append("c"); return "## The short answer\nYes.", "m3"
    monkeypatch.setattr(ts, "PROVIDERS", (a, b, c))
    assert ts.generate("q") == ("## The short answer\nYes.", "m3") and calls == ["a", "b", "c"]


def test_thought_pdf_text_is_plain():
    from routes.interview_prep import _md_plain
    out = _md_plain("## How it works\n**Bold** and `code`\n- item\n```\nA -> B\n```")
    assert "HOW IT WORKS" in out and "**" not in out and "`" not in out and "* item" in out


def test_every_shipped_thought_follows_the_answer_format():
    from services import thoughts_service as ts
    seeds = ts.seeds()
    assert any("Kafka" in s["question"] for s in seeds)
    for s in seeds:
        for h in ("## The short answer", "## The intuition", "## How it actually works",
                  "## A worked example", "## Common misconceptions",
                  "## How to say it in an interview", "## Key takeaways", "## Check yourself"):
            assert h in s["answer"], (s["question"], h)
        assert s["answer"].count("Answer:") >= 3


def test_asking_with_an_image_stores_it_and_hands_it_to_the_answer(auth_client, thoughts, monkeypatch):
    import io
    from services import thoughts_service as ts
    stored = []
    monkeypatch.setattr(ts, "store_image", lambda u, data, mime: stored.append((u, mime)) or f"thoughts/{u}/k1.png")
    r = auth_client.post("/api/prep/thoughts", data={
        "question": "Explain my whiteboard", "tags": "kafka",
        "images": (io.BytesIO(b"\x89PNG fake"), "wb.png", "image/png")},
        content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    item = r.get_json()["item"]
    assert item["images"][0]["key"] == "thoughts/test-user-id/k1.png" and stored == [("test-user-id", "image/png")]
    assert thoughts["started"][-1][5][0]["key"] == "thoughts/test-user-id/k1.png", "the answer must see the image"
    bad = auth_client.post("/api/prep/thoughts", data={
        "question": "x", "images": (io.BytesIO(b"%PDF"), "a.pdf", "application/pdf")},
        content_type="multipart/form-data")
    assert bad.status_code == 400


def test_images_are_served_only_to_their_owner(auth_client, monkeypatch):
    from services import thoughts_service as ts
    monkeypatch.setattr(ts, "fetch_image", lambda key: (b"img", "image/png"))
    ok = auth_client.get("/interview-prep/thoughts/img/thoughts/test-user-id/abc.png")
    assert ok.status_code == 200 and ok.data == b"img" and "private" in ok.headers["Cache-Control"]
    assert auth_client.get("/interview-prep/thoughts/img/thoughts/someone-else/abc.png").status_code == 404
    # A Photos-page file in the same bucket is not reachable through this route.
    assert auth_client.get("/interview-prep/thoughts/img/test-user-id/photo.png").status_code == 404


def test_pdf_replaces_diagrams_with_a_note():
    from routes.interview_prep import _md_plain
    out = _md_plain("Before\n```mermaid\nflowchart LR\n  A --> B\n```\nAfter")
    assert "flowchart" not in out and "[Diagram" in out and "Before" in out and "After" in out


def test_shipped_answers_have_diagrams_and_refresh_only_when_untouched(thoughts):
    from services import thoughts_service as ts
    seeds = ts.seeds()
    assert all("```mermaid" in s["answer"] for s in seeds)
    rows = thoughts["rows"]
    rows.append({"id": "old", "user_id": "u9", "question": seeds[0]["question"],
                 "answer": "old text", "model": ts.SEED_MODEL})
    rows.append({"id": "mine", "user_id": "u9", "question": seeds[1]["question"],
                 "answer": "my edit", "model": "edited by you"})
    ts._seeded.clear()
    ts.ensure_seeds("u9")
    assert next(r for r in rows if r["id"] == "old")["answer"] == seeds[0]["answer"]
    assert next(r for r in rows if r["id"] == "mine")["answer"] == "my edit"


# ── Random thoughts on AI SDE Prep (a second shelf) ────────────────────

def test_ai_sde_has_its_own_random_thoughts(auth_client, thoughts):
    html = auth_client.get("/ai-sde/thoughts").get_data(as_text=True)
    assert 'data-shelf="aisde"' in html and "prep_thoughts.js" in html
    assert 'href="/ai-sde/thoughts"' in auth_client.get("/ai-sde").get_data(as_text=True)
    items = auth_client.get("/api/prep/thoughts?shelf=aisde").get_json()["items"]
    qs = [t["question"] for t in items]
    # Every shipped answer is on both shelves now, each in its own rows.
    assert any("real-time chat" in q for q in qs) and any("Maggi" in q for q in qs)
    assert any("tail inventory" in q for q in qs)
    assert all(r.get("shelf") == "aisde" for r in thoughts["rows"])
    # The Interview Prep shelf still gets everything, as its own rows.
    tpm = auth_client.get("/api/prep/thoughts").get_json()["items"]
    assert any("tail inventory" in t["question"] for t in tpm)
    assert sum("real-time chat" in r["question"] for r in thoughts["rows"]) == 2


def test_a_question_asked_on_ai_sde_stays_there(auth_client, thoughts):
    r = auth_client.post("/api/prep/thoughts?shelf=aisde", json={"question": "What is a heap?",
                                                               "shelf": "aisde"})
    assert r.status_code == 201
    row = next(x for x in thoughts["rows"] if x["question"] == "What is a heap?")
    assert row["shelf"] == "aisde"
    tpm = auth_client.get("/api/prep/thoughts").get_json()["items"]
    assert not any(t["question"] == "What is a heap?" for t in tpm)


def test_ai_sde_answers_are_written_for_a_new_grad():
    from services import thoughts_service as ts
    s = ts.system_for("aisde")
    assert "new-grad" in s and "Director" not in s and s != ts.system_for("tpm")
    assert ts.system_for("anything-else") == ts.SYSTEM


def test_shipped_answers_carry_topic_step_campus_and_related(auth_client, thoughts):
    from services import thoughts_service as ts
    seeds = ts.seeds()
    steps = [s["step"] for s in seeds]
    assert steps == list(range(1, len(seeds) + 1))          # file is in study order
    cats = [c for c, _ in ts.CATEGORIES]
    assert all(s["category"] in cats for s in seeds)
    assert all(isinstance(s["campus"], bool) and s.get("title") for s in seeds)
    qs = {s["question"] for s in seeds}
    assert all(s["related"] and set(s["related"]) <= qs and s["question"] not in s["related"] for s in seeds)
    j = auth_client.get("/api/prep/thoughts").get_json()
    assert [c[0] for c in j["categories"]] == cats
    first = next(t for t in j["items"] if t.get("step") == 1)
    assert first["category"] == "cs" and first["related"][0]["title"]
    js = open("static/js/prep_thoughts.js", encoding="utf-8").read()
    assert 'data-thf="campus"' in js and '"goto"' in js and "th-guide" in js


def test_marking_studied_schedules_a_review_and_reviews_move_it_out(auth_client, thoughts):
    from services import thoughts_service as ts
    from datetime import datetime, timezone
    items = auth_client.get("/api/prep/thoughts").get_json()["items"]
    root = next(t for t in items if t.get("step") == 1)
    r = auth_client.post(f"/api/prep/thoughts/{root['id']}", json={"understood": True}).get_json()
    assert r["status"] == "ok" and r["review_stage"] == 0 and r["next_review_at"]
    row = next(x for x in thoughts["rows"] if x["id"] == root["id"])
    assert row["understood"] is True and row["next_review_at"]
    days = (datetime.fromisoformat(r["next_review_at"]) - datetime.now(timezone.utc)).days
    assert days in (0, 1)
    j = auth_client.post(f"/api/prep/thoughts/{root['id']}/review", json={"rating": "good"}).get_json()
    assert j["review_stage"] == 1 and j["review_count"] == 1
    j = auth_client.post(f"/api/prep/thoughts/{root['id']}/review", json={"rating": "easy"}).get_json()
    assert j["review_stage"] == 3
    j = auth_client.post(f"/api/prep/thoughts/{root['id']}/review", json={"rating": "again"}).get_json()
    assert j["review_stage"] == 0
    assert auth_client.post(f"/api/prep/thoughts/{root['id']}/review", json={"rating": "meh"}).status_code == 400
    assert ts.next_review(6, "easy")[0] == len(ts.REVIEW_DAYS) - 1


def test_every_shipped_answer_has_a_choose_the_best_answer_quiz(auth_client, thoughts):
    from services import thoughts_service as ts
    seeds = ts.seeds(); quiz = ts.quizzes()
    assert all(len(quiz.get(s["question"], [])) >= 8 for s in seeds)
    for items in quiz.values():
        for m in items:
            assert len(m["options"]) == 4 and len(set(m["options"])) == 4 and m["answer"] in (0, 1, 2, 3) and m["why"]
    j = auth_client.get("/api/prep/thoughts/quiz/1").get_json()
    assert j["items"] and j["question"] == seeds[0]["question"]
    assert auth_client.get("/api/prep/thoughts/quiz/9999").status_code == 404
    items = auth_client.get("/api/prep/thoughts").get_json()["items"]
    assert next(t for t in items if t.get("step") == 1)["quiz_count"] >= 8


def test_every_shipped_answer_has_a_working_animated_diagram():
    import json, re
    from services import thoughts_service as ts
    kinds = {"user", "service", "broker", "db", "queue", "cache", "log", "note"}
    for s in ts.seeds():
        blocks = re.findall(r"```anim\n(.*?)\n```", s["answer"], re.S)
        assert blocks, s["title"]
        for b in blocks:
            spec = json.loads(b)
            ids = {n["id"] for n in spec["nodes"]}
            assert 2 <= len(spec["nodes"]) <= 14 and 4 <= len(spec["steps"]) <= 16
            assert all(n.get("kind", "service") in kinds for n in spec["nodes"])
            for st in spec["steps"]:
                assert st.get("say")
                for m in st.get("send", []):
                    assert m["from"] in ids and m["to"] in ids


def test_thought_pages_load_the_animation_player():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "static/js/flow_anim.js").exists()
    for page in ("templates/interview_prep.html", "templates/ai_sde_thoughts.html"):
        html = (root / page).read_text()
        assert html.index("js/flow_anim.js") < html.index("js/prep_thoughts.js")
    js = (root / "static/js/prep_thoughts.js").read_text()
    assert "fa-anim" in js and "FlowAnim.init" in js


def test_animation_player_has_speed_and_full_screen():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent / "static/js/flow_anim.js").read_text()
    assert 'data-fa="full"' in js and "requestFullscreen" in js and "fa-full" in js
    assert "fa-speed" in js and "faSpeed" in js and "/ (this.speed || 1)" in js


def test_thoughts_have_interview_version_and_ask_about_a_sentence():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent / "static/js/prep_thoughts.js").read_text()
    assert 'data-th="interview"' in js and 'case "interview"' in js
    # Selecting text is handled on every page by page_hints.js now; quoted
    # follow-ups made earlier still show their quote.
    assert "About this part: \\u201c" in js and "function followHead" in js


def test_a_follow_up_about_a_sentence_is_saved_on_that_thread(auth_client, thoughts):
    seed = auth_client.get("/api/prep/thoughts").get_json()["items"][0]
    q = "About this part: “Kafka keeps order only inside one partition.” Why?"
    j = auth_client.post("/api/prep/thoughts", json={"question": q, "parent_id": seed["id"]}).get_json()
    assert j["item"]["question"] == q and j["item"]["parent_id"] == seed["id"]

# ── Your notes on a Random thoughts question ──────────────────────────

def _a_question(auth_client):
    r = auth_client.post("/api/prep/thoughts", json={"question": "Why is Kafka ordered per partition?"})
    return r.get_json()["item"]


def test_notes_add_edit_and_soft_delete(auth_client, thoughts):
    q = _a_question(auth_client)
    r = auth_client.post(f"/api/prep/thoughts/{q['id']}/notes", json={"text": "  Asked at the Flipkart loop  "})
    assert r.status_code == 200, r.get_data(as_text=True)
    first = r.get_json()["notes"][0]
    assert first["text"] == "Asked at the Flipkart loop" and first["id"]
    second = auth_client.post(f"/api/prep/thoughts/{q['id']}/notes",
                              json={"text": "Lead with ordering, then throughput"}).get_json()["notes"][1]

    r = auth_client.post(f"/api/prep/thoughts/{q['id']}/notes/{first['id']}", json={"text": "Asked twice"})
    assert [n["text"] for n in r.get_json()["notes"]] == ["Asked twice", "Lead with ordering, then throughput"]

    r = auth_client.post(f"/api/prep/thoughts/{q['id']}/notes/{second['id']}/delete")
    assert [n["text"] for n in r.get_json()["notes"]] == ["Asked twice"]
    # Soft delete: the note is still in the row, stamped, and the list hides it.
    row = next(x for x in thoughts["rows"] if x["id"] == q["id"])
    gone = next(n for n in row["notes"] if n["id"] == second["id"])
    assert gone["deleted_at"] and gone["text"] == "Lead with ordering, then throughput"
    item = next(x for x in auth_client.get("/api/prep/thoughts").get_json()["items"] if x["id"] == q["id"])
    assert [n["text"] for n in item["notes"]] == ["Asked twice"]
    # A deleted note can't be edited back into view.
    assert auth_client.post(f"/api/prep/thoughts/{q['id']}/notes/{second['id']}",
                            json={"text": "x"}).status_code == 404


def test_notes_reject_empty_text_and_other_peoples_questions(auth_client, thoughts):
    q = _a_question(auth_client)
    assert auth_client.post(f"/api/prep/thoughts/{q['id']}/notes", json={"text": "   "}).status_code == 400
    thoughts["rows"].append({"id": "theirs", "user_id": "someone-else", "question": "Theirs", "notes": []})
    assert auth_client.post("/api/prep/thoughts/theirs/notes", json={"text": "hi"}).status_code == 404
    assert next(r for r in thoughts["rows"] if r["id"] == "theirs")["notes"] == []


def test_follow_ups_take_notes_too(auth_client, thoughts):
    q = _a_question(auth_client)
    child = auth_client.post("/api/prep/thoughts", json={"question": "Simpler?", "parent_id": q["id"]}).get_json()["item"]
    r = auth_client.post(f"/api/prep/thoughts/{child['id']}/notes", json={"text": "The queue analogy clicked"})
    assert r.status_code == 200 and r.get_json()["notes"][0]["text"] == "The queue analogy clicked"


def test_thoughts_still_load_before_the_notes_column_exists(auth_client, thoughts, monkeypatch):
    """The notes column comes from a later section of the migration: until it
    runs, the list must still load and say notes are unavailable, and adding
    a note must name the migration rather than fail obscurely."""
    import routes.interview_prep as ip
    from services import thoughts_service as ts
    q = _a_question(auth_client)
    real_get = ip.get

    def old_table(table, params=None, **kw):
        if "notes" in ((params or {}).get("select") or "").split(","):
            raise Exception('{"code":"42703","message":"column prep_thoughts.notes does not exist"}')
        return real_get(table, params, **kw)
    monkeypatch.setattr(ip, "get", old_table)
    monkeypatch.setattr(ts, "get", old_table)

    j = auth_client.get("/api/prep/thoughts").get_json()
    assert j["available"] is True and j["notes_available"] is False
    assert any(x["id"] == q["id"] for x in j["items"])
    r = auth_client.post(f"/api/prep/thoughts/{q['id']}/notes", json={"text": "hi"})
    assert r.status_code == 503 and "MIGRATION_PREP_THOUGHTS.sql" in r.get_json()["error"]


def test_the_thread_pdf_carries_your_notes(auth_client, thoughts, monkeypatch):
    import routes.interview_prep as ip
    q = _a_question(auth_client)
    auth_client.post(f"/api/prep/thoughts/{q['id']}/notes", json={"text": "Say partition key first"})
    seen = {}
    monkeypatch.setattr(ip, "_pdf_bytes", lambda title, sub, sections, **k: seen.setdefault("s", sections) and b"%PDF")
    thoughts["rows"][-1]["root_id"] = q["id"]
    for r in thoughts["rows"]:
        r.setdefault("root_id", r["id"])

    def by_root(table, params=None, **kw):
        out = [dict(r) for r in thoughts["rows"] if f"eq.{r.get('root_id')}" == (params or {}).get("root_id")]
        return out if "root_id" in (params or {}) else []
    monkeypatch.setattr(ip, "get", by_root)
    assert auth_client.get(f"/interview-prep/thoughts/{q['id']}/pdf").status_code == 200
    fields = dict(seen["s"][0]["fields"])
    assert "Say partition key first" in fields["Your notes"]


def test_notes_work_in_the_real_page(auth_client):
    """Runs tests/js/prep_thoughts_notes.test.js against the rendered page."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    html = auth_client.get("/ai-sde/thoughts").get_data(as_text=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        path = fh.name
    # Generous: a cold require('jsdom') from the Windows drive takes ~25 s.
    r = subprocess.run(["node", "tests/js/prep_thoughts_notes.test.js", path],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


def test_animated_diagrams_narrate_and_build_captions():
    """Runs tests/js/flow_anim_narration.test.js: Voice on/off, captions
    following the speech word by word, Play waiting for the voice."""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    # Generous: a cold require('jsdom') from the Windows drive takes ~25 s.
    r = subprocess.run(["node", "tests/js/flow_anim_narration.test.js"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


def test_highlight_and_ask_is_saved_as_a_hint_on_that_answer(auth_client, thoughts, monkeypatch):
    from services import thoughts_service as ts
    calls = []
    monkeypatch.setattr(ts, "answer_in_background", lambda *a, **k: calls.append((a, k)))
    root = auth_client.get("/api/prep/thoughts").get_json()["items"][0]
    hl = {"quote": "  a single   append-only log ", "prefix": "x" * 200}
    j = auth_client.post("/api/prep/thoughts", json={"question": "", "parent_id": root["id"], "highlight": hl})
    assert j.status_code == 201
    item = j.get_json()["item"]
    assert item["highlight"] == {"quote": "a single append-only log", "prefix": "x" * 80}
    assert item["parent_id"] == root["id"] and item["context"] == "a single append-only log"
    assert item["question"].startswith("Explain this part simply")
    assert calls[-1][1]["highlight"]["quote"] == "a single append-only log"
    # A highlight needs an answer to sit on, and some words.
    assert auth_client.post("/api/prep/thoughts", json={"question": "q", "highlight": hl}).status_code == 400
    assert auth_client.post("/api/prep/thoughts", json={"question": "q", "parent_id": root["id"],
                                                        "highlight": {"quote": " "}}).status_code == 400
    # Rewrite keeps it a hint.
    auth_client.post(f"/api/prep/thoughts/{item['id']}/retry")
    assert calls[-1][1]["highlight"]["quote"] == "a single append-only log"


def test_a_hint_gets_short_hint_instructions(monkeypatch):
    from services import thoughts_service as ts
    seen = {}
    def fake(prompt, images=(), system=None):
        seen.update(prompt=prompt, system=system); return "Short hint.", "fake"
    monkeypatch.setattr(ts, "PROVIDERS", [fake])
    text, _ = ts.generate("What is append-only?", "", {"question": "Q", "answer": "The study answer."},
                          shelf="aisde", highlight={"quote": "append-only log", "prefix": ""})
    assert text == "Short hint."
    assert seen["system"].startswith(ts.HINT_SYSTEM) and "student" in seen["system"]
    assert "“append-only log”" in seen["prompt"] and "The study answer." in seen["prompt"]
    ts.generate("Normal question", shelf="tpm")
    assert seen["system"] is None or not seen["system"].startswith(ts.HINT_SYSTEM)


def test_random_thoughts_leave_highlighting_to_page_hints():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    js = (root / "static/js/prep_thoughts.js").read_text()
    assert "Highlight & ask" not in js and "!t.highlight" in js
    assert 'data-tid="' in js  # answers carry their id, which page_hints uses as the anchor


def test_a_failed_read_is_an_error_not_the_read_only_seed_list(auth_client, thoughts, monkeypatch):
    # str(HTTPError) carries the URL, which names prep_thoughts; that used to
    # make every failure look like a missing table, so the page fell back to
    # "seed-N" items and every Mark studied on them was a 400.
    import requests
    import routes.interview_prep as ip
    from services import thoughts_service as ts

    def http_error(status, body):
        resp = requests.Response()
        resp.status_code, resp._content = status, body.encode()
        return requests.HTTPError(f"{status} for url: https://x.supabase.co/rest/v1/prep_thoughts?select=id",
                                  response=resp)

    def timeout(*a, **k):
        raise http_error(504, '{"message":"upstream timeout"}')
    monkeypatch.setattr(ts, "get", timeout)
    monkeypatch.setattr(ip, "get", timeout)
    ts._seeded.clear()
    r = auth_client.get("/api/prep/thoughts")
    assert r.status_code == 500 or not any(str(i["id"]).startswith("seed-") for i in (r.get_json() or {}).get("items", []))

    def gone(*a, **k):
        raise http_error(404, '{"code":"PGRST205","message":"Could not find the table \'public.prep_thoughts\'"}')
    monkeypatch.setattr(ts, "get", gone)
    monkeypatch.setattr(ip, "get", gone)
    ts._seeded.clear()
    j = auth_client.get("/api/prep/thoughts").get_json()
    assert j["available"] is False and j["items"][0]["id"].startswith("seed-")


def test_audio_is_made_on_request_and_served_to_its_owner_only(auth_client, thoughts, monkeypatch):
    import routes.interview_prep as ip
    started = []
    monkeypatch.setattr(ip.thoughts_audio, "start",
                        lambda tid, uid, force=False: started.append((tid, force)) or {"status": "pending"})
    thoughts["rows"].append({"id": "a1", "user_id": "test-user-id", "parent_id": None, "root_id": "a1",
                             "question": "Q?", "answer": "A.", "status": "ready", "audio": None})
    r = auth_client.post("/api/prep/thoughts/a1/audio", json={})
    assert r.status_code == 200 and r.get_json()["audio"]["status"] == "pending" and started == [("a1", False)]
    # Ready and current: nothing to do unless asked for a new take.
    from services import thoughts_audio as ta
    row = thoughts["rows"][-1]
    row["audio"] = {"status": "ready", "hash": ta.answer_hash("Q?", "A."), "key": "test-user-id/a1-x.mp3"}
    assert auth_client.post("/api/prep/thoughts/a1/audio", json={}).get_json()["audio"]["status"] == "ready"
    auth_client.post("/api/prep/thoughts/a1/audio", json={"force": True})
    assert started[-1] == ("a1", True)
    # The file: Range works (iOS needs it); someone else's key is refused.
    monkeypatch.setattr(ip.thoughts_audio, "fetch", lambda key: b"\xff\xf3\x84\xc4" + bytes(500))
    r = auth_client.get("/interview-prep/thoughts/audio/a1", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.mimetype == "audio/mpeg" and len(r.data) == 100
    row["audio"]["key"] = "someone-else/a1-x.mp3"
    assert auth_client.get("/interview-prep/thoughts/audio/a1").status_code == 404
    # Follow-ups have no audio of their own.
    thoughts["rows"].append({"id": "f1", "user_id": "test-user-id", "parent_id": "a1", "question": "Why?",
                             "answer": "B.", "status": "ready", "audio": None})
    assert auth_client.post("/api/prep/thoughts/f1/audio", json={}).status_code == 409


def test_marking_studied_queues_its_audio_and_a_plain_open_does_not(auth_client, thoughts):
    thoughts["rows"].append({"id": "s1", "user_id": "test-user-id", "parent_id": None, "root_id": "s1",
                             "question": "Q?", "answer": "A.", "status": "ready", "audio": None,
                             "understood": False})
    assert auth_client.get("/api/prep/thoughts").status_code == 200
    assert ("audio", "s1") not in thoughts["started"]
    r = auth_client.post("/api/prep/thoughts/s1", json={"understood": True}).get_json()
    assert r["audio"] == {"status": "pending"} and ("audio", "s1") in thoughts["started"]


def test_audio_rows_render_in_the_real_page(auth_client):
    """Runs tests/js/prep_thoughts_audio.test.js: real row shapes (audio
    null/pending/ready, studied and due) through the real script."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("node"):
        pytest.skip("node not installed")
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"],
                           capture_output=True, text=True, cwd="tests/js")
    if probe.returncode != 0:
        pytest.skip("jsdom not installed")
    html = auth_client.get("/ai-sde/thoughts").get_data(as_text=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        path = fh.name
    r = subprocess.run(["node", "tests/js/prep_thoughts_audio.test.js", path],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr


def test_an_empty_list_says_why(auth_client, thoughts, monkeypatch):
    # Every user has the shipped questions, so an empty list is a fault: with
    # the PUBLIC key, row-level security hides every row and refuses inserts.
    import routes.interview_prep as ip
    from services import thoughts_service as ts
    monkeypatch.setattr(ts, "seeds", lambda: [])
    monkeypatch.setattr(ts, "key_kind", lambda key=None: "public")
    ts._seeded.clear()
    j = auth_client.get("/api/prep/thoughts").get_json()
    assert j["items"] == [] and "SECRET key" in j["empty_reason"] and "disable row level security" in j["empty_reason"]
    monkeypatch.setattr(ts, "key_kind", lambda key=None: "secret")
    def refuse(*a, **k):
        raise RuntimeError("new row violates row-level security policy")
    monkeypatch.setattr(ts, "ensure_seeds", refuse)
    j = auth_client.get("/api/prep/thoughts").get_json()
    assert "row-level security" in j["empty_reason"]


def test_key_kind_reads_new_and_legacy_keys():
    import base64, json
    from services import thoughts_service as ts
    jwt = lambda role: "h." + base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=") + ".s"
    assert ts.key_kind("sb_secret_x") == "secret" and ts.key_kind("sb_publishable_x") == "public"
    assert ts.key_kind(jwt("service_role")) == "secret" and ts.key_kind(jwt("anon")) == "public"
    assert ts.key_kind("garbage") == "unknown"


def test_system_design_five_page_summary(auth_client):
    html = auth_client.get("/interview-prep/guides/system-design-summary").get_data(as_text=True)
    assert "System design in 5 pages" in html and "Page 3. The pattern behind each family" in html
    tab = auth_client.get("/interview-prep/design").get_data(as_text=True)
    assert "/interview-prep/guides/system-design-summary" in tab
    r = auth_client.get("/interview-prep/guides/system-design-summary/pdf?fs=10.5")
    if r.status_code == 200 and r.mimetype == "application/pdf":
        import re
        assert len(re.findall(rb"/Type\s*/Page\b", r.data)) == 5
    assert auth_client.get("/interview-prep/guides/nope/pdf").status_code == 404


def test_deep_dive_five_page_summaries(auth_client):
    import os, re
    import sd_deep_bank
    have = [d["slug"] for d in sd_deep_bank.DESIGNS if os.path.exists(sd_deep_bank.summary_path(d["slug"]))]
    assert "uber" in have
    lst = auth_client.get("/api/sd-deep").get_json()
    items = lst.get("designs") or lst.get("items") or []
    assert any(x.get("has_summary") for x in items if x.get("slug") == "uber")
    html = auth_client.get("/interview-prep/design/uber/summary").get_data(as_text=True)
    assert "5-page summary" in html and "Page 5. Say it in the interview" in html
    r = auth_client.get("/interview-prep/design/uber/summary.pdf")
    if r.mimetype == "application/pdf":
        assert len(re.findall(rb"/Type\s*/Page\b", r.data)) == 5
    for slug in have:  # every shipped summary keeps the 5-page shape
        md = sd_deep_bank.summary_text(slug)
        assert [int(n) for n in re.findall(r"^## Page (\d)\. ", md, re.M)] == [1, 2, 3, 4, 5], slug
    assert auth_client.get("/interview-prep/design/not-a-design/summary").status_code == 404


def test_system_design_phrases_guide(auth_client):
    client = auth_client
    r = client.get("/interview-prep/guides/system-design-phrases")
    assert r.status_code == 200
    assert b"Rescue phrases" in r.data
    r = client.get("/interview-prep/guides/system-design-phrases/pdf")
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    r = client.get("/interview-prep")
    assert b"/interview-prep/guides/system-design-phrases" in r.data
    r = client.get("/interview-prep/design/uber/summary")
    assert b"system-design-phrases" in r.data
