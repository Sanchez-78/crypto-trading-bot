from __future__ import annotations
import numpy as np
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class KronosSignal:
    symbol: str
    timeframe: str
    timestamp: datetime
    direction: str
    direction_prob: float
    signal_strength: float
    expected_volatility: float
    volatility_elevated: bool
    forecast_closes: list
    confidence_interval_pct: float
    trade_recommended: bool
    reason: str


class KronosAgent:
    """Optional Kronos AI signal layer.

    AAAI2026 foundation model, 12B+ K-lines, 45 exchanges.
    install: pip install torch transformers huggingface_hub
    download: snapshot_download("NeoQuasar/Kronos-small") + "NeoQuasar/Kronos-Tokenizer-base"

    evaluator_check: blocks trade if Kronos strongly disagrees
    (dir_prob > 0.65, opposite direction).
    """

    SIGNAL_THRESHOLD = 0.62
    DIRECTION_THRESHOLD = 0.55
    MIN_CANDLES = 64
    FORECAST_LEN = 24

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        model_size: str = "small",
        mock: bool = False,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.model_size = model_size
        self.mock = mock
        self._loaded = False
        self.predictor = None

    def load(self) -> bool:
        if self.mock:
            self._loaded = True
            return True
        try:
            from model import Kronos, KronosTokenizer, KronosPredictor
            tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
            mdl = Kronos.from_pretrained(f"NeoQuasar/Kronos-{self.model_size}")
            self.predictor = KronosPredictor(mdl, tok)
            self._loaded = True
            return True
        except Exception as e:
            logger.error("Kronos load: %s", e)
            return False

    def analyze(self, df) -> Optional[KronosSignal]:
        if not self._loaded or len(df) < self.MIN_CANDLES:
            return None
        df = df.copy()
        df.columns = df.columns.str.lower()
        try:
            fc = self._forecast(df)
            d, p = self._direction(df, fc)
            v, ve = self._volatility(df, fc)
            ci = self._ci(fc)
            st = self._strength(p, ve, ci)
            rec = d != "NEUTRAL" and st >= self.SIGNAL_THRESHOLD
            return KronosSignal(
                self.symbol, self.timeframe, datetime.now(),
                d, p, st, v, ve, fc["closes"], ci, rec,
                f"{d} st={st:.2f} p={p:.0%}",
            )
        except Exception as e:
            logger.error("Kronos analyze: %s", e)
            return None

    def _forecast(self, df) -> dict:
        if self.mock:
            lc = df["close"].iloc[-1]
            hv = df["close"].pct_change().std()
            rng = np.random.default_rng(42)
            n = 50
            s = np.zeros((n, self.FORECAST_LEN))
            for i in range(n):
                p = [lc]
                for _ in range(self.FORECAST_LEN):
                    p.append(p[-1] * (1 + rng.normal(0, hv)))
                s[i] = p[1:]
            return {
                "closes_samples": s,
                "closes": s.mean(0).tolist(),
                "highs": (s * 1.003).mean(0).tolist(),
                "lows": (s * 0.997).mean(0).tolist(),
            }
        ohlcv = df[["open", "high", "low", "close", "volume"]].values[-512:]
        raw = self.predictor.predict(ohlcv, pred_len=self.FORECAST_LEN)
        return {
            "closes_samples": raw[:, :, 3],
            "closes": raw[:, :, 3].mean(0).tolist(),
            "highs": raw[:, :, 1].mean(0).tolist(),
            "lows": raw[:, :, 2].mean(0).tolist(),
        }

    def _direction(self, df, fc) -> tuple[str, float]:
        lc = df["close"].iloc[-1]
        finals = fc["closes_samples"][:, -1]
        pu = (finals > lc).mean()
        if pu > self.DIRECTION_THRESHOLD:
            return "LONG", float(pu)
        if 1 - pu > self.DIRECTION_THRESHOLD:
            return "SHORT", float(1 - pu)
        return "NEUTRAL", max(float(pu), float(1 - pu))

    def _volatility(self, df, fc) -> tuple[float, bool]:
        hv = df["close"].pct_change().tail(100).std() * 100
        hi = np.array(fc.get("highs", fc["closes"]))
        lo = np.array(fc.get("lows", fc["closes"]))
        pv = float(((hi - lo) / lo * 100).mean()) if lo.any() else hv
        return pv, pv > hv * 1.25

    def _ci(self, fc) -> float:
        s = fc["closes_samples"][:, -1]
        return float(
            (np.percentile(s, 95) - np.percentile(s, 5)) / np.mean(s) * 100
        )

    def _strength(self, p: float, ve: bool, ci: float) -> float:
        return float(np.clip(
            ((p - 0.5) / 0.5 * 0.6 + max(0.0, 1.0 - ci / 20.0) * 0.3) * (0.7 if ve else 1.0),
            0, 1,
        ))

    def evaluator_check(self, direction: str, df) -> tuple[bool, str]:
        s = self.analyze(df)
        if s is None:
            return True, "unavailable"
        if s.direction != "NEUTRAL" and s.direction != direction and s.direction_prob > 0.65:
            return False, f"KRONOS_BLOCK:{s.direction} p={s.direction_prob:.0%}"
        if s.signal_strength < 0.55:
            return True, f"KRONOS_WARN:weak({s.signal_strength:.2f})"
        return True, f"KRONOS_OK:{s.direction}({s.signal_strength:.2f})"
