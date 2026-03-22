import time
from shared.strategy_selector import StrategySelector
from shared.volatility_filter import VolatilityFilter
from shared.profit_optimizer import ProfitOptimizer
from shared.position_manager import compute_position_size

from src.services.firebase_client import load_config, save_trade


class ExecutionBot:

    def __init__(self):
        self.selector = StrategySelector()
        self.vol_filter = VolatilityFilter()
        self.optimizer = ProfitOptimizer()

    def compute_signal(self, features, config):
        score = 0

        for k, w in config.get("weights", {}).items():
            score += features.get(k, 0) * w

        conf = score
        conf *= config.get("confidence_scale", 1)
        conf += config.get("confidence_bias", 0)

        return max(0, min(1, conf))

    def run(self, market):
        print("🟢 Execution started")

        while True:
            try:
                config = load_config()
                if not config:
                    time.sleep(5)
                    continue

                features = market.get_features()
                price = features["price"]

                if not self.vol_filter.allow(features):
                    continue

                strategy = self.selector.select(features)
                confidence = self.compute_signal(features, config)

                signal = "BUY" if confidence > 0.5 else "SELL"

                if self.optimizer.block(signal, confidence, features):
                    continue

                size = compute_position_size(
                    confidence,
                    trust=config.get("trust", 1)
                )

                trade = {
                    "symbol": features["symbol"],
                    "signal": signal,
                    "confidence": confidence,
                    "strategy": strategy,
                    "price": price,
                    "size": size,
                    "timestamp": datetime.utcnow().isoformat(),
                    "status": "OPEN",
                    "self_eval": {
                        "predicted": confidence
                    }
                }

                save_trade(trade)

                print(f"✅ {signal} {confidence:.2f}")

                time.sleep(5)

            except Exception as e:
                print("❌ ERROR:", e)
                time.sleep(5)