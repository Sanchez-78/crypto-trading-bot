import math

trade_memory = []


# =========================
# INIT MEMORY
# =========================
def load_memory(trades):
    global trade_memory

    trade_memory = trades
    print(f"🧠 Decision memory loaded: {len(trade_memory)} trades")


# =========================
# SIMILARITY
# =========================
def similarity(a, b):
    if not a or not b:
        return 0

    keys = set(a.keys()) & set(b.keys())
    if not keys:
        return 0

    score = 0

    for k in keys:
        try:
            diff = abs(a[k] - b[k])
            score += 1 / (1 + diff)
        except:
            continue

    return score / len(keys)


# =========================
# DECISION FILTER
# =========================
def evaluate_signal(signal):
    global trade_memory

    if not trade_memory:
        return signal

    features = signal.get("features", {})
    action = signal.get("action")

    similar = []

    for trade in trade_memory[-200:]:
        if trade.get("action") != action:
            continue

        sim = similarity(features, trade.get("features", {}))

        if sim > 0.7:
            similar.append(trade)

    if not similar:
        return signal

    wins = sum(1 for t in similar if t.get("result") == "WIN")
    losses = sum(1 for t in similar if t.get("result") == "LOSS")

    total = wins + losses
    winrate = wins / total if total > 0 else 0.5

    print(f"🧠 Pattern winrate: {winrate:.2f} ({wins}/{total})")

    # =========================
    # FILTER
    # =========================
    if winrate < 0.45:
        print("❌ REJECTED by history")
        return None

    # =========================
    # BOOST CONFIDENCE
    # =========================
    signal["confidence"] *= (0.5 + winrate)

    return signal


# =========================
# UPDATE MEMORY
# =========================
def update_memory(trade, result):
    global trade_memory

    trade_memory.append({
        "action": trade.get("action"),
        "features": trade.get("features", {}),
        "result": result.get("result")
    })