import random
import math
from collections import defaultdict

print("🧠 CONTEXTUAL BANDIT LOADED")

# =========================
# CONFIG
# =========================
ACTIONS = ["BUY", "SELL", "HOLD"]

epsilon = 0.2  # exploration
decay = 0.9995
min_epsilon = 0.05

# Q-table: context → action → value
Q = defaultdict(lambda: {a: 0.0 for a in ACTIONS})
N = defaultdict(lambda: {a: 0 for a in ACTIONS})

total_trades = 0
wins = 0
losses = 0


# =========================
# CONTEXT DISCRETIZATION
# =========================
def get_context(features):
    if not features:
        return "unknown"

    rsi = int(features.get("rsi", 50) // 10)  # 0-10 bucket
    ema = 1 if features.get("ema_short", 0) > features.get("ema_long", 0) else 0
    vol = int(features.get("volatility", 0) * 1000)

    return f"r{rsi}_e{ema}_v{vol}"


# =========================
# ACTION SELECTION
# =========================
def select_action(features):
    global epsilon

    context = get_context(features)

    # explore
    if random.random() < epsilon:
        action = random.choice(ACTIONS)
        return action

    # exploit
    q_vals = Q[context]
    action = max(q_vals, key=q_vals.get)

    return action


# =========================
# UPDATE (LEARNING)
# =========================
def update(features, action, reward):
    global epsilon, total_trades, wins, losses

    context = get_context(features)

    N[context][action] += 1
    n = N[context][action]

    # incremental mean
    Q[context][action] += (reward - Q[context][action]) / n

    # stats
    total_trades += 1
    if reward > 0:
        wins += 1
    else:
        losses += 1

    # decay exploration
    epsilon = max(min_epsilon, epsilon * decay)


# =========================
# METRICS
# =========================
def get_metrics():
    if total_trades == 0:
        return {}

    winrate = wins / total_trades

    return {
        "trades": total_trades,
        "winrate": winrate,
        "epsilon": epsilon
    }


# =========================
# READY CHECK
# =========================
def is_ready():
    m = get_metrics()
    return m.get("trades", 0) > 50 and m.get("winrate", 0) > 0.55