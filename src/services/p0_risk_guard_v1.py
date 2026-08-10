"""Central risk guard for the new signal-router pipeline (Evidence-First
Strategy Expansion v2, §17).

`signal_router.evaluate_signal_for_paper_entry()` has hardcoded
`risk_allowed = False` since it was written (commit d4d69ee, §16 step 9)
with an explicit, disclosed gap: "no central risk guard wired in this
phase". That gap is real -- it means the new P0.8+ pipeline has never
admitted a single signal, ever, regardless of edge or P0 eligibility. This
module closes it, narrowly.

§17: "The risk layer must remain independent of alpha. A positive signal
does not guarantee entry." This module has no knowledge of expected move,
confidence, or net edge -- it only answers "is it currently safe to open
ANYTHING", using the SAME primitives the existing (pre-P0.8) pipeline
already relies on, not a second, parallel risk model (§0.1: prefer the
existing architecture; a second risk engine disagreeing with the first
would itself be a safety hazard).

Reused, not reimplemented:
  - risk_engine.is_daily_dd_safe() -- §17.2 daily risk
  - firebase_client.get_firebase_health() -- §17.1 quota reserve
  - runtime_mode.live_trading_allowed() -- §17.1 paper-only state
  - paper_trade_executor.get_open_positions() -- §17.1 duplicate/opposite
    position conflict

NOT implemented in this phase (§0.3 disclosed, not hidden):
  - maximum aggregate/symbol notional as an independent check (position
    sizing and _SYMBOL_CAPS/_MAX_OPEN are already enforced inside
    open_paper_position() itself -- the single canonical open primitive
    every admitted signal must still pass through -- so this guard would
    only duplicate, not add, protection)
  - maximum correlated exposure (risk_engine.py has portfolio_variance()/
    corr_size_factor() primitives; not wired into this guard's admit/deny
    decision in this pass)
  - consecutive-loss protection / cooldown-after-stop as a distinct,
    configurable per-strategy/per-symbol/per-segment scope (§17.3) -- no
    existing tracker for the NEW pipeline's own loss streak was found to
    reuse; inventing one here without evidence of how loss streaks should
    scope (strategy? symbol? segment?) would be exactly the kind of
    unverified assumption §0.1 forbids. Tracked as follow-up.
  - cooldown after a data fault as a *distinct* guard beyond the
    market-data-freshness check signal_router.py already performs.

Fails closed: if any dependency is unavailable or raises, the guard denies
entry rather than defaulting to permissive (§2.5: "Do not replace a
rejection with a permissive default.").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RiskGuardResult:
    allowed: bool
    reason: str
    checks: Mapping[str, bool] = field(default_factory=dict)


def _check_paper_only_state(live_trading_allowed_fn: Callable[[], bool]) -> Tuple[bool, str]:
    """§17.1 'paper-only state' -- entry must never be permitted while real
    trading is (even theoretically) allowed. This does not gate on whether
    real trading IS happening, only whether it COULD -- the new pipeline
    must be at least as conservative as the existing five-layer guard
    (docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md §5), not weaker."""
    try:
        if live_trading_allowed_fn():
            return False, "real trading is allowed by runtime_mode -- refusing all new-pipeline entries"
        return True, ""
    except Exception as exc:  # fail closed on any inspection failure
        return False, f"paper-only state check raised: {exc!r}"


def _check_daily_risk(is_daily_dd_safe_fn: Callable[[], bool]) -> Tuple[bool, str]:
    """§17.2 daily risk -- delegates to the existing daily-drawdown tracker
    (risk_engine.is_daily_dd_safe()) rather than a second PnL model."""
    try:
        if not is_daily_dd_safe_fn():
            return False, "daily drawdown guard (risk_engine.is_daily_dd_safe) reports unsafe"
        return True, ""
    except Exception as exc:
        return False, f"daily risk check raised: {exc!r}"


def _check_quota_reserve(firebase_health_fn: Callable[[], Mapping]) -> Tuple[bool, str]:
    """§17.1 'quota reserve' -- do not open new evidence-collection
    positions while Firebase is degraded; a position that cannot be
    reliably persisted should not be opened (§15B.3: 'If persistence is
    unavailable... do not open a new paper position.')."""
    try:
        health = firebase_health_fn()
        if not health.get("available", False):
            reason = health.get("reason") or "unknown"
            return False, f"firebase degraded (reason={reason}) -- quota reserve check failing closed"
        return True, ""
    except Exception as exc:
        return False, f"quota reserve check raised: {exc!r}"


def _check_position_conflict(
    symbol: str,
    side: str,
    open_positions: Sequence[Mapping],
) -> Tuple[bool, str]:
    """§17.1 'duplicate position' / 'opposite position conflict'. Symbol/side
    field names are read defensively (`.get`) because `open_positions` may
    come from either paper_trade_executor.get_open_positions() (dict
    keyed by position_id, values include legacy field-name variants) or a
    test fixture -- this function does not assume a single canonical shape
    beyond 'has a symbol-like and side-like field'."""
    side_u = str(side or "").upper()
    normalized_side = "BUY" if side_u in ("BUY", "LONG") else "SELL" if side_u in ("SELL", "SHORT") else side_u
    for pos in open_positions:
        pos_symbol = pos.get("symbol")
        if pos_symbol != symbol:
            continue
        pos_side_raw = str(pos.get("side") or pos.get("action") or "").upper()
        pos_side = "BUY" if pos_side_raw in ("BUY", "LONG") else "SELL" if pos_side_raw in ("SELL", "SHORT") else pos_side_raw
        if pos_side == normalized_side:
            return False, f"duplicate position already open for {symbol}/{normalized_side}"
        if pos_side and pos_side != normalized_side:
            return False, f"opposite position already open for {symbol} ({pos_side} vs requested {normalized_side})"
    return True, ""


def evaluate_risk_guard(
    *,
    symbol: str,
    side: str,
    open_positions: Optional[Sequence[Mapping]] = None,
    live_trading_allowed_fn: Optional[Callable[[], bool]] = None,
    is_daily_dd_safe_fn: Optional[Callable[[], bool]] = None,
    firebase_health_fn: Optional[Callable[[], Mapping]] = None,
    get_open_positions_fn: Optional[Callable[[], Mapping]] = None,
) -> RiskGuardResult:
    """§17 top-level entry point. All dependencies are injectable for tests;
    production callers (signal_router.py) omit them and get the real
    modules. Returns `allowed=False` (fail closed) the instant any check
    fails or any dependency raises -- see module docstring.
    """
    # Lazy imports: this module must not force-import paper_trade_executor,
    # firebase_client, or risk_engine at module-load time -- signal_router.py
    # (which imports this module) is required by tests/test_signal_router_bypass.py
    # to have no import of paper_trade_executor at ALL; importing it here at
    # module scope would transitively violate that even though this module
    # itself never calls an entry primitive. Deferred to call time instead.
    if live_trading_allowed_fn is None:
        from src.core import runtime_mode
        live_trading_allowed_fn = runtime_mode.live_trading_allowed
    if is_daily_dd_safe_fn is None:
        from src.services import risk_engine
        is_daily_dd_safe_fn = risk_engine.is_daily_dd_safe
    if firebase_health_fn is None:
        from src.services import firebase_client
        firebase_health_fn = firebase_client.get_firebase_health
    if open_positions is None:
        if get_open_positions_fn is None:
            from src.services import paper_trade_executor
            get_open_positions_fn = paper_trade_executor.get_open_positions
        try:
            raw = get_open_positions_fn()
            open_positions = list(raw.values()) if isinstance(raw, dict) else list(raw)
        except Exception as exc:
            return RiskGuardResult(
                allowed=False,
                reason=f"could not read open positions: {exc!r}",
                checks={"paper_only_state": False, "daily_risk": False, "quota_reserve": False, "position_conflict": False},
            )

    checks: dict = {}

    paper_ok, paper_reason = _check_paper_only_state(live_trading_allowed_fn)
    checks["paper_only_state"] = paper_ok
    if not paper_ok:
        return RiskGuardResult(allowed=False, reason=paper_reason, checks=checks)

    daily_ok, daily_reason = _check_daily_risk(is_daily_dd_safe_fn)
    checks["daily_risk"] = daily_ok
    if not daily_ok:
        return RiskGuardResult(allowed=False, reason=daily_reason, checks=checks)

    quota_ok, quota_reason = _check_quota_reserve(firebase_health_fn)
    checks["quota_reserve"] = quota_ok
    if not quota_ok:
        return RiskGuardResult(allowed=False, reason=quota_reason, checks=checks)

    conflict_ok, conflict_reason = _check_position_conflict(symbol, side, open_positions)
    checks["position_conflict"] = conflict_ok
    if not conflict_ok:
        return RiskGuardResult(allowed=False, reason=conflict_reason, checks=checks)

    return RiskGuardResult(allowed=True, reason="", checks=checks)
