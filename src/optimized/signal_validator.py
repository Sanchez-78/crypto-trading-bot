from __future__ import annotations
from src.optimized.bot_types import BotConfig, TradeSignal, Direction


class SignalValidator:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg

    def validate(self, s: TradeSignal) -> tuple[bool, str]:
        for ok, r in [
            self._sl_tp_equal(s),
            self._sl_dist(s),
            self._sides(s),
            self._rr(s),
            self._obi(s),
            self._prob(s),
            self._atr(s),
        ]:
            if not ok:
                return False, r
        return True, "OK"

    def _sl_tp_equal(self, s: TradeSignal) -> tuple[bool, str]:
        if abs(s.sl_price - s.tp_price) < s.entry_price * 0.0001:
            return False, f"SL==TP({s.sl_price})"
        return True, ""

    def _sl_dist(self, s: TradeSignal) -> tuple[bool, str]:
        d = abs(s.entry_price - s.sl_price) / s.entry_price
        if d < self.cfg.min_sl_dist_pct:
            return False, f"SL tight:{d * 100:.3f}%"
        if d > self.cfg.max_sl_dist_pct:
            return False, f"SL wide:{d * 100:.3f}%"
        return True, ""

    def _sides(self, s: TradeSignal) -> tuple[bool, str]:
        if s.direction == Direction.LONG:
            if s.sl_price >= s.entry_price:
                return False, "LONG:SL>=entry"
            if s.tp_price <= s.entry_price:
                return False, "LONG:TP<=entry"
        else:
            if s.sl_price <= s.entry_price:
                return False, "SHORT:SL<=entry"
            if s.tp_price >= s.entry_price:
                return False, "SHORT:TP>=entry"
        return True, ""

    def _rr(self, s: TradeSignal) -> tuple[bool, str]:
        denom = abs(s.entry_price - s.sl_price)
        rr = abs(s.entry_price - s.tp_price) / denom if denom > 0 else 0
        if rr < self.cfg.min_rr:
            return False, f"R/R{rr:.2f}<{self.cfg.min_rr}"
        if rr > self.cfg.max_rr:
            return False, f"R/R{rr:.2f}>{self.cfg.max_rr}"
        return True, ""

    def _obi(self, s: TradeSignal) -> tuple[bool, str]:
        if s.direction == Direction.LONG and s.obi < self.cfg.min_obi_long:
            return False, f"LONG OBI={s.obi:.1f}"
        if s.direction == Direction.SHORT and s.obi > self.cfg.max_obi_short:
            return False, f"SHORT OBI={s.obi:.1f}"
        return True, ""

    def _prob(self, s: TradeSignal) -> tuple[bool, str]:
        if s.probability < 0.52:
            return False, f"P={s.probability:.0%}"
        return True, ""

    def _atr(self, s: TradeSignal) -> tuple[bool, str]:
        if s.atr <= 0:
            return True, ""
        sl_atr = abs(s.entry_price - s.sl_price) / s.atr
        if sl_atr < 1.5:
            return False, f"SL={sl_atr:.2f}xATR<1.5"
        return True, ""
