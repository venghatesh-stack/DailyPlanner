"""
Portfolio Watchlist — Track stocks, mutual funds, ETFs, FDs, bonds, cash, gold, PPF, NPS, etc.
Import from ICICI Direct CSV. XIRR calculation. Field-level encryption.
"""
import uuid
import logging
from datetime import datetime, date
from flask import Blueprint, request, jsonify, session, render_template
from supabase_client import get, post, update, delete
from services.login_service import login_required
from config import IST
from utils.user_tz import user_now, user_today
from utils.encryption import encrypt_fields, decrypt_fields, decrypt_rows

logger = logging.getLogger("daily_plan")
portfolio_bp = Blueprint("portfolio", __name__)

# Sensitive fields encrypted at rest
ENCRYPTED_FIELDS = ["name", "symbol", "folio_number", "broker", "notes",
                    "institution", "account_ref"]


@portfolio_bp.before_request
def _gate_with_vault():
    """Sit every portfolio route — page and API — behind the same vault
    password as /refcards. Imported lazily so the routes/refcards module
    is fully initialised before this resolves (both blueprints are
    imported by app.py at startup, but the order isn't guaranteed)."""
    from routes.refcards import vault_gate_for_blueprint
    return vault_gate_for_blueprint(page_label="Portfolio")


# ═══════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/portfolio")
@login_required
def portfolio_page():
    return render_template("portfolio.html")


# ═══════════════════════════════════════════════════
# HOLDINGS CRUD
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/holdings", methods=["GET"])
@login_required
def list_holdings():
    user_id = session["user_id"]
    asset_type = request.args.get("type")
    include_deleted = request.args.get("include_deleted") == "1"

    params = {
        "user_id": f"eq.{user_id}",
        "order": "asset_type.asc,name.asc",
    }
    if asset_type:
        params["asset_type"] = f"eq.{asset_type}"
    if not include_deleted:
        params["is_deleted"] = "is.false"

    rows = get("portfolio_holdings", params=params) or []
    decrypt_rows(rows, ENCRYPTED_FIELDS)
    return jsonify(rows)


@portfolio_bp.route("/api/portfolio/holdings", methods=["POST"])
@login_required
def add_holding():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    holding = {
        "id": str(uuid.uuid4()),
        "user_id": session["user_id"],
        "name": name,
        "symbol": (data.get("symbol") or "").strip().upper() or None,
        "asset_type": data.get("asset_type", "stock"),
        "exchange": (data.get("exchange") or "").strip().upper() or None,
        "quantity": float(data["quantity"]) if data.get("quantity") else 0,
        "avg_price": float(data["avg_price"]) if data.get("avg_price") else 0,
        "current_price": float(data["current_price"]) if data.get("current_price") else None,
        "currency": data.get("currency", "INR"),
        "folio_number": (data.get("folio_number") or "").strip() or None,
        "broker": (data.get("broker") or "").strip() or None,
        "notes": (data.get("notes") or "").strip() or None,
        "sector": (data.get("sector") or "").strip() or None,
        "held_by": (data.get("held_by") or "").strip() or None,
        "buy_date": data.get("buy_date") or None,
        "sell_date": data.get("sell_date") or None,
        # FD / Bond / PPF specific fields
        "institution": (data.get("institution") or "").strip() or None,
        "interest_rate": float(data["interest_rate"]) if data.get("interest_rate") else None,
        "payout_type": data.get("payout_type") or None,
        "compounding": data.get("compounding") or None,
        "maturity_date": data.get("maturity_date") or None,
        "start_date": data.get("start_date") or None,
        "account_ref": (data.get("account_ref") or "").strip() or None,
    }

    encrypt_fields(holding, ENCRYPTED_FIELDS)
    rows = post("portfolio_holdings", holding)
    if rows:
        decrypt_fields(rows[0], ENCRYPTED_FIELDS)
    return jsonify(rows[0] if rows else data)


@portfolio_bp.route("/api/portfolio/holdings/<hid>", methods=["PUT"])
@login_required
def update_holding(hid):
    data = request.get_json() or {}
    allowed = [
        "name", "symbol", "asset_type", "exchange", "quantity", "avg_price",
        "current_price", "currency", "folio_number", "broker", "notes", "sector",
        "held_by", "buy_date", "sell_date",
        "institution", "interest_rate", "payout_type", "compounding",
        "maturity_date", "start_date", "account_ref",
    ]
    payload = {f: data[f] for f in allowed if f in data}
    if not payload:
        return jsonify({"error": "Nothing to update"}), 400

    encrypt_fields(payload, ENCRYPTED_FIELDS)
    update("portfolio_holdings",
           params={"id": f"eq.{hid}", "user_id": f"eq.{session['user_id']}"},
           json=payload)
    return jsonify({"success": True})


@portfolio_bp.route("/api/portfolio/holdings/<hid>", methods=["DELETE"])
@login_required
def delete_holding(hid):
    # Soft-delete: years of investment history must remain recoverable.
    # Cascade the soft-delete to the holding's transactions too —
    # otherwise summary/XIRR/coverage queries that scan transactions
    # by user_id keep counting them, leaving deleted holdings visible
    # in the KPIs even after they vanish from the table.
    user_id = session["user_id"]
    now_iso = user_now().isoformat()
    update(
        "portfolio_holdings",
        params={"id": f"eq.{hid}", "user_id": f"eq.{user_id}"},
        json={"is_deleted": True, "deleted_at": now_iso},
    )
    update(
        "portfolio_transactions",
        params={"holding_id": f"eq.{hid}", "user_id": f"eq.{user_id}"},
        json={"is_deleted": True, "deleted_at": now_iso},
    )
    return jsonify({"success": True})


@portfolio_bp.route("/api/portfolio/holdings/<hid>/restore", methods=["POST"])
@login_required
def restore_holding(hid):
    """Undo a soft-deleted holding (and its transactions)."""
    user_id = session["user_id"]
    update(
        "portfolio_holdings",
        params={"id": f"eq.{hid}", "user_id": f"eq.{user_id}"},
        json={"is_deleted": False, "deleted_at": None},
    )
    update(
        "portfolio_transactions",
        params={"holding_id": f"eq.{hid}", "user_id": f"eq.{user_id}"},
        json={"is_deleted": False, "deleted_at": None},
    )
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════
# BULK IMPORT (CSV parsed on client, sent as JSON)
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/import", methods=["POST"])
@login_required
def import_holdings():
    data = request.get_json() or {}
    rows = data.get("rows", [])
    broker = data.get("broker", "ICICI Direct")
    # Family-member assignment from the import dialog. Falls back to
    # None so the column is omitted entirely (Postgres default applies)
    # rather than written as the string "" which would break filters.
    held_by = (data.get("held_by") or "").strip() or None

    if not rows:
        return jsonify({"error": "No rows to import"}), 400

    user_id = session["user_id"]
    created = 0

    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue

        try:
            row_data = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "name": name,
                "symbol": (r.get("symbol") or "").strip().upper() or None,
                "asset_type": r.get("asset_type", "stock"),
                "exchange": (r.get("exchange") or "").strip().upper() or None,
                "quantity": float(r["quantity"]) if r.get("quantity") else 0,
                "avg_price": float(r["avg_price"]) if r.get("avg_price") else 0,
                "current_price": float(r["current_price"]) if r.get("current_price") else None,
                "currency": r.get("currency", "INR"),
                "folio_number": (r.get("folio_number") or "").strip() or None,
                "broker": broker,
                "held_by": held_by,
                "sector": (r.get("sector") or "").strip() or None,
            }
            encrypt_fields(row_data, ENCRYPTED_FIELDS)
            post("portfolio_holdings", row_data)
            created += 1
        except Exception as e:
            logger.warning("Import row failed: %s", str(e))

    return jsonify({"status": "ok", "imported": created})


# ═══════════════════════════════════════════════════
# TRANSACTION-LEDGER IMPORT (e.g. ICICI Direct PortFolioEqtAll)
# ═══════════════════════════════════════════════════
#
# Different from /api/portfolio/import (which expects a holdings
# *snapshot*). The ledger CSV is one row per buy/sell with a date,
# so we have to replay transactions to derive the current quantity
# and weighted-average cost. Doing this client-side would mean
# trusting the browser to compute money math; doing it server-side
# keeps the holdings table authoritative.
#
# Idempotent: re-uploading the same CSV inserts zero duplicates
# because transactions are deduped on (holding_id, txn_type,
# txn_date, quantity, price).

_MONTH_ABBREV = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_dmy_or_iso(s: str):
    """Normalise a date string into ISO (YYYY-MM-DD).

    Accepts:
      - ISO already: 2026-03-30
      - Numeric DMY: 30-03-2026, 30/03/2026
      - Month-name DMY (ICICI tradeBook): 30-Mar-2026, 30/March/2026

    Returns None for anything we can't parse. The import filter drops
    rows with None so a single malformed row doesn't poison a batch."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    # ISO already?
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    sep = "-" if "-" in s else "/" if "/" in s else None
    if not sep:
        return None
    parts = s.split(sep)
    if len(parts) < 3:
        return None
    try:
        d = int(parts[0])
        m_raw = parts[1].strip().lower()
        if m_raw.isdigit():
            m = int(m_raw)
        else:
            # First 3-4 chars covers Jan/Feb/.../Sept etc.
            m = _MONTH_ABBREV.get(m_raw[:4]) or _MONTH_ABBREV.get(m_raw[:3])
            if m is None:
                return None
        y = int(parts[2])
        if y < 100:
            y += 2000
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (ValueError, TypeError):
        return None


def _replay_to_position(transactions):
    """Walk transactions in date order, applying weighted-average cost.

    Returns (final_quantity, final_avg_price, first_buy_date). Sells
    reduce quantity but leave avg unchanged — that's the convention
    every brokerage shows on the open position. If quantity ever
    goes through zero (fully exited then re-bought), avg resets to
    the next buy's price.
    """
    qty = 0.0
    avg = 0.0
    first_buy = None
    for t in sorted(transactions, key=lambda r: (r.get("txn_date") or "", r.get("created_at") or "")):
        action = (t.get("txn_type") or "").lower()
        q = float(t.get("quantity") or 0)
        p = float(t.get("price") or 0)
        if q <= 0:
            continue
        if action == "buy":
            if not first_buy:
                first_buy = t.get("txn_date")
            if qty <= 0:
                # Fully exited or never held — start fresh.
                qty = q
                avg = p
            else:
                avg = (qty * avg + q * p) / (qty + q)
                qty += q
        elif action == "sell":
            qty -= q
            if qty <= 1e-9:
                qty = 0.0
                avg = 0.0   # reset so a later re-buy starts clean
    return qty, avg, first_buy


@portfolio_bp.route("/api/portfolio/import-transactions", methods=["POST"])
@login_required
def import_transactions():
    """Import a transaction ledger (e.g. ICICI Direct equity transaction
    export) and rebuild the affected holdings.

    Body: { rows: [{ action, symbol, name, quantity, price, txn_date,
                     exchange, isin?, charges?, brokerage? }],
            broker: "ICICI Direct" }

    Each row's `txn_date` is normalised from DD-MM-YYYY → YYYY-MM-DD.
    Brokerage + charges are folded into the `amount` so XIRR reflects
    actual cash out/in (buys cost more, sells net less)."""
    data = request.get_json() or {}
    rows = data.get("rows", []) or []
    broker = data.get("broker") or "ICICI Direct"
    held_by = (data.get("held_by") or "").strip() or None
    if not rows:
        return jsonify({"error": "No rows to import"}), 400

    user_id = session["user_id"]

    # Group rows by symbol so each holding's transactions land together.
    by_symbol: dict[str, list] = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(r)

    # Pull existing holdings once, keyed by symbol — saves N round-trips.
    # Include soft-deleted rows so a delete-then-reimport doesn't create
    # a duplicate holding for the same ticker (the main cause of bloat
    # in users' tables). When we match a deleted row, we'll undelete it
    # and re-attach the new transactions.
    existing_holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "select": "id,symbol,name,exchange,asset_type,is_deleted,held_by",
    }) or []
    decrypt_rows(existing_holdings, ENCRYPTED_FIELDS)
    holdings_by_sym = {
        (h.get("symbol") or "").upper(): h for h in existing_holdings if h.get("symbol")
    }

    txn_inserted = 0
    txn_skipped = 0
    holdings_created = 0
    holdings_undeleted = 0

    for sym, group in by_symbol.items():
        # ── Find or create the holding ────────────────────────────
        holding = holdings_by_sym.get(sym)
        if holding and holding.get("is_deleted"):
            # User had soft-deleted this earlier. Re-importing the same
            # ticker is them re-asserting interest — undelete instead of
            # creating a parallel row. Also undelete the transactions
            # (delete_holding cascades soft-delete to them, so restore
            # has to mirror that).
            try:
                update(
                    "portfolio_holdings",
                    params={"id": f"eq.{holding['id']}", "user_id": f"eq.{user_id}"},
                    json={"is_deleted": False, "deleted_at": None},
                )
                update(
                    "portfolio_transactions",
                    params={"holding_id": f"eq.{holding['id']}", "user_id": f"eq.{user_id}"},
                    json={"is_deleted": False, "deleted_at": None},
                )
                holding["is_deleted"] = False
                holdings_undeleted += 1
            except Exception as e:
                logger.warning("import-txn undelete %s failed: %s", sym, e)
        # Backfill held_by on an existing row that doesn't have one
        # yet — covers holdings created by the pre-held-by-import code.
        # Never overwrite a non-empty held_by, since that could yank
        # someone else's portfolio entry from under them.
        if holding and held_by and not (holding.get("held_by") or "").strip():
            try:
                update(
                    "portfolio_holdings",
                    params={"id": f"eq.{holding['id']}", "user_id": f"eq.{user_id}"},
                    json={"held_by": held_by},
                )
                holding["held_by"] = held_by
            except Exception as e:
                logger.warning("import-txn set held_by %s failed: %s", sym, e)
        if not holding:
            sample = group[0]
            new_h = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "name": (sample.get("name") or sym).strip(),
                "symbol": sym,
                "asset_type": "stock",
                "exchange": (sample.get("exchange") or "NSE").strip().upper(),
                "currency": "INR",
                "held_by": held_by,
                "broker": broker,
                "quantity": 0,
                "avg_price": 0,
            }
            encrypt_fields(new_h, ENCRYPTED_FIELDS)
            try:
                created_rows = post("portfolio_holdings", new_h)
                # Decrypt the returned row so subsequent code reads
                # plaintext name/symbol like everywhere else does.
                if created_rows:
                    decrypt_fields(created_rows[0], ENCRYPTED_FIELDS)
                    holding = created_rows[0]
                else:
                    # Supabase returned no body — reconstruct minimally.
                    holding = {**new_h, "symbol": sym, "name": new_h["name"]}
                    decrypt_fields(holding, ENCRYPTED_FIELDS)
                holdings_created += 1
            except Exception as e:
                logger.warning("import-txn create holding %s failed: %s", sym, e)
                continue
            holdings_by_sym[sym] = holding

        holding_id = holding["id"]

        # ── Pre-fetch existing transactions for dedupe ────────────
        # Two-tier dedupe:
        #   1. Strong: broker's order_ref (unique per execution) —
        #      handles cases where 4 same-day same-qty same-price
        #      trades are genuinely 4 distinct executions, which the
        #      old (action,date,qty,price,amount) tuple collapsed
        #      into one.
        #   2. Legacy: (action, date, qty, price, amount) — for
        #      transactions imported before order_ref tracking
        #      existed, AND for CSVs that don't carry an order_ref
        #      column.
        # On import, a new row is skipped if EITHER its order_ref
        # matches an existing one OR its legacy tuple matches one
        # without an order_ref.
        existing_txns = get("portfolio_transactions", params={
            "holding_id": f"eq.{holding_id}",
            "user_id": f"eq.{user_id}",
            "is_deleted": "is.false",
            "select": "txn_type,txn_date,quantity,price,amount,order_ref",
            "limit": "5000",
        }) or []
        seen_refs: set[str] = set()
        seen_legacy: set[tuple] = set()
        for t in existing_txns:
            ref = (t.get("order_ref") or "").strip()
            if ref:
                seen_refs.add(ref)
            else:
                seen_legacy.add((
                    (t.get("txn_type") or "").lower(),
                    t.get("txn_date") or "",
                    round(float(t.get("quantity") or 0), 4),
                    round(float(t.get("price") or 0), 4),
                    round(float(t.get("amount") or 0), 2),
                ))

        # ── Insert each ledger row ────────────────────────────────
        for r in group:
            action = (r.get("action") or "").strip().lower()
            if action not in ("buy", "sell"):
                continue
            try:
                qty = float(r.get("quantity") or 0)
                price = float(r.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if qty <= 0 or price <= 0:
                continue

            date_iso = _parse_dmy_or_iso(r.get("txn_date"))
            if not date_iso:
                continue

            # Brokerage + statutory charges. Buys cost more; sells net
            # less. Folding them into the cashflow makes XIRR honest.
            try:
                fees = (
                    float(r.get("brokerage") or 0)
                    + float(r.get("charges") or 0)
                )
            except (TypeError, ValueError):
                fees = 0.0
            base = qty * price
            amount = round(base + fees, 2) if action == "buy" else round(base - fees, 2)

            order_ref = (r.get("order_ref") or "").strip() or None
            legacy_key = (action, date_iso, round(qty, 4), round(price, 4), amount)
            # Strong-match first: broker's unique trade ID. If we
            # already have a transaction with this order_ref, it's
            # an exact duplicate.
            if order_ref and order_ref in seen_refs:
                txn_skipped += 1
                continue
            # Legacy-match: only against existing rows that don't
            # have an order_ref (pre-tracking imports). Don't reject
            # against newly-inserted rows in this batch, since with
            # order_refs present they're definitionally distinct.
            if not order_ref and legacy_key in seen_legacy:
                txn_skipped += 1
                continue
            if order_ref:
                seen_refs.add(order_ref)
            else:
                seen_legacy.add(legacy_key)

            txn = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "holding_id": holding_id,
                "txn_type": action,
                "txn_date": date_iso,
                "quantity": qty,
                "price": price,
                "amount": amount,
                "notes": (r.get("notes") or "").strip() or None,
                "order_ref": order_ref,
            }
            try:
                post("portfolio_transactions", txn)
                txn_inserted += 1
            except Exception as e:
                logger.warning(
                    "import-txn insert (sym=%s, date=%s) failed: %s",
                    sym, date_iso, e,
                )

        # ── Recompute holding's quantity + WAC from full ledger ───
        all_txns = get("portfolio_transactions", params={
            "holding_id": f"eq.{holding_id}",
            "user_id": f"eq.{user_id}",
            "is_deleted": "is.false",
            "select": "txn_type,txn_date,quantity,price,created_at",
            "limit": "10000",
        }) or []
        new_qty, new_avg, first_buy = _replay_to_position(all_txns)

        patch = {
            "quantity": round(new_qty, 4),
            "avg_price": round(new_avg, 4),
        }
        if first_buy and not holding.get("buy_date"):
            patch["buy_date"] = first_buy

        try:
            update(
                "portfolio_holdings",
                params={"id": f"eq.{holding_id}", "user_id": f"eq.{user_id}"},
                json=patch,
            )
        except Exception as e:
            logger.warning("import-txn update holding %s failed: %s", sym, e)

    return jsonify({
        "status": "ok",
        "txn_inserted": txn_inserted,
        "txn_skipped_dupe": txn_skipped,
        "holdings_created": holdings_created,
        "holdings_undeleted": holdings_undeleted,
        "holdings_touched": len(by_symbol),
    })


# ═══════════════════════════════════════════════════
# SYMBOL SEARCH + LIVE PRICE APIs (no API key needed)
# ═══════════════════════════════════════════════════

import requests as http_requests

@portfolio_bp.route("/api/portfolio/search-stock")
@login_required
def search_stock():
    """Search Yahoo Finance for stock ticker by name. Returns top matches."""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])

    try:
        r = http_requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 8, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.ok:
            data = r.json()
            results = []
            for item in data.get("quotes", []):
                results.append({
                    "symbol": item.get("symbol", ""),
                    "name": item.get("shortname") or item.get("longname", ""),
                    "exchange": item.get("exchange", ""),
                    "type": item.get("quoteType", ""),
                })
            return jsonify(results)
    except Exception as e:
        logger.warning("Yahoo search failed: %s", e)

    return jsonify([])


@portfolio_bp.route("/api/portfolio/search-mf")
@login_required
def search_mf():
    """Search AMFI for mutual fund schemes by name."""
    q = request.args.get("q", "").strip().lower()
    if not q or len(q) < 3:
        return jsonify([])

    try:
        r = http_requests.get(
            f"https://api.mfapi.in/mf/search?q={q}",
            timeout=5,
        )
        if r.ok:
            data = r.json()
            # Returns list of {schemeCode, schemeName}
            results = [
                {"symbol": str(item.get("schemeCode", "")),
                 "name": item.get("schemeName", "")}
                for item in (data if isinstance(data, list) else [])[:10]
            ]
            return jsonify(results)
    except Exception as e:
        logger.warning("AMFI search failed: %s", e)

    return jsonify([])


@portfolio_bp.route("/api/portfolio/quote/<symbol>")
@login_required
def get_quote(symbol):
    """Fetch live price from Yahoo Finance for a single symbol."""
    try:
        r = http_requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "1d"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.ok:
            data = r.json()
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            return jsonify({
                "symbol": symbol,
                "price": meta.get("regularMarketPrice"),
                "prev_close": meta.get("previousClose"),
                "currency": meta.get("currency", "INR"),
                "name": meta.get("shortName", ""),
            })
    except Exception as e:
        logger.warning("Yahoo quote failed for %s: %s", symbol, e)

    return jsonify({"symbol": symbol, "price": None})


@portfolio_bp.route("/api/portfolio/mf-nav/<scheme_code>")
@login_required
def get_mf_nav(scheme_code):
    """Fetch latest NAV from AMFI for a mutual fund scheme code."""
    try:
        r = http_requests.get(
            f"https://api.mfapi.in/mf/{scheme_code}/latest",
            timeout=5,
        )
        if r.ok:
            data = r.json()
            nav_data = data.get("data", [{}])
            if nav_data:
                return jsonify({
                    "scheme_code": scheme_code,
                    "nav": float(nav_data[0].get("nav", 0)),
                    "date": nav_data[0].get("date", ""),
                    "name": data.get("meta", {}).get("scheme_name", ""),
                })
    except Exception as e:
        logger.warning("AMFI NAV failed for %s: %s", scheme_code, e)

    return jsonify({"scheme_code": scheme_code, "nav": None})


@portfolio_bp.route("/api/portfolio/stock-info/<symbol>")
@login_required
def stock_info(symbol):
    """Fetch sector/industry from Yahoo Finance for a stock symbol."""
    try:
        yf_symbol = symbol if "." in symbol else f"{symbol}.NS"
        r = http_requests.get(
            f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{yf_symbol}",
            params={"modules": "assetProfile,price"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.ok:
            data = r.json().get("quoteSummary", {}).get("result", [{}])[0]
            profile = data.get("assetProfile", {})
            price = data.get("price", {})
            return jsonify({
                "sector": profile.get("sector", ""),
                "industry": profile.get("industry", ""),
                "name": price.get("shortName") or price.get("longName", ""),
                "price": price.get("regularMarketPrice", {}).get("raw"),
            })
    except Exception as e:
        logger.warning("Yahoo stock-info failed for %s: %s", symbol, e)

    return jsonify({"sector": None})


@portfolio_bp.route("/api/portfolio/refresh-prices", methods=["POST"])
@login_required
def refresh_all_prices():
    """Fetch live prices for ALL holdings and update DB."""
    user_id = session["user_id"]
    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    }) or []

    decrypt_rows(holdings, ENCRYPTED_FIELDS)

    updated = 0
    for h in holdings:
        symbol = h.get("symbol")
        asset_type = h.get("asset_type", "stock")
        if not symbol:
            continue

        price = None
        try:
            if asset_type == "mf":
                # AMFI NAV
                r = http_requests.get(f"https://api.mfapi.in/mf/{symbol}/latest", timeout=5)
                if r.ok:
                    nav_data = r.json().get("data", [{}])
                    if nav_data:
                        price = float(nav_data[0].get("nav", 0))
            else:
                # Prefer the resolved Yahoo ticker (e.g. "NTPC.NS",
                # "OIL.NS") over the broker's internal short code,
                # which Yahoo mostly doesn't recognise. Fall back to
                # symbol+.NS for un-resolved rows so the existing
                # workflow still works.
                yf_symbol = (h.get("yahoo_symbol") or "").strip() or symbol
                if asset_type in ("stock", "etf") and not any(s in yf_symbol for s in [".NS", ".BO", "."]):
                    yf_symbol = f"{yf_symbol}.NS"  # Default to NSE

                r = http_requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_symbol}",
                    params={"interval": "1d", "range": "1d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5,
                )
                if r.ok:
                    meta = r.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                    price = meta.get("regularMarketPrice")

            if price and price > 0:
                update("portfolio_holdings",
                       params={"id": f"eq.{h['id']}", "user_id": f"eq.{user_id}"},
                       json={"current_price": float(price)})
                updated += 1
        except Exception as e:
            logger.warning("Price refresh failed for %s: %s", symbol, e)

    return jsonify({"status": "ok", "updated": updated, "total": len(holdings)})


# ═══════════════════════════════════════════════════
# CLEANUP — orphan placeholder holdings
# ═══════════════════════════════════════════════════
#
# The earlier date-parsing bug created a holdings row before the
# date check failed, so users ended up with phantom rows that
# have quantity=0 AND zero transactions. They aren't recoverable
# (no data backs them) so it's safe to hard-delete. This is
# distinct from "closed positions" (qty=0 but transactions exist)
# which represent real history and stay.

@portfolio_bp.route("/api/portfolio/purge-bad-snapshots", methods=["POST"])
@login_required
def purge_bad_snapshots():
    """Hard-delete snapshots with absurd XIRR values (|xirr| > 1000%)
    or with NaN/Inf-looking magnitudes. The previous _xirr could
    return rates like 1.7×10^14% on imbalanced cashflows; those got
    stored in portfolio_snapshots and now poison the trend chart.
    Re-running daily snapshots after the _xirr fix produces sane
    values, so removing the bad ones lets the chart recover."""
    user_id = session["user_id"]
    rows = get("portfolio_snapshots", params={
        "user_id": f"eq.{user_id}",
        "select": "id,xirr,current_value,invested",
        "limit": "100000",
    }) or []

    bad_ids = []
    for r in rows:
        xirr = r.get("xirr")
        try:
            if xirr is not None and (
                abs(float(xirr)) > 1000.0 or float(xirr) != float(xirr)
            ):
                bad_ids.append(r["id"])
                continue
        except (TypeError, ValueError):
            bad_ids.append(r["id"])
            continue
        # Same sanity check on stored value/invested. Column names
        # match the schema (current_value, invested), NOT the
        # earlier total_value / total_invested I'd typed by mistake.
        for k in ("current_value", "invested"):
            v = r.get(k)
            try:
                if v is not None and abs(float(v)) > 1e12:
                    bad_ids.append(r["id"])
                    break
            except (TypeError, ValueError):
                bad_ids.append(r["id"])
                break

    purged = 0
    for sid in bad_ids:
        try:
            delete("portfolio_snapshots", params={
                "id": f"eq.{sid}",
                "user_id": f"eq.{user_id}",
            })
            purged += 1
        except Exception as e:
            logger.warning("purge_bad_snapshots delete %s failed: %s", sid, e)

    return jsonify({
        "ok": True,
        "examined": len(rows),
        "purged": purged,
    })


@portfolio_bp.route("/api/portfolio/sync-deleted-txns", methods=["POST"])
@login_required
def sync_deleted_transactions():
    """One-shot reconciliation: for every soft-deleted holding, mark
    its transactions soft-deleted too. Older versions of delete_holding
    only flipped is_deleted on the holdings row, leaving orphan
    transactions that kept inflating summary/XIRR even after the
    holdings vanished from the table. The cleanup-empty button calls
    this implicitly so the user has a single 'fix everything' path."""
    user_id = session["user_id"]

    deleted_holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.true",
        "select": "id",
        "limit": "5000",
    }) or []
    if not deleted_holdings:
        return jsonify({"ok": True, "fixed": 0, "deleted_holdings": 0})

    fixed = 0
    now_iso = user_now().isoformat()
    for h in deleted_holdings:
        try:
            update(
                "portfolio_transactions",
                params={
                    "holding_id": f"eq.{h['id']}",
                    "user_id": f"eq.{user_id}",
                    "is_deleted": "is.false",
                },
                json={"is_deleted": True, "deleted_at": now_iso},
            )
            fixed += 1
        except Exception as e:
            logger.warning("sync_deleted_txns %s failed: %s", h["id"], e)

    return jsonify({
        "ok": True,
        "deleted_holdings": len(deleted_holdings),
        "fixed": fixed,
    })


@portfolio_bp.route("/api/portfolio/cleanup-empty", methods=["POST"])
@login_required
def cleanup_empty_holdings():
    user_id = session["user_id"]

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "id,symbol,quantity",
        "limit": "5000",
    }) or []

    candidates = [
        h for h in holdings
        if not float(h.get("quantity") or 0)
    ]

    purged = 0
    for h in candidates:
        # Only remove if there are no real transactions backing this
        # holding. A separate count call per candidate is wasteful at
        # scale but the candidate list is usually <100 — fine.
        txns = get("portfolio_transactions", params={
            "holding_id": f"eq.{h['id']}",
            "user_id": f"eq.{user_id}",
            "is_deleted": "is.false",
            "select": "id",
            "limit": "1",
        }) or []
        if txns:
            continue
        try:
            delete("portfolio_holdings", params={
                "id": f"eq.{h['id']}",
                "user_id": f"eq.{user_id}",
            })
            purged += 1
        except Exception as e:
            logger.warning(
                "cleanup_empty delete %s failed: %s", h.get("symbol"), e,
            )

    return jsonify({
        "ok": True,
        "examined_zero_qty": len(candidates),
        "purged": purged,
        "kept_with_history": len(candidates) - purged,
    })


# ═══════════════════════════════════════════════════
# YAHOO SYMBOL RESOLUTION
# ═══════════════════════════════════════════════════
#
# ICICI Direct's tradeBook export uses internal short codes
# (OILIND, STEWIL, JKCEME, HINDAL, ...) that mostly don't map
# 1:1 onto Yahoo Finance tickers (OIL.NS, JKCEMENT.NS,
# HINDALCO.NS, ...). This endpoint walks every holding without
# a yahoo_symbol, asks Yahoo Search to find the closest NSE/BSE
# ticker for that code, and caches the result.
#
# Conservative match rules:
#   1. Exact-symbol hit on .NS or .BO wins immediately.
#   2. Otherwise pick the top quoteType=EQUITY result on NSE
#      ("NSI" exchange in Yahoo's data), falling back to BSE.
#   3. Skip the holding if neither rule matches — better to
#      leave yahoo_symbol NULL and have the user fix it
#      manually than guess a wrong company.

def _yahoo_search(query: str) -> list:
    try:
        r = http_requests.get(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": 10, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        if not r.ok:
            return []
        return r.json().get("quotes", []) or []
    except Exception as e:
        logger.warning("yahoo_search %r failed: %s", query, e)
        return []


def _pick_indian_quote(quotes: list, original_symbol: str) -> dict | None:
    """Pick the best NSE/BSE result from a Yahoo search response.

    Yahoo encodes NSE as 'NSI' and BSE as 'BSE' in the `exchange`
    field. We prefer NSE because most Indian retail traders track
    NSE prices, and ICICI's NSE code usually has higher liquidity.
    Equity-only filter avoids picking up futures/options listings
    that share the underlying name."""
    if not quotes:
        return None
    nse, bse = [], []
    sym_upper = (original_symbol or "").upper()
    for q in quotes:
        if (q.get("quoteType") or "").upper() != "EQUITY":
            continue
        ex = (q.get("exchange") or "").upper()
        sym = (q.get("symbol") or "").upper()
        # Exact-symbol hit on either exchange — strongest signal.
        if sym == f"{sym_upper}.NS" or sym == f"{sym_upper}.BO":
            return q
        if ex == "NSI":
            nse.append(q)
        elif ex == "BSE":
            bse.append(q)
    return (nse or bse or [None])[0]


@portfolio_bp.route("/api/portfolio/resolve-symbols", methods=["POST"])
@login_required
def resolve_symbols():
    """Look up Yahoo tickers for stock/ETF holdings whose
    yahoo_symbol is NULL. One Yahoo search call per holding.

    Body (optional): {"force": true} — re-resolves even rows that
    already have a yahoo_symbol, useful when the user suspects a
    wrong match was cached."""
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force"))

    rows = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "id,symbol,yahoo_symbol,asset_type,name",
        "limit": "5000",
    }) or []
    decrypt_rows(rows, ENCRYPTED_FIELDS)

    resolved = 0
    skipped_already = 0
    skipped_no_match = 0
    examined = 0

    for h in rows:
        asset_type = (h.get("asset_type") or "stock").lower()
        if asset_type not in ("stock", "etf"):
            continue   # MFs use AMFI scheme codes; not Yahoo
        sym = (h.get("symbol") or "").strip()
        if not sym:
            continue
        if h.get("yahoo_symbol") and not force:
            skipped_already += 1
            continue
        examined += 1

        # Try the broker code first; if Yahoo doesn't recognise it
        # and a name exists, fall back to a name search.
        quotes = _yahoo_search(sym)
        picked = _pick_indian_quote(quotes, sym)
        if not picked and h.get("name") and h["name"] != sym:
            quotes = _yahoo_search(h["name"])
            picked = _pick_indian_quote(quotes, sym)

        if not picked or not picked.get("symbol"):
            skipped_no_match += 1
            continue

        try:
            update(
                "portfolio_holdings",
                params={"id": f"eq.{h['id']}", "user_id": f"eq.{user_id}"},
                json={"yahoo_symbol": picked["symbol"]},
            )
            resolved += 1
        except Exception as e:
            logger.warning("resolve_symbols update %s failed: %s", sym, e)

    return jsonify({
        "ok": True,
        "examined": examined,
        "resolved": resolved,
        "skipped_already_resolved": skipped_already,
        "skipped_no_match": skipped_no_match,
    })


# ═══════════════════════════════════════════════════
# BULK PRICE UPDATE
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/update-prices", methods=["POST"])
@login_required
def update_prices():
    """Update current_price for multiple holdings at once."""
    data = request.get_json() or {}
    prices = data.get("prices", {})  # {holding_id: new_price}

    user_id = session["user_id"]
    updated = 0

    for hid, price in prices.items():
        try:
            update("portfolio_holdings",
                   params={"id": f"eq.{hid}", "user_id": f"eq.{user_id}"},
                   json={"current_price": float(price)})
            updated += 1
        except Exception:
            pass

    return jsonify({"status": "ok", "updated": updated})


# ═══════════════════════════════════════════════════
# TRANSACTIONS (buy/sell/dividend log for XIRR)
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/transactions/latest", methods=["GET"])
@login_required
def latest_transactions():
    """Return the most recent transaction per holding for the current user."""
    user_id = session["user_id"]

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "order": "txn_date.desc",
    }) or []

    # Keep only the first (latest) per holding_id
    result = {}
    for t in txns:
        hid = t.get("holding_id")
        if hid and hid not in result:
            result[hid] = {
                "txn_type": t.get("txn_type"),
                "txn_date": t.get("txn_date"),
                "amount": t.get("amount"),
                "quantity": t.get("quantity"),
            }

    return jsonify(result)


@portfolio_bp.route("/api/portfolio/transactions/<holding_id>", methods=["GET"])
@login_required
def list_transactions(holding_id):
    rows = get("portfolio_transactions", params={
        "holding_id": f"eq.{holding_id}",
        "user_id": f"eq.{session['user_id']}",
        "order": "txn_date.desc",
        "limit": 100,
    }) or []
    return jsonify(rows)


@portfolio_bp.route("/api/portfolio/transactions", methods=["POST"])
@login_required
def add_transaction():
    data = request.get_json() or {}
    holding_id = data.get("holding_id")
    if not holding_id:
        return jsonify({"error": "holding_id required"}), 400

    txn = {
        "id": str(uuid.uuid4()),
        "user_id": session["user_id"],
        "holding_id": holding_id,
        "txn_type": data.get("txn_type", "buy"),
        "txn_date": data.get("txn_date") or user_today().isoformat(),
        "quantity": float(data["quantity"]) if data.get("quantity") else 0,
        "price": float(data["price"]) if data.get("price") else 0,
        "amount": float(data["amount"]) if data.get("amount") else None,
        "notes": (data.get("notes") or "").strip() or None,
    }

    # Auto-calc amount if not provided
    if not txn["amount"] and txn["quantity"] and txn["price"]:
        txn["amount"] = round(txn["quantity"] * txn["price"], 2)

    rows = post("portfolio_transactions", txn)
    return jsonify(rows[0] if rows else txn)


@portfolio_bp.route("/api/portfolio/transactions/<txn_id>", methods=["DELETE"])
@login_required
def delete_transaction(txn_id):
    # Transactions feed XIRR; hard-deleting would silently change historical returns.
    update(
        "portfolio_transactions",
        params={"id": f"eq.{txn_id}", "user_id": f"eq.{session['user_id']}"},
        json={"is_deleted": True, "deleted_at": user_now().isoformat()},
    )
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════
# XIRR CALCULATION
# ═══════════════════════════════════════════════════

_XIRR_RATE_MIN = -0.99       # rates ≤ -100% are mathematical garbage
_XIRR_RATE_MAX = 10.0        # 1000% annualised — anything beyond is divergence
_XIRR_RESIDUAL_TOL = 0.001   # |NPV| / |gross cashflow| must fall below this


def _xirr(cashflows):
    """Compute XIRR (annualised IRR) and return as percent (12.5 = 12.5%).
    Returns None when the cashflows can't yield a meaningful rate.

    Defensive — without these guards Newton's method on pathological
    inputs (e.g., post-deletion state with sells but no buys, or
    cashflows that don't bracket a sign change) returned rates like
    1.7×10^14 % which then poisoned every downstream chart.

    Three guards:
      1. Sign check — XIRR is undefined when all cashflows are
         same-sign. Return None.
      2. Bounded Newton — the guess is clamped to [-99%, 1000%]
         every step, with a numerical derivative (more stable near
         the rate=-1 asymptote).
      3. Residual check — at the "converged" rate, |NPV| must be
         small relative to total cashflow magnitude. If not, fall
         back to bisection over the bounded range; if bisection
         can't bracket either, return None.
    """
    if len(cashflows) < 2:
        return None

    cashflows = sorted(cashflows, key=lambda x: x[0])

    # Guard 1: sign check.
    has_pos = any(amt > 0 for _, amt in cashflows)
    has_neg = any(amt < 0 for _, amt in cashflows)
    if not (has_pos and has_neg):
        return None

    abs_total = sum(abs(amt) for _, amt in cashflows)
    if abs_total <= 0:
        return None

    d0 = cashflows[0][0]

    def _days(d):
        return (d - d0).days

    def _npv(rate):
        try:
            base = 1.0 + rate
            if base <= 0:
                return float("inf")
            return sum(amt / base ** (_days(d) / 365.0) for d, amt in cashflows)
        except (ZeroDivisionError, OverflowError, ValueError):
            return float("inf")

    # Guard 2: bounded Newton with numerical derivative.
    guess = 0.1
    for _ in range(100):
        npv = _npv(guess)
        if not isinstance(npv, (int, float)) or npv != npv or npv == float("inf"):
            break
        h = 1e-6
        dnpv = (_npv(guess + h) - npv) / h
        if dnpv != dnpv or abs(dnpv) < 1e-12:
            break
        new_guess = guess - npv / dnpv
        if new_guess < _XIRR_RATE_MIN:
            new_guess = _XIRR_RATE_MIN
        elif new_guess > _XIRR_RATE_MAX:
            new_guess = _XIRR_RATE_MAX
        if abs(new_guess - guess) < 1e-9:
            guess = new_guess
            break
        guess = new_guess

    # Guard 3: residual check; bisect on failure.
    if abs(_npv(guess)) > _XIRR_RESIDUAL_TOL * abs_total:
        lo, hi = _XIRR_RATE_MIN, _XIRR_RATE_MAX
        f_lo, f_hi = _npv(lo), _npv(hi)
        if f_lo == float("inf") or f_hi == float("inf") or f_lo * f_hi > 0:
            return None
        for _ in range(80):
            mid = (lo + hi) / 2
            f_mid = _npv(mid)
            if f_lo * f_mid < 0:
                hi, f_hi = mid, f_mid
            else:
                lo, f_lo = mid, f_mid
            if hi - lo < 1e-7:
                break
        guess = (lo + hi) / 2
        if abs(_npv(guess)) > _XIRR_RESIDUAL_TOL * abs_total:
            return None

    if not (_XIRR_RATE_MIN <= guess <= _XIRR_RATE_MAX):
        return None

    return round(guess * 100, 2)


@portfolio_bp.route("/api/portfolio/xirr/<holding_id>", methods=["GET"])
@login_required
def holding_xirr(holding_id):
    """Compute XIRR for a single holding from its transactions + current value."""
    user_id = session["user_id"]

    txns = get("portfolio_transactions", params={
        "holding_id": f"eq.{holding_id}",
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "order": "txn_date.asc",
    }) or []

    holding = get("portfolio_holdings", params={
        "id": f"eq.{holding_id}",
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    })
    if not holding:
        return jsonify({"error": "Not found"}), 404

    h = holding[0]
    qty = float(h.get("quantity") or 0)
    cmp = float(h.get("current_price") or h.get("avg_price") or 0)

    cashflows = []
    for t in txns:
        d = date.fromisoformat(t["txn_date"])
        amt = float(t.get("amount") or 0)
        if t["txn_type"] == "buy":
            cashflows.append((d, -abs(amt)))
        elif t["txn_type"] in ("sell", "dividend"):
            cashflows.append((d, abs(amt)))

    # If no transactions, use buy_date + avg_price as single buy
    if not cashflows:
        avg = float(h.get("avg_price") or 0)
        if avg and qty:
            bd = h.get("buy_date") or (h["created_at"][:10] if h.get("created_at") else None)
            buy_dt = date.fromisoformat(bd) if bd else user_today()
            cashflows.append((buy_dt, -(qty * avg)))

    # Add current value as final "sell"
    if qty > 0 and cmp > 0:
        cashflows.append((user_today(), qty * cmp))

    xirr = _xirr(cashflows) if len(cashflows) >= 2 else None

    return jsonify({"xirr": xirr, "cashflows_count": len(cashflows)})


@portfolio_bp.route("/api/portfolio/xirr-breakdown", methods=["GET"])
@login_required
def xirr_breakdown():
    """XIRR grouped by asset_type and sector."""
    user_id = session["user_id"]

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    }) or []

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "order": "txn_date.asc",
    }) or []

    # Group transactions by holding_id
    txn_by_holding = {}
    for t in txns:
        txn_by_holding.setdefault(t["holding_id"], []).append(t)

    today = user_today()
    by_type = {}   # asset_type -> {cashflows}
    by_sector = {} # sector -> {cashflows}
    allocation = {} # asset_type -> current_value

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        avg = float(h.get("avg_price") or 0)
        cmp = float(h.get("current_price") or avg)
        atype = h.get("asset_type", "other")
        sector = h.get("sector") or "Unknown"
        current_val = qty * cmp

        allocation[atype] = allocation.get(atype, 0) + current_val

        # Build cashflows for this holding
        hcf = []
        for t in txn_by_holding.get(h["id"], []):
            d = date.fromisoformat(t["txn_date"])
            amt = float(t.get("amount") or 0)
            if t["txn_type"] == "buy":
                hcf.append((d, -abs(amt)))
            elif t["txn_type"] in ("sell", "dividend"):
                hcf.append((d, abs(amt)))

        if not hcf and avg and qty:
            bd = h.get("buy_date") or (h["created_at"][:10] if h.get("created_at") else None)
            buy_dt = date.fromisoformat(bd) if bd else today
            hcf.append((buy_dt, -(qty * avg)))

        if qty > 0 and cmp > 0:
            hcf.append((today, current_val))

        # Aggregate into type and sector groups
        by_type.setdefault(atype, []).extend(hcf)
        by_sector.setdefault(sector, []).extend(hcf)

    # Calculate XIRR per group
    type_xirr = {}
    for k, cfs in by_type.items():
        x = _xirr(cfs) if len(cfs) >= 2 else None
        type_xirr[k] = x

    sector_xirr = {}
    for k, cfs in by_sector.items():
        x = _xirr(cfs) if len(cfs) >= 2 else None
        sector_xirr[k] = x

    return jsonify({
        "by_type": type_xirr,
        "by_sector": sector_xirr,
        "allocation": {k: round(v, 2) for k, v in allocation.items()},
    })


@portfolio_bp.route("/api/portfolio/xirr", methods=["GET"])
@login_required
def portfolio_xirr():
    """Compute portfolio-level XIRR from all transactions."""
    user_id = session["user_id"]

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "order": "txn_date.asc",
    }) or []

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    }) or []

    cashflows = []

    # All transactions
    for t in txns:
        d = date.fromisoformat(t["txn_date"])
        amt = float(t.get("amount") or 0)
        if t["txn_type"] == "buy":
            cashflows.append((d, -abs(amt)))
        elif t["txn_type"] in ("sell", "dividend"):
            cashflows.append((d, abs(amt)))

    # If no transactions, derive from holdings using buy_date
    if not cashflows:
        for h in holdings:
            qty = float(h.get("quantity") or 0)
            avg = float(h.get("avg_price") or 0)
            if qty and avg:
                bd = h.get("buy_date") or (h["created_at"][:10] if h.get("created_at") else None)
                buy_dt = date.fromisoformat(bd) if bd else user_today()
                cashflows.append((buy_dt, -(qty * avg)))

    # Current portfolio value as final inflow
    today = user_today()
    total_current = sum(
        float(h.get("quantity") or 0) * float(h.get("current_price") or h.get("avg_price") or 0)
        for h in holdings
    )
    if total_current > 0:
        cashflows.append((today, total_current))

    xirr = _xirr(cashflows) if len(cashflows) >= 2 else None

    return jsonify({"xirr": xirr, "cashflows_count": len(cashflows)})


# ═══════════════════════════════════════════════════
# DAILY SNAPSHOTS (for trend charts)
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/snapshot", methods=["POST"])
@login_required
def take_snapshot():
    """Save today's portfolio values. Called once per day (auto or manual)."""
    user_id = session["user_id"]
    today = user_today().isoformat()

    # Check if snapshot already exists for today
    existing = get("portfolio_snapshots", params={
        "user_id": f"eq.{user_id}",
        "snap_date": f"eq.{today}",
        "limit": 1,
    })
    if existing:
        # Delete old snapshot for today (will re-create)
        delete("portfolio_snapshots", params={
            "user_id": f"eq.{user_id}",
            "snap_date": f"eq.{today}",
        })

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    }) or []

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "order": "txn_date.asc",
    }) or []

    txn_by_holding = {}
    for t in txns:
        txn_by_holding.setdefault(t["holding_id"], []).append(t)

    today_date = user_today()

    # Aggregate by type and sector
    by_type = {}   # type -> {invested, current, cashflows}
    by_sector = {} # sector -> {invested, current, cashflows}
    total_invested = 0
    total_current = 0

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        avg = float(h.get("avg_price") or 0)
        cmp = float(h.get("current_price") or avg)
        invested = qty * avg
        current_val = qty * cmp
        atype = h.get("asset_type", "other")
        sector = h.get("sector") or "Unknown"

        total_invested += invested
        total_current += current_val

        for key, group in [(atype, by_type), (sector, by_sector)]:
            if key not in group:
                group[key] = {"invested": 0, "current": 0, "cashflows": []}
            group[key]["invested"] += invested
            group[key]["current"] += current_val

            # Build cashflows for XIRR
            for t in txn_by_holding.get(h["id"], []):
                d = date.fromisoformat(t["txn_date"])
                amt = float(t.get("amount") or 0)
                if t["txn_type"] == "buy":
                    group[key]["cashflows"].append((d, -abs(amt)))
                elif t["txn_type"] in ("sell", "dividend"):
                    group[key]["cashflows"].append((d, abs(amt)))

            if not txn_by_holding.get(h["id"]) and avg and qty:
                bd = h.get("buy_date") or (h["created_at"][:10] if h.get("created_at") else None)
                buy_dt = date.fromisoformat(bd) if bd else today_date
                group[key]["cashflows"].append((buy_dt, -(qty * avg)))

            if qty > 0 and cmp > 0:
                group[key]["cashflows"].append((today_date, current_val))

    # Calculate overall XIRR
    all_cashflows = []
    for g in by_type.values():
        all_cashflows.extend(g["cashflows"])
    overall_xirr = _xirr(all_cashflows) if len(all_cashflows) >= 2 else None

    # Save snapshot rows
    rows = []

    # Overall row
    rows.append({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "snap_date": today,
        "group_type": "overall",
        "group_name": "overall",
        "invested": round(total_invested, 2),
        "current_value": round(total_current, 2),
        "xirr": overall_xirr,
    })

    # Per asset type
    for k, v in by_type.items():
        x = _xirr(v["cashflows"]) if len(v["cashflows"]) >= 2 else None
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "snap_date": today,
            "group_type": "asset_type",
            "group_name": k,
            "invested": round(v["invested"], 2),
            "current_value": round(v["current"], 2),
            "xirr": x,
        })

    # Per sector
    for k, v in by_sector.items():
        x = _xirr(v["cashflows"]) if len(v["cashflows"]) >= 2 else None
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "snap_date": today,
            "group_type": "sector",
            "group_name": k,
            "invested": round(v["invested"], 2),
            "current_value": round(v["current"], 2),
            "xirr": x,
        })

    for row in rows:
        try:
            post("portfolio_snapshots", row)
        except Exception as e:
            logger.warning("Snapshot row failed: %s", e)

    return jsonify({"status": "ok", "rows_saved": len(rows), "date": today})


@portfolio_bp.route("/api/portfolio/backfill-snapshots", methods=["POST"])
@login_required
def backfill_snapshots():
    """Fill missing snapshot days by copying the last known snapshot forward."""
    user_id = session["user_id"]
    today = user_today()

    # Get all existing snapshot dates (overall only, to detect gaps)
    existing = get("portfolio_snapshots", params={
        "user_id": f"eq.{user_id}",
        "group_type": "eq.overall",
        "order": "snap_date.asc",
        "select": "snap_date",
    }) or []

    if not existing:
        return jsonify({"status": "ok", "filled": 0})

    existing_dates = set(r["snap_date"] for r in existing)
    first_date = date.fromisoformat(existing[0]["snap_date"])

    # Find all missing dates between first snapshot and today
    from datetime import timedelta as td
    missing = []
    d = first_date + td(days=1)
    while d <= today:
        if d.isoformat() not in existing_dates:
            missing.append(d)
        d += td(days=1)

    if not missing:
        return jsonify({"status": "ok", "filled": 0})

    # Get ALL snapshots to use as source for forward-fill
    all_snaps = get("portfolio_snapshots", params={
        "user_id": f"eq.{user_id}",
        "order": "snap_date.asc",
    }) or []

    # Index by (date, group_type, group_name)
    snap_by_date = {}
    for s in all_snaps:
        snap_by_date.setdefault(s["snap_date"], []).append(s)

    filled = 0
    last_known_rows = []

    # Walk through all dates from first to today
    d = first_date
    while d <= today:
        ds = d.isoformat()
        if ds in snap_by_date:
            last_known_rows = snap_by_date[ds]
        elif last_known_rows and ds in [m.isoformat() for m in missing]:
            # Copy last known rows with new date
            for src in last_known_rows:
                try:
                    post("portfolio_snapshots", {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "snap_date": ds,
                        "group_type": src["group_type"],
                        "group_name": src["group_name"],
                        "invested": src.get("invested"),
                        "current_value": src.get("current_value"),
                        "xirr": src.get("xirr"),
                    })
                    filled += 1
                except Exception:
                    pass
        d += td(days=1)

    return jsonify({"status": "ok", "filled": filled})


@portfolio_bp.route("/api/portfolio/cron-snapshot", methods=["POST"])
def cron_snapshot():
    """Called by external cron service (cron-job.org, etc.) to snapshot ALL users.
    Requires CRON_SECRET header for auth (set in .env)."""
    import os
    secret = os.environ.get("CRON_SECRET", "")
    import hmac
    # Constant-time compare, so the secret cannot be guessed byte by byte
    # from response timing.
    if not secret or not hmac.compare_digest(
            (request.headers.get("X-Cron-Secret") or "").encode(), secret.encode()):
        return jsonify({"error": "Unauthorized"}), 401

    # Get all distinct user_ids that have holdings
    all_holdings = get("portfolio_holdings", params={
        "select": "user_id",
    }) or []

    user_ids = list(set(h["user_id"] for h in all_holdings))
    today = user_today().isoformat()
    total = 0

    for uid in user_ids:
        # Check if already snapshotted today
        existing = get("portfolio_snapshots", params={
            "user_id": f"eq.{uid}",
            "snap_date": f"eq.{today}",
            "group_type": "eq.overall",
            "limit": 1,
        })
        if existing:
            continue

        # Simulate a snapshot for this user by calling the logic directly
        holdings = get("portfolio_holdings", params={
            "user_id": f"eq.{uid}",
            "is_deleted": "is.false",
        }) or []
        if not holdings:
            continue

        txns = get("portfolio_transactions", params={
            "user_id": f"eq.{uid}",
            "is_deleted": "is.false",
            "order": "txn_date.asc",
        }) or []
        txn_by_holding = {}
        for t in txns:
            txn_by_holding.setdefault(t["holding_id"], []).append(t)

        today_date = user_today()
        total_invested = 0
        total_current = 0
        by_type = {}
        all_cf = []

        for h in holdings:
            qty = float(h.get("quantity") or 0)
            avg = float(h.get("avg_price") or 0)
            cmp = float(h.get("current_price") or avg)
            invested = qty * avg
            current_val = qty * cmp
            atype = h.get("asset_type", "other")

            total_invested += invested
            total_current += current_val

            if atype not in by_type:
                by_type[atype] = {"invested": 0, "current": 0, "cf": []}
            by_type[atype]["invested"] += invested
            by_type[atype]["current"] += current_val

            hcf = []
            for t in txn_by_holding.get(h["id"], []):
                d = date.fromisoformat(t["txn_date"])
                amt = float(t.get("amount") or 0)
                if t["txn_type"] == "buy":
                    hcf.append((d, -abs(amt)))
                else:
                    hcf.append((d, abs(amt)))

            if not hcf and avg and qty:
                bd = h.get("buy_date") or (h["created_at"][:10] if h.get("created_at") else None)
                buy_dt = date.fromisoformat(bd) if bd else today_date
                hcf.append((buy_dt, -(qty * avg)))

            if qty > 0 and cmp > 0:
                hcf.append((today_date, current_val))

            by_type[atype]["cf"].extend(hcf)
            all_cf.extend(hcf)

        # Save overall
        overall_xirr = _xirr(all_cf) if len(all_cf) >= 2 else None
        try:
            post("portfolio_snapshots", {
                "id": str(uuid.uuid4()), "user_id": uid, "snap_date": today,
                "group_type": "overall", "group_name": "overall",
                "invested": round(total_invested, 2),
                "current_value": round(total_current, 2), "xirr": overall_xirr,
            })
        except Exception:
            pass

        for k, v in by_type.items():
            x = _xirr(v["cf"]) if len(v["cf"]) >= 2 else None
            try:
                post("portfolio_snapshots", {
                    "id": str(uuid.uuid4()), "user_id": uid, "snap_date": today,
                    "group_type": "asset_type", "group_name": k,
                    "invested": round(v["invested"], 2),
                    "current_value": round(v["current"], 2), "xirr": x,
                })
            except Exception:
                pass

        total += 1

    return jsonify({"status": "ok", "users_processed": total, "date": today})


@portfolio_bp.route("/api/portfolio/trends", methods=["GET"])
@login_required
def portfolio_trends():
    """Return snapshot history for trend charts. Query params: days=90, group_type=overall|asset_type|sector"""
    user_id = session["user_id"]
    days = int(request.args.get("days", 90))
    group_type = request.args.get("group_type", "overall")

    from datetime import timedelta as td
    from_date = (user_today() - td(days=days)).isoformat()

    rows = get("portfolio_snapshots", params={
        "user_id": f"eq.{user_id}",
        "group_type": f"eq.{group_type}",
        "snap_date": f"gte.{from_date}",
        "order": "snap_date.asc,group_name.asc",
    }) or []

    return jsonify(rows)


# ═══════════════════════════════════════════════════
# PORTFOLIO SUMMARY
# ═══════════════════════════════════════════════════

@portfolio_bp.route("/api/portfolio/summary", methods=["GET"])
@login_required
def portfolio_summary():
    user_id = session["user_id"]

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
    }) or []

    # Pull transactions for the trade-count tile and the "awaiting
    # older buy history" hint. Restricted to active holdings + active
    # transactions so the count matches what the user can actually
    # see in the Coverage page.
    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "txn_type,holding_id,quantity,price,amount",
        "limit": "100000",
    }) or []

    # Group transactions by holding to identify "sells without buys"
    # — those are positions where the user imported recent FY data
    # but the originating buy lives in an earlier un-imported file.
    # Distinct from genuinely closed positions (had buys, sold out).
    # Also track total sold quantity AND value per holding so the UI
    # can show "sold N @ ₹P" in the flag — answers the user's
    # "what did I actually sell?" question without requiring them to
    # open the transactions modal.
    by_holding: dict[str, dict] = {}
    for t in txns:
        hid = t.get("holding_id")
        if not hid:
            continue
        slot = by_holding.setdefault(hid, {
            "buys": 0, "sells": 0,
            "sold_qty": 0.0, "sold_value": 0.0,
        })
        ttype = (t.get("txn_type") or "").lower()
        q = float(t.get("quantity") or 0)
        if ttype == "buy":
            slot["buys"] += 1
        elif ttype == "sell":
            slot["sells"] += 1
            slot["sold_qty"] += q
            # `amount` is the realised cash from the sell (qty*price -
            # fees, fold-in done at import time). Falls back to the raw
            # qty*price if amount wasn't recorded.
            amt = t.get("amount")
            if amt is None:
                amt = q * float(t.get("price") or 0)
            slot["sold_value"] += float(amt or 0)

    sell_only_count = 0
    sell_only_ids: list[str] = []
    sell_only_qty: dict[str, float] = {}
    sell_only_avg: dict[str, float] = {}
    closed_count = 0
    active_holding_ids = {h["id"] for h in holdings}
    for hid in active_holding_ids:
        slot = by_holding.get(hid, {
            "buys": 0, "sells": 0,
            "sold_qty": 0.0, "sold_value": 0.0,
        })
        if slot["sells"] > 0 and slot["buys"] == 0:
            sell_only_count += 1
            sell_only_ids.append(hid)
            sell_only_qty[hid] = round(slot["sold_qty"], 4)
            sell_only_avg[hid] = round(
                slot["sold_value"] / slot["sold_qty"], 2
            ) if slot["sold_qty"] else 0.0

    total_invested = 0
    total_current = 0
    active_count = 0
    by_type = {}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        avg = float(h.get("avg_price") or 0)
        cur = float(h.get("current_price") or avg)
        invested = qty * avg
        current = qty * cur

        total_invested += invested
        total_current += current
        if qty > 0:
            active_count += 1
        else:
            closed_count += 1

        t = h.get("asset_type", "other")
        if t not in by_type:
            by_type[t] = {"invested": 0, "current": 0, "count": 0}
        by_type[t]["invested"] += invested
        by_type[t]["current"] += current
        by_type[t]["count"] += 1

    total_pnl = total_current - total_invested
    total_pnl_pct = round((total_pnl / total_invested * 100), 2) if total_invested else 0

    return jsonify({
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": total_pnl_pct,
        "holdings_count": len(holdings),
        "active_holdings_count": active_count,
        "closed_holdings_count": closed_count,
        "sell_only_count": sell_only_count,
        "sell_only_ids": sell_only_ids,
        "sell_only_qty": sell_only_qty,
        "sell_only_avg": sell_only_avg,
        "transactions_count": len(txns),
        "by_type": by_type,
    })


# ═══════════════════════════════════════════════════
# REALISED P&L — gains/losses on past sells, per-holding + total
# ═══════════════════════════════════════════════════
#
# For every holding, walks its transactions in date order using
# weighted-average cost (WAC). Each Sell crystallises a realised
# gain or loss = (sell_price − running_wac) × sell_qty. Buys
# don't realise anything, just shift the running WAC.
#
# Conservative on incomplete history: if a Sell ever tries to
# pop more units than the running ledger has bought, we mark the
# whole holding as `incomplete_history` and skip its realised P&L
# from the total — better to under-report than to overstate gains
# using a fabricated cost basis.
#
# WAC chosen over FIFO because the holdings table already shows
# avg_price as WAC; mixing methods would make per-row vs per-sell
# numbers confusing. Indian tax filing uses FIFO — that's a
# separate /portfolio/tax-report we can build later.

def _compute_realised(transactions):
    qty = 0.0
    wac = 0.0
    realised = 0.0
    sold_qty = 0.0
    sold_value = 0.0
    sells_count = 0
    incomplete = False

    for t in sorted(
        transactions,
        key=lambda r: (r.get("txn_date") or "", r.get("created_at") or "")
    ):
        action = (t.get("txn_type") or "").lower()
        try:
            q = float(t.get("quantity") or 0)
            p = float(t.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if q <= 0:
            continue

        if action == "buy":
            if qty <= 0:
                qty = q
                wac = p
            else:
                wac = (qty * wac + q * p) / (qty + q)
                qty += q
        elif action == "sell":
            if q > qty + 1e-9:
                # Selling more than we know we own → buys are
                # missing. Stop trying to compute realised P&L
                # for this holding; mark it.
                incomplete = True
                continue
            realised += (p - wac) * q
            sold_qty += q
            sold_value += q * p
            sells_count += 1
            qty -= q
            if qty <= 1e-9:
                qty = 0.0
                wac = 0.0

    return {
        "realised": round(realised, 2),
        "sold_qty": round(sold_qty, 4),
        "avg_sell_price": round(sold_value / sold_qty, 2) if sold_qty else 0.0,
        "sells_count": sells_count,
        "incomplete_history": incomplete,
    }


@portfolio_bp.route("/api/portfolio/realised-pnl", methods=["GET"])
@login_required
def realised_pnl():
    user_id = session["user_id"]

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "id",
        "limit": "5000",
    }) or []
    holding_ids = [h["id"] for h in holdings]

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "holding_id,txn_type,txn_date,quantity,price,created_at",
        "limit": "100000",
    }) or []

    by_holding: dict[str, list] = {}
    for t in txns:
        hid = t.get("holding_id")
        if hid:
            by_holding.setdefault(hid, []).append(t)

    by_holding_out: dict[str, dict] = {}
    total_realised = 0.0
    incomplete_count = 0
    for hid in holding_ids:
        info = _compute_realised(by_holding.get(hid, []))
        if info["sells_count"] == 0:
            continue   # buy-only holdings have nothing realised
        by_holding_out[hid] = info
        if info["incomplete_history"]:
            incomplete_count += 1
        else:
            total_realised += info["realised"]

    return jsonify({
        "total_realised": round(total_realised, 2),
        "by_holding": by_holding_out,
        "incomplete_holdings_count": incomplete_count,
    })


# ═══════════════════════════════════════════════════
# TAX REPORT — FIFO lot matching, STCG vs LTCG split
# ═══════════════════════════════════════════════════
#
# Indian tax law for listed equity uses FIFO: each sell is matched
# against the oldest buy lot first. Holding period > 12 months
# (>365 days) classifies as LTCG; otherwise STCG. The realised P&L
# tile uses WAC for consistency with the avg_price column, but
# WAC numbers don't match what a CA will file — this endpoint
# produces filing-grade lot-level detail.
#
# Doesn't compute the actual tax owed (rates change every budget;
# also depends on 80C / set-off / loss-carry-forward state we
# don't have). Surfaces gross gain per lot + STCG/LTCG totals so
# the user can drop the CSV into their CA's tax software.
#
# Conservative on incomplete history: if a sell exceeds the
# available buy queue, that lot is marked "BUYS-MISSING" instead
# of guessed-at — the user knows to import older FY tradeBooks.

def _fy_label_from_iso(date_iso: str) -> str | None:
    """ISO date → Indian FY label ('2025-26'). Apr-Dec maps to the
    current calendar year; Jan-Mar maps to the previous one."""
    if not date_iso or len(date_iso) < 7 or date_iso[4] != "-":
        return None
    try:
        y, m = int(date_iso[:4]), int(date_iso[5:7])
    except ValueError:
        return None
    fy_start = y if m >= 4 else y - 1
    return f"{fy_start}-{(fy_start + 1) % 100:02d}"


def _fifo_match(transactions):
    """Walk transactions chronologically. Maintain a queue of buy
    lots ({date, qty_remaining, price}). Each sell pops from the
    front, matching FIFO. Returns a list of matched lots, each one
    a dict with buy_date, sell_date, qty, buy_price, sell_price,
    gain, holding_days, classification ('STCG' / 'LTCG' /
    'BUYS-MISSING')."""
    from datetime import date as _date
    lots = []
    queue: list[dict] = []   # buy lots, oldest first
    for t in sorted(
        transactions,
        key=lambda r: (r.get("txn_date") or "", r.get("created_at") or "")
    ):
        action = (t.get("txn_type") or "").lower()
        try:
            q = float(t.get("quantity") or 0)
            p = float(t.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if q <= 0 or not t.get("txn_date"):
            continue

        if action == "buy":
            queue.append({
                "date": t["txn_date"],
                "qty_remaining": q,
                "price": p,
            })
        elif action == "sell":
            sell_date = t["txn_date"]
            try:
                sd = _date.fromisoformat(sell_date)
            except ValueError:
                continue
            remaining = q
            while remaining > 1e-9:
                if not queue:
                    # Buy history missing — record an unmatched lot
                    # so the user sees which sells need older data.
                    lots.append({
                        "buy_date": None,
                        "sell_date": sell_date,
                        "qty": round(remaining, 4),
                        "buy_price": None,
                        "sell_price": p,
                        "gain": None,
                        "holding_days": None,
                        "classification": "BUYS-MISSING",
                    })
                    remaining = 0
                    break
                lot = queue[0]
                matched = min(remaining, lot["qty_remaining"])
                try:
                    bd = _date.fromisoformat(lot["date"])
                    days = (sd - bd).days
                except ValueError:
                    days = 0
                # Listed equity: > 12 months (strictly more than
                # 365 days) is LTCG. Exactly 365 days is STCG.
                cls = "LTCG" if days > 365 else "STCG"
                lots.append({
                    "buy_date": lot["date"],
                    "sell_date": sell_date,
                    "qty": round(matched, 4),
                    "buy_price": round(lot["price"], 4),
                    "sell_price": round(p, 4),
                    "gain": round((p - lot["price"]) * matched, 2),
                    "holding_days": days,
                    "classification": cls,
                })
                lot["qty_remaining"] -= matched
                remaining -= matched
                if lot["qty_remaining"] <= 1e-9:
                    queue.pop(0)
    return lots


@portfolio_bp.route("/portfolio/tax-report", methods=["GET"])
@login_required
def tax_report_page():
    return render_template("portfolio_tax_report.html")


@portfolio_bp.route("/api/portfolio/tax-report", methods=["GET"])
@login_required
def tax_report_api():
    user_id = session["user_id"]
    fy_filter = (request.args.get("fy") or "").strip()   # e.g., "2025-26" or empty for all

    holdings = get("portfolio_holdings", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "id,symbol,name",
        "limit": "5000",
    }) or []
    decrypt_rows(holdings, ENCRYPTED_FIELDS)
    holdings_meta = {h["id"]: h for h in holdings}

    txns = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "holding_id,txn_type,txn_date,quantity,price,created_at",
        "limit": "100000",
    }) or []

    by_holding: dict[str, list] = {}
    for t in txns:
        hid = t.get("holding_id")
        if hid:
            by_holding.setdefault(hid, []).append(t)

    rows = []
    for hid, h in holdings_meta.items():
        for lot in _fifo_match(by_holding.get(hid, [])):
            sell_fy = _fy_label_from_iso(lot["sell_date"])
            if fy_filter and sell_fy != fy_filter:
                continue
            rows.append({
                **lot,
                "symbol": h.get("symbol"),
                "name": h.get("name") or h.get("symbol"),
                "fy": sell_fy,
            })

    # Sort by sell date so the report reads chronologically.
    rows.sort(key=lambda r: (r.get("sell_date") or "", r.get("symbol") or ""))

    # Totals — exclude BUYS-MISSING lots from gain sums.
    stcg_total = round(sum(
        r["gain"] for r in rows
        if r["classification"] == "STCG" and r["gain"] is not None
    ), 2)
    ltcg_total = round(sum(
        r["gain"] for r in rows
        if r["classification"] == "LTCG" and r["gain"] is not None
    ), 2)
    incomplete = sum(1 for r in rows if r["classification"] == "BUYS-MISSING")

    # Indian listed-equity LTCG exemption threshold (effective
    # FY 2024-25 onward; was ₹1L for FY 2018-19 to FY 2023-24).
    LTCG_EXEMPTION = 125000
    ltcg_exempt = min(LTCG_EXEMPTION, max(0, ltcg_total))
    ltcg_taxable = max(0, ltcg_total - LTCG_EXEMPTION)

    # FY list across all matched lots, for the dropdown.
    fy_set = {r["fy"] for r in rows if r["fy"]}
    fys = sorted(fy_set, reverse=True)

    return jsonify({
        "fy": fy_filter or None,
        "available_fys": fys,
        "lots": rows,
        "summary": {
            "stcg_total": stcg_total,
            "ltcg_total": ltcg_total,
            "ltcg_exempt": round(ltcg_exempt, 2),
            "ltcg_taxable": round(ltcg_taxable, 2),
            "ltcg_exemption_cap": LTCG_EXEMPTION,
            "incomplete_lots": incomplete,
            "lot_count": len(rows),
        },
    })


# ═══════════════════════════════════════════════════
# COVERAGE — what years of trade history have been imported
# ═══════════════════════════════════════════════════
#
# We don't keep an explicit upload log (per-row CSV provenance would
# bloat every transaction). Instead we derive coverage from the data
# itself: group existing transactions by Indian financial year
# (Apr 1 → Mar 31) and report counts. Lets the user spot which FYs
# they've already imported and which still need pulling from the
# broker portal.
#
# Missing-FY detection only looks at gaps *within* the existing
# range. We don't know what to expect outside it (the user might
# have legitimately not traded in FY 2014-15), so we don't warn
# about years before the earliest or after the latest.

@portfolio_bp.route("/api/portfolio/coverage", methods=["GET"])
@login_required
def trade_coverage():
    user_id = session["user_id"]
    rows = get("portfolio_transactions", params={
        "user_id": f"eq.{user_id}",
        "is_deleted": "is.false",
        "select": "txn_type,txn_date,amount,holding_id",
        "order": "txn_date.asc",
        "limit": "100000",
    }) or []

    by_fy: dict[str, dict] = {}
    holdings_by_fy: dict[str, set] = {}

    for r in rows:
        d = (r.get("txn_date") or "")[:10]
        if len(d) < 10 or d[4] != "-":
            continue
        try:
            y, m = int(d[0:4]), int(d[5:7])
        except ValueError:
            continue
        # Indian FY: Apr-Dec → current year; Jan-Mar → prev year.
        fy_start = y if m >= 4 else y - 1
        fy_label = f"FY {fy_start}-{(fy_start + 1) % 100:02d}"
        b = by_fy.setdefault(fy_label, {
            "buys": 0, "sells": 0,
            "buy_value": 0.0, "sell_value": 0.0,
            "earliest": d, "latest": d,
            "fy_start": fy_start,
        })
        amt = float(r.get("amount") or 0)
        if (r.get("txn_type") or "").lower() == "buy":
            b["buys"] += 1
            b["buy_value"] += amt
        else:
            b["sells"] += 1
            b["sell_value"] += amt
        if d < b["earliest"]:
            b["earliest"] = d
        if d > b["latest"]:
            b["latest"] = d
        holdings_by_fy.setdefault(fy_label, set()).add(r.get("holding_id"))

    out = []
    for fy_label, b in sorted(by_fy.items(), key=lambda kv: kv[1]["fy_start"]):
        out.append({
            "fy": fy_label,
            "buys": b["buys"],
            "sells": b["sells"],
            "total": b["buys"] + b["sells"],
            "buy_value": round(b["buy_value"], 2),
            "sell_value": round(b["sell_value"], 2),
            "earliest": b["earliest"],
            "latest": b["latest"],
            "symbols": len(holdings_by_fy[fy_label]),
        })

    # Internal-gap detection: if the user has FY 2018-19 and FY 2020-21
    # but not FY 2019-20, that's almost certainly a missing import (you
    # don't usually skip a whole year of trading).
    missing = []
    if out:
        present = {int(r["fy"].split()[1].split("-")[0]) for r in out}
        first_fy = min(present)
        last_fy = max(present)
        for fy in range(first_fy, last_fy + 1):
            if fy not in present:
                missing.append(f"FY {fy}-{(fy + 1) % 100:02d}")

    return jsonify({
        "total_transactions": len(rows),
        "by_fy": out,
        "missing_internal_fys": missing,
    })


@portfolio_bp.route("/portfolio/coverage", methods=["GET"])
@login_required
def coverage_page():
    return render_template("portfolio_coverage.html")
