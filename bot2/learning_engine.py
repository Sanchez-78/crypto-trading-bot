import math
from collections import defaultdict


class LearningEngine:

    def __init__(self):
        self.bandit = defaultdict(lambda: {"n": 0, "reward": 0})
        self.conf_calibration = {}
        self.strategy_blame = defaultdict(float)
        self.regime_perf = defaultdict(list)

    # =========================
    # 🧠 BANDIT UPDATE
    # =========================
    def update_bandit(self, trades):
        total = sum(v["n"] for v in self.bandit.values()) + 1

        for t in trades:
            key = f"{t['regime']}_{t['strategy']}_{t['meta']['feature_bucket']}"
            reward = t["evaluation"]["profit"]

            self.bandit[key]["n"] += 1
            self.bandit[key]["reward"] += reward

    def compute_scores(self):
        scores = {}

        total = sum(v["n"] for v in self.bandit.values()) + 1

        for k, v in self.bandit.items():
            if v["n"] == 0:
                continue

            avg = v["reward"] / v["n"]
            bonus = math.sqrt(math.log(total) / v["n"])

            scores[k] = avg + bonus

        return scores

    # =========================
    # 🎯 CONFIDENCE CALIBRATION
    # =========================
    def calibrate_confidence(self, trades):
        buckets = defaultdict(lambda: {"wins": 0, "total": 0})

        for t in trades:
            c = round(t["meta"]["confidence_used"], 1)
            buckets[c]["total"] += 1

            if t["evaluation"]["result"] == "WIN":
                buckets[c]["wins"] += 1

        for c, d in buckets.items():
            if d["total"] > 5:
                self.conf_calibration[c] = d["wins"] / d["total"]

    # =========================
    # ⚖️ STRATEGY BLAME
    # =========================
    def update_strategy_blame(self, trades):
        for t in trades:
            self.strategy_blame[t["strategy"]] += t["evaluation"]["profit"]

    # =========================
    # 🌍 REGIME VALIDATION
    # =========================
    def update_regime_perf(self, trades):
        for t in trades:
            self.regime_perf[t["regime"]].append(t["evaluation"]["profit"])

    # =========================
    # 📊 EXPORT CONFIG
    # =========================
    def export_config(self):
        return {
            "bandit_scores": self.compute_scores(),
            "confidence_calibration": self.conf_calibration,
            "epsilon": 0.1
        }

    # BUG-008 fix: moved from module-level standalone functions into class
    def update_features(self, features, reward, learning_rate=0.01):
        """Update feature importance weights from reward signals."""
        if not hasattr(self, 'feature_weights'):
            self.feature_weights = {}
        for f in features:
            self.feature_weights.setdefault(f, 0.0)
            self.feature_weights[f] += learning_rate * reward

    def learn_bias(self, batch):
        """Update bias term from mini-batch of (state, action, reward, next_state) tuples."""
        if not hasattr(self, 'bias'):
            self.bias = 0.0
        if not batch:
            return
        avg_reward = sum(r for _, _, r, *_ in batch) / len(batch)
        self.bias += 0.01 * avg_reward


# ────────────────────────────────────────────────────────────────────────────────
# PATCH 8: Reward Engine — Proper reward calculation with portfolio penalties
# ────────────────────────────────────────────────────────────────────────────────
class RewardEngine:
    """PATCH 8: Compute trading rewards with portfolio-level penalties.
    
    Rewards drive reinforcement learning by signaling whether an action was
    good (positive reward) or bad (negative). This engine computes rewards
    from trade P&L while penalizing portfolio-level drawdowns.
    """
    
    def __init__(self):
        self.timeout_penalty = 0.002  # Penalty for time-out exits
        self.dd_penalty = 0.1         # Portfolio drawdown penalty multiplier
    
    def compute(self, trade, portfolio=None):
        """Compute reward for a single trade.
        
        Args:
            trade: Trade dict with 'pnl', optional 'timeout' flag
            portfolio: Portfolio state dict with 'drawdown' method/key
        
        Returns:
            float: Reward value (positive = good, negative = bad)
        """
        pnl = trade.get("pnl", 0.0) if trade else 0.0
        dd = 0.0
        
        if portfolio and callable(getattr(portfolio, 'get_drawdown', None)):
            dd = portfolio.get_drawdown()
        elif portfolio and isinstance(portfolio, dict):
            dd = portfolio.get("drawdown", 0.0)
        
        # Base reward is the trade P&L
        reward = pnl
        
        # Penalty for portfolio-level drawdown
        reward -= self.dd_penalty * dd
        
        # Additional penalty for timeout exits
        if trade and trade.get("timeout", False):
            reward -= self.timeout_penalty
        
        return reward


# ────────────────────────────────────────────────────────────────────────────────
# PATCH 9: Force Learning Step — Scheduled learning/exploration boost
# ────────────────────────────────────────────────────────────────────────────────
def hourly_update(agent, memory):
    """PATCH 9: Execute learning step hourly or when memory is full.
    
    Triggers:
    - Memory >= 32 samples: train mini-batch
    - Memory < 32: boost exploration rate
    
    Args:
        agent: DQN/RL agent with learn() method
        memory: Replay buffer/memory with sample() method and __len__
    """
    if len(memory) > 32:
        batch = memory.sample(32)
        agent.learn(batch)
        print(f"[LEARN] Trained on batch of {len(batch)} samples")
    else:
        # Insufficient data — boost exploration
        if hasattr(agent, 'exploration_rate'):
            agent.exploration_rate = min(1.0, agent.exploration_rate + 0.1)
            print(f"[LEARN] Boosting exploration: {agent.exploration_rate:.2f}")


# ────────────────────────────────────────────────────────────────────────────────
# PATCH 10 & 11 — BUG-008 fix: these were standalone functions with `self` param
# Moved inside LearningEngine class as proper instance methods.
# ────────────────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────────────────
# PATCH 12: Learning Log — Diagnostic output for reward/bias tracking
# ────────────────────────────────────────────────────────────────────────────────
def learning_log(agent, portfolio, trade):
    """PATCH 12: Log learning metrics for diagnostics.
    
    Args:
        agent: RL agent with bias, exploration_rate attributes
        portfolio: Portfolio with drawdown info
        trade: Completed trade with pnl, timeout info
    """
    reward_engine = RewardEngine()
    reward = reward_engine.compute(trade, portfolio)
    
    dd = portfolio.get("drawdown", 0.0) if isinstance(portfolio, dict) else 0.0
    
    bias = getattr(agent, 'bias', 0.0)
    exp = getattr(agent, 'exploration_rate', 0.0)
    pnl = trade.get("pnl", 0.0) if trade else 0.0
    
    print(f"[LEARN] r={reward:.6f} pnl={pnl:.6f} dd={dd:.4f} bias={bias:.4f} exp={exp:.2f}")