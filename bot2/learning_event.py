from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE, CONFIG_UPDATED

from bot2.learning_engine import LearningEngine


learner = LearningEngine()


# =========================
# 🧠 LEARNING HANDLER
# =========================
def on_evaluation(trade):
    try:
        # =========================
        # 🔥 HARDENING (NIKDY NESPADNE)
        # =========================

        if "confidence_used" not in trade:
            trade["confidence_used"] = trade.get("confidence", 0.5)

        if "regime" not in trade:
            trade["regime"] = "UNKNOWN"

        if "strategy" not in trade:
            trade["strategy"] = "UNKNOWN"

        if "meta" not in trade:
            trade["meta"] = {}

        # =========================
        # 🧠 LEARNING
        # =========================
        learner.update_bandit([trade])
        learner.calibrate_confidence([trade])
        learner.update_strategy_blame([trade])
        learner.update_regime_perf([trade])

        # =========================
        # ⚙️ CONFIG UPDATE
        # =========================
        config = learner.export_config()

        event_bus.publish(CONFIG_UPDATED, config)

        print("🧠 Learning updated")

    except Exception as e:
        print(f"❌ Learning error: {e}")


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_evaluation)