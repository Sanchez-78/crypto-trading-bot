import time
import sys, os
import math

sys.path.append(os.getcwd())

from src.services.firebase_client import get_db, load_evaluated_signals


# =========================
# 🧠 BANDIT (UCB)
# =========================
def compute_bandit_stats(trades):
    stats = {}

    for t in trades:
        strat = t.get("strategy")
        if not strat:
            continue

        if strat not in stats:
            stats[strat] = {"n": 0, "reward": 0}

        stats[strat]["n"] += 1
        stats[strat]["reward"] += t.get("profit", 0)

    return stats


def compute_ucb_scores(stats):
    scores = {}
    total_n = sum(s["n"] for s in stats.values()) + 1

    for strat, s in stats.items():
        avg = s["reward"] / s["n"] if s["n"] else 0

        exploration = math.sqrt(math.log(total_n) / (s["n"] + 1))

        scores[strat] = avg + exploration

    return scores


# =========================
# 🔍 AUDIT (ROLLBACK)
# =========================
def evaluate_versions(db):
    docs = db.collection("signals") \
        .where("evaluated", "==", True) \
        .limit(200) \
        .stream()

    versions = {}

    for d in docs:
        t = d.to_dict()
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

    for v, data in versions.items():
        wr = data["wins"] / data["total"] if data["total"] else 0

        if wr > best_wr:
            best_wr = wr
            best_v = v

    return best_v, best_wr


# =========================
# 🚀 MAIN
# =========================
def run_brain():
    print("🧠 Brain (Bandit) started...")

    db = get_db()

    current_version = 1

    while True:
        trades = load_evaluated_signals(limit=100)

        if not trades:
            print("⚠️ No data...")
            time.sleep(30)
            continue

        # =========================
        # 📊 BANDIT
        # =========================
        stats = compute_bandit_stats(trades)
        scores = compute_ucb_scores(stats)

        print("🎯 BANDIT SCORES:", scores)

        # =========================
        # 🔍 AUDIT
        # =========================
        versions = evaluate_versions(db)
        best_v, best_wr = select_best_version(versions)

        print("📦 VERSION STATS:", versions)
        print("🏆 BEST:", best_v, best_wr)

        # rollback pokud current horší
        if best_v and best_v != current_version:
            print("⚠️ ROLLBACK to version", best_v)
            current_version = best_v

        else:
            current_version += 1  # nová iterace

        config = {
            "bandit_scores": scores,
            "epsilon": 0.1,
            "version": current_version
        }

        db.collection("config").document("latest").set(config)

        print("⚙️ CONFIG:", config)

        time.sleep(60)


if __name__ == "__main__":
    run_brain()