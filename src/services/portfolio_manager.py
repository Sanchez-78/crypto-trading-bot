import logging
import threading
from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, TRADE_CLOSED

log = logging.getLogger(__name__)
log.info("Portfolio manager ready")

_portfolio_lock = threading.Lock()

portfolio = {
    "open": [],
    "closed": [],
    "balance": 10000
}


def _calc_profit(trade: dict) -> float:
    """Calculate real P&L from entry/exit prices. BUG-001 fix."""
    entry = trade.get("price") or trade.get("entry_price", 0)
    exit_p = trade.get("exit_price") or trade.get("current_price", entry)
    direction = trade.get("signal", trade.get("direction", "BUY")).upper()
    if not entry or entry <= 0:
        return 0.0
    if direction in ("BUY", "LONG"):
        return (exit_p - entry) / entry
    else:
        return (entry - exit_p) / entry


def on_trade_executed(trade):
    try:
        if not isinstance(trade, dict):
            log.warning("Invalid trade payload: %s", trade)
            return
        price = trade.get("price")
        if price is None:
            log.warning("Missing price in trade: %s", trade)
            return
        with _portfolio_lock:
            portfolio["open"].append(trade)
    except Exception as e:
        log.error("portfolio on_trade_executed error: %s", e)


def process_portfolio():
    with _portfolio_lock:
        to_process = portfolio["open"][:]
    for trade in to_process:
        try:
            profit = _calc_profit(trade)
            trade["profit"] = profit
            trade["status"] = "CLOSED"
            with _portfolio_lock:
                if trade in portfolio["open"]:
                    portfolio["open"].remove(trade)
                portfolio["closed"].append(trade)
            log.info("Trade closed: %s profit=%.4f%%", trade.get("symbol", "?"), profit * 100)
            event_bus.publish(TRADE_CLOSED, trade)
        except Exception as e:
            log.error("close trade error: %s", e)


event_bus.subscribe(TRADE_EXECUTED, on_trade_executed)