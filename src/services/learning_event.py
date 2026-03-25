from src.core.event_bus import subscribe
from src.services.firebase_client import load_trade_history, save_bot_stats
from src.services.decision_engine import load_memory, update_memory

trades_count = 0
wins = 0
losses = 0
ready = False


# =========================
# INIT LEARNING
# =========================
def init_learning():
    global trades_count, wins, losses, ready

    print("🧠 LOADING TRADE HISTORY...")

    history = load_trade_history()

    load_memory(history)

    trades_count = len(history)
    wins = sum(1 for t in history if t.get("result") == "WIN")
    losses = sum(1 for t in history if t.get("result") == "LOSS")

    print(f"🧠 Bootstrapped: {trades_count} trades")
    print(f"📊 Winrate: {wins}/{trades_count}")

    ready = True


# =========================
# EVENT: TRADE EXECUTED
# =========================
@subscribe("trade_executed")
def on_trade(data):
    global trades_count, wins, losses

    trade = data.get("trade", {})
    result = data.get("result", {})

    if not trade or not result:
        return

    trades_count += 1

    if result.get("result") == "WIN":
        wins += 1
    else:
        losses += 1

    # 🔥 update memory
    update_memory(trade, result)

    # 📊 stats
    winrate = wins / trades_count if trades_count > 0 else 0

    print(f"📈 PERFORMANCE → Trades: {trades_count}, Winrate: {winrate:.2%}")

    # 💾 save do Firebase
    save_bot_stats({
        "trades": trades_count,
        "wins": wins,
        "losses": losses,
        "winrate": winrate
    })


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
        "winrate": (wins / trades_count if trades_count else 0)
    }