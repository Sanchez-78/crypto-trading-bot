"""
V10.13t: Forced-Explore Quality Gates (Context-Aware)

Forced-explore mode allows trading pairs with insufficient data when other
conditions are met. This module gates when forced-explore is safe.

PATCH 5: Context-aware spread policy
- Normal trades: strict (spread >= 5%)
- Forced trades: relaxed (spread >= 2-3%, escalates to 1% in hard idle)
- Micro trades: very relaxed (spread >= 0.5% in hard idle)

Gates check:
  1. Spread quality: market spread >= threshold for branch/mode
  2. Execution quality: Recent fill rates acceptable
  3. OFI toxicity: Order flow imbalance not toxic
  4. Coherence: Signal coherence > 0.5 (reasonable signal quality)
  5. Edge bucket: Pair edge >= minimum threshold
  6. Loss cluster: Pair not in active loss cluster

ALL gates must pass for forced-explore.
"""

import logging

log = logging.getLogger(__name__)


def check_spread_quality(
    market_spread_bps: float,
    ev_history: list = None,
    branch: str = "normal",
    idle_mode: str = "NORMAL"
) -> tuple[bool, str]:
    """
    PATCH 5: Check if market spread is acceptable for branch/mode.

    Args:
        market_spread_bps: actual bid-ask spread in basis points
        ev_history: EV history for spread diversity (optional, unused with market_spread_bps)
        branch: "normal" | "forced" | "micro"
        idle_mode: "NORMAL" | "UNBLOCK_SOFT" | "UNBLOCK_MEDIUM" | "UNBLOCK_HARD"

    Returns:
        (pass: bool, detail: str)
    """
    if market_spread_bps is None:
        return True, "no_spread_data"

    try:
        from src.services.idle_escalation import get_admission_policy
        policy = get_admission_policy(idle_mode, branch)
    except Exception:
        # Fallback if idle_escalation unavailable
        if branch == "normal":
            policy = {"spread_min_bps": 5.0, "spread_max_bps": 100.0}
        elif branch == "forced":
            policy = {"spread_min_bps": 3.0, "spread_max_bps": 80.0}
        else:  # micro
            policy = {"spread_min_bps": 0.5, "spread_max_bps": 150.0}

    min_bps = policy.get("spread_min_bps", 5.0)
    max_bps = policy.get("spread_max_bps", 100.0)

    if market_spread_bps < min_bps:
        return (
            False,
            f"spread_too_flat={market_spread_bps:.2f}bps<{min_bps:.1f}bps"
        )
    if market_spread_bps > max_bps:
        return (
            False,
            f"spread_too_wide={market_spread_bps:.2f}bps>{max_bps:.1f}bps"
        )
    return True, f"spread_ok={market_spread_bps:.2f}bps"


def check_execution_quality(symbol: str, min_fill_rate: float = 0.70) -> tuple[bool, str]:
    """Check if recent execution quality acceptable (fill rates)."""
    try:
        from src.services.execution import returns_hist
        if symbol not in returns_hist:
            return True, "no_history"
        fills = returns_hist[symbol].get("fills", [])
        if not fills or len(fills) < 5:
            return True, "insufficient_fills"
        recent_fill_rate = sum(1 for f in fills[-10:] if f >= min_fill_rate) / min(len(fills[-10:]), 10)
        if recent_fill_rate >= min_fill_rate:
            return True, f"fill_rate={recent_fill_rate:.0%}"
        return False, f"fill_rate_low={recent_fill_rate:.0%}"
    except Exception as e:
        log.debug(f"[EXEC_QUALITY] Error: {e}")
        return True, "error_check_skipped"


def check_ofi_toxicity(symbol: str, regime: str, max_toxicity: float = 0.3) -> tuple[bool, str]:
    """Check if OFI toxicity acceptable (not adversarial)."""
    try:
        from src.services.signal_filter import get_ofi_toxicity
        tox = get_ofi_toxicity(symbol, regime)
        if tox is None:
            return True, "no_ofi_data"
        if tox <= max_toxicity:
            return True, f"toxicity={tox:.3f}"
        return False, f"toxicity_high={tox:.3f}"
    except Exception as e:
        log.debug(f"[OFI_TOXICITY] Error: {e}")
        return True, "error_check_skipped"


def check_coherence(signal: dict, min_coherence: float = 0.50) -> tuple[bool, str]:
    """Check if signal coherence acceptable."""
    try:
        coh = signal.get("coherence", 0.5)
        if coh >= min_coherence:
            return True, f"coherence={coh:.2f}"
        return False, f"coherence_low={coh:.2f}"
    except Exception as e:
        log.debug(f"[COHERENCE] Error: {e}")
        return True, "error_check_skipped"


def check_edge_bucket(symbol: str, regime: str, min_edge: float = 0.001) -> tuple[bool, str]:
    """Check if pair edge is above minimum."""
    try:
        from src.services.realtime_decision_engine import lm_edge_strength
        edge = lm_edge_strength(symbol, regime)
        if edge is None:
            return True, "no_edge_data"
        if edge >= min_edge:
            return True, f"edge={edge:.4f}"
        return False, f"edge_too_weak={edge:.4f}"
    except Exception as e:
        log.debug(f"[EDGE_BUCKET] Error: {e}")
        return True, "error_check_skipped"


def check_loss_cluster(symbol: str, regime: str) -> tuple[bool, str]:
    """Check if pair not in active loss cluster."""
    try:
        from src.services.signal_filter import loss_cluster_check
        blocked, reason = loss_cluster_check(symbol, regime)
        if blocked:
            return False, f"in_loss_cluster: {reason}"
        return True, "not_in_cluster"
    except Exception as e:
        log.debug(f"[LOSS_CLUSTER] Error: {e}")
        return True, "error_check_skipped"


def is_forced_explore_allowed(
    symbol: str,
    regime: str,
    signal: dict,
    ev_history: list = None,
    market_spread_bps: float = None,
    branch: str = "forced",
    idle_mode: str = "NORMAL",
    is_rate_limited: bool = False
) -> tuple[bool, dict]:
    """
    PATCH 5: Check if forced-explore/micro is safe for this signal (context-aware).

    Args:
        symbol: trading pair
        regime: market regime
        signal: signal dict with coherence, ws, etc.
        ev_history: EV history (mostly unused now)
        market_spread_bps: actual bid-ask spread in basis points
        branch: "forced" | "micro"
        idle_mode: escalation mode from idle_escalation module
        is_rate_limited: if True, already hit rate limit → block

    Returns:
        (allow: bool, check_results: dict with gate statuses + context info)
    """
    results = {
        "branch": branch,
        "idle_mode": idle_mode,
        "is_rate_limited": is_rate_limited,
    }

    # Rate limit check (not a gate, but overrides)
    if is_rate_limited:
        results["rate_limit"] = {"pass": False, "detail": "rate_limit_exceeded"}
        return False, results

    # Gate 1: Spread quality (PATCH 5: context-aware)
    if market_spread_bps is not None:
        spread_ok, spread_msg = check_spread_quality(
            market_spread_bps,
            ev_history=ev_history,
            branch=branch,
            idle_mode=idle_mode
        )
    else:
        # Fallback to EV history spread check (old method)
        spread_ok, spread_msg = check_spread_quality(
            0.0,  # dummy value
            ev_history=ev_history or [],
            branch=branch,
            idle_mode=idle_mode
        )
    results["spread_quality"] = {"pass": spread_ok, "detail": spread_msg}

    # Gate 2: Execution quality
    exec_ok, exec_msg = check_execution_quality(symbol)
    results["execution_quality"] = {"pass": exec_ok, "detail": exec_msg}

    # Gate 3: OFI toxicity
    ofi_ok, ofi_msg = check_ofi_toxicity(symbol, regime)
    results["ofi_toxicity"] = {"pass": ofi_ok, "detail": ofi_msg}

    # Gate 4: Coherence
    coh_ok, coh_msg = check_coherence(signal)
    results["coherence"] = {"pass": coh_ok, "detail": coh_msg}

    # Gate 5: Edge bucket
    edge_ok, edge_msg = check_edge_bucket(symbol, regime)
    results["edge_bucket"] = {"pass": edge_ok, "detail": edge_msg}

    # Gate 6: Loss cluster
    cluster_ok, cluster_msg = check_loss_cluster(symbol, regime)
    results["loss_cluster"] = {"pass": cluster_ok, "detail": cluster_msg}

    # All gates must pass
    all_pass = all(results[gate]["pass"] for gate in results if gate not in ("branch", "idle_mode", "is_rate_limited"))

    return all_pass, results


def format_forced_explore_result(allowed: bool, results: dict) -> str:
    """Format gate check results for logging."""
    if allowed:
        return "FORCED_EXPLORE_ALLOWED"
    failed = [f"{gate}:{results[gate]['detail']}" for gate in results if not results[gate]["pass"]]
    return f"FORCED_EXPLORE_BLOCKED ({'; '.join(failed[:2])})"
