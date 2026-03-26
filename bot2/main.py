import threading, time

from src.services.market_stream import start
from src.services.firebase_client import init_firebase
from src.services.learning_event import get_metrics

import src.services.signal_generator
import src.services.trade_executor

def print_status():
    m = get_metrics()

    print("\n📊 ===== STATUS =====")
    print(f"Trades: {m['trades']}")
    print(f"Winrate: {m['winrate']*100:.2f}%")
    print(f"Profit: {m['profit']:.4f}")
    print(f"Drawdown: {m['drawdown']:.4f}")
    print(f"Confidence: {m['confidence_avg']:.3f}")
    print(f"Signals: {m['signals_generated']} / {m['signals_executed']}")
    print(f"Blocked: {m['blocked']}")
    print(f"Regimes: {m['regimes']}")
    print(f"READY: {'YES' if m['ready'] else 'NO'}")
    print("=====================\n")


def main():
    init_firebase()

    t = threading.Thread(target=start)
    t.daemon = True
    t.start()

    while True:
        time.sleep(10)
        print_status()


if __name__ == "__main__":
    main()