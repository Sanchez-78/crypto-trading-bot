"""
PRIORITY 8: Audit Regression Testing — Better baseline comparison and regression detection.

Compares current audit run against previous baseline to catch regressions:

Regression categories:
  1. Acceptance rate regression (acceptance_rate down >5pp)
  2. Bootstrap phase regression (any phase acceptance drops >10pp)
  3. Branch split regression (branch pass_rate drops >8pp)
  4. Weak EV acceptance increase (weak EV acceptance up >10pp)
  5. Gate blocking shift (top blocker changed or % increased >10pp)

Usage:
  from src.services.audit_regression_testing import (
      save_audit_baseline, load_audit_baseline,
      check_for_regressions, get_regression_report
  )

  # After successful audit, save baseline
  save_audit_baseline("audit_baseline_v10.13.json")

  # On next audit, compare
  regressions = check_for_regressions("audit_baseline_v10.13.json")
  if regressions["has_regressions"]:
      print(regressions["report"])
"""

import logging
import json
from typing import Dict, Optional, List
from pathlib import Path

log = logging.getLogger(__name__)


def save_audit_baseline(audit_report: Dict, output_file: str) -> bool:
    """
    Save current audit report as baseline for future regression testing.

    Args:
        audit_report: Enhanced audit report dict from audit_enhancements.py
        output_file: File path to save baseline

    Returns:
        bool: True if saved successfully
    """
    try:
        with open(output_file, "w") as f:
            json.dump(audit_report, f, indent=2, default=str)
        log.info(f"[AUDIT_REGRESSION] Baseline saved to {output_file}")
        return True
    except Exception as e:
        log.error(f"[AUDIT_REGRESSION] Failed to save baseline: {e}")
        return False


def load_audit_baseline(baseline_file: str) -> Optional[Dict]:
    """
    Load previously saved audit baseline.

    Args:
        baseline_file: File path to baseline

    Returns:
        Dict: Audit report, or None if failed to load
    """
    try:
        with open(baseline_file, "r") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"[AUDIT_REGRESSION] Failed to load baseline: {e}")
        return None


def _check_acceptance_regression(current: Dict, baseline: Dict) -> tuple[bool, List[str]]:
    """Check if overall acceptance rate regressed."""
    current_rate = current.get("overall_acceptance_rate", 0)
    baseline_rate = baseline.get("overall_acceptance_rate", 0)

    regression_threshold = 0.05  # 5 percentage points

    if current_rate < baseline_rate - regression_threshold:
        return True, [
            f"Acceptance rate regressed: {current_rate:.1%} vs baseline {baseline_rate:.1%} "
            f"(down {(baseline_rate - current_rate):.1%}pp)"
        ]

    return False, []


def _check_bootstrap_regression(current: Dict, baseline: Dict) -> tuple[bool, List[str]]:
    """Check if bootstrap phase acceptance rates regressed."""
    issues = []

    current_bootstrap = current.get("bootstrap_analysis", {}).get("by_phase", {})
    baseline_bootstrap = baseline.get("bootstrap_analysis", {}).get("by_phase", {})

    regression_threshold = 0.10  # 10 percentage points

    for phase in ["COLD", "WARM", "LIVE"]:
        current_rate = current_bootstrap.get(phase, {}).get("pass_rate", 0)
        baseline_rate = baseline_bootstrap.get(phase, {}).get("pass_rate", 0)

        if baseline_rate > 0 and current_rate < baseline_rate - regression_threshold:
            issues.append(
                f"{phase} phase regression: {current_rate:.1%} vs {baseline_rate:.1%} "
                f"(down {(baseline_rate - current_rate):.1%}pp)"
            )

    return len(issues) > 0, issues


def _check_branch_regression(current: Dict, baseline: Dict) -> tuple[bool, List[str]]:
    """Check if branch-specific pass rates regressed."""
    issues = []

    current_branches = current.get("branch_splits", {})
    baseline_branches = baseline.get("branch_splits", {})

    regression_threshold = 0.08  # 8 percentage points

    for branch_key in ["branch_normal", "branch_forced", "branch_micro"]:
        current_rate = current_branches.get(branch_key, {}).get("pass_rate", 0)
        baseline_rate = baseline_branches.get(branch_key, {}).get("pass_rate", 0)

        if baseline_rate > 0 and current_rate < baseline_rate - regression_threshold:
            issues.append(
                f"{branch_key} regression: {current_rate:.1%} vs {baseline_rate:.1%} "
                f"(down {(baseline_rate - current_rate):.1%}pp)"
            )

    return len(issues) > 0, issues


def _check_weak_ev_regression(current: Dict, baseline: Dict) -> tuple[bool, List[str]]:
    """Check if weak EV acceptance increased (bad)."""
    issues = []

    current_weak_ev = current.get("weak_ev_analysis", {}).get("weak_ev_acceptance_rate", 0)
    baseline_weak_ev = baseline.get("weak_ev_analysis", {}).get("weak_ev_acceptance_rate", 0)

    regression_threshold = 0.10  # 10 percentage points

    if current_weak_ev > baseline_weak_ev + regression_threshold:
        issues.append(
            f"Weak EV acceptance increased: {current_weak_ev:.1%} vs {baseline_weak_ev:.1%} "
            f"(up {(current_weak_ev - baseline_weak_ev):.1%}pp)"
        )

    return len(issues) > 0, issues


def _check_gate_blocking_regression(current: Dict, baseline: Dict) -> tuple[bool, List[str]]:
    """Check if gate blocking patterns changed significantly."""
    issues = []

    current_gate = current.get("gate_blocking", {})
    baseline_gate = baseline.get("gate_blocking", {})

    current_top = current_gate.get("top_blocker", "unknown")
    baseline_top = baseline_gate.get("top_blocker", "unknown")

    if current_top != baseline_top:
        issues.append(
            f"Top blocker changed: {current_top} vs {baseline_top}"
        )

    # Check if any gate's percentage increased significantly
    current_pct = current_gate.get("gate_percentages", {})
    baseline_pct = baseline_gate.get("gate_percentages", {})

    for gate, current_val in current_pct.items():
        baseline_val = baseline_pct.get(gate, 0)
        if current_val > baseline_val + 10:
            issues.append(
                f"{gate} blocking increased: {current_val:.1f}% vs {baseline_val:.1f}% "
                f"(up {current_val - baseline_val:.1f}pp)"
            )

    return len(issues) > 0, issues


def check_for_regressions(baseline_file: str, current_report: Dict) -> Dict:
    """
    Check current audit against baseline for regressions.

    Args:
        baseline_file: File path to baseline
        current_report: Current enhanced audit report

    Returns:
        Dict with:
          - has_regressions: bool
          - categories: dict of {category: (has_issue, [issues])}
          - report: human-readable summary
    """
    baseline = load_audit_baseline(baseline_file)

    if baseline is None:
        return {
            "has_regressions": False,
            "categories": {},
            "report": "No baseline loaded, cannot check regressions",
        }

    results = {
        "acceptance_rate": _check_acceptance_regression(current_report, baseline),
        "bootstrap_phase": _check_bootstrap_regression(current_report, baseline),
        "branch_split": _check_branch_regression(current_report, baseline),
        "weak_ev": _check_weak_ev_regression(current_report, baseline),
        "gate_blocking": _check_gate_blocking_regression(current_report, baseline),
    }

    has_regressions = any(has_issue for has_issue, _ in results.values())

    # Build report
    report_lines = ["[REGRESSION TEST RESULTS]"]

    if has_regressions:
        report_lines.append("STATUS: REGRESSIONS DETECTED")
    else:
        report_lines.append("STATUS: NO REGRESSIONS")

    report_lines.append("")

    for category, (has_issue, issues) in results.items():
        if has_issue:
            report_lines.append(f"[{category.upper()}] FAILED:")
            for issue in issues:
                report_lines.append(f"  - {issue}")
        else:
            report_lines.append(f"[{category.upper()}] OK")

    report = "\n".join(report_lines)

    return {
        "has_regressions": has_regressions,
        "categories": {cat: has_issue for cat, (has_issue, _) in results.items()},
        "issues": {cat: issues for cat, (_, issues) in results.items()},
        "report": report,
    }


def generate_regression_fix_recommendations(regressions: Dict) -> List[str]:
    """
    Generate recommended fixes based on detected regressions.

    Args:
        regressions: Result from check_for_regressions()

    Returns:
        List of recommended actions
    """
    recommendations = []

    issues = regressions.get("issues", {})

    if issues.get("acceptance_rate"):
        recommendations.append(
            "Acceptance rate low: Review gate thresholds (EV min, score min, spread min)"
        )

    if issues.get("bootstrap_phase"):
        if any("COLD" in i for i in issues.get("bootstrap_phase", [])):
            recommendations.append(
                "COLD phase acceptance regressed: Relax gates for data collection phase"
            )
        if any("WARM" in i for i in issues.get("bootstrap_phase", [])):
            recommendations.append(
                "WARM phase acceptance regressed: Check economic gate and soft constraints"
            )

    if issues.get("branch_split"):
        if any("forced" in i for i in issues.get("branch_split", [])):
            recommendations.append(
                "Forced branch acceptance down: Review idle escalation modes and spread thresholds"
            )
        if any("micro" in i for i in issues.get("branch_split", [])):
            recommendations.append(
                "Micro branch acceptance down: Check micro-specific gates (score, spread)"
            )

    if issues.get("weak_ev"):
        recommendations.append(
            "Too many weak-EV trades: Increase EV minimum threshold or reduce confidence scaling"
        )

    if issues.get("gate_blocking"):
        if any("changed" in i for i in issues.get("gate_blocking", [])):
            recommendations.append(
                "Top blocker changed: Investigate which gate became dominant"
            )

    return recommendations
