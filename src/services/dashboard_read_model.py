"""Single authoritative dashboard read model (audit PR4 / P1.7).

Every dashboard API endpoint (`/api/dashboard/metrics`, `/api/dashboard/metrics/enhanced`,
`/api/trades/recent`) reads through THIS module so they can never disagree.

Authoritative sources (and nothing else):
  * cache.sqlite `closed_trades`  — recent window + session detail (read-only, ephemeral)
  * server_local_backups/paper_adaptive_learning_state.json — lifetime + durable fallback
  * data/paper_open_positions.json — open positions

Explicitly NOT read (audit 8.2): the dead `learning_database.sqlite`/`trades` table,
`journalctl`/`os.system`/subprocess trade scraping, and the port-5000 network fallback.
No dead fallbacks that a downstream error could accidentally activate.

Metric definitions come from the PR3 contract (trade_metrics_contract): outcome is the
stored canonical WIN/LOSS/FLAT (±0.05pp net deadband), win rate is WIN/(WIN+LOSS+FLAT),
profit factor is the magnitude ratio (never ~1.0-for-any-positive). Legacy rows without a
stored `outcome` are classified at read time via the same canonical classifier.

Never raises: on missing/locked DB, missing column, empty cache, corrupt JSON or legacy
schema the public functions return a valid, fully-shaped JSON dict with `degraded: true`
and machine-readable `errors` — never a stack trace or server path.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

from src.core.trade_metrics_contract import (
    OUTCOME_POLICY_VERSION,
    TradeOutcome,
    classify_outcome,
    compute_profit_factor,
    compute_win_rate,
)

RECENT_WINDOW = 100
COST_FLOOR_BPS = 18  # modeled paper round-trip cost (15 fee + 3 slippage)


# ── paths ─────────────────────────────────────────────────────────────────────

def _paths():
    if os.path.exists("/opt/cryptomaster"):
        base = "/opt/cryptomaster"
    else:
        base = "."
    return (
        os.path.join(base, "local_learning_storage/cache.sqlite"),
        os.path.join(base, "server_local_backups/paper_adaptive_learning_state.json"),
        os.path.join(base, "data/paper_open_positions.json"),
    )


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ts_iso(ts):
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


# ── source loaders (each records an error code instead of raising) ────────────

def _load_learning_state(errors):
    path = _paths()[1]
    try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            errors.append("learning_state_unreadable")  # valid JSON but not an object
    except (json.JSONDecodeError, OSError):
        errors.append("learning_state_unreadable")
    return {}


def _read_recent_rows(errors, limit=RECENT_WINDOW):
    """Newest <=limit closed_trades rows, read-only. Returns list of dicts."""
    cache_path = _paths()[0]
    if not cache_path or not os.path.exists(cache_path):
        errors.append("cache_missing")
        return []
    # `outcome`/`side` may be absent on a legacy schema — degrade the SELECT.
    select_variants = [
        "SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
        "exit_reason, entry_ts, exit_ts, regime, win, side, outcome "
        "FROM closed_trades ORDER BY exit_ts DESC LIMIT ?",
        "SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
        "exit_reason, entry_ts, exit_ts, regime, win, side, NULL AS outcome "
        "FROM closed_trades ORDER BY exit_ts DESC LIMIT ?",
        "SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
        "exit_reason, entry_ts, exit_ts, regime, win, NULL AS side, NULL AS outcome "
        "FROM closed_trades ORDER BY exit_ts DESC LIMIT ?",
    ]
    try:
        conn = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        errors.append("cache_unopenable")
        return []
    try:
        rows = None
        for q in select_variants:
            try:
                rows = list(conn.execute(q, (int(limit),)))
                break
            except sqlite3.OperationalError:
                continue
        if rows is None:
            errors.append("cache_schema_unreadable")
            return []
    except sqlite3.Error:
        errors.append("cache_locked")
        return []
    finally:
        conn.close()

    out = []
    for r in rows:
        tid, sym, ep, xp, pu, pp, reason, ets, xts, regime, win, side, outcome = r
        out.append({
            "trade_id": tid, "symbol": sym,
            "entry_price": _f(ep), "exit_price": _f(xp),
            "pnl_usd": _f(pu), "pnl_pct": _f(pp), "pnl_pct_null": pp is None,
            "exit_reason": reason, "entry_ts": _f(ets), "exit_ts": _f(xts),
            "regime": regime, "win": int(win or 0), "side": side, "outcome": outcome,
        })
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _session_aggregate(errors):
    """COUNT + SUM(pnl_usd) + exit-reason distribution over the full cache."""
    cache_path = _paths()[0]
    exits = {"tp": 0, "sl": 0, "scratch": 0, "stagnation": 0, "timeout": 0}
    if not cache_path or not os.path.exists(cache_path):
        return 0, 0.0, exits
    try:
        conn = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        errors.append("cache_unopenable")
        return 0, 0.0, exits
    try:
        row = conn.execute(
            "SELECT COUNT(*), SUM(COALESCE(pnl_usd,0)) FROM closed_trades").fetchone() or (0, 0)
        session_n = int(row[0] or 0)
        session_net = float(row[1] or 0)
        for reason, cnt in conn.execute(
            "SELECT LOWER(COALESCE(exit_reason,'')), COUNT(*) "
            "FROM closed_trades GROUP BY LOWER(COALESCE(exit_reason,''))"
        ):
            if reason == "tp":
                exits["tp"] = cnt
            elif reason == "sl":
                exits["sl"] = cnt
            elif "scratch" in reason:
                exits["scratch"] += cnt
            elif "stag" in reason:
                exits["stagnation"] += cnt
            elif "timeout" in reason:
                exits["timeout"] += cnt
        return session_n, session_net, exits
    except sqlite3.Error:
        errors.append("cache_locked")
        return 0, 0.0, exits
    finally:
        conn.close()


# ── canonical outcome per row ─────────────────────────────────────────────────

def _row_outcome(row) -> TradeOutcome:
    """Prefer the stored canonical outcome; derive from net pct for legacy rows."""
    stored = row.get("outcome")
    if stored:
        try:
            return TradeOutcome(str(stored).strip().upper())
        except ValueError:
            pass
    return classify_outcome(row.get("pnl_pct", 0.0))


# ── recent-window headline (ONE definition, shared by all endpoints) ──────────

def _recent_headline(rows):
    """Canonical WR/PF/net over the recent window. Same numbers everywhere.

    Audit F7: profit factor is exposed on BOTH bases — normalized (pct-points,
    strategy-quality, size-independent) and economic (USD, real sizing impact) —
    because with variable position size the two differ. `recent_profit_factor`
    keeps the pct basis as the documented default.
    """
    outcomes = [_row_outcome(r) for r in rows]
    net_pct = [r.get("pnl_pct", 0.0) for r in rows]
    net_usd_vals = [r.get("pnl_usd", 0.0) for r in rows]
    pf_pct = round(compute_profit_factor(net_pct), 3)
    pf_usd = round(compute_profit_factor(net_usd_vals), 3)
    wins = sum(1 for o in outcomes if o is TradeOutcome.WIN)
    losses = sum(1 for o in outcomes if o is TradeOutcome.LOSS)
    flats = sum(1 for o in outcomes if o is TradeOutcome.FLAT)
    return {
        "recent_window_n": len(rows),
        "recent_win_rate_pct": round(compute_win_rate(outcomes) * 100.0, 2),
        "recent_profit_factor": pf_pct,                     # default = pct basis
        "recent_profit_factor_pct_basis": pf_pct,
        "recent_profit_factor_usd_basis": pf_usd,
        "profit_factor_default_basis": "pct_points",
        "recent_net_pnl_usd": round(sum(net_usd_vals), 6),
        "recent_net_pnl_pct": round(sum(net_pct), 4),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate_denominator": len(rows),
        "outcome_policy_version": OUTCOME_POLICY_VERSION,
    }


# ── list builders ─────────────────────────────────────────────────────────────

def _closed_trades_list(rows, limit=30):
    out = []
    for r in rows[:limit]:
        ep, xp, pu = r["entry_price"], r["exit_price"], r["pnl_usd"]
        pp = r["pnl_pct"]
        side = r.get("side")
        # Legacy NULL pnl_pct (matches old `if pp is None`): recompute long-formula
        # then correct sign for shorts. A genuine stored 0.0 is left untouched.
        if r.get("pnl_pct_null") and ep and xp:
            recomputed = (xp / ep - 1.0) * 100.0
            if (side or "").upper() in ("SELL", "SHORT"):
                recomputed = -recomputed
            elif side is None and pu and recomputed * pu < 0:
                recomputed = -recomputed
            pp = round(recomputed, 4) if recomputed else pp
        ets, xts = r["entry_ts"], r["exit_ts"]
        out.append({
            "trade_id": r["trade_id"], "symbol": r["symbol"], "side": (side or "BUY"),
            "entry_price": ep, "exit_price": xp,
            "pnl_pct": pp, "pnl_usd": pu,
            "reason": r["exit_reason"], "exit_reason": r["exit_reason"],
            "hold_s": int(xts - ets) if (xts and ets) else 0,
            "regime": r["regime"] or "UNKNOWN", "win": r["win"],
            "outcome": _row_outcome(r).value,
            "exit_time": int(xts) if xts else 0,
            "entry_timestamp": _ts_iso(ets), "exit_timestamp": _ts_iso(xts),
        })
    return out


def _closed_trades_from_rolling(rolling, limit=30):
    """Durable fallback when the ephemeral cache is empty after a restart."""
    out = []
    for e in reversed(list(rolling)[-limit:]):
        if not isinstance(e, (list, tuple)) or len(e) < 3:
            continue
        pnl = e[0] if isinstance(e[0], (int, float)) else 0.0
        outcome = next((x.upper() for x in e if isinstance(x, str)
                        and x.upper() in ("WIN", "LOSS", "FLAT")), "")
        if not outcome:
            outcome = classify_outcome(float(pnl)).value
        seg = next((x for x in e if isinstance(x, str) and ":" in x), "::")
        parts = seg.split(":")
        ts = next((x for x in e if isinstance(x, (int, float)) and x > 1e9), 0)
        exit_iso = _ts_iso(ts)
        out.append({
            "trade_id": "", "symbol": parts[0] if parts and parts[0] else "?",
            "side": parts[2] if len(parts) > 2 else "BUY",
            "entry_price": 0, "exit_price": 0,
            "pnl_pct": round(float(pnl), 4), "pnl_usd": 0.0,
            "reason": outcome, "exit_reason": outcome, "outcome": outcome,
            "hold_s": 0, "regime": parts[1] if len(parts) > 1 else "UNKNOWN",
            "win": 1 if outcome == "WIN" else 0, "exit_time": int(ts),
            "entry_ts": "", "entry_timestamp": "",
            "exit_ts": exit_iso, "exit_timestamp": exit_iso,
        })
    return out


def _open_positions(errors):
    pos_path = _paths()[2]
    out = []
    try:
        if not os.path.exists(pos_path):
            return out
        with open(pos_path) as f:
            positions = json.load(f)
    except (json.JSONDecodeError, OSError):
        errors.append("positions_unreadable")
        return out
    # Valid JSON but not an object/array -> degrade ONLY positions, not the payload.
    if not isinstance(positions, (dict, list)):
        errors.append("positions_unreadable")
        return out
    now_ts = time.time()
    iterable = positions.items() if isinstance(positions, dict) else enumerate(positions)
    for pid, p in iterable:
        if not isinstance(p, dict):
            continue
        ets = _f(p.get("entry_ts", now_ts))
        ep = _f(p.get("entry_price", 0))
        cp = _f(p.get("last_price", p.get("entry_price", 0)))
        side = p.get("side", "BUY")
        pnl = ((cp / ep - 1.0) * 100.0) if ep else 0.0
        if str(side).upper() in ("SELL", "SHORT"):
            pnl = -pnl
        out.append({
            "trade_id": str(pid)[:12], "symbol": p.get("symbol", "N/A"),
            "side": side, "entry_price": ep, "current_price": cp,
            "tp": _f(p.get("tp", 0)), "sl": _f(p.get("sl", 0)),
            "entry_ts": ets, "age_seconds": int(now_ts - ets),
            "age_s": int(now_ts - ets), "current_hold_s": int(now_ts - ets),
            "hold_s": int(now_ts - ets), "regime": p.get("regime", "N/A"),
            "size_usd": _f(p.get("size_usd", 0.5)),
            "pnl_pct": round(pnl, 4), "status": "OPEN",
            "entry_timestamp": _ts_iso(ets),
        })
    return out


def _android_status_fields(state):
    rolling = state.get("rolling100") or state.get("rolling50") or []
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    closed_today = sum(
        1 for e in rolling
        if isinstance(e, (list, tuple))
        and any(isinstance(x, (int, float)) and x > 1e9 and x >= midnight for x in e)
    )
    lifetime_n = int(state.get("lifetime_n", 0) or 0)
    if state.get("regime_tp_learning_enabled"):
        learning_status = "UČENÍ"
    elif lifetime_n > 0:
        learning_status = "PŘIPRAVEN"
    else:
        learning_status = "VYPNUTO"
    return {"closed_today": closed_today, "learning_status": learning_status,
            "recommendation": "ČEKAT"}


# ── public API ────────────────────────────────────────────────────────────────

def get_metrics() -> dict:
    """Primary Android contract payload. Never raises."""
    errors: list[str] = []
    iso = _now_iso()
    try:
        state = _load_learning_state(errors)
        lifetime_n = int(state.get("lifetime_n", 0) or 0)
        lifetime_pf = state.get("lifetime_pf", 0.0)
        lifetime_exp = state.get("lifetime_expectancy", 0.0)

        rows = _read_recent_rows(errors, RECENT_WINDOW)
        headline = _recent_headline(rows)
        session_n, session_net, exits = _session_aggregate(errors)

        rolling = state.get("rolling100") or state.get("rolling50") or []
        closed_list = _closed_trades_list(rows) if rows else _closed_trades_from_rolling(rolling)

        # Honest outcome-basis exit distribution when the ephemeral session is empty.
        if session_n == 0 and rolling:
            exits = dict(exits)
            exits["win"] = sum(1 for e in rolling if _rolling_outcome(e) == "WIN")
            exits["loss"] = sum(1 for e in rolling if _rolling_outcome(e) == "LOSS")
            exits["flat"] = sum(1 for e in rolling if _rolling_outcome(e) == "FLAT")
            exits["basis"] = "outcome"

        positions = _open_positions(errors)

        return {
            "closed_trades": lifetime_n,
            "total_trades": lifetime_n,
            **_android_status_fields(state),
            "session_closed_trades": session_n,
            "lifetime_closed_trades": lifetime_n,
            "open_positions": len(positions),
            "open_positions_list": positions,
            "closed_trades_list": closed_list,
            # Headline (canonical, shared by /enhanced): PR3 outcome-based WR/PF.
            "profit_factor": headline["recent_profit_factor"],
            "win_rate_pct": headline["recent_win_rate_pct"],
            "win_rate_window": headline["recent_window_n"],
            "net_pnl": round(session_net, 6),
            "net_pnl_window": headline["recent_net_pnl_usd"],
            # Audit F6: ONE explicit single-window headline object the frontend
            # must consume (never mix lifetime_n * recent WR; FLAT is its own
            # bucket, not a loss). All fields are from the SAME recent window.
            "headline": {
                "schema_version": 1,
                "window": f"recent_{headline['recent_window_n']}",
                "n": headline["recent_window_n"],
                "wins": headline["wins"],
                "losses": headline["losses"],
                "flats": headline["flats"],
                "win_rate_pct": headline["recent_win_rate_pct"],
                "profit_factor_pct_basis": headline["recent_profit_factor_pct_basis"],
                "profit_factor_usd_basis": headline["recent_profit_factor_usd_basis"],
                "profit_factor_default_basis": "pct_points",
                "net_pnl_pct": headline["recent_net_pnl_pct"],
                "net_pnl_usd": headline["recent_net_pnl_usd"],
                "source": "cache.sqlite:closed_trades",
                "generated_at": iso,
            },
            # Explicit windows + metadata (audit 8.4).
            "recent": {**headline, "source": "cache.sqlite:closed_trades",
                       "unit": "pct_points+usd", "generated_at": iso},
            "lifetime": {"lifetime_n": lifetime_n, "lifetime_profit_factor": lifetime_pf,
                         "lifetime_expectancy": lifetime_exp,
                         "source": "learning_state.json", "generated_at": iso},
            "session_n": session_n,
            "exit_distribution": exits,
            "timestamp": iso, "last_update": iso, "last_update_utc": iso,
            "data_source": "learning_state+cache.sqlite",
            "lifetime_metrics": {"lifetime_n": lifetime_n, "lifetime_pf": lifetime_pf,
                                 "lifetime_expectancy": lifetime_exp},
            "degraded": bool(errors),
            "errors": errors,
        }
    except Exception:
        return _degraded_envelope(["internal_error"], iso)


def get_enhanced_metrics() -> dict:
    """Primary payload PLUS diagnostics. Headline metrics are IDENTICAL (audit 8.3)."""
    base = get_metrics()
    try:
        tp_zone = os.getenv("PAPER_TP_ZONE_BPS", "")
        sl_zone = os.getenv("PAPER_SL_ZONE_BPS", "")
        recent = base.get("recent", {})
        pf = recent.get("recent_profit_factor", base.get("profit_factor", 0.0))
        base["enhanced"] = {
            "cost_floor_bps": COST_FLOOR_BPS,
            "tp_zone_bps": tp_zone, "sl_zone_bps": sl_zone,
            # Canonical PF (audit 8.7) — never the legacy ~1.0-for-any-positive value.
            "profit_factor": pf,
            "health": "ok" if not base.get("degraded") else "degraded",
        }
    except Exception:
        base.setdefault("enhanced", {"health": "degraded"})
    return base


def get_recent_trades(limit=30) -> list:
    """Recent closed trades — same cache.sqlite the headline uses (audit 8.3).

    Never raises: the Flask wrapper has no guard of its own, so this is the
    never-500 boundary for /api/trades/recent.
    """
    errors: list[str] = []
    try:
        rows = _read_recent_rows(errors, max(limit, RECENT_WINDOW))
        if rows:
            return _closed_trades_list(rows, limit)
        state = _load_learning_state(errors)
        rolling = state.get("rolling100") or state.get("rolling50") or []
        return _closed_trades_from_rolling(rolling, limit)
    except Exception:
        return []


def _rolling_outcome(e):
    if isinstance(e, (list, tuple)):
        for x in e:
            if isinstance(x, str) and x.upper() in ("WIN", "LOSS", "FLAT"):
                return x.upper()
        pnl = e[0] if e and isinstance(e[0], (int, float)) else 0.0
        return classify_outcome(float(pnl)).value
    return ""


def _degraded_envelope(errors, iso):
    """Fully-shaped, safe-default payload with degraded flag (never a 500)."""
    return {
        "closed_trades": 0, "total_trades": 0, "closed_today": 0,
        "learning_status": "VYPNUTO", "recommendation": "ČEKAT",
        "session_closed_trades": 0, "lifetime_closed_trades": 0,
        "open_positions": 0, "open_positions_list": [], "closed_trades_list": [],
        "profit_factor": 0.0, "win_rate_pct": 0.0, "win_rate_window": 0,
        "net_pnl": 0.0, "net_pnl_window": 0.0, "session_n": 0,
        # F6: zeroed headline so the shape is consistent even when degraded.
        "headline": {
            "schema_version": 1, "window": "recent_0", "n": 0,
            "wins": 0, "losses": 0, "flats": 0, "win_rate_pct": 0.0,
            "profit_factor_pct_basis": 0.0, "profit_factor_usd_basis": 0.0,
            "profit_factor_default_basis": "pct_points",
            "net_pnl_pct": 0.0, "net_pnl_usd": 0.0,
            "source": "degraded", "generated_at": iso,
        },
        "exit_distribution": {"tp": 0, "sl": 0, "scratch": 0, "stagnation": 0, "timeout": 0},
        "timestamp": iso, "last_update": iso, "last_update_utc": iso,
        "data_source": "degraded",
        "lifetime_metrics": {"lifetime_n": 0, "lifetime_pf": 0.0, "lifetime_expectancy": 0.0},
        "degraded": True, "errors": errors,
    }
