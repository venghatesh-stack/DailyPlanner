"""Compare two schema snapshots from scripts/schema_snapshot.sql.

    python scripts/compare_schema.py schema_A.json schema_B.json

Prints every difference: tables, columns (type / nullability / default),
constraints, indexes, RLS, policies, triggers, views, functions (by
definition hash) and extensions. Exit code 0 when identical, 1 otherwise.
Accepts the raw JSON, or the JSON wrapped in quotes / a CSV cell as the
Supabase editor sometimes copies it.
"""
import json
import sys


def load(path):
    raw = open(path, encoding="utf-8").read().strip()
    # Tolerate a copied CSV cell: header line and/or surrounding quotes.
    if raw.lower().startswith("snapshot"):
        raw = raw.split("\n", 1)[1].strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1].replace('""', '"')
    data = json.loads(raw)
    if isinstance(data, list):                 # [{"snapshot": {...}}]
        data = data[0]
    if isinstance(data, dict) and "snapshot" in data and len(data) == 1:
        data = data["snapshot"]
    if isinstance(data, str):
        data = json.loads(data)
    return data


def diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in b:
                out.append(f"only in A   {p}")
            elif k not in a:
                out.append(f"only in B   {p}")
            else:
                diff(a[k], b[k], p, out)
    elif a != b:
        out.append(f"different   {path}\n      A: {a}\n      B: {b}")


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    a, b = load(sys.argv[1]), load(sys.argv[2])
    out = []
    diff(a, b, "", out)
    if not out:
        print("Identical.")
        sys.exit(0)
    print(f"{len(out)} difference(s):\n")
    print("\n".join(out))
    sys.exit(1)


if __name__ == "__main__":
    main()
