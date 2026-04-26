"""
Self Healing Engine v1 — Auto-response to anomalies.

When anomaly detected, system:
1. Adjusts risk multipliers (reduce exposure)
2. Escalates exploration (find new opportunities)
3. Reduces thresholds (accept more signals)
4. Enters safe mode (reduce signal confidence)

All changes are reversible via rollback mechanism.
"""

import logging

logger = logging.getLogger(__name__)


def handle_anomaly(anomaly: str, state):
    """
    Auto-respond to detected anomaly.
    Modifies state in-place for fast response.

    V10.13L: If runtime fault is active, skip threshold relaxations — fault
    recovery is handled by fail-closed gates, not by lowering barriers.
    """
    # V10.13L: Check for runtime faults — don't mask them via threshold relaxation
    is_runtime_faulted = False
    try:
        from src.services.runtime_fault_registry import has_hard_fault
        is_runtime_faulted = has_hard_fault()
    except Exception:
        pass

    if is_runtime_faulted:
        logger.warning(f"SELF_HEAL: SKIPPED {anomaly} — runtime fault active, "
                       f"using fail-closed gate instead")
        return

    # ────────────────────────────────────────────────────────────────────────
    # EQUITY DROP: Hard defense (cut position size)
    # ────────────────────────────────────────────────────────────────────────
    if anomaly == "EQUITY_DROP":
        logger.error(f"SELF_HEAL: EQUITY_DROP triggered → reducing risk to 50%")
        state.risk_multiplier = getattr(state, "risk_multiplier", 1.0) * 0.5
        state.safe_mode = True
        state.max_position_size = getattr(state, "max_position_size", 0.05) * 0.5
        state.exploration_factor = getattr(state, "exploration_factor", 1.0) * 1.2

    # ────────────────────────────────────────────────────────────────────────
    # HIGH DRAWDOWN: Emergency defense (aggressive risk cut)
    # ────────────────────────────────────────────────────────────────────────
    elif anomaly == "HIGH_DRAWDOWN":
        logger.error(f"SELF_HEAL: HIGH_DRAWDOWN (>35%) triggered → reducing risk to 30%")
        state.risk_multiplier = getattr(state, "risk_multiplier", 1.0) * 0.3
        state.safe_mode = True
        state.max_position_size = getattr(state, "max_position_size", 0.05) * 0.3
        state.filter_strength = getattr(state, "filter_strength", 1.0) * 1.2  # Tighten filters

    # ────────────────────────────────────────────────────────────────────────
    # STALL: Try to unstagnate (loosen filters, boost exploration)
    # V10.13u+12: Check close-lock health before boosting exploration
    # ────────────────────────────────────────────────────────────────────────
    elif anomaly == "STALL":
        # V10.13u+12: Suppress exploration boost if close locks are active (recovery in progress)
        try:
            from src.services.trade_executor import get_close_lock_health
            close_health = get_close_lock_health()
        except Exception:
            close_health = {"active": 0, "oldest_age": 0.0}

        if close_health["active"] > 0:
            logger.warning(f"[WATCHDOG_SUPPRESSED_CLOSE_LOCK] active={close_health['active']} "
                          f"oldest_age={close_health['oldest_age']:.1f}s reason=STALL_while_closing")
            return  # Skip exploration boost while close locks are active

        logger.warning(f"SELF_HEAL: STALL (no trades 900s) → boosting exploration")
        state.exploration_factor = getattr(state, "exploration_factor", 1.0) * 1.5
        state.allow_micro_trade = True
        state.ev_threshold = getattr(state, "ev_threshold", 0.0) * 0.9  # Lower EV requirement
        state.filter_strength = getattr(state, "filter_strength", 1.0) * 0.9  # Soften filters

    # ────────────────────────────────────────────────────────────────────────
    # NO SIGNALS: Pipeline might be stuck (reduce filter severity)
    # ────────────────────────────────────────────────────────────────────────
    elif anomaly == "NO_SIGNALS":
        logger.debug("self_heal: NO_SIGNALS → reducing filter thresholds")
        state.ev_threshold = getattr(state, "ev_threshold", 0.0) * 0.8
        state.filter_strength = getattr(state, "filter_strength", 1.0) * 0.8
        # Force some micro-trades to restart flow
        state.allow_micro_trade = True
        state.min_position_floor = 0.01

    logger.info(f"SELF_HEAL: Applied response for {anomaly}")


def apply_safe_mode(signal, state):
    """
    Apply safe mode constraints to signal.
    
    When system is in safe mode:
    - Reduce position size to 30% of normal
    - Reduce confidence signal
    - Add safe mode tag for audit trail
    """
    if getattr(state, "safe_mode", False):
        original_size = signal.size if hasattr(signal, "size") else 0
        signal.size = original_size * 0.3
        
        # Reduce confidence if available
        if hasattr(signal, "confidence"):
            signal.confidence *= 0.8
        
        # Add tag for audit
        signal.tag = getattr(signal, "tag", "") + "[SAFE_MODE]"
        
        logger.debug(f"SAFE_MODE: reduced {signal.symbol} from {original_size:.4f} to {signal.size:.4f}")

    return signal


def apply_position_floor(signal, state):
    """
    If in safe mode + micro-trading enabled, enforce minimum position.
    Prevents complete freeze at zero size.
    """
    if getattr(state, "allow_micro_trade", False):
        min_floor = getattr(state, "min_position_floor", 0.01)
        if signal.size < min_floor:
            signal.size = min_floor
            logger.debug(f"Floor applied: {signal.symbol} set to {min_floor:.4f}")

    return signal


def apply_position_cap(signal, state):
    """
    Never let single position exceed max allocation.
    Anti-explosion safeguard.
    """
    max_size = getattr(state, "max_position_size", 0.05)
    if signal.size > max_size:
        signal.size = max_size
        logger.debug(f"Cap applied: {signal.symbol} capped at {max_size:.4f}")

    return signal


def failsafe_halt(state) -> bool:
    """
    Emergency halt if system too unstable.
    
    Conditions:
    - Safe mode active AND
    - Drawdown > 45%
    
    Returns: True if trading should be halted
    """
    if getattr(state, "safe_mode", False) and state.drawdown > 0.45:
        logger.critical("🛑 FAILSAFE: Trading disabled (safe_mode + DD>45%)")
        state.trading_enabled = False
        return True

    return False
