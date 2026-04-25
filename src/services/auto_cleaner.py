import time
from src.services.data_manager import DataManager
from src.services.firebase_client import load_old_trades, delete_trade, save_compressed

dm = DataManager()
_LAST_CLEANUP_TS = 0  # EMERGENCY (2026-04-25): Throttle cleanup to once per hour

def run_cleanup():
    global _LAST_CLEANUP_TS
    now = time.time()
    # EMERGENCY: Only run cleanup if 1 hour has passed since last run
    if now - _LAST_CLEANUP_TS < 3600:
        return
    _LAST_CLEANUP_TS = now

    trades = load_old_trades(200)

    for t in trades:
        if dm.should_delete(t):
            delete_trade(t["id"])
        else:
            save_compressed(dm.compress_trade(t))
            delete_trade(t["id"])