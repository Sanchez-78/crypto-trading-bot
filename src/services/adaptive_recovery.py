"""
Adaptive Recovery Engine — Anti-deadlock stall fix + self-healing core.

Components:
1. AdaptiveEVGate    — Relaxation curve for zero-trade stall recovery
2. FilterRelaxation  — Multiplicative constraint relaxation when no signals
3. StallRecovery     — Hard stall detector + system reset
4. MicroTradeMode    — Position size reduction for stagnation recovery
"""

import logging
import time
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

# Global state for adaptive systems
_no_trade_counter = [0]  # Counter for consecutive no-trade cycles
_no_signal_cycles = [0]  # Counter for zero-signal cycles
_last_trade_time = [time.time()]  # Timestamp of last trade execution


class AdaptiveEVGate:
    """
    Adaptive EV threshold with relaxation curve.
    
    When system has no trades for extended period:
    - 50+ cycles: -0.005
    - 100+ cycles: -0.01
    - 200+ cycles: -0.02 (full relaxation)
    """

    def __init__(self, base_threshold: float = 0.0, min_threshold: float = -0.02):
        self.base_threshold = base_threshold
        self.min_threshold = min_threshold
        self.no_trade_counter = 0

    def update(self, trades_last_n: int):
        """Update counter based on whether trades occurred."""
        if trades_last_n == 0:
            self.no_trade_counter += 1
        else:
            self.no_trade_counter = 0

    def get_relaxation(self) -> float:
        """
        Compute relaxation offset to base threshold.
        Returns negative value that gets added to ev_threshold.
        """
        if self.no_trade_counter > 200:
            return -0.02  # Full relaxation
        if self.no_trade_counter > 100:
            return -0.01
        if self.no_trade_counter > 50:
            return -0.005
        return 0.0

    def threshold(self) -> float:
        """Get final EV threshold with relaxation applied."""
        return self.base_threshold + self.get_relaxation()


class FilterRelaxation:
    """
    Cascading filter relaxation when system stuck in no-signal regime.
    
    Applied to:
    - EV threshold (relaxation offset)
    - Min score threshold
    - Risk multiplier
    """

    def __init__(self):
        self.no_signal_cycles = 0
        self.base_min_score = 0.3  # Default minimum signal score
        self.base_risk_mult = 1.0  # Default risk multiplier

    def update(self, signals_generated: int):
        """Track consecutive cycles with zero signals."""
        if signals_generated == 0:
            self.no_signal_cycles += 1
        else:
            self.no_signal_cycles = 0

    def apply_relaxation(self) -> Dict[str, float]:
        """
        Return relaxation factors to apply to system constraints.
        """
        if self.no_signal_cycles > 400:
            # Full emergency mode
            return {
                "ev_relaxation": -0.02,
                "min_score_reduction": -0.25,
                "risk_multiplier": 0.3,
                "force_micro_trades": True,
            }
        elif self.no_signal_cycles > 250:
            # Moderate relaxation
            return {
                "ev_relaxation": -0.01,
                "min_score_reduction": -0.15,
                "risk_multiplier": 0.5,
                "force_micro_trades": False,
            }
        elif self.no_signal_cycles > 100:
            # Light relaxation
            return {
                "ev_relaxation": -0.005,
                "min_score_reduction": -0.05,
                "risk_multiplier": 0.8,
                "force_micro_trades": False,
            }
        else:
            # No relaxation
            return {
                "ev_relaxation": 0.0,
                "min_score_reduction": 0.0,
                "risk_multiplier": 1.0,
                "force_micro_trades": False,
            }


class StallRecovery:
    """
    Hard stall detector and recovery trigger.
    
    When no_trade_time > 900 seconds:
    - Reset EV gate to minimum
    - Force RL exploration mode
    - Reduce position size to micro-trades
    - Clear filter counters
    """

    def __init__(self, stall_threshold_seconds: int = 900):
        self.stall_threshold = stall_threshold_seconds
        self.last_recovery_time = 0
        self.recovery_cooldown = 300  # Prevent recovery spam

    def check_and_recover(
        self, no_trade_time: float, system_state: Dict[str, Any]
    ) -> Optional[str]:
        """
        Check if stall recovery should trigger.
        Returns "RECOVERY_TRIGGERED" if triggered, None otherwise.
        """
        current_time = time.time()

        # Only allow recovery every cooldown seconds
        if current_time - self.last_recovery_time < self.recovery_cooldown:
            return None

        if no_trade_time > self.stall_threshold:
            log.warning(f"🚨 STALL DETECTED: {no_trade_time:.0f}s no trades → RECOVERY")

            # Apply emergency recovery settings
            system_state["ev_threshold"] = -0.02
            system_state["min_score"] = 0.0
            system_state["rl_force_exploration"] = True
            system_state["risk_multiplier"] = 0.3
            system_state["position_size_multiplier"] = 0.2

            # Clear filter state
            if "filter_relaxation" in system_state:
                system_state["filter_relaxation"].no_signal_cycles = 0

            self.last_recovery_time = current_time
            return "RECOVERY_TRIGGERED"

        return None


class MicroTradeMode:
    """
    Micro-trade execution mode for stagnation recovery.
    
    When system has been idle too long:
    - Reduce position size to 20% of normal
    - Allow negative EV signals
    - Increase RL exploration rate
    """

    def __init__(self, stagnation_threshold: int = 300):
        self.stagnation_threshold = stagnation_threshold
        self.active = False

    def update(self, no_trade_time: float):
        """Update micro-trade mode state."""
        if no_trade_time > self.stagnation_threshold:
            self.active = True
        else:
            self.active = False

    def get_position_multiplier(self) -> float:
        """Return position size multiplier when in micro-trade mode."""
        return 0.2 if self.active else 1.0

    def get_exploration_boost(self) -> float:
        """Return RL exploration rate boost."""
        return 0.5 if self.active else 0.0

    def should_allow_negative_ev(self) -> bool:
        """Allow negative-EV trades in micro-mode for data collection."""
        return self.active


# Global instances
ev_gate = AdaptiveEVGate(base_threshold=0.0, min_threshold=-0.02)
filter_relaxation = FilterRelaxation()
stall_recovery = StallRecovery(stall_threshold_seconds=900)
micro_trade_mode = MicroTradeMode(stagnation_threshold=300)


def update_adaptive_state(trades_last_n: int, signals_generated: int, no_trade_time: float):
    """
    Main entry point for updating all adaptive recovery systems.
    Call this from main loop once per cycle.
    """
    ev_gate.update(trades_last_n)
    filter_relaxation.update(signals_generated)
    micro_trade_mode.update(no_trade_time)

    # Return recovery trigger if stall detected
    stall_status = stall_recovery.check_and_recover(
        no_trade_time,
        {
            "ev_threshold": 0.0,  # Placeholder
            "min_score": 0.3,
            "rl_force_exploration": False,
            "risk_multiplier": 1.0,
            "position_size_multiplier": 1.0,
            "filter_relaxation": filter_relaxation,
        },
    )
    return stall_status


def get_ev_relaxation() -> float:
    """Get adaptive EV relaxation offset."""
    return ev_gate.get_relaxation()


def get_filter_relaxation_state() -> Dict[str, Any]:
    """Get current filter relaxation state."""
    return filter_relaxation.apply_relaxation()


def is_micro_trade_active() -> bool:
    """Check if micro-trade mode is active."""
    return micro_trade_mode.active


def get_position_size_multiplier() -> float:
    """Get position size multiplier (normal or micro-mode)."""
    return micro_trade_mode.get_position_multiplier()
