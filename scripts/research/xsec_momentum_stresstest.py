#!/usr/bin/env python3
"""Stress-test the one positive lead: cross-sectional momentum (720/168/2).

Before believing +12bp OOS or sending it to audit, check the things that killed
tsmom: is it small-sample luck? does it survive sub-periods, cost stress, a
bootstrap CI? is the SHORT leg real, or is it long-only beta in disguise?
"""
import json, urllib.request, time

SYMBOLS = ["BTCUSDT","ETHUSDT","ADAUSDT","BNBUSDT","DOTUSDT","SOLUSDT","XRPUSDT"]
BASE = "https://data-api.binance.vision/api/v3/klines"
HOURS = 26000
LB, HOLD, NS = 720, 168, 2

def fetch(sym):
    out=[]; end=None; got=0
    while got<HOURS:
        n=min(1000,HOURS-got)
        url=f"{BASE}?symbol={sym}&interval=1h&limit={n}"+(f"&endTime={end}" if end else "")
        for a in range(4):
            try:
                with urllib.request.urlopen(url,timeout=30) as r: rows=json.load(r); break
            except Exception:
                if a==3: raise
                time.sleep(1.5*(a+1))
        if not rows: break
        out=rows+out; got+=len(rows); end=rows[0][0]-1
        if len(rows)<n: break
    return {r[0]: float(r[4]) for r in out}

def bps(x): return 10000.0*x
data={s:fetch(s) for s in SYMBOLS}
common=set.intersection(*[set(d.keys()) for d in data.values()])
ts=sorted(common); px={s:[data[s][t] for t in ts] for s in SYMBOLS}; n=len(ts)
print(f"aligned {n} bars ({n//24}d)")

def legs(cost_leg):
    """per-rebalance: (spread_net, long_only_net, short_only_net) in bps."""
    out=[]; i=LB
    while i<n-HOLD:
        past=sorted(((s,(px[s][i]-px[s][i-LB])/px[s][i-LB]) for s in SYMBOLS), key=lambda kv: kv[1])
        shorts=[s for s,_ in past[:NS]]; longs=[s for s,_ in past[-NS:]]
        fwd={s:(px[s][i+HOLD]-px[s][i])/px[s][i] for s in SYMBOLS}
        lr=sum(fwd[s] for s in longs)/NS; sr=sum(fwd[s] for s in shorts)/NS
        spread=bps(lr-sr)-2*cost_leg          # 2 legs, round-trip cost each
        long_only=bps(lr)-cost_leg             # long winners only, 1 leg
        short_only=bps(-sr)-cost_leg           # short losers only, 1 leg
        out.append((spread,long_only,short_only))
        i+=HOLD
    return out

def m(xs): return sum(xs)/len(xs) if xs else 0.0
def wr(xs): return 100*sum(1 for x in xs if x>0)/len(xs) if xs else 0.0

# 1) cost sensitivity (per leg)
print("\n=== cost sensitivity (per-leg bps) ===")
for c in (0,5,10,18,25):
    L=legs(c); sp=[x[0] for x in L]
    print(f"  cost/leg={c:>2}bp  spread mean={m(sp):>7.2f}bp  WR={wr(sp):.1f}%  n={len(sp)}")

# 2) long vs short leg contribution (is the short leg real?) at 18bp
L=legs(18); sp=[x[0] for x in L]; lo=[x[1] for x in L]; so=[x[2] for x in L]
print("\n=== leg decomposition @18bp/leg ===")
print(f"  spread     mean={m(sp):>7.2f}bp WR={wr(sp):.1f}%")
print(f"  long-only  mean={m(lo):>7.2f}bp WR={wr(lo):.1f}%  (winners; includes market beta)")
print(f"  short-only mean={m(so):>7.2f}bp WR={wr(so):.1f}%  (losers, shorted)")

# 3) sub-period thirds (spread @18) + OOS holdout
print("\n=== sub-period stability (spread @18bp/leg) ===")
k=len(sp)//3
for name,seg in [("early",sp[:k]),("mid",sp[k:2*k]),("late",sp[2*k:])]:
    print(f"  {name:6} mean={m(seg):>7.2f}bp WR={wr(seg):.1f}% n={len(seg)}")
cut=int(len(sp)*0.6); oos=sp[cut:]
print(f"  OOS(last40%) mean={m(oos):>7.2f}bp WR={wr(oos):.1f}% n={len(oos)}")

# 4) deterministic block-bootstrap CI on OOS mean (no RNG: all contiguous blocks)
def block_ci(xs, bl=8):
    if len(xs)<bl: return None
    means=[m(xs[i:i+bl]) for i in range(0,len(xs)-bl+1)]
    means.sort()
    lo=means[int(0.05*len(means))]; hi=means[int(0.95*len(means))]
    return m(xs), lo, hi
ci=block_ci(oos)
if ci: print(f"\n=== OOS block-bootstrap (block=8) ===\n  mean={ci[0]:.2f}bp  5-95% block-mean range=[{ci[1]:.2f}, {ci[2]:.2f}]")
print("\nVERDICT: lead is real ONLY if OOS mean>0 across cost≤18, short leg contributes,")
print("all thirds positive-ish, and the block range doesn't straddle deeply negative.")
