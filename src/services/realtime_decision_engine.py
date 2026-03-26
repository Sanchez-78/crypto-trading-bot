"""
Historical pattern filter.

Compares incoming signal features against last 100 trades
(same symbol, same action direction).
Rejects if weighted winrate of similar past trades < 45%.
Time-decays older trades (half-life = 1 hour).
"""

from src.services.firebase_client import load_history
from src.services.learning_event import track_blocked, track_regime
import math, time

# Lazy import to avoid circular dependency at module load time
def _auditor():
    from bot2.auditor import get_min_confidence, is_in_cooldown
    return get_min_confidence, is_in_cooldown


def _decay(ts):
    return math.exp(-(time.time() - ts) / 3600)


def _sim(f1, f2):
    keys = ["ema_diff", "rsi", "volatility", "macd"]
    sc, n = 0, 0
    for k in keys:
        if k in f1 and k in f2:
            diff = abs(f1[k] - f2[k])
            norm = abs(f2[k]) or 1
            sc += max(0, 1 - diff / norm)
            n  += 1
    return sc / n if n else 0


def evaluate_signal(signal):
    # ── Auditor gates (cooldown + dynamic confidence threshold) ───────────────
    try:
        get_min_conf, in_cooldown = _auditor()
        if in_cooldown():
            track_blocked()
            print("    ⏸ signal zamítnut – auditor cooldown")
            return None
        min_conf = get_min_conf()
    except Exception:
        min_conf = 0.60   # fallback if auditor not yet initialised

    if signal.get("confidence", 0) < min_conf:
        track_blocked()
        return None

    history = load_history()
    f       = signal["features"]
    reg     = signal.get("regime", "RANGING")

    track_regime(reg)

    if not history:
        return signal

    similar = []
    for t in history:
        if t["symbol"] != signal["symbol"]:
            continue
        if t.get("action") != signal["action"]:
            continue
        sim = _sim(f, t.get("features", {}))
        if sim > 0.6:
            similar.append((t, sim * _decay(t["timestamp"])))

    if len(similar) < 5:
        return signal  # not enough history → pass through

    w    = sum(x[1] for x in similar) or 1e-9
    wins = sum(x[1] for x in similar if x[0]["result"] == "WIN")
    wr   = wins / w

    verdict = "✅" if wr >= 0.45 else "🚫"
    print(f"    🧠 {len(similar)} vzorů  WR:{wr:.0%}  {reg}  {verdict}")

    if wr < 0.45:
        track_blocked()
        return None

    signal["confidence"] *= (0.5 + wr)
    return signal
