"""
Auditor – periodic strategy reviewer.

NO hard stop. Instead:
  - loss_streak ≥ 3 → position size × 0.60
  - loss_streak ≥ 5 → position size × 0.30 (defensive)
  - loss_streak ≥ 4 AND grew this session → cooldown 1 cycle (~30s)

EV threshold is managed by realtime_decision_engine (not auditor).
"""

from bot2.strategy_weights import StrategyWeights
from src.services.learning_event import get_metrics
from src.services.firebase_client import save_auditor_state, load_auditor_state
import time as _time

_weights = StrategyWeights()

_position_size_mult = 1.0
_cooldown           = 0
_prev_loss_streak   = -1   # -1 = unset (skip bootstrap)
_initialized        = False
_cached_weights     = {}
_dd_halt_until      = 0.0

DD_HALT_THR  = 0.40    # 40% relative drawdown
DD_HALT_MIN  = 0.050   # minimum absolute DD to prevent false trigger on tiny equity
DD_HALT_SECS = 1800    # pause duration: 30 min


# ── Public API ────────────────────────────────────────────────────────────────

def is_in_cooldown() -> bool:
    return _cooldown > 0

def is_halted() -> bool:
    return _time.time() < _dd_halt_until

def get_position_size_mult() -> float:
    return _position_size_mult

def get_strategy_weights() -> dict:
    return dict(_cached_weights) if _cached_weights else {}


# ── Main audit cycle ──────────────────────────────────────────────────────────

def run_audit():
    global _position_size_mult, _cooldown
    global _prev_loss_streak, _initialized, _cached_weights, _dd_halt_until

    m = get_metrics()

    if _cooldown > 0:
        _cooldown -= 1

    loss_streak = m.get("loss_streak", 0)
    win_streak  = m.get("win_streak",  0)
    rwr         = m.get("recent_winrate", 0.0)
    t           = m.get("trades",        0)

    # ── First run: restore persisted state ───────────────────────────────────
    if not _initialized:
        _prev_loss_streak = loss_streak
        _initialized = True
        try:
            saved = load_auditor_state()
            if saved.get("pos_size_mult"):
                _position_size_mult = float(saved["pos_size_mult"])
                print(f"  🔍 AUDITOR restored: sz={_position_size_mult:.2f}")
            else:
                print(f"  🔍 AUDITOR init: bootstrap streak={loss_streak}")
        except Exception:
            print(f"  🔍 AUDITOR init: bootstrap streak={loss_streak}")
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
        _position_size_mult = 0.60
    else:
        _position_size_mult = 1.0

    # ── Drawdown circuit breaker ──────────────────────────────────────────────
    ep = m.get("equity_peak", 0)
    dd = m.get("drawdown",    0)
    if ep > 0 and dd >= DD_HALT_MIN:
        dd_pct = dd / ep
        if dd_pct >= DD_HALT_THR and not is_halted():
            _dd_halt_until = _time.time() + DD_HALT_SECS
            print(f"  🚨 DRAWDOWN HALT: {dd_pct:.1%}  abs={dd:.6f} → pause {DD_HALT_SECS//60}min")
    elif is_halted():
        rem = (_dd_halt_until - _time.time()) / 60
        print(f"  ⏸ DD HALT: {rem:.0f}min zbývá")

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

    cd_tag = f"  ⏸{_cooldown}" if _cooldown   > 0   else ""
    sz_tag = f"  sz×{_position_size_mult:.2f}" if _position_size_mult < 1.0 else ""
    print(f"  🔍 AUDITOR: streak={loss_streak}  WR:{rwr:.0%}{cd_tag}{sz_tag}")

    # Persist state so it survives restarts
    try:
        save_auditor_state({
            "pos_size_mult": round(_position_size_mult, 4),
            "loss_streak":   loss_streak,
            "win_streak":    win_streak,
            "cooldown":      _cooldown,
        })
    except Exception:
        pass
