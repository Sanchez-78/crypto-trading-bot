"""Central strategy registry — Evidence-First Strategy Expansion v2, §16.3.

Unknown strategies must reject (§16.3). This registry is the single source
of truth the router (signal_router.py) consults; it does NOT dynamically
import arbitrary strategy names from external input (§16.3's explicit
prohibition) -- registration is a deliberate, in-process call, not a
string-driven import.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional


@dataclass(frozen=True)
class StrategyRegistration:
    strategy_id: str
    current_version: str
    enabled: bool
    evidence_only: bool
    allowed_symbols: FrozenSet[str]
    allowed_regimes: FrozenSet[str]
    allowed_sides: FrozenSet[str]
    exit_profile: str
    minimum_warmup_seconds: int
    required_feature_schema_version: str

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not self.current_version:
            raise ValueError("current_version must be non-empty")
        bad_sides = self.allowed_sides - {"BUY", "SELL", "LONG", "SHORT"}
        if bad_sides:
            raise ValueError(f"allowed_sides contains unknown values: {bad_sides}")
        if self.minimum_warmup_seconds < 0:
            raise ValueError("minimum_warmup_seconds must be non-negative")


class StrategyRegistry:
    """Thread-safe in-process registry. Not a singleton by construction --
    tests instantiate their own registry; production wiring uses one shared
    instance (get_default_registry())."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: Dict[str, StrategyRegistration] = {}

    def register(self, registration: StrategyRegistration) -> None:
        with self._lock:
            existing = self._entries.get(registration.strategy_id)
            if existing is not None and existing.current_version != registration.current_version:
                # §7.1: "Do not reuse a version identifier after modifying
                # [feature/threshold/regime/cost/exit/sizing/timing/
                # confirmation] behavior." Re-registration under a NEW
                # version is expected (upgrade); re-registration under the
                # SAME strategy_id with a DIFFERENT version silently
                # replacing history is exactly what that rule guards
                # against being done carelessly -- require the caller to be
                # explicit by unregistering first.
                raise ValueError(
                    f"strategy_id={registration.strategy_id!r} is already registered at "
                    f"version={existing.current_version!r}; re-registering at "
                    f"version={registration.current_version!r} requires an explicit "
                    f"unregister() first (cohort-version discipline, §23.7)"
                )
            self._entries[registration.strategy_id] = registration

    def unregister(self, strategy_id: str) -> None:
        with self._lock:
            self._entries.pop(strategy_id, None)

    def get(self, strategy_id: str) -> Optional[StrategyRegistration]:
        with self._lock:
            return self._entries.get(strategy_id)

    def is_registered(self, strategy_id: str) -> bool:
        with self._lock:
            return strategy_id in self._entries

    def all_strategy_ids(self) -> FrozenSet[str]:
        with self._lock:
            return frozenset(self._entries.keys())


_default_registry: Optional[StrategyRegistry] = None
_default_registry_lock = threading.Lock()


def get_default_registry() -> StrategyRegistry:
    """Process-wide registry singleton. P0.8+ strategy modules register
    themselves here at import time; the router consults this instance by
    default (a router instance may also be given an explicit registry for
    tests)."""
    global _default_registry
    with _default_registry_lock:
        if _default_registry is None:
            _default_registry = StrategyRegistry()
        return _default_registry
