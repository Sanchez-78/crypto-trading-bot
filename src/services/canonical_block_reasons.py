"""
PATCH 8: Canonical Block Reason Tracking — Machine-readable and consistent.

Standardize block reason reporting across all decision gates so audit can
identify which path (normal/forced/micro) is actually failing and why.

Structure:
  {
    "branch": "forced" | "normal" | "micro",
    "stage": "economic" | "fe_gate" | "score" | "spread" | "risk" | "timeout" | "exec_quality",
    "reason": "spread_too_flat" | "score_too_low" | ... (machine-readable)
    "value": 0.0047,  (optional: value that triggered block)
    "threshold": 0.0050,  (optional: what it had to exceed)
    "idle_mode": "UNBLOCK_HARD",
  }
"""

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# ── Canonical stage codes ──────────────────────────────────────────────────
STAGES = {
    "economic": "Economic health gate",
    "fe_gate": "Forced-explore quality gate",
    "score": "Score threshold gate",
    "spread": "Spread quality gate",
    "risk": "Risk engine gate",
    "timeout": "Position timeout gate",
    "exec_quality": "Execution quality gate",
    "daily_dd": "Daily drawdown gate",
    "freq_cap": "Frequency cap gate",
    "inhibit": "Monte council inhibit",
}

# ── Canonical reason codes ─────────────────────────────────────────────────
REASONS = {
    # Spread gates
    "spread_too_flat": "Market spread < minimum",
    "spread_too_wide": "Market spread > maximum",
    "spread_insufficient_ev": "EV spread too small (flat history)",

    # Score gates
    "score_too_low": "Signal score below threshold",
    "score_hard_blocked": "Score in hard-block zone",

    # Economic gates
    "economic_degraded": "Economic health degraded",
    "economic_fragile": "Economic health fragile",
    "economic_insufficient_data": "Insufficient economic data",

    # Risk gates
    "risk_budget_depleted": "Risk budget exhausted",
    "heat_limit_exceeded": "Heat limit exceeded",
    "dd_limit_exceeded": "Drawdown limit exceeded",

    # Execution quality
    "fill_rate_low": "Fill rate below threshold",
    "latency_high": "Order latency too high",
    "slippage_high": "Slippage exceeded threshold",

    # Forced-explore gates
    "ofi_toxicity_high": "Order flow imbalance too high",
    "coherence_low": "Signal coherence too low",
    "edge_too_weak": "Pair edge below minimum",
    "in_loss_cluster": "Pair in active loss cluster",

    # Frequency
    "frequency_cap_hit": "Trades per window exceeded",

    # Timeout
    "position_timeout": "Position held past max duration",

    # Rate limiting
    "rate_limit_exceeded": "Too many recovery attempts",

    # Market conditions
    "daily_drawdown_halt": "Daily loss limit hit",
    "inhibit_combined": "Combined inhibition signal",

    # Bootstrap
    "insufficient_data": "Insufficient bootstrap data",
    "cold_start_active": "System in cold-start mode",
}


@dataclass
class BlockReason:
    """Canonical block reason record."""
    branch: str      # "normal" | "forced" | "micro"
    stage: str       # Gate stage (economic, fe_gate, score, etc.)
    reason: str      # Machine-readable reason code
    value: Optional[float] = None  # e.g. 0.0047 for spread
    threshold: Optional[float] = None  # e.g. 0.0050
    idle_mode: Optional[str] = None  # e.g. "UNBLOCK_HARD"
    timestamp: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dict for telemetry."""
        return {
            "branch": self.branch,
            "stage": self.stage,
            "reason": self.reason,
            "value": self.value,
            "threshold": self.threshold,
            "idle_mode": self.idle_mode,
        }

    def to_log_string(self) -> str:
        """Format for human-readable logging."""
        parts = [f"{self.stage}:{self.reason}"]
        if self.value is not None and self.threshold is not None:
            parts.append(f"({self.value:.4f}/{self.threshold:.4f})")
        if self.idle_mode:
            parts.append(f"[{self.idle_mode}]")
        return " ".join(parts)


# ── Global tracking ────────────────────────────────────────────────────────
# Track block reasons from current cycle
_cycle_block_reasons: dict[str, list[BlockReason]] = {
    "normal": [],
    "forced": [],
    "micro": [],
}


def record_block_reason(block_reason: BlockReason) -> None:
    """Record a block reason for current cycle."""
    _cycle_block_reasons[block_reason.branch].append(block_reason)
    log.debug(f"[BLOCK_REASON] {block_reason.to_log_string()}")


def get_cycle_block_reasons(branch: str = None) -> dict | list:
    """Get block reasons for current cycle, optionally filtered by branch."""
    if branch is None:
        return _cycle_block_reasons.copy()
    return _cycle_block_reasons.get(branch, [])


def reset_cycle_block_reasons() -> None:
    """Reset block reasons (typically at start of new cycle)."""
    _cycle_block_reasons["normal"] = []
    _cycle_block_reasons["forced"] = []
    _cycle_block_reasons["micro"] = []


def get_top_block_reasons(branch: str = "normal", limit: int = 3) -> list[dict]:
    """Get top N block reasons for a branch, suitable for reporting."""
    reasons = _cycle_block_reasons.get(branch, [])
    # Count by reason code
    reason_counts: dict[str, int] = {}
    for br in reasons:
        key = f"{br.stage}:{br.reason}"
        reason_counts[key] = reason_counts.get(key, 0) + 1

    # Sort by count descending
    sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"reason": r, "count": c} for r, c in sorted_reasons[:limit]]


def get_block_reason_summary() -> dict:
    """Get summary of block reasons across all branches."""
    return {
        "normal_total": len(_cycle_block_reasons["normal"]),
        "forced_total": len(_cycle_block_reasons["forced"]),
        "micro_total": len(_cycle_block_reasons["micro"]),
        "normal_top_reasons": get_top_block_reasons("normal", 2),
        "forced_top_reasons": get_top_block_reasons("forced", 2),
        "micro_top_reasons": get_top_block_reasons("micro", 2),
    }
