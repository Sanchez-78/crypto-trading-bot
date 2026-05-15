"""
PRIORITY 5: Probability Calibration — Map raw signal p to empirical reliability buckets.

Problem: Raw signal probability p=46.2% but empirical WR=74.4% (28.2pp deviation).
This indicates the probability model is miscalibrated — it's too pessimistic.

Solution: Build empirical reliability curve via binning historical signals by p-value
and measuring actual WR in each bin. Then use this curve to map raw p → empirical p.

Reliability buckets:
  Bucket 1 (raw p ∈ 0.45-0.55):  empirical p = 0.50 (baseline)
  Bucket 2 (raw p ∈ 0.55-0.60):  empirical p = 0.58
  Bucket 3 (raw p ∈ 0.60-0.70):  empirical p = 0.68
  Bucket 4 (raw p ∈ 0.70-0.80):  empirical p = 0.80
  Bucket 5 (raw p > 0.80):        empirical p = 0.90

Construction:
  1. Track all signals with (raw_p, actual_win_flag) during live trading
  2. Periodically (every 50 trades) recompute empirical p per bucket
  3. Use calibrated p in decision gates (EV, Kelly, sizing)

Usage:
  from src.services.probability_calibration import (
      calibrate_probability, get_calibration_report,
      get_reliability_bucket
  )

  raw_p = 0.46
  empirical_p = calibrate_probability(raw_p)
  # Returns ~0.50 (bucket 1)

  report = get_calibration_report()
  # Shows calibration curve and accuracy metrics

  bucket = get_reliability_bucket(raw_p)
  # Returns bucket index (1-5)
"""

import logging
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CalibrationBucket:
    """Represents one reliability bucket."""
    bucket_id: int
    raw_p_min: float
    raw_p_max: float
    empirical_p: float
    sample_count: int
    actual_wins: int
    actual_losses: int


# ── Global calibration state ─────────────────────────────────────────────────
_calibration_history: List[Dict] = []  # [(raw_p, actual_win), ...]
_calibration_buckets: Dict[int, CalibrationBucket] = {}


def record_signal(raw_probability: float, actual_win: bool) -> None:
    """
    Record a signal with its outcome for later calibration.

    Called after trade close with actual result.

    Args:
        raw_probability: Original signal probability (0.0-1.0)
        actual_win: Whether trade was a winner (True/False)
    """
    _calibration_history.append({
        "raw_p": raw_probability,
        "win": actual_win
    })

    # Keep history to last 500 signals
    if len(_calibration_history) > 500:
        _calibration_history.pop(0)


def _build_default_buckets() -> Dict[int, CalibrationBucket]:
    """
    Build default calibration buckets (before empirical data).

    Default assumptions:
      - Bucket 1 (0.45-0.55): p=0.50 (baseline)
      - Bucket 2 (0.55-0.60): p=0.58
      - Bucket 3 (0.60-0.70): p=0.68
      - Bucket 4 (0.70-0.80): p=0.80
      - Bucket 5 (0.80-1.0):  p=0.90
    """
    return {
        1: CalibrationBucket(
            bucket_id=1, raw_p_min=0.45, raw_p_max=0.55,
            empirical_p=0.50, sample_count=0, actual_wins=0, actual_losses=0
        ),
        2: CalibrationBucket(
            bucket_id=2, raw_p_min=0.55, raw_p_max=0.60,
            empirical_p=0.58, sample_count=0, actual_wins=0, actual_losses=0
        ),
        3: CalibrationBucket(
            bucket_id=3, raw_p_min=0.60, raw_p_max=0.70,
            empirical_p=0.68, sample_count=0, actual_wins=0, actual_losses=0
        ),
        4: CalibrationBucket(
            bucket_id=4, raw_p_min=0.70, raw_p_max=0.80,
            empirical_p=0.80, sample_count=0, actual_wins=0, actual_losses=0
        ),
        5: CalibrationBucket(
            bucket_id=5, raw_p_min=0.80, raw_p_max=1.0,
            empirical_p=0.90, sample_count=0, actual_wins=0, actual_losses=0
        ),
    }


# Initialize with defaults
_calibration_buckets = _build_default_buckets()


def recompute_calibration(min_samples_per_bucket: int = 10) -> None:
    """
    Recompute empirical probabilities from historical signals.

    Called periodically (e.g., every 50 trades) to update buckets.

    Args:
        min_samples_per_bucket: Minimum samples required to update (default 10)
    """
    if len(_calibration_history) < min_samples_per_bucket * 3:
        log.debug(f"[CALIBRATION] Insufficient history ({len(_calibration_history)}), skipping recompute")
        return

    global _calibration_buckets

    # Re-bin history into buckets
    bucket_data = {i: {"wins": 0, "losses": 0} for i in range(1, 6)}

    for record in _calibration_history:
        raw_p = record["raw_p"]
        win = record["win"]

        # Find bucket — use < on upper bound to prevent boundary values landing in two buckets
        bucket_id = None
        for bid, bucket in _calibration_buckets.items():
            if bucket.raw_p_min <= raw_p < bucket.raw_p_max:
                bucket_id = bid
                break
        # Handle raw_p == 1.0 edge (above all half-open intervals): assign to bucket 5
        if bucket_id is None and raw_p >= 0.80:
            bucket_id = 5

        if bucket_id is None:
            continue  # Skip if out of range

        if win:
            bucket_data[bucket_id]["wins"] += 1
        else:
            bucket_data[bucket_id]["losses"] += 1

    # Recompute empirical p per bucket
    for bucket_id, counts in bucket_data.items():
        total = counts["wins"] + counts["losses"]

        if total < min_samples_per_bucket:
            # Reset to research prior rather than holding stale empirical value
            _DEFAULT_P = {1: 0.50, 2: 0.58, 3: 0.68, 4: 0.80, 5: 0.90}
            bucket = _calibration_buckets[bucket_id]
            bucket.empirical_p = _DEFAULT_P.get(bucket_id, 0.5)
            bucket.sample_count = 0
            bucket.actual_wins = 0
            bucket.actual_losses = 0
            continue

        empirical_p = counts["wins"] / total if total > 0 else 0.5

        bucket = _calibration_buckets[bucket_id]
        bucket.sample_count = total
        bucket.actual_wins = counts["wins"]
        bucket.actual_losses = counts["losses"]
        bucket.empirical_p = empirical_p

        log.info(
            f"[CALIBRATION] Bucket {bucket_id} (raw_p {bucket.raw_p_min:.2f}-{bucket.raw_p_max:.2f}): "
            f"empirical_p={empirical_p:.3f} (wins={counts['wins']}, losses={counts['losses']})"
        )


def get_reliability_bucket(raw_probability: float) -> int:
    """
    Determine which calibration bucket a raw probability falls into.

    Args:
        raw_probability: Raw signal probability (0.0-1.0)

    Returns:
        int: Bucket ID (1-5)
    """
    for bucket_id, bucket in _calibration_buckets.items():
        if bucket.raw_p_min <= raw_probability < bucket.raw_p_max:
            return bucket_id
    # Handle raw_p == 1.0: assign to bucket 5; anything else defaults to bucket 3
    return 5 if raw_probability >= 0.80 else 3


def calibrate_probability(raw_probability: float) -> float:
    """
    Map raw signal probability to empirically calibrated probability.

    Uses reliability bucket mapping to convert overly pessimistic/optimistic
    raw probabilities to empirical expectations.

    Args:
        raw_probability: Raw signal probability (0.0-1.0)

    Returns:
        float: Calibrated probability (0.0-1.0)
    """
    bucket_id = get_reliability_bucket(raw_probability)
    bucket = _calibration_buckets.get(bucket_id)

    if bucket is None:
        return raw_probability

    return bucket.empirical_p


def get_calibration_report() -> Dict:
    """
    Generate comprehensive calibration report.

    Returns dict with:
      - total_signals: Total historical signals recorded
      - buckets: Dict of calibration bucket details
      - overall_accuracy: How well calibration matches expectations
      - recommendations: Suggested actions based on calibration state
    """
    total_signals = len(_calibration_history)

    bucket_reports = {}
    for bid, bucket in _calibration_buckets.items():
        bucket_reports[f"bucket_{bid}"] = {
            "raw_p_range": f"{bucket.raw_p_min:.2f}-{bucket.raw_p_max:.2f}",
            "empirical_p": bucket.empirical_p,
            "sample_count": bucket.sample_count,
            "actual_wr": (bucket.actual_wins / max(bucket.sample_count, 1)),
            "accuracy": abs(bucket.empirical_p - (bucket.actual_wins / max(bucket.sample_count, 1)))
                       if bucket.sample_count > 0 else 0,
        }

    overall_accuracy = 0.0
    if total_signals > 0:
        total_wins = sum(1 for r in _calibration_history if r["win"])
        overall_wr = total_wins / total_signals
        overall_accuracy = 1.0 - abs(overall_wr - 0.55)

    recommendations = []
    if total_signals < 50:
        recommendations.append("Insufficient calibration history (< 50 signals), use defaults")
    else:
        for bid, bucket in _calibration_buckets.items():
            if bucket.sample_count > 0:
                error = abs(bucket.empirical_p - (bucket.actual_wins / bucket.sample_count))
                if error > 0.10:
                    recommendations.append(
                        f"Bucket {bid}: Large calibration error ({error:.2f}), "
                        f"consider recalibrating"
                    )

    return {
        "total_signals": total_signals,
        "buckets": bucket_reports,
        "overall_accuracy": overall_accuracy,
        "recommendations": recommendations,
    }


def get_calibration_curve() -> List[Tuple[float, float]]:
    """
    Get calibration curve as list of (raw_p, empirical_p) tuples.

    Useful for plotting or analysis.

    Returns:
        List of (raw_p, empirical_p) points
    """
    points = []
    for bucket_id in sorted(_calibration_buckets.keys()):
        bucket = _calibration_buckets[bucket_id]
        mid_p = (bucket.raw_p_min + bucket.raw_p_max) / 2
        points.append((mid_p, bucket.empirical_p))
    return points


def is_calibration_ready() -> bool:
    """
    Check if calibration has sufficient data to be used.

    Returns True if at least 30 signals recorded (sufficient for basic bucketing).
    """
    return len(_calibration_history) >= 30


def reset_calibration() -> None:
    """Reset calibration to defaults (e.g., for new session)."""
    global _calibration_history, _calibration_buckets
    _calibration_history = []
    _calibration_buckets = _build_default_buckets()
    log.info("[CALIBRATION] Reset to defaults")
