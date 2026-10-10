"""Generate the SQL that brings schema B up to schema A.

    python scripts/schema_delta.py schema_A.json schema_B.json > delta.sql

Both inputs are outputs of scripts/schema_snapshot.sql. The SQL has two
parts:

  PART 1 — safe and additive, runs as one transaction:
    missing tables (with their sequences, keys and checks), missing
    columns, missing defaults, missing constraints (foreign keys last),
    missing indexes, and trigger functions whose source is in this repo.
  PART 2 — commented out, for review: anything that rewrites or can fail
    on existing data — column type changes, adding NOT NULL — plus notes
    on what exists only in B (left alone) and RLS differences.

Nothing is dropped.

Also usable as `--create B.json` to print CREATE statements for a whole
snapshot (used to rebuild a schema from a snapshot for testing).
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_schema import load  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def q(name):
    return '"' + name.replace('"', '""') + '"'


def col_sql(name, c):
    s = f"{q(name)} {c['type']}"
    if c.get("default") is not None:
        s += f" default {c['default']}"
    if c.get("not_null"):
        s += " not null"
    return s


def sequences_in(default):
    return re.findall(r"nextval\('([^']+)'::regclass\)", default or "")


def is_fk(defn):
    return defn.startswith("FOREIGN KEY")


def pk_cols(t):
    out = set()
    for d in t["constraints"].values():
        m = re.match(r"PRIMARY KEY \((.+)\)", d)
        if m:
            out |= {x.strip().strip('"') for x in m.group(1).split(",")}
    return out


def create_table(name, t):
    out = []
    for c in t["columns"].values():
        for seq in sequences_in(c.get("default")):
            out.append(f"create sequence if not exists {seq};")
    cols = [col_sql(n, c) for n, c in t["columns"].items()]
    cons = [f"constraint {q(cn)} {d}" for cn, d in t["constraints"].items() if not is_fk(d)]
    body = ",\n    ".join(cols + cons)
    out.append(f"create table if not exists public.{q(name)} (\n    {body}\n);")
    return out


def index_sql(defn):
    return re.sub(r"^CREATE (UNIQUE )?INDEX ", lambda m: f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS ", defn) + ";"


def add_constraint(table, cn, defn):
    # Postgres has no ADD CONSTRAINT IF NOT EXISTS — guard it.
    return (f"do $$ begin\n"
            f"  if not exists (select 1 from pg_constraint where conname = '{cn}'"
            f" and conrelid = 'public.{q(table)}'::regclass) then\n"
            f"    alter table public.{q(table)} add constraint {q(cn)} {defn};\n"
            f"  end if;\nend $$;")


def function_source(signature):
    """Find CREATE FUNCTION for a missing trigger function in the repo's SQL."""
    fname = signature.split("(")[0]
    pat = re.compile(r"create\s+(or\s+replace\s+)?function\s+(public\.)?" + re.escape(fname) + r"\s*\(",
                     re.I)
    for path in sorted(glob.glob(os.path.join(REPO, "*.sql"))):
        src = open(path, encoding="utf-8").read()
        m = pat.search(src)
        if not m:
            continue
        # The body ends at the closing $$ / $tag$ followed by ';'
        tail = src[m.start():]
        tag = re.search(r"as\s+(\$[A-Za-z_]*\$)", tail, re.I)
        if not tag:
            continue
        end = tail.find(tag.group(1), tag.end())
        semi = tail.find(";", end)
        if end > 0 and semi > 0:
            body = re.sub(r"^create\s+(or\s+replace\s+)?function", "create or replace function",
                          tail[:semi + 1], count=1, flags=re.I)
            return os.path.basename(path), body
    return None, None


def create_all(snap):
    """Whole-schema CREATE script for a snapshot (testing aid)."""
    out = ["begin;"]
    for name, t in snap["tables"].items():
        out += create_table(name, t)
    for name, t in snap["tables"].items():
        for cn, d in t["constraints"].items():
            if is_fk(d):
                out.append(add_constraint(name, cn, d))
        for iname, d in t["indexes"].items():
            if iname not in t["constraints"]:
                out.append(index_sql(d))
        if t.get("rls"):
            out.append(f"alter table public.{q(name)} enable row level security;")
    out.append("commit;")
    return "\n".join(out)


def delta(a, b):
    ta, tb = a["tables"], b["tables"]
    p1, fks, idx, p2, notes = [], [], [], [], []

    missing = [t for t in ta if t not in tb]
    for t in missing:
        p1.append(f"-- table {t}")
        p1 += create_table(t, ta[t])
        for cn, d in ta[t]["constraints"].items():
            if is_fk(d):
                fks.append(add_constraint(t, cn, d))
        for iname, d in ta[t]["indexes"].items():
            if iname not in ta[t]["constraints"]:
                idx.append(index_sql(d))
        for trg, d in ta[t]["triggers"].items():
            idx.append(f"-- trigger {trg} (needs its function — see FUNCTIONS below)\n"
                       f"drop trigger if exists {q(trg)} on public.{q(t)};\n{d};")

    for t in ta:
        if t not in tb:
            continue
        A, B = ta[t], tb[t]
        for c, spec in A["columns"].items():
            if c not in B["columns"]:
                for seq in sequences_in(spec.get("default")):
                    p1.append(f"create sequence if not exists {seq};")
                # Add as nullable with its default; NOT NULL is applied in
                # PART 2 only when safe, because existing rows have no value
                # unless a default fills them.
                safe_nn = spec.get("not_null") and spec.get("default") is not None
                spec2 = dict(spec, not_null=safe_nn)
                p1.append(f"alter table public.{q(t)} add column if not exists {col_sql(c, spec2)};")
                if spec.get("not_null") and not safe_nn:
                    p2.append(f"-- {t}.{c} is NOT NULL in A; it has no default, so fill it first:\n"
                              f"-- alter table public.{q(t)} alter column {q(c)} set not null;")
            else:
                cb = B["columns"][c]
                if spec["type"] != cb["type"]:
                    p2.append(f"-- {t}.{c}: A={spec['type']}  B={cb['type']}\n"
                              f"-- alter table public.{q(t)} alter column {q(c)} type {spec['type']} "
                              f"using {q(c)}::{spec['type']};")
                if spec.get("default") != cb.get("default") and spec["type"] == cb["type"]:
                    if spec.get("default") is None:
                        p1.append(f"alter table public.{q(t)} alter column {q(c)} drop default;")
                    else:
                        for seq in sequences_in(spec.get("default")):
                            p1.append(f"create sequence if not exists {seq};")
                        p1.append(f"alter table public.{q(t)} alter column {q(c)} set default {spec['default']};")
                if spec.get("not_null") and not cb.get("not_null"):
                    p2.append(f"-- {t}.{c}: NOT NULL in A, nullable in B (fails if B has nulls):\n"
                              f"-- alter table public.{q(t)} alter column {q(c)} set not null;")
                if not spec.get("not_null") and cb.get("not_null"):
                    if c in pk_cols(B):
                        notes.append(f"-- {t}.{c}: nullable in A but part of B's primary key — left NOT NULL")
                    else:
                        p1.append(f"alter table public.{q(t)} alter column {q(c)} drop not null;")
        extra = [c for c in B["columns"] if c not in A["columns"]]
        if extra:
            notes.append(f"-- {t}: columns only in B, left in place: {', '.join(extra)}")
        for cn, d in A["constraints"].items():
            if cn not in B["constraints"]:
                (fks if is_fk(d) else p1).append(add_constraint(t, cn, d))
        for iname, d in A["indexes"].items():
            if iname in A["constraints"] or iname in B["constraints"]:
                continue
            if iname not in B["indexes"]:
                idx.append(index_sql(d))
            elif B["indexes"][iname] != d:
                # Same name, different definition: rebuild it as A has it.
                idx.append(f"-- {iname}: B had {B['indexes'][iname]}\n"
                           f"drop index if exists public.{q(iname)};\n{index_sql(d)}")
        for trg, d in A["triggers"].items():
            if trg not in B["triggers"]:
                idx.append(f"drop trigger if exists {q(trg)} on public.{q(t)};\n{d};")
        if A.get("rls") != B.get("rls"):
            notes.append(f"-- {t}: RLS A={A.get('rls')} B={B.get('rls')}")

    funcs = []
    for f in a["functions"]:
        if f not in b["functions"]:
            src_file, src = function_source(f)
            if src:
                funcs.append(f"-- {f}  (from {src_file})\n{src}")
            else:
                p2.append(f"-- function {f} exists only in A and its source is not in this repo;\n"
                          f"-- copy it from A: select pg_get_functiondef('public.{f}'::regprocedure);")
    for f in b["functions"]:
        if f not in a["functions"]:
            notes.append(f"-- function {f} exists only in B (left in place)")
    for e, v in a["extensions"].items():
        if e not in b["extensions"]:
            p1.insert(0, f"create extension if not exists {q(e)};")

    lines = ["-- ============================================================",
             "--  DELTA: bring schema B up to schema A (generated by",
             "--  scripts/schema_delta.py). Nothing is dropped.",
             "-- ============================================================",
             "",
             "-- PART 1 — safe, additive. One transaction: all or nothing.",
             "begin;", "", "create extension if not exists pgcrypto;",
             "create extension if not exists \"uuid-ossp\";", ""]
    lines += p1
    if funcs:
        lines += ["", "-- FUNCTIONS (needed by triggers below)"] + funcs
    lines += ["", "-- FOREIGN KEYS (after every table exists)"] + fks
    lines += ["", "-- INDEXES AND TRIGGERS"] + idx
    lines += ["", "commit;", "", "",
              "-- PART 2 — REVIEW BEFORE RUNNING. Commented out on purpose: these",
              "-- rewrite columns or can fail on existing rows."]
    lines += p2
    lines += ["", "-- NOTES (no action generated)"] + notes
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--create":
        print(create_all(load(sys.argv[2])))
        return
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    print(delta(load(sys.argv[1]), load(sys.argv[2])), end="")


if __name__ == "__main__":
    main()
