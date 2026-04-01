import time
import sys, os

sys.path.append(os.getcwd())

from shared.bot1.market_provider    import MarketProvider
from src.services.firebase_client   import (
    save_signal, load_config, load_weights,
    load_bot2_metrics, load_bot2_advice,
)
from src.services.risk_manager      import RiskManager
from src.services.risk_engine       import RiskEngine
from src.services.portfolio_manager import PortfolioManager
from src.services.ml_model          import MLModel


def load_metrics():
    """
    Read live bot2 metrics from Firebase (metrics/latest, written every 30s).
    Falls back to conservative defaults if unavailable or bot2 not running.
    """
    raw  = load_bot2_metrics()
    perf = raw.get("performance", {})
    eq   = raw.get("equity", {})
    return {
        "performance": {
            "winrate":       perf.get("winrate",       0.50),
            "profit_factor": perf.get("profit_factor", 1.00),
            "trades":        perf.get("trades",        0),
        },
        "drawdown": eq.get("drawdown", 0.0),
        "health":   raw.get("health", {}).get("score", 50),
    }


def _is_blocked_by_bot2(symbol, regime):
    """
    Check if bot2 has flagged this (symbol, regime) as a structural loser.
    Returns (blocked: bool, reason: str).
    Bot2 publishes blocked_pairs as "SYM|REGIME" strings after every audit.
    If advice is stale (>5 min) or unavailable, pass through — don't block.
    """
    try:
        advice = load_bot2_advice()
        if not advice:
            return False, ""
        age = time.time() - float(advice.get("timestamp", 0))
        if age > 300:
            return False, "advice_stale"
        key = f"{symbol}|{regime}"
        if key in advice.get("blocked_pairs", []):
            return True, f"bot2_blocked({key})"
        # Respect bot2's drawdown halt — if pos_size_mult=0 bot2 itself stopped
        if float(advice.get("pos_size_mult", 1.0)) == 0.0:
            return True, "bot2_dd_halt"
    except Exception:
        pass
    return False, ""


def _bot2_ev_boost(symbol, regime):
    """
    Return a size multiplier based on bot2's EV for this (sym, regime).
    top_pairs with high EV get up to 1.5x; blocked pairs already filtered above.
    Returns 1.0 (neutral) if no advice available.
    """
    try:
        advice = load_bot2_advice()
        if not advice:
            return 1.0
        for p in advice.get("top_pairs", []):
            if p.get("sym") == symbol and p.get("regime") == regime:
                ev = float(p.get("ev", 0.0))
                if ev > 0.20:   return 1.5
                if ev > 0.10:   return 1.2
                if ev > 0.05:   return 1.0
    except Exception:
        pass
    return 1.0


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

        # ── Bot2 pair block ────────────────────────────────────────────────────
        # Skip pairs bot2 has confirmed as structural losers (WR<20% + EV≤0,
        # or WR<10% at n≥15). This prevents bot1 from trading pairs that bot2's
        # real-time learning has already identified as dead capital sinks.
        blocked, block_reason = _is_blocked_by_bot2(symbol, regime)
        if blocked:
            print(f"  ⛔ {symbol}/{regime} blocked by bot2: {block_reason}")
            time.sleep(60)
            continue

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

        # ── Bot2 EV boost: size up on confirmed winners ────────────────────────
        size *= _bot2_ev_boost(symbol, regime)

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
                "bot2_ev_boost":   _bot2_ev_boost(symbol, regime),
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
