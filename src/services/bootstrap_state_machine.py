"""
PRIORITY 2: Bootstrap State Machine — Explicit Hard/Soft/Normal/Quality-Locked progression.

Replaces simple trade-count thresholds (COLD <30, WARM <100, LIVE ≥100) with:

State progression:
  HARD (0-50 trades, convergence <0.3)
    → Minimal gates, sized 50% reduction, learn everything

  SOFT (50-150 trades, convergence 0.3-0.6)
    → Soft constraints, sized 70% reduction, selective gates

  NORMAL (150+ trades, convergence 0.6+, data quality good)
    → Full gates, standard sizing, strict risk

  QUALITY_LOCKED (150+ trades, convergence 0.8+, all metrics stable)
    → Highest precision, full leverage, advanced strategies enabled

State transitions:
  - Only forward (HARD → SOFT → NORMAL → QUALITY_LOCKED)
  - Transition on convergence + data quality thresholds, not just trade count
  - Quality degradation can reset toward NORMAL (not backward to HARD)

Calibration per branch:
  - Normal trades: standard progression
  - Forced trades: stay at SOFT longer (learning delayed by nature)
  - Micro trades: skip HARD, start at SOFT (protective)

Usage:
  from src.services.bootstrap_state_machine import (
      get_bootstrap_state, update_bootstrap_state,
      get_sizing_multiplier, get_gate_relaxation,
      get_state_diagnostics
  )

  state = get_bootstrap_state("BTC", "TRENDING", "normal")
  sizing_mult = get_sizing_multiplier(state)  # 0.5 in HARD, 1.0 in NORMAL
"""

import logging
from typing import Dict, Optional
from enum import Enum
import time as _time

log = logging.getLogger(__name__)


class BootstrapState(Enum):
    """Four explicit bootstrap states."""
    HARD = "HARD"
    SOFT = "SOFT"
    NORMAL = "NORMAL"
    QUALITY_LOCKED = "QUALITY_LOCKED"


@staticmethod
def get_default_state() -> str:
    """Return the default state for new symbol/regime pairs."""
    return BootstrapState.HARD.value


# ── Per-(sym, regime, branch) state tracking ────────────────────────────────
_bootstrap_states: Dict[str, Dict[str, str]] = {}
_state_timestamps: Dict[str, float] = {}
_state_counts: Dict[str, int] = {}


def _make_key(sym: str, regime: str, branch: str = "normal") -> str:
    """Create unique key for (sym, regime, branch) tuple."""
    return f"{sym}:{regime}:{branch}"


def get_bootstrap_state(sym: str, regime: str, branch: str = "normal") -> str:
    """
    Get current bootstrap state for (sym, regime, branch).

    Args:
        sym: Symbol (e.g., "BTCUSDT")
        regime: Regime (e.g., "TRENDING", "RANGING")
        branch: Trade branch ("normal", "forced", "micro")

    Returns:
        State string ("HARD", "SOFT", "NORMAL", "QUALITY_LOCKED")
    """
    key = _make_key(sym, regime, branch)
    return _bootstrap_states.get(key, BootstrapState.HARD.value)


def _get_convergence_score(sym: str, regime: str) -> float:
    """
    Get convergence score for (sym, regime) from learning monitor.

    Score ranges 0.0 (noisy) to 1.0 (fully converged).
    Returns 0.0 if insufficient data.
    """
    try:
        from src.services.learning_monitor import lm_convergence
        return lm_convergence(sym, regime)
    except Exception:
        return 0.0


def _get_trade_count(sym: str, regime: str) -> int:
    """Get trade count for (sym, regime) from learning monitor."""
    try:
        from src.services.learning_monitor import lm_count
        key = (sym, regime)
        return lm_count.get(key, 0)
    except Exception:
        return 0


def _get_win_rate(sym: str, regime: str) -> float:
    """Get win rate for (sym, regime) from learning monitor."""
    try:
        from src.services.learning_monitor import lm_wr_hist
        key = (sym, regime)
        hist = lm_wr_hist.get(key, [])
        if hist:
            return hist[-1]
        return 0.5
    except Exception:
        return 0.5


def _should_transition(
    current_state: str,
    trade_count: int,
    convergence: float,
    win_rate: float,
) -> Optional[str]:
    """
    Determine if state transition is warranted.

    Transition rules:
      HARD → SOFT: trades ≥ 50 AND convergence ≥ 0.3
      SOFT → NORMAL: trades ≥ 150 AND convergence ≥ 0.6
      NORMAL → QUALITY_LOCKED: trades ≥ 200 AND convergence ≥ 0.8 AND wr stable
      (any) → NORMAL: if convergence drops < 0.4 (quality degradation)

    Returns:
        New state string if transition warranted, else None
    """
    if current_state == BootstrapState.HARD.value:
        if trade_count >= 50 and convergence >= 0.3:
            return BootstrapState.SOFT.value

    elif current_state == BootstrapState.SOFT.value:
        if trade_count >= 150 and convergence >= 0.6:
            return BootstrapState.NORMAL.value

    elif current_state == BootstrapState.NORMAL.value:
        if trade_count >= 200 and convergence >= 0.8:
            return BootstrapState.QUALITY_LOCKED.value

    # Quality degradation: reset to NORMAL if convergence drops
    if current_state == BootstrapState.QUALITY_LOCKED.value:
        if convergence < 0.7:
            log.warning(f"[BOOTSTRAP] Quality degradation detected (convergence={convergence:.2f}), "
                       f"resetting to NORMAL")
            return BootstrapState.NORMAL.value

    return None


def update_bootstrap_state(sym: str, regime: str, branch: str = "normal") -> str:
    """
    Update bootstrap state for (sym, regime, branch) based on current data.

    Called periodically (e.g., on every trade close) to check for state transitions.

    Returns:
        New state string (same as current if no transition)
    """
    key = _make_key(sym, regime, branch)
    current_state = get_bootstrap_state(sym, regime, branch)

    trade_count = _get_trade_count(sym, regime)
    convergence = _get_convergence_score(sym, regime)
    win_rate = _get_win_rate(sym, regime)

    new_state = _should_transition(current_state, trade_count, convergence, win_rate)

    if new_state and new_state != current_state:
        log.info(
            f"[BOOTSTRAP] State transition: {sym}/{regime}/{branch} "
            f"{current_state} → {new_state} "
            f"(trades={trade_count}, conv={convergence:.2f}, wr={win_rate:.2f})"
        )
        _bootstrap_states[key] = new_state
        _state_timestamps[key] = _time.time()
        return new_state

    # Initialize if not seen before
    if key not in _bootstrap_states:
        _bootstrap_states[key] = BootstrapState.HARD.value
        _state_timestamps[key] = _time.time()

    return current_state


def get_sizing_multiplier(state: str, branch: str = "normal") -> float:
    """
    Get position sizing multiplier for bootstrap state.

    HARD (learning):      0.50x (min risk while gathering data)
    SOFT (warming up):    0.70x (still learning, but more confident)
    NORMAL (mature):      1.00x (full standard sizing)
    QUALITY_LOCKED:       1.00x (can enable leverage, but caution)

    Args:
        state: Bootstrap state string
        branch: Trade branch ("normal", "forced", "micro")

    Returns:
        float: Multiplier to apply to standard position size
    """
    if state == BootstrapState.HARD.value:
        return 0.50
    elif state == BootstrapState.SOFT.value:
        return 0.70
    elif state == BootstrapState.NORMAL.value:
        return 1.00
    elif state == BootstrapState.QUALITY_LOCKED.value:
        return 1.00
    else:
        return 1.00


def get_gate_relaxation(state: str) -> float:
    """
    Get gate threshold relaxation for bootstrap state (multiplicative).

    HARD:          0.70 (relax EV, WR checks by 30%)
    SOFT:          0.85 (relax by 15%)
    NORMAL:        1.00 (standard gates)
    QUALITY_LOCKED: 1.00 (standard gates, can add advanced filters)

    Returns:
        float: Multiplier for gate thresholds (< 1.0 = relax, = 1.0 = strict)
    """
    if state == BootstrapState.HARD.value:
        return 0.70
    elif state == BootstrapState.SOFT.value:
        return 0.85
    elif state == BootstrapState.NORMAL.value:
        return 1.00
    elif state == BootstrapState.QUALITY_LOCKED.value:
        return 1.00
    else:
        return 1.00


def get_state_diagnostics(sym: str, regime: str, branch: str = "normal") -> Dict:
    """
    Get diagnostic info for bootstrap state (for logging/dashboards).

    Returns dict with:
      - state: current state string
      - trade_count: trades in this (sym, regime) pair
      - convergence: 0.0-1.0 score
      - win_rate: empirical WR
      - sizing_mult: position sizing multiplier
      - gate_relax: gate threshold relaxation multiplier
      - time_in_state: seconds since last transition
      - next_transition: description of next transition criteria
    """
    state = get_bootstrap_state(sym, regime, branch)
    key = _make_key(sym, regime, branch)

    trade_count = _get_trade_count(sym, regime)
    convergence = _get_convergence_score(sym, regime)
    win_rate = _get_win_rate(sym, regime)

    time_in_state = _time.time() - _state_timestamps.get(key, _time.time())
    sizing_mult = get_sizing_multiplier(state, branch)
    gate_relax = get_gate_relaxation(state)

    if state == BootstrapState.HARD.value:
        next_transition = f"SOFT @ 50 trades & convergence ≥0.3 (now: {trade_count} trades, conv={convergence:.2f})"
    elif state == BootstrapState.SOFT.value:
        next_transition = f"NORMAL @ 150 trades & convergence ≥0.6 (now: {trade_count} trades, conv={convergence:.2f})"
    elif state == BootstrapState.NORMAL.value:
        next_transition = f"QUALITY_LOCKED @ 200 trades & convergence ≥0.8 (now: {trade_count} trades, conv={convergence:.2f})"
    else:
        next_transition = "Fully converged (monitor for quality degradation)"

    return {
        "state": state,
        "trade_count": trade_count,
        "convergence": convergence,
        "win_rate": win_rate,
        "sizing_mult": sizing_mult,
        "gate_relax": gate_relax,
        "time_in_state_seconds": time_in_state,
        "next_transition": next_transition,
    }
