from src.services.firebase_client import load_history
from src.services.learning_event import track_blocked, track_regime
import math, time

def decay(ts):
    return math.exp(-(time.time() - ts) / 3600)

def similarity(f1, f2):
    keys = ["ema_diff", "rsi", "volatility"]
    s = 0
    c = 0
    for k in keys:
        if k in f1 and k in f2:
            diff = abs(f1[k] - f2[k])
            norm = abs(f2[k]) or 1
            s += max(0, 1 - diff / norm)
            c += 1
    return s / c if c else 0

def detect_regime(f):
    v = f.get("volatility", 0)
    if v > 0.01: return "HIGH_VOL"
    if v < 0.002: return "CHOP"
    return "TREND"

def evaluate_signal(signal):
    history = load_history()
    f = signal["features"]

    regime = detect_regime(f)
    track_regime(regime)

    if not history:
        return signal

    similar = []
    for t in history:
        if t["symbol"] != signal["symbol"]:
            continue
        if t.get("action") != signal["action"]:
            continue
        sim = similarity(f, t.get("features", {}))
        if sim > 0.6:
            similar.append((t, sim * decay(t["timestamp"])))

    if len(similar) < 5:
        return signal

    w = sum(x[1] for x in similar)
    wins = sum(x[1] for x in similar if x[0]["result"] == "WIN")
    profit = sum(x[0]["profit"] * x[1] for x in similar)

    wr = wins / w if w else 0
    avg_p = profit / w if w else 0

    verdict = "✅ OK" if wr >= 0.45 else "🚫 BLK"
    print(f"    🧠 vzory:{len(similar)} WR:{wr:.0%} PnL:{avg_p:.5f} {regime} {verdict}")

    # Block only if winrate is clearly bad (avoid blocking on tiny avg_p noise)
    if wr < 0.45:
        track_blocked()
        return None

    signal["confidence"] *= (0.5 + wr)
    return signal
