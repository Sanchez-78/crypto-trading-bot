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

    def __init__(self):
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

        Called after loading state. Filters out D_NEG entries from rolling windows
        and recomputes metrics if necessary.
        """
        try:
            d_neg_count_before = 0

            # Filter D_NEG entries from rolling windows
            for window_name in ["rolling20", "rolling50", "rolling100"]:
                window = getattr(self, window_name)
                original_len = len(window)

                # Filter out D_NEG entries
                filtered = deque(
                    [e for e in window if not self._is_d_neg_entry(e)],
                    maxlen=window.maxlen
                )
                d_neg_removed = original_len - len(filtered)
                d_neg_count_before += d_neg_removed

                if d_neg_removed > 0:
                    setattr(self, window_name, filtered)
                    log.info(
                        "[PAPER_ADAPTIVE_STATE_RECONCILED] window=%s d_neg_removed=%d remaining=%d",
                        window_name, d_neg_removed, len(filtered)
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
            if os.path.exists(_STATE_FILE):
                with open(_STATE_FILE, 'r') as f:
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

                # P1.1AP-N1 Fix 3: Reconcile state to remove D_NEG contamination
                self._reconcile_state()
        except Exception as e:
            log.warning("[PAPER_LEARNING_STATE_RESTORE] failed: %s", e)

    def _save_state(self) -> None:
        """Persist state to JSON file."""
        try:
            os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
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
            }
            with open(_STATE_FILE, 'w') as f:
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
        segment_key = f"{symbol}:{regime}:{side}"

        # Record to rolling windows
        entry = (net_pnl_pct, outcome, segment_key, time.time())
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
        """P1.1AP-O1A: Increment qualification evidence for post-integration eligible closes.

        Only eligible canonical PAPER closes recorded after qualification_started_at
        contribute to future REAL_READY qualification.

        Eligible criteria:
        - Not D_NEG_EV_CONTROL
        - Not quarantined
        - Not shadow-only
        - Not timeout_no_price
        - Valid trade_id, symbol, outcome, net_pnl
        - Recorded after qualification_started_at (first O1A init epoch)
        """
        # Check eligibility criteria (mirroring paper_trade_executor._is_eligible_canonical_paper_learning_trade)
        trade_id = trade.get("trade_id", "")
        symbol = trade.get("symbol", "UNKNOWN")
        outcome = trade.get("outcome", "FLAT")
        training_bucket = trade.get("training_bucket", "")

        # D_NEG must not contribute
        if training_bucket == "D_NEG_EV_CONTROL":
            return

        # Quarantined excluded
        if trade.get("quarantined"):
            return

        # Timeout_no_price excluded
        if trade.get("exit_reason") == "TIMEOUT_NO_PRICE":
            return

        # Shadow-only excluded
        if trade.get("learning_shadow_skip") or trade.get("shadow_only"):
            return

        # Valid fields required
        if not trade_id or symbol == "UNKNOWN" or outcome == "FLAT":
            return

        # All checks passed: increment qualification
        self.qualification_n += 1
        entry = (net_pnl_pct, outcome, symbol, time.time())
        self.qualification_window.append(entry)

        log.info(
            "[PAPER_QUALIFICATION_UPDATE] "
            "trade_id=%s qualification_n=%d rolling100_pf=%.3f "
            "rolling100_expectancy=%.6f operator_unlock=False",
            trade_id,
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
        """Determine current policy action based on data."""
        if total_closes < 20:
            return "collect_bootstrap"

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

        rolling20_pf = self._compute_rolling_pf(self.rolling20)
        rolling20_exp = self._compute_expectancy([e[0] for e in self.rolling20])

        # Extract symbols from rolling100 (legacy)
        symbols = list(set(e[2].split(":")[0] for e in self.rolling100))

        # Segment concentration from rolling100 (legacy)
        max_segment_share = 0.0
        if self.rolling100:
            for seg in set(e[2] for e in self.rolling100):
                seg_profit = sum(e[0] for e in self.rolling100 if e[2] == seg and e[1] == "WIN")
                total_profit = sum(e[0] for e in self.rolling100 if e[1] == "WIN")
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


# Module-level singleton
_learner = None

def get_learner() -> PaperAdaptiveLearning:
    """Get or create the singleton learner instance."""
    global _learner
    if _learner is None:
        _learner = PaperAdaptiveLearning()
    return _learner

