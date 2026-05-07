"""
app_metrics_contract.py — Pure snapshot builder for Android dashboard.

Builds a stable, JSON-safe Firestore document for app_metrics/latest.
No Firebase imports. No runtime module imports. No learning-monitor imports.
All runtime/health/quota/learning status is passed as plain dicts.

Schema version: app_metrics_v1
Android reads: app_metrics/latest (one document, full set())
Trade history:  trades orderBy(timestamp desc).limit(100)
"""

import math
import time as _time
from typing import Optional

APP_METRICS_SCHEMA_VERSION = "app_metrics_v1"
APP_METRICS_WINDOW_LIMIT = 500
APP_METRICS_MAX_OPEN_POSITIONS = 50
APP_METRICS_STALE_SIGNAL_S = 300


# ── Safe helpers ──────────────────────────────────────────────────────────────

def _safe_float(value, default: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_safe(obj):
    """Recursively make obj JSON-safe: remove NaN/inf, truncate large arrays."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return round(obj, 6)
    return obj


# ── Outcome classification ────────────────────────────────────────────────────

_NEUTRAL_REASONS = frozenset({
    "timeout", "TIMEOUT", "TIMEOUT_PROFIT", "TIMEOUT_FLAT", "TIMEOUT_LOSS",
    "SCRATCH_EXIT", "STAGNATION_EXIT",
})
# |profit| < this on a neutral exit → FLAT
_FLAT_THRESHOLD = 0.001
# below this, profit is treated as exactly zero even on non-neutral exits
_EPS = 1e-9


def _extract_profit(trade: dict) -> float:
    # unit_pnl excluded: ambiguous unit (percent vs decimal); use canonical fields only
    for field in ("profit", "pnl", "net_pnl"):
        if field in trade:
            try:
                v = float(trade[field] or 0.0)
                if not (math.isnan(v) or math.isinf(v)):
                    return v
            except (TypeError, ValueError):
                pass
    try:
        return float(trade.get("evaluation", {}).get("profit", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _classify_outcome(trade: dict, profit: float) -> str:
    """WIN / LOSS / FLAT.

    Neutral exits (timeout/scratch/stagnation): FLAT when |profit| < threshold.
    Non-neutral exits: respect stored result field if WIN/LOSS, otherwise classify
    by sign. Never flatten a real TP/SL trade just because the profit is small.
    """
    close_reason = str(trade.get("close_reason") or trade.get("exit_reason") or "").lower()
    is_neutral = close_reason in {r.lower() for r in _NEUTRAL_REASONS}

    if is_neutral:
        if abs(profit) < _FLAT_THRESHOLD:
            return "FLAT"
        return "WIN" if profit > 0 else "LOSS"

    # Non-neutral exit: respect stored result if decisive
    stored = str(trade.get("result") or trade.get("outcome") or "").upper()
    if stored in ("WIN", "LOSS"):
        return stored

    # Classify by sign; only truly zero profit is FLAT
    if abs(profit) < _EPS:
        return "FLAT"
    return "WIN" if profit > 0 else "LOSS"


# ── Symbol / regime / exit breakdowns ────────────────────────────────────────

def _build_window_breakdowns(trades: list) -> tuple[dict, dict, dict]:
    """Build per-symbol, per-regime, per-exit counts from window trades."""
    symbols: dict = {}
    regimes: dict = {}
    exits: dict = {}

    for t in trades:
        profit = _extract_profit(t)
        outcome = _classify_outcome(t, profit)
        sym = str(t.get("symbol") or "UNKNOWN")
        reg = str(t.get("regime") or "UNKNOWN")
        exit_r = str(t.get("close_reason") or t.get("exit_reason") or "UNKNOWN")

        for bucket, key in [(symbols, sym), (regimes, reg), (exits, exit_r)]:
            if key not in bucket:
                bucket[key] = {"count": 0, "wins": 0, "losses": 0, "flats": 0, "net_pnl": 0.0}
            bucket[key]["count"] += 1
            bucket[key]["net_pnl"] = _safe_float(bucket[key]["net_pnl"]) + profit
            if outcome == "WIN":
                bucket[key]["wins"] += 1
            elif outcome == "LOSS":
                bucket[key]["losses"] += 1
            else:
                bucket[key]["flats"] += 1

    return symbols, regimes, exits


def _build_kpis(
    closed_trades: list,
    all_time_stats: Optional[dict],
    session_metrics: dict,
    now: float,
) -> tuple[dict, str]:
    """Compute all KPI fields. Returns (kpis_dict, all_time_source)."""
    # Window metrics
    profits = [_extract_profit(t) for t in closed_trades]
    outcomes = [_classify_outcome(t, p) for t, p in zip(closed_trades, profits)]

    wins = outcomes.count("WIN")
    losses = outcomes.count("LOSS")
    flats = outcomes.count("FLAT")
    decisive = wins + losses
    window_wr = _safe_float(wins / decisive) if decisive > 0 else 0.0

    gross_win = sum(p for p, o in zip(profits, outcomes) if o == "WIN")
    gross_loss = abs(sum(p for p, o in zip(profits, outcomes) if o == "LOSS"))
    profit_factor = _safe_float(gross_win / gross_loss) if gross_loss > 1e-9 else (1.0 if gross_win > 0 else 0.0)

    net_pnl = sum(profits)
    gross_pnl = gross_win - gross_loss
    expectancy = _safe_float(net_pnl / len(profits)) if profits else 0.0
    avg_profit = expectancy
    best = max(profits) if profits else 0.0
    worst = min(profits) if profits else 0.0

    # Drawdown
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for p in profits:
        equity += p
        if equity > peak:
            peak = equity
        dd = equity - peak
        if dd < drawdown:
            drawdown = dd

    # Last trade timestamp
    last_ts = 0.0
    for t in closed_trades:
        ts = _safe_float(t.get("timestamp") or t.get("exit_ts") or 0.0)
        if ts > last_ts:
            last_ts = ts
    since_last = None
    if last_ts > 0:
        since_last = _safe_float(now - last_ts)

    # All-time stats — prefer system/stats, fallback to canonical, then session
    all_time_source = "unknown"
    trades_total_all_time = 0
    wins_all_time = 0
    losses_all_time = 0
    timeouts_all_time = 0

    if all_time_stats and isinstance(all_time_stats, dict):
        trades_total_all_time = _safe_int(all_time_stats.get("trades") or all_time_stats.get("trades_total"))
        wins_all_time = _safe_int(all_time_stats.get("wins") or all_time_stats.get("trades_won"))
        losses_all_time = _safe_int(all_time_stats.get("losses") or all_time_stats.get("trades_lost"))
        timeouts_all_time = _safe_int(all_time_stats.get("timeouts"))
        all_time_source = "system_stats"
    elif session_metrics:
        trades_total_all_time = _safe_int(session_metrics.get("trades"))
        wins_all_time = _safe_int(session_metrics.get("wins"))
        losses_all_time = _safe_int(session_metrics.get("losses"))
        timeouts_all_time = _safe_int(session_metrics.get("timeouts"))
        all_time_source = "session_metrics"

    decisive_all = wins_all_time + losses_all_time
    wr_all_time = _safe_float(wins_all_time / decisive_all) if decisive_all > 0 else 0.0

    return {
        "all_time_source": all_time_source,
        "window_source": "load_history",

        "trades_total_all_time": trades_total_all_time,
        "wins_all_time": wins_all_time,
        "losses_all_time": losses_all_time,
        "timeouts_all_time": timeouts_all_time,
        "decisive_trades_all_time": decisive_all,
        "winrate_all_time": round(wr_all_time, 4),

        "window_trades": len(closed_trades),
        "window_wins": wins,
        "window_losses": losses,
        "window_flats": flats,
        "window_decisive_trades": decisive,
        "window_winrate": round(window_wr, 4),

        "profit_factor": round(profit_factor, 4),
        "net_pnl": round(net_pnl, 6),
        "gross_pnl": round(gross_pnl, 6),
        "expectancy": round(expectancy, 6),
        "avg_profit": round(avg_profit, 6),
        "best_trade": round(best, 6),
        "worst_trade": round(worst, 6),
        "drawdown": round(drawdown, 6),
        "last_trade_ts": last_ts,
        "since_last_trade_s": since_last,
    }, all_time_source


def _build_open_positions(open_positions, now: float) -> dict:
    """Normalize open_positions (list or dict) into compact snapshot."""
    if isinstance(open_positions, dict):
        all_items = list(open_positions.values())
    elif isinstance(open_positions, (list, tuple)):
        all_items = list(open_positions)
    else:
        all_items = []

    # Cap and strip large fields
    compact = []
    for pos in all_items[:APP_METRICS_MAX_OPEN_POSITIONS]:
        if not isinstance(pos, dict):
            continue
        entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at") or 0.0)
        age_s = round(_safe_float(now - entry_ts), 1) if entry_ts > 0 else None
        compact.append({
            "trade_id": str(pos.get("trade_id") or pos.get("id") or ""),
            "symbol": str(pos.get("symbol") or ""),
            "side": str(pos.get("side") or pos.get("action") or ""),
            "entry_price": _safe_float(pos.get("entry_price") or pos.get("entry") or 0.0),
            "size_usd": _safe_float(pos.get("size_usd") or pos.get("size") or 0.0),
            "ev_at_entry": _safe_float(pos.get("ev_at_entry") or pos.get("ev") or 0.0),
            "bucket": str(pos.get("training_bucket") or pos.get("explore_bucket") or ""),
            "age_s": age_s,
        })

    return {
        "count": len(all_items),          # total open positions, not truncated
        "items_count": len(compact),       # items actually returned
        "items_limit": APP_METRICS_MAX_OPEN_POSITIONS,
        "items": compact,
    }


def _build_last_signals(last_signals: dict, now: float, safe_mode: bool) -> dict:
    """Build per-symbol recommendation map."""
    result = {}
    if not isinstance(last_signals, dict):
        return result

    for sym, sig in last_signals.items():
        if not isinstance(sig, dict):
            result[sym] = {"action": "HOLD", "reason": "no_signal", "confidence": 0.0, "ts": 0.0, "age_s": None}
            continue

        sig_ts = _safe_float(sig.get("ts") or sig.get("timestamp") or 0.0)
        age_s = round(_safe_float(now - sig_ts), 1) if sig_ts > 0 else None

        if safe_mode:
            action, reason = "HOLD", "safe_mode"
        elif not sig:
            action, reason = "HOLD", "no_signal"
        elif age_s is not None and age_s > APP_METRICS_STALE_SIGNAL_S:
            action, reason = "HOLD", "stale_signal"
        else:
            action = str(sig.get("action") or "HOLD").upper()
            reason = "latest_signal"

        result[sym] = {
            "action": action,
            "reason": reason,
            "confidence": _safe_float(sig.get("confidence") or sig.get("p") or 0.0),
            "ts": sig_ts,
            "age_s": age_s,
        }

    return result


def _build_learning_section(session_metrics: dict) -> dict:
    """Build learning progress section from session metrics only.

    Keep this module pure: no Firebase/runtime/learning-monitor imports here.
    """
    m = session_metrics or {}
    trades = _safe_int(m.get("trades"))
    wins = _safe_int(m.get("wins"))
    losses = _safe_int(m.get("losses"))
    decisive = wins + losses
    wr = _safe_float(wins / decisive) if decisive > 0 else 0.0

    # Simple progress heuristic: 0% at 0 trades, 100% at 100 decisive trades
    progress = min(1.0, _safe_float(decisive / 100.0))
    maturity = min(1.0, _safe_float(trades / 150.0))
    edge = decisive >= 30 and (wr > 0.55 or wr < 0.40)  # edge detected if non-trivial WR

    health = str(
        m.get("confidence_momentum")
        or m.get("learning_health")
        or "UNKNOWN"
    )

    return {
        "progress_to_ready": round(progress, 3),
        "data_maturity": round(maturity, 3),
        "edge_detected": edge,
        "confidence_momentum": health,
        "next_milestone": f"{max(0, 30 - decisive)} more decisive trades to basic calibration" if decisive < 30 else "",
        "hydration_source": str(m.get("hydration_source") or m.get("source") or "unknown"),
        "paper_train_entries_1h": _safe_int(m.get("paper_train_entries_1h")),
        "paper_train_closed_1h": _safe_int(m.get("paper_train_closed_1h")),
        "paper_train_learning_updates_1h": _safe_int(m.get("paper_train_learning_updates_1h")),
    }


# ── Main builder ──────────────────────────────────────────────────────────────

def build_app_metrics_snapshot(
    *,
    closed_trades: list,
    session_metrics: dict,
    open_positions,
    last_signals: dict,
    all_time_stats: Optional[dict] = None,
    runtime: Optional[dict] = None,
    firebase_health: Optional[dict] = None,
    quota_status: Optional[dict] = None,
    now: Optional[float] = None,
    window_limit_requested: Optional[int] = None,
) -> dict:
    """
    Build a stable, JSON-safe app_metrics snapshot for Firestore.

    Args:
        closed_trades:   Recent closed trades (window, max APP_METRICS_WINDOW_LIMIT)
        session_metrics: Current session METRICS dict (from learning_event.get_metrics)
        open_positions:  List or dict of currently open positions
        last_signals:    {symbol: signal_dict} last signal per symbol
        all_time_stats:  All-time stats from system/stats doc (optional)
        runtime:         Runtime state dict (trading_mode, paper_mode, etc.)
        firebase_health: Firebase health dict from get_firebase_health()
        quota_status:    Quota dict from get_quota_status()
        now:             Current timestamp (defaults to time.time())
        window_limit_requested: Actual load_history limit requested by caller.

    Returns:
        dict — snapshot ready for Firestore set()
    """
    if now is None:
        now = _time.time()

    closed_trades = closed_trades or []
    session_metrics = session_metrics or {}
    last_signals = last_signals or {}
    runtime = runtime or {}
    firebase_health = firebase_health or {}
    quota_status = quota_status or {}

    safe_mode = bool(runtime.get("safe_mode"))
    actual_loaded = len(closed_trades)
    limit_requested = _safe_int(window_limit_requested, APP_METRICS_WINDOW_LIMIT)

    # KPIs
    kpis, all_time_source = _build_kpis(closed_trades, all_time_stats, session_metrics, now)

    # Window breakdowns
    symbols, regimes, exits = _build_window_breakdowns(closed_trades)

    # Open positions
    open_pos = _build_open_positions(open_positions, now)

    # Recommendations per symbol
    recommendations = _build_last_signals(last_signals, now, safe_mode)

    # Recent window stats
    recent_window = min(len(closed_trades), 20)
    recent_trades = closed_trades[-recent_window:] if recent_window > 0 else []
    recent_profits = [_extract_profit(t) for t in recent_trades]
    recent_outcomes = [_classify_outcome(t, p) for t, p in zip(recent_trades, recent_profits)]
    recent_wins = recent_outcomes.count("WIN")
    recent_decisive = recent_wins + recent_outcomes.count("LOSS")
    recent_wr = _safe_float(recent_wins / recent_decisive) if recent_decisive > 0 else None
    recent_avg_ev = None
    if recent_trades:
        evs = [_safe_float(t.get("ev") or t.get("ev_at_entry") or 0.0) for t in recent_trades]
        evs = [e for e in evs if e != 0.0]
        if evs:
            recent_avg_ev = round(sum(evs) / len(evs), 4)

    # Firebase health
    quota_reads = _safe_int(quota_status.get("reads_today") or quota_status.get("reads"))
    quota_writes = _safe_int(quota_status.get("writes_today") or quota_status.get("writes"))
    quota_reads_limit = _safe_int(quota_status.get("reads_limit") or 50000)
    quota_writes_limit = _safe_int(quota_status.get("writes_limit") or 20000)
    reads_pct = f"{100 * quota_reads / max(quota_reads_limit, 1):.1f}%"
    writes_pct = f"{100 * quota_writes / max(quota_writes_limit, 1):.1f}%"

    health_section = {
        "firebase_available": bool(firebase_health.get("available", True)),
        "firebase_read_degraded": bool(firebase_health.get("read_degraded") or firebase_health.get("degraded")),
        "firebase_write_degraded": bool(firebase_health.get("write_degraded") or firebase_health.get("degraded")),
        "quota_reads": quota_reads,
        "quota_reads_limit": quota_reads_limit,
        "quota_reads_pct": reads_pct,
        "quota_writes": quota_writes,
        "quota_writes_limit": quota_writes_limit,
        "quota_writes_pct": writes_pct,
        "reconciliation_verified": bool(firebase_health.get("reconciliation_verified", True)),
        "alerts": list(firebase_health.get("alerts") or []),
    }

    snapshot = {
        "schema_version": APP_METRICS_SCHEMA_VERSION,
        "generated_at": now,
        "source": "cryptomaster_bot",

        "runtime": {
            "trading_mode": str(runtime.get("trading_mode") or "paper_live"),
            "paper_mode": bool(runtime.get("paper_mode", True)),
            "live_allowed": bool(runtime.get("live_allowed", False)),
            "paper_training_enabled": bool(runtime.get("paper_training_enabled", False)),
            "safe_mode": safe_mode,
            "safe_mode_reason": str(runtime.get("safe_mode_reason") or ""),
            "git_sha": str(runtime.get("git_sha") or ""),
            "branch": str(runtime.get("branch") or ""),
            "version": str(runtime.get("version") or ""),
        },

        "health": health_section,

        "kpis": kpis,

        "window": {
            "source": "load_history",
            "limit_configured": APP_METRICS_WINDOW_LIMIT,
            "limit_requested": limit_requested,
            "actual_loaded": actual_loaded,
            "count": actual_loaded,
            "note": "Breakdowns are based on the actual loaded recent window unless marked otherwise.",
        },

        "learning": _build_learning_section(session_metrics),

        "open_positions": open_pos,

        "symbols_scope": "window",
        "symbols": symbols,

        "regimes_scope": "window",
        "regimes": regimes,

        "exits_scope": "window",
        "exits": exits,

        "recommendations": recommendations,

        "recent": {
            "recent_window_known": recent_window > 0,
            "recent_window": recent_window,
            "recent_winrate": recent_wr,
            "recent_avg_ev": recent_avg_ev,
        },

        "app_context_cs": {
            "trades_total_all_time": "Celkový počet uzavřených obchodů z atomického počítadla. Není to jen posledních 500 obchodů.",
            "window_trades": "Počet obchodů v posledním skutečně načteném okně pro detailní statistiky.",
            "winrate_all_time": "Úspěšnost z all-time WIN/LOSS počtů, pokud jsou dostupné.",
            "window_winrate": "Úspěšnost v posledním okně obchodů.",
            "profit_factor": "Poměr hrubých zisků vůči hrubým ztrátám. Nad 1.0 systém vydělává, nad 1.5 je zdravější.",
            "net_pnl": "Součet čistého PnL v posledním metrickém okně.",
            "expectancy": "Průměrný očekávaný výsledek jednoho obchodu podle historie v okně.",
            "open_positions": "Aktuálně otevřené paper/live pozice.",
            "recommendation": "Poslední signál bota pro daný symbol. Není to finanční doporučení.",
            "scope": "Symboly, režimy a exity jsou window-scoped, pokud není výslovně uvedeno jinak.",
        },
    }

    return _json_safe(snapshot)
