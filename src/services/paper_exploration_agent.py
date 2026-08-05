"""Bounded PAPER-only control sampler used during verified signal droughts."""

from __future__ import annotations

import math
import logging
import os
import time
from collections import Counter, deque
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


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


def _finite_metric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


class PaperExplorationAgent:
    """Chooses and opens a tiny diagnostic control trade, never a live order."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        opener: Optional[Callable[..., dict]] = None,
        enabled: Optional[bool] = None,
        drought_after_s: Optional[float] = None,
        cooldown_s: Optional[float] = None,
        max_entries_per_hour: Optional[int] = None,
    ):
        self._clock = clock
        self._opener = opener
        self.enabled = (
            _env_bool("TRADING_AGENT_EXPLORATION_ENABLED", False)
            if enabled is None
            else bool(enabled)
        )
        self._drought_after_s = drought_after_s or _env_float(
            "TRADING_AGENT_EXPLORATION_DROUGHT_S",
            1800.0,
            120.0,
            21600.0,
        )
        self._cooldown_s = cooldown_s or _env_float(
            "TRADING_AGENT_EXPLORATION_COOLDOWN_S",
            900.0,
            60.0,
            21600.0,
        )
        configured_cap = (
            int(os.getenv("TRADING_AGENT_EXPLORATION_MAX_PER_HOUR", "2"))
            if max_entries_per_hour is None
            else int(max_entries_per_hour)
        )
        # Paper-only learning can sample frequently; keep a finite hourly cap
        # so a bad market feed cannot create an unbounded position stream.
        # Paper-only exploration may run at a higher cadence to build a useful
        # learning sample. Keep a finite hard ceiling so a bad feed cannot
        # create an unbounded position stream or exhaust local resources.
        self._max_entries_per_hour = min(max(configured_cap, 1), 240)
        self._started_at = float(clock())
        self._entry_times: deque[float] = deque(maxlen=24)
        self._last_attempt_at = 0.0
        self._last_open_at = 0.0
        self._last_trade_id: Optional[str] = None
        self._last_reason = "not_evaluated"

    def restore(self, state: Any) -> None:
        if not isinstance(state, dict):
            return
        now = float(self._clock())
        for value in state.get("entry_times", []):
            try:
                ts = float(value)
            except (TypeError, ValueError):
                continue
            if now - ts <= 3600:
                self._entry_times.append(ts)
        self._last_attempt_at = float(state.get("last_attempt_at") or 0.0)
        self._last_open_at = float(state.get("last_open_at") or 0.0)
        self._last_trade_id = state.get("last_trade_id")
        self._last_reason = str(state.get("last_reason") or "restored")

    def _snapshot(self, *, status: str, now: float, **extra: Any) -> dict:
        self._prune(now)
        return {
            "agent": "paper_exploration",
            "status": status,
            "enabled": self.enabled,
            "bucket": "D_NEG_EV_CONTROL",
            "drought_after_s": self._drought_after_s,
            "cooldown_s": self._cooldown_s,
            "max_entries_per_hour": self._max_entries_per_hour,
            "entries_last_hour": len(self._entry_times),
            "entry_times": list(self._entry_times),
            "last_attempt_at": self._last_attempt_at or None,
            "last_open_at": self._last_open_at or None,
            "last_trade_id": self._last_trade_id,
            "last_reason": self._last_reason,
            "checked_at": now,
            **extra,
        }

    def _prune(self, now: float) -> None:
        while self._entry_times and now - self._entry_times[0] > 3600:
            self._entry_times.popleft()

    @staticmethod
    def _blocked_symbols() -> set[str]:
        values = []
        for name in ("PAPER_DISABLED_SYMBOLS", "PAPER_SYMBOL_BLACKLIST"):
            values.extend(os.getenv(name, "").split(","))
        return {value.strip().upper() for value in values if value.strip()}

    @staticmethod
    def _pick_candidate(
        candidates: list[dict],
        review: dict,
        market_regime: str = "UNKNOWN",
    ) -> tuple[Optional[dict], str]:
        coverage = (
            review.get("metrics", {})
            .get("exploration", {})
            .get("coverage", {})
        )
        coverage = coverage if isinstance(coverage, dict) else {}
        segments = (
            review.get("metrics", {})
            .get("exploration", {})
            .get("segments", {})
        )
        segments = segments if isinstance(segments, dict) else {}
        minimum_segment_n = int(
            _env_float(
                "TRADING_AGENT_POSITIVE_SEGMENT_MIN_N",
                20.0,
                20.0,
                200.0,
            )
        )
        minimum_segment_pf = _env_float(
            "TRADING_AGENT_POSITIVE_SEGMENT_MIN_PF", 1.25, 1.05, 5.0
        )
        regime_norm = str(market_regime or "UNKNOWN").strip().upper()
        side_counts = Counter()
        for key, value in coverage.items():
            side = str(key).rsplit(":", 1)[-1].upper()
            side_counts[side] += int(value or 0)

        ranked = []
        for candidate_index, candidate in enumerate(candidates):
            symbol = str(candidate.get("symbol") or "").upper()
            price = candidate.get("price")
            move_bps = float(candidate.get("move_bps") or 0.0)
            if not symbol or not isinstance(price, (int, float)) or price <= 0:
                continue
            if abs(move_bps) >= 1.0:
                side = "SELL" if move_bps > 0 else "BUY"
            else:
                side = "BUY" if side_counts["BUY"] <= side_counts["SELL"] else "SELL"
            count = int(coverage.get(f"{symbol}:{side}", 0) or 0)
            segment_key = f"{symbol}:{regime_norm}:{side}"
            segment = segments.get(segment_key, {})
            segment = segment if isinstance(segment, dict) else {}
            segment_n = int(_finite_metric(segment.get("n"), 0.0))
            segment_pf = _finite_metric(segment.get("profit_factor"), 0.0)
            segment_expectancy = _finite_metric(
                segment.get("expectancy_pct_points"), 0.0
            )
            recent = segment.get("recent5", {})
            recent = recent if isinstance(recent, dict) else {}
            recent_n = int(_finite_metric(recent.get("n"), 0.0))
            recent_expectancy = _finite_metric(
                recent.get("expectancy_pct_points"), 0.0
            )
            positive_segment = (
                segment_n >= minimum_segment_n
                and segment_pf >= minimum_segment_pf
                and segment_expectancy > 0.0
                and recent_n >= 5
                and recent_expectancy > 0.0
            )
            ranked.append(
                (
                    0 if positive_segment else 1,
                    -segment_pf if positive_segment else 0.0,
                    count,
                    -abs(move_bps),
                    symbol,
                    candidate_index,
                    side,
                    candidate,
                    segment_key,
                )
            )
        if not ranked:
            return None, "no_valid_control_candidate"
        priority, _, _, _, _, _, side, selected, segment_key = min(ranked)
        selected = dict(selected)
        selected["side"] = side
        selected["segment_key"] = segment_key
        return selected, (
            "positive_segment_retest"
            if priority == 0
            else "least_sampled_symbol_side"
        )

    def consider(
        self,
        *,
        market: dict,
        trading: dict,
        review: dict,
        open_positions: Any,
        policy: dict,
        paper_safe: bool,
        now: Optional[float] = None,
    ) -> dict:
        now = float(self._clock() if now is None else now)
        self._prune(now)
        if not self.enabled:
            return self._snapshot(status="disabled", now=now)
        if not paper_safe:
            self._last_reason = "paper_safety_invariant_failed"
            return self._snapshot(status="blocked", now=now)
        if policy.get("pause_new_entries"):
            self._last_reason = "supervisor_paused_entries"
            return self._snapshot(status="blocked", now=now)
        if market.get("status") != "healthy":
            self._last_reason = "market_not_healthy"
            return self._snapshot(status="observing", now=now)

        positions = [
            position
            for position in (open_positions or [])
            if isinstance(position, dict)
        ]
        # This is a verified entry drought only when no position of any cohort
        # is currently active.  Normal strategy entries always take priority.
        if positions:
            self._last_reason = "open_position_already_active"
            return self._snapshot(status="observing", now=now)

        last_close_age = trading.get("last_close_age_s")
        if last_close_age is None:
            drought_age = max(0.0, now - self._started_at)
        else:
            drought_age = max(0.0, float(last_close_age))
        if drought_age < self._drought_after_s:
            self._last_reason = "waiting_for_verified_drought"
            return self._snapshot(
                status="observing",
                now=now,
                drought_age_s=round(drought_age, 3),
            )
        if self._last_open_at and now - self._last_open_at < self._cooldown_s:
            self._last_reason = "control_cooldown"
            return self._snapshot(status="cooldown", now=now)
        if len(self._entry_times) >= self._max_entries_per_hour:
            self._last_reason = "hourly_control_cap"
            return self._snapshot(status="capped", now=now)

        blocked = self._blocked_symbols()
        candidates = [
            candidate
            for candidate in market.get("control_candidates", [])
            if str(candidate.get("symbol") or "").upper() not in blocked
            and not any(
                str(position.get("symbol") or "").upper()
                == str(candidate.get("symbol") or "").upper()
                for position in positions
            )
        ]
        candidate, selection_reason = self._pick_candidate(
            candidates,
            review,
            str(market.get("market_regime") or "UNKNOWN"),
        )
        if not candidate:
            self._last_reason = selection_reason
            return self._snapshot(status="observing", now=now)

        symbol = str(candidate["symbol"]).upper()
        side = candidate["side"]
        price = float(candidate["price"])
        open_now = float(self._clock())
        try:
            price_ts = float(candidate.get("price_ts"))
        except (TypeError, ValueError):
            self._last_reason = "candidate_missing_price_timestamp"
            return self._snapshot(status="observing", now=open_now)
        max_price_age_s = float(market.get("stale_after_s") or 90.0)
        price_age_s = open_now - price_ts
        if (
            price_age_s < -5.0
            or price_age_s > max_price_age_s
        ):
            self._last_reason = "candidate_price_stale_at_open"
            return self._snapshot(
                status="observing",
                now=open_now,
                price_age_s=round(price_age_s, 3),
            )
        self._last_attempt_at = open_now
        signal = {
            "symbol": symbol,
            "action": side,
            "price": price,
            "timestamp": open_now,
            "price_ts": price_ts,
            "ev": -0.001,
            "score": 0.0,
            "p": 0.5,
            "coherence": 0.0,
            "auditor_factor": 0.0,
            "regime": str(market.get("market_regime") or "UNKNOWN").upper(),
            "strict_ev": False,
            "readiness_eligible": False,
            "real_readiness_eligible": False,
            "paper_learning_only": True,
            "learning_shadow_only": True,
            "learning_source": "paper_exploration_control",
            "features": {
                "control_move_bps": candidate.get("move_bps", 0.0),
                "control_selection": selection_reason,
                "control_segment_key": candidate.get("segment_key"),
            },
        }
        extra = {
            "paper_source": "agent_exploration",
            "training_bucket": "D_NEG_EV_CONTROL",
            "explore_bucket": "D_NEG_EV_CONTROL",
            "original_decision": "AGENT_SIGNAL_DROUGHT",
            "reject_reason": "CONTROL_COVERAGE_SAMPLE",
            "size_mult": 0.02,
            "final_size_usd": _env_float(
                "TRADING_AGENT_EXPLORATION_SIZE_USD",
                0.50,
                0.10,
                100.00,
            ),
            "max_hold_s": 300,
            "side_inferred": True,
            "side_inference_reason": selection_reason,
            "source_price_ts": price_ts,
            "source_price_age_s": round(price_age_s, 3),
            "tags": [
                "agent_exploration",
                "control",
                "shadow_only",
                selection_reason,
            ],
        }
        try:
            if self._opener is None:
                from src.services.paper_trade_executor import open_paper_position

                opener = open_paper_position
            else:
                opener = self._opener
            result = opener(
                signal=signal,
                price=price,
                ts=open_now,
                reason="AGENT_EXPLORATION_CONTROL",
                extra=extra,
            )
        except Exception as exc:
            self._last_reason = f"open_error:{type(exc).__name__}"
            log.exception(
                "[PAPER_EXPLORATION_OPEN_ERROR] symbol=%s side=%s error=%s",
                symbol,
                side,
                exc,
            )
            return self._snapshot(status="degraded", now=now)

        if result.get("status") != "opened":
            self._last_reason = str(result.get("reason") or "open_blocked")
            return self._snapshot(
                status="blocked",
                now=now,
                candidate={"symbol": symbol, "side": side},
            )

        self._last_open_at = open_now
        self._last_trade_id = str(result.get("trade_id") or "")
        self._last_reason = selection_reason
        self._entry_times.append(open_now)
        try:
            from src.services.learning_archive import archive_learning_event

            archive_learning_event(
                "paper_exploration_opened",
                {
                    "trade_id": self._last_trade_id,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": price,
                    "bucket": "D_NEG_EV_CONTROL",
                    "readiness_eligible": False,
                    "selection_reason": selection_reason,
                    "segment_key": candidate.get("segment_key"),
                },
                event_id=f"paper_exploration_opened:{self._last_trade_id}",
                created_at=open_now,
            )
        except Exception:
            pass
        return self._snapshot(
            status="opened",
            now=open_now,
            candidate={"symbol": symbol, "side": side, "price": price},
        )
