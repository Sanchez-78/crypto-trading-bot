"""
PRIORITY 7: Audit Enhancements — Better branch splits and granular reporting.

Extends pre_live_audit.py with:
  1. Bootstrap phase tracking (COLD/WARM/LIVE acceptance rates)
  2. Weak EV analysis (% of trades with EV < 0.05 that were executed)
  3. Per-branch detailed metrics (normal/forced/micro split across all dimensions)
  4. Gate-by-gate breakdown (which gate blocked most trades)

Usage:
  from src.services.audit_enhancements import (
      get_enhanced_audit_report, track_signal_evaluation,
      get_bootstrap_phase_analysis
  )

  # Track each signal during audit
  track_signal_evaluation(
      sym="BTCUSDT",
      regime="TRENDING",
      branch="normal",
      ev=0.035,
      passed=True,
      bootstrap_phase="WARM"
  )

  report = get_enhanced_audit_report()
  # Returns detailed report with branch splits and bootstrap phase analysis
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class BootstrapPhase(Enum):
    """Bootstrap phase for a trade."""
    COLD = "COLD"      # < 30 trades
    WARM = "WARM"      # 30-100 trades
    LIVE = "LIVE"      # >= 100 trades


@dataclass
class SignalEvaluation:
    """Track decision point for a single signal."""
    sym: str
    regime: str
    branch: str = "normal"  # "normal", "forced", "micro"
    ev: float = 0.0
    score: float = 0.0
    passed: bool = False
    bootstrap_phase: str = "WARM"
    block_reason: Optional[str] = None
    gate_failed: Optional[str] = None  # "economic", "spread", "score", etc.


# ── Global audit state ─────────────────────────────────────────────────────
_signal_evaluations: List[SignalEvaluation] = []


def track_signal_evaluation(
    sym: str,
    regime: str,
    branch: str = "normal",
    ev: float = 0.0,
    score: float = 0.0,
    passed: bool = False,
    bootstrap_phase: str = "WARM",
    block_reason: Optional[str] = None,
    gate_failed: Optional[str] = None,
) -> None:
    """
    Track a single signal evaluation for audit.

    Called during signal processing in realtime_decision_engine.

    Args:
        sym: Symbol
        regime: Market regime
        branch: Trade branch ("normal", "forced", "micro")
        ev: Expected value
        score: Signal score
        passed: Whether trade was executed
        bootstrap_phase: Current bootstrap phase
        block_reason: Human-readable reason if blocked
        gate_failed: Which gate caused block ("economic", "fe_gate", etc.)
    """
    evaluation = SignalEvaluation(
        sym=sym,
        regime=regime,
        branch=branch,
        ev=ev,
        score=score,
        passed=passed,
        bootstrap_phase=bootstrap_phase,
        block_reason=block_reason,
        gate_failed=gate_failed,
    )
    _signal_evaluations.append(evaluation)


def get_bootstrap_phase_analysis() -> Dict:
    """
    Analyze acceptance rates by bootstrap phase.

    Returns dict with:
      - cold_total: Signals evaluated in COLD phase
      - cold_passed: Passed in COLD phase
      - cold_pass_rate: Percentage accepted
      - (similar for WARM, LIVE)
      - recommendation: Suggested gate adjustments per phase
    """
    by_phase = {}

    for phase in ["COLD", "WARM", "LIVE"]:
        phase_evals = [e for e in _signal_evaluations if e.bootstrap_phase == phase]
        if not phase_evals:
            by_phase[phase] = {
                "total": 0,
                "passed": 0,
                "pass_rate": 0.0,
            }
        else:
            passed = sum(1 for e in phase_evals if e.passed)
            by_phase[phase] = {
                "total": len(phase_evals),
                "passed": passed,
                "pass_rate": passed / len(phase_evals),
            }

    # Bootstrap phase assessment
    recommendations = []
    for phase, stats in by_phase.items():
        if stats["total"] == 0:
            continue

        pass_rate = stats["pass_rate"]

        if phase == "COLD":
            if pass_rate < 0.70:
                recommendations.append(f"COLD phase pass_rate too low ({pass_rate:.1%}), relax gates")
        elif phase == "WARM":
            if pass_rate < 0.40:
                recommendations.append(f"WARM phase acceptance too low ({pass_rate:.1%}), consider softening")
        elif phase == "LIVE":
            if pass_rate > 0.70:
                recommendations.append(f"LIVE phase acceptance high ({pass_rate:.1%}), may be too loose")

    return {
        "by_phase": by_phase,
        "recommendations": recommendations,
    }


def get_branch_split_analysis() -> Dict:
    """
    Get detailed metrics broken down by trade branch.

    Returns dict with normal/forced/micro splits:
      - branch_normal: Count, pass_rate, avg_ev, avg_score
      - branch_forced: Same
      - branch_micro: Same
    """
    by_branch = {}

    for branch in ["normal", "forced", "micro"]:
        branch_evals = [e for e in _signal_evaluations if e.branch == branch]

        if not branch_evals:
            by_branch[f"branch_{branch}"] = {
                "total": 0,
                "passed": 0,
                "pass_rate": 0.0,
                "avg_ev": 0.0,
                "avg_score": 0.0,
            }
        else:
            passed = sum(1 for e in branch_evals if e.passed)
            avg_ev = sum(e.ev for e in branch_evals) / len(branch_evals)
            avg_score = sum(e.score for e in branch_evals) / len(branch_evals)

            by_branch[f"branch_{branch}"] = {
                "total": len(branch_evals),
                "passed": passed,
                "pass_rate": passed / len(branch_evals),
                "avg_ev": avg_ev,
                "avg_score": avg_score,
            }

    return by_branch


def get_weak_ev_analysis(ev_threshold: float = 0.05) -> Dict:
    """
    Analyze trades with weak EV (below threshold).

    Returns:
      - weak_ev_total: Count with EV < threshold
      - weak_ev_accepted: How many of those were executed
      - weak_ev_acceptance_rate: Percentage accepted (should be < 20%)
      - examples: List of weak EV trades that were accepted (risk)
    """
    weak_ev_evals = [e for e in _signal_evaluations if e.ev < ev_threshold]

    if not weak_ev_evals:
        return {
            "weak_ev_total": 0,
            "weak_ev_accepted": 0,
            "weak_ev_acceptance_rate": 0.0,
            "examples": [],
        }

    accepted = [e for e in weak_ev_evals if e.passed]
    acceptance_rate = len(accepted) / len(weak_ev_evals)

    examples = [
        {
            "sym": e.sym,
            "regime": e.regime,
            "branch": e.branch,
            "ev": e.ev,
            "score": e.score,
            "bootstrap_phase": e.bootstrap_phase,
        }
        for e in accepted[:5]
    ]

    return {
        "weak_ev_total": len(weak_ev_evals),
        "weak_ev_accepted": len(accepted),
        "weak_ev_acceptance_rate": acceptance_rate,
        "recommendation": (
            "GOOD: Accepting mostly high-EV trades" if acceptance_rate < 0.20
            else "CAUTION: Too many weak-EV trades accepted" if acceptance_rate > 0.50
            else "OK: Moderate weak-EV acceptance"
        ),
        "examples": examples,
    }


def get_gate_blocking_analysis() -> Dict:
    """
    Analyze which gates are blocking most trades.

    Returns dict with gate block frequency:
      - economic: Count blocked by economic gate
      - spread: Count blocked by spread quality
      - score: Count blocked by score threshold
      - other: Other blockers
    """
    gate_blocks = {
        "economic": 0,
        "spread": 0,
        "score": 0,
        "fe_gate": 0,
        "other": 0,
    }

    blocked_evals = [e for e in _signal_evaluations if not e.passed]

    for e in blocked_evals:
        gate = e.gate_failed or "other"
        if gate in gate_blocks:
            gate_blocks[gate] += 1
        else:
            gate_blocks["other"] += 1

    total_blocked = len(blocked_evals)

    gate_percentages = {
        gate: (count / total_blocked * 100) if total_blocked > 0 else 0.0
        for gate, count in gate_blocks.items()
    }

    # Find top blocker
    top_blocker = max(gate_percentages.items(), key=lambda x: x[1]) if gate_percentages else ("none", 0)

    return {
        "total_blocked": total_blocked,
        "gate_blocks": gate_blocks,
        "gate_percentages": gate_percentages,
        "top_blocker": f"{top_blocker[0]} ({top_blocker[1]:.1f}%)",
    }


def get_enhanced_audit_report() -> Dict:
    """
    Generate comprehensive enhanced audit report.

    Combines bootstrap phase analysis, branch splits, weak EV analysis,
    and gate blocking analysis.

    Returns:
        Dict with all analytical components
    """
    total_evals = len(_signal_evaluations)
    if total_evals == 0:
        return {
            "total_signals_evaluated": 0,
            "total_accepted": 0,
            "overall_acceptance_rate": 0.0,
            "bootstrap_analysis": {},
            "branch_splits": {},
            "weak_ev_analysis": {},
            "gate_blocking": {},
        }

    total_passed = sum(1 for e in _signal_evaluations if e.passed)
    overall_acceptance = total_passed / total_evals

    return {
        "total_signals_evaluated": total_evals,
        "total_accepted": total_passed,
        "overall_acceptance_rate": overall_acceptance,
        "bootstrap_analysis": get_bootstrap_phase_analysis(),
        "branch_splits": get_branch_split_analysis(),
        "weak_ev_analysis": get_weak_ev_analysis(),
        "gate_blocking": get_gate_blocking_analysis(),
    }


def reset_audit_tracking() -> None:
    """Reset audit state (for new session)."""
    global _signal_evaluations
    _signal_evaluations = []
    log.info("[AUDIT_ENHANCEMENTS] Reset tracking")


def get_audit_diagnostics() -> str:
    """
    Get human-readable audit diagnostics.

    Useful for logging/debugging.
    """
    report = get_enhanced_audit_report()

    lines = [
        "[AUDIT ENHANCEMENTS DIAGNOSTICS]",
        f"Total signals evaluated: {report['total_signals_evaluated']}",
        f"Total accepted: {report['total_accepted']}",
        f"Overall acceptance rate: {report['overall_acceptance_rate']:.1%}",
        "",
        "[Bootstrap Phase Analysis]",
    ]

    bootstrap = report.get("bootstrap_analysis", {})
    for phase, stats in bootstrap.get("by_phase", {}).items():
        lines.append(
            f"  {phase}: {stats['passed']}/{stats['total']} ({stats['pass_rate']:.1%})"
        )

    lines.append("\n[Branch Splits]")
    for branch, stats in report.get("branch_splits", {}).items():
        lines.append(
            f"  {branch}: {stats['passed']}/{stats['total']} ({stats['pass_rate']:.1%}), "
            f"avg_ev={stats['avg_ev']:.4f}"
        )

    weak_ev = report.get("weak_ev_analysis", {})
    lines.append(f"\n[Weak EV Analysis]")
    lines.append(
        f"  Weak EV trades: {weak_ev.get('weak_ev_total', 0)}, "
        f"Accepted: {weak_ev.get('weak_ev_accepted', 0)} "
        f"({weak_ev.get('weak_ev_acceptance_rate', 0):.1%})"
    )

    gate_block = report.get("gate_blocking", {})
    lines.append(f"\n[Gate Blocking]")
    lines.append(f"  Top blocker: {gate_block.get('top_blocker', 'none')}")

    return "\n".join(lines)
