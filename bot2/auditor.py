"""
Auditor – periodic strategy reviewer.

NO hard stop. Instead:
  - loss_streak ≥ 3 → position size × 0.5
  - loss_streak ≥ 5 → position size × 0.25 (defensive)
  - loss_streak ≥ 4 AND grew this session → cooldown 1 cycle (~30s)
  - no trades 15 min → lower min_conf (exploration mode)

Parameters:
  min_conf base: 0.55
  no-trade: -0.05
  loss streak: +0.02/loss (up to 0.70)
"""

from bot2.stabilizer       import Stabilizer
from bot2.strategy_weights import StrategyWeights
from src.services.learning_event import get_metrics

_stab    = Stabilizer()
_weights = StrategyWeights()

_min_confidence     = 0.55
_position_size_mult = 1.0
_cooldown           = 0
_prev_loss_streak   = -1   # -1 = unset (skip bootstrap)
_initialized        = False
_cached_weights     = {}


# ── Public API ────────────────────────────────────────────────────────────────

def get_min_confidence() -> float:
    return _min_confidence

def is_in_cooldown() -> bool:
    return _cooldown > 0

def get_position_size_mult() -> float:
    return _position_size_mult

def get_strategy_weights() -> dict:
    return dict(_cached_weights) if _cached_weights else {}


# ── Main audit cycle ──────────────────────────────────────────────────────────

def run_audit():
    global _min_confidence, _position_size_mult, _cooldown
    global _prev_loss_streak, _initialized, _cached_weights

    m = get_metrics()

    if _cooldown > 0:
        _cooldown -= 1

    loss_streak = m.get("loss_streak", 0)
    rwr         = m.get("recent_winrate", 0.0)
    rc          = m.get("recent_count",  0)
    t           = m.get("trades",        0)
    since       = m.get("since_last")

    # ── First run: snapshot bootstrap state, no cooldown ─────────────────────
    if not _initialized:
        _prev_loss_streak = loss_streak
        _initialized = True
        print(f"  🔍 AUDITOR init: bootstrap streak={loss_streak}  (no cooldown)")
        return

    # ── Cooldown: only if streak GREW in this session AND hit ≥ 4 ────────────
    if loss_streak > _prev_loss_streak and loss_streak >= 4 and _cooldown == 0:
        _cooldown = 1
        print(f"  ⚠️  AUDITOR: streak {loss_streak}x → cooldown 1 cyklus")

    _prev_loss_streak = loss_streak

    # ── Position size (no hard block — just scale down) ───────────────────────
    if loss_streak >= 5:
        _position_size_mult = 0.30
    elif loss_streak >= 3:
        _position_size_mult = 0.50
    else:
        _position_size_mult = 1.0

    # ── Dynamic min_confidence ────────────────────────────────────────────────
    if rc >= 5:
        if   rwr < 0.30: base = 0.70
        elif rwr < 0.45: base = 0.62
        elif rwr > 0.60: base = 0.50
        else:            base = 0.55
    else:
        base = 0.55

    # Exploration mode: no trades for 15 min → lower threshold
    if since and since > 900:
        base = max(0.45, base - 0.05)

    if abs(base - _min_confidence) >= 0.02:
        since_s = f"  since:{since:.0f}s" if since else ""
        print(f"  🧠 AUDITOR: min_conf {_min_confidence:.2f}→{base:.2f}"
              f"  WR:{rwr:.0%}  streak:{loss_streak}{since_s}")
        _min_confidence = base

    # ── Anti-collapse: filter pass-rate < 2% → lower min_conf ───────────────
    gen = m.get("signals_generated", 0)
    flt = m.get("signals_filtered",  0)
    blk = m.get("blocked", 0)
    if gen > 50:
        passed_rt = max(0, gen - flt - blk) / gen
        if passed_rt < 0.02 and base > 0.50:
            base = max(0.45, base - 0.05)
            print(f"  ⚠️  FILTER COLLAPSE: pass={passed_rt:.1%} → min_conf={base:.2f}")

    # ── Deadlock: signals generated but no trades for 20 min → hard reset ────
    if since and since > 1200 and gen > 50:
        if _min_confidence > 0.50 or _cooldown > 0:
            _min_confidence = 0.50
            _cooldown       = 0
            base            = 0.50
            print(f"  🔓 DEADLOCK RESET: {since/60:.0f}min no trades → conf=0.50  cooldown=0")

    # ── Strategy weights ──────────────────────────────────────────────────────
    if t >= 10:
        try:
            w = _weights.update()
            if w:
                _cached_weights = w
                best = max(w, key=w.get)
                print(f"  📊 AUDITOR: best={best}  w={w[best]:.2f}")
        except Exception:
            pass

    cd_tag   = f"  ⏸{_cooldown}" if _cooldown   > 0   else ""
    sz_tag   = f"  sz×{_position_size_mult:.2f}" if _position_size_mult < 1.0 else ""
    print(f"  🔍 AUDITOR: conf={_min_confidence:.2f}  streak={loss_streak}"
          f"  WR:{rwr:.0%}{cd_tag}{sz_tag}")
