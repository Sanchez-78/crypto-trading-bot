"""
PATCH: State Builder — Convert market data to RL state vector.

Transforms raw market indicators and system state into normalized
8-feature vector used by DQN agent.

State Vector [8 features]:
  [0] RSI (0-1): Momentum indicator (normalized 0-100)
  [1] ADX (0-1): Trend strength (normalized 0-50)
  [2] MACD: Moving average convergence divergence
  [3] EMA diff: Fast EMA - Slow EMA (normalized)
  [4] BB width: Bollinger band width (volatility)
  [5] Learning health (0-1): Learning system confidence
  [6] Expected value (0-1): Normalized EV estimate
  [7] Win rate (0-1): Historical win rate
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


class StateBuilder:
    """Build RL state vectors from market and system data."""
    
    def __init__(self):
        """Initialize state builder with normalization parameters."""
        # Normalization ranges (used to convert raw values to [0, 1])
        self.rsi_range = (0, 100)
        self.adx_range = (0, 50)
        self.macd_range = (-0.05, 0.05)
        self.ema_diff_range = (-1.0, 1.0)
        self.bb_width_range = (0, 0.1)
        self.ev_range = (-0.01, 0.01)

    def build(self, market_data: dict, learning_state: dict = None) -> np.ndarray:
        """
        Build 8-feature state vector.
        
        Args:
            market_data: dict with indicators
                - rsi: RSI value (0-100)
                - adx: ADX value (0-50)
                - macd: MACD value
                - ema_fast: Fast EMA
                - ema_slow: Slow EMA
                - bb_width: Bollinger Band width
                - current_price: Current price (for normalization)
            
            learning_state: dict with learning system state
                - health: Learning health (0-1)
                - ev: Expected value
                - wr: Win rate (0-1)
                
        Returns:
            Normalized numpy array of shape (8,)
        """
        try:
            # Default learning state if not provided
            if learning_state is None:
                learning_state = {
                    'health': 0.5,
                    'ev': 0.0,
                    'wr': 0.5,
                }
            
            # Extract and normalize features
            features = [
                # [0] RSI (0-1)
                self._normalize(
                    market_data.get('rsi', 50),
                    self.rsi_range[0],
                    self.rsi_range[1]
                ),
                
                # [1] ADX (0-1)
                self._normalize(
                    market_data.get('adx', 25),
                    self.adx_range[0],
                    self.adx_range[1]
                ),
                
                # [2] MACD (0-1)
                self._normalize(
                    market_data.get('macd', 0),
                    self.macd_range[0],
                    self.macd_range[1]
                ),
                
                # [3] EMA Difference (0-1)
                self._normalize(
                    market_data.get('ema_fast', 0) - market_data.get('ema_slow', 0),
                    self.ema_diff_range[0],
                    self.ema_diff_range[1]
                ),
                
                # [4] Bollinger Band Width (0-1)
                self._normalize(
                    market_data.get('bb_width', 0.05),
                    self.bb_width_range[0],
                    self.bb_width_range[1]
                ),
                
                # [5] Learning Health (0-1) - already normalized
                max(0, min(1, learning_state.get('health', 0.5))),
                
                # [6] Expected Value (0-1)
                self._normalize(
                    learning_state.get('ev', 0),
                    self.ev_range[0],
                    self.ev_range[1]
                ),
                
                # [7] Win Rate (0-1) - already normalized
                max(0, min(1, learning_state.get('wr', 0.5))),
            ]
            
            # Convert to numpy array and clip to [0, 1]
            state = np.array(features, dtype=np.float32)
            state = np.clip(state, 0, 1)
            
            return state
            
        except Exception as e:
            logger.warning(f"State building error: {e}; returning neutral state")
            return np.array([0.5] * 8, dtype=np.float32)

    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """
        Normalize value to [0, 1] range.
        
        Args:
            value: Value to normalize
            min_val: Minimum value in range
            max_val: Maximum value in range
            
        Returns:
            Normalized value (0-1)
        """
        if max_val == min_val:
            return 0.5
        
        normalized = (value - min_val) / (max_val - min_val)
        return max(0, min(1, normalized))

    def __repr__(self):
        return "StateBuilder(features=8)"


# Action definitions
ACTIONS = {
    0: 'HOLD',
    1: 'LONG',
    2: 'SHORT',
}

ACTION_NAMES = {v: k for k, v in ACTIONS.items()}


def action_to_name(action_id: int) -> str:
    """Convert action ID to name."""
    return ACTIONS.get(action_id, 'UNKNOWN')


def name_to_action(action_name: str) -> int:
    """Convert action name to ID."""
    return ACTION_NAMES.get(action_name, 0)
