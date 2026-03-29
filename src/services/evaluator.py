import src.core.event_bus as _bus
from src.core.events import TRADE_EXECUTED

print("EVALUATOR READY (pass-through)")


def on_trade(trade):
    """
    No-op. Trade results are computed and persisted by trade_executor.on_price().
    Old implementation wrote random.uniform(-0.01, 0.02) as profit to Firebase,
    polluting all training history with fabricated WIN/LOSS records. Removed.
    """
    pass


def evaluate_signals(symbol=None):
    """Stub for main.py compatibility — evaluation now happens in trade_executor."""
    pass


_bus.subscribe(TRADE_EXECUTED, on_trade)
