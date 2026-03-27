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

from bot2.strategy_weights import StrategyWeights
from src.services.learning_event import get_metrics
from src.services.firebase_client import save_auditor_state, load_auditor_state
import time as _time

_weights = StrategyWeights()

_min_confidence     = 0.55
_position_size_mult = 1.0
_cooldown           = 0
_prev_loss_streak   = -1   # -1 = unset (skip bootstrap)
_initialized        = False
_cached_weights     = {}
_dd_halt_until      = 0.0

DD_HALT_THR  = 0.40    # 40% relative drawdown (was 5% — too sensitive for paper trading)
DD_HALT_MIN  = 0.050   # minimum absolute DD to prevent false trigger on tiny equity
DD_HALT_SECS = 1800    # pause duration: 30 min


# ── Public API ────────────────────────────────────────────────────────────────

def get_min_confidence() -> float:
    return _min_confidence

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
    global _min_confidence, _position_size_mult, _cooldown
    global _prev_loss_streak, _initialized, _cached_weights, _dd_halt_until

    m = get_metrics()

    if _cooldown > 0:
        _cooldown -= 1

    loss_streak = m.get("loss_streak", 0)
    win_streak  = m.get("win_streak",  0)
    rwr         = m.get("recent_winrate", 0.0)
    rc          = m.get("recent_count",  0)
    t           = m.get("trades",        0)
    since       = m.get("since_last")

    # ── First run: restore persisted state, snapshot bootstrap ──────────────
    if not _initialized:
        _prev_loss_streak = loss_streak
        _initialized = True
        try:
            saved = load_auditor_state()
            if saved.get("min_conf"):
                _min_confidence     = float(saved["min_conf"])
                _position_size_mult = float(saved.get("pos_size_mult", 1.0))
                # dd_halt_until intentionally NOT restored — halt resets on restart
                print(f"  🔍 AUDITOR restored: conf={_min_confidence:.2f}  sz={_position_size_mult:.2f}")
            else:
                print(f"  🔍 AUDITOR init: bootstrap streak={loss_streak}  (no saved state)")
        except Exception:
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
        _position_size_mult = 0.60
    else:
        _position_size_mult = 1.0

    # ── Dynamic min_confidence: streak-based (max 0.65 at streak=5) ─────────
    # Win streak lowers threshold (reward), loss streak raises it (protection).
    base = min(0.55 + loss_streak * 0.02, 0.65)

    # Win streak reward: 2+ consecutive wins → lower threshold
    if win_streak >= 2:
        base = max(base - 0.02, 0.50)

    # Exploration mode: no trades for 15 min → lower threshold by 0.10
    if since and since > 900:
        base = max(0.45, base - 0.10)

    # Hysteresis clamp: never outside [0.50, 0.65]
    base = min(max(base, 0.50), 0.65)

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
        if passed_rt < 0.05 and base > 0.50:
            base = max(0.45, base - 0.05)
            print(f"  ⚠️  FILTER COLLAPSE: pass={passed_rt:.1%} → min_conf={base:.2f}")

    # ── Deadlock: no trades for 20 min (or no signals at all) → hard reset ───
    if since and since > 1200 and (gen == 0 or gen > 50):
        _min_confidence = 0.50
        _cooldown       = 0
        base            = 0.50
        print(f"  🔓 DEADLOCK RESET: {since/60:.0f}min no trades (gen={gen}) → conf=0.50  cooldown=0")

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

    cd_tag   = f"  ⏸{_cooldown}" if _cooldown   > 0   else ""
    sz_tag   = f"  sz×{_position_size_mult:.2f}" if _position_size_mult < 1.0 else ""
    print(f"  🔍 AUDITOR: conf={_min_confidence:.2f}  streak={loss_streak}"
          f"  WR:{rwr:.0%}{cd_tag}{sz_tag}")

    # Persist state so it survives restarts
    try:
        save_auditor_state({
            "min_conf":      round(_min_confidence, 4),
            "pos_size_mult": round(_position_size_mult, 4),
            "loss_streak":   loss_streak,
            "win_streak":    win_streak,
            "cooldown":      _cooldown,
        })
    except Exception:
        pass
