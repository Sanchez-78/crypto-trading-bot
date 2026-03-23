from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

from src.services.firebase_client import smart_write, log_trade, write_last_trade
from src.services.auto_control import auto_control
from src.services.portfolio_event import open_trades
from src.services.risk_manager import risk_manager
from src.services.portfolio_risk import portfolio_risk

import time
import statistics


history = []

equity = 1000.0
peak = 1000.0
last_winrate = None


def compute_drawdown():
    global equity, peak
    peak = max(peak, equity)
    return (peak - equity) / peak if peak > 0 else 0


def compute_winrate(data):
    if not data:
        return 0
    wins = sum(1 for t in data if t["evaluation"]["result"] == "WIN")
    return wins / len(data)


def compute_avg_profit(data):
    if not data:
        return 0
    return sum(t["evaluation"]["profit"] for t in data) / len(data)


def compute_profit_factor(data):
    profits = [t["evaluation"]["profit"] for t in data]
    gains = sum(p for p in profits if p > 0)
    losses = abs(sum(p for p in profits if p < 0))
    return gains / losses if losses > 0 else 999


def compute_score(winrate, pf, dd):
    return round(winrate * 50 + min(pf, 3) * 15 + (1 - dd) * 35, 2)


def compute_status(score, dd):
    if dd > 0.25:
        return "BROKEN"
    if score > 70:
        return "HEALTHY"
    if score > 50:
        return "RISKY"
    return "BAD"


def on_eval(trade):
    global equity, last_winrate

    history.append(trade)

    pnl = trade["evaluation"]["profit"]
    equity *= (1 + pnl)

    total = len(history)
    winrate = compute_winrate(history)
    avg_profit = compute_avg_profit(history)
    pf = compute_profit_factor(history)
    dd = compute_drawdown()

    trend = "STABLE"
    if last_winrate:
        if winrate > last_winrate:
            trend = "IMPROVING"
        elif winrate < last_winrate:
            trend = "WORSENING"

    last_winrate = winrate

    score = compute_score(winrate, pf, dd)
    status = compute_status(score, dd)

    portfolio = portfolio_risk.get_metrics(open_trades, risk_manager.balance)

    # =========================
    # LAST TRADE
    # =========================
    last_trade_data = {
        "symbol": trade["symbol"],
        "result": trade["evaluation"]["result"],
        "pnl": pnl,
        "confidence": trade.get("confidence", 0),
        "is_profit": pnl > 0,
        "timestamp": time.time()
    }

    # =========================
    # METRICS
    # =========================
    metrics = {
        "performance": {
            "trades": total,
            "winrate": winrate,
            "avg_profit": avg_profit,
            "profit_factor": pf
        },
        "equity": {
            "equity": equity,
            "drawdown": dd
        },
        "learning": {
            "trend": trend
        },
        "health": {
            "score": score,
            "status": status
        },
        "portfolio": portfolio,
        "system": {
            "trading_enabled": auto_control.trading_enabled,
            "risk_mode": auto_control.risk_multiplier
        },

        # 🔥 INLINE LAST TRADE
        "last_trade": last_trade_data,

        "timestamp": time.time()
    }

    smart_write(metrics)

    # 🔥 WRITE LAST TRADE
    write_last_trade(last_trade_data)

    auto_control.update(metrics)

    log_trade(trade)


event_bus.subscribe(EVALUATION_DONE, on_eval)

print("🧠 Learning + LastTrade READY")