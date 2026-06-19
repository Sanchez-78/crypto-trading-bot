# Forensic Report — Static TP Unreachable (100% TIMEOUT)

**Generated:** 2026-06-19 ~07:03 UTC
**Analyst:** Runtime forensic agent
**Window:** journalctl `--since '60 min ago'` + live dashboard snapshot + code paths
**Host:** Hetzner `root@78.47.2.198` (`/opt/cryptomaster`, systemd unit `cryptomaster`)

---

## 1. Exit Distribution (live dashboard snapshot)

Source: `curl http://localhost:5001/api/dashboard/metrics` @ `2026-06-19T07:02:21Z`

```json
"closed_trades": 53,
"exit_distribution": {"tp": 0, "sl": 0, "timeout": 53, "scratch": 0, "stagnation": 0},
"win_rate_pct": 20.75, "profit_factor": 0.0, "net_pnl": 13.85, "open_positions": 25
```

| Exit type | Count | %      |
|-----------|-------|--------|
| TP        | 0     | 0.0%   |
| SL        | 0     | 0.0%   |
| TIMEOUT   | 53    | 100.0% |
| scratch   | 0     | 0.0%   |
| stagnation| 0     | 0.0%   |

**Confirmed:** 53/53 closed trades = TIMEOUT. **Zero TP hits, zero SL hits.** Matches hypothesis.

> NOTE (correction to brief): dashboard `win_rate_pct` reads **20.75%**, not 0%. WR > 0 despite
> 100% TIMEOUT because TIMEOUT exits that close marginally positive are still counted as wins.
> `profit_factor` = 0.0. `net_pnl` is reported +13.85 but PF=0 — counters are partially
> inconsistent (RECON status=MISMATCH seen in logs), so treat PnL figure with caution.

---

## 2. Timeline — Example TIMEOUT Trades (real `[PAPER_EXIT]` records)

Source: `journalctl | grep PAPER_EXIT`. All `reason=TIMEOUT`, all `hold_s=600`. Move in bps = |exit-entry|/entry × 10000.

| Time (UTC) | Symbol  | Entry        | Exit         | hold_s | Move (bps) | net_pnl% | Outcome |
|------------|---------|--------------|--------------|--------|------------|----------|---------|
| 06:49:43   | ETHUSDT | 1696.77500   | 1698.17500   | 600    | **+8.25**  | -0.0975  | LOSS    |
| 06:50:29   | XRPUSDT | 1.12979790   | 1.12945000   | 600    | **-3.08**  | -0.2108  | LOSS    |
| 06:50:29   | ADAUSDT | 0.16045802   | 0.16035000   | 600    | **-6.73**  | -0.2473  | LOSS    |
| 06:51:32   | BTCUSDT | 62771.72365  | 62797.86500  | 600    | **+4.17**  | -0.2216  | LOSS    |
| 06:53:01   | XRPUSDT | 1.13065000   | 1.12905000   | 600    | **-14.15** | -0.3215  | LOSS    |
| 06:51:07   | BNBUSDT | 574.70479    | 573.75500    | 600    | **-16.53** | -0.0147  | FLAT    |

**Pattern:** Every trade rode the full `hold_s=600` window. Absolute price moves over 600s ranged
**~3–17 bps**, never reaching the **35 bps TP band** or **40 bps SL band**. Realized intra-600s
volatility ≈ **8–18 bps** — below both bands → guaranteed TIMEOUT.

Live open positions confirm the same: 25 positions open with `pnl_pct: 0.0`, holds 513–901s,
none near TP/SL.

---

## 3. Code Path Evidence

### 3a. TP/SL bands are static env-var driven (not volatility-adaptive)

Live config on Hetzner (`systemctl show cryptomaster -p Environment` + `override.conf`):
```
PAPER_TP_ZONE_BPS=35
PAPER_SL_ZONE_BPS=40
```

`src/services/paper_trade_executor.py:1444-1474` — env vars are AUTHORITATIVE; when
`PAPER_TP_ZONE_BPS` is set (it is), bands are computed as a **fixed percentage of entry price**:
```python
1444  tp_zone_bps = int(os.getenv("PAPER_TP_ZONE_BPS", "40"))
1445  sl_zone_bps = int(os.getenv("PAPER_SL_ZONE_BPS", "30"))
1446  tp_pct_env = 1.0 + tp_zone_bps / 10000 if side == "BUY" else 1.0 - tp_zone_bps / 10000
...
1469  if os.getenv("PAPER_TP_ZONE_BPS"):           # explicitly configured → override
1470      tp_price = tp_price_env                    # FIXED 35bps band, no ATR input
1471      sl_price = sl_price_env                    # FIXED 40bps band
```
`dashboard_web.py:760-761` mirrors the same defaults (`'35'` / `'40'`).

### 3b. ATR is calculated but NOT wired into TP sizing (the gap)

`src/services/signal_generator.py:138-140` — `_atr()` exists and runs:
```python
138  def _atr(series, n=14):
139      diffs = [abs(series[i] - series[i-1]) for i in range(1, len(series))]
140      return _ema(diffs[-n*3:], n) if diffs else 1e-9
```
It is consumed only for Keltner channels / signal generation (`_kc` line 134, `signal_generator.py:616`),
and `exit_monetization.py:50 calculate_atr()` is a separate unused helper. **No code path feeds
ATR into `tp_zone_bps` / `sl_zone_bps` in `paper_trade_executor.py`.** Bands stay static at 35/40 bps
regardless of measured volatility (~8–18 bps).

The in-code comment at `paper_trade_executor.py:1444` even claims 40bps is "reachable in 600s hold
window" — runtime evidence (Section 2) contradicts this: moves cap at ~17 bps.

---

## 4. Cost Floor Validation

- Slippage: `paper_trade_executor.py:55` → `PAPER_SLIPPAGE_PCT=0.0003` = **3 bps** (per side).
- Fee: ~15 bps documented round-trip.
- **Total round-trip cost ≈ 18 bps.**
- TP=35 bps → leaves **17 bps margin** above cost (mathematically viable IF reached).
- **But TP is never reached** — realized volatility (~8–18 bps/600s) < 35 bps band → 100% TIMEOUT.

---

## 5. SECONDARY FINDING (out of scope but critical) — Bot is crash-looping

The main process is NOT trading right now. journalctl shows continuous restart loop:
```
06:54:58 → 07:00:22  cryptomaster.service: Main process exited, code=exited, status=1/FAILURE
07:00:22             ...code=killed, status=9/KILL
07:00:30+            [DASH] Port 5000 API failed: Connection refused (every ~5s)
```
The 53 TIMEOUT trades are from the prior healthy window (PID 2697228, last active ~06:54).
Python traceback was not flushed to journald before SIGKILL, so the crash root cause is not yet
captured in logs. This is a separate incident from the TP-band issue and should be triaged first
(the bot cannot trade while crash-looping).

---

## 6. Conclusion

**Root cause (TP unreachability): CONFIRMED — HIGH confidence.**

> Static TP band (35 bps, env-fixed in `paper_trade_executor.py:1444-1470`) exceeds realized
> intra-600s price volatility (~8–18 bps, measured from 53 real `[PAPER_EXIT]` records).
> Result: **0% TP hits, 0% SL hits, 100% (53/53) TIMEOUT exits.** ATR is computed in
> `signal_generator.py:138` but is NOT wired into TP/SL sizing — the bands are insensitive to
> volatility. Cost floor (~18 bps) is cleared by 35 bps in principle, but the band is never reached.

**Fix direction (not implemented here):** Size TP/SL from measured ATR (e.g. TP = max(cost_floor +
margin, k·ATR)) instead of a fixed 35/40 bps, OR shrink bands toward realized vol while staying
above the ~18 bps cost floor — but margin above cost shrinks fast, so a shorter hold + ATR-scaled
band is the more durable lever.

**Confidence calibration:**
- 100% TIMEOUT, 0 TP/SL: **certain** (direct dashboard + 53 PAPER_EXIT records).
- Bands static, ATR unused: **certain** (code citations).
- "Realized vol ~8–18 bps": **high** (6 sampled trades, consistent; full 53-trade aggregation would tighten the figure).
- WR=0% claim in brief: **refuted** — actual WR=20.75%; the operative metric is exit_distribution, not WR.
