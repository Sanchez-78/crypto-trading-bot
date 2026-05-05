"""
PATCH: Strategy Executor — Apply strategy DNA to generate trading signals.

Converts strategy DNA parameters into actual trading signals by:
1. Computing technical indicators (EMA, RSI, ADX, BB)
2. Checking entry conditions
3. Calculating stop-loss and take-profit levels
4. Sizing positions based on DNA risk settings

DNA parameters used:
- ema_fast, ema_slow, ema_trend: Moving average crossovers
- rsi_period, rsi_oversold, rsi_overbought: Momentum filtering
- adx_period, adx_threshold: Trend strength filtering
- bb_period, bb_std_dev: Volatility filtering
- atr_mult_sl, atr_mult_tp: Risk/reward sizing
- risk_pct, kelly_fraction: Position sizing
- trailing_stop, trail_mult: Trade management
- uptrend_bias, downtrend_bias, ranging_bias: Regime adaptation
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


class StrategyExecutor:
    """Apply strategy DNA to generate trading signals."""
    
    def __init__(self, strategy_dna):
        """
        Initialize executor with strategy DNA.
        
        Args:
            strategy_dna: StrategyDNA object with parameters
        """
        self.dna = strategy_dna

    def evaluate(self, market_data):
        """
        Evaluate market conditions and generate trading signals.
        
        Args:
            market_data: dict with OHLCV data
                - close: list of closing prices
                - high: list of high prices
                - low: list of low prices
                - volume: list of volumes
                - atr: current ATR value
                - regime: market regime (UPTREND, DOWNTREND, RANGING)
                
        Returns:
            dict with:
            - entry_signal: "LONG", "SHORT", or None
            - entry_price: suggested entry price
            - stop_loss: stop loss price
            - take_profit: take profit price
            - position_size: suggested size (0-1 multiplier)
            - confidence: signal strength (0-1)
        """
        
        try:
            close = np.array(market_data.get('close', [])[-50:])  # Last 50 candles
            high = np.array(market_data.get('high', [])[-50:])
            low = np.array(market_data.get('low', [])[-50:])
            atr = market_data.get('atr', 0.0)
            regime = market_data.get('regime', 'RANGING')
            
            if len(close) < max(self.dna.ema_fast, self.dna.ema_slow, self.dna.rsi_period):
                return self._no_signal()
            
            # ────────────────────────────────────────────────────────────
            # Calculate technical indicators
            # ────────────────────────────────────────────────────────────
            ema_fast = self._ema(close, self.dna.ema_fast)
            ema_slow = self._ema(close, self.dna.ema_slow)
            ema_trend = self._ema(close, self.dna.ema_trend)
            
            rsi = self._rsi(close, self.dna.rsi_period)
            adx = self._adx(high, low, close, self.dna.adx_period)
            
            bb_upper, bb_lower, bb_mid = self._bollinger(close, self.dna.bb_period, self.dna.bb_std_dev)
            
            # ────────────────────────────────────────────────────────────
            # Entry logic: EMA crossover + RSI + ADX + Trend filter
            # ────────────────────────────────────────────────────────────
            
            # EMA crossover
            ema_cross_up = (ema_fast[-2] <= ema_slow[-2]) and (ema_fast[-1] > ema_slow[-1])
            ema_cross_down = (ema_fast[-2] >= ema_slow[-2]) and (ema_fast[-1] < ema_slow[-1])
            
            # Trend filter
            in_uptrend = close[-1] > ema_trend[-1]
            in_downtrend = close[-1] < ema_trend[-1]
            
            # Momentum filter
            rsi_oversold = rsi[-1] < self.dna.rsi_oversold
            rsi_overbought = rsi[-1] > self.dna.rsi_overbought
            
            # Trend strength filter
            trend_strong = adx[-1] > self.dna.adx_threshold
            
            # ────────────────────────────────────────────────────────────
            # LONG signal
            # ────────────────────────────────────────────────────────────
            long_signal = (
                ema_cross_up and
                in_uptrend and
                (rsi_oversold or rsi[-1] < 50) and
                trend_strong
            )
            
            # SHORT signal
            short_signal = (
                ema_cross_down and
                in_downtrend and
                (rsi_overbought or rsi[-1] > 50) and
                trend_strong
            )
            
            if not (long_signal or short_signal):
                return self._no_signal()
            
            # ────────────────────────────────────────────────────────────
            # Calculate exit levels (SL/TP)
            # ────────────────────────────────────────────────────────────
            current_price = close[-1]
            
            if long_signal:
                entry_price = current_price
                stop_loss = entry_price - (atr * self.dna.atr_mult_sl)
                take_profit = entry_price + (atr * self.dna.atr_mult_tp)
                
                confidence = self._calculate_confidence(
                    regime=regime,
                    rsi=rsi[-1],
                    adx=adx[-1],
                    is_long=True,
                    dna=self.dna
                )
                
                return {
                    'entry_signal': 'LONG',
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'position_size': confidence * self.dna.kelly_fraction,
                    'confidence': confidence,
                    'regime': regime,
                    'atr': atr,
                }
            
            else:  # short_signal
                entry_price = current_price
                stop_loss = entry_price + (atr * self.dna.atr_mult_sl)
                take_profit = entry_price - (atr * self.dna.atr_mult_tp)
                
                confidence = self._calculate_confidence(
                    regime=regime,
                    rsi=rsi[-1],
                    adx=adx[-1],
                    is_long=False,
                    dna=self.dna
                )
                
                return {
                    'entry_signal': 'SHORT',
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'position_size': confidence * self.dna.kelly_fraction,
                    'confidence': confidence,
                    'regime': regime,
                    'atr': atr,
                }
        
        except Exception as e:
            logger.debug(f"Strategy evaluation error: {e}")
            return self._no_signal()

    def _no_signal(self):
        """Return no-signal response."""
        return {
            'entry_signal': None,
            'entry_price': 0.0,
            'stop_loss': 0.0,
            'take_profit': 0.0,
            'position_size': 0.0,
            'confidence': 0.0,
        }

    def _ema(self, prices, period):
        """Calculate EMA."""
        if len(prices) < 2:
            return prices
        alpha = 2.0 / (period + 1)
        ema = [prices[0]]
        for p in prices[1:]:
            ema.append((p * alpha) + (ema[-1] * (1 - alpha)))
        return np.array(ema)

    def _rsi(self, prices, period):
        """Calculate RSI using Wilder's smoothing. BUG-010 fix."""
        if len(prices) < period + 1:
            return np.zeros(len(prices))
        delta = np.diff(prices)

        avg_gain = np.mean(np.maximum(delta[:period], 0))
        avg_loss = np.mean(np.maximum(-delta[:period], 0))

        rsi_values = []
        for i in range(period, len(prices)):
            if i > period:
                gain = max(delta[i - 1], 0)
                loss = max(-delta[i - 1], 0)
                avg_gain = (avg_gain * (period - 1) + gain) / period
                avg_loss = (avg_loss * (period - 1) + loss) / period

            if avg_loss == 0:
                rsi = 100.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
            rsi_values.append(rsi)

        result = np.full(len(prices), 50.0)
        result[period:] = rsi_values
        return result

    def _adx(self, high, low, close, period):
        """Calculate ADX with proper Wilder smoothing per bar. BUG-006 fix."""
        high_diff = np.diff(high)
        low_diff = -np.diff(low)

        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)

        tr = np.maximum(
            np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1])),
            np.abs(low[1:] - close[:-1])
        )

        n = len(tr)
        if n < period:
            return np.zeros(len(close))

        atr_w = np.zeros(n)
        pdm_w = np.zeros(n)
        mdm_w = np.zeros(n)
        atr_w[period - 1] = np.sum(tr[:period])
        pdm_w[period - 1] = np.sum(plus_dm[:period])
        mdm_w[period - 1] = np.sum(minus_dm[:period])
        for i in range(period, n):
            atr_w[i] = atr_w[i - 1] - (atr_w[i - 1] / period) + tr[i]
            pdm_w[i] = pdm_w[i - 1] - (pdm_w[i - 1] / period) + plus_dm[i]
            mdm_w[i] = mdm_w[i - 1] - (mdm_w[i - 1] / period) + minus_dm[i]

        with np.errstate(divide='ignore', invalid='ignore'):
            di_plus  = np.where(atr_w > 0, (pdm_w / atr_w) * 100, 0.0)
            di_minus = np.where(atr_w > 0, (mdm_w / atr_w) * 100, 0.0)
            denom    = di_plus + di_minus
            dx       = np.where(denom > 0, (np.abs(di_plus - di_minus) / denom) * 100, 0.0)

        adx_w = np.zeros(n)
        start = 2 * period - 2
        if start < n:
            adx_w[start] = np.mean(dx[period - 1:2 * period - 1])
            for i in range(start + 1, n):
                adx_w[i] = (adx_w[i - 1] * (period - 1) + dx[i]) / period

        result = np.zeros(len(close))
        result[1:] = adx_w
        return result

    def _bollinger(self, prices, period, std_dev):
        """Calculate Bollinger Bands."""
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, lower, sma

    def _calculate_confidence(self, regime, rsi, adx, is_long, dna):
        """Calculate signal confidence (0-1) based on indicators and regime."""
        # Base confidence from ADX (higher trend strength = higher confidence)
        base_confidence = min(adx / 50, 1.0)  # Normalized to [0, 1]
        
        # RSI adjustment
        if is_long:
            rsi_adj = 1.0 - (rsi / 100) if rsi < 50 else 0.5
        else:
            rsi_adj = (rsi / 100) if rsi > 50 else 0.5
        
        # Regime adjustment
        if regime == "UPTREND":
            regime_mult = dna.uptrend_bias if is_long else (1.0 / dna.uptrend_bias)
        elif regime == "DOWNTREND":
            regime_mult = dna.downtrend_bias if not is_long else (1.0 / dna.downtrend_bias)
        else:  # RANGING
            regime_mult = dna.ranging_bias
        
        confidence = base_confidence * rsi_adj * regime_mult
        return min(max(confidence, 0.1), 1.0)

    def __repr__(self):
        return f"Executor({self.dna})"
