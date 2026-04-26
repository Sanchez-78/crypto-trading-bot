# CryptoMaster V10.13u — Post-Deploy Validation + Next Patch Prompt

> Goal: verify deployed PATCH 1–6, then apply only small follow-up fixes if validation shows remaining inconsistencies. Do not rewrite architecture. Preserve live bot behavior unless a guard is clearly wrong.

## Context
The following patches were deployed:

1. **Maturity Type Safety**
   - `_safe_get()` and `_extract_trade_count()` added.
   - Maturity oracle should no longer crash on mixed `dict/int/list` sources.
   - Expected log: `[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False...`

2. **Canonical Profit Factor**
   - Economic health now uses `canonical_profit_factor` from the same source as dashboard.
   - Expected log: `[ECON_CANONICAL] pf=0.75 source=...`

3. **LearningMonitor Hydration Depth**
   - Normalizes `symbol/sym`, `regime/reg`, and PnL field variants.
   - Counts real wins/losses/flats from net PnL.
   - Expected: LM pairs should show real WR/EV, not universal `WR=50% EV=0.0`.

4. **RR Consistency Guard**
   - `canonical_rr(tp_distance, sl_distance)` added.
   - Risk/reward should be computed consistently across RDE, execution, dashboard/logs.

5. **Runtime Commit/Branch Injection**
   - Reads `COMMIT_SHA` / `GIT_BRANCH` from GitHub Actions env vars.
   - Falls back to local git.
   - Expected runtime log: real `commit=<sha>` and `branch=main`, not `UNKNOWN`.

6. **Comprehensive Tests**
   - 17 tests covering type safety, canonical PF, LM hydration normalization, RR, runtime version.

## Validation Checklist
Run on the server after deploy:

```bash
sudo systemctl restart cryptomaster
sudo journalctl -u cryptomaster -n 250 --no-pager
```

Check these exact success signals:

```text
[RUNTIME_VERSION] ... commit=<real_sha> branch=main
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False
[ECON_CANONICAL] pf=0.75 source=canonical
[7/7d.5] LM hydrated: 500 trades across ... pairs
```

Then confirm these old problems are gone:

```text
NO: [MATURITY_PATCH1] Computation failed: 'int' object has no attribute 'get'
NO: LearningMonitor all pairs WR=50% EV=0.0 after hydration
NO: Economic PF different from dashboard PF
NO: RUNTIME_VERSION commit=UNKNOWN branch=UNKNOWN
NO: UI says RR 1.5 while RDE logs rr=1.25 for the same decision path
```

## Expected Healthy State
After the patch, these values should align:

- Dashboard trades: `500`
- Maturity oracle trades: `500`, not `0` or `7631`
- Bootstrap state: `bootstrap=False` once canonical closed trades >= configured maturity threshold
- Dashboard PF and economic PF: same value from canonical source
- LM pair stats: real WR and EV per `(symbol, regime)`, not default 50% everywhere
- Runtime version: real commit and branch

## If Problems Remain — Minimal Follow-up Patch

### A. If maturity still says `trades=0` or `bootstrap=True`
Inspect all callers of maturity computation. Enforce canonical source priority:

```python
trade_count = _extract_trade_count(canonical_state) or _extract_trade_count(canonical_closed_trades)
```

Do not allow Redis/model-state legacy totals to override canonical closed trade count. Legacy totals may be logged as diagnostics only.

### B. If LM still shows `WR=50% EV=0.0`
Patch `hydrate_from_canonical_trades()` to reject default/fallback stats when real `net_pnl` exists.

Rules:

```python
if net_pnl > eps: win += 1
elif net_pnl < -eps: loss += 1
else: flat += 1
wr = win / max(win + loss, 1)
ev = mean(non_flat_or_all_net_pnl)
```

Log a compact audit:

```text
[LM_HYDRATE_AUDIT] pairs=17 trades=500 wins=79 losses=24 flats=397 ev=... wr=76.7%
[LM_PAIR] ETHUSDT_BEAR_TREND n=44 wins=... losses=... flats=... wr=... ev=...
```

### C. If economic health still reports PF 5.33 while dashboard PF is 0.75
Find the old economic PF calculation and delete/disable it. Only use:

```python
pf = canonical_profit_factor(canonical_closed_trades)
```

Add one log source marker:

```text
[ECON_CANONICAL] pf=<value> source=canonical_closed_trades wins=<gross_win> losses=<gross_loss>
```

### D. If RR logs still conflict
Search for all local RR formulas:

```bash
grep -R "rr\|risk.reward\|tp_distance\|sl_distance" -n src bot2 | head -100
```

Replace local formulas with `canonical_rr()`. The same signal must not show `rr=1.25` in RDE and `RR 1.5:1` in UI.

### E. If commit is still UNKNOWN on server
Patch GitHub Actions deploy step to export variables into the remote service environment or `.env` before restart:

```bash
echo "COMMIT_SHA=${GITHUB_SHA}" > .runtime_version.env
echo "GIT_BRANCH=${GITHUB_REF_NAME}" >> .runtime_version.env
```

Then systemd must load it:

```ini
EnvironmentFile=/path/to/project/.runtime_version.env
```

Run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cryptomaster
```

## Guardrails
- Do not reset Firebase.
- Do not wipe model_state.
- Do not change trading thresholds unless validation proves a specific gate is wrong.
- Do not add new AI/strategy layers.
- Keep Firestore reads under budget; validation logs must use already-loaded data.
- Prefer diagnostics and source-of-truth fixes over behavioral tuning.

## Acceptance Criteria
Patch is accepted only when one startup + 3 cycles show:

```text
[RUNTIME_VERSION] commit=<real_sha> branch=main
[V10.13u/PATCH_MATURITY] source=canonical trades=500 bootstrap=False cold_start=False
[ECON_CANONICAL] pf=<same_as_dashboard>
[LM_HYDRATE_AUDIT] trades=500 pairs>=10 wr=<not_default> ev=<not_default>
No MATURITY_PATCH crash
No commit UNKNOWN
No PF mismatch
No universal LM WR=50% EV=0.0
```

## Final Output Required From Claude/Codex
Return only:

1. Files changed
2. Exact bug found
3. Patch summary
4. Test results
5. 20-line production log proof
6. Any remaining risk
