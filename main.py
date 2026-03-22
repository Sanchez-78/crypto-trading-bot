import time
import traceback
from datetime import datetime, UTC

from src.services.market_data import get_all_prices
from src.services.meta_agent import MetaAgent
from src.services.firebase_client import (
    init_firebase,
    save_signal,
    load_recent_trades,
    save_meta_state,
)
from src.services.trade_filter import TradeFilter
from src.services.portfolio_manager import PortfolioManager
from src.services.feature_engine import FeatureEngine
from src.services.auto_cleaner import run_cleanup

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "XRPUSDT"]
LOOP_DELAY = 10

agent = MetaAgent()
trade_filter = TradeFilter()
portfolio = PortfolioManager()
feature_engine = FeatureEngine()

loop_count = 0


def render_progress(progress):
    score = progress["score"]
    filled = int(score / 5)
    bar = "█" * filled + "-" * (20 - filled)

    if score < 30:
        color = "\033[91m"
        emoji = "🔴"
    elif score < 60:
        color = "\033[93m"
        emoji = "🟡"
    else:
        color = "\033[92m"
        emoji = "🟢"

    print("\n📊 PROGRESS:")
    print(progress)
    print(f"{emoji} {color}[{bar}] {score}%\033[0m")


def run_pipeline():
    global loop_count
    loop_count += 1

    print("\n=== PIPELINE ===")

    init_firebase()
    trade_filter.reset()

    prices = get_all_prices()
    if not prices:
        prices = {
            "BTCUSDT": 60000,
            "ETHUSDT": 3000,
            "ADAUSDT": 0.5,
            "SOLUSDT": 150,
            "XRPUSDT": 0.6,
        }

    # ─── UPDATE TRADES ─────────────────
    closed_trades = portfolio.update_trades(prices)

    print(f"Closed trades: {len(closed_trades)}")

    for trade, profit, result in closed_trades:
        save_signal({
            "symbol": trade["symbol"],
            "signal": trade["action"],
            "confidence": trade["confidence"],
            "features": trade.get("features", {}),
            "profit": profit,
            "result": result,
            "evaluated": True,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        })

    # ─── NEW TRADES ───────────────────
    for symbol in SYMBOLS:
        try:
            price = prices.get(symbol)
            if not price:
                continue

            feature_engine.update(symbol, price)
            features = feature_engine.build(symbol)

            print(
                f"{symbol} | regime={features['market_regime']} "
                f"| trend={round(features['trend_strength'],5)} "
                f"| vol={round(features['vol_10'],5)}"
            )

            action, confidence = agent.decide(features)

            trade, _ = portfolio.open_trade(symbol, action, price, confidence)

            if trade:
                trade["features"] = features

        except Exception as e:
            print(f"❌ {symbol}:", e)
            traceback.print_exc()

    # ─── LEARNING ─────────────────────
    trades = load_recent_trades(1000)
    print(f"Trades loaded: {len(trades)}")

    agent.learn_from_history(trades)

    # ─── PROGRESS ─────────────────────
    progress = agent.get_progress()
    render_progress(progress)

    # ─── SAVE META ────────────────────
    save_meta_state({
        "progress": progress,
        "balance": portfolio.balance,
        "patterns": len(agent.patterns),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    })

    portfolio.print_status()

    # 🔥 AUTO CLEAN
    if loop_count % 20 == 0:
        run_cleanup()

    print("=============================\n")


if __name__ == "__main__":
    print("🔥 BOT STARTED (AUTO CLEAN ENABLED)")

    while True:
        try:
            run_pipeline()
        except Exception as e:
            print("❌ PIPELINE ERROR:", e)
            traceback.print_exc()

        time.sleep(LOOP_DELAY)