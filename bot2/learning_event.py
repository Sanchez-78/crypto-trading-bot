from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE, CONFIG_UPDATED

from bot2.learning_engine import LearningEngine


learner = LearningEngine()


def on_evaluation(trade):
    try:
        # 🔥 ochrana proti rozbitým datům
        if "regime" not in trade:
            return

        learner.update_bandit([trade])
        learner.calibrate_confidence([trade])
        learner.update_strategy_blame([trade])
        learner.update_regime_perf([trade])

        config = learner.export_config()

        event_bus.publish(CONFIG_UPDATED, config)

        print("🧠 Learning updated")

    except Exception as e:
        print(f"❌ Learning error: {e}")


event_bus.subscribe(EVALUATION_DONE, on_evaluation)