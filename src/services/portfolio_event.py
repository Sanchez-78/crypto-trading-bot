from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, PRICE_TICK, TRADE_CLOSED

from src.services.portfolio_manager import PortfolioManager
from src.services.risk_manager import RiskManager
from src.services.risk_engine import RiskEngine


portfolio = PortfolioManager()
risk_manager = RiskManager()
risk_engine = RiskEngine()


def handle_signal(data):
    features = data["features"]
    confidence = data["confidence"]

    sl, tp = risk_manager.compute(features, features["price"], "BUY")

    if sl is None:
        return

    edge = risk_engine.compute_edge(confidence, 0.55)

    size = risk_engine.position_size(
        10000,
        features["price"],
        sl,
        edge
    )

    if size <= 0:
        return

    trade, _ = portfolio.open_trade(
        symbol="BTCUSDT",
        action="BUY",
        price=features["price"],
        size=size,
        sl=sl,
        tp=tp,
        confidence=confidence
    )

    if not trade:
        return

    # 🔥 KLÍČOVÝ FIX — PROPAGACE METADATA
    trade["strategy"] = data.get("strategy")
    trade["regime"] = data.get("regime")
    trade["meta"] = data.get("meta", {})

    event_bus.publish(TRADE_OPENED, trade)


def on_price_update(data):
    prices = {"BTCUSDT": data["price"]}

    closed = portfolio.update_trades(prices)

    for t, pnl, result in closed:
        event_bus.publish(TRADE_CLOSED, {
            "trade": t,
            "pnl": pnl,
            "result": result
        })


event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price_update)