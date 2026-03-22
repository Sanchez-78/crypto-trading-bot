from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED

from src.services.risk_manager import RiskManager
from src.services.risk_engine import RiskEngine
from src.services.portfolio_manager import PortfolioManager


risk_manager = RiskManager()
risk_engine = RiskEngine()
portfolio = PortfolioManager()


def on_price_tick(data):
    features = data

    # jednoduchá logika (napojíš svůj bandit)
    if features["trend"] != "UP":
        return

    signal = "BUY"
    confidence = 0.7

    event_bus.publish(SIGNAL_CREATED, {
        "signal": signal,
        "confidence": confidence,
        "features": features
    })


event_bus.subscribe(PRICE_TICK, on_price_tick)