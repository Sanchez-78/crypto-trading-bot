import time
from src.services.firebase_client import load_trade_history

# =========================
# CACHE (low-cost Firebase usage)
# =========================
CACHE = {
    "data": [],
    "last_update": 0
}

CACHE_TTL = 60  # 🔥 refresh z DB max 1x za minutu


# =========================
# LOAD / CACHE
# =========================
def get_cached_history():
    global CACHE

    now = time.time()

    if now - CACHE["last_update"] > CACHE_TTL:
        print("📥 Loading history from Firebase...")
        CACHE["data"] = load_trade_history(limit=50)
        CACHE["last_update"] = now
        print(f"📊 Loaded {len(CACHE['data'])} trades")

    return CACHE["data"]


# =========================
# SIMILARITY
# =========================
def similarity(f1, f2):
    try:
        keys = ["ema_short", "ema_long", "rsi", "volatility"]

        score = 0
        count = 0

        for k in keys:
            if k in f1 and k in f2:
                v1 = f1[k]
                v2 = f2[k]

                if v1 is None or v2 is None:
                    continue

                diff = abs(v1 - v2)

                # normalizace
                norm = abs(v2) if abs(v2) > 0 else 1

                sim = max(0, 1 - (diff / norm))

                score += sim
                count += 1

        if count == 0:
            return 0

        return score / count

    except Exception as e:
        print("❌ similarity error:", e)
        return 0


# =========================
# MAIN DECISION ENGINE
# =========================
def evaluate_signal(signal):
    history = get_cached_history()

    symbol = signal.get("symbol")
    action = signal.get("action")
    features = signal.get("features", {})

    relevant = [
        t for t in history
        if t.get("symbol") == symbol
        and t.get("action") == action
    ]

    # 🔥 málo dat → nech projít
    if len(relevant) < 5:
        return signal

    similar = []

    for t in relevant:
        sim = similarity(features, t.get("features", {}))

        if sim > 0.6:
            similar.append(t)

    # 🔥 málo podobných → snížit confidence
    if len(similar) < 3:
        signal["confidence"] *= 0.9
        return signal

    wins = sum(1 for t in similar if t.get("result") == "WIN")
    losses = sum(1 for t in similar if t.get("result") == "LOSS")

    total = wins + losses

    if total == 0:
        return signal

    winrate = wins / total
    avg_profit = sum(t.get("profit", 0) for t in similar) / total

    print(f"🧠 WR={winrate:.2f} | N={total} | PnL={avg_profit:.4f}")

    # 🔥 hard filtr (zabraňuje ztrátám)
    if winrate < 0.45 or avg_profit < 0:
        print("⛔ BLOCKED by history")
        return None

    # 🔥 posílení confidence
    signal["confidence"] *= (0.5 + winrate)
    signal["confidence"] = min(signal["confidence"], 1.0)

    return signal


# =========================
# LIVE UPDATE FROM TRADES
# =========================
def update_from_trade(trade, result):
    global CACHE

    if not isinstance(CACHE.get("data"), list):
        CACHE["data"] = []

    CACHE["data"].append({
        "symbol": trade.get("symbol"),
        "action": trade.get("action"),
        "features": trade.get("features", {}),
        "result": result.get("result"),
        "profit": result.get("profit", 0)
    })

    # 🔥 držíme limit (RAM + rychlost)
    if len(CACHE["data"]) > 100:
        CACHE["data"] = CACHE["data"][-100:]