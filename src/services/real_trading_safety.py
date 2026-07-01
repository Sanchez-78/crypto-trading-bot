"""Real Trading Safety Framework - PHASE 2

Circuit breaker + position sizing + manual override for production account.

Safety Invariants:
- Max 2% daily loss before auto-stop
- Position size scaled by Kelly criterion (with 25% safety factor)
- Manual kill switch always available
- Drawdown tracking per symbol
- Emergency rollback to paper trading on trigger
"""

import logging
import time
import json
import os
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Safety thresholds
MAX_DAILY_LOSS_PCT = 0.02  # 2% daily max loss
MAX_DAILY_LOSS_USD = None  # Set based on account size on startup
KELLY_SAFETY_FACTOR = 0.25  # Use 25% of Kelly fraction (conservative)
MAX_POSITION_SIZE_USD = 100  # Absolute max per trade
MIN_POSITION_SIZE_USD = 10   # Minimum bet size
DRAWDOWN_ALERT_PCT = 0.05   # Alert at 5% drawdown


class RealTradingSafety:
    """Safety framework for real trading."""

    def __init__(self, account_balance_usd: float = 5000):
        """Initialize safety system with account balance."""
        self.account_balance = account_balance_usd
        self.max_daily_loss_usd = account_balance_usd * MAX_DAILY_LOSS_PCT

        # Daily P&L tracking
        self.daily_pnl_usd = 0.0
        self.daily_start_time = datetime.utcnow()
        self.daily_loss_triggered = False

        # Position tracking
        self.open_positions = {}  # symbol -> {size_usd, entry_price, pnl}
        self.closed_positions_today = []  # List of closed trades

        # Manual override
        self.manual_override_active = False
        self.override_reason = None
        self.override_start_time = None

        # Emergency rollback
        self.emergency_mode = False
        self.emergency_reason = None

        self.state_file = "server_local_backups/real_trading_safety_state.json"
        self._load_state()

        log.info(f"[SAFETY_INIT] Account: ${account_balance_usd:.2f}, "
                f"Daily loss limit: ${self.max_daily_loss_usd:.2f}, "
                f"Kelly safety factor: {KELLY_SAFETY_FACTOR}")

    def check_circuit_breaker(self) -> Tuple[bool, Optional[str]]:
        """Check if circuit breaker should trigger.

        Returns: (should_stop, reason)
        """
        # Reset daily P&L if new day
        self._reset_daily_if_needed()

        # Check daily loss limit
        if self.daily_pnl_usd < -self.max_daily_loss_usd:
            self.daily_loss_triggered = True
            reason = f"Daily loss limit hit: ${self.daily_pnl_usd:.2f} < ${-self.max_daily_loss_usd:.2f}"
            log.error(f"[CIRCUIT_BREAKER] {reason}")
            return True, reason

        # Check manual override
        if self.manual_override_active:
            reason = f"Manual override active: {self.override_reason}"
            log.warning(f"[CIRCUIT_BREAKER] {reason}")
            return True, reason

        # Check emergency mode
        if self.emergency_mode:
            reason = f"Emergency mode: {self.emergency_reason}"
            log.error(f"[CIRCUIT_BREAKER] {reason}")
            return True, reason

        return False, None

    def calculate_position_size(self, symbol: str, win_rate: float,
                               avg_win_pct: float, avg_loss_pct: float) -> float:
        """Calculate position size using Kelly criterion with safety factor.

        Kelly fraction = (bp * p - q) / b
        where:
          p = win probability
          q = 1 - p (loss probability)
          b = win/loss ratio
          bp = average win size

        Apply 25% safety factor: kelly_size * 0.25
        """
        if win_rate <= 0 or avg_win_pct <= 0 or avg_loss_pct <= 0:
            # Fallback to conservative base size
            return MIN_POSITION_SIZE_USD

        try:
            p = win_rate
            q = 1 - p
            b = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 1.0

            # Kelly fraction (as % of account)
            if b > 0 and (b * p - q) > 0:
                kelly_pct = (b * p - q) / b
            else:
                kelly_pct = 0.01  # Fall back to 1% if Kelly is negative

            # Apply safety factor (use only 25% of Kelly fraction)
            safe_kelly_pct = kelly_pct * KELLY_SAFETY_FACTOR
            safe_kelly_pct = min(safe_kelly_pct, 0.02)  # Cap at 2% per trade

            position_size = self.account_balance * safe_kelly_pct
            position_size = max(MIN_POSITION_SIZE_USD, min(MAX_POSITION_SIZE_USD, position_size))

            log.info(f"[POSITION_SIZE] {symbol}: Kelly={kelly_pct:.2%}, "
                    f"Safe={safe_kelly_pct:.2%}, Size=${position_size:.2f}")
            return position_size

        except Exception as e:
            log.error(f"[POSITION_SIZE_ERROR] {symbol}: {e}")
            return MIN_POSITION_SIZE_USD

    def record_trade_closed(self, symbol: str, pnl_usd: float, side: str):
        """Record a closed trade and update daily P&L."""
        self._reset_daily_if_needed()

        self.daily_pnl_usd += pnl_usd
        self.closed_positions_today.append({
            "symbol": symbol,
            "pnl_usd": pnl_usd,
            "side": side,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Check drawdown alert
        drawdown_pct = abs(self.daily_pnl_usd) / self.account_balance
        if drawdown_pct > DRAWDOWN_ALERT_PCT:
            log.warning(f"[DRAWDOWN_ALERT] {drawdown_pct:.2%} ({self.daily_pnl_usd:.2f})")

        log.info(f"[TRADE_CLOSED] {symbol}: ${pnl_usd:.2f}, Daily P&L: ${self.daily_pnl_usd:.2f}")
        self._save_state()

    def set_manual_override(self, active: bool, reason: str = None):
        """Set manual override (kill switch)."""
        self.manual_override_active = active
        if active:
            self.override_reason = reason or "Manual override"
            self.override_start_time = datetime.utcnow()
            log.warning(f"[MANUAL_OVERRIDE] ON: {reason}")
        else:
            log.info(f"[MANUAL_OVERRIDE] OFF")
        self._save_state()

    def set_emergency_mode(self, active: bool, reason: str = None):
        """Trigger emergency mode (auto-rollback to paper)."""
        self.emergency_mode = active
        if active:
            self.emergency_reason = reason or "Emergency mode triggered"
            log.error(f"[EMERGENCY_MODE] ON: {reason}")
        else:
            log.info(f"[EMERGENCY_MODE] OFF")
        self._save_state()

    def _reset_daily_if_needed(self):
        """Reset daily P&L counters if new UTC day."""
        now = datetime.utcnow()
        if (now - self.daily_start_time).days >= 1:
            log.info(f"[DAILY_RESET] New UTC day. Previous daily P&L: ${self.daily_pnl_usd:.2f}")
            self.daily_pnl_usd = 0.0
            self.daily_start_time = now
            self.daily_loss_triggered = False
            self.closed_positions_today = []
            self._save_state()

    def get_status(self) -> Dict:
        """Get current safety status."""
        self._reset_daily_if_needed()

        return {
            "account_balance_usd": self.account_balance,
            "daily_pnl_usd": self.daily_pnl_usd,
            "daily_pnl_pct": self.daily_pnl_usd / self.account_balance * 100 if self.account_balance > 0 else 0,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "circuit_breaker_active": self.daily_loss_triggered,
            "manual_override_active": self.manual_override_active,
            "emergency_mode": self.emergency_mode,
            "trades_closed_today": len(self.closed_positions_today),
        }

    def _save_state(self):
        """Persist safety state to disk."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            data = {
                "timestamp": datetime.utcnow().isoformat(),
                "account_balance_usd": self.account_balance,
                "daily_pnl_usd": self.daily_pnl_usd,
                "daily_start_time": self.daily_start_time.isoformat(),
                "manual_override_active": self.manual_override_active,
                "override_reason": self.override_reason,
                "emergency_mode": self.emergency_mode,
                "emergency_reason": self.emergency_reason,
                "closed_positions_today": self.closed_positions_today,
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.warning(f"[SAFETY_STATE_SAVE] Failed: {e}")

    def _load_state(self):
        """Load persisted safety state."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)

                # Load if same day
                last_time = datetime.fromisoformat(data.get("daily_start_time", ""))
                now = datetime.utcnow()
                if (now - last_time).days == 0:
                    self.daily_pnl_usd = data.get("daily_pnl_usd", 0.0)
                    self.manual_override_active = data.get("manual_override_active", False)
                    self.override_reason = data.get("override_reason")
                    self.emergency_mode = data.get("emergency_mode", False)
                    self.emergency_reason = data.get("emergency_reason")
                    log.info(f"[SAFETY_STATE_RESTORE] Loaded daily P&L: ${self.daily_pnl_usd:.2f}")
        except Exception as e:
            log.warning(f"[SAFETY_STATE_LOAD] Failed: {e}")


# Singleton instance (initialized with account balance on startup)
_safety = None

def init_real_trading_safety(account_balance_usd: float = 5000):
    """Initialize safety system."""
    global _safety
    _safety = RealTradingSafety(account_balance_usd)
    return _safety

def get_safety() -> RealTradingSafety:
    """Get safety instance."""
    global _safety
    if not _safety:
        _safety = RealTradingSafety()
    return _safety

def check_can_trade() -> Tuple[bool, Optional[str]]:
    """Check if trading is allowed."""
    safety = get_safety()
    return safety.check_circuit_breaker()

def calculate_position_size(symbol: str, win_rate: float,
                           avg_win_pct: float, avg_loss_pct: float) -> float:
    """Calculate safe position size."""
    safety = get_safety()
    return safety.calculate_position_size(symbol, win_rate, avg_win_pct, avg_loss_pct)

def get_safety_status() -> Dict:
    """Get current safety status."""
    safety = get_safety()
    return safety.get_status()
