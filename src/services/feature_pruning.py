"""
PRIORITY 6: Feature Pruning — Downweight persistently weak features.

Problem: Most features show uniform ~43% WR, indicating poor feature attribution or correlation.
Solution: Track per-feature win rate, downweight persistently weak features.

Feature quality tiers:
  Tier 1 (WR > 60%):  weight multiplier 1.30x (excellent)
  Tier 2 (WR 55-60%): weight multiplier 1.10x (good)
  Tier 3 (WR 50-55%): weight multiplier 1.00x (baseline)
  Tier 4 (WR 45-50%): weight multiplier 0.70x (weak)
  Tier 5 (WR < 45%):  weight multiplier 0.30x (very weak, consider removing)

Weight updates:
  - Exponential moving average with α=0.15 (slow adaptation)
  - Only update if feature had ≥ 20 samples (statistical confidence)
  - Periodic recomputation (every 50 trades)

Removal criteria:
  - Feature in Tier 5 for 200+ consecutive trades
  - Becomes eligible for complete removal from signal calculation

Usage:
  from src.services.feature_pruning import (
      get_feature_weight_multiplier, get_feature_quality_report,
      update_feature_quality
  )

  mult = get_feature_weight_multiplier("rsi_overbought")
  # Returns 0.30 if RSI has been consistently weak

  report = get_feature_quality_report()
  # Identifies underperforming features for removal
"""

import logging
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass
import time as _time

log = logging.getLogger(__name__)


@dataclass
class FeatureStats:
    """Track quality metrics for a single feature."""
    feature_name: str
    win_count: int = 0
    loss_count: int = 0
    flat_count: int = 0
    weight_multiplier: float = 1.00
    last_update_time: float = 0.0
    tier: str = "BASELINE"
    samples_in_current_tier: int = 0
    estimated_feature_importance: float = 0.0


# ── Global feature tracking ─────────────────────────────────────────────────
_feature_stats: Dict[str, FeatureStats] = {}
_feature_signal_history: List[Dict] = []  # [(feature, value, actual_win), ...]


def record_feature_outcome(
    feature_name: str,
    feature_value: float,
    actual_win: bool
) -> None:
    """
    Record a feature's value and outcome for later analysis.

    Called after every trade close.

    Args:
        feature_name: Feature identifier (e.g., "rsi_overbought")
        feature_value: Feature value at entry (0.0-1.0 for probabilities)
        actual_win: Whether trade was a winner
    """
    if feature_name not in _feature_stats:
        _feature_stats[feature_name] = FeatureStats(feature_name=feature_name)

    _feature_signal_history.append({
        "feature": feature_name,
        "value": feature_value,
        "win": actual_win,
        "timestamp": _time.time(),
    })

    # Keep history to last 1000 signals
    if len(_feature_signal_history) > 1000:
        _feature_signal_history.pop(0)


def _compute_feature_win_rate(feature_name: str, min_samples: int = 20) -> Tuple[float, int]:
    """
    Compute win rate for a specific feature from history.

    Args:
        feature_name: Feature to analyze
        min_samples: Minimum samples required to compute (default 20)

    Returns:
        Tuple of (win_rate: 0.0-1.0, sample_count: int)
    """
    relevant_signals = [
        s for s in _feature_signal_history if s["feature"] == feature_name
    ]

    if len(relevant_signals) < min_samples:
        return 0.5, len(relevant_signals)

    wins = sum(1 for s in relevant_signals if s["win"])
    return wins / len(relevant_signals), len(relevant_signals)


def _classify_feature_tier(win_rate: float) -> str:
    """Classify feature into quality tier based on WR."""
    if win_rate > 0.60:
        return "EXCELLENT"
    elif win_rate > 0.55:
        return "GOOD"
    elif win_rate >= 0.50:
        return "BASELINE"
    elif win_rate > 0.45:
        return "WEAK"
    else:
        return "VERY_WEAK"


def _get_tier_multiplier(tier: str) -> float:
    """Get weight multiplier for feature tier."""
    tiers = {
        "EXCELLENT": 1.30,
        "GOOD": 1.10,
        "BASELINE": 1.00,
        "WEAK": 0.70,
        "VERY_WEAK": 0.30,
    }
    return tiers.get(tier, 1.00)


def recompute_feature_quality(min_samples: int = 20, alpha: float = 0.15) -> None:
    """
    Recompute feature quality metrics and update weight multipliers.

    Uses exponential moving average to smooth updates (avoid reaction to noise).

    Args:
        min_samples: Minimum samples per feature to recompute (default 20)
        alpha: EMA smoothing factor (default 0.15 for slow adaptation)
    """
    if len(_feature_signal_history) < min_samples:
        log.debug(f"[FEATURE_PRUNING] Insufficient history ({len(_feature_signal_history)}), skipping recompute")
        return

    for feature_name, stats in _feature_stats.items():
        win_rate, sample_count = _compute_feature_win_rate(feature_name, min_samples)

        if sample_count < min_samples:
            continue  # Not enough data

        # Determine tier
        new_tier = _classify_feature_tier(win_rate)
        new_multiplier = _get_tier_multiplier(new_tier)

        # EMA update
        current_mult = stats.weight_multiplier
        smoothed_mult = (1 - alpha) * current_mult + alpha * new_multiplier

        # Track samples in current tier
        if new_tier == stats.tier:
            stats.samples_in_current_tier += sample_count
        else:
            stats.tier = new_tier
            stats.samples_in_current_tier = sample_count

        stats.weight_multiplier = smoothed_mult
        stats.win_count += sum(1 for s in _feature_signal_history if s["feature"] == feature_name and s["win"])
        stats.loss_count += sum(1 for s in _feature_signal_history if s["feature"] == feature_name and not s["win"])
        stats.last_update_time = _time.time()

        log.info(
            f"[FEATURE_PRUNING] {feature_name}: WR={win_rate:.2f}, tier={new_tier}, "
            f"multiplier={smoothed_mult:.2f}, samples={sample_count}"
        )


def get_feature_weight_multiplier(feature_name: str) -> float:
    """
    Get weight multiplier for a feature.

    Multiplier adjusts feature contribution to overall signal based on quality.

    Args:
        feature_name: Feature identifier

    Returns:
        float: Weight multiplier (0.30 to 1.30)
    """
    if feature_name not in _feature_stats:
        return 1.00

    return _feature_stats[feature_name].weight_multiplier


def get_feature_quality_report() -> Dict:
    """
    Generate comprehensive feature quality report.

    Returns dict with:
      - total_features: Number of features tracked
      - excellent: Count of excellent features
      - good: Count of good features
      - baseline: Count of baseline features
      - weak: Count of weak features
      - very_weak: Count of very weak features
      - candidate_for_removal: Features eligible for removal (Tier 5, 200+ trades)
      - avg_weight: Average weight multiplier across all features
      - feature_details: Per-feature breakdown
    """
    tier_counts = {
        "EXCELLENT": 0,
        "GOOD": 0,
        "BASELINE": 0,
        "WEAK": 0,
        "VERY_WEAK": 0,
    }

    candidates_for_removal = []
    multipliers = []
    feature_details = []

    for feature_name, stats in _feature_stats.items():
        tier = stats.tier
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        multipliers.append(stats.weight_multiplier)

        # Identify removal candidates
        if tier == "VERY_WEAK" and stats.samples_in_current_tier >= 200:
            candidates_for_removal.append(feature_name)

        total_trades = stats.win_count + stats.loss_count
        wr = stats.win_count / max(total_trades, 1)

        feature_details.append({
            "name": feature_name,
            "tier": tier,
            "weight_multiplier": stats.weight_multiplier,
            "win_rate": wr,
            "samples_in_tier": stats.samples_in_current_tier,
            "total_trades": total_trades,
        })

    # Sort details by weight (worst first)
    feature_details.sort(key=lambda x: x["weight_multiplier"])

    avg_weight = float(np.mean(multipliers)) if multipliers else 1.00

    return {
        "total_features": len(_feature_stats),
        "tier_counts": tier_counts,
        "avg_weight": avg_weight,
        "candidates_for_removal": candidates_for_removal,
        "feature_details": feature_details,
        "recommendations": (
            f"Remove {len(candidates_for_removal)} features: {candidates_for_removal}"
            if candidates_for_removal
            else "No features eligible for removal yet"
        )
    }


def get_feature_importance_estimate() -> Dict[str, float]:
    """
    Estimate relative feature importance based on contribution to wins.

    Importance = (contribution to winning trades) / (total contribution)

    Returns:
        Dict mapping feature_name to importance score (0.0-1.0)
    """
    importance = {}

    for feature_name, stats in _feature_stats.items():
        if stats.weight_multiplier > 0:
            importance[feature_name] = (
                stats.win_count * stats.weight_multiplier
            ) / max(
                stats.weight_multiplier + stats.loss_count, 1e-6
            )

    # Normalize
    total_importance = sum(importance.values())
    if total_importance > 0:
        importance = {
            k: v / total_importance for k, v in importance.items()
        }

    return importance


def reset_feature_tracking() -> None:
    """Reset all feature tracking to defaults."""
    global _feature_stats, _feature_signal_history
    _feature_stats = {}
    _feature_signal_history = []
    log.info("[FEATURE_PRUNING] Reset all tracking")
