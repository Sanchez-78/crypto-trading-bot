from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE, CONFIG_UPDATED

from bot2.learning_engine import LearningEngine
from src.services.metrics_engine import MetricsEngine
from src.services.firebase_client import save_metrics


# =========================
# INIT
# =========================
learner = LearningEngine()
metrics_engine = MetricsEngine()
history = []  # ukládá poslední trades pro metriky


# =========================
# LEARNING HANDLER
# =========================
def on_evaluation(trade):
    try:
        # =========================
        # HARDENING / fallbacky
        # =========================
        trade["confidence_used"] = trade.get("confidence_used", trade.get("confidence", 0.5))
        trade["regime"] = trade.get("regime", "UNKNOWN")
        trade["strategy"] = trade.get("strategy", "UNKNOWN")
        trade["meta"] = trade.get("meta", {})

        # =========================
        # ULOŽENÍ DO HISTORIE
        # =========================
        history.append(trade)

        # =========================
        # LEARNING
        # =========================
        learner.update_bandit([trade])
        learner.calibrate_confidence([trade])
        learner.update_strategy_blame([trade])
        learner.update_regime_perf([trade])

        # EXPORT CONFIG
        config = learner.export_config()
        event_bus.publish(CONFIG_UPDATED, config)

        # =========================
        # METRICS
        # =========================
        # posledních 200 tradeů
        metrics = metrics_engine.compute(history[-200:])
        save_metrics(metrics)

        # =========================
        # LOG VIZUALIZACE (čitelná)
        # =========================
        perf = metrics["performance"]
        risk = metrics["risk"]
        learning = metrics["learning"]

        print(f"🧠 Learning updated | WR={perf['winrate']:.2f} "
              f"| AvgProfit={perf['avg_profit']:.4f} "
              f"| PF={perf['profit_factor']:.2f} "
              f"| MaxDD={risk['max_drawdown']:.4f} "
              f"| Trend={learning['trend']} "
              f"| Trades={perf['trades']}")

        # Volitelně více detailů:
        # strategie a regime
        for s, v in metrics["strategy"].items():
            print(f"  Strategy {s}: WR={v['winrate']:.2f} AvgProfit={v['avg_profit']:.4f} Trades={v['trades']}")
        for r, v in metrics["regime"].items():
            print(f"  Regime {r}: WR={v['winrate']:.2f} AvgProfit={v['avg_profit']:.4f} Trades={v['trades']}")

        # Confidence bins
        conf = metrics["confidence"]
        print(f"  Confidence bins: low={conf['low']:.4f} mid={conf['mid']:.4f} high={conf['high']:.4f}")

    except Exception as e:
        print(f"❌ Learning error: {e}")


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_evaluation)