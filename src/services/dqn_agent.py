import random
import numpy as np
from collections import deque



ACTIONS = ["BUY", "SELL", "HOLD"]


class DQNAgent:

    def __init__(self):
        self.state_size = 10
        self.hidden_size = 32

        self.memory = deque(maxlen=2000)

        self.gamma = 0.95
        self.epsilon = 0.3
        self.epsilon_min = 0.02
        self.epsilon_decay = 0.995
        self.lr = 0.001

        # 🔥 jednoduchá NN
        self.W1 = np.random.randn(self.state_size, self.hidden_size) * 0.1
        self.W2 = np.random.randn(self.hidden_size, len(ACTIONS)) * 0.1

        self._load()

    # =========================
    # 🔧 FEATURES → VECTOR
    # =========================
    def _to_vector(self, f):
        return np.array([
            f.get("rsi_m15", 0),
            f.get("macd_m15", 0),
            f.get("ema_m15", 0),
            f.get("bb_m15", 0),
            f.get("atr_m15", 0),
            f.get("rsi_h1", 0),
            f.get("macd_h1", 0),
            f.get("ema_h1", 0),
            f.get("rsi_h4", 0),
            f.get("ema_h4", 0),
        ], dtype=float)

    # =========================
    # 🧠 FORWARD
    # =========================
    def _forward(self, x):
        z1 = np.dot(x, self.W1)
        a1 = np.tanh(z1)
        z2 = np.dot(a1, self.W2)
        return z2, a1

    # =========================
    # 🎯 ACTION
    # =========================
    def act(self, features):
        state = self._to_vector(features)

        # exploration
        if np.random.rand() < self.epsilon:
            action = random.choice(ACTIONS)
            print("🎲 DQN random:", action)
            return action, 0.5

        # exploitation
        q_values, _ = self._forward(state)

        idx = np.argmax(q_values)
        action = ACTIONS[idx]

        confidence = abs(q_values[idx])
        if confidence == 0:
            confidence = 0.3

        return action, float(min(confidence, 1.0))

    # =========================
    # 🧠 MEMORY
    # =========================
    def remember(self, state, action, reward):
        if state is None:
            return
        self.memory.append((state, action, reward))

    # =========================
    # 🧠 TRAIN (BACKPROP)
    # =========================
    def replay(self, batch_size=32):
        if len(self.memory) < batch_size:
            return

        batch = random.sample(self.memory, batch_size)

        for state, action, reward in batch:
            q_values, a1 = self._forward(state)

            target = q_values.copy()
            idx = ACTIONS.index(action)

            # 🔥 simple reward update
            target[idx] = reward

            error = target - q_values

            # 🔥 gradient
            dW2 = np.outer(a1, error)
            d_hidden = np.dot(self.W2, error) * (1 - a1 ** 2)
            dW1 = np.outer(state, d_hidden)

            # 🔥 update
            self.W1 += self.lr * dW1
            self.W2 += self.lr * dW2

        # epsilon decay
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    # =========================
    # 💾 SAVE (Firestore SAFE)
    # =========================
    def save(self):
        try:
            data = {
                "W1": self.W1.flatten().tolist(),
                "W2": self.W2.flatten().tolist(),
                "W1_shape": list(self.W1.shape),
                "W2_shape": list(self.W2.shape),
                "epsilon": float(self.epsilon)
            }

            save_weights({"dqn": data})

        except Exception as e:
            print("❌ Save error:", e)

    # =========================
    # 📂 LOAD
    # =========================
    def _load(self):
        try:
            data = load_weights().get("dqn")

            if not data:
                return

            self.W1 = np.array(data["W1"]).reshape(data["W1_shape"])
            self.W2 = np.array(data["W2"]).reshape(data["W2_shape"])
            self.epsilon = data.get("epsilon", 0.3)

            print("🧠 DQN loaded")

        except Exception as e:
            print("❌ Load error:", e)