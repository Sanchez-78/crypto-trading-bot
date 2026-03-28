import time
import sys, os

sys.path.append(os.getcwd())

from shared.bot1.market_provider    import MarketProvider
from src.services.firebase_client   import save_signal, load_config, load_weights
from src.services.risk_manager      import RiskManager
from src.services.risk_engine       import RiskEngine
from src.services.portfolio_manager import PortfolioManager
from src.services.ml_model          import MLModel


def load_metrics():
    # TODO: replace with live Firestore read when metrics module exposes it
    return {
        "performance": {"winrate": 0.55},
        "drawdown":    0.05,
    }


def run_execution():
    provider     = MarketProvider()
    ml           = MLModel()
    risk_manager = RiskManager()
    risk_engine  = RiskEngine()
    portfolio    = PortfolioManager()

    balance = 10000

    while True:
        config   = load_config() or {}
        features = provider.get_features()

        if features is None:
            time.sleep(30)
            continue

        symbol = features.get("symbol", "BTCUSDT")
        regime = features.get("regime", "RANGING")

        # ── ML prediction ──────────────────────────────────────────────────────
        # MLModel.predict() raises if the model has not been trained yet.
        # Training happens in bot2 after enough closed trades accumulate.
        try:
            ml_result = ml.predict(symbol, features)
        except Exception as e:
            print(f"⚠️  ML not ready ({e}) — waiting 60s")
            time.sleep(60)
            continue

        if ml_result["signal"] == "HOLD":
            time.sleep(60)
            continue

        signal     = ml_result["signal"]
        confidence = float(ml_result["confidence"])

        # ── Apply strategy weights written by bot2/strategy_weights.py ─────────
        # bot2 calls save_weights({"regime_weights": {...}}) after every audit.
        # load_weights() reads them back with a short TTL cache (~60 s).
        regime_weights = load_weights().get("regime_weights", {})
        regime_w       = float(regime_weights.get(regime, 1.0))
        confidence     = max(0.0, min(1.0, confidence * regime_w))

        metrics  = load_metrics()
        winrate  = metrics["performance"]["winrate"]
        drawdown = metrics["drawdown"]

        # ── Confidence calibration from Firebase config ────────────────────────
        cal            = config.get("confidence_calibration", {})
        confidence_adj = cal.get(round(confidence, 1), confidence)

        # ── Risk per trade — regime-aware ──────────────────────────────────────
        if regime in ("BULL_TREND", "BEAR_TREND"):
            risk_engine.max_risk_per_trade = 0.03
        elif features.get("volatility") == "HIGH":
            risk_engine.max_risk_per_trade = 0.01
        else:
            risk_engine.max_risk_per_trade = 0.02

        if drawdown > 0.1:
            risk_engine.max_risk_per_trade *= 0.5

        if drawdown > 0.2:
            print("💀 HARD STOP: drawdown > 20%")
            time.sleep(300)
            continue

        if not risk_engine.should_trade(drawdown, {"cooldown": 0}):
            time.sleep(60)
            continue

        price  = float(features.get("price") or features.get("close", 50000))
        sl, tp = risk_manager.compute(features, price, signal)

        if sl is None:
            time.sleep(60)
            continue

        edge = risk_engine.compute_edge(confidence_adj, winrate)
        size = risk_engine.position_size(balance, price, sl, edge)

        if size <= 0 or not portfolio.can_open(balance):
            time.sleep(60)
            continue

        vol_tag  = features.get("volatility", "NORMAL")
        trade, _ = portfolio.open_trade(
            symbol=symbol,
            action=signal,
            price=price,
            confidence=confidence_adj,
            size=size,
            sl=sl,
            tp=tp,
        )

        save_signal({
            **trade,
            "strategy":  regime,
            "regime":    regime,
            "features":  features,
            "edge":      edge,
            "meta": {
                "feature_bucket":  f"{features.get('trend', 0)}_{vol_tag}",
                "confidence_raw":  confidence,
                "confidence_used": confidence_adj,
                "regime_weight":   regime_w,
            },
            "timestamp": time.time(),
        })

        prices = {symbol: price}
        closed  = portfolio.update_trades(prices)

        for t, pnl, result in closed:
            print(f"🔒 CLOSED {t['id']} {result} {round(pnl, 4)}")

        time.sleep(60)


if __name__ == "__main__":
    run_execution()
