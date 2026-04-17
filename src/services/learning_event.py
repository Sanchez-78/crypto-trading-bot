import time as _time
import threading as _threading
import queue as _queue
from collections import deque as _deque

_lock = _threading.Lock()

# ── Redis hydration on boot ───────────────────────────────────────────────────

def _hydrate_from_redis() -> None:
    try:
        from src.services.state_manager import hydrate_metrics
        data = hydrate_metrics()
        if not data:
            return
        m = data.get("metrics", {})
        if m:
            METRICS.update(m)
        _close_reasons.update(data.get("close_reasons", {}))
        _regime_stats.update(data.get("regime_stats", {}))
        if m.get("trades", 0):
            print(f"🔄 Metrics hydrated from Redis: {m['trades']} trades")
    except Exception as exc:
        print(f"⚠️  Metrics Redis hydration skipped: {exc}")


METRICS = {
    "trades": 0, "wins": 0, "losses": 0, "timeouts": 0, "profit": 0.0,
    "win_streak": 0, "loss_streak": 0,
    "equity_peak": 0.0, "drawdown": 0.0,
    "confidence_avg": 0.0,
    "signals_generated": 0,
    "signals_filtered": 0,
    "signals_executed": 0,
    "signals_accepted": 0,   # signals that passed ALL gates → trade opened
    "blocked": 0,
    "regimes": {"BULL_TREND": 0, "BEAR_TREND": 0, "RANGING": 0,
                "QUIET_RANGE": 0, "HIGH_VOL": 0},
    # Extended performance metrics
    "gross_wins":      0.0,
    "gross_losses":    0.0,
    "avg_win":         0.0,
    "avg_loss":        0.0,
    "best_trade":      0.0,
    "worst_trade":     0.0,
    "last_trade_time": 0.0,
    "block_reasons":   {},
}

_last_prices    = {}
_last_signals   = {}
_sym_stats      = {}
_close_reasons  = {
    "TP": 0, "SL": 0,
    "TRAIL_SL": 0, "TRAIL_PROFIT": 0, "trail": 0,
    "MICRO_TP": 0, "PARTIAL_TP_25": 0, "PARTIAL_TP_50": 0, "PARTIAL_TP_75": 0,
    "BREAKEVEN_STOP": 0, "SCRATCH_EXIT": 0, "STAGNATION_EXIT": 0,
    "timeout": 0, "TIMEOUT_PROFIT": 0, "TIMEOUT_FLAT": 0, "TIMEOUT_LOSS": 0,
    "HARVEST_PROFIT": 0,  # V10.13g: promoted timeout_profit exits (>3min)
    "wall_exit": 0, "early_exit": 0,
}
_regime_stats   = {}   # regime -> {"wins": int, "trades": int}

# Ring-buffers: O(1) append+auto-evict; no manual pop(0) needed
_recent_results: _deque = _deque(maxlen=50)   # last 50 trade outcomes
_ev_history:     _deque = _deque(maxlen=50)   # EV values of last 50 executed trades
_trade_times:    _deque = _deque(maxlen=200)  # rolling timestamps of completed trades

# ── Async metrics writer ──────────────────────────────────────────────────────
# Caller fires update_metrics() and returns immediately.
# A dedicated daemon thread drains the queue — no trading engine stall.

_update_queue: _queue.Queue = _queue.Queue(maxsize=500)


def _worker():
    """Background thread: drain _update_queue and apply DERIVED metrics.

    NOTE: _trade_times, trades, signals_executed, last_trade_time are
    already updated synchronously in update_metrics() — do NOT append
    _trade_times here to avoid double-counting (race condition fix).
    """
    while True:
        try:
            signal, trade = _update_queue.get(timeout=1)
        except _queue.Empty:
            continue
        try:
            with _lock:
                # _trade_times already appended synchronously — skip it here
                _update_metrics_locked(signal, trade)
            try:
                from src.services.state_manager import flush_metrics
                flush_metrics(METRICS, dict(_close_reasons), dict(_regime_stats))
            except Exception:
                pass
        except Exception:
            pass
        finally:
            _update_queue.task_done()


_worker_thread = _threading.Thread(target=_worker, daemon=True, name="metrics-worker")
_worker_thread.start()

# V10.13b: Defer hydration until explicit call from bootstrap sequence
# _hydrate_from_redis()  # REMOVED — now called explicitly from bot2/main.py

async def explicit_hydrate_from_redis():
    """
    V10.13b: Explicit hydration point called from bootstrap sequence, not at module import.
    This ensures we load Redis state AFTER Firebase is ready and BEFORE replaying trades.

    Returns: dict with hydration source and metrics count
    """
    global _hydration_source

    try:
        from src.services.state_manager import get_redis_client
        redis_client = await get_redis_client()
    except Exception:
        redis_client = None

    if redis_client is None:
        _hydration_source = "empty"
        return {"source": "empty", "trades": METRICS.get("trades", 0)}

    try:
        data = _hydrate_from_redis_impl()
        if data and data.get("metrics", {}).get("trades", 0) > 0:
            _hydration_source = "redis"
            return {"source": "redis", "trades": METRICS.get("trades", 0)}
        else:
            _hydration_source = "empty"
            return {"source": "empty", "trades": 0}
    except Exception as exc:
        import logging
        logging.error(f"[METRICS] Explicit hydration failed: {exc}")
        _hydration_source = "error"
        return {"source": "error", "trades": 0}


def _hydrate_from_redis_impl():
    """Internal: do the actual metrics hydration (sync version)."""
    try:
        from src.services.state_manager import hydrate_metrics
        data = hydrate_metrics()
        if not data:
            return {}
        m = data.get("metrics", {})
        if m:
            METRICS.update(m)
        _close_reasons.update(data.get("close_reasons", {}))
        _regime_stats.update(data.get("regime_stats", {}))
        if m.get("trades", 0):
            import logging
            logging.info(f"[METRICS] Hydrated from Redis: {m['trades']} trades")
        return data
    except Exception as exc:
        import logging
        logging.error(f"[METRICS] Hydration impl failed: {exc}")
        return {}


_hydration_source = "pending"  # Track source for diagnostics


def track_price(symbol, price):
    prev = _last_prices.get(symbol, (price, price))[0]
    _last_prices[symbol] = (price, prev)
    # Feed OFI guard with each price tick
    try:
        from src.services.ofi_guard import update_price as _ofi_update
        _ofi_update(symbol, price)
    except Exception:
        pass


def track_signal(symbol: str, action: str, price: float,
                 confidence: float, ev: float, regime: str) -> None:
    """Update _last_signals when a signal is GENERATED (not only on trade close).
    Called from realtime_decision_engine so dashboard always shows current bot intent."""
    with _lock:
        _last_signals[symbol] = {
            "action":     action,
            "price":      price,
            "confidence": round(confidence, 4),
            "ev":         round(ev, 4),
            "regime":     regime,
            "timestamp":  _time.time(),   # signal generation time — used by app for age display
        }


def _update_sym(symbol, result, profit):
    s = _sym_stats.setdefault(symbol, {"trades": 0, "wins": 0, "profit": 0.0})
    s["trades"] += 1
    if result == "WIN":
        s["wins"] += 1
    s["profit"] += profit


def trades_in_window(seconds=900):
    """Count completed trades in the last `seconds` seconds."""
    cutoff = _time.time() - seconds
    # deque iteration is GIL-safe in CPython; no lock needed for read
    return sum(1 for t in list(_trade_times) if t > cutoff)


def update_metrics(signal, trade):
    """Non-blocking: enqueue metrics update for background processing.

    FIX — Race condition patch:
    METRICS['trades'], 'signals_executed', and 'last_trade_time' are now
    updated SYNCHRONOUSLY here (under lock) before the payload is enqueued.
    This guarantees save_metrics_full() sees the correct trade count
    immediately — not 0-30 seconds later when the async worker drains.
    _update_metrics_locked still handles all complex derived fields (WR,
    streaks, drawdown etc.) but must NOT touch trades/signals_executed
    to avoid double-counting.
    """
    with _lock:
        METRICS["trades"]          += 1
        METRICS["signals_executed"] += 1
        METRICS["last_trade_time"]   = _time.time()
        _trade_times.append(METRICS["last_trade_time"])

    try:
        _update_queue.put_nowait((signal, trade))
    except _queue.Full:
        # Queue saturated — process complex metrics inline to avoid data loss
        with _lock:
            _update_metrics_locked(signal, trade)


def _update_metrics_locked(signal, trade):
    """Process all DERIVED metrics (WR, streaks, drawdown).

    NOTE: trades / signals_executed / last_trade_time are already
    incremented synchronously in update_metrics() — do NOT touch them here
    to avoid double-counting (race condition fix).
    Handles both async-queue path AND bootstrap_from_history() path.
    The bootstrap path passes _bootstrap=True to re-enable counter increments.
    """
    m      = METRICS
    profit = float(trade["profit"])

    # ────────────────────────────────────────────────────────────────────────
    # PATCH 7: Anti-Zero Reward — Convert zero/tiny PnL to penalty
    # ────────────────────────────────────────────────────────────────────────
    if abs(profit) < 1e-8:
        profit = -0.0001  # Assign a small penalty to prevent reward signal collapse

    result = trade["result"]
    sym    = signal["symbol"]
    conf   = float(signal.get("confidence", 0.5))

    # trades / signals_executed / last_trade_time already set in update_metrics()
    # Only increment here if called from bootstrap (replay) path
    _is_bootstrap_call = trade.get("_bootstrap_replay", False)
    if _is_bootstrap_call:
        m["trades"]          += 1
        m["signals_executed"] += 1
        m["last_trade_time"]   = float(trade.get("timestamp", _time.time()))

    m["profit"] += profit

    # Neutral timeout: close_reason=="timeout" + |profit| < 0.001
    # Learning system already maps these to 0.0 PnL — METRICS must match.
    # Do NOT count as losses: they carry no directional signal and
    # inflate loss_streak / suppress winrate misleadingly.
    # IMPORTANT: neutral check MUST fire BEFORE result=="WIN" check —
    # Firestore stores result="WIN" when pnl>0 (even tiny 0.0005), so a
    # tiny-positive timeout would be miscounted as a real win.
    _reason          = trade.get("close_reason", "")
    _TIMEOUT_REASONS = {"timeout", "TIMEOUT_PROFIT", "TIMEOUT_FLAT", "TIMEOUT_LOSS",
                        "SCRATCH_EXIT", "STAGNATION_EXIT"}
    _neutral_timeout = (_reason in _TIMEOUT_REASONS and abs(profit) < 0.001)

    if _neutral_timeout:
        m["timeouts"]   += 1
        # streak unchanged — a neutral exit is not a loss
    elif result == "WIN":
        m["wins"]       += 1
        m["win_streak"] += 1
        m["loss_streak"] = 0
        m["gross_wins"] += profit
        m["avg_win"]     = m["gross_wins"] / m["wins"]
        if profit > m["best_trade"]:
            m["best_trade"] = profit
    else:
        m["losses"]      += 1
        m["loss_streak"] += 1
        m["win_streak"]   = 0
        m["gross_losses"] += abs(profit)
        m["avg_loss"]      = m["gross_losses"] / max(m["losses"], 1)
        if profit < m["worst_trade"]:
            m["worst_trade"] = profit

    m["equity_peak"] = max(m["equity_peak"], m["profit"])
    m["drawdown"]    = max(m["drawdown"], m["equity_peak"] - m["profit"])
    m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1

    # Neutral timeouts are excluded from per-symbol WR — they carry no
    # directional signal and would inflate sym_stats.winrate just like METRICS.winrate.
    if not _neutral_timeout:
        _update_sym(sym, result, profit)
        # Direction bias tracking (B17) — record to detect systematic wrong-direction
        try:
            from src.services.signal_filter import record_bias as _rb
            _rb(sym, signal.get("action", "BUY"), profit)
        except Exception:
            pass

    # EV history (deque auto-evicts oldest at maxlen=50)
    ev = float(signal.get("ev", 0))
    if ev > 0:
        _ev_history.append(ev)

    # Close-reason breakdown
    reason = trade.get("close_reason", "")
    
    # V10.13g: Promote profitable stale exits to HARVEST_PROFIT
    # If trade was held 3+ min AND profitable AND exited via timeout,
    # reclassify as harvested profit (not just survived timeout)
    hold_duration = trade.get("duration_seconds", 0)
    if reason == "TIMEOUT_PROFIT" and hold_duration >= 180 and profit > 0:
        reason = "HARVEST_PROFIT"  # Promote to harvest category
        _close_reasons["HARVEST_PROFIT"] = _close_reasons.get("HARVEST_PROFIT", 0) + 1
        _close_reasons["TIMEOUT_PROFIT"] -= 1  # Decrement old count
    elif reason in _close_reasons:
        _close_reasons[reason] += 1
    elif reason == "HARVEST_PROFIT":
        _close_reasons["HARVEST_PROFIT"] = _close_reasons.get("HARVEST_PROFIT", 0) + 1

    # Regime-specific WR
    regime = signal.get("regime", "RANGING")
    rs = _regime_stats.setdefault(regime, {"wins": 0, "trades": 0})
    rs["trades"] += 1
    if result == "WIN": rs["wins"] += 1

    _last_signals[sym] = {
        "action":     signal["action"],
        "price":      signal["price"],
        "confidence": conf,
        "result":     result,
        "ev":         ev,
        "regime":     regime,
        "timestamp":  _time.time(),
    }

    # deque auto-evicts at maxlen=50
    _recent_results.append(result)


def get_metrics():
    m  = METRICS
    t  = m["trades"]
    # Effective winrate excludes neutral timeouts — directional trades only
    _decisive = m["wins"] + m["losses"]
    wr = m["wins"] / _decisive if _decisive else 0.0

    rr = list(_recent_results)
    recent_wr = (
        sum(1 for r in rr if r == "WIN") / len(rr)
        if rr else 0.0
    )

    # Need at least 10 session samples for a meaningful trend
    if len(rr) >= 10:
        delta = recent_wr - wr
        if   delta >  0.05: trend = "ZLEPŠUJE SE 📈"
        elif delta < -0.05: trend = "ZHORŠUJE SE 📉"
        else:               trend = "STABILNÍ ➡️"
    else:
        trend = "SBÍRÁ DATA..."

    # Derived
    gw = m["gross_wins"]
    gl = m["gross_losses"]
    profit_factor = gw / gl if gl > 0 else (99.0 if gw > 0 else 1.0)
    expectancy    = (wr * m["avg_win"]) - ((1 - wr) * m["avg_loss"])

    # Time since last trade
    since = _time.time() - m["last_trade_time"] if m["last_trade_time"] else None

    sym_stats = {
        sym: {**s, "winrate": s["wins"] / s["trades"] if s["trades"] else 0.0}
        for sym, s in _sym_stats.items()
    }

    _timeouts     = m.get("timeouts", 0)
    _timeout_rate = _timeouts / t if t else 0.0

    return {
        **m,
        "winrate":        wr,           # wins / (wins + real_losses) — excludes neutral timeouts
        "timeout_rate":   _timeout_rate,
        "ready":          t > 50 and wr > 0.55 and m["profit"] > 0,
        "recent_winrate": recent_wr,
        "recent_count":   len(rr),
        "learning_trend": trend,
        "profit_factor":  profit_factor,
        "expectancy":     expectancy,
        "since_last":     since,
        "last_prices":    dict(_last_prices),
        "last_signals":   dict(_last_signals),
        "sym_stats":      sym_stats,
        "ev_stats":       get_ev_stats(),
        "close_stats":    get_close_stats(),
        "regime_stats":   get_regime_stats(),
    }


def bootstrap_from_history(trades):
    """Rebuild METRICS from Firebase history on startup."""
    if not trades:
        print("📂 Bootstrap: žádná historická data")
        return

    m = METRICS
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

    # Prefer accurate total from Firestore atomic counter (avoids limit=100 cap).
    # The history query is capped at HISTORY_LIMIT (100–200 docs) so m["trades"]
    # would otherwise be off by however many older trades exist in the DB.
    _count_seeded = False
    try:
        from src.services.firebase_client import load_stats as _ls
        stats = _ls()
        total_count = stats.get("trades", 0)
        if total_count > len(sorted_trades):
            m["trades"]           = total_count
            m["signals_executed"] = total_count
            m["wins"]             = stats.get("wins",     0)
            m["losses"]           = stats.get("losses",   0)
            m["timeouts"]         = stats.get("timeouts", 0)
            _count_seeded = True
    except Exception:
        pass

    for trade in sorted_trades:
        result = trade.get("result")
        profit = float(trade.get("profit") or 0)
        sym    = trade.get("symbol")
        conf   = float(trade.get("confidence") or 0.5)
        if not result or not sym:
            continue

        # Skip counter increment when already seeded from atomic counter doc
        if not _count_seeded:
            m["trades"] += 1
            m["signals_executed"] += 1
        m["profit"] += profit
        m["last_trade_time"] = float(trade.get("timestamp") or 0)

        _bs_reason   = trade.get("close_reason", "")
        _BS_TIMEOUT_REASONS = {"timeout", "TIMEOUT_PROFIT", "TIMEOUT_FLAT", "TIMEOUT_LOSS",
                               "SCRATCH_EXIT", "STAGNATION_EXIT"}
        _bs_neutral  = (_bs_reason in _BS_TIMEOUT_REASONS and abs(profit) < 0.001)
        # neutral_timeout check MUST precede result=="WIN":
        # Firestore stores result="WIN" when pnl>0, even 0.0005 — a tiny-positive
        # timeout would otherwise be miscounted as a win and inflate WR.
        if _bs_neutral:
            m["timeouts"] = m.get("timeouts", 0) + 1
        elif result == "WIN":
            if not _count_seeded: m["wins"] += 1
            m["win_streak"] += 1; m["loss_streak"] = 0
            m["gross_wins"] += profit
            if profit > m["best_trade"]:  m["best_trade"] = profit
        else:
            if not _count_seeded: m["losses"] += 1
            m["loss_streak"] += 1; m["win_streak"] = 0
            m["gross_losses"] += abs(profit)
            if profit < m["worst_trade"]: m["worst_trade"] = profit

        m["equity_peak"] = max(m["equity_peak"], m["profit"])
        m["drawdown"]    = max(m["drawdown"], m["equity_peak"] - m["profit"])
        m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1
        _update_sym(sym, result, profit)

        # Bootstrap new trackers
        ev = float(trade.get("ev", 0))
        if ev > 0:
            _ev_history.append(ev)   # deque handles cap automatically
        reason = trade.get("close_reason", "")
        if reason in _close_reasons:
            _close_reasons[reason] += 1
        regime = trade.get("regime", "RANGING")
        rs = _regime_stats.setdefault(regime, {"wins": 0, "trades": 0})
        rs["trades"] += 1
        if result == "WIN": rs["wins"] += 1

    # Seed online calibrator from closed trades (must be after loop)
    try:
        from src.services.realtime_decision_engine import (
            calibrator, _seeded, update_edge_stats, _restore_full_state)
        _restore_full_state()   # load persisted calibrator/bayes/bandit FIRST
        for t in sorted_trades:
            p        = float(t.get("confidence", 0.5))
            result   = t.get("result")
            features = t.get("features", {})
            regime   = t.get("regime", "RANGING")
            if result in ("WIN", "LOSS"):
                outcome = 1 if result == "WIN" else 0
                calibrator.update(p, outcome)
                if features:
                    update_edge_stats(features, outcome, regime)
        _seeded[0] = True
        total  = sum(v[1] for v in calibrator.buckets.values())
        edge_n = sum(v[1] for v in
                     __import__("src.services.realtime_decision_engine",
                                fromlist=["edge_stats"]).edge_stats.values())
        print(f"🎯 Calibrator bootstrap: {total} samples  "
              f"buckets={calibrator.summary()}")
        print(f"🧠 Edge stats bootstrap: {edge_n} feature observations")
    except Exception as e:
        print(f"⚠️  Calibrator bootstrap skipped: {e}")

    if m["wins"]   > 0: m["avg_win"]  = m["gross_wins"]   / m["wins"]
    if m["losses"] > 0: m["avg_loss"] = m["gross_losses"]  / m["losses"]

    # Directly set confidence_avg from last 20 signals instead of EMA approximation
    conf_samples = [
        float(t.get("confidence") or 0.5)
        for t in sorted_trades[-20:]
        if t.get("result") in ("WIN", "LOSS")
    ]
    if conf_samples:
        m["confidence_avg"] = sum(conf_samples) / len(conf_samples)

    # Intentionally NOT seeding _recent_results from history.
    # The velocity guard in realtime_decision_engine uses list(_rr)[-5:] to
    # detect "3 losses in last 5 trades" — if we load historical results here,
    # a streak of losses at session-end would permanently block trading after
    # every restart until 2 in-session wins flip the ratio.
    # _recent_results must only contain in-session trades so the guard reflects
    # current performance, not stale history.  Streak (loss_streak / win_streak)
    # is tracked separately via METRICS which IS seeded from history below.
    _recent_results.clear()   # velocity guard: in-session trades only

    # Compute TRAILING streak from the last 30 historical trades rather than
    # resetting to 0.  A plain reset meant the MAX_LOSS_STREAK circuit-breaker
    # in realtime_decision_engine never fired after a loss run survived a
    # restart — the auditor always saw streak=0 and kept trading into losses.
    # We limit look-back to 30 trades so a single bad historic session doesn't
    # permanently halt a fresh session that is actually recovering.
    from itertools import takewhile as _tw
    _recent_closed = [
        t.get("result") for t in sorted_trades[-30:]
        if t.get("result") in ("WIN", "LOSS")
    ]
    m["loss_streak"] = sum(1 for _ in _tw(lambda r: r == "LOSS", reversed(_recent_closed)))
    m["win_streak"]  = sum(1 for _ in _tw(lambda r: r == "WIN",  reversed(_recent_closed)))

    # Seed learning monitor trade counts from history so lm_health() can
    # evaluate pairs immediately instead of waiting for 10 new in-session trades.
    # Use actual ws/features from Firebase doc when available (stored since
    # firebase_client._slim_trade now writes both fields).
    try:
        from src.services.learning_monitor import lm_update as _lmu
        from src.services.execution       import bandit_update as _bu
        for t in sorted_trades:
            sym    = t.get("symbol") or t.get("sym")
            reg    = t.get("regime", "RANGING")
            pnl    = float(t.get("profit") or 0)
            result = t.get("result")
            ws     = float(t.get("ws", 0.5))
            raw_f  = t.get("features") or {}
            feats  = {k: v for k, v in raw_f.items() if isinstance(v, bool)}
            if sym and result in ("WIN", "LOSS"):
                _lmu(sym, reg, pnl, ws, feats)
                # Seed bandit_stats so UCB scores diverge from 0.50 prior on boot
                _bu(sym, reg, max(-0.05, min(0.05, pnl)))
    except Exception:
        pass

    # Toxic history check — clear lm+bandit state if WR < 10% on 50+ trades.
    # Must run after lm_update seeding so the data exists to evaluate.
    try:
        from src.services.learning_monitor import reset_if_toxic as _rit
        _rit()
    except Exception:
        pass

    t  = m["trades"]
    _decisive = m["wins"] + m["losses"]
    wr = m["wins"] / _decisive if _decisive else 0.0
    print(f"📂 Bootstrap: {t} obchodů  WR:{wr*100:.1f}%  "
          f"zisk:{m['profit']:+.8f}  "
          f"posledních {len(_recent_results)} výsledků")


def track_generated(): METRICS["signals_generated"] += 1
def track_filtered():  METRICS["signals_filtered"]  += 1
def track_blocked(reason="UNKNOWN"):
    METRICS["blocked"] += 1
    METRICS["block_reasons"][reason] = METRICS["block_reasons"].get(reason, 0) + 1
def track_regime(r):
    if r in METRICS["regimes"]:
        METRICS["regimes"][r] += 1


def get_ev_stats():
    """Returns avg/min/max EV of last 50 executed trades."""
    ev = list(_ev_history)
    if not ev:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "count": 0}
    return {
        "avg":   round(sum(ev) / len(ev), 4),
        "min":   round(min(ev), 4),
        "max":   round(max(ev), 4),
        "count": len(ev),
    }


def get_close_stats():
    """Returns close-reason counts and percentages."""
    total = sum(_close_reasons.values())
    if not total:
        return {k: {"n": 0, "pct": 0.0} for k in _close_reasons}
    return {k: {"n": v, "pct": round(v / total * 100, 1)}
            for k, v in _close_reasons.items()}


def get_regime_stats():
    """Returns WR per regime for executed trades."""
    out = {}
    for regime, rs in _regime_stats.items():
        t = rs["trades"]
        out[regime] = {
            "trades": t,
            "winrate": round(rs["wins"] / t, 3) if t else 0.0,
        }
    return out


def trades_per_hour():
    """Estimated trade rate from last 60 minutes."""
    return trades_in_window(3600)


def real_ev():
    """PnL-based expectancy: wr×avg_win - (1-wr)×avg_loss. Returns 0 if insufficient data."""
    m  = METRICS
    _decisive = m["wins"] + m["losses"]   # excludes neutral timeouts
    if _decisive == 0 or m["wins"] == 0 or m["losses"] == 0:
        return 0.0
    wr = m["wins"] / _decisive
    return wr * m["avg_win"] - (1 - wr) * m["avg_loss"]
