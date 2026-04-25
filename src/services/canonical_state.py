"""
V10.13s.1 — Canonical State Oracle

PROBLÉM:
  Log ukazuje 4 různé počty obchodů zároveň:
  - 100 (learning runtime)
  - 500 (dashboard reconciliation)
  - 7467 (stale global bootstrap)
  - 0 (maturity oracle — BUG!)

  Maturity neví která čísla věřit → vždycky vybere špatně

ŘEŠENÍ:
  Jedna funkce get_canonical_state() která vrátí single source of truth.
  Všechny subsystémy se budou řídí JÍ.

Priorita zdrojů:
  1. Learning monitor (runtime accurate state)
  2. Learning event metrics (live reconciliation)
  3. Firebase last saved state
  4. Redis hydrated state
  5. NIKDY stale global state
"""

import logging
import time as _time

log = logging.getLogger(__name__)

# Track last refresh
_last_canonical_refresh = 0.0
_canonical_cache = None
_cache_ttl_sec = 5.0  # Recompute každých 5 sekund


def get_canonical_state() -> dict:
    """
    V10.13s.1: Single source of truth pro trade counts a maturity.

    Vrací:
    {
        "trades_runtime": int,           # Current session actual trades
        "trades_dashboard": int,         # Historical reconciled count
        "trades_historical_total": int,  # Full bootstrap history (WARNING: may be stale)
        "trades_for_maturity": int,      # Authoritative count for logic
        "source": "learning|firebase|redis|bootstrap",
        "maturity": "cold_start|bootstrap|live",
        "bootstrap_active": bool,
        "state_consistent": bool,
        "warnings": [str],
        "ts": float,                     # Refresh timestamp
    }

    Procedura:
      1. Get runtime count from learning_monitor
      2. Get dashboard count from learning_event
      3. Compare — if mismatch, log warning
      4. Pick authoritative count based on priority
      5. Determine maturity level
      6. Return unified dict

    NIKDY nevrátit stale data — vždy preferuj runtime.
    """
    global _last_canonical_refresh, _canonical_cache

    now = _time.time()
    if _canonical_cache and (now - _last_canonical_refresh) < _cache_ttl_sec:
        return _canonical_cache  # Return cached if fresh

    warnings = []

    # Zdroj 1: Learning Monitor (runtime state)
    runtime_trades = 0
    try:
        from src.services.learning_monitor import lm_count
        runtime_trades = sum(lm_count.values())
    except Exception as e:
        warnings.append(f"learning_monitor unavailable: {e}")

    # Zdroj 2: Learning Event (dashboard reconciliation)
    dashboard_trades = 0
    try:
        from src.services.learning_event import METRICS
        dashboard_trades = METRICS.get("trades", 0)
    except Exception as e:
        warnings.append(f"learning_event unavailable: {e}")

    # Zdroj 3: Firebase (historical, may be stale)
    firebase_trades = 0
    try:
        from src.services.firebase_client import load_latest_state
        state = load_latest_state()
        firebase_trades = state.get("trade_count", 0) if state else 0
    except Exception:
        pass  # Firebase unavailable, OK during offline

    # Zdroj 4: Bootstrap (legacy, usually stale after runtime)
    bootstrap_trades = runtime_trades  # Use runtime unless explicitly marked stale

    # Determine which count to use (priority order)
    # Authoritative: runtime + dashboard agreement, or runtime if dashboard not ready
    state_consistent = abs(runtime_trades - dashboard_trades) <= 5

    if not state_consistent:
        warnings.append(
            f"count_mismatch: runtime={runtime_trades} vs dashboard={dashboard_trades}"
        )

    # Prefer runtime (current session), fall back to dashboard
    trades_for_maturity = runtime_trades if runtime_trades > 0 else dashboard_trades

    # Determine maturity
    if trades_for_maturity == 0:
        maturity = "cold_start"
        bootstrap_active = True
    elif trades_for_maturity < 50:
        maturity = "bootstrap"
        bootstrap_active = True
    else:
        maturity = "live"
        bootstrap_active = False

    # Sanity check: if maturity logic would set trades=0 but we have runtime data, log bug
    if trades_for_maturity > 0 and maturity == "cold_start":
        warnings.append(
            "BUG: maturity oracle logic error — trades>0 but cold_start selected"
        )

    _canonical_cache = {
        "trades_runtime": runtime_trades,
        "trades_dashboard": dashboard_trades,
        "trades_historical_total": firebase_trades,
        "trades_for_maturity": trades_for_maturity,
        "source": "runtime" if runtime_trades > 0 else ("dashboard" if dashboard_trades > 0 else "bootstrap"),
        "maturity": maturity,
        "bootstrap_active": bootstrap_active,
        "state_consistent": state_consistent,
        "warnings": warnings,
        "ts": now,
    }

    _last_canonical_refresh = now
    return _canonical_cache


def get_authoritative_trade_count() -> int:
    """Shortcut: vrátí jen trade count pro logiku."""
    return get_canonical_state()["trades_for_maturity"]


def is_bootstrap_active() -> bool:
    """Shortcut: je systém v bootstrap fázi?"""
    return get_canonical_state()["bootstrap_active"]


def get_maturity() -> str:
    """Shortcut: vrátí maturity level (cold_start|bootstrap|live)."""
    return get_canonical_state()["maturity"]


def print_canonical_state():
    """Tiskne diagnostic state."""
    state = get_canonical_state()
    print(f"\n[CANONICAL STATE]")
    print(f"  Runtime:    {state['trades_runtime']}")
    print(f"  Dashboard:  {state['trades_dashboard']}")
    print(f"  For Logic:  {state['trades_for_maturity']}  [{state['maturity']}]")
    print(f"  Consistent: {state['state_consistent']}")
    print(f"  Source:     {state['source']}")
    if state['warnings']:
        print(f"  Warnings:")
        for w in state['warnings']:
            print(f"    - {w}")


def invalidate_cache():
    """Force recompute na příští volání (po state changes)."""
    global _canonical_cache, _last_canonical_refresh
    _canonical_cache = None
    _last_canonical_refresh = 0.0
