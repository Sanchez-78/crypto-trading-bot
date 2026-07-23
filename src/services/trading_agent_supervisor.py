"""Bounded autonomous monitoring and PAPER-strategy supervision.

The runtime topology is intentionally deterministic:

* TradingHealthAgent reads trade and learning activity.
* MarketStateAgent reads price freshness and short-horizon market state.
* StrategyTuningAgent proposes a bounded PAPER policy.
* TradingAgentSupervisor is the only component allowed to apply a proposal.

No component edits ``.env`` or enables real orders.  The only automatic policy
controls are a PAPER entry pause and an entry-quota multiplier clamped to
``0.50..1.00``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PAPER_MODES = frozenset({"paper_live", "paper_train", "replay_train"})
MIN_QUOTA_MULTIPLIER = 0.50
MAX_QUOTA_MULTIPLIER = 1.00
MAX_QUOTA_STEP = 0.25
MAX_AUDIT_RECORDS = 50


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(value, minimum), maximum)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _utc_iso(ts: float) -> str:
    return (
        datetime.fromtimestamp(float(ts), tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _default_state_path() -> Path:
    configured = os.getenv("TRADING_AGENT_STATE_FILE", "").strip()
    if configured:
        return Path(configured)
    production = Path("/opt/cryptomaster")
    base = production if production.is_dir() else Path(".")
    return base / "server_local_backups" / "trading_agent_supervisor_state.json"


def _default_policy() -> dict:
    return {
        "revision": 0,
        "paper_entry_quota_multiplier": 1.0,
        "pause_new_entries": False,
        "reason": "baseline",
        "applied_at": 0.0,
        "applied_at_utc": None,
        "cooldown_until": 0.0,
        "evidence_lifetime_n": 0,
    }


def _validated_policy(raw: Any) -> dict:
    baseline = _default_policy()
    if not isinstance(raw, dict):
        return baseline

    multiplier = _finite(raw.get("paper_entry_quota_multiplier"), 1.0)
    baseline.update(
        {
            "revision": max(0, int(_finite(raw.get("revision"), 0))),
            "paper_entry_quota_multiplier": min(
                max(multiplier, MIN_QUOTA_MULTIPLIER),
                MAX_QUOTA_MULTIPLIER,
            ),
            "pause_new_entries": bool(raw.get("pause_new_entries", False)),
            "reason": str(raw.get("reason", "restored"))[:240],
            "applied_at": max(0.0, _finite(raw.get("applied_at"), 0.0)),
            "cooldown_until": max(
                0.0, _finite(raw.get("cooldown_until"), 0.0)
            ),
            "evidence_lifetime_n": max(
                0, int(_finite(raw.get("evidence_lifetime_n"), 0))
            ),
        }
    )
    applied_at = baseline["applied_at"]
    baseline["applied_at_utc"] = _utc_iso(applied_at) if applied_at else None
    return baseline


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


class MarketStateAgent:
    """Thread-safe, read-only price freshness and market-state analyzer."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        stale_after_s: Optional[float] = None,
        warmup_s: Optional[float] = None,
        sample_interval_s: float = 5.0,
        history_points: int = 120,
    ):
        self._clock = clock
        self._started_at = float(clock())
        self._stale_after_s = stale_after_s or _env_float(
            "TRADING_AGENT_PRICE_STALE_AFTER_S", 90.0, 15.0, 900.0
        )
        self._warmup_s = warmup_s or _env_float(
            "TRADING_AGENT_MARKET_WARMUP_S", 120.0, 15.0, 900.0
        )
        self._sample_interval_s = max(1.0, float(sample_interval_s))
        self._history_points = max(12, min(int(history_points), 720))
        self._latest: Dict[str, tuple[float, float]] = {}
        self._history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self._history_points)
        )
        self._lock = threading.RLock()

    def record_tick(
        self,
        symbol: str,
        price: float,
        ts: Optional[float] = None,
    ) -> bool:
        symbol = str(symbol or "").strip().upper()
        price = _finite(price, 0.0)
        ts = float(self._clock() if ts is None else ts)
        if (
            not symbol
            or len(symbol) > 24
            or not symbol.replace("_", "").isalnum()
            or price <= 0.0
            or not math.isfinite(ts)
        ):
            return False

        with self._lock:
            self._latest[symbol] = (price, ts)
            history = self._history[symbol]
            if not history or ts - history[-1][0] >= self._sample_interval_s:
                history.append((ts, price))
        return True

    def analyze(
        self,
        expected_symbols: Optional[Iterable[str]] = None,
        *,
        now: Optional[float] = None,
    ) -> dict:
        now = float(self._clock() if now is None else now)
        expected = {
            str(symbol).strip().upper()
            for symbol in (expected_symbols or ())
            if str(symbol).strip()
        }

        with self._lock:
            latest = dict(self._latest)
            histories = {
                symbol: list(points) for symbol, points in self._history.items()
            }

        observed = set(latest)
        tracked = expected or observed
        stale_symbols = []
        fresh_symbols = []
        ages = {}
        for symbol in sorted(tracked):
            tick = latest.get(symbol)
            age = max(0.0, now - tick[1]) if tick else None
            ages[symbol] = round(age, 3) if age is not None else None
            if age is None or age > self._stale_after_s:
                stale_symbols.append(symbol)
            else:
                fresh_symbols.append(symbol)

        coverage = len(fresh_symbols) / len(tracked) if tracked else 0.0
        uptime = max(0.0, now - self._started_at)
        if uptime < self._warmup_s and not fresh_symbols:
            status = "warming_up"
            pause_recommended = False
        elif not fresh_symbols or coverage < 0.50:
            status = "critical"
            pause_recommended = True
        elif stale_symbols:
            status = "degraded"
            pause_recommended = False
        else:
            status = "healthy"
            pause_recommended = False

        returns_bps = []
        directions = []
        for symbol in fresh_symbols:
            points = histories.get(symbol, [])
            if len(points) < 2:
                continue
            first_price = _finite(points[0][1], 0.0)
            last_price = _finite(points[-1][1], 0.0)
            if first_price <= 0.0 or last_price <= 0.0:
                continue
            move = (last_price / first_price) - 1.0
            directions.append(move)
            previous = first_price
            for _, price in points[1:]:
                price = _finite(price, 0.0)
                if price > 0.0 and previous > 0.0:
                    returns_bps.append(abs((price / previous) - 1.0) * 10_000.0)
                previous = price

        median_abs_return_bps = (
            statistics.median(returns_bps) if returns_bps else 0.0
        )
        positive_breadth = (
            sum(1 for value in directions if value > 0.0) / len(directions)
            if directions
            else 0.0
        )
        if median_abs_return_bps >= _env_float(
            "TRADING_AGENT_HIGH_VOL_BPS", 15.0, 1.0, 500.0
        ):
            market_regime = "high_volatility"
        elif directions and positive_breadth >= 0.70:
            market_regime = "broad_uptrend"
        elif directions and positive_breadth <= 0.30:
            market_regime = "broad_downtrend"
        elif directions:
            market_regime = "mixed"
        else:
            market_regime = "insufficient_history"

        newest_tick_ts = max((tick[1] for tick in latest.values()), default=0.0)
        return {
            "agent": "market_state",
            "status": status,
            "pause_recommended": pause_recommended,
            "expected_symbols": len(tracked),
            "fresh_symbols": len(fresh_symbols),
            "coverage": round(coverage, 4),
            "stale_symbols": stale_symbols[:50],
            "price_age_s": ages,
            "stale_after_s": self._stale_after_s,
            "market_regime": market_regime,
            "median_abs_return_bps": round(median_abs_return_bps, 4),
            "positive_breadth": round(positive_breadth, 4),
            "last_tick_ts": newest_tick_ts or None,
            "last_tick_utc": _utc_iso(newest_tick_ts) if newest_tick_ts else None,
            "checked_at": now,
            "checked_at_utc": _utc_iso(now),
        }


class TradingHealthAgent:
    """Analyze durable trade activity and adaptive-learning progress."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        stall_after_s: Optional[float] = None,
        learning_stall_after_s: Optional[float] = None,
    ):
        self._clock = clock
        self._stall_after_s = stall_after_s or _env_float(
            "TRADING_AGENT_TRADE_STALL_AFTER_S", 7200.0, 300.0, 86400.0
        )
        self._learning_stall_after_s = learning_stall_after_s or _env_float(
            "TRADING_AGENT_LEARNING_STALL_AFTER_S",
            7200.0,
            300.0,
            86400.0,
        )
        self._last_lifetime_n: Optional[int] = None
        self._last_learning_change_ts = float(clock())

    def restore_learning_observation(
        self,
        lifetime_n: Any,
        last_change_ts: Any,
    ) -> None:
        self._last_lifetime_n = max(0, int(_finite(lifetime_n, 0)))
        restored = _finite(last_change_ts, 0.0)
        if restored > 0.0:
            self._last_learning_change_ts = restored

    def analyze(
        self,
        *,
        closed_trades: Any,
        open_positions: Any,
        learning_snapshot: Any,
        now: Optional[float] = None,
    ) -> dict:
        now = float(self._clock() if now is None else now)
        closed = closed_trades if isinstance(closed_trades, list) else []
        positions = open_positions if isinstance(open_positions, list) else []
        learning = learning_snapshot if isinstance(learning_snapshot, dict) else {}

        exit_times = []
        for trade in closed:
            if not isinstance(trade, dict):
                continue
            exit_ts = _finite(
                trade.get("exit_ts", trade.get("exit_time")),
                0.0,
            )
            if exit_ts > 0.0:
                exit_times.append(exit_ts)

        last_close_ts = max(exit_times) if exit_times else 0.0
        last_close_age_s = (
            max(0.0, now - last_close_ts) if last_close_ts else None
        )
        if positions:
            trading_status = "active"
            trading_reason = "open_position"
        elif last_close_age_s is None:
            trading_status = "no_history"
            trading_reason = "no_closed_trade_timestamp"
        elif last_close_age_s > self._stall_after_s:
            trading_status = "stalled"
            trading_reason = "last_close_older_than_threshold"
        else:
            trading_status = "active"
            trading_reason = "recent_close"

        lifetime_n = max(
            0,
            int(
                _finite(
                    learning.get("lifetime_n", learning.get("rolling100_n")),
                    len(closed),
                )
            ),
        )
        if self._last_lifetime_n is None or lifetime_n != self._last_lifetime_n:
            self._last_lifetime_n = lifetime_n
            self._last_learning_change_ts = now
        learning_idle_s = max(0.0, now - self._last_learning_change_ts)
        if lifetime_n <= 0:
            learning_status = "no_history"
        elif learning_idle_s > self._learning_stall_after_s:
            learning_status = "stalled"
        elif learning_idle_s <= 120.0:
            learning_status = "active"
        else:
            learning_status = "observing"

        return {
            "agent": "trading_health",
            "status": (
                "degraded"
                if trading_status == "stalled" or learning_status == "stalled"
                else "healthy"
            ),
            "trading_status": trading_status,
            "trading_reason": trading_reason,
            "learning_status": learning_status,
            "open_positions": len(positions),
            "last_close_ts": last_close_ts or None,
            "last_close_utc": _utc_iso(last_close_ts) if last_close_ts else None,
            "last_close_age_s": (
                round(last_close_age_s, 3)
                if last_close_age_s is not None
                else None
            ),
            "trade_stall_after_s": self._stall_after_s,
            "learning_idle_s": round(learning_idle_s, 3),
            "learning_stall_after_s": self._learning_stall_after_s,
            "last_learning_change_ts": self._last_learning_change_ts,
            "lifetime_n": lifetime_n,
            "rolling20_n": max(
                0, int(_finite(learning.get("rolling20_n"), 0))
            ),
            "rolling20_pf": max(
                0.0, _finite(learning.get("rolling20_pf"), 1.0)
            ),
            "rolling20_expectancy": _finite(
                learning.get("rolling20_expectancy"), 0.0
            ),
            "checked_at": now,
            "checked_at_utc": _utc_iso(now),
        }


class StrategyTuningAgent:
    """Pure proposal engine; it has no write or execution capability."""

    def __init__(self, min_samples: Optional[int] = None):
        self._min_samples = min_samples or _env_int(
            "TRADING_AGENT_MIN_TUNING_SAMPLES", 20, 10, 100
        )
        self._min_lifetime_samples = _env_int(
            "TRADING_AGENT_MIN_LIFETIME_SAMPLES", 200, 50, 1000000
        )

    def propose(
        self,
        *,
        trading: dict,
        market: dict,
        current_policy: dict,
        now: float,
    ) -> dict:
        current = _validated_policy(current_policy)
        target_multiplier = current["paper_entry_quota_multiplier"]
        pause = current["pause_new_entries"]
        reason = "hold_current_policy"
        urgency = "normal"

        if market.get("pause_recommended"):
            target_multiplier = min(target_multiplier, MIN_QUOTA_MULTIPLIER)
            pause = True
            reason = "market_price_feed_critical"
            urgency = "critical"
        elif market.get("status") in {"healthy", "degraded"}:
            pause = False

            sample_n = max(0, int(_finite(trading.get("rolling20_n"), 0)))
            lifetime_n = max(0, int(_finite(trading.get("lifetime_n"), 0)))
            pf = max(0.0, _finite(trading.get("rolling20_pf"), 1.0))
            expectancy = _finite(trading.get("rolling20_expectancy"), 0.0)
            if lifetime_n < self._min_lifetime_samples:
                reason = "insufficient_lifetime_samples"
            elif sample_n < self._min_samples:
                reason = "insufficient_recent_samples"
            elif pf < 0.50 or expectancy <= -0.15:
                target_multiplier = 0.50
                reason = "critical_negative_recent_edge"
                urgency = "high"
            elif pf < 0.80 or expectancy < 0.0:
                target_multiplier = 0.75
                reason = "weak_recent_edge"
            elif pf >= 1.05 and expectancy > 0.0:
                target_multiplier = 1.00
                reason = "recent_edge_recovered"
            else:
                reason = "recent_edge_neutral"
        else:
            reason = "market_agent_warming_up"

        target_multiplier = min(
            max(_finite(target_multiplier, 1.0), MIN_QUOTA_MULTIPLIER),
            MAX_QUOTA_MULTIPLIER,
        )
        return {
            "agent": "strategy_tuner",
            "target_entry_quota_multiplier": target_multiplier,
            "pause_new_entries": bool(pause),
            "reason": reason,
            "urgency": urgency,
            "evidence": {
                "lifetime_n": max(
                    0, int(_finite(trading.get("lifetime_n"), 0))
                ),
                "rolling20_n": max(
                    0, int(_finite(trading.get("rolling20_n"), 0))
                ),
                "rolling20_pf": max(
                    0.0, _finite(trading.get("rolling20_pf"), 1.0)
                ),
                "rolling20_expectancy": _finite(
                    trading.get("rolling20_expectancy"), 0.0
                ),
                "market_status": str(market.get("status", "unknown")),
                "market_regime": str(
                    market.get("market_regime", "unknown")
                ),
            },
            "proposed_at": float(now),
            "proposed_at_utc": _utc_iso(now),
        }


class TradingAgentSupervisor:
    """Supervisor, policy gate, persistence layer and circuit breaker."""

    def __init__(
        self,
        *,
        state_file: Optional[Path] = None,
        clock: Callable[[], float] = time.time,
        mode_provider: Optional[Callable[[], str]] = None,
        expected_symbols_provider: Optional[Callable[[], Iterable[str]]] = None,
        trading_source: Optional[Callable[[], dict]] = None,
        enabled: Optional[bool] = None,
        auto_apply: Optional[bool] = None,
        cycle_interval_s: Optional[float] = None,
        market_agent: Optional[MarketStateAgent] = None,
        trading_agent: Optional[TradingHealthAgent] = None,
        tuning_agent: Optional[StrategyTuningAgent] = None,
    ):
        self._clock = clock
        self._state_file = Path(state_file or _default_state_path())
        self._mode_provider = mode_provider or self._runtime_mode
        self._expected_symbols_provider = (
            expected_symbols_provider or self._active_symbols
        )
        self._trading_source = trading_source or self._default_trading_source
        self.enabled = (
            _env_bool("TRADING_AGENT_SUPERVISOR_ENABLED", False)
            if enabled is None
            else bool(enabled)
        )
        self.auto_apply = (
            _env_bool("TRADING_AGENT_AUTO_APPLY", False)
            if auto_apply is None
            else bool(auto_apply)
        )
        self.cycle_interval_s = cycle_interval_s or _env_float(
            "TRADING_AGENT_INTERVAL_S", 60.0, 30.0, 3600.0
        )
        self._policy_cooldown_s = _env_float(
            "TRADING_AGENT_POLICY_COOLDOWN_S", 3600.0, 300.0, 86400.0
        )
        self._min_new_trades = _env_int(
            "TRADING_AGENT_MIN_NEW_TRADES", 20, 5, 100
        )
        self._circuit_failures = _env_int(
            "TRADING_AGENT_CIRCUIT_FAILURES", 3, 2, 10
        )
        self._circuit_cooldown_s = _env_float(
            "TRADING_AGENT_CIRCUIT_COOLDOWN_S", 600.0, 60.0, 3600.0
        )
        self.market_agent = market_agent or MarketStateAgent(clock=clock)
        self.trading_agent = trading_agent or TradingHealthAgent(clock=clock)
        self.tuning_agent = tuning_agent or StrategyTuningAgent()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = self._load_state()

        previous_trading = self._state.get("agents", {}).get(
            "trading_health", {}
        )
        self.trading_agent.restore_learning_observation(
            previous_trading.get("lifetime_n"),
            previous_trading.get("last_learning_change_ts"),
        )

    @staticmethod
    def _runtime_mode() -> str:
        try:
            from src.core.runtime_mode import get_trading_mode

            return get_trading_mode().value
        except Exception:
            return str(os.getenv("TRADING_MODE", "paper_live")).strip().lower()

    @staticmethod
    def _active_symbols() -> Iterable[str]:
        try:
            from src.services.portfolio_discovery import get_active_symbols

            return get_active_symbols()
        except Exception:
            return ()

    @staticmethod
    def _default_trading_source() -> dict:
        from src.services.local_persistent_cache import get_closed_trades
        from src.services.paper_adaptive_learning import get_learner
        from src.services.paper_trade_executor import get_paper_open_positions

        learner = get_learner()
        return {
            "closed_trades": get_closed_trades(limit=100),
            "open_positions": get_paper_open_positions(),
            "learning_snapshot": learner.get_paper_policy_snapshot(),
        }

    def _blank_state(self) -> dict:
        now = float(self._clock())
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now,
            "updated_at_utc": _utc_iso(now),
            "supervisor": {
                "status": "disabled" if not self.enabled else "starting",
                "enabled": self.enabled,
                "auto_apply": self.auto_apply,
                "mode": "unknown",
                "cycles": 0,
                "consecutive_failures": 0,
                "circuit_open_until": 0.0,
                "last_error": None,
            },
            "agents": {},
            "proposal": {},
            "pending": {"key": "", "streak": 0},
            "policy": _default_policy(),
            "audit": [],
        }

    def _load_state(self) -> dict:
        state = self._blank_state()
        loaded = _read_json(self._state_file)
        if not loaded or loaded.get("schema_version") != SCHEMA_VERSION:
            return state

        state["policy"] = _validated_policy(loaded.get("policy"))
        state["audit"] = (
            loaded.get("audit", [])[-MAX_AUDIT_RECORDS:]
            if isinstance(loaded.get("audit"), list)
            else []
        )
        if isinstance(loaded.get("agents"), dict):
            state["agents"] = loaded["agents"]
        if isinstance(loaded.get("pending"), dict):
            state["pending"] = {
                "key": str(loaded["pending"].get("key", ""))[:300],
                "streak": max(
                    0, int(_finite(loaded["pending"].get("streak"), 0))
                ),
            }
        previous_supervisor = loaded.get("supervisor", {})
        if isinstance(previous_supervisor, dict):
            state["supervisor"]["cycles"] = max(
                0, int(_finite(previous_supervisor.get("cycles"), 0))
            )
        return state

    def record_market_tick(
        self,
        symbol: str,
        price: float,
        ts: Optional[float] = None,
    ) -> bool:
        return self.market_agent.record_tick(symbol, price, ts)

    def _proposal_key(self, proposal: dict) -> str:
        return json.dumps(
            {
                "target": proposal.get("target_entry_quota_multiplier"),
                "pause": proposal.get("pause_new_entries"),
                "reason": proposal.get("reason"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def _append_audit(self, record: dict) -> None:
        audit = self._state.setdefault("audit", [])
        audit.append(record)
        del audit[:-MAX_AUDIT_RECORDS]

    def _consider_proposal(
        self,
        *,
        proposal: dict,
        mode: str,
        now: float,
    ) -> str:
        policy = _validated_policy(self._state.get("policy"))
        self._state["policy"] = policy

        key = self._proposal_key(proposal)
        pending = self._state.setdefault("pending", {"key": "", "streak": 0})
        if pending.get("key") == key:
            pending["streak"] = max(0, int(pending.get("streak", 0))) + 1
        else:
            pending["key"] = key
            pending["streak"] = 1

        if mode not in PAPER_MODES:
            return "blocked_non_paper_mode"
        if not self._paper_safety_invariants(mode):
            return "blocked_real_order_flags"
        if not self.enabled:
            return "blocked_supervisor_disabled"
        if not self.auto_apply:
            return "proposal_only"

        supervisor_state = self._state["supervisor"]
        if now < _finite(supervisor_state.get("circuit_open_until"), 0.0):
            return "blocked_circuit_open"

        target = min(
            max(
                _finite(
                    proposal.get("target_entry_quota_multiplier"),
                    policy["paper_entry_quota_multiplier"],
                ),
                MIN_QUOTA_MULTIPLIER,
            ),
            MAX_QUOTA_MULTIPLIER,
        )
        pause = bool(proposal.get("pause_new_entries", False))
        current_pause = bool(policy["pause_new_entries"])
        critical_pause = (
            pause
            and proposal.get("urgency") == "critical"
            and not current_pause
        )

        required_streak = 1 if critical_pause else (3 if current_pause and not pause else 2)
        if pending["streak"] < required_streak:
            return "awaiting_confirmation"

        size_changed = not math.isclose(
            target,
            policy["paper_entry_quota_multiplier"],
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        pause_changed = pause != current_pause
        if not size_changed and not pause_changed:
            return "no_change"

        if not critical_pause and now < policy["cooldown_until"]:
            return "blocked_policy_cooldown"

        evidence = proposal.get("evidence", {})
        lifetime_n = max(0, int(_finite(evidence.get("lifetime_n"), 0)))
        new_trades = lifetime_n - int(policy["evidence_lifetime_n"])
        if (
            size_changed
            and policy["revision"] > 0
            and target != MIN_QUOTA_MULTIPLIER
            and new_trades < self._min_new_trades
        ):
            return "awaiting_new_trade_evidence"

        current = policy["paper_entry_quota_multiplier"]
        bounded_target = min(
            max(target, current - MAX_QUOTA_STEP),
            current + MAX_QUOTA_STEP,
        )
        bounded_target = min(
            max(bounded_target, MIN_QUOTA_MULTIPLIER),
            MAX_QUOTA_MULTIPLIER,
        )

        previous = deepcopy(policy)
        applied = {
            "revision": policy["revision"] + 1,
            "paper_entry_quota_multiplier": bounded_target,
            "pause_new_entries": pause,
            "reason": str(proposal.get("reason", "bounded_adjustment"))[:240],
            "applied_at": now,
            "applied_at_utc": _utc_iso(now),
            "cooldown_until": now + self._policy_cooldown_s,
            "evidence_lifetime_n": lifetime_n,
        }
        self._state["policy"] = applied
        self._append_audit(
            {
                "event": "policy_applied",
                "at": now,
                "at_utc": _utc_iso(now),
                "mode": mode,
                "previous": previous,
                "applied": deepcopy(applied),
                "proposal_evidence": deepcopy(evidence),
            }
        )
        pending["streak"] = 0
        log.warning(
            "[TRADING_AGENT_POLICY_APPLIED] revision=%d mode=%s "
            "entry_quota_multiplier=%.2f pause_new_entries=%s reason=%s",
            applied["revision"],
            mode,
            applied["paper_entry_quota_multiplier"],
            applied["pause_new_entries"],
            applied["reason"],
        )
        return "applied"

    def _run_cycle(self, now: float) -> dict:
        mode = str(self._mode_provider()).strip().lower()
        paper_safe = self._paper_safety_invariants(mode)
        expected_symbols = list(self._expected_symbols_provider() or ())
        market = self.market_agent.analyze(expected_symbols, now=now)
        inputs = self._trading_source()
        if not isinstance(inputs, dict):
            raise TypeError("trading_source must return a dict")
        trading = self.trading_agent.analyze(
            closed_trades=inputs.get("closed_trades"),
            open_positions=inputs.get("open_positions"),
            learning_snapshot=inputs.get("learning_snapshot"),
            now=now,
        )
        proposal = self.tuning_agent.propose(
            trading=trading,
            market=market,
            current_policy=self._state.get("policy", {}),
            now=now,
        )

        supervisor_state = self._state["supervisor"]
        supervisor_state.update(
            {
                "status": (
                    "monitoring"
                    if paper_safe
                    else (
                        "safety_blocked"
                        if mode in PAPER_MODES
                        else "read_only_non_paper"
                    )
                ),
                "enabled": self.enabled,
                "auto_apply": self.auto_apply and paper_safe,
                "mode": mode,
                "cycles": int(supervisor_state.get("cycles", 0)) + 1,
                "consecutive_failures": 0,
                "last_error": None,
                "last_cycle_at": now,
                "last_cycle_at_utc": _utc_iso(now),
            }
        )
        self._state["agents"] = {
            "trading_health": trading,
            "market_state": market,
            "strategy_tuner": {
                "agent": "strategy_tuner",
                "status": "proposal_ready",
                "last_reason": proposal["reason"],
                "last_target_entry_quota_multiplier": proposal[
                    "target_entry_quota_multiplier"
                ],
                "last_pause_new_entries": proposal["pause_new_entries"],
                "checked_at": now,
                "checked_at_utc": _utc_iso(now),
            },
        }
        self._state["proposal"] = proposal
        self._state["proposal"]["decision"] = self._consider_proposal(
            proposal=proposal,
            mode=mode,
            now=now,
        )
        self._state["updated_at"] = now
        self._state["updated_at_utc"] = _utc_iso(now)
        return deepcopy(self._state)

    def run_cycle(self) -> dict:
        """Run one supervised cycle; failures degrade and open a circuit safely."""
        with self._lock:
            now = float(self._clock())
            supervisor_state = self._state["supervisor"]
            circuit_until = _finite(
                supervisor_state.get("circuit_open_until"), 0.0
            )
            if circuit_until and now >= circuit_until:
                supervisor_state["circuit_open_until"] = 0.0
                supervisor_state["consecutive_failures"] = 0

            try:
                result = self._run_cycle(now)
            except Exception as exc:
                failures = int(
                    supervisor_state.get("consecutive_failures", 0)
                ) + 1
                supervisor_state.update(
                    {
                        "status": "degraded",
                        "enabled": self.enabled,
                        "auto_apply": False,
                        "consecutive_failures": failures,
                        "last_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                        "last_cycle_at": now,
                        "last_cycle_at_utc": _utc_iso(now),
                    }
                )
                if failures >= self._circuit_failures:
                    supervisor_state["status"] = "circuit_open"
                    supervisor_state["circuit_open_until"] = (
                        now + self._circuit_cooldown_s
                    )
                self._state["updated_at"] = now
                self._state["updated_at_utc"] = _utc_iso(now)
                result = deepcopy(self._state)
                log.error(
                    "[TRADING_AGENT_CYCLE_ERROR] failures=%d circuit_open=%s error=%s",
                    failures,
                    supervisor_state["status"] == "circuit_open",
                    supervisor_state["last_error"],
                )

            try:
                _atomic_write_json(self._state_file, self._state)
            except OSError as exc:
                log.error(
                    "[TRADING_AGENT_STATE_WRITE_ERROR] path=%s error=%s",
                    self._state_file,
                    exc,
                )
            return result

    def get_effective_policy(self) -> dict:
        with self._lock:
            mode = str(self._mode_provider()).strip().lower()
            if not self.enabled or not self._paper_safety_invariants(mode):
                return _default_policy()
            return deepcopy(_validated_policy(self._state.get("policy")))

    @staticmethod
    def _paper_safety_invariants(mode: str) -> bool:
        """Real-order flags are forbidden even while the selected mode is PAPER."""
        if mode not in PAPER_MODES:
            return False
        for flag in (
            "ENABLE_REAL_ORDERS",
            "LIVE_TRADING_CONFIRMED",
            "REAL_TRADING_ENABLED",
        ):
            if _env_bool(flag, False):
                return False
        try:
            from src.core.runtime_mode import live_trading_allowed

            if live_trading_allowed():
                return False
        except Exception:
            # Direct flags above remain the local fail-safe if the runtime
            # module is unavailable.
            pass
        return True

    def get_status(self) -> dict:
        with self._lock:
            return deepcopy(self._state)

    def start(self) -> Optional[threading.Thread]:
        if not self.enabled:
            log.info("[TRADING_AGENT_SUPERVISOR] disabled by configuration")
            return None
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self._thread
            self._stop_event.clear()

            def loop() -> None:
                while not self._stop_event.is_set():
                    self.run_cycle()
                    self._stop_event.wait(self.cycle_interval_s)

            self._thread = threading.Thread(
                target=loop,
                name="trading-agent-supervisor",
                daemon=True,
            )
            self._thread.start()
            log.info(
                "[TRADING_AGENT_SUPERVISOR] started interval_s=%.1f auto_apply=%s",
                self.cycle_interval_s,
                self.auto_apply,
            )
            return self._thread

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout_s))


_supervisor: Optional[TradingAgentSupervisor] = None
_supervisor_lock = threading.Lock()
_candidate_sequence = 0
_candidate_sequence_lock = threading.Lock()


def get_supervisor() -> TradingAgentSupervisor:
    global _supervisor
    if _supervisor is None:
        with _supervisor_lock:
            if _supervisor is None:
                _supervisor = TradingAgentSupervisor()
    return _supervisor


def start_supervisor() -> Optional[threading.Thread]:
    return get_supervisor().start()


def stop_supervisor(timeout_s: float = 5.0) -> None:
    get_supervisor().stop(timeout_s)


def record_market_tick(
    symbol: str,
    price: float,
    ts: Optional[float] = None,
) -> bool:
    """Cheap tick hook; never performs analysis or disk I/O."""
    return get_supervisor().record_market_tick(symbol, price, ts)


def get_supervisor_status() -> dict:
    return get_supervisor().get_status()


def apply_policy_to_training_candidate(
    *,
    symbol: str,
    bucket: str,
    size_mult: float,
) -> dict:
    """Apply the current bounded policy to one PAPER training candidate."""
    global _candidate_sequence
    original_size = max(0.0, _finite(size_mult, 0.0))
    policy = get_supervisor().get_effective_policy()
    if policy["pause_new_entries"]:
        return {
            "allowed": False,
            "reason": f"agent_supervisor_pause:{policy['reason']}",
            "size_mult": 0.0,
            "policy_revision": policy["revision"],
            "symbol": str(symbol),
            "bucket": str(bucket),
        }

    quota_multiplier = min(
        max(
            _finite(policy["paper_entry_quota_multiplier"], 1.0),
            MIN_QUOTA_MULTIPLIER,
        ),
        MAX_QUOTA_MULTIPLIER,
    )
    if quota_multiplier < 1.0:
        with _candidate_sequence_lock:
            _candidate_sequence += 1
            sequence = _candidate_sequence
        fingerprint = hashlib.sha256(
            f"{policy['revision']}|{sequence}|{symbol}|{bucket}".encode("utf-8")
        ).digest()
        sample = int.from_bytes(fingerprint[:8], "big") / float(2**64)
        if sample >= quota_multiplier:
            return {
                "allowed": False,
                "reason": f"agent_supervisor_quota:{policy['reason']}",
                "size_mult": 0.0,
                "policy_revision": policy["revision"],
                "entry_quota_multiplier": quota_multiplier,
                "symbol": str(symbol),
                "bucket": str(bucket),
            }

    return {
        "allowed": True,
        "reason": f"agent_supervisor_policy:{policy['reason']}",
        "size_mult": original_size,
        "policy_revision": policy["revision"],
        "entry_quota_multiplier": quota_multiplier,
        "symbol": str(symbol),
        "bucket": str(bucket),
    }
