from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

from src.services.firebase_client import (
    smart_write,
    log_trade,
    write_last_trade
)
from src.services.auto_control import auto_control
from src.services.portfolio_event import open_trades
from src.services.risk_manager import risk_manager
from src.services.portfolio_risk import portfolio_risk
from src.services.alert_system import alert_system
from src.services.self_healing import self_healing

import time
import statistics


# =========================
# STATE
# =========================
history = []

equity = 1000.0
peak = 1000.0

last_winrate = None


# =========================
# METRICS
# =========================
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


def compute_consistency(data):
    profits = [t["evaluation"]["profit"] for t in data]
    if len(profits) < 5:
        return 0

    try:
        return 1 / (1 + statistics.stdev(profits))
    except:
        return 0


def compute_score(winrate, pf, dd):
    return round(
        winrate * 50 +
        min(pf, 3) * 15 +
        (1 - dd) * 35,
        2
    )


def compute_status(score, dd):
    if dd > 0.25:
        return "BROKEN"
    if score > 70:
        return "HEALTHY"
    if score > 50:
        return "RISKY"
    return "BAD"


def compute_learning_state(data):
    if len(data) < 20:
        return "WARMUP"

    first = data[:len(data)//2]
    second = data[len(data)//2:]

    if compute_winrate(second) > compute_winrate(first):
        return "IMPROVING"
    else:
        return "DEGRADING"


# =========================
# MAIN
# =========================
def on_eval(trade):
    global equity, last_winrate

    print("\n🧠 LEARNING TRIGGERED")

    history.append(trade)

    pnl = trade["evaluation"]["profit"]
    equity *= (1 + pnl)

    # =========================
    # CORE METRICS
    # =========================
    total = len(history)
    winrate = compute_winrate(history)
    avg_profit = compute_avg_profit(history)
    pf = compute_profit_factor(history)
    dd = compute_drawdown()
    consistency = compute_consistency(history)

    # =========================
    # TREND
    # =========================
    trend = "STABLE"

    if last_winrate is not None:
        if winrate > last_winrate:
            trend = "IMPROVING"
        elif winrate < last_winrate:
            trend = "WORSENING"

    last_winrate = winrate

    # =========================
    # LEARNING STATE
    # =========================
    learning_state = compute_learning_state(history)

    # =========================
    # HEALTH
    # =========================
    score = compute_score(winrate, pf, dd)
    status = compute_status(score, dd)

    # =========================
    # PORTFOLIO
    # =========================
    portfolio = portfolio_risk.get_metrics(
        open_trades,
        risk_manager.balance
    )

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
    # DEBUG PRINT
    # =========================
    print("===================================")
    print(f"📊 Trades: {total}")
    print(f"🎯 Winrate: {winrate:.2f}")
    print(f"💰 Equity: {equity:.2f}")
    print(f"📉 Drawdown: {dd:.2%}")
    print(f"📈 Trend: {trend}")
    print(f"🧠 Learning: {learning_state}")
    print(f"📊 Score: {score}")
    print(f"🚦 Status: {status}")
    print(f"📦 Open Trades: {portfolio['open_trades']}")
    print("===================================\n")

    # =========================
    # FIREBASE EXPORT
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
            "trend": trend,
            "state": learning_state,
            "consistency": consistency
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

        # 🔥 SELF HEALING
        "self_healing": self_healing.get_status(),

        # 🔥 LAST TRADE
        "last_trade": last_trade_data,

        "timestamp": time.time()
    }

    # =========================
    # FIREBASE WRITE
    # =========================
    smart_write(metrics)
    write_last_trade(last_trade_data)
    log_trade(trade)

    # =========================
    # AUTO CONTROL
    # =========================
    auto_control.update(metrics)

    # =========================
    # ALERT SYSTEM
    # =========================
    alert_system.check_metrics(metrics)
    alert_system.on_trade(trade)

    # =========================
    # SELF HEALING
    # =========================
    self_healing.update(metrics, auto_control)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_eval)

print("🧠 Learning Engine FINAL (Self-Healing Enabled)")from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

from src.services.firebase_client import (
    smart_write,
    log_trade,
    write_last_trade
)
from src.services.auto_control import auto_control
from src.services.portfolio_event import open_trades
from src.services.risk_manager import risk_manager
from src.services.portfolio_risk import portfolio_risk
from src.services.alert_system import alert_system
from src.services.self_healing import self_healing

import time
import statistics


# =========================
# STATE
# =========================
history = []

equity = 1000.0
peak = 1000.0

last_winrate = None


# =========================
# METRICS
# =========================
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


def compute_consistency(data):
    profits = [t["evaluation"]["profit"] for t in data]
    if len(profits) < 5:
        return 0

    try:
        return 1 / (1 + statistics.stdev(profits))
    except:
        return 0


def compute_score(winrate, pf, dd):
    return round(
        winrate * 50 +
        min(pf, 3) * 15 +
        (1 - dd) * 35,
        2
    )


def compute_status(score, dd):
    if dd > 0.25:
        return "BROKEN"
    if score > 70:
        return "HEALTHY"
    if score > 50:
        return "RISKY"
    return "BAD"


def compute_learning_state(data):
    if len(data) < 20:
        return "WARMUP"

    first = data[:len(data)//2]
    second = data[len(data)//2:]

    if compute_winrate(second) > compute_winrate(first):
        return "IMPROVING"
    else:
        return "DEGRADING"


# =========================
# MAIN
# =========================
def on_eval(trade):
    global equity, last_winrate

    print("\n🧠 LEARNING TRIGGERED")

    history.append(trade)

    pnl = trade["evaluation"]["profit"]
    equity *= (1 + pnl)

    # =========================
    # CORE METRICS
    # =========================
    total = len(history)
    winrate = compute_winrate(history)
    avg_profit = compute_avg_profit(history)
    pf = compute_profit_factor(history)
    dd = compute_drawdown()
    consistency = compute_consistency(history)

    # =========================
    # TREND
    # =========================
    trend = "STABLE"

    if last_winrate is not None:
        if winrate > last_winrate:
            trend = "IMPROVING"
        elif winrate < last_winrate:
            trend = "WORSENING"

    last_winrate = winrate

    # =========================
    # LEARNING STATE
    # =========================
    learning_state = compute_learning_state(history)

    # =========================
    # HEALTH
    # =========================
    score = compute_score(winrate, pf, dd)
    status = compute_status(score, dd)

    # =========================
    # PORTFOLIO
    # =========================
    portfolio = portfolio_risk.get_metrics(
        open_trades,
        risk_manager.balance
    )

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
    # DEBUG PRINT
    # =========================
    print("===================================")
    print(f"📊 Trades: {total}")
    print(f"🎯 Winrate: {winrate:.2f}")
    print(f"💰 Equity: {equity:.2f}")
    print(f"📉 Drawdown: {dd:.2%}")
    print(f"📈 Trend: {trend}")
    print(f"🧠 Learning: {learning_state}")
    print(f"📊 Score: {score}")
    print(f"🚦 Status: {status}")
    print(f"📦 Open Trades: {portfolio['open_trades']}")
    print("===================================\n")

    # =========================
    # FIREBASE EXPORT
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
            "trend": trend,
            "state": learning_state,
            "consistency": consistency
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

        # 🔥 SELF HEALING
        "self_healing": self_healing.get_status(),

        # 🔥 LAST TRADE
        "last_trade": last_trade_data,

        "timestamp": time.time()
    }

    # =========================
    # FIREBASE WRITE
    # =========================
    smart_write(metrics)
    write_last_trade(last_trade_data)
    log_trade(trade)

    # =========================
    # AUTO CONTROL
    # =========================
    auto_control.update(metrics)

    # =========================
    # ALERT SYSTEM
    # =========================
    alert_system.check_metrics(metrics)
    alert_system.on_trade(trade)

    # =========================
    # SELF HEALING
    # =========================
    self_healing.update(metrics, auto_control)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_eval)

print("🧠 Learning Engine FINAL (Self-Healing Enabled)")