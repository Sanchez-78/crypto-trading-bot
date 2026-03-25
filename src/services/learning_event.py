from src.core.event_bus import subscribe
from src.services.firebase_client import load_trade_history, save_bot_stats
from src.services.decision_engine import load_memory, update_memory

trades_count = 0
wins = 0
losses = 0
total_profit = 0.0

ready = False


# =========================
# INIT LEARNING
# =========================
def init_learning():
    global trades_count, wins, losses, total_profit, ready

    print("🧠 LOADING TRADE HISTORY...")

    try:
        history = load_trade_history()
    except Exception as e:
        print("❌ Failed to load history:", e)
        history = []

    # 🧠 load decision memory
    try:
        load_memory(history)
        print(f"🧠 Decision memory loaded: {len(history)} trades")
    except Exception as e:
        print("❌ Memory load error:", e)

    trades_count = len(history)
    wins = sum(1 for t in history if t.get("result") == "WIN")
    losses = sum(1 for t in history if t.get("result") == "LOSS")
    total_profit = sum(t.get("profit", 0) for t in history)

    print(f"📊 Bootstrapped: {trades_count} trades")
    print(f"📊 Wins: {wins}, Losses: {losses}")
    print(f"📊 Winrate: {(wins / trades_count if trades_count else 0):.2%}")
    print(f"💰 Total profit: {total_profit:.4f}")

    ready = True


# =========================
# EVENT: TRADE EXECUTED
# =========================
@subscribe("trade_executed")
def on_trade(data):
    global trades_count, wins, losses, total_profit

    try:
        trade = data.get("trade", {})
        result = data.get("result", {})

        if not trade or not result:
            print("⚠️ Invalid trade event")
            return

        trades_count += 1

        outcome = result.get("result")
        profit = result.get("profit", 0)

        if outcome == "WIN":
            wins += 1
        else:
            losses += 1

        total_profit += profit

        # 🧠 update decision memory
        try:
            update_memory(trade, result)
        except Exception as e:
            print("⚠️ Memory update error:", e)

        # 📊 metrics
        winrate = wins / trades_count if trades_count else 0
        avg_profit = total_profit / trades_count if trades_count else 0

        print(f"📈 PERFORMANCE → Trades: {trades_count}")
        print(f"📊 Winrate: {winrate:.2%}")
        print(f"💰 Profit: {total_profit:.4f} | Avg: {avg_profit:.4f}")

        # 💾 save stats
        try:
            save_bot_stats({
                "trades": trades_count,
                "wins": wins,
                "losses": losses,
                "winrate": winrate,
                "profit": total_profit,
                "avg_profit": avg_profit
            })
        except Exception as e:
            print("⚠️ Failed to save stats:", e)

    except Exception as e:
        print("❌ Learning error:", e)


# =========================
# READY FLAG
# =========================
def is_ready():
    return ready


# =========================
# METRICS
# =========================
def get_metrics():
    return {
        "trades": trades_count,
        "wins": wins,
        "losses": losses,
        "winrate": (wins / trades_count if trades_count else 0),
        "profit": total_profit,
        "avg_profit": (total_profit / trades_count if trades_count else 0)
    }