"""
Calibration Guard Module

Monitors signal calibration quality and detects calibration drift.
Prevents trading when prediction accuracy degrades.

Calibration drift occurs when:
  - Predicted win probability diverges from actual win rate
  - Mean discrepancy exceeds threshold
  - Model has become unreliable
"""

import numpy as np
import logging
from typing import Optional, List, Tuple
from collections import deque

logger = logging.getLogger(__name__)


class CalibrationGuard:
    """
    Monitors calibration between predicted probabilities and actual outcomes.
    
    Maintains a rolling window of (predicted_p, actual_outcome) pairs.
    Detects when model predictions diverge from reality.
    """
    
    def __init__(
        self,
        window_size: int = 500,
        drift_threshold: float = 0.05,
        min_samples: int = 50
    ):
        """
        Initialize calibration guard.
        
        Args:
            window_size: Size of rolling observation window (default 500)
            drift_threshold: Mean discrepancy threshold for drift alarm (default 5%)
            min_samples: Minimum samples before validating calibration (default 50)
        """
        self.window: deque = deque(maxlen=window_size)
        self.drift_threshold = drift_threshold
        self.min_samples = min_samples
        self.drift_detected = False
        self.last_check_size = 0
    
    def update(self, predicted_p: float, actual_outcome: int):
        """
        Record a trade outcome for calibration monitoring.
        
        Args:
            predicted_p: Predicted win probability (0-1)
            actual_outcome: Actual outcome (1=WIN, 0=LOSS)
            
        Examples:
            >>> guard = CalibrationGuard()
            >>> guard.update(0.6, 1)  # Predicted 60%, actually won
            >>> guard.update(0.55, 0)  # Predicted 55%, actually lost
        """
        if not (0 <= predicted_p <= 1):
            logger.warning(f"Invalid predicted_p: {predicted_p}, clamping")
            predicted_p = max(0, min(1, predicted_p))
        
        if actual_outcome not in (0, 1):
            logger.warning(f"Invalid actual_outcome: {actual_outcome}, treating as 0")
            actual_outcome = 0
        
        self.window.append((predicted_p, actual_outcome))
    
    def is_broken(self) -> bool:
        """
        Check if calibration has drifted (model is unreliable).
        
        Returns:
            True if calibration is broken (drift detected), False otherwise
            
        Logic:
            - Requires minimum samples (default 50)
            - Compares mean predicted vs mean actual
            - Flags if discrepancy > threshold (5%)
        """
        if len(self.window) < self.min_samples:
            return False
        
        preds = np.array([p for p, _ in self.window])
        actuals = np.array([a for _, a in self.window])
        
        mean_pred = preds.mean()
        mean_actual = actuals.mean()
        
        discrepancy = abs(mean_pred - mean_actual)
        is_broken = discrepancy > self.drift_threshold
        
        if is_broken != self.drift_detected:
            status = "BROKEN 🚨" if is_broken else "RESTORED ✅"
            logger.warning(
                f"Calibration {status}: mean_pred={mean_pred:.3f}, "
                f"mean_actual={mean_actual:.3f}, discrepancy={discrepancy:.3f}"
            )
            self.drift_detected = is_broken
        
        return is_broken
    
    def get_calibration_quality(self) -> float:
        """
        Get normalized calibration quality score (0-1).
        
        Returns:
            Quality score where:
            - 1.0 = Perfect calibration (mean_pred == mean_actual)
            - 0.0 = Severe drift (discrepancy >> threshold)
            
        Used for signal confidence adjustment.
        """
        if len(self.window) < self.min_samples:
            return 0.5  # Neutral before enough data
        
        preds = np.array([p for p, _ in self.window])
        actuals = np.array([a for _, a in self.window])
        
        mean_pred = preds.mean()
        mean_actual = actuals.mean()
        
        discrepancy = abs(mean_pred - mean_actual)
        
        # Map discrepancy to quality: 0 = 1.0, threshold = 0.5, 2x threshold = 0.0
        quality = max(0, 1.0 - (discrepancy / (self.drift_threshold * 2)))
        
        return quality
    
    def get_reliability_multiplier(self) -> float:
        """
        Get EV multiplier based on calibration reliability.
        
        Used to reduce signal strength when calibration is suspect.
        
        Returns:
            Multiplier (0.3-1.0) to apply to EV:
            - 1.0 = Perfect calibration
            - 0.5 = Drift detected (50% penalty)
            - 0.3 = Severe drift (70% penalty, near break state)
            
        Example:
            >>> guard.get_reliability_multiplier()
            0.5  # 50% EV reduction due to drift
        """
        quality = self.get_calibration_quality()
        
        if self.is_broken():
            return 0.5  # 50% penalty when broken
        
        # Scale 0.5-1.0 based on quality
        return 0.5 + (quality * 0.5)
    
    def get_statistics(self) -> dict:
        """
        Get detailed calibration statistics.
        
        Returns:
            Dict with:
            - samples: Number of observations
            - mean_predicted: Mean predicted probability
            - mean_actual: Mean actual outcome (win rate)
            - discrepancy: Absolute difference
            - is_broken: Calibration status
            - quality_score: 0-1 quality metric
        """
        if len(self.window) < self.min_samples:
            return {
                "samples": len(self.window),
                "mean_predicted": None,
                "mean_actual": None,
                "discrepancy": None,
                "is_broken": False,
                "quality_score": 0.5,
                "status": "INSUFFICIENT_DATA"
            }
        
        preds = np.array([p for p, _ in self.window])
        actuals = np.array([a for _, a in self.window])
        
        mean_pred = preds.mean()
        mean_actual = actuals.mean()
        discrepancy = abs(mean_pred - mean_actual)
        
        return {
            "samples": len(self.window),
            "mean_predicted": float(mean_pred),
            "mean_actual": float(mean_actual),
            "discrepancy": float(discrepancy),
            "is_broken": self.is_broken(),
            "quality_score": self.get_calibration_quality(),
            "reliability_multiplier": self.get_reliability_multiplier(),
            "status": "BROKEN" if self.is_broken() else "HEALTHY"
        }
    
    def reset(self):
        """Clear calibration window (use when retraining model)."""
        self.window.clear()
        self.drift_detected = False
        logger.info("Calibration guard reset")
    
    def clear(self):
        """Alias for reset()."""
        self.reset()
