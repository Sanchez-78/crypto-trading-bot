"""
V5.1 Anti-Idle Reward System.

Key fixes:
1. Reward execution activity (not just profit)
2. Penalize inactivity cycles
3. Reward quick decisions
4. Penalize timeout-based exits
5. Avoid HOLD collapse

Previously: RL learned "do nothing = best reward"
Now: Activity + small profit bonuses encourage exploration
"""


def compute_reward(signal, features, result, profit, trade_duration_minutes=None, idle_cycles=0, exit_reason=None):
    """
    Compute reward with anti-idle incentives.

    Args:
        signal: "BUY" | "SELL" | "HOLD"
        features: dict of feature signals
        result: "WIN" | "LOSS" | "BREAK_EVEN"
        profit: P&L as decimal (e.g., 0.005 for +0.5%)
        trade_duration_minutes: How long trade was held
        idle_cycles: Number of no-trade cycles
        exit_reason: "TP" | "SL" | "TIMEOUT" | "STAGNATION" | etc.
    """
    reward = 0.0

    # ═════════════════════════════════════════════════════════════════════════════
    # 1. BASE PROFIT (fundamental)
    # ═════════════════════════════════════════════════════════════════════════════
    reward += profit * 100  # Scale to percentage

    # ═════════════════════════════════════════════════════════════════════════════
    # 2. ANTI-IDLE: Reward execution activity
    # ═════════════════════════════════════════════════════════════════════════════
    if signal in ["BUY", "SELL"]:
        reward += 0.0002  # Small bonus for taking action

    # Penalize inactivity severely (the core problem in V5.0)
    if idle_cycles > 50:
        reward -= 0.0005 * min(idle_cycles / 50, 10)  # Scales with stagnation

    # ═════════════════════════════════════════════════════════════════════════════
    # 3. QUICK DECISIONS: Reward fast execution
    # ═════════════════════════════════════════════════════════════════════════════
    if trade_duration_minutes is not None and trade_duration_minutes < 10:
        reward += 0.0001  # Bonus for quick scalps

    # ═════════════════════════════════════════════════════════════════════════════
    # 4. EXIT LOGIC FIX: Penalize timeout dependency
    # ═════════════════════════════════════════════════════════════════════════════
    if exit_reason == "TIMEOUT":
        reward -= 0.0003  # Penalize passive timeout exits
    elif exit_reason in ["TP", "SL", "TRAILING_STOP"]:
        reward += 0.0001  # Reward active exit decisions

    # ═════════════════════════════════════════════════════════════════════════════
    # 5. LOSS PENALTY
    # ═════════════════════════════════════════════════════════════════════════════
    if result == "LOSS":
        reward *= 1.3  # Penalty for losses

    # ═════════════════════════════════════════════════════════════════════════════
    # 6. TREND ALIGNMENT
    # ═════════════════════════════════════════════════════════════════════════════
    trend = features.get("trend", "NEUTRAL")
    if trend == "BULL" and signal == "BUY":
        reward += 0.5
    elif trend == "BEAR" and signal == "SELL":
        reward += 0.5
    elif signal in ["BUY", "SELL"]:
        reward -= 0.2  # Against-trend penalty

    # ═════════════════════════════════════════════════════════════════════════════
    # 7. VOLATILITY CONTEXT
    # ═════════════════════════════════════════════════════════════════════════════
    vol = features.get("volatility", "MEDIUM")
    if vol == "HIGH":
        reward *= 1.2  # Boost in volatile environments
    elif vol == "LOW":
        reward *= 0.8  # Reduce reward in low-vol (fewer edges)

    # ═════════════════════════════════════════════════════════════════════════════
    # 8. REGIME ALIGNMENT
    # ═════════════════════════════════════════════════════════════════════════════
    regime = features.get("regime", "RANGING")
    if regime == "BULL_TREND" and signal == "BUY":
        reward += 0.5
    elif regime == "BEAR_TREND" and signal == "SELL":
        reward += 0.5
    elif regime == "RANGING" and signal in ["BUY", "SELL"]:
        reward -= 0.1  # Slight penalty for trending in ranging market

    # ═════════════════════════════════════════════════════════════════════════════
    # 9. HOLD PENALTY (CRITICAL FIX)
    # ═════════════════════════════════════════════════════════════════════════════
    if signal == "HOLD":
        reward -= 0.5  # Strong penalty to prevent HOLD collapse

    return round(reward, 6)