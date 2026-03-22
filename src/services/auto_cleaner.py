from src.services.data_manager import DataManager
from src.services.firebase_client import load_old_trades, delete_trade, save_compressed

dm = DataManager()

def run_cleanup():
    trades = load_old_trades(200)

    for t in trades:
        if dm.should_delete(t):
            delete_trade(t["id"])
        else:
            save_compressed(dm.compress_trade(t))
            delete_trade(t["id"])