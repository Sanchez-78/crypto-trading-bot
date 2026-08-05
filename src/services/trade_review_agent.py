"""Deterministic cohort-aware review agent for recent PAPER trades."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Optional

from src.core.trade_metrics_contract import classify_outcome

SCHEMA_VERSION = "trade_review_report_v1"
WINDOW_SIZE = 200
SCAN_SIZE = 400
SYMBOL_POLICY_HALF_WINDOW = 30
POST_POLICY_MIN_CANONICAL = 20
DEGRADED_CANONICAL_SYMBOL_QUOTA = 0.00
CANONICAL_SHADOW_RECOVERY_QUOTA = 0.10
CONTROL_BUCKETS = frozenset(
    {
        "D_NEG_EV_CONTROL",
        "E_NO_PATTERN",
        "E_NO_PATTERN_BASELINE",
        "C_NEG_EV_PROBE",
        "PAPER_STARVATION_DISCOVERY",
    }
)


def _finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metric_block(trades: list[dict]) -> dict:
    pnl = [float(trade["_net_pnl_pct"]) for trade in trades]
    positives = sum(value for value in pnl if value > 0)
    negatives = abs(sum(value for value in pnl if value < 0))
    outcomes = Counter(trade["_outcome"] for trade in trades)
    if negatives > 0:
        profit_factor = positives / negatives
        capped = profit_factor > 999.0
        profit_factor = min(profit_factor, 999.0)
    elif positives > 0:
        profit_factor = 999.0
        capped = True
    else:
        profit_factor = 0.0
        capped = False

    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in pnl:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)

    exit_reasons = Counter(
        str(trade.get("exit_reason") or "UNKNOWN") for trade in trades
    )
    denominator = max(1, len(trades))
    return {
        "n": len(trades),
        "wins": outcomes["WIN"],
        "losses": outcomes["LOSS"],
        "flats": outcomes["FLAT"],
        "win_rate": round(outcomes["WIN"] / denominator, 6),
        "profit_factor": round(profit_factor, 6),
        "profit_factor_capped": capped,
        "expectancy_pct_points": round(
            statistics.fmean(pnl) if pnl else 0.0,
            8,
        ),
        "median_pnl_pct_points": round(
            statistics.median(pnl) if pnl else 0.0,
            8,
        ),
        "net_pnl_pct_points": round(sum(pnl), 8),
        "max_drawdown_pct_points": round(drawdown, 8),
        "exit_distribution": dict(sorted(exit_reasons.items())),
    }


class TradeReviewAgent:
    """Pure analyzer; it cannot write strategy or execute trades."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        window_size: int = WINDOW_SIZE,
        scan_size: int = SCAN_SIZE,
    ):
        self._clock = clock
        self._window_size = min(max(int(window_size), 20), WINDOW_SIZE)
        self._scan_size = min(
            max(int(scan_size), self._window_size),
            SCAN_SIZE,
        )

    @staticmethod
    def _normalise_trade(raw: Any) -> tuple[str, Optional[dict]]:
        if not isinstance(raw, dict):
            return "invalid_record", None
        trade_id = str(raw.get("trade_id") or raw.get("id") or "").strip()
        pnl = _finite(
            raw.get("net_pnl_pct")
            if raw.get("net_pnl_pct") is not None
            else raw.get("pnl_pct")
        )
        exit_ts = _finite(raw.get("exit_ts", raw.get("exit_time")), 0.0)
        if not trade_id or pnl is None or not exit_ts or exit_ts <= 0:
            return "invalid_record", None

        try:
            outcome = classify_outcome(pnl).value
        except Exception:
            return "invalid_outcome", None
        stored_outcome = str(raw.get("outcome") or "").upper()
        if stored_outcome and stored_outcome not in {"WIN", "LOSS", "FLAT"}:
            return "invalid_outcome", None
        if stored_outcome and stored_outcome != outcome:
            return "outcome_contract_mismatch", None
        if raw.get("quarantined"):
            return "quarantined_trade", None
        if raw.get("learning_skipped"):
            return "learning_skipped_trade", None
        if str(raw.get("exit_reason") or "").upper() == "TIMEOUT_NO_PRICE":
            return "timeout_without_real_price", None
        contract_version = raw.get("metrics_contract_version")
        if contract_version not in (None, "", 1, "1"):
            return "metrics_contract_mismatch", None
        if raw.get("entry_price") is not None:
            entry_price = _finite(raw.get("entry_price"))
            if entry_price is None or entry_price <= 0:
                return "invalid_entry_price", None
        if raw.get("exit_price") is not None:
            exit_price = _finite(raw.get("exit_price"))
            if exit_price is None or exit_price <= 0:
                return "invalid_exit_price", None

        bucket = str(
            raw.get("bucket")
            or raw.get("training_bucket")
            or raw.get("explore_bucket")
            or ""
        )
        readiness = raw.get("readiness_eligible")
        real_readiness = raw.get("real_readiness_eligible")
        paper_only = bool(raw.get("paper_learning_only", False))
        shadow = bool(
            raw.get("learning_shadow_only", False)
            or raw.get("shadow_only", False)
        )
        provenance_present = any(
            value is not None and value != ""
            for value in (
                raw.get("paper_source"),
                raw.get("learning_source"),
                raw.get("bucket"),
                raw.get("training_bucket"),
                raw.get("explore_bucket"),
                readiness,
                real_readiness,
            )
        )
        if (
            bucket in CONTROL_BUCKETS
            or readiness is False
            or real_readiness is False
            or paper_only
            or shadow
        ):
            cohort = "exploration"
        elif not provenance_present or readiness is None or real_readiness is None:
            cohort = "unknown_provenance"
        elif bool(readiness) and bool(real_readiness) and not paper_only:
            cohort = "canonical"
        else:
            cohort = "exploration"

        trade = dict(raw)
        trade.update(
            {
                "trade_id": trade_id,
                "_net_pnl_pct": float(pnl),
                "_outcome": outcome,
                "_exit_ts": float(exit_ts),
                "_bucket": bucket,
                "_cohort": cohort,
            }
        )
        return cohort, trade

    def analyze(
        self,
        trades: Any,
        *,
        current_policy: Optional[dict] = None,
        learning_snapshot: Optional[dict] = None,
        now: Optional[float] = None,
    ) -> dict:
        now = float(self._clock() if now is None else now)
        raw_list = [item for item in (trades or []) if isinstance(item, dict)]
        raw_list.sort(
            key=lambda item: (
                _finite(item.get("exit_ts", item.get("exit_time")), 0.0) or 0.0,
                str(item.get("trade_id") or item.get("id") or ""),
            ),
            reverse=True,
        )
        # Exploration trades are intentionally high-volume and must not evict
        # canonical evidence from the strategy feedback loop. Scan a bounded
        # local-only source, then build equally bounded cohort windows. This
        # preserves fresh experimental coverage without letting it starve the
        # canonical two-window checks that are allowed to tune policy.
        scanned = raw_list[: self._scan_size]

        seen: set[str] = set()
        cohorts: dict[str, list[dict]] = defaultdict(list)
        excluded = Counter()
        normalized = []
        for raw in scanned:
            cohort, trade = self._normalise_trade(raw)
            if trade is None:
                excluded[cohort] += 1
                continue
            if trade["trade_id"] in seen:
                excluded["duplicate_trade_id"] += 1
                continue
            seen.add(trade["trade_id"])
            normalized.append(trade)
            cohorts[cohort].append(trade)

        scanned_canonical_n = len(cohorts["canonical"])
        scanned_exploration_n = len(cohorts["exploration"])
        canonical = sorted(
            cohorts["canonical"], key=lambda trade: trade["_exit_ts"]
        )[-self._window_size:]
        exploration = sorted(
            cohorts["exploration"],
            key=lambda trade: trade["_exit_ts"],
        )[-self._window_size:]
        unknown = cohorts["unknown_provenance"]
        recent50 = canonical[-50:]
        previous50 = canonical[-100:-50]
        policy = current_policy if isinstance(current_policy, dict) else {}
        learning = (
            learning_snapshot if isinstance(learning_snapshot, dict) else {}
        )

        evidence_rows = [
            {
                "trade_id": trade["trade_id"],
                "exit_ts": trade["_exit_ts"],
                "pnl": trade["_net_pnl_pct"],
                "outcome": trade["_outcome"],
                "cohort": trade["_cohort"],
                "bucket": trade["_bucket"],
            }
            for trade in sorted(
                normalized,
                key=lambda trade: (trade["_exit_ts"], trade["trade_id"]),
            )
        ]
        evidence_hash = _stable_hash(evidence_rows)

        all_metrics = _metric_block(canonical)
        recent_metrics = _metric_block(recent50)
        previous_metrics = _metric_block(previous50)
        exploration_metrics = _metric_block(exploration)

        policy_revision = max(0, int(_finite(policy.get("revision"), 0.0) or 0))
        policy_applied_at = _finite(policy.get("applied_at"), 0.0) or 0.0
        post_policy_canonical = [
            trade
            for trade in canonical
            if policy_applied_at > 0.0 and trade["_exit_ts"] >= policy_applied_at
        ]
        post_policy_exploration = [
            trade
            for trade in exploration
            if policy_applied_at > 0.0 and trade["_exit_ts"] >= policy_applied_at
        ]
        post_policy_canonical_metrics = _metric_block(post_policy_canonical)
        post_policy_exploration_metrics = _metric_block(post_policy_exploration)
        post_policy_symbol_groups: dict[str, list[dict]] = defaultdict(list)
        for trade in post_policy_canonical:
            post_policy_symbol_groups[
                str(trade.get("symbol") or "UNKNOWN").upper()
            ].append(trade)
        if policy_revision <= 0 or policy_applied_at <= 0.0:
            post_policy_status = "baseline"
            post_policy_next_action = "await_first_policy_change"
        elif len(post_policy_canonical) < POST_POLICY_MIN_CANONICAL:
            post_policy_status = "collecting"
            post_policy_next_action = "collect_more_canonical_evidence"
        elif (
            post_policy_canonical_metrics["profit_factor"] < 0.80
            or post_policy_canonical_metrics["expectancy_pct_points"] < 0.0
        ):
            post_policy_status = "review_required"
            post_policy_next_action = "review_post_policy_edge"
        else:
            post_policy_status = "healthy"
            post_policy_next_action = "hold_policy"
        post_policy = {
            "policy_revision": policy_revision,
            "applied_at": policy_applied_at or None,
            "status": post_policy_status,
            "next_action": post_policy_next_action,
            "minimum_canonical_n": POST_POLICY_MIN_CANONICAL,
            "bounded_by_review_scan": True,
            "canonical": post_policy_canonical_metrics,
            "exploration": {
                "descriptive_only": True,
                **post_policy_exploration_metrics,
            },
            "canonical_by_symbol": {
                symbol: _metric_block(values)
                for symbol, values in sorted(post_policy_symbol_groups.items())
            },
        }

        unknown_ratio = len(unknown) / max(1, len(scanned))
        schema_valid_ratio = len(normalized) / max(1, len(scanned))
        data_blocked = bool(
            excluded
            or schema_valid_ratio < 0.95
            or unknown_ratio > 0.05
        )
        lifetime_n = int(
            _finite(
                learning.get("lifetime_n", learning.get("rolling100_n")),
                0.0,
            )
            or 0
        )
        sufficient = (
            len(scanned) >= self._window_size
            and len(canonical) >= 100
            and len(recent50) == 50
            and len(previous50) == 50
            and lifetime_n >= 200
            and not data_blocked
        )

        recommendation = {
            "code": "HOLD_CURRENT_POLICY",
            "severity": "info",
            "target_entry_quota_multiplier": None,
            "auto_applicable": False,
            "reason_codes": [],
        }
        if data_blocked:
            recommendation.update(
                {
                    "code": "DATA_QUALITY_BLOCK",
                    "severity": "warning",
                    "reason_codes": [
                        "unknown_or_invalid_trade_provenance",
                    ],
                }
            )
        elif not sufficient:
            recommendation.update(
                {
                    "code": "INSUFFICIENT_EVIDENCE",
                    "reason_codes": [
                        "need_bounded_scan_100_canonical_two_50_windows",
                    ],
                }
            )
        else:
            recent_critical = (
                recent_metrics["profit_factor"] < 0.50
                or recent_metrics["expectancy_pct_points"] <= -0.15
            )
            previous_weak = (
                previous_metrics["profit_factor"] < 0.80
                or previous_metrics["expectancy_pct_points"] < 0.0
            )
            recent_weak = (
                recent_metrics["profit_factor"] < 0.80
                or recent_metrics["expectancy_pct_points"] < 0.0
            )
            previous_critical = (
                previous_metrics["profit_factor"] < 0.80
                or previous_metrics["expectancy_pct_points"] < 0.0
            )
            if recent_critical and previous_weak:
                recommendation.update(
                    {
                        "code": "GLOBAL_QUOTA_050",
                        "severity": "high",
                        "target_entry_quota_multiplier": 0.50,
                        "auto_applicable": True,
                        "reason_codes": ["two_window_critical_negative_edge"],
                    }
                )
            elif recent_weak and previous_critical:
                recommendation.update(
                    {
                        "code": "GLOBAL_QUOTA_075",
                        "severity": "warning",
                        "target_entry_quota_multiplier": 0.75,
                        "auto_applicable": True,
                        "reason_codes": ["two_window_weak_edge"],
                    }
                )
            elif (
                float(policy.get("paper_entry_quota_multiplier", 1.0)) < 1.0
                and recent_metrics["profit_factor"] >= 1.05
                and previous_metrics["profit_factor"] >= 1.05
                and recent_metrics["expectancy_pct_points"] > 0.0
                and previous_metrics["expectancy_pct_points"] > 0.0
                and len(canonical) >= 150
            ):
                recommendation.update(
                    {
                        "code": "RESTORE_BASELINE_100",
                        "target_entry_quota_multiplier": 1.0,
                        "auto_applicable": True,
                        "reason_codes": ["two_window_edge_recovery"],
                    }
                )

        segment_groups: dict[str, list[dict]] = defaultdict(list)
        for trade in canonical:
            key = ":".join(
                [
                    str(trade.get("symbol") or "UNKNOWN"),
                    str(trade.get("regime") or "UNKNOWN"),
                    str(trade.get("side") or "UNKNOWN"),
                ]
            )
            segment_groups[key].append(trade)
        risky_segments = []
        for key, values in segment_groups.items():
            metrics = _metric_block(values[-40:])
            if metrics["n"] >= 40 and (
                metrics["profit_factor"] < 0.80
                or metrics["expectancy_pct_points"] < 0.0
            ):
                risky_segments.append({"segment": key, **metrics})
        risky_segments.sort(
            key=lambda item: (
                item["expectancy_pct_points"],
                item["profit_factor"],
            )
        )

        raw_current_symbol_quotas = policy.get(
            "canonical_symbol_quota_multipliers", {}
        )
        current_symbol_quotas = {}
        if isinstance(raw_current_symbol_quotas, dict):
            for raw_symbol, raw_quota in raw_current_symbol_quotas.items():
                symbol = str(raw_symbol or "").strip().upper()
                quota = _finite(raw_quota, 1.0)
                if symbol and quota is not None and quota < 1.0:
                    current_symbol_quotas[symbol] = min(max(quota, 0.00), 1.0)
        target_symbol_quotas = dict(current_symbol_quotas)
        symbol_groups: dict[str, list[dict]] = defaultdict(list)
        for trade in canonical:
            symbol_groups[str(trade.get("symbol") or "UNKNOWN").upper()].append(
                trade
            )
        canonical_shadow_groups: dict[str, list[dict]] = defaultdict(list)
        for trade in exploration:
            tags = {
                str(tag).strip().lower()
                for tag in (trade.get("tags") or [])
            }
            if "canonical_policy_shadow" in tags:
                canonical_shadow_groups[
                    str(trade.get("symbol") or "UNKNOWN").upper()
                ].append(trade)
        symbol_advisories = []
        reviewed_symbols = set(symbol_groups) | set(current_symbol_quotas)
        for symbol in sorted(reviewed_symbols):
            required = SYMBOL_POLICY_HALF_WINDOW * 2
            current_quota = current_symbol_quotas.get(symbol, 1.0)
            shadow_values = canonical_shadow_groups.get(symbol, [])

            # A fully quarantined symbol may only re-enter canonical as a
            # bounded 10% probe.  The evidence must be made of candidates that
            # passed canonical admission and were routed to exploration solely
            # by this policy, all collected after the quarantine started.
            if current_quota <= 0.0:
                recovery_values = [
                    trade
                    for trade in shadow_values
                    if policy_applied_at > 0.0
                    and trade["_exit_ts"] >= policy_applied_at
                ]
                if len(recovery_values) >= required:
                    recovery_evidence = recovery_values[-required:]
                    shadow_previous = _metric_block(
                        recovery_evidence[:SYMBOL_POLICY_HALF_WINDOW]
                    )
                    shadow_recent = _metric_block(
                        recovery_evidence[SYMBOL_POLICY_HALF_WINDOW:]
                    )
                    shadow_combined = _metric_block(recovery_evidence)
                    stable_shadow_recovery = (
                        shadow_previous["profit_factor"] >= 1.20
                        and shadow_recent["profit_factor"] >= 1.20
                        and shadow_combined["profit_factor"] >= 1.20
                        and shadow_previous["expectancy_pct_points"] > 0.0
                        and shadow_recent["expectancy_pct_points"] > 0.0
                    )
                    if stable_shadow_recovery:
                        target_symbol_quotas[symbol] = (
                            CANONICAL_SHADOW_RECOVERY_QUOTA
                        )
                        symbol_advisories.append(
                            {
                                "code": "CANONICAL_SYMBOL_RECOVERY_PROBE",
                                "auto_applicable": sufficient,
                                "symbol": symbol,
                                "target_quota_multiplier":
                                    CANONICAL_SHADOW_RECOVERY_QUOTA,
                                "shadow_previous30": shadow_previous,
                                "shadow_recent30": shadow_recent,
                                "shadow_combined60": shadow_combined,
                                "reason_codes": [
                                    "two_canonical_shadow_windows_positive_edge"
                                ],
                            }
                        )
                continue

            values = symbol_groups.get(symbol, [])
            # Once a shadow-backed recovery probe is active, stale canonical
            # history must not immediately undo it.  Gather two fresh canonical
            # windows after the probe before either restoring or quarantining.
            if current_quota < 1.0 and len(shadow_values) >= required:
                values = [
                    trade
                    for trade in values
                    if policy_applied_at > 0.0
                    and trade["_exit_ts"] >= policy_applied_at
                ]
            if len(values) < required:
                continue
            evidence = values[-required:]
            previous = _metric_block(evidence[:SYMBOL_POLICY_HALF_WINDOW])
            recent = _metric_block(evidence[SYMBOL_POLICY_HALF_WINDOW:])
            combined = _metric_block(evidence)
            previous_weak = (
                previous["profit_factor"] < 0.80
                or previous["expectancy_pct_points"] < 0.0
            )
            recent_weak = (
                recent["profit_factor"] < 0.80
                or recent["expectancy_pct_points"] < 0.0
            )
            stable_degradation = (
                previous_weak
                and recent_weak
                and combined["profit_factor"] < 0.70
                and combined["expectancy_pct_points"] < 0.0
            )
            stable_recovery = (
                previous["profit_factor"] >= 1.05
                and recent["profit_factor"] >= 1.05
                and previous["expectancy_pct_points"] > 0.0
                and recent["expectancy_pct_points"] > 0.0
            )
            if stable_degradation:
                target_symbol_quotas[symbol] = DEGRADED_CANONICAL_SYMBOL_QUOTA
                symbol_advisories.append(
                    {
                        "code": "CANONICAL_SYMBOL_QUOTA_REDUCE",
                        "auto_applicable": sufficient,
                        "symbol": symbol,
                        "target_quota_multiplier":
                            DEGRADED_CANONICAL_SYMBOL_QUOTA,
                        "previous30": previous,
                        "recent30": recent,
                        "combined60": combined,
                        "reason_codes": ["two_symbol_windows_negative_edge"],
                    }
                )
            elif symbol in current_symbol_quotas and stable_recovery:
                target_symbol_quotas.pop(symbol, None)
                symbol_advisories.append(
                    {
                        "code": "CANONICAL_SYMBOL_QUOTA_RESTORE",
                        "auto_applicable": sufficient,
                        "symbol": symbol,
                        "target_quota_multiplier": 1.0,
                        "previous30": previous,
                        "recent30": recent,
                        "combined60": combined,
                        "reason_codes": ["two_symbol_windows_edge_recovery"],
                    }
                )
        symbol_policy_changed = (
            sufficient and target_symbol_quotas != current_symbol_quotas
        )
        symbol_policy = {
            "code": (
                "APPLY_CANONICAL_SYMBOL_QUOTAS"
                if symbol_policy_changed
                else "HOLD_CANONICAL_SYMBOL_QUOTAS"
            ),
            "auto_applicable": symbol_policy_changed,
            "current_canonical_quota_multipliers": dict(
                sorted(current_symbol_quotas.items())
            ),
            "target_canonical_quota_multipliers": dict(
                sorted(target_symbol_quotas.items())
            ),
            "minimum_evidence_per_symbol": SYMBOL_POLICY_HALF_WINDOW * 2,
        }

        exploration_coverage = Counter(
            f"{trade.get('symbol', 'UNKNOWN')}:{trade.get('side', 'UNKNOWN')}"
            for trade in exploration
        )
        exploration_segment_groups: dict[str, list[dict]] = defaultdict(list)
        for trade in exploration:
            segment_key = ":".join(
                [
                    str(trade.get("symbol") or "UNKNOWN").upper(),
                    str(trade.get("regime") or "UNKNOWN").upper(),
                    str(trade.get("side") or "UNKNOWN").upper(),
                ]
            )
            exploration_segment_groups[segment_key].append(trade)
        exploration_segments = {
            key: _metric_block(values[-50:])
            for key, values in sorted(exploration_segment_groups.items())
            if len(values) >= 10
        }
        report = {
            "schema_version": SCHEMA_VERSION,
            "agent": "trade_review",
            "status": (
                "data_quality_blocked"
                if data_blocked
                else ("ready" if sufficient else "collecting")
            ),
            "run_id": f"trv_{evidence_hash[:16]}",
            "checked_at": now,
            "window": {
                "requested_n": self._window_size,
                "scan_limit_n": self._scan_size,
                "raw_n": len(scanned),
                "canonical_n": len(canonical),
                "exploration_n": len(exploration),
                "scanned_canonical_n": scanned_canonical_n,
                "scanned_exploration_n": scanned_exploration_n,
                "unknown_provenance_n": len(unknown),
            },
            "data_quality": {
                "schema_valid_ratio": round(schema_valid_ratio, 6),
                "unknown_provenance_ratio": round(unknown_ratio, 6),
                "excluded_by_reason": dict(sorted(excluded.items())),
                "blocked": data_blocked,
            },
            "metrics": {
                "canonical": {
                    "all": all_metrics,
                    "recent50": recent_metrics,
                    "previous50": previous_metrics,
                },
                "exploration": {
                    "descriptive_only": True,
                    "all": exploration_metrics,
                    "coverage": dict(sorted(exploration_coverage.items())),
                    "segments": exploration_segments,
                },
            },
            "post_policy": post_policy,
            "recommendation": recommendation,
            "symbol_policy": symbol_policy,
            "advisories": [
                {
                    "code": "SEGMENT_RISK_REVIEW",
                    "auto_applicable": False,
                    **segment,
                }
                for segment in risky_segments[:3]
            ] + symbol_advisories,
            "evidence": {
                "sha256": evidence_hash,
                "metrics_contract_version": 1,
            },
        }
        return report
