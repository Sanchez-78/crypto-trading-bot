#!/usr/bin/env python3
"""Cost-wall feasibility check for candidate signal classes (offline, read-only).

Per RESEARCH_PIVOT_CHARTER.md: before building ANY infra, test whether a candidate
signal plausibly clears the ~18 bp taker round-trip cost wall (route a: gross edge
>> 18 bp), out-of-sample. This is a CHEAP feasibility screen, not the full evidence
bar (no executable-fill model here — we test GROSS edge on hourly closes, which is
the friendliest case; if a signal can't clear the wall even on gross close-to-close,
it's dead).

Data: hourly klines from data-api.binance.vision (public mirror). Cost model applied
to gross per-trade return: taker 18 bp round-trip, and a lenient 6 bp (maker-ish).
Chronological OOS: first 60% train (pick best params), last 40% test once, with a
1-bar purge gap. Verdict per signal = OOS net expectancy after 18 bp.
"""
import json, sys, urllib.request, time

SYMBOLS = ["BTCUSDT","ETHUSDT","ADAUSDT","BNBUSDT","DOTUSDT","SOLUSDT","XRPUSDT"]
BASE = "https://data-api.binance.vision/api/v3/klines"
INTERVAL = "1h"
HOURS = 4320  # ~180 days

def fetch(sym):
    out = []
    end = None
    got = 0
    while got < HOURS:
        n = min(1000, HOURS - got)
        url = f"{BASE}?symbol={sym}&interval={INTERVAL}&limit={n}"
        if end is not None:
            url += f"&endTime={end}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    rows = json.load(r)
                break
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(1.5*(attempt+1))
        if not rows:
            break
        out = rows + out
        got += len(rows)
        end = rows[0][0] - 1  # page backwards
        if len(rows) < n:
            break
    # closes, chronological
    closes = [float(r[4]) for r in out]
    highs = [float(r[2]) for r in out]
    lows = [float(r[3]) for r in out]
    return closes, highs, lows

def bps(x):
    return 10000.0 * x

# ---- signals: each yields a list of per-trade gross returns (fraction) ----
def sig_breakout(closes, highs, lows, lookback, hold):
    """Long on N-bar high breakout, hold H bars (momentum / larger-move capture)."""
    trades = []
    n = len(closes)
    i = lookback
    while i < n - hold:
        window_high = max(highs[i-lookback:i])
        if closes[i] > window_high:
            entry = closes[i]; exit_ = closes[i+hold]
            trades.append((i, (exit_-entry)/entry))
            i += hold  # non-overlapping
        else:
            i += 1
    return trades

def sig_tsmom(closes, highs, lows, lookback, hold):
    """Time-series momentum: long if past-lookback return > 0, else short. Hold H."""
    trades = []
    n = len(closes)
    i = lookback
    while i < n - hold:
        past = (closes[i]-closes[i-lookback])/closes[i-lookback]
        entry = closes[i]; exit_ = closes[i+hold]
        r = (exit_-entry)/entry
        trades.append((i, r if past > 0 else -r))
        i += hold
    return trades

def sig_revert(closes, highs, lows, lookback, hold):
    """Longer-horizon mean reversion: fade z-score extreme vs SMA(lookback)."""
    import statistics as st
    trades = []
    n = len(closes)
    i = lookback
    while i < n - hold:
        w = closes[i-lookback:i]
        m = sum(w)/len(w); sd = st.pstdev(w) or 1e-9
        z = (closes[i]-m)/sd
        entry = closes[i]; exit_ = closes[i+hold]
        r = (exit_-entry)/entry
        if z > 1.5:      trades.append((i, -r))   # too high -> short
        elif z < -1.5:   trades.append((i, r))    # too low -> long
        i += 1 if abs(z) < 1.5 else hold
    return trades

SIGNALS = {
    "breakout": (sig_breakout, [(24,6),(48,12),(72,24),(24,24)]),
    "tsmom":    (sig_tsmom,    [(24,6),(48,24),(168,48),(72,24)]),
    "revert":   (sig_revert,   [(24,6),(48,12),(72,24),(168,24)]),
}

def net_exp(trades, cost_bps):
    if not trades: return None, 0
    rs = [bps(r) - cost_bps for _, r in trades]
    return sum(rs)/len(rs), len(rs)

def evaluate(all_data):
    print(f"{'signal':10} {'params':12} {'symbol':8} {'n':>5} {'gross_bp':>9} {'net@18':>8} {'net@6':>8} {'WR%':>6} {'OOS_net@18':>10}")
    summary = {}
    for sname,(fn,param_grid) in SIGNALS.items():
        best_by_sym = {}
        for sym,(closes,highs,lows) in all_data.items():
            cut = int(len(closes)*0.6)
            # train: pick best params by net@18 on train
            best = None
            for params in param_grid:
                tr = fn(closes[:cut],highs[:cut],lows[:cut],*params)
                e,_ = net_exp(tr, 18)
                if e is not None and (best is None or e > best[1]):
                    best = (params, e)
            if not best: continue
            params = best[0]
            # test once on holdout (with purge = drop first `hold` bars of test)
            hold = params[1]
            th = closes[cut+hold:]; hh = highs[cut+hold:]; lh = lows[cut+hold:]
            tr_test = fn(th,hh,lh,*params)
            oos18,_ = net_exp(tr_test, 18)
            # full-sample descriptive
            trf = fn(closes,highs,lows,*params)
            g,_ = net_exp(trf, 0); n18,_ = net_exp(trf,18); n6,nn = net_exp(trf,6)
            wr = 100*sum(1 for _,r in trf if r>0)/len(trf) if trf else 0
            best_by_sym[sym] = oos18
            print(f"{sname:10} {str(params):12} {sym:8} {nn:>5} {g:>9.2f} {n18:>8.2f} {n6:>8.2f} {wr:>6.1f} {(oos18 if oos18 is not None else 0):>10.2f}")
        # portfolio OOS median across symbols
        vals = [v for v in best_by_sym.values() if v is not None]
        if vals:
            vals.sort()
            med = vals[len(vals)//2]
            pos = sum(1 for v in vals if v>0)
            summary[sname] = (med, pos, len(vals))
    print("\n=== VERDICT (OOS net after 18bp, per signal across 7 symbols) ===")
    for sname,(med,pos,tot) in summary.items():
        verdict = "CLEARS WALL" if med>0 and pos>tot/2 else "below wall"
        print(f"  {sname:10} median_OOS_net@18 = {med:+.2f} bp   symbols_positive={pos}/{tot}   -> {verdict}")

def main():
    all_data = {}
    for sym in SYMBOLS:
        try:
            closes,highs,lows = fetch(sym)
            all_data[sym] = (closes,highs,lows)
            print(f"fetched {sym}: {len(closes)} hourly bars", file=sys.stderr)
        except Exception as e:
            print(f"fetch {sym} failed: {e}", file=sys.stderr)
    print(f"\nData: {INTERVAL} bars, {HOURS}h target (~{HOURS//24}d), {len(all_data)} symbols\n")
    evaluate(all_data)

if __name__ == "__main__":
    main()
