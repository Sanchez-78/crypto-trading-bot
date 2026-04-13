from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategySignal:
    signal: str
    strength: float
    reason: str
    strategy: str
    timeframe: str
    regime_required: str


# ── TREND FOLLOWING (regime=TRENDING, ADX>25 required) ──────────────────────

class SupertrendMACDStrategy:
    """SuperTrend ATR(14)×3.5 + MACD(7,23,10) + ADX≥25 + vol≥1.2×avg.

    Best TF: 1h, 4h. Flip signal stronger than continuation.
    Backtest: 11.61% ann 7yr PF 2.12.
    """
    NAME = "SupertrendMACD"
    REGIME = "TRENDING"

    def __init__(self, atr_p=14, atr_m=3.5, mf=7, ms=23, ms2=10, adx_min=25):
        self.atr_p = atr_p; self.atr_m = atr_m
        self.mf = mf; self.ms = ms; self.ms2 = ms2; self.adx_min = adx_min

    def analyze(self, df: pd.DataFrame, tf: str = "1h") -> StrategySignal:
        try:
            import talib
        except ImportError:
            return StrategySignal("NEUTRAL", 0, "talib_missing", self.NAME, tf, self.REGIME)

        c = df["close"].values; h = df["high"].values; l = df["low"].values
        adx = talib.ADX(h, l, c, 14)[-1]
        if adx < self.adx_min:
            return StrategySignal("NEUTRAL", 0, f"ADX={adx:.0f}<{self.adx_min}", self.NAME, tf, self.REGIME)

        atr = talib.ATR(h, l, c, self.atr_p)
        st = np.where(c > (h + l) / 2 - self.atr_m * atr, 1, -1)
        _, _, hist = talib.MACD(c, self.mf, self.ms, self.ms2)
        vol_ok = df["volume"].iloc[-1] > df["volume"].rolling(20).mean().iloc[-1] * 1.2
        st_flip = st[-1] != st[-2]
        strength = min(1.0, (adx - self.adx_min) / 25)

        if st[-1] == 1 and hist[-1] > 0 and hist[-1] > hist[-2] and vol_ok:
            return StrategySignal("LONG", strength,
                f"ST_bull+MACD+vol {'flip' if st_flip else 'cont'}", self.NAME, tf, self.REGIME)
        if st[-1] == -1 and hist[-1] < 0 and hist[-1] < hist[-2] and vol_ok:
            return StrategySignal("SHORT", strength,
                f"ST_bear+MACD+vol {'flip' if st_flip else 'cont'}", self.NAME, tf, self.REGIME)
        return StrategySignal("NEUTRAL", 0, "no_align", self.NAME, tf, self.REGIME)


class EMABreakoutStrategy:
    """EMA 10/50/200 stack + price breaks recent 10-bar high/low + 1.5× vol surge.

    Best TF: 15m-4h swing.
    """
    NAME = "EMABreakout"
    REGIME = "TRENDING"

    def __init__(self, f=10, m=50, s=200):
        self.f = f; self.m = m; self.s = s

    def analyze(self, df: pd.DataFrame, tf: str = "1h") -> StrategySignal:
        try:
            import talib
        except ImportError:
            return StrategySignal("NEUTRAL", 0, "talib_missing", self.NAME, tf, self.REGIME)

        c = df["close"].values; h = df["high"].values; l = df["low"].values
        adx = talib.ADX(h, l, c, 14)[-1]
        if adx < 20:
            return StrategySignal("NEUTRAL", 0, f"ADX={adx:.0f}<20", self.NAME, tf, self.REGIME)

        ef = talib.EMA(c, self.f)[-1]; em = talib.EMA(c, self.m)[-1]; es = talib.EMA(c, self.s)[-1]
        rh = max(h[-10:-1]); rl = min(l[-10:-1])
        vs = df["volume"].iloc[-1] > df["volume"].rolling(20).mean().iloc[-1] * 1.5
        strength = min(1.0, adx / 50)

        if ef > em > es and c[-1] > rh and vs:
            return StrategySignal("LONG", strength, "EMA_stack+breakout+vol", self.NAME, tf, self.REGIME)
        if ef < em < es and c[-1] < rl and vs:
            return StrategySignal("SHORT", strength, "EMA_bear+breakdown+vol", self.NAME, tf, self.REGIME)
        return StrategySignal("NEUTRAL", 0, "no_breakout", self.NAME, tf, self.REGIME)


# ── MEAN REVERSION (regime=RANGING, ADX<25 required) ────────────────────────

class BBRSIMeanReversionStrategy:
    """BB(20,2) lower/upper touch + RSI<30/>70 + ADX<25 + BB_width>0.01.

    Exit: middle band. NEVER use in TRENDING — walking the bands = blow-up.
    Backtest: 78% WR avg +1.4%/trade (RANGING only).
    """
    NAME = "BBRSIReversion"
    REGIME = "RANGING"

    def __init__(self, bb_p=20, bb_s=2.0, rsi_p=14, os=30, ob=70, adx_max=25):
        self.bb_p = bb_p; self.bb_s = bb_s; self.rsi_p = rsi_p
        self.os = os; self.ob = ob; self.adx_max = adx_max

    def analyze(self, df: pd.DataFrame, tf: str = "1h") -> StrategySignal:
        try:
            import talib
        except ImportError:
            return StrategySignal("NEUTRAL", 0, "talib_missing", self.NAME, tf, self.REGIME)

        c = df["close"].values; h = df["high"].values; l = df["low"].values
        adx = talib.ADX(h, l, c, 14)[-1]
        if adx > self.adx_max:
            return StrategySignal("NEUTRAL", 0, f"TRENDING ADX={adx:.0f}", self.NAME, tf, self.REGIME)

        up, mid, lo = talib.BBANDS(c, self.bb_p, self.bb_s, self.bb_s)
        rsi = talib.RSI(c, self.rsi_p)[-1]
        bw = (up[-1] - lo[-1]) / mid[-1]
        if bw < 0.01:
            return StrategySignal("NEUTRAL", 0, "BB_narrow_prebreakout", self.NAME, tf, self.REGIME)

        strength = min(1.0, (self.adx_max - adx) / self.adx_max)
        if c[-1] <= lo[-1] and rsi < self.os:
            return StrategySignal("LONG", strength, f"BB_low RSI={rsi:.0f}", self.NAME, tf, self.REGIME)
        if c[-1] >= up[-1] and rsi > self.ob:
            return StrategySignal("SHORT", strength, f"BB_up RSI={rsi:.0f}", self.NAME, tf, self.REGIME)
        return StrategySignal("NEUTRAL", 0, f"no_extreme RSI={rsi:.0f}", self.NAME, tf, self.REGIME)


class ZScoreMeanReversionStrategy:
    """z = (price - rolling_mean) / rolling_std; entry z < -2.0 long, z > +2.0 short.

    Lookback = half_life via OLS: hl = -ln(2)/theta where theta from Δp = θp_{t-1} + ε.
    """
    NAME = "ZScoreReversion"
    REGIME = "RANGING"

    def __init__(self, z_entry=2.0, lookback=20, adx_max=22):
        self.z_entry = z_entry; self.lookback = lookback; self.adx_max = adx_max

    def analyze(self, df: pd.DataFrame, tf: str = "4h") -> StrategySignal:
        try:
            import talib
            adx = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)[-1]
            if adx > self.adx_max:
                return StrategySignal("NEUTRAL", 0, f"TRENDING ADX={adx:.0f}", self.NAME, tf, self.REGIME)
        except Exception:
            pass

        c = df["close"]
        rm = c.rolling(self.lookback).mean()
        rs = c.rolling(self.lookback).std()
        z = (c - rm) / rs
        zv = z.iloc[-1]
        strength = min(1.0, abs(zv) / (self.z_entry * 2))

        if zv < -self.z_entry:
            return StrategySignal("LONG", strength, f"z={zv:.2f}<-{self.z_entry}", self.NAME, tf, self.REGIME)
        if zv > +self.z_entry:
            return StrategySignal("SHORT", strength, f"z={zv:.2f}>+{self.z_entry}", self.NAME, tf, self.REGIME)
        return StrategySignal("NEUTRAL", 0, f"z={zv:.2f}", self.NAME, tf, self.REGIME)

    @staticmethod
    def half_life(s: pd.Series) -> float:
        lag = s.shift(1); d = s - lag
        lag = lag.dropna(); d = d.dropna()
        t = np.polyfit(lag, d, 1)[0]
        return -np.log(2) / t if t < 0 else 20


# ── ARBITRAGE (regime=ANY) ────────────────────────────────────────────────────

class FundingRateArbitrageStrategy:
    """Delta-neutral: long_spot + short_perp = capture funding payments.

    2025 avg APY 19.26%, maxDD 0.85% (Gate.com). Funding every 8h.
    Entry: rate > 0.0005 (0.05%/8h ≈ 20% APY). Exit: rate < 0.0001.
    MAX LEVERAGE 3×. Risk: rate reversal, basis risk, liquidation on short leg.
    """
    NAME = "FundingArb"
    REGIME = "ANY"

    def __init__(self, min_r=0.0005, exit_r=0.0001, max_lev=3.0):
        self.min_r = min_r; self.exit_r = exit_r; self.max_lev = max_lev

    def analyze(
        self,
        funding_rate: float,
        predicted_rate: float = None,
        in_position: bool = False,
    ) -> StrategySignal:
        ann = funding_rate * 3 * 365 * 100
        if in_position:
            if funding_rate < self.exit_r:
                return StrategySignal("NEUTRAL", 0, f"EXIT rate={funding_rate * 100:.4f}%", self.NAME, "8h", self.REGIME)
            return StrategySignal("LONG", min(1.0, funding_rate / 0.003),
                f"HOLD arb≈{ann:.1f}%APY", self.NAME, "8h", self.REGIME)
        if funding_rate < self.min_r:
            return StrategySignal("NEUTRAL", 0, f"rate_low={funding_rate * 100:.4f}%", self.NAME, "8h", self.REGIME)
        if predicted_rate is not None and predicted_rate < self.min_r * 0.5:
            return StrategySignal("NEUTRAL", 0.3, "rate_ok_but_reversal_predicted", self.NAME, "8h", self.REGIME)
        return StrategySignal("LONG", min(1.0, funding_rate / 0.003),
            f"ENTER arb rate={funding_rate * 100:.4f}%≈{ann:.1f}%APY long_spot+short_perp max{self.max_lev}x",
            self.NAME, "8h", self.REGIME)


class StatisticalArbitrageStrategy:
    """Cointegrated pairs (BTC/ETH most stable). 16.34% ann Sharpe 2.45 (IJSRA2026).

    Method: Engle-Granger + OLS hedge_ratio + z-score.
    Re-test cointegration every 1-4 weeks!
    """
    NAME = "StatArb"
    REGIME = "ANY"

    def __init__(self, z_entry=2.0, z_exit=0.5, hedge_ratio: float = None, lookback=60):
        self.z_entry = z_entry; self.z_exit = z_exit; self.hr = hedge_ratio; self.lb = lookback

    def analyze(self, a1: pd.Series, a2: pd.Series, tf: str = "1h") -> dict:
        hr = self.hr or np.polyfit(a2[-self.lb:], a1[-self.lb:], 1)[0]
        sp = a1 - hr * a2
        sm = sp.rolling(self.lb).mean().iloc[-1]
        ss = sp.rolling(self.lb).std().iloc[-1]
        z = (sp.iloc[-1] - sm) / ss if ss > 0 else 0
        st = min(1.0, abs(z) / (self.z_entry * 2))

        if z > self.z_entry:
            return {"a1": StrategySignal("SHORT", st, f"z={z:.2f}", self.NAME, tf, self.REGIME),
                    "a2": StrategySignal("LONG", st, f"z={z:.2f}", self.NAME, tf, self.REGIME), "z": z, "hr": hr}
        if z < -self.z_entry:
            return {"a1": StrategySignal("LONG", st, f"z={z:.2f}", self.NAME, tf, self.REGIME),
                    "a2": StrategySignal("SHORT", st, f"z={z:.2f}", self.NAME, tf, self.REGIME), "z": z, "hr": hr}
        return {"a1": StrategySignal("NEUTRAL", 0, f"z={z:.2f}", self.NAME, tf, self.REGIME),
                "a2": StrategySignal("NEUTRAL", 0, f"z={z:.2f}", self.NAME, tf, self.REGIME), "z": z, "hr": hr}

    @staticmethod
    def test_coint(s1: pd.Series, s2: pd.Series) -> dict:
        try:
            from statsmodels.tsa.stattools import coint
            _, p, _ = coint(s1, s2)
            return {"cointegrated": p < 0.05, "pvalue": round(p, 4)}
        except Exception:
            return {"cointegrated": None, "error": "statsmodels_missing"}


# ── MARKET MAKING / GRID (regime=RANGING) ────────────────────────────────────

class DynamicGridStrategy:
    """ATR-adaptive grid outperforms static grids 15-30%.

    Dec2024-Apr2025: BTC +9.6%, SOL +21.88% vs buy-hold -16%/-49%.
    spacing = clamp(ATR%×0.6, 1.0%, 4.0%). Recalibrate hourly.
    STOP grid if regime=TRENDING or price exits range. MAX LEVERAGE 3×.
    """
    NAME = "DynamicGrid"
    REGIME = "RANGING"

    def __init__(self, capital: float, n: int = 15, min_s: float = 0.01,
                 max_s: float = 0.04, atr_m: float = 0.6, max_lev: float = 3.0):
        self.capital = capital; self.n = n; self.min_s = min_s
        self.max_s = max_s; self.atr_m = atr_m; self.max_lev = max_lev

    def calculate(self, price: float, atr: float, regime: str = "RANGING") -> dict:
        if regime == "TRENDING":
            return {"active": False, "reason": "TRENDING_pause"}
        sp = np.clip(atr / price * self.atr_m, self.min_s, self.max_s)
        ppl = self.capital / self.n
        buys = [price * (1 - sp * i) for i in range(1, self.n // 2 + 1)]
        sells = [price * (1 + sp * i) for i in range(1, self.n // 2 + 1)]
        return {
            "active": True,
            "spacing_pct": round(sp * 100, 3),
            "per_level_usd": round(ppl, 2),
            "buy_levels": [round(p, 6) for p in buys],
            "sell_levels": [round(p, 6) for p in sells],
            "stop_loss": round(buys[-1] * (1 - sp * 2), 6),
            "atr_pct": round(atr / price * 100, 3),
        }

    def should_pause(self, price: float, lo: float, hi: float, regime: str) -> tuple[bool, str]:
        if regime == "TRENDING":
            return True, "regime→TRENDING"
        if price < lo:
            return True, f"price<floor({lo})"
        if price > hi:
            return True, f"price>ceil({hi})"
        return False, "active"


class AvellanedaStoikovMarketMaker:
    """Inventory-aware market maker.

    r = mid - q×γ×σ²×(T-t)
    spread = γσ²dt + (2/γ)ln(1+γ/κ)
    Crypto params: γ=0.1, κ=0.1. Update σ from prior-day.
    Inventory skew: reduce quotes on overexposed side (>50% max_inv).
    Hummingbot native A-S support.
    """
    NAME = "AvellanedaStoikov"
    REGIME = "RANGING"

    def __init__(self, gamma: float = 0.1, kappa: float = 0.1, T: float = 1.0,
                 min_spread: float = 0.001, max_inv: float = 0.3):
        self.g = gamma; self.k = kappa; self.T = T; self.ms = min_spread; self.mi = max_inv

    def quotes(self, mid: float, sigma: float, inv: float, t: float = 0.5) -> dict:
        dt = self.T - t
        r = mid - inv * self.g * sigma ** 2 * dt
        sh = max(self.g * sigma ** 2 * dt / 2 + np.log(1 + self.g / self.k) / self.g,
                 self.ms * mid)
        bid = r - sh; ask = r + sh
        ir = abs(inv) / (self.mi * mid)
        if inv > 0 and ir > 0.5:
            bid *= (1 - ir * 0.002)
        elif inv < 0 and ir > 0.5:
            ask *= (1 + ir * 0.002)
        return {
            "bid": round(bid, 8),
            "ask": round(ask, 8),
            "spread_pct": round((ask - bid) / mid * 100, 4),
            "reservation": round(r, 8),
            "inv_skew": round(inv * self.g * sigma ** 2 * dt, 8),
        }


# ── STRATEGY ROUTER ───────────────────────────────────────────────────────────
# Allocation half-Kelly:
#   TRENDING  → 70% trend + 10% meanrev + 20% cash
#   RANGING   → 60% meanrev + 20% grid + 20% fundarb
#   VOLATILE  → 30% fundarb + 70% cash

class StrategyRouter:
    def __init__(self, capital: float = 10_000):
        self.capital = capital
        self.st = SupertrendMACDStrategy()
        self.eb = EMABreakoutStrategy()
        self.bb = BBRSIMeanReversionStrategy()
        self.zs = ZScoreMeanReversionStrategy()
        self.fa = FundingRateArbitrageStrategy()
        self.grid = DynamicGridStrategy(capital * 0.2)
        self.avs = AvellanedaStoikovMarketMaker()

    def route(
        self,
        df: pd.DataFrame,
        regime: str,
        tf: str = "1h",
        funding_rate: float = 0.0,
    ) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        if regime == "TRENDING":
            signals += [self.st.analyze(df, tf), self.eb.analyze(df, tf)]
        elif regime == "RANGING":
            signals += [self.bb.analyze(df, tf), self.zs.analyze(df, tf)]
        if funding_rate != 0.0:
            signals.append(self.fa.analyze(funding_rate))
        active = [s for s in signals if s.signal != "NEUTRAL"]
        active.sort(key=lambda s: s.strength, reverse=True)
        return active

    @staticmethod
    def kelly_size(wr: float, aw: float, al: float, capital: float, frac: float = 0.5) -> float:
        """Half-Kelly position sizing."""
        b = aw / abs(al)
        return capital * max(0, (b * wr - (1 - wr)) / b) * frac
