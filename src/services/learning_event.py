import time as _time
import threading as _threading

_lock = _threading.Lock()

METRICS = {
    "trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
    "win_streak": 0, "loss_streak": 0,
    "equity_peak": 0.0, "drawdown": 0.0,
    "confidence_avg": 0.0,
    "signals_generated": 0,
    "signals_filtered": 0,
    "signals_executed": 0,
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
}

_last_prices    = {}
_last_signals   = {}
_recent_results = []
_sym_stats      = {}
_trade_times    = []   # rolling timestamps of completed trades
_ev_history     = []   # EV values of last 50 executed trades
_close_reasons  = {"TP": 0, "SL": 0, "trail": 0, "timeout": 0}
_regime_stats   = {}   # regime -> {"wins": int, "trades": int}


def track_price(symbol, price):
    prev = _last_prices.get(symbol, (price, price))[0]
    _last_prices[symbol] = (price, prev)


def _update_sym(symbol, result, profit):
    s = _sym_stats.setdefault(symbol, {"trades": 0, "wins": 0, "profit": 0.0})
    s["trades"] += 1
    if result == "WIN":
        s["wins"] += 1
    s["profit"] += profit


def trades_in_window(seconds=900):
    """Count completed trades in the last `seconds` seconds."""
    with _lock:
        cutoff = _time.time() - seconds
        return sum(1 for t in _trade_times if t > cutoff)


def update_metrics(signal, trade):
    with _lock:
        _trade_times.append(_time.time())
        if len(_trade_times) > 200:
            _trade_times.pop(0)
        return _update_metrics_locked(signal, trade)


def _update_metrics_locked(signal, trade):
    m      = METRICS
    profit = float(trade["profit"])
    result = trade["result"]
    sym    = signal["symbol"]
    conf   = float(signal.get("confidence", 0.5))

    m["trades"] += 1
    m["signals_executed"] += 1
    m["profit"] += profit
    m["last_trade_time"] = _time.time()

    if result == "WIN":
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
        m["avg_loss"]      = m["gross_losses"] / m["losses"]
        if profit < m["worst_trade"]:
            m["worst_trade"] = profit

    m["equity_peak"] = max(m["equity_peak"], m["profit"])
    m["drawdown"]    = max(m["drawdown"], m["equity_peak"] - m["profit"])
    m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1

    _update_sym(sym, result, profit)

    # EV history (last 50 executed trades)
    ev = float(signal.get("ev", 0))
    if ev > 0:
        _ev_history.append(ev)
        if len(_ev_history) > 50: _ev_history.pop(0)

    # Close-reason breakdown
    reason = trade.get("close_reason", "")
    if reason in _close_reasons:
        _close_reasons[reason] += 1

    # Regime-specific WR
    regime = signal.get("regime", "RANGING")
    rs = _regime_stats.setdefault(regime, {"wins": 0, "trades": 0})
    rs["trades"] += 1
    if result == "WIN": rs["wins"] += 1

    _last_signals[sym] = {
        "action": signal["action"], "price": signal["price"],
        "confidence": conf, "result": result,
        "ev": ev, "regime": regime,
    }

    _recent_results.append(result)
    if len(_recent_results) > 50:
        _recent_results.pop(0)


def get_metrics():
    m  = METRICS
    t  = m["trades"]
    wr = m["wins"] / t if t else 0.0

    recent_wr = (
        sum(1 for r in _recent_results if r == "WIN") / len(_recent_results)
        if _recent_results else 0.0
    )

    if t >= 20:
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

    return {
        **m,
        "winrate":        wr,
        "ready":          t > 50 and wr > 0.55 and m["profit"] > 0,
        "recent_winrate": recent_wr,
        "recent_count":   len(_recent_results),
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

    global _recent_results
    m = METRICS
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", 0))

    for trade in sorted_trades:
        result = trade.get("result")
        profit = float(trade.get("profit") or 0)
        sym    = trade.get("symbol")
        conf   = float(trade.get("confidence") or 0.5)
        if not result or not sym:
            continue

        m["trades"] += 1
        m["signals_executed"] += 1
        m["profit"] += profit
        m["last_trade_time"] = float(trade.get("timestamp") or 0)

        if result == "WIN":
            m["wins"] += 1; m["win_streak"] += 1; m["loss_streak"] = 0
            m["gross_wins"] += profit
            if profit > m["best_trade"]:  m["best_trade"] = profit
        else:
            m["losses"] += 1; m["loss_streak"] += 1; m["win_streak"] = 0
            m["gross_losses"] += abs(profit)
            if profit < m["worst_trade"]: m["worst_trade"] = profit

        m["equity_peak"] = max(m["equity_peak"], m["profit"])
        m["drawdown"]    = max(m["drawdown"], m["equity_peak"] - m["profit"])
        m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1
        _update_sym(sym, result, profit)

        # Bootstrap new trackers
        ev = float(trade.get("ev", 0))
        if ev > 0:
            _ev_history.append(ev)
        reason = trade.get("close_reason", "")
        if reason in _close_reasons:
            _close_reasons[reason] += 1
        regime = trade.get("regime", "RANGING")
        rs = _regime_stats.setdefault(regime, {"wins": 0, "trades": 0})
        rs["trades"] += 1
        if result == "WIN": rs["wins"] += 1

    if len(_ev_history) > 50: _ev_history[:] = _ev_history[-50:]

    # Seed online calibrator from closed trades (must be after loop)
    try:
        from src.services.realtime_decision_engine import (
            calibrator, _seeded, update_edge_stats)
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

    _recent_results = [
        t["result"] for t in sorted_trades[-50:]
        if t.get("result") in ("WIN", "LOSS")
    ]

    t  = m["trades"]
    wr = m["wins"] / t if t else 0
    print(f"📂 Bootstrap: {t} obchodů  WR:{wr*100:.1f}%  "
          f"zisk:{m['profit']:+.8f}  "
          f"posledních {len(_recent_results)} výsledků")


def track_generated(): METRICS["signals_generated"] += 1
def track_filtered():  METRICS["signals_filtered"]  += 1
def track_blocked():   METRICS["blocked"]           += 1
def track_regime(r):
    if r in METRICS["regimes"]:
        METRICS["regimes"][r] += 1


def get_ev_stats():
    """Returns avg/min/max EV of last 50 executed trades."""
    if not _ev_history:
        return {"avg": 0.0, "min": 0.0, "max": 0.0, "count": 0}
    return {
        "avg":   round(sum(_ev_history) / len(_ev_history), 4),
        "min":   round(min(_ev_history), 4),
        "max":   round(max(_ev_history), 4),
        "count": len(_ev_history),
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
