"""P1.1AP-N: Paper Adaptive Learning - Rolling Metrics & Policy Adaptation

Tracks rolling metrics (20/50/100 closes) alongside lifetime metrics.
Adapts policy weights based on rolling segment performance.
Gates REAL_READY transition on strict rolling metrics criteria.

State persisted as JSON; survives restarts.
"""

import json
import os
import logging
import time
from collections import deque
from typing import Optional, Dict, List

log = logging.getLogger(__name__)

# Persistent state file
_STATE_FILE = "server_local_backups/paper_adaptive_learning_state.json"

# Rolling window sizes
ROLLING_SIZES = {
    "rolling20": 20,
    "rolling50": 50,
    "rolling100": 100,
}

# Segment key format: symbol:regime:side
# Tracks metrics per segment for adaptive weighting

class PaperAdaptiveLearning:
    """Rolling metrics + policy adaptation engine."""

    def __init__(self, state_file: Optional[str] = None):
        # P1.1AP-O1A1: Allow test isolation via dependency injection
        self._state_file = state_file or _STATE_FILE

        self.lifetime_n = 0
        self.lifetime_pf = 1.0
        self.lifetime_expectancy = 0.0
        self.lifetime_net_pnl = 0.0

        # Rolling windows: list of (net_pnl_pct, outcome, segment_key, ts)
        self.rolling20 = deque(maxlen=20)
        self.rolling50 = deque(maxlen=50)
        self.rolling100 = deque(maxlen=100)

        # Segment weights: {segment_key: weight}
        # Weight affects priority in next paper entries
        self.segment_weights = {}

        # Readiness tracking
        self.lifecycle = "PAPER_COLLECTING"  # COLLECTING -> ADAPTING -> VALIDATING -> REAL_READY
        self.ready_ts = None
        self.real_active = False

        # P1.1AP-O1A: Qualification provenance for future REAL_READY
        self.qualification_schema_version = 1
        self.qualification_started_at = None  # Set on first O1A init
        self.qualification_n = 0
        self.qualification_window = deque(maxlen=100)
        self.operator_unlock = False

        # P1.1AP-O2: PAPER admission control policy state (cooldowns, etc.)
        self.paper_admission_controls = {
            "schema_version": 1,
            "starvation_discovery_cooldown": {
                "active": False,
                "activated_at": 0.0,
                "cooldown_until": 0.0,
                "reevaluation_budget_remaining": 0,
                "activation_evidence": {
                    "closed_n": 0,
                    "profit_factor": 0.0,
                    "avg_net_pnl_pct": 0.0,
                    "timeout_rate": 0.0
                }
            },
            "c_weak_segment_cooldowns": {},
            # P1.1AP-O2 Path C: One-time legacy discovery migration guard
            # Applied once on first patched startup if pre-patch entries lack route identity
            "legacy_pre_scoped_discovery_guard": {
                "activated_once": False,
                "reason": "operator_verified_pre_scoped_loss_evidence",
                "cooldown_until": 0.0,
                "applies_only_to": "PAPER_STARVATION_DISCOVERY"
            }
        }

        # Load persisted state if exists
        self._load_state()

        # P1.1AP-O1A: Initialize qualification epoch on first load if not persisted
        if self.qualification_started_at is None:
            self.qualification_started_at = time.time()
            log.info(
                "[PAPER_QUALIFICATION_EPOCH_STARTED] "
                "reason=provenance_migration_existing_history_not_counted "
                "existing_rolling100_n=%d qualification_n=0",
                len(self.rolling100)
            )

    def _is_d_neg_entry(self, entry: tuple) -> bool:
        """P1.1AP-N1 Fix 3: Check if rolling entry is D_NEG-contaminated.

        Entry format: (net_pnl_pct, outcome, segment_key, timestamp)
        D_NEG markers: segment_key contains "D_NEG" (shouldn't happen) or entry has diagnostic outcome markers.
        """
        if len(entry) < 3:
            return False
        segment_key = entry[2]
        # Check for D_NEG in segment key (unlikely but defensive)
        if "D_NEG" in str(segment_key):
            return True
        # Entries from D_NEG_EV_CONTROL would have been marked during record_close,
        # but as a fallback, check for suspiciously negative outcomes from cold-start period
        return False

    def _reconcile_state(self) -> None:
        """P1.1AP-N1 Fix 3: Safely reconcile state to remove D_NEG contamination.

        P1.1AP-O2: Also normalize entry format to ensure learning_source and admission_bucket are present.
        Legacy entries may have 4 or 5 elements; current format has 6.
        Called after loading state.
        """
        try:
            d_neg_count_before = 0

            # Filter D_NEG entries from rolling windows and normalize format
            for window_name in ["rolling20", "rolling50", "rolling100"]:
                window = getattr(self, window_name)
                original_len = len(window)
                legacy_4_element_count = sum(1 for e in window if len(e) == 4)
                legacy_5_element_count = sum(1 for e in window if len(e) == 5)

                # Filter out D_NEG entries AND normalize format
                # Ensure all entries have learning_source (position 4) and admission_bucket (position 5)
                normalized = []
                for e in window:
                    if self._is_d_neg_entry(e):
                        d_neg_count_before += 1
                        continue
                    # Normalize: extend with defaults for missing fields
                    if len(e) == 4:
                        # 4-element legacy: (pnl, outcome, segment, ts) → add learning_source="unknown", admission_bucket="unknown"
                        normalized.append((*e, "unknown", "unknown"))
                    elif len(e) == 5:
                        # 5-element: (pnl, outcome, segment, ts, learning_source) → add admission_bucket="unknown"
                        normalized.append((*e, "unknown"))
                    else:
                        # 6-element or other: keep as-is
                        normalized.append(e)

                filtered = deque(normalized, maxlen=window.maxlen)

                # Update if either D_NEG removed or format normalized
                if original_len > len(filtered) or legacy_4_element_count > 0 or legacy_5_element_count > 0:
                    setattr(self, window_name, filtered)
                    log.info(
                        "[PAPER_ADAPTIVE_STATE_RECONCILED] window=%s "
                        "d_neg_removed=%d legacy_4_elem_normalized=%d legacy_5_elem_normalized=%d remaining=%d",
                        window_name,
                        d_neg_count_before,
                        legacy_4_element_count,
                        legacy_5_element_count,
                        len(filtered)
                    )

            # Recompute metrics from remaining entries
            if d_neg_count_before > 0:
                # Recompute lifetime from rolling100 (approximation)
                lifetime_entries = list(self.rolling100)
                self.lifetime_n = max(len(lifetime_entries), self.lifetime_n - d_neg_count_before)

                if lifetime_entries:
                    self.lifetime_expectancy = self._compute_expectancy([e[0] for e in lifetime_entries])
                    self.lifetime_pf = self._compute_pf([(e[0], e[1]) for e in lifetime_entries])

                # Reset lifecycle if it was inflated by D_NEG
                if self.lifecycle == "REAL_READY" and len(self.rolling100) < 100:
                    self.lifecycle = "PAPER_COLLECTING"
                    log.info(
                        "[PAPER_ADAPTIVE_STATE_RECONCILED] lifecycle_reset "
                        "reason=d_neg_contamination rolling100_len=%d",
                        len(self.rolling100)
                    )

                log.warning(
                    "[PAPER_ADAPTIVE_STATE_RECONCILED] d_neg_entries_removed=%d "
                    "lifecycle=%s lifetime_n=%d rolling100_n=%d lifetime_pf=%.3f",
                    d_neg_count_before,
                    self.lifecycle,
                    self.lifetime_n,
                    len(self.rolling100),
                    self.lifetime_pf
                )
        except Exception as e:
            log.warning("[PAPER_ADAPTIVE_STATE_RECONCILE_ERROR] %s", str(e))

    def _load_state(self) -> None:
        """Load persistent state from JSON file."""
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    data = json.load(f)

                self.lifetime_n = data.get("lifetime_n", 0)
                self.lifetime_pf = data.get("lifetime_pf", 1.0)
                self.lifetime_expectancy = data.get("lifetime_expectancy", 0.0)
                self.lifecycle = data.get("lifecycle", "PAPER_COLLECTING")

                # Restore rolling windows
                self.rolling20 = deque(data.get("rolling20", []), maxlen=20)
                self.rolling50 = deque(data.get("rolling50", []), maxlen=50)
                self.rolling100 = deque(data.get("rolling100", []), maxlen=100)

                self.segment_weights = data.get("segment_weights", {})

                # P1.1AP-O1A: Restore qualification metadata
                self.qualification_schema_version = data.get("qualification_schema_version", 1)
                self.qualification_started_at = data.get("qualification_started_at")
                self.qualification_n = data.get("qualification_n", 0)
                self.qualification_window = deque(data.get("qualification_window", []), maxlen=100)
                self.operator_unlock = data.get("operator_unlock", False)

                log.info(
                    "[PAPER_LEARNING_STATE_RESTORE] state_ok=True "
                    "lifetime_n=%d rolling20=%d rolling50=%d rolling100=%d "
                    "lifecycle=%s",
                    self.lifetime_n,
                    len(self.rolling20),
                    len(self.rolling50),
                    len(self.rolling100),
                    self.lifecycle
                )

                # P1.1AP-O2: Restore admission control policy state
                self.paper_admission_controls = data.get("paper_admission_controls", self.paper_admission_controls)

                # P1.1AP-N1 Fix 3: Reconcile state to remove D_NEG contamination
                self._reconcile_state()
        except Exception as e:
            log.warning("[PAPER_LEARNING_STATE_RESTORE] failed: %s", e)

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            data = {
                "lifetime_n": self.lifetime_n,
                "lifetime_pf": self.lifetime_pf,
                "lifetime_expectancy": self.lifetime_expectancy,
                "lifecycle": self.lifecycle,
                "rolling20": list(self.rolling20),
                "rolling50": list(self.rolling50),
                "rolling100": list(self.rolling100),
                "segment_weights": self.segment_weights,
                "qualification_schema_version": self.qualification_schema_version,
                "qualification_started_at": self.qualification_started_at,
                "qualification_n": self.qualification_n,
                "qualification_window": list(self.qualification_window),
                "operator_unlock": self.operator_unlock,
                "paper_admission_controls": self.paper_admission_controls,
            }
            with open(self._state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.warning("[PAPER_LEARNING_STATE_SAVE] failed: %s", e)

    def record_close(self, trade: dict) -> None:
        """Record a closed paper trade and update metrics.

        Args:
            trade: {
                'net_pnl_pct': float,
                'outcome': str (WIN/LOSS/FLAT),
                'symbol': str,
                'regime': str,
                'side': str,
                'learning_source': str,
                'training_bucket': str,  # admission route that opened the trade
                'mfe_pct': float,
                'mae_pct': float,
                ...
            }
        """
        try:
            net_pnl_pct = float(trade.get("net_pnl_pct", 0.0))
        except (TypeError, ValueError):
            net_pnl_pct = 0.0
        outcome = str(trade.get("outcome", "FLAT"))
        symbol = str(trade.get("symbol", "UNKNOWN"))
        regime = str(trade.get("regime", "UNKNOWN"))
        side = str(trade.get("side", "UNKNOWN"))
        learning_source = str(trade.get("learning_source", "unknown"))
        admission_bucket = str(trade.get("training_bucket", "unknown"))
        segment_key = f"{symbol}:{regime}:{side}"

        # Record to rolling windows - P1.1AP-O2 Path C: Separate admission_bucket from learning_source
        # Entry format: (net_pnl_pct, outcome, segment_key, timestamp, learning_source, admission_bucket)
        entry = (net_pnl_pct, outcome, segment_key, time.time(), learning_source, admission_bucket)
        self.rolling20.append(entry)
        self.rolling50.append(entry)
        self.rolling100.append(entry)

        # Update lifetime metrics
        self.lifetime_n += 1
        self.lifetime_expectancy = self._compute_expectancy(
            [e[0] for e in self._lifetime_entries()]
        )
        self.lifetime_pf = self._compute_pf(
            [(e[0], e[1]) for e in self._lifetime_entries()]
        )

        # Update segment metrics and policy
        self._update_segment_policy(segment_key)

        # Emit log
        rolling20_pf = self._compute_rolling_pf(self.rolling20)
        rolling50_pf = self._compute_rolling_pf(self.rolling50)
        rolling100_pf = self._compute_rolling_pf(self.rolling100)
        rolling20_exp = self._compute_expectancy([e[0] for e in self.rolling20])
        rolling50_exp = self._compute_expectancy([e[0] for e in self.rolling50])
        rolling100_exp = self._compute_expectancy([e[0] for e in self.rolling100])

        policy_action = self._compute_policy_action(segment_key, len(self.rolling100))

        log.info(
            "[PAPER_CANONICAL_LEARNING_UPDATE] "
            "trade_id=%s symbol=%s side=%s regime=%s learning_source=%s "
            "outcome=%s net_pnl_pct=%.4f mfe_pct=%s mae_pct=%s "
            "lifetime_n=%d lifetime_pf=%.3f lifetime_expectancy=%.6f "
            "rolling20_n=%d rolling20_pf=%.3f rolling20_expectancy=%.6f "
            "rolling50_n=%d rolling50_pf=%.3f rolling50_expectancy=%.6f "
            "rolling100_n=%d rolling100_pf=%.3f rolling100_expectancy=%.6f "
            "segment=%s policy_action=%s",
            trade.get("trade_id", ""),
            symbol, side, regime,
            trade.get("learning_source", ""),
            outcome, net_pnl_pct,
            trade.get("mfe_pct", ""),
            trade.get("mae_pct", ""),
            self.lifetime_n, self.lifetime_pf, self.lifetime_expectancy,
            len(self.rolling20), rolling20_pf, rolling20_exp,
            len(self.rolling50), rolling50_pf, rolling50_exp,
            len(self.rolling100), rolling100_pf, rolling100_exp,
            segment_key,
            policy_action,
        )

        # P1.1AP-O1A: Track qualification evidence for future REAL_READY
        # Only count eligible canonical PAPER closes recorded after qualification epoch started
        self._try_increment_qualification(trade, net_pnl_pct, rolling100_pf, rolling100_exp)

        # Save state
        self._save_state()

    def _try_increment_qualification(
        self,
        trade: dict,
        net_pnl_pct: float,
        rolling100_pf: float,
        rolling100_exp: float,
    ) -> None:
        """P1.1AP-O1A1: Increment qualification evidence for post-epoch eligible closes only.

        Only eligible canonical PAPER closes opened after qualification_started_at
        contribute to future REAL_READY qualification.

        Eligible criteria:
        - Not D_NEG_EV_CONTROL
        - Not quarantined
        - Not shadow-only
        - Not timeout_no_price
        - Valid trade_id, symbol, outcome (WIN/LOSS/FLAT accepted)
        - Opened after qualification_started_at (provenance check)
        - Not already counted (deduplication)
        """
        # Check eligibility criteria (mirroring paper_trade_executor._is_eligible_canonical_paper_learning_trade)
        trade_id = trade.get("trade_id", "")
        symbol = trade.get("symbol", "UNKNOWN")
        outcome = trade.get("outcome", "FLAT")
        training_bucket = trade.get("training_bucket", "")
        entry_ts = trade.get("entry_ts") or trade.get("opened_at") or time.time()

        # D_NEG must not contribute
        if training_bucket == "D_NEG_EV_CONTROL":
            log.debug(
                "[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=d_neg_ev_control symbol=%s",
                trade_id, symbol
            )
            return

        # Quarantined excluded
        if trade.get("quarantined"):
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=quarantined", trade_id)
            return

        # Timeout_no_price excluded
        if trade.get("exit_reason") == "TIMEOUT_NO_PRICE":
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=timeout_no_price", trade_id)
            return

        # Shadow-only excluded
        if trade.get("learning_shadow_skip") or trade.get("shadow_only"):
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=shadow_only", trade_id)
            return

        # Valid fields required
        if not trade_id or symbol == "UNKNOWN":
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=invalid_fields", trade_id)
            return

        # Invalid outcome (only WIN/LOSS/FLAT are valid)
        if outcome not in ("WIN", "LOSS", "FLAT"):
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=invalid_outcome outcome=%s", trade_id, outcome)
            return

        # P1.1AP-O1A1: Require post-epoch opened trade provenance
        if entry_ts < self.qualification_started_at:
            log.debug(
                "[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=pre_epoch_or_unproven_open "
                "entry_ts=%.1f qualification_started_at=%.1f",
                trade_id, entry_ts, self.qualification_started_at
            )
            return

        # P1.1AP-O1A1: Check for deduplication (prevent double-counting on replay/restart)
        if any(e[4] == trade_id for e in self.qualification_window if len(e) > 4):
            log.debug("[PAPER_QUALIFICATION_SKIP] trade_id=%s reason=already_counted", trade_id)
            return

        # P1.1AP-O1A1: All checks passed: increment qualification
        # Store full segment_key for readiness metrics later
        segment_key = f"{symbol}:{trade.get('regime', 'UNKNOWN')}:{trade.get('side', 'UNKNOWN')}"
        self.qualification_n += 1
        entry = (net_pnl_pct, outcome, segment_key, time.time(), trade_id)
        self.qualification_window.append(entry)

        log.info(
            "[PAPER_QUALIFICATION_UPDATE] "
            "trade_id=%s symbol=%s outcome=%s qualification_n=%d rolling100_pf=%.3f "
            "rolling100_expectancy=%.6f operator_unlock=False",
            trade_id,
            symbol,
            outcome,
            self.qualification_n,
            rolling100_pf,
            rolling100_exp,
        )

    def _lifetime_entries(self) -> List:
        """Get all lifetime entries (rolling20+50+100 combined)."""
        # This is approximate; ideally we'd track all lifetime entries
        # For now, combine rolling windows (will miss oldest after rotate)
        return list(self.rolling100)

    def _compute_expectancy(self, net_pnl_pcts: List[float]) -> float:
        """Mean net PnL pct."""
        if not net_pnl_pcts:
            return 0.0
        return sum(net_pnl_pcts) / len(net_pnl_pcts)

    def _compute_pf(self, trades: List) -> float:
        """Profit factor: gross_wins / abs(gross_losses)."""
        gross_wins = sum(net for net, outcome in trades if outcome == "WIN")
        gross_losses = abs(sum(net for net, outcome in trades if outcome == "LOSS"))
        if gross_losses == 0:
            return 1.0 if gross_wins >= 0 else 0.0
        return gross_wins / gross_losses if gross_wins > 0 else 0.0

    def _compute_rolling_pf(self, window: deque) -> float:
        """PF for a rolling window."""
        if not window:
            return 1.0
        return self._compute_pf([(e[0], e[1]) for e in window])

    def _update_segment_policy(self, segment_key: str) -> None:
        """Adapt policy weight for segment based on rolling performance."""
        # Count closes in this segment in rolling100
        segment_closes = sum(1 for e in self.rolling100 if e[2] == segment_key)
        if segment_closes < 20:
            return  # Not enough data yet

        # Compute segment metrics
        segment_entries = [e for e in self.rolling100 if e[2] == segment_key]
        segment_pf = self._compute_pf([(e[0], e[1]) for e in segment_entries])
        segment_exp = self._compute_expectancy([e[0] for e in segment_entries])

        # Adaptive weighting
        if segment_pf < 0.80 and segment_exp < 0:
            # Losing segment: downweight
            new_weight = max(0.25, (self.segment_weights.get(segment_key, 1.0) - 0.1))
            self.segment_weights[segment_key] = new_weight
            action = "downweight_losing_segment"
        elif segment_pf > 1.10 and segment_exp > 0:
            # Winning segment: upweight
            new_weight = min(2.00, (self.segment_weights.get(segment_key, 1.0) + 0.1))
            self.segment_weights[segment_key] = new_weight
            action = "prefer_improving_segment"
        else:
            action = "continue_learning"

        if action != "continue_learning":
            log.info(
                "[PAPER_POLICY_ADAPTATION] "
                "segment=%s n=%d pf=%.3f expectancy=%.6f "
                "old_weight=%.2f new_weight=%.2f action=%s reason=post_cost_rolling_learning",
                segment_key,
                segment_closes,
                segment_pf,
                segment_exp,
                self.segment_weights.get(segment_key, 1.0),
                self.segment_weights.get(segment_key, 1.0),  # Will be updated above
                action
            )

    def _compute_policy_action(self, segment_key: str, total_closes: int) -> str:
        """Determine current policy action based on data.

        Phase 3A: Losing segment policy update.
        rolling20_n>=10 + rolling20_pf<=0.01 + rolling20_expectancy<=-0.10 => reduce_quota, cooldown 1800s
        rolling50_n>=30 + rolling50_pf<=0.10 + rolling50_expectancy<=-0.10 => cooldown, cooldown 3600s
        """
        if total_closes < 20:
            return "collect_bootstrap"

        # Phase 3A: Check for losing segments with rolling20/rolling50
        segment_closes_20 = [e for e in self.rolling20 if e[2] == segment_key]
        segment_closes_50 = [e for e in self.rolling50 if e[2] == segment_key]

        if len(segment_closes_20) >= 10:
            rolling20_pf = self._compute_rolling_pf(segment_closes_20)
            rolling20_exp = self._compute_expectancy([e[0] for e in segment_closes_20])

            if rolling20_pf <= 0.01 and rolling20_exp <= -0.10:
                old_action = "continue_learning"
                new_action = "reduce_quota"
                cooldown_s = 1800
                log.info(
                    "[PAPER_SEGMENT_POLICY_UPDATE] "
                    "segment=%s rolling20_n=%d rolling20_pf=%.4f rolling20_expectancy=%.6f "
                    "old_action=%s new_action=%s cooldown_s=%d reason=persistent_negative_edge",
                    segment_key, len(segment_closes_20), rolling20_pf, rolling20_exp,
                    old_action, new_action, cooldown_s
                )
                # Activate cooldown
                if not hasattr(self, '_segment_cooldowns'):
                    self._segment_cooldowns = {}
                self._segment_cooldowns[segment_key] = {
                    "active": True,
                    "activated_at": time.time(),
                    "cooldown_s": cooldown_s,
                    "cooldown_until": time.time() + cooldown_s
                }
                return new_action

        if len(segment_closes_50) >= 30:
            rolling50_pf = self._compute_rolling_pf(segment_closes_50)
            rolling50_exp = self._compute_expectancy([e[0] for e in segment_closes_50])

            if rolling50_pf <= 0.10 and rolling50_exp <= -0.10:
                old_action = "continue_learning"
                new_action = "cooldown"
                cooldown_s = 3600
                log.info(
                    "[PAPER_SEGMENT_POLICY_UPDATE] "
                    "segment=%s rolling50_n=%d rolling50_pf=%.4f rolling50_expectancy=%.6f "
                    "old_action=%s new_action=%s cooldown_s=%d reason=persistent_negative_edge",
                    segment_key, len(segment_closes_50), rolling50_pf, rolling50_exp,
                    old_action, new_action, cooldown_s
                )
                # Activate cooldown
                if not hasattr(self, '_segment_cooldowns'):
                    self._segment_cooldowns = {}
                self._segment_cooldowns[segment_key] = {
                    "active": True,
                    "activated_at": time.time(),
                    "cooldown_s": cooldown_s,
                    "cooldown_until": time.time() + cooldown_s
                }
                return new_action

        segment_closes = sum(1 for e in self.rolling100 if e[2] == segment_key)
        if segment_closes >= 20:
            weight = self.segment_weights.get(segment_key, 1.0)
            if weight < 0.50:
                return "downweight_losing_segment"
            elif weight > 1.50:
                return "prefer_improving_segment"

        return "continue_learning"

    def check_real_readiness(self) -> Dict:
        """Check if REAL_READY conditions are met.

        Returns:
            {
                'eligible': bool,
                'paper_closed': int,
                'qualification_n': int,
                'qualification_pf': float,
                'qualification_expectancy': float,
                'rolling100_pf': float,
                'rolling100_expectancy': float,
                'rolling100_net_pnl': float,
                'rolling20_pf': float,
                'rolling20_expectancy': float,
                'drawdown': float,
                'symbols': list,
                'max_segment_profit_share': float,
                'reason': str,
            }
        """
        paper_closed = len(self.rolling100)
        rolling100_pf = self._compute_rolling_pf(self.rolling100)
        rolling100_exp = self._compute_expectancy([e[0] for e in self.rolling100])
        rolling100_net = sum(e[0] for e in self.rolling100) / 100.0 if self.rolling100 else 0.0

        # P1.1AP-O1A1: Phase 3 - Compute recent behavior from qualification window only
        # Recent-20: last 20 entries from qualification_window (not rolling20 which is legacy all-time)
        qual_recent_20 = list(self.qualification_window)[-20:] if self.qualification_window else []
        rolling20_pf = self._compute_rolling_pf(qual_recent_20) if qual_recent_20 else 1.0
        rolling20_exp = self._compute_expectancy([e[0] for e in qual_recent_20]) if qual_recent_20 else 0.0

        # Extract symbols from qualification_window only (post-epoch eligible trades)
        symbols = list(set(e[2].split(":")[0] for e in self.qualification_window))

        # Segment concentration from qualification_window only
        max_segment_share = 0.0
        if self.qualification_window:
            for seg in set(e[2] for e in self.qualification_window):
                seg_profit = sum(e[0] for e in self.qualification_window if e[2] == seg and e[1] == "WIN")
                total_profit = sum(e[0] for e in self.qualification_window if e[1] == "WIN")
                if total_profit > 0:
                    max_segment_share = max(max_segment_share, seg_profit / total_profit)

        # P1.1AP-O1A: Qualification-based readiness using post-integration eligible closes only
        qualification_pf = self._compute_rolling_pf(self.qualification_window)
        qualification_exp = self._compute_expectancy([e[0] for e in self.qualification_window])

        reasons = []

        # Gate 1: qualification_n must be >= 100 (post-integration eligible closes)
        if self.qualification_n < 100:
            reasons.append(f"insufficient_post_integration_samples qualification_n={self.qualification_n}<100")

        # Gate 2: operator_unlock must be True
        if not self.operator_unlock:
            reasons.append(f"operator_unlock_required=True")

        # Gate 3: Qualification window metrics must pass gates
        if self.qualification_n >= 100:
            if qualification_pf < 1.20:
                reasons.append(f"qualification_pf={qualification_pf:.3f}<1.20")
            if qualification_exp <= 0:
                reasons.append(f"qualification_expectancy={qualification_exp:.6f}<=0")
            # Net PnL gate on qualification window
            qualification_net = sum(e[0] for e in self.qualification_window) / 100.0 if self.qualification_window else 0.0
            if qualification_net <= 0:
                reasons.append(f"qualification_net_pnl={qualification_net:.6f}<=0")

        # Gate 4: Rolling20 must remain healthy (recent behavior)
        # P1.1AP-O1A1: Only check rolling20 gates if we have 20+ post-epoch closes (meaningful recent window)
        if len(qual_recent_20) >= 20:
            if rolling20_pf <= 1.00:
                reasons.append(f"rolling20_pf={rolling20_pf:.3f}<=1.00")
            if rolling20_exp <= 0:
                reasons.append(f"rolling20_expectancy={rolling20_exp:.6f}<=0")

        # Gate 5: Diversification (symbols, segment concentration)
        if len(symbols) < 3:
            reasons.append(f"symbols={len(symbols)}<3")
        if max_segment_share > 0.60:
            reasons.append(f"max_segment_share={max_segment_share:.2f}>0.60")

        # Eligible only if all gates pass AND qualification >= 100 AND operator unlocked
        eligible = len(reasons) == 0 and self.qualification_n >= 100 and self.operator_unlock

        log.info(
            "[REAL_READINESS_CHECK] "
            "eligible=%s qualification_n=%d qualification_pf=%.3f "
            "qualification_expectancy=%.6f rolling20_pf=%.3f "
            "rolling20_expectancy=%.6f symbols=%d max_segment_profit_share=%.2f "
            "operator_unlock=%s %s",
            eligible, self.qualification_n, qualification_pf, qualification_exp,
            rolling20_pf, rolling20_exp, len(symbols), max_segment_share,
            self.operator_unlock,
            " ".join(reasons) if reasons else "reason=all_gates_pass"
        )

        # P1.1AP-O1A: REAL_READY remains locked until:
        # 1. qualification_n >= 100 (post-integration eligible closes)
        # 2. All PF/expectancy/net/rolling20/symbols/concentration gates pass
        # 3. operator_unlock is explicitly set to True
        # No automatic transition.

        return {
            "eligible": eligible,
            "paper_closed": paper_closed,
            "qualification_n": self.qualification_n,
            "qualification_pf": qualification_pf,
            "qualification_expectancy": qualification_exp,
            "rolling100_pf": rolling100_pf,
            "rolling100_expectancy": rolling100_exp,
            "rolling100_net_pnl": rolling100_net,
            "rolling20_pf": rolling20_pf,
            "rolling20_expectancy": rolling20_exp,
            "drawdown": 0.0,  # TODO: compute from trade data
            "symbols": symbols,
            "max_segment_profit_share": max_segment_share,
            "reason": " ".join(reasons) if reasons else "all_gates_pass",
        }

    def get_paper_policy_snapshot(
        self,
        symbol: Optional[str] = None,
        regime: Optional[str] = None,
        side: Optional[str] = None,
    ) -> Dict:
        """P1.1AP-O1: Expose safe read-only adaptive policy snapshot for PAPER decisions.

        Returns current rolling/segment metrics and qualification status.
        Safe defaults if state is absent/corrupt.

        Args:
            symbol: Optional symbol filter
            regime: Optional regime filter
            side: Optional side filter

        Returns:
            {
                'lifecycle': str,
                'lifetime_n': int,
                'lifetime_pf': float,
                'lifetime_expectancy': float,
                'rolling20_n': int,
                'rolling20_pf': float,
                'rolling20_expectancy': float,
                'rolling50_n': int,
                'rolling50_pf': float,
                'rolling50_expectancy': float,
                'rolling100_n': int,
                'rolling100_pf': float,
                'rolling100_expectancy': float,
                'segment_key': str or None (if filters provided),
                'segment_n': int,
                'segment_pf': float,
                'segment_expectancy': float,
                'segment_weight': float,
                'unresolved_anomalies': int,
                'qualification_n': int,
                'qualification_status': str,
            }
        """
        try:
            # Build segment key if filters provided
            segment_key = None
            if symbol and regime and side:
                segment_key = f"{symbol}:{regime}:{side}"

            # Compute rolling metrics
            rolling20_pf = self._compute_rolling_pf(self.rolling20)
            rolling50_pf = self._compute_rolling_pf(self.rolling50)
            rolling100_pf = self._compute_rolling_pf(self.rolling100)

            rolling20_exp = self._compute_expectancy([e[0] for e in self.rolling20])
            rolling50_exp = self._compute_expectancy([e[0] for e in self.rolling50])
            rolling100_exp = self._compute_expectancy([e[0] for e in self.rolling100])

            # Compute segment metrics if segment_key provided
            segment_n = 0
            segment_pf = 1.0
            segment_exp = 0.0
            segment_weight = 1.0

            if segment_key:
                segment_entries = [e for e in self.rolling100 if e[2] == segment_key]
                segment_n = len(segment_entries)
                if segment_entries:
                    segment_pf = self._compute_pf([(e[0], e[1]) for e in segment_entries])
                    segment_exp = self._compute_expectancy([e[0] for e in segment_entries])
                segment_weight = self.segment_weights.get(segment_key, 1.0)

            # Determine qualification status
            qualification_status = "unqualified"
            if len(self.rolling100) >= 100:
                qualification_status = "post_integration_qualifiable"
            elif len(self.rolling100) >= 20:
                qualification_status = "collecting_bootstrap"
            elif len(self.rolling100) > 0:
                qualification_status = "cold_start"

            return {
                "lifecycle": self.lifecycle,
                "lifetime_n": self.lifetime_n,
                "lifetime_pf": self.lifetime_pf,
                "lifetime_expectancy": self.lifetime_expectancy,
                "rolling20_n": len(self.rolling20),
                "rolling20_pf": rolling20_pf,
                "rolling20_expectancy": rolling20_exp,
                "rolling50_n": len(self.rolling50),
                "rolling50_pf": rolling50_pf,
                "rolling50_expectancy": rolling50_exp,
                "rolling100_n": len(self.rolling100),
                "rolling100_pf": rolling100_pf,
                "rolling100_expectancy": rolling100_exp,
                "segment_key": segment_key,
                "segment_n": segment_n,
                "segment_pf": segment_pf,
                "segment_expectancy": segment_exp,
                "segment_weight": segment_weight,
                "unresolved_anomalies": 0,  # TODO: track from learning updates
                "qualification_n": self.qualification_n,
                "qualification_status": qualification_status,
            }
        except Exception as e:
            log.warning("[PAPER_POLICY_SNAPSHOT_ERROR] %s", str(e))
            # Return safe defaults
            return {
                "lifecycle": "PAPER_COLLECTING",
                "lifetime_n": 0,
                "lifetime_pf": 1.0,
                "lifetime_expectancy": 0.0,
                "rolling20_n": 0,
                "rolling20_pf": 1.0,
                "rolling20_expectancy": 0.0,
                "rolling50_n": 0,
                "rolling50_pf": 1.0,
                "rolling50_expectancy": 0.0,
                "rolling100_n": 0,
                "rolling100_pf": 1.0,
                "rolling100_expectancy": 0.0,
                "segment_key": None,
                "segment_n": 0,
                "segment_pf": 1.0,
                "segment_expectancy": 0.0,
                "segment_weight": 1.0,
                "unresolved_anomalies": 0,
                "qualification_n": 0,
                "qualification_status": "unqualified",
            }

    def get_admission_controls_state(self) -> dict:
        """P1.1AP-O2: Get current admission control policy state (cooldowns)."""
        return self.paper_admission_controls

    def update_admission_controls_state(self, controls: dict) -> None:
        """P1.1AP-O2: Update admission control policy state and persist."""
        try:
            self.paper_admission_controls = controls
            self._save_state()
        except Exception as e:
            log.warning("[PAPER_ADMISSION_CONTROLS_SAVE] failed: %s", e)

    def save_state_sync(self) -> None:
        """P1.1AP-O2: Synchronously save state to disk (for cooldown updates)."""
        self._save_state()


# Module-level singleton
_learner = None

def get_learner() -> PaperAdaptiveLearning:
    """Get or create the singleton learner instance."""
    global _learner
    if _learner is None:
        _learner = PaperAdaptiveLearning()
    return _learner


def get_segment_metrics(symbol: str, regime: str, side: str) -> Optional[Dict]:
    """P1.1AP-O2 Fix D: Export segment metrics for admission safety checks.

    Returns segment n, pf, and expectancy for loss-triggered segment cooldown decisions.
    Safe to call from admission path with exception handling.

    Args:
        symbol, regime, side: Segment key components

    Returns:
        {
            'n': int (number of closes in rolling100),
            'pf': float (profit factor),
            'expectancy': float,
        }
        or None if not available
    """
    try:
        learner = get_learner()
        if not learner:
            return None

        segment_key = f"{symbol}:{regime}:{side}"

        # Compute metrics from rolling100 entries matching this segment
        matching = [e for e in learner.rolling100 if len(e) > 2 and e[2] == segment_key]
        if not matching:
            return None

        n = len(matching)
        wins = sum(1 for _, outcome, _, _ in matching if outcome == "WIN")
        losses = sum(1 for _, outcome, _, _ in matching if outcome == "LOSS")

        # Profit factor
        wins_pnl = sum(pnl for pnl, outcome, _, _ in matching if outcome == "WIN")
        losses_pnl = abs(sum(pnl for pnl, outcome, _, _ in matching if outcome == "LOSS"))
        pf = wins_pnl / losses_pnl if losses_pnl > 0 else (1.0 if wins_pnl > 0 else 0.0)

        # Expectancy
        expectancy = sum(pnl for pnl, _, _, _ in matching) / n if n > 0 else 0.0

        return {
            "n": n,
            "pf": pf,
            "expectancy": expectancy,
        }

    except Exception as e:
        log.debug("[PAPER_SEGMENT_METRICS_ERROR] symbol=%s regime=%s side=%s error=%s",
                  symbol, regime, side, str(e))
        return None

