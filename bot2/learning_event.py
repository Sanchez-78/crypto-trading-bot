from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE, CONFIG_UPDATED

from bot2.learning_engine import LearningEngine
from src.services.metrics_engine import MetricsEngine
from src.services.firebase_client import save_metrics

learner = LearningEngine()
metrics_engine = MetricsEngine()

history = []


def on_evaluation(trade):
    try:
        # =========================
        # fallbacky
        # =========================
        trade["confidence_used"] = trade.get("confidence_used", trade.get("confidence", 0.5))
        trade["regime"] = trade.get("regime", "UNKNOWN")
        trade["strategy"] = trade.get("strategy", "UNKNOWN")

        history.append(trade)

        # =========================
        # LEARNING
        # =========================
        learner.update_bandit([trade])
        learner.calibrate_confidence([trade])
        learner.update_strategy_blame([trade])
        learner.update_regime_perf([trade])

        config = learner.export_config()
        event_bus.publish(CONFIG_UPDATED, config)

        # =========================
        # METRICS
        # =========================
        metrics = metrics_engine.compute(history[-100:])

        print("📊 METRICS READY")

        # 🔥 KLÍČOVÉ
        save_metrics(metrics)

        # =========================
        # LOG
        # =========================
        perf = metrics["performance"]

        print(f"🧠 WR={perf['winrate']:.2f} | Trades={perf['trades']}")

    except Exception as e:
        print(f"❌ Learning error: {e}")


event_bus.subscribe(EVALUATION_DONE, on_evaluation)