import time
import sys, os
import math

sys.path.append(os.getcwd())

from src.services.firebase_client import get_db, load_evaluated_signals


# =========================
# 🧠 FEATURE BUCKET
# =========================
def extract_feature_bucket(t):
    f = t.get("features", {})

    vol = f.get("volatility", 0)
    trend = f.get("trend", "NONE")

    if vol > 0.7:
        vol_bucket = "HIGH"
    elif vol > 0.3:
        vol_bucket = "MID"
    else:
        vol_bucket = "LOW"

    return f"{trend}_{vol_bucket}"


# =========================
# ⏳ DECAY
# =========================
def compute_decay_weight(t, now):
    age = now - t.get("timestamp", now)
    return 0.5 ** (age / 3600)


# =========================
# 🧠 CONTEXTUAL BANDIT
# =========================
def compute_contextual_bandit(trades):
    stats = {}
    now = time.time()

    for t in trades:
        strat = t.get("strategy")
        regime = t.get("regime")

        if not strat or not regime:
            continue

        feature_bucket = extract_feature_bucket(t)
        key = f"{regime}_{strat}_{feature_bucket}"

        if key not in stats:
            stats[key] = {"n": 0, "reward": 0}

        decay = compute_decay_weight(t, now)

        stats[key]["n"] += decay
        stats[key]["reward"] += t.get("profit", 0) * decay

    return stats


def compute_ucb(stats):
    scores = {}
    total = sum(v["n"] for v in stats.values()) + 1

    for k, v in stats.items():
        avg = v["reward"] / v["n"] if v["n"] else 0
        exploration = math.sqrt(math.log(total) / (v["n"] + 1))
        scores[k] = avg + exploration

    return scores


# =========================
# 🔍 AUDIT
# =========================
def evaluate_versions(trades):
    versions = {}

    for t in trades:
        v = t.get("config_version", 0)

        if v not in versions:
            versions[v] = {"wins": 0, "total": 0}

        versions[v]["total"] += 1

        if t.get("result") == "WIN":
            versions[v]["wins"] += 1

    return versions


def select_best_version(versions):
    best_v = None
    best_wr = 0

    for v, d in versions.items():
        wr = d["wins"] / d["total"] if d["total"] else 0

        if wr > best_wr:
            best_wr = wr
            best_v = v

    return best_v, best_wr


# =========================
# 📊 PERFORMANCE METRICS
# =========================
def compute_performance_metrics(trades):
    wins = 0
    losses = 0
    profit_sum = 0
    profit_win = 0
    profit_loss = 0

    for t in trades:
        p = t.get("profit", 0)

        profit_sum += p

        if p > 0:
            wins += 1
            profit_win += p
        else:
            losses += 1
            profit_loss += abs(p)

    total = wins + losses

    winrate = wins / total if total else 0
    avg_profit = profit_sum / total if total else 0
    profit_factor = (profit_win / profit_loss) if profit_loss > 0 else 0

    return {
        "winrate": round(winrate, 3),
        "avg_profit": round(avg_profit, 5),
        "profit_factor": round(profit_factor, 3),
        "trades": total
    }


# =========================
# 📉 DRAWDOWN
# =========================
def compute_drawdown(trades):
    equity = 0
    peak = 0
    max_dd = 0

    for t in trades:
        equity += t.get("profit", 0)

        if equity > peak:
            peak = equity

        dd = peak - equity

        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 5)


# =========================
# 🧠 STRATEGY METRICS
# =========================
def compute_strategy_stats(trades):
    stats = {}

    for t in trades:
        s = t.get("strategy")
        p = t.get("profit", 0)

        if not s:
            continue

        if s not in stats:
            stats[s] = {"wins": 0, "total": 0}

        stats[s]["total"] += 1

        if p > 0:
            stats[s]["wins"] += 1

    for s in stats:
        total = stats[s]["total"]
        wins = stats[s]["wins"]
        stats[s]["winrate"] = round(wins / total, 3) if total else 0

    return stats


# =========================
# 📈 LEARNING PROGRESS
# =========================
def compute_learning_progress(trades):
    if len(trades) < 20:
        return {"trend": "NO_DATA"}

    mid = len(trades) // 2

    first = trades[:mid]
    second = trades[mid:]

    w1 = compute_performance_metrics(first)["winrate"]
    w2 = compute_performance_metrics(second)["winrate"]

    if w2 > w1:
        trend = "IMPROVING"
    elif w2 < w1:
        trend = "WORSENING"
    else:
        trend = "STABLE"

    return {
        "before": round(w1, 3),
        "after": round(w2, 3),
        "trend": trend
    }


# =========================
# 🚀 MAIN
# =========================
def run_brain():
    print("🧠 Brain started (Full AI System)")

    db = get_db()
    current_version = 1

    while True:
        trades = load_evaluated_signals(limit=100)

        if not trades:
            print("⚠️ No data")
            time.sleep(30)
            continue

        # =========================
        # 🧠 BANDIT
        # =========================
        stats = compute_contextual_bandit(trades)
        scores = compute_ucb(stats)

        print("🎯 SCORES:", scores)

        # =========================
        # 🔍 AUDIT
        # =========================
        versions = evaluate_versions(trades)
        best_v, best_wr = select_best_version(versions)

        print("📦 VERSIONS:", versions)

        if best_v and best_v != current_version:
            print("⚠️ ROLLBACK →", best_v)
            current_version = best_v
        else:
            current_version += 1

        # =========================
        # 📊 METRICS
        # =========================
        perf = compute_performance_metrics(trades)
        dd = compute_drawdown(trades)
        strat_stats = compute_strategy_stats(trades)
        learning = compute_learning_progress(trades)

        print("📊 PERFORMANCE:", perf)
        print("📉 DRAWDOWN:", dd)
        print("🧠 STRATEGY:", strat_stats)
        print("📈 LEARNING:", learning)

        # =========================
        # 💾 SAVE CONFIG
        # =========================
        config = {
            "bandit_scores": scores,
            "epsilon": 0.1,
            "version": current_version
        }

        try:
            db.collection("config").document("latest").set(config)
        except Exception as e:
            print("⚠️ config save fail:", e)

        # =========================
        # 💾 SAVE METRICS
        # =========================
        metrics = {
            "performance": perf,
            "drawdown": dd,
            "strategy": strat_stats,
            "learning": learning,
            "timestamp": time.time()
        }

        try:
            db.collection("metrics").document("latest").set(metrics)
        except Exception as e:
            print("⚠️ metrics save fail:", e)

        print("⚙️ CONFIG + METRICS UPDATED")

        time.sleep(60)


if __name__ == "__main__":
    run_brain()