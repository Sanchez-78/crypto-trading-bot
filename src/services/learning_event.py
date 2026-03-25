# src/services/learning_event.py

METRICS = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
    "last_results": [],
    "confidence_avg": 0.0,
    "learning_score": 0.0
}


def update_metrics(trade, result):
    global METRICS

    METRICS["trades"] += 1

    profit = result.get("profit", 0)
    METRICS["profit"] += profit

    if result.get("result") == "WIN":
        METRICS["wins"] += 1
    else:
        METRICS["losses"] += 1

    # sliding window
    METRICS["last_results"].append(result.get("result"))
    if len(METRICS["last_results"]) > 50:
        METRICS["last_results"] = METRICS["last_results"][-50:]

    # confidence tracking
    conf = trade.get("confidence", 0.5)
    METRICS["confidence_avg"] = (
        METRICS["confidence_avg"] * 0.9 + conf * 0.1
    )

    # learning score (kombinace winrate + profit + stabilita)
    winrate = get_winrate()
    stability = METRICS["last_results"].count("WIN") / max(1, len(METRICS["last_results"]))

    METRICS["learning_score"] = (winrate * 0.5) + (stability * 0.3) + (min(METRICS["profit"], 1) * 0.2)


def get_winrate():
    t = METRICS["trades"]
    return METRICS["wins"] / t if t > 0 else 0


def is_ready():
    if METRICS["trades"] < 30:
        return False

    if get_winrate() < 0.55:
        return False

    if METRICS["profit"] <= 0:
        return False

    return True


def get_metrics():
    return {
        "trades": METRICS["trades"],
        "winrate": round(get_winrate(), 3),
        "profit": round(METRICS["profit"], 4),
        "confidence": round(METRICS["confidence_avg"], 3),
        "learning_score": round(METRICS["learning_score"], 3),
        "ready": is_ready()
    }