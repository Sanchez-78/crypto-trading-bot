"""
PATCH: Strategy DNA — Genetic code for trading strategies.

Each strategy has DNA (parameters) that can mutate and evolve.
DNA includes:
- Technical indicator thresholds (EMA, RSI, ADX, BB)
- Risk/reward ratios (TP, SL multipliers)
- Position sizing parameters
- Regime-specific adaptations

Mutation occurs randomly to create diversity.
Selection occurs based on fitness (EV + stability).
"""

import random


class StrategyDNA:
    """Complete genetic code for a trading strategy."""
    
    def __init__(self):
        # ────────────────────────────────────────────────────────────────
        # Moving Average parameters
        # ────────────────────────────────────────────────────────────────
        self.ema_fast = random.randint(5, 20)      # 5-20 bars
        self.ema_slow = random.randint(20, 100)    # 20-100 bars
        self.ema_trend = random.randint(50, 200)   # 50-200 bars (long-term context)
        
        # ────────────────────────────────────────────────────────────────
        # Momentum filters
        # ────────────────────────────────────────────────────────────────
        self.rsi_period = random.randint(7, 21)          # 7-21 bars
        self.rsi_oversold = random.uniform(20, 40)       # 20-40 = oversold threshold
        self.rsi_overbought = random.uniform(60, 80)     # 60-80 = overbought threshold
        
        self.adx_period = random.randint(7, 21)          # 7-21 bars
        self.adx_threshold = random.uniform(15, 35)      # 15-35 = trend strength
        
        # ────────────────────────────────────────────────────────────────
        # Volatility and support/resistance
        # ────────────────────────────────────────────────────────────────
        self.bb_period = random.randint(15, 30)          # 15-30 bars
        self.bb_std_dev = random.uniform(1.5, 3.0)       # 1.5-3.0 std devs
        
        self.atr_mult_sl = random.uniform(0.5, 1.5)      # SL = Entry ± ATR × this
        self.atr_mult_tp = random.uniform(0.8, 2.5)      # TP = Entry ± ATR × this
        
        # ────────────────────────────────────────────────────────────────
        # Position sizing
        # ────────────────────────────────────────────────────────────────
        self.risk_pct = random.uniform(0.01, 0.05)       # 1-5% risk per trade
        self.kelly_fraction = random.uniform(0.25, 1.0)  # 0.25-1.0 of kelly
        
        # ────────────────────────────────────────────────────────────────
        # Trade management
        # ────────────────────────────────────────────────────────────────
        self.trailing_stop = random.choice([True, False]) # Enable trailing stop
        self.trail_mult = random.uniform(1.0, 3.0)        # Trail distance = ATR × this
        self.max_hold_bars = random.randint(10, 100)      # Force close after N bars
        
        # ────────────────────────────────────────────────────────────────
        # Regime adaptation
        # ────────────────────────────────────────────────────────────────
        self.uptrend_bias = random.uniform(0.8, 1.5)      # Signal strength in uptrend
        self.downtrend_bias = random.uniform(0.8, 1.5)    # Signal strength in downtrend
        self.ranging_bias = random.uniform(0.5, 1.0)      # Signal strength in range
        
        # ────────────────────────────────────────────────────────────────
        # Evolution control
        # ────────────────────────────────────────────────────────────────
        self.mutation_rate = 0.15  # 15% chance to mutate each attribute

    def mutate(self):
        """Randomly mutate DNA parameters (create offspring variation)."""
        for attr in dir(self):
            # Skip private/magic attributes and mutation_rate itself
            if attr.startswith('_') or attr == 'mutation_rate':
                continue
            
            # Random chance to mutate this parameter
            if random.random() < self.mutation_rate:
                try:
                    value = getattr(self, attr)
                    mutated = self._mutate_value(value)
                    setattr(self, attr, mutated)
                except (AttributeError, TypeError):
                    pass  # Skip non-numeric attributes

    def _mutate_value(self, value):
        """Apply random perturbation to a value."""
        if isinstance(value, int):
            # Integer: scale by ±20%
            scaled = value * random.uniform(0.8, 1.2)
            return max(1, int(scaled))
        elif isinstance(value, float):
            # Float: scale by ±20%
            return value * random.uniform(0.8, 1.2)
        elif isinstance(value, bool):
            # Boolean: flip with 20% chance
            return not value if random.random() < 0.2 else value
        return value

    def crossover(self, other):
        """
        Create offspring from two parent DNA.
        (Optional feature for more sophisticated evolution)
        """
        child = StrategyDNA()
        for attr in vars(self):
            if random.random() < 0.5:
                setattr(child, attr, getattr(self, attr))
            else:
                setattr(child, attr, getattr(other, attr))
        return child

    def to_dict(self):
        """Serialize to dict for logging/storage."""
        return {k: v for k, v in vars(self).items() if not k.startswith('_')}

    def __repr__(self):
        return f"DNA(ema={self.ema_fast}/{self.ema_slow}, rsi={self.rsi_period}, adx={self.adx_threshold:.1f})"
