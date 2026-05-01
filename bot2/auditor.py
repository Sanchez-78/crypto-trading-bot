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
from src.services.firebase_client import save_auditor_state, load_auditor_state, save_bot2_advice
import time as _time
import logging as _logging
import threading as _threading

_log = _logging.getLogger(__name__)

_weights = StrategyWeights()

_auditor_lock = _threading.Lock()  # BUG-024 fix: protect global state
_position_size_mult  = 1.0
_cooldown            = 0
_prev_loss_streak    = -1   # -1 = unset (skip bootstrap)
_initialized         = False
_cached_weights      = {}
_dd_halt_until       = 0.0
_monotone_violations = 0    # V10.14.b: monotone corruption counter

DD_HALT_THR  = 0.40    # 40% relative drawdown
DD_HALT_MIN  = 0.050   # minimum absolute DD to prevent false trigger on tiny equity
DD_HALT_SECS = 1800    # pause duration: 30 min


# ── Public API ────────────────────────────────────────────────────────────────

def is_in_cooldown() -> bool:
    return _cooldown > 0

def is_halted() -> bool:
    """True if DD circuit-breaker is active OR system_state is HALTED."""
    if _time.time() < _dd_halt_until:
        return True
    try:
        from src.core.system_state import is_halted as _sys_halted
        return _sys_halted()
    except Exception:
        return False

def get_position_size_mult() -> float:
    return _position_size_mult

def get_strategy_weights() -> dict:
    return dict(_cached_weights) if _cached_weights else {}


# ── Verdict + bias detection ──────────────────────────────────────────────────

def _compute_verdict(m: dict, pos_size_mult: float) -> tuple[str, list[str]]:
    """
    Produce a structured audit verdict and bias flag list.

    Verdict levels
    ──────────────
    APPROVED              : no significant issues detected
    APPROVED_WITH_WARNINGS: soft warnings present; trading continues with caution
    REJECTED              : hard stop condition active (DD halt, loss_streak ≥ 5,
                            or multiple simultaneous bias flags)

    Bias detections
    ───────────────
    recency_overconfidence : recent win-rate exceeded historical by ≥ 15 pp AND
                             trade count is large enough to distinguish noise
                             (Kahneman & Tversky: recency bias inflates confidence
                             after short hot streaks, leading to oversizing)

    revenge_trading_risk   : loss_streak ≥ 2 AND elevated trade frequency in last
                             session (≥ 1.5× baseline) — hallmark of revenge trading
                             pattern identified in algo-trading audit literature

    win_streak_overconfidence : win_streak ≥ 5 — anti-martingale multiplier at max,
                             risk of over-concentration after hot run
                             (Barberis & Thaler 2003: hot-hand fallacy)
    """
    bias_flags: list[str] = []

    loss_streak  = m.get("loss_streak",      0)
    win_streak   = m.get("win_streak",       0)
    recent_wr    = m.get("recent_winrate",   0.0)
    historical_wr= m.get("win_rate",         0.0)  # long-run WR from full history
    total_trades = m.get("trades",           0)
    trade_freq   = m.get("trade_freq_ratio", 0.0)  # recent freq / baseline freq

    # ── Bias: recency overconfidence ────────────────────────────────────────
    # Only meaningful once we have ≥ 30 trades (cold-start noise is large)
    if (total_trades >= 30
            and historical_wr > 0
            and recent_wr > historical_wr + 0.15):
        bias_flags.append("recency_overconfidence")

    # ── Bias: revenge trading risk ───────────────────────────────────────────
    # Loss streak ≥ 2 + abnormally high trade frequency = chasing losses
    if loss_streak >= 2 and trade_freq >= 1.5:
        bias_flags.append("revenge_trading_risk")

    # ── Bias: win-streak overconfidence ─────────────────────────────────────
    if win_streak >= 5:
        bias_flags.append("win_streak_overconfidence")

    # ── Hard REJECTED conditions ─────────────────────────────────────────────
    if is_halted():
        return "REJECTED", bias_flags + ["dd_halt_active"]

    if loss_streak >= 5:
        return "REJECTED", bias_flags + ["critical_loss_streak"]

    # Multiple simultaneous biases = compound risk → reject
    if len(bias_flags) >= 2:
        return "REJECTED", bias_flags

    # ── APPROVED_WITH_WARNINGS ────────────────────────────────────────────────
    if bias_flags or loss_streak >= 3 or pos_size_mult < 1.0:
        return "APPROVED_WITH_WARNINGS", bias_flags

    return "APPROVED", bias_flags


# ── Main audit cycle ──────────────────────────────────────────────────────────

_MONOTONE_THRESH = 3   # consecutive violations before HARD escalation


def run_audit():
    global _position_size_mult, _cooldown
    global _prev_loss_streak, _initialized, _cached_weights, _dd_halt_until
    global _monotone_violations

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

    # ── Position size: scale down on losses, scale up on wins (anti-martingale) ─
    # Research (Algorithmic Crypto Trading XI, Medium): anti-martingale increases
    # size after wins, decreases after losses. Mathematical expectation is favorable
    # when underlying strategy has edge — compounds gains on hot streaks.
    # Loss side: conservative reduction to preserve capital.
    # Win side: modest boost capped at 1.4× to avoid over-concentration.
    if loss_streak >= 5:
        _position_size_mult = 0.30
    elif loss_streak >= 3:
        _position_size_mult = 0.60
    elif win_streak >= 5:
        _position_size_mult = 1.40   # proven hot streak — ride it
    elif win_streak >= 3:
        _position_size_mult = 1.20   # building momentum — modest boost
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

    # ── Monotone violation guard (V10.14.b) ──────────────────────────────────
    # avg_win < 0 with wins >= 5 means "winning" trades are net negative —
    # a structural data-corruption signal (sign inversion, wrong PnL calc, etc.).
    # Three consecutive observations trigger a HARD escalation.
    avg_win = m.get("avg_win", 0.0)
    wins    = m.get("wins",    0)
    if avg_win < 0 and wins >= 5:
        _monotone_violations += 1
        _log.warning(
            "[AUDITOR] Monotone violation #%d: avg_win=%.6f  wins=%d",
            _monotone_violations, avg_win, wins,
        )
        if _monotone_violations >= _MONOTONE_THRESH:
            try:
                from src.core.failure_manager import handle_hard_fail
                handle_hard_fail(
                    f"Monotone violation: avg_win={avg_win:.6f} after {wins} wins"
                )
            except Exception as _me:
                _log.critical("[AUDITOR] handle_hard_fail import failed: %s", _me)
    else:
        _monotone_violations = max(0, _monotone_violations - 1)

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

    # ── Structured verdict + bias detection ──────────────────────────────────
    verdict, bias_flags = _compute_verdict(m, _position_size_mult)

    # ── Publish advice for bot1 ───────────────────────────────────────────────
    # Bot1 reads this via load_bot2_advice() before opening any trade.
    # Gives bot1 access to bot2's learned knowledge: which pairs/regimes are
    # blocked, which have positive EV, current system health/streak state.
    try:
        from src.services.learning_monitor import (
            lm_count, lm_pnl_hist, lm_ev_hist, lm_health, conf_ev
        )
        import numpy as _np

        # Blocked pairs: fast_fail or pair_block candidates
        blocked = []
        top     = []
        reg_ev  = {}
        for (sym, reg), n in lm_count.items():
            pnl = lm_pnl_hist.get((sym, reg), [])
            if not pnl:
                continue
            wr = sum(1 for x in pnl if x > 0) / len(pnl)
            ev = conf_ev(sym, reg)
            # Mirror fast_fail and pair_block logic
            if n >= 5:
                ff_m  = float(_np.mean(pnl))
                ff_s  = max(float(_np.std(pnl)), 0.002)
                ff_ev = float(_np.tanh(ff_m / ff_s))
                if wr < 0.20 and ff_ev <= 0.0:
                    blocked.append(f"{sym}|{reg}")
            if (n >= 15 and wr < 0.10) or (n >= 25 and wr < 0.30):
                blocked.append(f"{sym}|{reg}")
            # Top pairs: positive EV with enough data
            if n >= 10 and ev > 0.0:
                top.append({"sym": sym, "regime": reg, "ev": round(ev, 4),
                            "wr": round(wr, 4), "n": n})
            # Regime-level average EV
            prev = reg_ev.get(reg, [])
            prev.append(ev)
            reg_ev[reg] = prev

        top.sort(key=lambda x: -x["ev"])
        regime_ev_avg = {r: round(float(_np.mean(v)), 4)
                         for r, v in reg_ev.items() if v}

        save_bot2_advice({
            "blocked_pairs": list(set(blocked)),
            "top_pairs":     top[:10],
            "regime_ev":     regime_ev_avg,
            "loss_streak":   loss_streak,
            "health":        round(lm_health(), 4),
            "pos_size_mult": round(_position_size_mult, 4),
            "verdict":       verdict,
            "bias_flags":    bias_flags,
        })
    except Exception:
        pass
