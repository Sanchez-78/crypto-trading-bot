from src.services.metrics_engine import MetricsEngine
from src.services.firebase_client import save_metrics

metrics_engine = MetricsEngine()
history = []

def on_evaluation(trade):
    trade["confidence_used"] = trade.get("confidence_used", trade.get("confidence",0.5))
    history.append(trade)

    # Learning update
    learner.update_bandit([trade])
    learner.calibrate_confidence([trade])
    learner.update_strategy_blame([trade])
    learner.update_regime_perf([trade])
    config = learner.export_config()
    event_bus.publish(CONFIG_UPDATED, config)

    # Metrics
    metrics = metrics_engine.compute(history[-200:])
    save_metrics(metrics)

    # Čitelný výstup
    print(f"🧠 Learning updated | WR={metrics['performance']['winrate']:.2f} "
          f"| AvgProfit={metrics['performance']['avg_profit']:.4f} "
          f"| PF={metrics['performance']['profit_factor']:.2f} "
          f"| MaxDD={metrics['risk']['max_drawdown']:.4f} "
          f"| Trend={metrics['learning']['trend']}")