METRICS = {
    "trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
    "win_streak": 0, "loss_streak": 0,
    "equity_peak": 0.0, "drawdown": 0.0,
    "confidence_avg": 0.0,
    "signals_generated": 0,
    "signals_filtered": 0,
    "signals_executed": 0,
    "blocked": 0,
    "regimes": {"TREND": 0, "CHOP": 0, "HIGH_VOL": 0},
}

_last_prices  = {}   # symbol -> (current, prev)
_last_signals = {}   # symbol -> {action, price, confidence, result}
_recent_results = [] # last 20 outcomes for trend detection

# Per-symbol stats: symbol -> {trades, wins, profit}
_sym_stats = {}


def track_price(symbol, price):
    prev = _last_prices.get(symbol, (price, price))[0]
    _last_prices[symbol] = (price, prev)


def _update_sym(symbol, result, profit):
    s = _sym_stats.setdefault(symbol, {"trades": 0, "wins": 0, "profit": 0.0})
    s["trades"] += 1
    if result == "WIN":
        s["wins"] += 1
    s["profit"] += profit


def update_metrics(signal, trade):
    m = METRICS
    m["trades"] += 1
    m["signals_executed"] += 1

    profit = trade["profit"]
    result = trade["result"]
    m["profit"] += profit

    if result == "WIN":
        m["wins"] += 1
        m["win_streak"] += 1
        m["loss_streak"] = 0
    else:
        m["losses"] += 1
        m["loss_streak"] += 1
        m["win_streak"] = 0

    m["equity_peak"] = max(m["equity_peak"], m["profit"])
    m["drawdown"]    = max(m["drawdown"], m["equity_peak"] - m["profit"])

    conf = signal.get("confidence", 0.5)
    m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1

    # Per-symbol tracking
    sym = signal["symbol"]
    _update_sym(sym, result, profit)

    # Last signal state
    _last_signals[sym] = {
        "action":     signal["action"],
        "price":      signal["price"],
        "confidence": conf,
        "result":     result,
    }

    # Recent trend window (last 20)
    _recent_results.append(result)
    if len(_recent_results) > 20:
        _recent_results.pop(0)


def get_metrics():
    m  = METRICS
    t  = m["trades"]
    wr = m["wins"] / t if t else 0

    recent_wr = 0.0
    if _recent_results:
        recent_wr = sum(1 for r in _recent_results if r == "WIN") / len(_recent_results)

    if t >= 20:
        if recent_wr > wr + 0.05:
            trend = "ZLEPŠUJE SE 📈"
        elif recent_wr < wr - 0.05:
            trend = "ZHORŠUJE SE 📉"
        else:
            trend = "STABILNÍ ➡️"
    else:
        trend = "SBÍRÁ DATA..."

    # Per-symbol winrates
    sym_stats = {}
    for sym, s in _sym_stats.items():
        sym_wr = s["wins"] / s["trades"] if s["trades"] else 0
        sym_stats[sym] = {**s, "winrate": sym_wr}

    return {
        **m,
        "winrate":       wr,
        "ready":         t > 50 and wr > 0.55 and m["profit"] > 0,
        "recent_winrate": recent_wr,
        "recent_count":  len(_recent_results),
        "learning_trend": trend,
        "last_prices":   dict(_last_prices),
        "last_signals":  dict(_last_signals),
        "sym_stats":     sym_stats,
    }


def track_generated(): METRICS["signals_generated"] += 1
def track_filtered():  METRICS["signals_filtered"] += 1
def track_blocked():   METRICS["blocked"] += 1
def track_regime(r):
    if r in METRICS["regimes"]:
        METRICS["regimes"][r] += 1
