#!/usr/bin/env python3
"""Cost-wall check: CROSS-SECTIONAL (relative-value) momentum, market-neutral.

Untested class. At each rebalance, rank the N symbols by past-lookback return,
go LONG the top and SHORT the bottom (dollar-neutral), hold H hours. This has
edge uncorrelated to market direction and amortizes cost over longer holds.
Honest test: gross per-leg return net of round-trip cost, chronological OOS,
across 3y multi-regime. Also reports a market-neutral spread so beta is removed.
"""
import json, urllib.request, time

SYMBOLS = ["BTCUSDT","ETHUSDT","ADAUSDT","BNBUSDT","DOTUSDT","SOLUSDT","XRPUSDT"]
BASE = "https://data-api.binance.vision/api/v3/klines"
HOURS = 26000  # ~3y

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
    return {r[0]: float(r[4]) for r in out}  # ts -> close

def bps(x): return 10000.0*x

# align on common timestamps
data={s:fetch(s) for s in SYMBOLS}
common=set.intersection(*[set(d.keys()) for d in data.values()])
ts=sorted(common)
px={s:[data[s][t] for t in ts] for s in SYMBOLS}
n=len(ts)
print(f"aligned bars: {n} ({n//24}d), {len(SYMBOLS)} symbols")

def run(lookback, hold, n_side, cost_bps):
    """Return list of per-rebalance market-neutral spread returns (bps, net)."""
    rets=[]
    i=lookback
    while i < n-hold:
        past=[(s,(px[s][i]-px[s][i-lookback])/px[s][i-lookback]) for s in SYMBOLS]
        past.sort(key=lambda kv: kv[1])
        shorts=[s for s,_ in past[:n_side]]
        longs=[s for s,_ in past[-n_side:]]
        fwd={s:(px[s][i+hold]-px[s][i])/px[s][i] for s in SYMBOLS}
        long_r=sum(fwd[s] for s in longs)/len(longs)
        short_r=sum(fwd[s] for s in shorts)/len(shorts)
        spread=long_r - short_r          # market-neutral: long winners, short losers
        # cost: both legs enter+exit -> ~2 round-trips of cost on the spread
        rets.append(bps(spread) - 2*cost_bps)
        i+=hold
    return rets

def stats(rets):
    if not rets: return None
    m=sum(rets)/len(rets)
    wr=100*sum(1 for r in rets if r>0)/len(rets)
    gw=sum(r for r in rets if r>0); gl=-sum(r for r in rets if r<0)
    pf=gw/gl if gl>0 else float('inf')
    return m,len(rets),wr,pf

GRID=[(168,48,1),(168,48,2),(72,24,1),(336,72,2),(720,168,2)]  # (lookback,hold,n_side)
print(f"\n{'lookback':8} {'hold':5} {'nside':5} {'n':>5} {'gross_bp':>9} {'net@18':>8} {'WR%':>6} {'PF@18':>6} {'OOS_net@18':>10} {'OOS_WR':>7}")
best=None
for lb,hold,ns in GRID:
    full=run(lb,hold,ns,0)
    g,_,_,_=stats(full)
    net=run(lb,hold,ns,18)
    m,cnt,wr,pf=stats(net)
    # OOS: last 40%
    cut=int(len(net)*0.6)
    oos=net[cut:]
    om,on,owr,opf=stats(oos) if oos else (0,0,0,0)
    flag=""
    if om>0 and owr>50: flag=" <== CLEARS (net>0 & WR>50 OOS)"
    print(f"{lb:8} {hold:5} {ns:5} {cnt:>5} {g:>9.2f} {m:>8.2f} {wr:>6.1f} {pf:>6.2f} {om:>10.2f} {owr:>6.1f}{flag}")
