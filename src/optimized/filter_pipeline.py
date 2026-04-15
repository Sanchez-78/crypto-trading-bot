from __future__ import annotations
from datetime import datetime
from src.optimized.bot_types import BotConfig, TradeSignal, CloseReason
from src.optimized.timing_filter import AdaptiveTimingFilter
from src.optimized.cooldown_manager import RegimeAdaptiveCooldown
from src.optimized.fast_fail_filters import AdaptiveVolumeFilter, AdaptiveSpreadFilter, MovementFilter
from src.optimized.obi_filter import adjusted_obi
from src.optimized.sl_tp_calculator import calculate_sl_tp
from src.optimized.mtf_filter import mtf_score, mtf_size
from src.optimized.signal_validator import SignalValidator

# PATCH: Learning + Rejection Fixes (Zero Bug Architecture - Feedback Loop)
from src.services.learning_system import LearningSystem, TradeOutcome
from src.services.daily_dd_halt_fix import GraduatedDrawdownController
from src.services.timing_fix import AggressiveTimingOverride, TimingDiagnostic
from src.services.skip_score_fix import AdaptiveScoreGate
from src.services.ofi_toxic_calibrate import CalibratedOFIFilter
from src.services.rejection_monitor import RejectionMonitor

# PATCH: Self-Healing System (Autonomous Failure Recovery)
from src.core.state_v2 import get_state_store
from src.core.self_heal import apply_position_floor, apply_position_cap

import logging
logger = logging.getLogger(__name__)


class SignalFilterPipeline:
    """Integrated filter pipeline — cheapest-to-expensive ordering.

    Order: PAIR_BLOCK(O1) → SPREAD(O1) → VOLUME_TOD(O1) → MOVEMENT(O1)
           → TIMING(ATR) → MTF(multi-TF) → OBI(orderbook)

    PATCH: Learning + Rejection Fixes
    - LearningSystem: outcome → 4 learners (feature, filter, strategy, conviction)
    - GraduatedDrawdownController: graduated tiers, not binary halt
    - AggressiveTimingOverride: aggressive windows, auto-calibration
    - AdaptiveScoreGate: rate-limited, no circular deadlock
    - CalibratedOFIFilter: self-tuning threshold
    - RejectionMonitor: detect filter dominance

    market dict keys required:
      bid, ask, volume, hour, candle_open_time, candle_open, candle_high, candle_low,
      atr_pct_history, bid_vols, ask_vols, prev_snapshots, data_1h, data_15m, data_5m
    """

    def __init__(self, cfg: BotConfig, candle_seconds: int = 3600, balance: float = 10000):
        self.cfg = cfg
        self.validator = SignalValidator(cfg)
        self.cooldown = RegimeAdaptiveCooldown(candle_seconds)
        self.timing = AdaptiveTimingFilter(candle_seconds)
        self.volume = AdaptiveVolumeFilter()
        self.spread = AdaptiveSpreadFilter()
        self.movement = MovementFilter()
        
        # PATCH: Learning + Rejection Fixes (FEEDBACK LOOP FIX)
        self.learning = LearningSystem()
        self.dd_ctrl = GraduatedDrawdownController(balance)
        self.timing_diag = TimingDiagnostic()
        self.timing_aggressive = AggressiveTimingOverride(candle_seconds, self.timing_diag)
        self.score_gate = AdaptiveScoreGate()
        self.ofi_cal = CalibratedOFIFilter()
        self.rej_mon = RejectionMonitor()

    def evaluate(
        self, signal: TradeSignal, market: dict, balance: float = None, learning_score: float = None, n_trades: int = 0
    ) -> tuple[str, dict]:
        """
        Evaluate signal through multi-stage filter pipeline.
        
        PATCH: Integrated learning + rejection fixes.
        
        Args:
            signal: Trade signal
            market: Market data dict
            balance: Current account balance (for DD control)
            learning_score: Learning system score (0-100)
            n_trades: Total trades so far (for adaptive thresholds)
        
        Returns: (action, details_dict)
        """
        # Validation
        ok, r = self.validator.validate(signal)
        if not ok:
            self.rej_mon.record("VALIDATION")
            return "VALIDATION", {"reason": r}

        # ────────────────────────────────────────────────────────────────────
        # PATCH FIX 1: Graduated Drawdown (DAILY_DD_HALT=383)
        # ────────────────────────────────────────────────────────────────────
        if balance is not None:
            ok, dd_sz, dd_r = self.dd_ctrl.check(balance)
            if not ok:
                self.rej_mon.record("DAILY_DD_HALT", signal.symbol)
                return "DAILY_DD_HALT", {"r": dd_r}
        else:
            dd_sz = 1.0

        # ────────────────────────────────────────────────────────────────────
        # Pair block
        # ────────────────────────────────────────────────────────────────────
        locked, msg = self.cooldown.is_locked(signal.symbol)
        if locked:
            self.rej_mon.record("PAIR_BLOCK")
            return "PAIR_BLOCK", {"msg": msg}

        # ────────────────────────────────────────────────────────────────────
        # Fast-fail filters (cheap checks first)
        # ────────────────────────────────────────────────────────────────────
        ok, msg = self.spread.check(market["bid"], market["ask"])
        if not ok:
            self.rej_mon.record("FAST_FAIL_SPREAD")
            return "FAST_FAIL_SPREAD", {"msg": msg}

        ok, msg = self.volume.check(market["volume"], market["hour"])
        if not ok:
            self.rej_mon.record("FAST_FAIL_VOLUME")
            return "FAST_FAIL_VOLUME", {"msg": msg}

        ok, msg = self.movement.check(
            market["candle_high"], market["candle_low"], signal.atr
        )
        if not ok:
            self.rej_mon.record("FAST_FAIL_MOVEMENT")
            return "FAST_FAIL_MOVEMENT", {"msg": msg}

        # ────────────────────────────────────────────────────────────────────
        # PATCH FIX 2: Aggressive Timing (TIMING=514)
        # ────────────────────────────────────────────────────────────────────
        t = self.timing_aggressive.evaluate(
            signal.timestamp,
            market["candle_open_time"],
            signal.entry_price,
            market["candle_open"],
            market["candle_high"],
            market["candle_low"],
            signal.atr,
            market.get("atr_pct_history", []),
            signal.symbol,
        )
        if t["action"] == "REJECT":
            self.rej_mon.record("TIMING", signal.symbol, market.get("hour", 0))
            return "TIMING", t
        
        timing_frac = t["frac"]
        timing_sz = t["size"]

        # ────────────────────────────────────────────────────────────────────
        # PATCH FIX 3: Score-based gating (SKIP_SCORE=73, rate-limited)
        # ────────────────────────────────────────────────────────────────────
        if learning_score is not None:
            self.score_gate.record_score(learning_score)
            skip, skip_r = self.score_gate.check(learning_score, n_trades)
            if skip:
                self.rej_mon.record("SKIP_SCORE")
                return "SKIP_SCORE", {"r": skip_r}

        # ────────────────────────────────────────────────────────────────────
        # Multi-timeframe check
        # ────────────────────────────────────────────────────────────────────
        score, mtf_msg = mtf_score(
            market["data_1h"],
            market["data_15m"],
            market["data_5m"],
            signal.direction.value,
        )
        mtf_sz = mtf_size(score)
        if mtf_sz == 0.0:
            self.rej_mon.record("MTF_LOW")
            return "MTF_LOW", {"score": score, "msg": mtf_msg}

        # ────────────────────────────────────────────────────────────────────
        # PATCH FIX 4: Calibrated OFI filter (OFI_TOXIC=24)
        # ────────────────────────────────────────────────────────────────────
        obi_r = adjusted_obi(
            market["bid_vols"], market["ask_vols"], market["prev_snapshots"]
        )
        toxic, tx_r = self.ofi_cal.check(obi_r["adj_obi"], obi_r["spoof"])
        if toxic:
            self.rej_mon.record("OFI_TOXIC")
            return "OFI_TOXIC", {"r": tx_r}

        # ────────────────────────────────────────────────────────────────────
        # ENTER: Signal passed all filters
        # ────────────────────────────────────────────────────────────────────
        stops = calculate_sl_tp(
            signal.direction.value,
            signal.entry_price,
            signal.atr,
            signal.atr_ratio,
            signal.symbol,
        )
        
        # Apply learned sizing (feature weights × learning position size)
        feature_sz = self.learning.pos_size(signal.conviction if hasattr(signal, 'conviction') else 0.6)
        final_sz = round(timing_sz * mtf_sz * obi_r["size"] * dd_sz * max(feature_sz, 0.1), 2)
        
        # PATCH: Apply self-healing constraints to position size
        # Get current state to check if system is in healing mode
        try:
            state_store = get_state_store()
            state = state_store.get_state()
            risk_mult = getattr(state, 'risk_multiplier', 1.0)  # Default: no reduction
            final_sz = round(final_sz * risk_mult, 2)
            
            if risk_mult < 1.0:
                logger.info(f"SAFE_MODE: Position size reduced by {(1-risk_mult)*100:.0f}% (risk_mult={risk_mult:.2f})")
        except Exception as e:
            logger.debug(f"Could not apply healing constraints: {e}")
        
        self.rej_mon.record_pass()
        
        return "ENTER", {
            "size": final_sz,
            "dd": dd_r if balance is not None else "n/a",
            "timing_frac": timing_frac,
            "mtf_score": score,
            "obi": obi_r["adj_obi"],
            "spoof": obi_r["spoof"],
            **stops,
        }

    def on_trade_closed(
        self,
        symbol: str,
        regime: str,
        pnl_pct: float,
        close_reason: CloseReason,
    ) -> None:
        self.cooldown.lock(symbol, regime, pnl_pct, close_reason)

    # ────────────────────────────────────────────────────────────────────────
    # PATCH: Broadcast outcome to learning system (FEEDBACK LOOP FIX)
    # ────────────────────────────────────────────────────────────────────────
    def broadcast_outcome(
        self,
        trade_id: str,
        symbol: str,
        direction: str,
        regime: str,
        won: bool,
        net_pnl_pct: float,
        duration_s: int,
        signal_features: dict = None,
        filters_passed: list = None,
        timing_frac: float = 0.0,
    ):
        """
        Broadcast trade outcome to learning system.
        Call this when a trade closes (after every exit).
        
        This triggers all 4 learners to update:
        - Feature learner
        - Filter learner
        - Strategy learner
        - Conviction calibrator
        """
        if signal_features is None:
            signal_features = {}
        if filters_passed is None:
            filters_passed = []
        
        outcome = TradeOutcome(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            regime=regime,
            won=won,
            net_pnl_pct=net_pnl_pct,
            duration_s=duration_s,
            features=signal_features,
            filters_passed=filters_passed,
            timing_frac=timing_frac,
            conviction=signal_features.get("conviction", 0.6),
            mtf_score=signal_features.get("mtf_score", 0.0),
            obi=signal_features.get("obi", 0.0),
            atr_regime=signal_features.get("atr_regime", "normal"),
        )
        
        # Broadcast to all learners
        self.learning.update(outcome)
        
        # Record result for timing calibration
        self.timing_aggressive.record_result(won)
        
        # Log outcome
        logger.info(
            f"OUTCOME: {symbol} {direction} {regime} won={won} pnl={net_pnl_pct:+.2f}% "
            f"duration={duration_s}s timing_frac={timing_frac:.2f}"
        )
