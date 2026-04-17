"""
V10.13j: Smart Exit Engine Guard

Wraps smart exit engine import so syntax/runtime errors cannot kill the price tick path.

Behavior:
  - Try to import and use smart exit features
  - If import fails, log FATAL once and fallback to hard TP/SL/timeout only
  - Degraded trading is better than zero trading

This prevents a module-level syntax error from blocking all execution.
"""

import logging
from typing import Optional, Dict, Any

log = logging.getLogger(__name__)

_smart_exit_available = False
_smart_exit_module = None
_smart_exit_failed_once = False


def _try_import_smart_exit():
    """Attempt to import smart exit engine."""
    global _smart_exit_available, _smart_exit_module, _smart_exit_failed_once
    
    if _smart_exit_module is not None:
        _smart_exit_available = True
        return
    
    try:
        from src.services import smart_exit_engine
        _smart_exit_module = smart_exit_engine
        _smart_exit_available = True
        log.debug("✓ Smart exit engine imported successfully")
    except Exception as e:
        if not _smart_exit_failed_once:
            banner = "\n" + ("🚨" * 40)
            banner += "\n🚨 SMART EXIT ENGINE IMPORT FAILED\n"
            banner += f"🚨 Error: {type(e).__name__}: {str(e)}\n"
            banner += "🚨 Degraded trading mode: only hard TP/SL/timeout\n"
            banner += ("🚨" * 40) + "\n"
            log.critical(banner)
            _smart_exit_failed_once = True
        
        _smart_exit_available = False
        _smart_exit_module = None


def is_available() -> bool:
    """Check if smart exit engine is available."""
    if _smart_exit_module is None:
        _try_import_smart_exit()
    return _smart_exit_available


def evaluate_smart_exit(
    symbol: str,
    entry_price: float,
    tp: float,
    sl: float,
    current_price: float,
    age_seconds: int,
    direction: str = "LONG",
    max_favorable_move: float = 0.0,
    regime: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Safely evaluate smart exit.
    
    If smart exit engine is not available, returns None (use hard exit logic).
    If evaluation fails, logs and returns None.
    """
    if not is_available():
        return None
    
    try:
        return _smart_exit_module.evaluate_smart_exit(
            symbol=symbol,
            entry_price=entry_price,
            tp=tp,
            sl=sl,
            current_price=current_price,
            age_seconds=age_seconds,
            direction=direction,
            max_favorable_move=max_favorable_move,
            regime=regime,
        )
    except Exception as e:
        log.error(f"Smart exit evaluation failed for {symbol}: {type(e).__name__}: {str(e)}")
        return None


def get_status() -> Dict[str, Any]:
    """Get smart exit guard status."""
    return {
        "available": is_available(),
        "failed_once": _smart_exit_failed_once,
    }
