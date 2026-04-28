"""V10.13u+20: Runtime trading mode and live-order guard."""
import os
import logging
from enum import Enum

log = logging.getLogger(__name__)


class TradingMode(str, Enum):
    """Runtime trading modes for V10.13u+20 paper training."""
    PAPER_LIVE = "paper_live"
    REPLAY_TRAIN = "replay_train"
    LIVE_REAL = "live_real"


# Default mode if not specified
_DEFAULT_TRADING_MODE = TradingMode.PAPER_LIVE


def get_trading_mode() -> TradingMode:
    """Get current trading mode from environment.

    Returns:
        TradingMode: Current mode (defaults to paper_live)
    """
    mode_str = os.getenv("TRADING_MODE", str(_DEFAULT_TRADING_MODE.value)).lower()
    try:
        return TradingMode(mode_str)
    except ValueError:
        log.warning("[RUNTIME_MODE] Invalid TRADING_MODE=%s, defaulting to %s", mode_str, _DEFAULT_TRADING_MODE.value)
        return _DEFAULT_TRADING_MODE


def real_orders_enabled() -> bool:
    """Check if real orders are enabled.

    Returns:
        bool: True only if ENABLE_REAL_ORDERS=true
    """
    return os.getenv("ENABLE_REAL_ORDERS", "false").lower() in ("true", "1", "yes")


def paper_exploration_enabled() -> bool:
    """Check if paper exploration is enabled.

    Returns:
        bool: True only if PAPER_EXPLORATION_ENABLED=true
    """
    return os.getenv("PAPER_EXPLORATION_ENABLED", "false").lower() in ("true", "1", "yes")


def live_trading_confirmed() -> bool:
    """Check if live trading has been manually confirmed.

    Returns:
        bool: True only if LIVE_TRADING_CONFIRMED=true
    """
    return os.getenv("LIVE_TRADING_CONFIRMED", "false").lower() in ("true", "1", "yes")


def is_paper_mode() -> bool:
    """Check if current mode is paper (paper_live or replay_train).

    Returns:
        bool: True if mode is paper_live or replay_train
    """
    mode = get_trading_mode()
    return mode in (TradingMode.PAPER_LIVE, TradingMode.REPLAY_TRAIN)


def live_trading_allowed() -> bool:
    """Check if live trading is allowed and properly configured.

    CRITICAL: All conditions must be true to allow live orders:
    - TRADING_MODE=live_real
    - ENABLE_REAL_ORDERS=true
    - LIVE_TRADING_CONFIRMED=true
    - PAPER_EXPLORATION_ENABLED=false

    Returns:
        bool: True only if all conditions are met
    """
    if get_trading_mode() != TradingMode.LIVE_REAL:
        return False

    if not real_orders_enabled():
        return False

    if not live_trading_confirmed():
        return False

    if paper_exploration_enabled():
        return False

    return True


def log_runtime_config():
    """Log current runtime configuration at startup."""
    mode = get_trading_mode()
    real_orders = real_orders_enabled()
    live_allowed = live_trading_allowed()
    exploration = paper_exploration_enabled()

    log.info(
        "[TRADING_MODE] mode=%s real_orders=%s live_allowed=%s exploration=%s",
        mode.value,
        real_orders,
        live_allowed,
        exploration,
    )


def check_live_order_guard(symbol: str, side: str) -> dict:
    """Check if live order is allowed before placing on exchange.

    CRITICAL: This must be called before any real Binance API order.

    Args:
        symbol: Trading pair (e.g., "XRPUSDT")
        side: Order side ("BUY" or "SELL")

    Returns:
        dict: {"allowed": bool, "reason": str, "mode": str}
    """
    if live_trading_allowed():
        return {
            "allowed": True,
            "reason": "live_trading_enabled",
            "mode": get_trading_mode().value,
        }

    mode = get_trading_mode()
    reason = ""

    if mode != TradingMode.LIVE_REAL:
        reason = f"trading_mode_{mode.value}"
    elif not real_orders_enabled():
        reason = "real_orders_disabled"
    elif not live_trading_confirmed():
        reason = "live_trading_not_confirmed"
    elif paper_exploration_enabled():
        reason = "exploration_enabled_incompatible_with_live"
    else:
        reason = "unknown_blocker"

    log.error(
        "[LIVE_ORDER_DISABLED] symbol=%s side=%s mode=%s reason=%s",
        symbol,
        side,
        mode.value,
        reason,
    )

    return {
        "allowed": False,
        "reason": reason,
        "mode": mode.value,
    }


# Convenience function for tests/diagnostics
def get_runtime_status() -> dict:
    """Get comprehensive runtime status.

    Returns:
        dict: Current runtime configuration and guard status
    """
    mode = get_trading_mode()
    return {
        "mode": mode.value,
        "real_orders": real_orders_enabled(),
        "live_trading_allowed": live_trading_allowed(),
        "live_trading_confirmed": live_trading_confirmed(),
        "paper_exploration": paper_exploration_enabled(),
        "is_paper_mode": is_paper_mode(),
    }
