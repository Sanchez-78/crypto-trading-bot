"""
V10.13i: Hard-Block Adaptive Relaxation & Performance Optimization

Dynamically adjusts hard-block thresholds based on system state.
Reduces computational waste in the critical signal path.

Components:
1. HardBlockZones — Adaptive soft/hard zone management
2. ComputeCaching — LRU cache for expensive calculations
3. RelaxationStrategy — State-aware threshold adjustment
"""

import logging
import time
from functools import lru_cache
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Global state tracking
_last_state_check = [time.time()]
_cached_metrics = {}
_zone_history = {}  # Track zone transitions for debugging


class HardBlockZones:
    """
    Manages soft/hard zone boundaries that adapt to system health.
    
    Zone structure:
      ACCEPT: score > hard_floor + buffer
      SOFT:   hard_floor <= score <= hard_floor + buffer
      HARD:   score < hard_floor
    
    Adaptation:
      - Healthy: buffer is narrow (stricter)
      - Idle/Low health: buffer is wide (more forgiving)
    """

    def __init__(self):
        self.base_hard_floor = 0.05  # Minimum acceptable score
        self.base_buffer = 0.06      # Normal soft zone
        self.current_hard_floor = self.base_hard_floor
        self.current_buffer = self.base_buffer
        self.last_adjustment_ts = time.time()

    def adjust(self, health: float, idle_seconds: float, trades_count: int = 0) -> Dict[str, float]:
        """
        Compute adaptive zone boundaries.
        
        Returns dict with:
          - hard_floor: Minimum score before hard reject
          - soft_ceiling: Boundary between soft penalty and accept
          - soft_zone_size: Width of soft zone
        """
        now = time.time()
        
        # Don't recalculate more than once per 30s
        if now - self.last_adjustment_ts < 30 and self.current_buffer > 0:
            return {
                "hard_floor": self.current_hard_floor,
                "soft_ceiling": self.current_hard_floor + self.current_buffer,
                "soft_zone_size": self.current_buffer,
            }

        # Determine relaxation level
        if idle_seconds > 900:  # 15+ min idle
            relaxation = "CRITICAL"
            new_buffer = 0.20  # Very wide soft zone
            new_hard_floor = 0.02  # Very lenient
        elif idle_seconds > 600:  # 10+ min idle
            relaxation = "SEVERE"
            new_buffer = 0.15
            new_hard_floor = 0.03
        elif idle_seconds > 300 or health < 0.15:  # 5+ min idle OR critical health
            relaxation = "HIGH"
            new_buffer = 0.12
            new_hard_floor = 0.04
        elif idle_seconds > 60 or health < 0.30:  # 1+ min idle OR low health
            relaxation = "MODERATE"
            new_buffer = 0.09
            new_hard_floor = 0.045
        else:  # Healthy
            relaxation = "NONE"
            new_buffer = self.base_buffer
            new_hard_floor = self.base_hard_floor

        # Log significant transitions
        old_buffer = self.current_buffer
        if abs(new_buffer - old_buffer) > 0.01:
            logger.warning(
                f"🔄 HardBlock zone adjustment: {relaxation} "
                f"(idle={idle_seconds:.0f}s, health={health:.2f}) "
                f"buffer: {old_buffer:.3f} → {new_buffer:.3f}"
            )

        self.current_buffer = new_buffer
        self.current_hard_floor = new_hard_floor
        self.last_adjustment_ts = now

        return {
            "hard_floor": new_hard_floor,
            "soft_ceiling": new_hard_floor + new_buffer,
            "soft_zone_size": new_buffer,
            "relaxation_level": relaxation,
        }

    def classify_score(
        self, score: float, hard_floor: float, soft_ceiling: float
    ) -> Tuple[str, float]:
        """
        Classify score and return penalty multiplier.
        
        Returns (zone: str, penalty: float)
          - "ACCEPT": score >= soft_ceiling, penalty=1.0
          - "SOFT": hard_floor <= score < soft_ceiling, penalty=0.3-0.9
          - "HARD": score < hard_floor, penalty=0.0 (reject)
        """
        if score >= soft_ceiling:
            return "ACCEPT", 1.0

        if score >= hard_floor:
            # Soft zone: graduated penalty
            soft_range = soft_ceiling - hard_floor
            progress = (score - hard_floor) / max(soft_range, 0.001)
            penalty = 0.30 + (progress * 0.60)  # 0.30 → 0.90
            return "SOFT", penalty

        return "HARD", 0.0


class ComputeCaching:
    """
    LRU caching for expensive signal calculations.
    
    Reduces redundant work in tight loop:
      - _ff_wr / _ff_ev calculations
      - Regime statistics lookups
      - Health/idle computations
    """

    def __init__(self):
        self.cache_time = {}
        self.cache_data = {}
        self.cache_ttl = 5  # seconds

    def get(self, key: str) -> Optional[Any]:
        """Retrieve cached value if not stale."""
        now = time.time()
        if key in self.cache_time:
            age = now - self.cache_time[key]
            if age < self.cache_ttl:
                return self.cache_data[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Cache a value with timestamp."""
        self.cache_time[key] = time.time()
        self.cache_data[key] = value

    def invalidate(self, key: Optional[str] = None) -> None:
        """Clear cache or single key."""
        if key:
            self.cache_time.pop(key, None)
            self.cache_data.pop(key, None)
        else:
            self.cache_time.clear()
            self.cache_data.clear()


class RelaxationStrategy:
    """
    Coordinates which blockers and thresholds relax during stall/crisis.
    
    Strategy:
      - Healthy (idle < 60s): All blockers at 100% strength
      - Moderate (idle 60-300s): Hard blockers soften 10-20%
      - Severe (idle 300-900s): Hard blockers soften 30-50%
      - Critical (idle > 900s): Hard blockers soften 50-80%
    """

    def __init__(self):
        self.last_strategy = "HEALTHY"
        self.last_applied_ts = time.time()

    def get_strategy(self, idle_seconds: float, health: float) -> str:
        """Determine relaxation strategy."""
        if idle_seconds > 900 or health < 0.10:
            return "CRITICAL"
        elif idle_seconds > 300 or health < 0.25:
            return "SEVERE"
        elif idle_seconds > 60 or health < 0.40:
            return "MODERATE"
        else:
            return "HEALTHY"

    def get_blocker_multiplier(self, blocker_name: str, strategy: str) -> float:
        """
        Compute how much to relax a specific blocker.
        
        Returns: multiplier ∈ [0.2, 1.0]
          1.0 = full strength (hard reject)
          0.5 = soft penalty (50% × original impact)
          0.2 = minimal (only if extremely toxic)
        
        Different blockers relax at different rates:
          - OFI_TOXIC_HARD: Relaxes more (already selective per V10.13h)
          - SKIP_SCORE_HARD: Relaxes less (score is critical)
          - FAST_FAIL_HARD: Relaxes moderately (regime-specific)
        """
        multipliers = {
            "HEALTHY": 1.0,
            "MODERATE": {
                "OFI_TOXIC_HARD": 0.90,
                "FAST_FAIL_HARD": 0.85,
                "SKIP_SCORE_HARD": 0.95,  # Score strictest
                "default": 0.90,
            },
            "SEVERE": {
                "OFI_TOXIC_HARD": 0.70,
                "FAST_FAIL_HARD": 0.65,
                "SKIP_SCORE_HARD": 0.80,
                "default": 0.70,
            },
            "CRITICAL": {
                "OFI_TOXIC_HARD": 0.40,
                "FAST_FAIL_HARD": 0.40,
                "SKIP_SCORE_HARD": 0.60,
                "default": 0.40,
            },
        }

        if strategy == "HEALTHY":
            return 1.0

        blockers = multipliers.get(strategy, {})
        return blockers.get(blocker_name, blockers.get("default", 1.0))

    def apply_soft_penalty(self, hard_reject: bool, strategy: str) -> bool:
        """
        Decide if hard rejection should be softened to penalty.
        
        Returns: True if should convert hard → soft penalty
        """
        if strategy == "CRITICAL":
            # Relax 70% of hard rejects in critical state
            import random
            return random.random() < 0.70
        elif strategy == "SEVERE":
            return random.random() < 0.50
        elif strategy == "MODERATE":
            return random.random() < 0.20
        return False


# Module-level instances
_zones = HardBlockZones()
_cache = ComputeCaching()
_strategy = RelaxationStrategy()


def get_zone_config(health: float, idle_seconds: float) -> Dict[str, float]:
    """Public interface: get adaptive zone configuration."""
    return _zones.adjust(health, idle_seconds)


def get_blocker_multiplier(blocker_name: str, idle_seconds: float, health: float) -> float:
    """Public interface: get relaxation multiplier for blocker."""
    strategy = _strategy.get_strategy(idle_seconds, health)
    return _strategy.get_blocker_multiplier(blocker_name, strategy)


def classify_score(score: float, health: float, idle_seconds: float) -> Tuple[str, float]:
    """Public interface: classify score with adaptive zones."""
    zones = get_zone_config(health, idle_seconds)
    return _zones.classify_score(score, zones["hard_floor"], zones["soft_ceiling"])


def cache_get(key: str) -> Optional[Any]:
    """Public interface: retrieve cached value."""
    return _cache.get(key)


def cache_set(key: str, value: Any) -> None:
    """Public interface: cache a value."""
    _cache.set(key, value)


def cache_invalidate(key: Optional[str] = None) -> None:
    """Public interface: clear cache."""
    _cache.invalidate(key)
