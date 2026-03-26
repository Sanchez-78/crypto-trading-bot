"""
Auditor – periodic strategy reviewer.

Runs every 30 s in the main loop.
Reads live metrics, updates Stabilizer, and exposes two values
that realtime_decision_engine reads before every signal:

    get_min_confidence() → float  (0.50 – 0.75)
    is_in_cooldown()     → bool   (blocks all trading when True)

Also logs a short audit report so the user can see what it decided.
"""

from bot2.stabilizer     import Stabilizer
from bot2.strategy_weights import StrategyWeights
from src.services.learning_event import get_metrics

# ── Singleton state ───────────────────────────────────────────────────────────

_stab    = Stabilizer()
_weights = StrategyWeights()

_min_confidence  = 0.6
_cooldown        = 0       # ticks remaining


# ── Public API (read by realtime_decision_engine) ─────────────────────────────

def get_min_confidence() -> float:
    return _min_confidence


def is_in_cooldown() -> bool:
    return _cooldown > 0


# ── Main audit cycle ──────────────────────────────────────────────────────────

def run_audit():
    global _min_confidence, _cooldown

    m = get_metrics()

    # Decrement cooldown counter each audit cycle (every 30 s)
    if _cooldown > 0:
        _cooldown -= 1

    loss_streak = m.get("loss_streak", 0)
    rwr         = m.get("recent_winrate", 0.0)
    rc          = m.get("recent_count", 0)
    t           = m.get("trades", 0)

    # ── Cooldown: 3+ losses in a row → pause 3 cycles (~90 s) ────────────────
    if loss_streak >= 3 and _cooldown == 0:
        _cooldown = 3
        print(f"  🛑 AUDITOR: {loss_streak}x prohra v řadě → cooldown {_cooldown} cyklů")

    # ── Dynamic min_confidence based on recent winrate ────────────────────────
    if rc >= 10:
        if rwr < 0.30:
            new_conf = 0.75     # very bad  → demand high confidence
        elif rwr < 0.45:
            new_conf = 0.65     # below avg → tighten
        elif rwr > 0.60:
            new_conf = 0.50     # good      → relax
        else:
            new_conf = 0.60     # normal
    else:
        new_conf = 0.60         # not enough data → default

    if abs(new_conf - _min_confidence) >= 0.05:
        print(f"  🧠 AUDITOR: min_confidence  {_min_confidence:.2f} → {new_conf:.2f}"
              f"  (posledních {rc} obchodů  WR:{rwr:.0%})")
        _min_confidence = new_conf

    # ── Strategy weights (refresh every audit cycle) ──────────────────────────
    if t >= 10:
        try:
            weights = _weights.update()
            if weights:
                best = max(weights, key=weights.get)
                print(f"  📊 AUDITOR: nejlepší strategie → {best}  "
                      f"(váha {weights[best]:.2f})")
        except Exception as e:
            pass   # Firebase unavailable → skip silently

    # Status line
    cd_tag = f"  ⏸ cooldown {_cooldown}" if _cooldown > 0 else ""
    print(f"  🔍 AUDITOR: min_conf={_min_confidence:.2f}  "
          f"loss_streak={loss_streak}  recent_WR={rwr:.0%}{cd_tag}")
