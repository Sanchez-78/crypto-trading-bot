from datetime import datetime
from src.services.firebase_client import get_db, update_signal
from src.services.market_data import get_all_prices
from google.cloud.firestore_v1.base_query import FieldFilter

HOLD_CYCLES = 3


# =========================
# 🔄 EVALUACE SIGNALŮ (UPGRADED)
# =========================
def evaluate_signals(symbol):
    db = get_db()
    if db is None:
        return

    prices = get_all_prices()

    docs = db.collection("signals") \
        .where(filter=FieldFilter("symbol", "==", symbol)) \
        .where(filter=FieldFilter("evaluated", "==", False)) \
        .stream()

    for d in docs:
        doc_id = d.id
        signal = d.to_dict()

        age = signal.get("age", 0)

        # ⏳ simulace držení
        if age < HOLD_CYCLES:
            update_signal(doc_id, {"age": age + 1})
            continue

        entry_price = signal.get("price")
        current_price = prices.get(symbol, entry_price)

        action = signal.get("signal")
        sl = signal.get("stop_loss")
        tp = signal.get("take_profit")

        # =========================
        # 📊 PROFIT
        # =========================
        if action == "BUY":
            profit = (current_price - entry_price) / entry_price
        elif action == "SELL":
            profit = (entry_price - current_price) / entry_price
        else:
            profit = 0

        # =========================
        # 📉 SL / TP HIT LOGIKA
        # =========================
        hit_sl = False
        hit_tp = False

        if action == "BUY":
            if sl and current_price <= sl:
                hit_sl = True
            if tp and current_price >= tp:
                hit_tp = True

        elif action == "SELL":
            if sl and current_price >= sl:
                hit_sl = True
            if tp and current_price <= tp:
                hit_tp = True

        # =========================
        # 📈 MFE / MAE (SIMULACE)
        # =========================
        # TODO: později nahradit reálnými OHLC daty
        mfe = max(0, profit * 1.5)
        mae = min(0, profit * 1.2)

        # =========================
        # ⚡ EFFICIENCY
        # =========================
        efficiency = profit / mfe if mfe > 0 else 0

        # =========================
        # 🎯 RESULT
        # =========================
        if hit_tp:
            result = "WIN"
        elif hit_sl:
            result = "LOSS"
        else:
            result = "WIN" if profit > 0 else "LOSS"

        # =========================
        # 🧠 META FEEDBACK
        # =========================
        meta = signal.get("meta", {})

        evaluation = {
            "profit": float(profit),
            "result": result,
            "mfe": float(mfe),
            "mae": float(mae),
            "efficiency": float(efficiency),
            "duration": age,
            "hit_sl": hit_sl,
            "hit_tp": hit_tp,
            "confidence_used": meta.get("confidence_used"),
            "feature_bucket": meta.get("feature_bucket")
        }

        update_signal(doc_id, {
            "evaluated": True,
            "evaluation": evaluation,
            "profit": float(profit),
            "result": result,
            "evaluated_at": datetime.utcnow().isoformat()
        })


# =========================
# 📊 PERFORMANCE PRO BOT2
# =========================
def calculate_performance(trades):
    if not trades:
        return {
            "winrate": 0,
            "avg_pnl": 0,
            "avg_efficiency": 0
        }

    wins = [t for t in trades if t.get("result") == "WIN"]

    winrate = len(wins) / len(trades)
    avg_pnl = sum(t.get("profit", 0) for t in trades) / len(trades)

    efficiencies = [
        t.get("evaluation", {}).get("efficiency", 0)
        for t in trades
    ]

    avg_eff = sum(efficiencies) / len(efficiencies) if efficiencies else 0

    return {
        "winrate": winrate,
        "avg_pnl": avg_pnl,
        "avg_efficiency": avg_eff
    }