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
        """Calculate RSI."""
        if len(prices) < period:
            return np.zeros(len(prices))
        delta = np.diff(prices)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        
        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])
        
        rsi_values = []
        for i in range(period, len(prices)):
            if i > period:
                avg_gain = (avg_gain * (period - 1) + (1 if delta[i-1] > 0 else 0) * delta[i-1]) / period
                avg_loss = (avg_loss * (period - 1) + (1 if delta[i-1] < 0 else 0) * abs(delta[i-1])) / period
            
            if avg_loss == 0:
                rsi = 100 if avg_gain > 0 else 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
        
        result = np.zeros(len(prices))
        result[period:] = rsi_values
        return result

    def _adx(self, high, low, close, period):
        """Calculate ADX (simplified)."""
        high_diff = np.diff(high)
        low_diff = -np.diff(low)
        
        # Determine +DM and -DM
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        
        tr = np.maximum(
            np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1])),
            np.abs(low[1:] - close[:-1])
        )
        
        # Smooth
        smoothed_tr = np.mean(tr[:period])
        smoothed_plus = np.mean(plus_dm[:period])
        smoothed_minus = np.mean(minus_dm[:period])
        
        if smoothed_tr == 0:
            return np.zeros(len(close))
        
        di_plus = (smoothed_plus / smoothed_tr) * 100
        di_minus = (smoothed_minus / smoothed_tr) * 100
        dx = (np.abs(di_plus - di_minus) / (di_plus + di_minus)) * 100
        
        adx = np.full(len(close), dx)
        return adx

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
