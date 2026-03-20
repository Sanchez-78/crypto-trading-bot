from src.services.model import predict_signal
from src.services.reward_system import compute_reward


class MetaAgent:

    def __init__(self):
        
        self.weights = {
            "dqn": 1.0,
            "strategy": 1.0,
            "momentum": 1.0
        }

    # =========================
    # 🤖 DECISION
    # =========================
    def decide(self, features):
        signals = {}

        # DQN
        dqn_signal, dqn_conf = self.dqn.act(features)
        signals["dqn"] = (dqn_signal, dqn_conf)

        # Strategy
        try:
            strat_signal, strat_conf = predict_signal(features)
        except:
            strat_signal, strat_conf = "HOLD", 0.3

        signals["strategy"] = (strat_signal, strat_conf)

        # Momentum
        macd = features.get("macd_m15", 0)
        if macd > 0:
            momentum_signal = "BUY"
        elif macd < 0:
            momentum_signal = "SELL"
        else:
            momentum_signal = "HOLD"

        signals["momentum"] = (momentum_signal, 0.4)

        # =========================
        # 🧠 WEIGHTED VOTING
        # =========================
        scores = {"BUY": 0, "SELL": 0, "HOLD": 0}

        for agent, (sig, conf) in signals.items():
            weight = self.weights.get(agent, 1.0)
            scores[sig] += conf * weight

        final_signal = max(scores, key=scores.get)
        confidence = scores[final_signal]

        print("🧠 Meta scores:", scores)
        print("⚖️ Weights:", self.weights)

        return final_signal, min(confidence, 1.0)

    # =========================
    # 🧠 LEARNING (META)
    # =========================
    def learn(self, signals):
        for s in signals[-50:]:
            try:
                if s.get("result") not in ["WIN", "LOSS"]:
                    continue

                features = s.get("features")
                if not features:
                    continue

                reward = compute_reward(
                    s.get("signal"),
                    features,
                    s.get("result"),
                    s.get("profit", 0)
                )

                # 🔥 uprav váhy podle rewardu
                if reward > 0:
                    self.weights["dqn"] += 0.01
                    self.weights["strategy"] += 0.005
                else:
                    self.weights["dqn"] -= 0.01
                    self.weights["momentum"] -= 0.005

                # clamp
                for k in self.weights:
                    self.weights[k] = max(0.1, min(self.weights[k], 2.0))

            except Exception as e:
                print("❌ Meta learn error:", e)

        # 🔥 normalize
        total = sum(self.weights.values())
        for k in self.weights:
            self.weights[k] /= total

        print("🧠 Updated weights:", self.weights)