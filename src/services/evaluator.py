from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED

print("📊 EVALUATOR READY (pass-through)")


def on_trade(trade):
    """
    No-op.  Trade results (profit, result, close_reason) are computed and
    persisted by trade_executor.on_price() which has the actual entry/exit
    prices and fees.  The old implementation here used random.uniform(-0.01,
    0.02) as profit and wrote it to Firebase, polluting all training history
    with fabricated WIN/LOSS records.  Removed entirely.
    """
    pass


event_bus.subscribe(TRADE_EXECUTED, on_trade)
