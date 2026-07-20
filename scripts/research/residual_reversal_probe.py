import json, math
SYMBOLS=["BTCUSDT","ETHUSDT","ADAUSDT","BNBUSDT","DOTUSDT","SOLUSDT","XRPUSDT"]
c=json.load(open("klines_cache.json")); data={s:{int(k):v for k,v in c[s].items()} for s in SYMBOLS}
common=sorted(set.intersection(*[set(d.keys()) for d in data.values()]))
px={s:[data[s][t] for t in common] for s in SYMBOLS}; n=len(common)
r={s:[0.0]+[math.log(px[s][i]/px[s][i-1]) for i in range(1,n)] for s in SYMBOLS}
Mx={s:[(sum(r[o][t] for o in SYMBOLS if o!=s)/6.0) for t in range(n)] for s in SYMBOLS}
resid={s:[r[s][t]-Mx[s][t] for t in range(n)] for s in SYMBOLS}
def bps(x): return 10000.0*x
STD_W=720
# prefix of resid per symbol for fast forward sums + rolling mean/std of resid (L=1 => E=resid)
pre={s:[0.0]*(n+1) for s in SYMBOLS}; pre2={s:[0.0]*(n+1) for s in SYMBOLS}
for s in SYMBOLS:
    for t in range(n):
        pre[s][t+1]=pre[s][t]+resid[s][t]; pre2[s][t+1]=pre2[s][t]+resid[s][t]**2
print("L=1 tail residual reversal — ACTUAL gross (sign tells revert vs continue)")
print(f"{'theta':>5} {'H':>3} {'n':>6} {'gross_bp':>9} {'net@36':>8} {'WR%':>6}")
for theta in (2.0,3.0):
    for H in (1,3,6,12,24):
        gs=[]
        for s in SYMBOLS:
            e=resid[s]
            for t in range(STD_W, n-H):
                a=t-STD_W; b=t; cnt=b-a
                m=(pre[s][b]-pre[s][a])/cnt
                var=(pre2[s][b]-pre2[s][a])/cnt-m*m
                sd=math.sqrt(var) if var>1e-18 else 0.0
                if sd==0: continue
                z=(e[t]-m)/sd
                if abs(z)<theta: continue
                d=-1 if z>0 else 1
                fr=pre[s][t+1+H]-pre[s][t+1]
                gs.append(bps(d*fr))
        if not gs: continue
        g=sum(gs)/len(gs); net=g-36; wr=100*sum(1 for x in gs if x-36>0)/len(gs)
        print(f"{theta:>5} {H:>3} {len(gs):>6} {g:>9.2f} {net:>8.2f} {wr:>6.1f}")
