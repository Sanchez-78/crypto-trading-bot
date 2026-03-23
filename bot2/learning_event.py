from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE, CONFIG_UPDATED

from bot2.learning_engine import LearningEngine
from src.services.metrics_engine import MetricsEngine
from src.services.firebase_client import save_metrics

learner = LearningEngine()
metrics_engine = MetricsEngine()

history = []


def on_evaluation(trade):
    history.append(trade)

    learner.update_bandit([trade])
    learner.calibrate_confidence([trade])

    config = learner.export_config()
    event_bus.publish(CONFIG_UPDATED, config)

    metrics = metrics_engine.compute(history[-100:])

    # =========================
    # LEARNING PROGRESS DEBUG
    # =========================
    trend = metrics["learning"]["trend"]
    winrate = metrics["performance"]["winrate"]

    print("\n📊 ===== BOT STATUS =====")
    print(f"Trades: {metrics['performance']['trades']}")
    print(f"Winrate: {winrate:.2f}")
    print(f"Trend: {trend}")
    print("========================\n")

    save_metrics(metrics)

event_bus.subscribe(EVALUATION_DONE, on_evaluation)