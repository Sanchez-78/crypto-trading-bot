import time

from src.services.meta_agent import MetaAgent
from src.services.feature_engine import FeatureEngine
from src.services.portfolio_manager import PortfolioManager
from src.services.firebase_client import save_signal, save_meta_state
from src.services.market_stream import MarketStream

agent = MetaAgent()
fe = FeatureEngine()
pf = PortfolioManager()

# 🔥 REAL MARKET
stream = MarketStream(["btcusdt", "ethusdt"])
stream.start()

loop = 0

# ─────────────────────────────
# 💰 RISK MANAGER CONFIG
# ─────────────────────────────
MAX_OPEN_TRADES = 5
MAX_LOSS_STREAK = 5
MAX_DRAWDOWN = -5.0  # celkový profit
MIN_CONFIDENCE = 0.55

loss_streak = 0
total_profit = 0.0


# ─────────────────────────────
# 📊 PROGRESS BAR
# ─────────────────────────────
def render_progress(p):
    if "status" in p:
        print(f"\n🧠 {p['status']} | trades={p['trades']}")
        return

    score = p["score"]
    filled = score // 5
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

    print(f"\n📊 {emoji} {color}[{bar}] {score}%\033[0m")
    print(
        f"winrate={p['winrate']} profit={p['avg_profit']} "
        f"bias={p['bias']} trades={p['trades']}"
    )


# ─────────────────────────────
# 🛡️ RISK CHECK
# ─────────────────────────────
def risk_check(conf):
    global loss_streak, total_profit

    if len(pf.open_trades) >= MAX_OPEN_TRADES:
        print("⛔ MAX OPEN TRADES")
        return False

    if loss_streak >= MAX_LOSS_STREAK:
        print("⛔ LOSS STREAK LIMIT")
        return False

    if total_profit <= MAX_DRAWDOWN:
        print("⛔ MAX DRAWDOWN HIT")
        return False

    if conf < MIN_CONFIDENCE:
        return False

    return True


# ─────────────────────────────
# 🔥 MAIN LOOP
# ─────────────────────────────
def run():
    global loop, loss_streak, total_profit
    loop += 1

    print(f"\n=== LOOP {loop} ===")

    # ❤️ BOT ALIVE
    if loop % 30 == 0:
        print("💓 BOT ALIVE")

    prices = stream.get_prices()

    if not prices:
        print("⏳ čekám na data...")
        return

    # ─── UPDATE TRADES ─────────────────
    closed = pf.update_trades(prices)

    for trade, profit, result in closed:
        trade["signal"] = trade["action"]

        total_profit += profit

        if result == "LOSS":
            loss_streak += 1
        else:
            loss_streak = 0

        print(
            f"💰 CLOSED {trade['symbol']} profit={round(profit,4)} "
            f"total={round(total_profit,2)} streak={loss_streak}"
        )

        # 🔥 SAVE
        save_signal({
            "symbol": trade["symbol"],
            "signal": trade["signal"],
            "profit": profit,
            "result": result,
            "features": trade.get("features", {}),
        })

        # 🔥 LEARNING
        agent.learn_from_trade({
            "profit": profit,
            "result": result,
            "signal": trade["signal"],
            "features": trade.get("features", {}),
        })

    # ─── NEW TRADES ───────────────────
    for symbol, price in prices.items():
        fe.update(symbol, price)
        f = fe.build(symbol)

        action, conf = agent.decide(f)

        print(
            f"{symbol} {action} conf={round(conf,3)} "
            f"trend={round(f['trend_strength'],5)}"
        )

        # 🛡️ RISK CHECK
        if not risk_check(conf):
            continue

        trade, status = pf.open_trade(symbol, action, price, conf)

        if trade:
            trade["features"] = f

    # ─── PROGRESS ─────────────────────
    progress = agent.get_progress()
    render_progress(progress)

    print(
        f"💼 OPEN={len(pf.open_trades)} "
        f"💰 TOTAL={round(total_profit,2)} "
        f"📉 STREAK={loss_streak}"
    )

    # 🔥 DEBUG CLUSTERS
    if loop % 20 == 0:
        agent.print_top_clusters()

    # ─── SAVE META ────────────────────
    if loop % 10 == 0:
        save_meta_state({
            "progress": progress,
            "profit": total_profit,
            "loss_streak": loss_streak,
            "trades": agent.total_trades,
        })

    pf.print_status()

    print("==========================")


# ─────────────────────────────
# 🚀 START
# ─────────────────────────────
if __name__ == "__main__":
    print("🔥 BOT START (RISK MODE)")

    while True:
        try:
            run()
            time.sleep(3)

        except Exception as e:
            print("❌ ERROR:", e)
            time.sleep(5)