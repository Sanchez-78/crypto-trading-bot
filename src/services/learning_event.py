METRICS = {
    "trades": 0, "wins": 0, "losses": 0, "profit": 0.0,
    "win_streak": 0, "loss_streak": 0,
    "equity_peak": 0.0, "drawdown": 0.0,
    "confidence_avg": 0.0,
    "signals_generated": 0,
    "signals_filtered": 0,
    "signals_executed": 0,
    "blocked": 0,
    "regimes": {"TREND": 0, "CHOP": 0, "HIGH_VOL": 0}
}

def update_metrics(signal, trade):
    m = METRICS
    m["trades"] += 1
    m["signals_executed"] += 1

    profit = trade["profit"]
    m["profit"] += profit

    if trade["result"] == "WIN":
        m["wins"] += 1
        m["win_streak"] += 1
        m["loss_streak"] = 0
    else:
        m["losses"] += 1
        m["loss_streak"] += 1
        m["win_streak"] = 0

    m["equity_peak"] = max(m["equity_peak"], m["profit"])
    dd = m["equity_peak"] - m["profit"]
    m["drawdown"] = max(m["drawdown"], dd)

    conf = signal.get("confidence", 0.5)
    m["confidence_avg"] = m["confidence_avg"] * 0.9 + conf * 0.1


def get_metrics():
    m = METRICS
    t = m["trades"]
    winrate = m["wins"] / t if t else 0

    ready = t > 50 and winrate > 0.55 and m["profit"] > 0

    return {
        **m,
        "winrate": winrate,
        "ready": ready
    }


def track_generated(): METRICS["signals_generated"] += 1
def track_filtered(): METRICS["signals_filtered"] += 1
def track_blocked(): METRICS["blocked"] += 1
def track_regime(r): 
    if r in METRICS["regimes"]:
        METRICS["regimes"][r] += 1