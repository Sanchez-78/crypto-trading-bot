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


class SignalFilterPipeline:
    """Integrated filter pipeline — cheapest-to-expensive ordering.

    Order: PAIR_BLOCK(O1) → SPREAD(O1) → VOLUME_TOD(O1) → MOVEMENT(O1)
           → TIMING(ATR) → MTF(multi-TF) → OBI(orderbook)

    market dict keys required:
      bid, ask, volume, hour, candle_open_time, candle_open, candle_high, candle_low,
      atr_pct_history, bid_vols, ask_vols, prev_snapshots, data_1h, data_15m, data_5m
    """

    def __init__(self, cfg: BotConfig, candle_seconds: int = 3600):
        self.cfg = cfg
        self.validator = SignalValidator(cfg)
        self.cooldown = RegimeAdaptiveCooldown(candle_seconds)
        self.timing = AdaptiveTimingFilter(candle_seconds)
        self.volume = AdaptiveVolumeFilter()
        self.spread = AdaptiveSpreadFilter()
        self.movement = MovementFilter()

    def evaluate(
        self, signal: TradeSignal, market: dict
    ) -> tuple[str, dict]:
        ok, r = self.validator.validate(signal)
        if not ok:
            return "VALIDATION", {"reason": r}

        locked, msg = self.cooldown.is_locked(signal.symbol)
        if locked:
            return "PAIR_BLOCK", {"msg": msg}

        ok, msg = self.spread.check(market["bid"], market["ask"])
        if not ok:
            return "FAST_FAIL_SPREAD", {"msg": msg}

        ok, msg = self.volume.check(market["volume"], market["hour"])
        if not ok:
            return "FAST_FAIL_VOLUME", {"msg": msg}

        ok, msg = self.movement.check(
            market["candle_high"], market["candle_low"], signal.atr
        )
        if not ok:
            return "FAST_FAIL_MOVEMENT", {"msg": msg}

        timing = self.timing.evaluate(
            signal.timestamp,
            market["candle_open_time"],
            signal.entry_price,
            market["candle_open"],
            market["candle_high"],
            market["candle_low"],
            signal.atr,
            market["atr_pct_history"],
        )
        if timing["action"] == "REJECT":
            return "TIMING", {"regime": timing["regime"]}

        score, mtf_msg = mtf_score(
            market["data_1h"], market["data_15m"], market["data_5m"],
            signal.direction.value,
        )
        mtf_sz = mtf_size(score)
        if mtf_sz == 0.0:
            return "MTF_LOW", {"score": score, "msg": mtf_msg}

        obi_r = adjusted_obi(
            market["bid_vols"], market["ask_vols"], market["prev_snapshots"]
        )
        if obi_r["quality"] in ("LOW", "NEUTRAL"):
            return "OBI_WEAK", obi_r

        stops = calculate_sl_tp(
            signal.direction.value,
            signal.entry_price,
            signal.atr,
            signal.atr_ratio,
            signal.symbol,
        )
        return "ENTER", {
            "size": round(timing["size"] * mtf_sz * obi_r["size"], 2),
            "regime": timing["regime"],
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
