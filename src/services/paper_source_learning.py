"""Opt-in adaptation of PAPER evidence admissions from canonical closed trades.

This policy filters otherwise admissible candidates. It never supplies a side,
changes sizing/exits, grants strict EV, or calls an executor. A small control
cohort and periodic probes keep collecting outcomes when estimated returns are
negative. Improvement is an experiment, not a promised property of this rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Mapping, Sequence

from src.services.paper_learning_budget import SOURCES as PROBE_SOURCES

VERSION = "paper_source_learning_v1"
TAG_PREFIX = VERSION + ":"
NEURAL_VERSION = "paper_source_learning_stonkfly_v1"
NEURAL_TAG_PREFIX = NEURAL_VERSION + ":"
MAX_TAG_BYTES = 4096
FLAG = "PAPER_ADAPTIVE_EXPLORATION_ENABLED"
CLOSED_BAR_FLAG = "PAPER_COMPLETED_CANDLE_LEARNING_ENABLED"
CLOSED_BAR_VERSION = "closed_bar_v2"
PROBE_FLAG = "PAPER_COST_EXPLORATION_ENABLED"
PROBE_VERSION = "paper_probe_v2"
MAX_PROBE_COST_BPS = 20.0
MIN_PROBE_NET_BPS = -15.0
TRUTHY = frozenset({"1", "true", "yes", "on"})
SOURCES = frozenset({"sideways_mean_reversion_v1", "volatility_breakout_v1", "trend_cost_aware_v1",
                     "sideways_mean_reversion_closed_v2", "volatility_breakout_closed_v2",
                     "trend_cost_aware_closed_v2"}) | PROBE_SOURCES
WARMUP_CLOSES = 5
HALF_LIFE_CLOSES = 16
CONTROL_FRACTION = 0.2
MIN_ADMISSION_PROBABILITY = 0.1
MAX_ADMISSION_PROBABILITY = 0.9
RETURN_SCALE_BPS = 10.0
PROBE_INTERVAL_MS = 4 * 60 * 60 * 1000
MAX_HISTORY = 500


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _finite(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("invalid_paper_learning_number")
    return float(value)


def enabled(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return values.get(FLAG, "false").strip().lower() in TRUTHY


def completed_candles_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return values.get(CLOSED_BAR_FLAG, "false").strip().lower() in TRUTHY


def cost_exploration_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return values.get(PROBE_FLAG, "false").strip().lower() in TRUTHY


def candidate_version() -> str:
    return PROBE_VERSION if cost_exploration_enabled() else CLOSED_BAR_VERSION


def probe_signal_valid(signal) -> bool:
    if not cost_exploration_enabled():
        return False
    validate_config()
    return (signal.learning_source in PROBE_SOURCES
            and signal.learning_source == f"{signal.strategy_id}_paper_probe_v2"
            and signal.strategy_version == PROBE_VERSION
            and signal.evidence_only is True and signal.shadow_only is False)


def control_fraction(env: Mapping[str, str] | None = None) -> float:
    """Operator override PAPER_LEARNING_CONTROL_FRACTION in [0, 1]; invalid fails closed.

    1.0 admits every candidate unfiltered (estimate still logged) so offline replay
    can evaluate any learner on selection-free data.
    """
    values = os.environ if env is None else env
    raw = values.get("PAPER_LEARNING_CONTROL_FRACTION", "").strip()
    if not raw:
        return CONTROL_FRACTION
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("invalid_paper_learning_control_fraction") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("invalid_paper_learning_control_fraction")
    return value


def min_probe_net_bps(env: Mapping[str, str] | None = None) -> float:
    """Operator override PAPER_PROBE_MIN_NET_BPS in [-100, 0]; invalid fails closed."""
    values = os.environ if env is None else env
    raw = values.get("PAPER_PROBE_MIN_NET_BPS", "").strip()
    if not raw:
        return MIN_PROBE_NET_BPS
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("invalid_paper_probe_min_net") from exc
    if not math.isfinite(value) or not -100.0 <= value <= 0.0:
        raise ValueError("invalid_paper_probe_min_net")
    return value


def probe_cost_allowed(signal, edge) -> bool:
    """Admit a measured cost debit for research; never mislabel it as alpha."""
    return (probe_signal_valid(signal)
            and 0 < edge.gross_expected_move_bps
            and edge.all_in_cost_bps <= MAX_PROBE_COST_BPS
            and edge.net_expected_edge_bps >= min_probe_net_bps())


def validate_config(env: Mapping[str, str] | None = None) -> None:
    """An explicit training policy replaces the permanent evidence-stop policy."""
    values = os.environ if env is None else env
    if cost_exploration_enabled(values) and (
            not completed_candles_enabled(values)
            or any(values.get(key, "false").strip().lower() not in TRUTHY for key in
                   ("PAPER_UNIFIED_ENGINE_ENABLED", "PAPER_P0_8_PLUS_LIVE_ENABLED"))):
        raise ValueError("paper_cost_exploration_requires_completed_candles_and_single_pipeline")
    if cost_exploration_enabled(values):
        from src.services.paper_learning_budget import limits
        limits(values)
        min_probe_net_bps(values)
    if completed_candles_enabled(values) and not enabled(values):
        raise ValueError("completed_candle_learning_requires_adaptive_learning")
    if not enabled(values):
        return
    control_fraction(values)
    if values.get("PAPER_EVIDENCE_STOP_RULE_ENABLED", "false").strip().lower() in TRUTHY:
        raise ValueError("paper_learning_and_permanent_stop_are_mutually_exclusive")
    if (values.get("TRADING_MODE") != "paper_train"
            or values.get("PAPER_ONLY_MODE", "").strip().lower() not in TRUTHY
            or any(values.get(key, "").strip().lower() not in {"false", "0", "no", "off"}
                   for key in ("ENABLE_REAL_ORDERS", "REAL_ORDERS_ALLOWED", "LIVE_TRADING_CONFIRMED"))):
        raise ValueError("paper_learning_requires_explicit_paper_only_guards")
    profile_signature(values)


def profile_signature(env: Mapping[str, str] | None = None) -> str:
    """Preserve the declared executor geometry/cost cohort, without retuning it."""
    values = os.environ if env is None else env
    profile: dict[str, float] = {}
    for key in ("PAPER_TP_ZONE_BPS", "PAPER_SL_ZONE_BPS", "PAPER_MAX_POSITION_AGE_S",
                "PAPER_FEE_PCT", "PAPER_SLIPPAGE_PCT"):
        try:
            value = float(values[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("paper_learning_requires_explicit_exit_cost_profile") from exc
        if not math.isfinite(value) or value < 0 or ("PCT" not in key and value == 0):
            raise ValueError("invalid_paper_learning_exit_cost_profile")
        profile[key] = value
    return _hash(profile)


@dataclass(frozen=True)
class LearningContext:
    learning_source: str
    strategy_version: str
    exit_profile: str
    profile_signature: str
    symbol: str
    regime: str
    side: str
    neural_cohort: str = ""
    neural_bucket: str = ""

    def __post_init__(self) -> None:
        if self.learning_source not in SOURCES or self.side not in {"BUY", "SELL"}:
            raise ValueError("unsupported_paper_learning_source_or_side")
        if any(not isinstance(x, str) or not x or len(x) > 120 for x in (
                self.strategy_version, self.exit_profile, self.profile_signature, self.symbol, self.regime)):
            raise ValueError("invalid_paper_learning_context")
        if bool(self.neural_cohort) != bool(self.neural_bucket):
            raise ValueError("incomplete_neural_learning_context")
        if self.neural_cohort and (
                self.symbol != "BTCUSDT" or len(self.neural_cohort) != 64
                or any(c not in "0123456789abcdef" for c in self.neural_cohort)
                or len(self.neural_bucket) > 40):
            raise ValueError("invalid_neural_learning_context")

    @property
    def base_cohort(self) -> str:
        return _hash((VERSION, self.learning_source, self.strategy_version,
                      self.exit_profile, self.profile_signature))

    @property
    def cohort(self) -> str:
        if self.neural_cohort:
            return _hash((NEURAL_VERSION, self.base_cohort, "BTCUSDT", self.neural_cohort))
        return self.base_cohort

    @property
    def base_key(self) -> str:
        return _hash((self.base_cohort, self.symbol, self.regime, self.side))

    @property
    def key(self) -> str:
        if self.neural_cohort:
            return _hash((self.cohort, self.symbol, self.regime, self.side, self.neural_bucket))
        return _hash((self.cohort, self.symbol, self.regime, self.side))


@dataclass(frozen=True)
class ClosedOutcome:
    trade_id: str
    context_key: str
    entry_ms: int
    exit_ms: int
    net_bps: float

    def __post_init__(self) -> None:
        if (not isinstance(self.trade_id, str) or not self.trade_id or len(self.trade_id) > 256
                or not isinstance(self.context_key, str) or len(self.context_key) != 64
                or type(self.entry_ms) is not int or type(self.exit_ms) is not int
                or not 0 < self.entry_ms <= self.exit_ms):
            raise ValueError("invalid_paper_learning_outcome")
        _finite(self.net_bps)


@dataclass(frozen=True)
class LearningDecision:
    allowed: bool
    action: str
    n: int
    context_n: int
    mean_net_bps: float
    probability: float
    draw: float
    last_close_ms: int
    context_key: str
    cohort: str
    training_hash: str
    neural_metadata: Mapping = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (type(self.allowed) is not bool or self.action not in {"CONTROL", "WARMUP", "PROBE", "ADAPTIVE", "HOLD"}
                or self.allowed != (self.action != "HOLD")
                or type(self.n) is not int or type(self.context_n) is not int
                or not 0 <= self.context_n <= self.n <= MAX_HISTORY
                or type(self.last_close_ms) is not int or self.last_close_ms < 0):
            raise ValueError("invalid_paper_learning_decision")
        _finite(self.mean_net_bps)
        if not 0 <= _finite(self.draw) < 1 or not 0 <= _finite(self.probability) <= 1:
            raise ValueError("invalid_paper_learning_probability")
        for digest in (self.context_key, self.cohort, self.training_hash):
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid_paper_learning_digest")
        if self.neural_metadata:
            from src.services.paper_neural_context import validate_metadata
            validate_metadata(self.neural_metadata)

    def metadata(self) -> dict:
        return {"policy_version": NEURAL_VERSION if self.neural_metadata else VERSION, "policy_action": self.action,
                "policy_n": self.n, "policy_context_n": self.context_n,
                "policy_mean_net_bps": self.mean_net_bps, "policy_probability": self.probability,
                "policy_draw": self.draw, "policy_last_close_ms": self.last_close_ms,
                "policy_context": self.context_key, "policy_cohort": self.cohort,
                "policy_training_hash": self.training_hash, **self.neural_metadata}


def _weighted_mean(rows: Sequence[ClosedOutcome]) -> tuple[float, float]:
    weighted = total = 0.0
    for index, row in enumerate(reversed(rows)):
        weight = 2 ** (-index / HALF_LIFE_CLOSES)
        weighted += weight * row.net_bps
        total += weight
    return (weighted / total if total else 0.0), total


def decide(context: LearningContext, outcomes: Sequence[ClosedOutcome], *,
           decision_id: str, as_of_ms: int, neural_metadata: Mapping | None = None) -> LearningDecision:
    """Chronological post-cost adaptation; subsequent outcomes cannot leak in.

    A five-observation source/profile prior shrinks sparse contexts toward the
    other contexts in the same cohort. No history means a zero prior, not edge.
    Hash draws are stable for retries and independent of future market outcomes.
    """
    if not isinstance(decision_id, str) or not decision_id or type(as_of_ms) is not int or as_of_ms <= 0:
        raise ValueError("invalid_paper_learning_decision_identity")
    neural_metadata = dict(neural_metadata or {})
    if context.neural_cohort:
        from src.services.paper_neural_context import validate_metadata
        validate_metadata(neural_metadata)
        if (neural_metadata["neural_cohort"] != context.neural_cohort
                or neural_metadata["neural_bucket"] != context.neural_bucket
                or neural_metadata["neural_decision_ms"] > as_of_ms):
            raise ValueError("neural_learning_context_mismatch")
    elif neural_metadata:
        raise ValueError("unexpected_neural_learning_metadata")
    rows = sorted((row for row in outcomes if row.exit_ms <= as_of_ms), key=lambda r: (r.exit_ms, r.trade_id))
    if len({row.trade_id for row in rows}) != len(rows):
        raise ValueError("duplicate_paper_learning_outcome")
    rows = rows[-MAX_HISTORY:]
    own = [row for row in rows if row.context_key == context.key]
    other = [row for row in rows if row.context_key != context.key]
    prior_mean, _ = _weighted_mean(other)
    own_mean, own_weight = _weighted_mean(own)
    mean = (own_mean * own_weight + prior_mean * 5) / (own_weight + 5)
    probability = min(MAX_ADMISSION_PROBABILITY, max(MIN_ADMISSION_PROBABILITY,
                      1 / (1 + math.exp(-max(-50, min(50, mean / RETURN_SCALE_BPS))))))
    # New inference never buys another random draw for the same candle candidate.
    # Baseline and neural cohorts keep the same native admission/control draw.
    identity = (context.base_cohort, context.base_key, decision_id)
    draw = int(_hash((VERSION, "admission", identity))[:13], 16) / 16**13
    control_draw = int(_hash((VERSION, "control", identity))[:13], 16) / 16**13
    last_close = max((row.exit_ms for row in rows), default=0)
    if control_draw < control_fraction():
        action, probability = "CONTROL", 1.0
    elif len(rows) < WARMUP_CLOSES:
        action, probability = "WARMUP", 1.0
    elif as_of_ms - last_close >= PROBE_INTERVAL_MS:
        action, probability = "PROBE", 1.0
    else:
        action = "ADAPTIVE" if draw < probability else "HOLD"
    training_hash = _hash([(row.trade_id, row.context_key, row.entry_ms, row.exit_ms, row.net_bps) for row in rows])
    return LearningDecision(action != "HOLD", action, len(rows), len(own), mean, probability,
                            draw, last_close, context.key, context.cohort, training_hash, neural_metadata)


def encode_tag(metadata: Mapping) -> str:
    """Use the existing bounded tags→position→close→tags_json path."""
    validated_metadata(metadata)
    encoded = metadata["policy_version"] + ":" + json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_TAG_BYTES:
        raise ValueError("paper_learning_tag_too_large")
    return encoded


def validated_metadata(metadata: Mapping) -> dict:
    if not isinstance(metadata, Mapping) or metadata.get("policy_version") not in {VERSION, NEURAL_VERSION}:
        raise ValueError("invalid_paper_learning_metadata")
    neural = {key: value for key, value in metadata.items() if key.startswith("neural_")}
    if (metadata["policy_version"] == NEURAL_VERSION) != bool(neural):
        raise ValueError("paper_learning_version_context_mismatch")
    decision = LearningDecision(metadata.get("policy_action") != "HOLD", metadata.get("policy_action"),
        metadata.get("policy_n"), metadata.get("policy_context_n"), metadata.get("policy_mean_net_bps"),
        metadata.get("policy_probability"), metadata.get("policy_draw"), metadata.get("policy_last_close_ms"),
        metadata.get("policy_context"), metadata.get("policy_cohort"), metadata.get("policy_training_hash"), neural)
    result = decision.metadata()
    if dict(metadata) != result:
        raise ValueError("unexpected_paper_learning_metadata")
    return result


def metadata_from_tags(tags: object) -> dict | None:
    if not isinstance(tags, list):
        return None
    matches = [tag for tag in tags if isinstance(tag, str) and tag.startswith("paper_source_learning_")]
    if not matches:
        return None
    if len(matches) != 1 or len(matches[0].encode()) > MAX_TAG_BYTES:
        raise ValueError("ambiguous_paper_learning_tags")
    prefix, separator, payload = matches[0].partition(":")
    if not separator or prefix not in {VERSION, NEURAL_VERSION}:
        raise ValueError("unsupported_paper_learning_tag")
    meta = validated_metadata(json.loads(payload))
    if meta["policy_version"] != prefix:
        raise ValueError("paper_learning_tag_version_mismatch")
    return meta


def read_outcomes(db_path: Path, context: LearningContext, *, as_of_ms: int) -> list[ClosedOutcome]:
    """Read the existing durable close projection; no state reset or cache import."""
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)
    try:
        connection.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + 0.5
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        rows = connection.execute(
            "SELECT trade_id,symbol,side,regime,tp_sl_profile,entry_ts,exit_ts,pnl_pct,tags_json "
            "FROM closed_trades WHERE paper_source=? AND learning_source=? AND exit_ts<=? "
            "ORDER BY exit_ts DESC,trade_id DESC LIMIT ?",
            ("p0_8_plus_evidence_collection", context.learning_source, as_of_ms / 1000, MAX_HISTORY)).fetchall()
    finally:
        connection.close()
    outcomes = []
    for trade_id, symbol, side, regime, exit_profile, entry, exit_time, pnl_pct, tags_json in rows:
        if tags_json is None:
            continue  # historical policy provenance cannot be fabricated
        if len(tags_json) > 16384:
            raise ValueError("oversized_paper_learning_history_tags")
        metadata = metadata_from_tags(json.loads(tags_json))
        if metadata is None or metadata["policy_cohort"] != context.cohort:
            continue
        row_context = LearningContext(context.learning_source, context.strategy_version,
            exit_profile, context.profile_signature, symbol, regime, side,
            metadata.get("neural_cohort", ""), metadata.get("neural_bucket", ""))
        entry_ms, exit_ms = round(_finite(entry) * 1000), round(_finite(exit_time) * 1000)
        if (row_context.key != metadata["policy_context"] or metadata["policy_action"] == "HOLD"
                or metadata["policy_last_close_ms"] > entry_ms
                or metadata.get("neural_decision_ms", 0) > entry_ms):
            raise ValueError("invalid_paper_learning_close_attribution")
        outcomes.append(ClosedOutcome(trade_id, row_context.key, entry_ms, exit_ms, _finite(pnl_pct) * 100))
    return outcomes


def evaluate(signal) -> LearningDecision:
    """Production adapter, called only by the existing central admission router."""
    if not enabled():
        raise ValueError("paper_learning_not_enabled")
    validate_config()
    if signal.shadow_only or not signal.evidence_only:
        raise ValueError("paper_learning_requires_evidence_candidate")
    from src.services.paper_neural_context import for_signal
    neural = for_signal(signal)
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(signal.side, signal.side)
    context = LearningContext(signal.learning_source, signal.strategy_version, signal.exit_profile,
                              profile_signature(), signal.symbol, signal.regime, side,
                              neural.get("neural_cohort", ""), neural.get("neural_bucket", ""))
    cache = sys.modules.get("src.services.local_persistent_cache")
    if cache is None:
        raise ValueError("canonical_close_cache_not_initialized")
    outcomes = read_outcomes(Path(cache.LOCAL_DB_PATH), context, as_of_ms=signal.generated_processing_time_ms)
    decision = decide(context, outcomes, decision_id=signal.signal_id,
                      as_of_ms=signal.generated_processing_time_ms, neural_metadata=neural)
    if signal.learning_source in PROBE_SOURCES:
        if not probe_signal_valid(signal):
            raise ValueError("invalid_paper_probe_signal")
        from src.services.paper_learning_budget import current_reason
        reason = current_reason(signal.symbol, now_ms=signal.generated_processing_time_ms)
        if reason != "allow":
            logging.getLogger(__name__).info("[PAPER_LEARNING_BUDGET] symbol=%s reason=%s", signal.symbol, reason)
            decision = replace(decision, allowed=False, action="HOLD", probability=0.0)
    return decision
