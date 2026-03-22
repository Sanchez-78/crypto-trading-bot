import threading
import time

from bot1.execution_bot import run_execution
from bot2.brain import run_brain
from src.services.evaluator import evaluate_signals
from src.services.firebase_client import load_signals, save_config
from bot2.learning_engine import LearningEngine


SYMBOL = "BTCUSDT"


# =========================
# 🧠 LEARNING LOOP
# =========================
def learning_loop():
    learner = LearningEngine()

    while True:
        try:
            trades = load_signals(evaluated=True)

            if trades:
                learner.update_bandit(trades)
                learner.calibrate_confidence(trades)
                learner.update_strategy_blame(trades)
                learner.update_regime_perf(trades)

                config = learner.export_config()
                save_config(config)

                print("🧠 Learning updated")

        except Exception as e:
            print(f"❌ Learning error: {e}")

        time.sleep(60)


# =========================
# 📊 EVALUATOR LOOP
# =========================
def evaluator_loop():
    while True:
        try:
            evaluate_signals(SYMBOL)
        except Exception as e:
            print(f"❌ Evaluator error: {e}")

        time.sleep(20)


# =========================
# 🚀 MAIN
# =========================
def main():
    print("🚀 STARTING FULL SYSTEM")

    # =========================
    # BOT1 (EXECUTION)
    # =========================
    threading.Thread(target=run_execution, daemon=True).start()

    # =========================
    # EVALUATOR
    # =========================
    threading.Thread(target=evaluator_loop, daemon=True).start()

    # =========================
    # LEARNING ENGINE
    # =========================
    threading.Thread(target=learning_loop, daemon=True).start()

    # =========================
    # OPTIONAL: původní brain (méně často)
    # =========================
    while True:
        try:
            run_brain()  # může dělat deeper analýzu / audit
        except Exception as e:
            print(f"❌ Brain error: {e}")

        time.sleep(300)  # každých 5 min


if __name__ == "__main__":
    main()