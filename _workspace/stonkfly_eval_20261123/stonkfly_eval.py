"""Read-only Stonkfly evaluation (aggregates only). Runs on the server via stdin."""
import json, math, random, sqlite3, statistics as st
from collections import defaultdict

DB = "file:/opt/cryptomaster/local_learning_storage/shadow_excursion.sqlite?mode=ro"
CACHE = "file:/opt/cryptomaster/local_learning_storage/cache.sqlite?mode=ro"
TP, SL, COST = 35.0, 25.0, 9.0   # live geometry and round-trip cost (bps)

c = sqlite3.connect(DB, uri=True, timeout=5)
c.execute("PRAGMA query_only=ON")

def band(x, edges):
    for i, e in enumerate(edges):
        if x < e:
            return i
    return len(edges)

def bucket(d, g):
    return ("+" if d > 0 else "-" if d < 0 else "0") + "d%d" % band(abs(d), (2, 10, 20)) + "g%d" % band(g, (1, 5, 20))

rows = []
for strat in ("stonkfly_frozen_v1", "stonkfly_frozen_paired_v1"):
    q = ("SELECT p.decision_id, p.observation_ms, p.metadata_json FROM shadow_strategy_predictions p "
         "JOIN shadow_excursion_observations o ON o.observation_id=p.decision_id "
         "WHERE p.strategy_id=? AND p.stale=0 AND o.data_quality='ok' ORDER BY p.observation_ms")
    for did, obs_ms, meta in c.execute(q, (strat,)).fetchall():
        m = json.loads(meta)
        path = c.execute("SELECT second_offset, high_bps, low_bps, close_bps, first_high_ms, first_low_ms "
                         "FROM shadow_path_1s WHERE observation_id=? ORDER BY second_offset", (did,)).fetchall()
        if len(path) < 500:
            continue
        r600 = path[-1][3]
        out = None
        for sec, hi, lo, cl, fh, fl in path:
            up, dn = hi >= TP, lo <= -SL
            if up and dn:
                out = TP if (fh or 0) <= (fl or 0) else -SL
            elif up:
                out = TP
            elif dn:
                out = -SL
            if out is not None:
                break
        tpsl = (out if out is not None else r600) - COST
        rows.append(dict(strat=strat, t=obs_ms, r=r600, net=tpsl, win=tpsl > 0,
                         d=float(m.get("difference_hz", 0.0)), g=float(m.get("gate_spikes", 0)),
                         kc=m.get("KC_spikes", 0), ce=m.get("changed_edges", 0)))

def ci_day_bootstrap(xs, ts, n=2000, seed=7):
    days = defaultdict(list)
    for x, t in zip(xs, ts):
        days[t // 86400000].append(x)
    keys = list(days)
    rnd = random.Random(seed)
    means = []
    for _ in range(n):
        s = [v for k in (rnd.choice(keys) for _ in keys) for v in days[k]]
        means.append(sum(s) / len(s))
    means.sort()
    return round(means[int(0.025 * n)], 2), round(means[int(0.975 * n)], 2), len(keys)

def summ(rs, label):
    if not rs:
        print(label, "n=0"); return
    r = [x["r"] for x in rs]; net = [x["net"] for x in rs]; ts = [x["t"] for x in rs]
    lo, hi, nd = ci_day_bootstrap(net, ts)
    print(f"{label}: n={len(rs)} days={nd} gross600_mean={st.mean(r):+.2f}bps "
          f"BUY_TP35/SL25_net_mean={st.mean(net):+.2f}bps CI95_day=[{lo:+.2f};{hi:+.2f}] "
          f"WR={100*sum(x['win'] for x in rs)/len(rs):.1f}%")

print("all labels BUY; KC_spikes>0:", sum(1 for x in rows if x["kc"]), "changed_edges>0:", sum(1 for x in rows if x["ce"]))
for s in ("stonkfly_frozen_v1", "stonkfly_frozen_paired_v1"):
    summ([x for x in rows if x["strat"] == s], s)
summ(rows, "ALL frozen (= always BUY every ~5 min)")

# Do the neural features carry information? Chronological split: pick on first half, test on second.
rows.sort(key=lambda x: x["t"])
half = len(rows) // 2
train, test = rows[:half], rows[half:]

def spearman(a, b):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 0.0

for name, part in (("TRAIN", train), ("TEST", test)):
    print(f"{name}: n={len(part)} spearman(difference_hz, r600)={spearman([x['d'] for x in part], [x['r'] for x in part]):+.3f} "
          f"spearman(gate_spikes, r600)={spearman([x['g'] for x in part], [x['r'] for x in part]):+.3f}")
    summ(part, f"  {name} always-BUY")

tb = defaultdict(list)
for x in train:
    tb[bucket(x["d"], x["g"])].append(x["net"])
chosen = {k for k, v in tb.items() if len(v) >= 30 and st.mean(v) > 0}
print("TRAIN buckets (n>=30):", {k: (len(v), round(st.mean(v), 2)) for k, v in sorted(tb.items()) if len(v) >= 30})
print("chosen on TRAIN (mean net>0):", sorted(chosen))
summ([x for x in test if bucket(x["d"], x["g"]) in chosen], "  TEST in chosen buckets")
summ([x for x in test if bucket(x["d"], x["g"]) not in chosen], "  TEST outside chosen buckets")

# Real paper trades that carried the neural context vs other BTC trades of the same period.
k = sqlite3.connect(CACHE, uri=True, timeout=5)
k.execute("PRAGMA query_only=ON")
cols = {r[1] for r in k.execute("PRAGMA table_info(closed_trades)")}
if "tags_json" in cols:
    first = min(x["t"] for x in rows if x["strat"] == "stonkfly_frozen_paired_v1") / 1000
    for label, cond in (("BTC trades WITH neural context", "tags_json LIKE '%neural_source%'"),
                        ("BTC trades WITHOUT neural context", "(tags_json IS NULL OR tags_json NOT LIKE '%neural_source%')")):
        r = k.execute(f"SELECT COUNT(*), AVG(pnl_pct)*100, SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END), SUM(pnl_usd) "
                      f"FROM closed_trades WHERE symbol='BTCUSDT' AND entry_ts>=? AND {cond}", (first,)).fetchone()
        n = r[0] or 0
        print(f"{label}: n={n} avg_net={r[1] or 0:+.2f}bps WR={100*(r[2] or 0)/n if n else 0:.1f}% sum_usd={r[3] or 0:+.4f}")
else:
    print("closed_trades has no tags_json column")
