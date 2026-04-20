"""
V10.13s Learning Pipeline Instrumentation

Tracks trade close → lm_update → persistence → hydration flow.
Exposes counters to verify every trade is processed.

Usage:
  from src.services.learning_instrumentation import (
      increment_trades_closed, increment_lm_update_called, 
      get_lm_counters
  )
  
  increment_trades_closed()
  increment_lm_update_called()
  
  counters = get_lm_counters()
  print(f"trades_closed={counters['trades_closed_total']}")
"""

# Global counters — all incremented in production
_LM_COUNTERS = {
    "trades_closed_total": 0,          # Trade closed event reached record_trade_close
    "lm_update_called_total": 0,       # lm_update function called
    "lm_update_success_total": 0,      # lm_update completed without exception
    "lm_update_failed_total": 0,       # lm_update raised exception
    "hydrated_pairs_count": 0,         # Unique (sym, reg) pairs after hydration
    "hydrated_features_count": 0,      # Feature stats entries after hydration
}


def increment_trades_closed() -> None:
    """Called when trade closes (in record_trade_close)."""
    _LM_COUNTERS["trades_closed_total"] += 1


def increment_lm_update_called() -> None:
    """Called at entry to lm_update()."""
    _LM_COUNTERS["lm_update_called_total"] += 1


def increment_lm_update_success() -> None:
    """Called on successful lm_update completion."""
    _LM_COUNTERS["lm_update_success_total"] += 1


def increment_lm_update_failed() -> None:
    """Called if lm_update raises exception."""
    _LM_COUNTERS["lm_update_failed_total"] += 1


def set_hydrated_pairs_count(count: int) -> None:
    """Called after hydration to record unique pairs loaded."""
    _LM_COUNTERS["hydrated_pairs_count"] = count


def set_hydrated_features_count(count: int) -> None:
    """Called after hydration to record features loaded."""
    _LM_COUNTERS["hydrated_features_count"] = count


def get_lm_counters() -> dict:
    """Return copy of all counters for logging."""
    return _LM_COUNTERS.copy()


def format_lm_counters() -> str:
    """Return formatted counter line for startup logs."""
    c = get_lm_counters()
    return (
        f"[LM_COUNTERS] "
        f"trades_closed={c['trades_closed_total']} "
        f"lm_update_called={c['lm_update_called_total']} "
        f"lm_update_success={c['lm_update_success_total']} "
        f"lm_update_failed={c['lm_update_failed_total']} "
        f"hydrated_pairs={c['hydrated_pairs_count']} "
        f"hydrated_features={c['hydrated_features_count']}"
    )
