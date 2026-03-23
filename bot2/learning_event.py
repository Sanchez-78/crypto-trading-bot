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

history = []


# =========================
# HELPER: interpretace
# =========================
def interpret_performance(winrate, avg_profit):
    if winrate > 0.6 and avg_profit > 0:
        return "✅ Silně ziskový"
    elif winrate > 0.52:
        return "⚠️ Mírně ziskový (nestabilní)"
    elif winrate > 0.48:
        return "➡️ Break-even"
    else:
        return "❌ Prodělává"


def interpret_trend(trend):
    if trend == "IMPROVING":
        return "📈 Zlepšuje se"
    elif trend == "WORSENING":
        return "📉 Zhoršuje se"
    return "➡️ Stagnuje"


# =========================
# LEARNING HANDLER
# =========================
def on_evaluation(trade):
    try:
        # -------------------------
        # fallbacky
        # -------------------------
        trade["confidence_used"] = trade.get("confidence_used", trade.get("confidence", 0.5))
        trade["regime"] = trade.get("regime", "UNKNOWN")
        trade["strategy"] = trade.get("strategy", "UNKNOWN")

        # -------------------------
        # uložit historii
        # -------------------------
        history.append(trade)

        # -------------------------
        # LEARNING CORE
        # -------------------------
        learner.update_bandit([trade])
        learner.calibrate_confidence([trade])
        learner.update_strategy_blame([trade])
        learner.update_regime_perf([trade])

        # config → Bot1
        config = learner.export_config()
        event_bus.publish(CONFIG_UPDATED, config)

        # -------------------------
        # METRICS
        # -------------------------
        metrics = metrics_engine.compute(history[-100:])

        perf = metrics["performance"]
        learning = metrics["learning"]
        strat = metrics["strategy"]
        regime = metrics.get("regime", {})

        winrate = perf["winrate"]
        trades = perf["trades"]
        avg_profit = perf["avg_profit"]
        profit_factor = perf["profit_factor"]

        trend = learning["trend"]

        # -------------------------
        # 🔥 HUMAN DEBUG OUTPUT
        # -------------------------
        print("\n====================================")
        print("🤖 BOT STATUS (SROZUMITELNĚ)")
        print("====================================")

        print(f"📊 Obchodů: {trades}")
        print(f"🎯 Winrate: {winrate:.2f}")
        print(f"💰 Avg profit: {avg_profit:.4f}")
        print(f"📈 Profit factor: {profit_factor:.2f}")

        print(f"\n📌 Stav: {interpret_performance(winrate, avg_profit)}")
        print(f"🧠 Učení: {interpret_trend(trend)}")

        # -------------------------
        # STRATEGIE
        # -------------------------
        print("\n📊 Strategie:")
        for s, v in strat.items():
            print(f"  {s}: WR={v['winrate']:.2f} | Trades={v['trades']}")

        # -------------------------
        # REGIME
        # -------------------------
        if regime:
            print("\n🌍 Market režimy:")
            for r, v in regime.items():
                print(f"  {r}: WR={v['winrate']:.2f} | Trades={v['trades']}")

        print("====================================\n")

        # -------------------------
        # FIREBASE WRITE
        # -------------------------
        save_metrics(metrics)

        print("🔥 Metrics uloženy do Firebase")

    except Exception as e:
        print(f"❌ Learning error: {e}")


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_evaluation)