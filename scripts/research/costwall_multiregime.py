#!/usr/bin/env python3
"""Multi-regime + purged walk-forward test of tsmom(168,48).

The 180d screen cleared the wall in a BEAR/trending window (via shorts, not beta).
Trend-following's known failure mode is RANGING/chop. So: fetch a long history,
label each trade's regime by trend-strength, and check whether tsmom survives
RANGING regimes and a rolling purged walk-forward — the evidence-bar test.
"""
import json, urllib.request, time, statistics as st

SYMBOLS = ["BTCUSDT","ETHUSDT","ADAUSDT","BNBUSDT","DOTUSDT","SOLUSDT","XRPUSDT"]
BASE = "https://data-api.binance.vision/api/v3/klines"
HOURS = 26000  # ~3 years
LOOKBACK, HOLD = 168, 48

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
    ts=[r[0] for r in out]; cl=[float(r[4]) for r in out]
    return ts, cl

def bps(x): return 10000.0*x

def trades(closes):
    """(i, signed_ret, dir, regime_adx_like)."""
    tr=[]; n=len(closes); i=LOOKBACK
    while i<n-HOLD:
        w=closes[i-LOOKBACK:i]
        past=(closes[i]-w[0])/w[0]
        r=(closes[i+HOLD]-closes[i])/closes[i]
        d=1 if past>0 else -1
        # trend strength: |net move| / sum(|step moves|) over lookback  (0=chop,1=pure trend)
        steps=[abs(w[j+1]-w[j]) for j in range(len(w)-1)]
        path=sum(steps) or 1e-9
        eff=abs(w[-1]-w[0])/path   # efficiency ratio (Kaufman): high=trending, low=ranging
        tr.append((i, d*r, d, eff))
        i+=HOLD
    return tr

def net(ts, cost=18):
    rs=[bps(r)-cost for r in ts]
    return (sum(rs)/len(rs), len(rs)) if rs else (None,0)

# Fetch
data={}
for sym in SYMBOLS:
    try:
        ts,cl=fetch(sym); data[sym]=cl
        print(f"fetched {sym}: {len(cl)} bars ({len(cl)//24}d)")
    except Exception as e:
        print(f"{sym} failed: {e}")

# 1) regime breakdown: pool all trades, bucket by efficiency ratio
print("\n=== tsmom(168,48) net@18 by REGIME (efficiency ratio; low=ranging, high=trending) ===")
pool=[]
for sym,cl in data.items():
    for (i,r,d,eff) in trades(cl):
        pool.append((r,eff))
pool.sort(key=lambda x:x[1])
def bucket(lo,hi,label):
    sub=[r for r,eff in pool if lo<=eff<hi]
    e,_=net(sub); wr=100*sum(1 for r in sub if r>0)/len(sub) if sub else 0
    print(f"  {label:14} eff[{lo:.2f},{hi:.2f})  n={len(sub):>5}  net@18={ (e if e else 0):>8.2f} bp  WR={wr:.1f}%")
bucket(0.0,0.15,"deep-ranging")
bucket(0.15,0.30,"ranging")
bucket(0.30,0.50,"mild-trend")
bucket(0.50,1.01,"strong-trend")

# 2) per-symbol full-period + rolling purged walk-forward (expanding train, test next block)
print("\n=== per-symbol full-period + rolling purged walk-forward (net@18) ===")
print(f"{'symbol':8} {'n':>5} {'full_net':>9} {'WF_test_net':>11} {'WF_folds_pos':>12}")
for sym,cl in data.items():
    tr=trades(cl)
    rs=[t[1] for t in tr]
    full,_=net(rs)
    # rolling WF: 5 folds, expanding train, test on next chunk, purge HOLD bars between (approx: drop 1 trade)
    k=len(tr)//5
    fold_nets=[]
    for f in range(1,5):
        test=tr[f*k+1:(f+1)*k]  # +1 = purge one trade
        e,_=net([t[1] for t in test])
        if e is not None: fold_nets.append(e)
    pos=sum(1 for e in fold_nets if e>0)
    med=sorted(fold_nets)[len(fold_nets)//2] if fold_nets else 0
    print(f"{sym:8} {len(tr):>5} {(full if full else 0):>9.2f} {med:>11.2f} {pos:>8}/{len(fold_nets)}")
