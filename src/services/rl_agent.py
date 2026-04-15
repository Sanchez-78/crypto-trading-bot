import random
from collections import defaultdict
from src.services.firebase_client import load_weights, save_weights


class RLAgent:

    def __init__(self):
        self.q_table = defaultdict(lambda: {"BUY": 0, "SELL": 0, "HOLD": 0})
        self.lr = 0.1
        self.gamma = 0.9
        self.epsilon = 0.2

        self._load()

    # =========================
    # 🔧 STATE
    # =========================
    def _state_key(self, features):
        return (
            features.get("regime"),
            features.get("volatility")
        )

    # =========================
    # 🎯 ACTION
    # =========================
    def act(self, features, no_trade_cycles=0, force_exploration=False):
        """
        V5.1 Anti-hold force exploration fix.

        Args:
            features: Feature dict with regime, volatility
            no_trade_cycles: Number of consecutive cycles with no trades
            force_exploration: If True, force random action (stall recovery)
        """
        state = self._state_key(features)

        # 🚨 FORCE EXPLORATION: If stalled (no trades > 100 cycles), force non-HOLD action
        if force_exploration or no_trade_cycles > 100:
            action = random.choice(["BUY", "SELL"])  # Exclude HOLD in recovery mode
            return action, 0.3

        # 🎲 Standard exploration
        if random.random() < self.epsilon:
            action = random.choice(["BUY", "SELL", "HOLD"])
            return action, 0.5

        q_values = self.q_table[state]
        action = max(q_values, key=q_values.get)

        # 🔥 ANTI-HOLD BIAS CORRECTION: If HOLD wins but no_trade_cycles > 50, override
        if action == "HOLD" and no_trade_cycles > 50 and random.random() < 0.3:
            action = random.choice(["BUY", "SELL"])

        confidence = abs(q_values[action])

        # 🔥 FIX: bootstrap confidence
        if confidence == 0:
            confidence = 0.3

        return action, min(confidence, 1.0)

    # =========================
    # 🧠 LEARN
    # =========================
    def learn(self, features, action, reward):
        state = self._state_key(features)

        current_q = self.q_table[state][action]

        new_q = current_q + self.lr * (reward - current_q)

        self.q_table[state][action] = new_q

    # =========================
    # 💾 SAVE (FIXED)
    # =========================
    def save(self):
        serializable = {}

        for k, v in self.q_table.items():
            key = f"{k[0]}|{k[1]}"
            serializable[key] = v

        save_weights({"rl": serializable})

    # =========================
    # 📂 LOAD (FIXED)
    # =========================
    def _load(self):
        data = load_weights()
        rl = data.get("rl", {})

        for k, v in rl.items():
            try:
                regime, vol = k.split("|")
                self.q_table[(regime, vol)] = v
            except:
                continue