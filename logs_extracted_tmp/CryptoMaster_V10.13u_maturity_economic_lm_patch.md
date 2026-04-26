# CryptoMaster V10.13u+1 — Incremental Patch: Maturity/Economic/LM Consistency

Role: senior Python quant/backend engineer. Work incrementally. Do not rewrite architecture. Preserve live trading safety, Firebase quota limits, canonical metrics, and current V10.13u+1 behavior. Implement only the fixes below, then run tests/smoke checks.

## Current deployed status

Runtime is live and not stuck in Firebase degraded SAFE_MODE anymore. Logs confirm:

```text
[RUNTIME_VERSION] version=V10.13u+1 commit=UNKNOWN branch=UNKNOWN
Firebase health OK ✓
[7/7d.5] LM hydrated: 100 trades across 17 pairs ✓
decision=TAKE
[EXEC] regime=BEAR_TREND ...
```

Known remaining issues from logs:

```text
[MATURITY_PATCH1] Computation failed: 'int' object has no attribute 'get', using cache
Maturity computed: trades=0 bootstrap=True cold_start=True
```

Also inconsistent metrics:

```text
Dashboard Profit Factor 0.75x
Economic PF 5.33
```

And LM hydration looks shallow/defaulted:

```text
ETH BEAR_TREND n:44 EV:+0.000 WR:50%
```

Plus possible RR inconsistency:

```text
rr=1.25 decision=TAKE
Dashboard says TP:1.2xATR / SL:0.8xATR RR 1.5:1
```

## Objective

Fix canonical state consistency without increasing Firebase read pressure. After patch:

1. maturity oracle must not crash on mixed dict/int state.
2. maturity must use canonical closed trades / canonical state and return realistic trade counts, not `trades=0`.
3. economic health must use the same canonical profit factor as dashboard.
4. LearningMonitor hydration must populate real WR/EV per `(symbol, regime)`, not default 50%/0.0 everywhere.
5. runtime version must show real commit/branch when available.
6. RR displayed and RR accepted by RDE must be consistent.

## Hard constraints

- Do not wipe Firebase.
- Do not add high-frequency Firestore reads.
- Do not remove existing safety gates.
- Do not increase position sizing until maturity/economic consistency is validated.
- Do not break Android/dashboard canonical fields.
- Prefer pure functions and unit tests.
- Keep logs compact but diagnostic.

---

# Patch 1 — Fix maturity oracle type safety and canonical source

## Problem

Maturity computation crashes:

```text
'int' object has no attribute 'get'
```

Then falls back to cache and reports:

```text
trades=0 bootstrap=True cold_start=True
```

even though logs show 500 canonical trades and 7631 completed trades.

## Required implementation

Find maturity computation in `src/services/realtime_decision_engine.py` or related maturity/unified oracle module.

Add a safe accessor helper:

```python
def _safe_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default
```

Add robust canonical trade count extraction:

```python
def _extract_trade_count(*sources) -> int:
    best = 0
    for src in sources:
        if src is None:
            continue
        if isinstance(src, int):
            best = max(best, src)
            continue
        if isinstance(src, (list, tuple)):
            best = max(best, len(src))
            continue
        if isinstance(src, dict):
            for k in ("closed_trades", "completed_trades", "total_trades", "trades", "n"):
                v = src.get(k)
                if isinstance(v, int):
                    best = max(best, v)
                elif isinstance(v, (list, tuple)):
                    best = max(best, len(v))
    return best
```

Use this count in unified maturity. Preferred source priority:

1. canonical closed trades snapshot count
2. canonical_state completed/closed trade count
3. dashboard canonical metrics count
4. LM completed count
5. old cached maturity count

Do not let one malformed field crash maturity computation.

## Acceptance log

Expected after restart:

```text
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False cold_start=False min_pair_n=...
```

Or if rules still require reduced mode because pair-level data is low:

```text
[V10.13u/PATCH_MATURITY] source=canonical trades=500 global_mature=True pair_bootstrap=True min_pair_n=2
```

But this must never happen again when canonical trades exist:

```text
trades=0 bootstrap=True cold_start=True
```

---

# Patch 2 — Use canonical Profit Factor everywhere

## Problem

Dashboard says PF `0.75x`, economic health says PF `5.33`. This means economic scoring still uses another source or excludes scratch/flats differently.

## Required implementation

Find economic health calculation, likely in one of:

- `src/services/canonical_metrics.py`
- `src/services/learning_monitor.py`
- `src/services/economic_*`
- dashboard/status rendering module

Require single source of truth:

```python
from src.services.canonical_metrics import canonical_profit_factor
```

Economic health must call the same canonical PF function used by dashboard, with the same input closed trades/canonical state.

Add explicit log once per status cycle:

```text
[ECON_CANONICAL] pf=0.75 source=canonical_closed_trades trades=500 wins=79 losses=24 flats=397
```

If economic health intentionally excludes scratch/flats or uses a different subset, rename it clearly, e.g. `pf_decisive_only`, and display both:

```text
PF canonical: 0.75 | PF decisive_only: 5.33
```

But do not label subset PF as overall Economic PF.

## Acceptance

Dashboard PF and Economic PF must match unless the label explicitly says subset.

---

# Patch 3 — Fix LearningMonitor canonical hydration depth

## Problem

Hydration reports success:

```text
LM hydrated: 100 trades across 17 pairs
```

But pair stats look neutral/defaulted:

```text
n:44 EV:+0.000 WR:50%
```

Likely hydration increments `n`, but not true wins/losses/net PnL.

## Required implementation

In `learning_monitor.py`, update `hydrate_from_canonical_trades(closed_trades)`.

For every closed trade, normalize:

```python
sym = trade.get("symbol") or trade.get("sym")
reg = trade.get("regime") or trade.get("reg") or "UNKNOWN"
pnl = trade.get("net_pnl") or trade.get("pnl") or trade.get("pnl_pct") or 0.0
exit_type = trade.get("exit_type") or trade.get("reason") or "UNKNOWN"
```

Use actual net PnL to classify:

```python
EPS = 1e-12
if pnl > EPS: win
elif pnl < -EPS: loss
else: flat
```

Per `(sym, reg)` store/update at minimum:

```python
n_total
n_decisive = wins + losses
wins
losses
flats
gross_win
abs_gross_loss
net_pnl_sum
avg_pnl
wr_decisive = wins / max(wins + losses, 1)
wr_all = wins / max(n_total, 1)
ev = avg_pnl
last_seen_ts
```

Important: do not force WR to 0.50 when there is real decisive data. Use 0.50 only when `wins + losses == 0`.

Feature hydration should also use actual PnL/win outcome, not only increment count.

Add compact hydration audit:

```text
[LM_HYDRATE_CANONICAL] trades=500 pairs=17 decisive=103 flats=397 wr_decisive=0.767 net=-0.000527 pf=0.75
[LM_HYDRATE_PAIR] ETHUSDT_BEAR_TREND n=44 decisive=... wr=... ev=...
```

Print only top 5 pairs by n to avoid log spam.

## Acceptance

LM should no longer show every pair as WR 50% if decisive trades exist. Example expected style:

```text
ETH BEAR_TREND n:44 WR:72% EV:-0.000002
```

Exact values depend on trade data.

---

# Patch 4 — RR consistency guard

## Problem

Logs show:

```text
rr=1.25 decision=TAKE
```

while dashboard says:

```text
TP: 1.2xATR / SL: 0.8xATR (RR 1.5:1)
```

## Required implementation

Find where RDE computes/logs `rr`, and where execution computes TP/SL.

Add one canonical RR function:

```python
def canonical_rr(tp_distance: float, sl_distance: float) -> float:
    if sl_distance <= 0:
        return 0.0
    return abs(tp_distance) / abs(sl_distance)
```

Use same RR value for:

- RDE decision log
- execution validation
- dashboard text
- rejection reason

If configured minimum RR is 1.5, enforce before TAKE:

```python
if rr < min_rr:
    return reject("RR_TOO_LOW", rr=rr, min_rr=min_rr)
```

If forced/cold-start mode intentionally allows lower RR, do not silently TAKE. Log explicitly:

```text
[RR_SOFT_BOOTSTRAP] rr=1.25 min=1.50 size×0.50 allowed=True reason=forced_explore
```

Preferred safer behavior: do not allow RR below 1.5 unless an explicit config flag exists.

## Acceptance

No more ambiguous `rr=1.25 decision=TAKE` without an explicit allowance reason.

---

# Patch 5 — Runtime commit/branch injection

## Problem

Runtime log still says:

```text
commit=UNKNOWN branch=UNKNOWN
```

## Required implementation

In runtime version module, use env first:

```python
COMMIT_SHA = os.getenv("COMMIT_SHA") or os.getenv("GITHUB_SHA")
GIT_BRANCH = os.getenv("GIT_BRANCH") or os.getenv("GITHUB_REF_NAME")
```

Fallback to local git:

```python
subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], timeout=1)
subprocess.check_output(["git", "branch", "--show-current"], timeout=1)
```

Never crash if git unavailable.

Update `.github/workflows/deploy.yml` service env or deployment script to export:

```yaml
env:
  COMMIT_SHA: ${{ github.sha }}
  GIT_BRANCH: ${{ github.ref_name }}
```

If using systemd on Hetzner, ensure these env vars are written to the app `.env` or injected into service restart command.

## Acceptance

Runtime log should show:

```text
[RUNTIME_VERSION] version=V10.13u+2 commit=<short-or-full-sha> branch=main
```

---

# Patch 6 — Tests / smoke checks

Add or update tests. Minimal required tests:

## Maturity tests

```python
def test_maturity_accepts_int_dict_list_sources():
    assert _extract_trade_count(5, {"trades": 10}, [1, 2, 3]) == 10
```

```python
def test_maturity_no_crash_on_malformed_fields():
    src = {"trades": {"bad": "shape"}, "completed_trades": 500}
    assert _extract_trade_count(src) == 500
```

## Canonical PF consistency test

Same input trades must produce same PF for dashboard and economic function.

## LM hydration test

Use 4 trades:

- BTC BULL +0.01
- BTC BULL -0.02
- BTC BULL 0.0
- ETH BEAR +0.03

Assert:

```text
BTC_BULL n_total=3 wins=1 losses=1 flats=1 wr_decisive=0.5 ev=(-0.01/3)
ETH_BEAR n_total=1 wins=1 losses=0 wr_decisive=1.0 ev=0.03
```

## RR test

Assert that `rr < min_rr` rejects unless explicit bootstrap override is enabled.

---

# Post-deploy verification commands

Run locally first:

```bash
python -m pytest tests -q
python -m compileall src
```

On Hetzner after deploy:

```bash
sudo systemctl restart cryptomaster
journalctl -u cryptomaster -n 250 --no-pager
```

Look for these success lines:

```text
[RUNTIME_VERSION] version=V10.13u+2 commit=... branch=main
[V10.13u/PATCH_MATURITY] source=canonical trades=500
[ECON_CANONICAL] pf=0.75 source=canonical_closed_trades trades=500
[LM_HYDRATE_CANONICAL] trades=500 pairs=17 decisive=103 flats=397
```

And confirm these are gone:

```text
'int' object has no attribute 'get'
Maturity computed: trades=0 bootstrap=True cold_start=True
Economic: PF: 5.33   # if dashboard PF is 0.75 and label is not subset
commit=UNKNOWN branch=UNKNOWN
rr=1.25 decision=TAKE  # without explicit RR override log
```

---

# Implementation order

1. Fix maturity type safety and canonical count.
2. Fix economic PF canonical source.
3. Fix LM hydration real WR/EV.
4. Add RR consistency guard/log.
5. Add runtime commit/branch.
6. Add tests.
7. Deploy and verify logs.

Do not implement roadmap/economic monetization features in this patch. This is a safety/consistency patch only.
