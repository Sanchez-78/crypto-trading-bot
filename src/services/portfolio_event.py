from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, PRICE_TICK, TRADE_CLOSED

from src.services.portfolio_manager import PortfolioManager
from src.services.risk_manager import RiskManager
from src.services.risk_engine import RiskEngine
from src.services.trade_guard import TradeGuard


# =========================
# INIT
# =========================
portfolio = PortfolioManager()
risk_manager = RiskManager()
risk_engine = RiskEngine()
guard = TradeGuard()

BALANCE = 10000  # můžeš per-symbol později dynamicky


# =========================
# HANDLE SIGNAL
# =========================
def handle_signal(data):
    try:
        features = data["features"]
        confidence = data["confidence"]
        symbol = data.get("symbol")
        if not symbol:
            return  # safety

        # =========================
        # ❗ TRADE GATING
        # =========================
        if not guard.cooldown_ok(symbol):
            return

        if guard.is_duplicate(symbol, features):
            return

        if not portfolio.can_open(BALANCE):
            return

        # =========================
        # RISK MANAGEMENT
        # =========================
        sl, tp = risk_manager.compute(features, features["price"], "BUY")
        if sl is None:
            return

        edge = risk_engine.compute_edge(confidence, 0.55)

        size = risk_engine.position_size(
            BALANCE,
            features["price"],
            sl,
            edge
        )

        if size <= 0:
            return

        # =========================
        # OPEN TRADE
        # =========================
        trade, reason = portfolio.open_trade(
            symbol=symbol,
            action="BUY",
            price=features["price"],
            size=size,
            sl=sl,
            tp=tp,
            confidence=confidence
        )

        if not trade:
            print(f"⚠️ Trade skipped: {reason}")
            return

        # =========================
        # METADATA
        # =========================
        trade["strategy"] = data.get("strategy")
        trade["regime"] = data.get("regime")
        trade["meta"] = data.get("meta", {})

        trade["confidence_used"] = confidence * edge

        # =========================
        # MARK TRADE
        # =========================
        guard.mark_trade(symbol)

        # =========================
        # PUBLISH
        # =========================
        event_bus.publish(TRADE_OPENED, trade)

    except Exception as e:
        print(f"❌ handle_signal error: {e}")


# =========================
# PRICE UPDATE
# =========================
def on_price_update(data):
    try:
        # data = {"BTCUSDT":price, "ADAUSDT":price, "ETHUSDT":price, ...}
        for symbol, price in data.items():
            closed = portfolio.update_trades({symbol: price})
            for t, pnl, result in closed:
                event_bus.publish(TRADE_CLOSED, {
                    "trade": t,
                    "pnl": pnl,
                    "result": result
                })

    except Exception as e:
        print(f"❌ price update error: {e}")


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price_update)