from src.services.data_manager import DataManager
from src.services.firebase_client import (
    load_old_trades,
    delete_trade,
    save_compressed,
)

data_manager = DataManager()


def run_cleanup():
    print("\n🧹 CLEANUP START")

    trades = load_old_trades(limit=200)

    deleted = 0
    compressed = 0

    for t in trades:
        try:
            if data_manager.should_delete(t):
                delete_trade(t["id"])
                deleted += 1
            else:
                c = data_manager.compress_trade(t)
                save_compressed(c)
                delete_trade(t["id"])
                compressed += 1

        except Exception as e:
            print("❌ CLEAN ERROR:", e)

    print(f"🧹 DONE | deleted={deleted} compressed={compressed}")