# CryptoMaster — V10.13w Learning Integrity + Score Wiring + PnL Reconciliation Patch

## Role
You are a senior quant/backend engineer working directly in an existing live Python crypto trading bot project.  
Your task is to **analyze and patch the current codebase**, not to redesign it from scratch.

Work carefully, preserve existing functionality, and implement only targeted production-safe fixes.

---

## Current confirmed state from logs

The bot has improved decision observability and exit attribution, but the latest production logs reveal a **critical data integrity problem**:

### Trading summary says:
- `completed_trades = 137`
- `winrate = 88.5%`
- `profit factor = 3.55x`
- `expectancy = +0.00000363`
- multiple symbols show positive realized PnL
- exit attribution shows:
  - `SCRATCH_EXIT=84`
  - `PARTIAL_TP_25=41`
  - `MICRO_TP=6`
  - `EARLY_STOP=2`

### But Learning Monitor says at the same time:
- almost all pairs have:
  - `EV:+0.000`
  - `WR:0%`
  - `conv:1.0` for many mature BEAR regimes
- all features show:
  - `0.0`
  - `0%`
- example:
  - `ADAUSDT_BEAR_TREND n:15 EV:+0.000 WR:0% conv:-- (15/20) bandit:0.70`
  - `SOLUSDT_BEAR_TREND n:15 EV:+0.000 WR:0% conv:-- (15/20) bandit:0.70`

This is a hard contradiction.

### Additional confirmed correctness issues from logs
1. **Canonical decision logger still logs wrong score field**
   - detail log shows e.g. `score=0.210[n=7]`
   - canonical log still shows `score_raw=0.0000`
   - therefore canonical decision logging is still not wired to the true score source

2. **PnL/accounting mismatch still exists**
   - summary can show:
     - negative total profit
     - positive expectancy
     - high PF
     - high WR
   - these values may be computed from different sources or inconsistent trade subsets

3. **Exit structure confirms most edge is not from TP/SL**
   - TP = 0
   - SL = 0
   - most closes are scratch / partial / micro
   - current system behaves more like a defensive micro-harvest engine than classic TP/SL trend capture

4. **Some direction/regime combinations remain potentially ambiguous**
   - examples like `SHORT BULL_TREND` may be valid for fake breakout / counter impulse logic
   - but current logs still do not fully explain *why* that direction was selected

---

## Main diagnosis

The highest-priority issue is now:

# Learning Monitor is not hydrated from real realized trade outcomes.

The system appears to have:
- one data path for summary / trading stats
- another broken or stale data path for learning / pair-regime / feature statistics

This means adaptation may be running on false state.

That is unacceptable in live trading.

---

## Your mission

Implement **V10.13w** as a focused integrity patch with these goals:

1. **Repair Learning Monitor data flow**
2. **Fix canonical decision score wiring**
3. **Reconcile summary PnL / expectancy / winrate to one source of truth**
4. **Extend exit attribution from counts to net contribution**
5. **Add runtime mismatch detection**
6. **Freeze adaptive components when integrity mismatch is detected**

Do not remove existing features unless strictly necessary for correctness.

---

# REQUIRED IMPLEMENTATION

## Fix A — Learning Integrity Audit and Repair

### Goal
Ensure every closed trade updates Learning Monitor correctly and consistently.

### You must trace and validate the full path:
- trade close event
- close reason normalization
- realized gross pnl
- realized net pnl
- outcome classification
- learning update function call
- pair/regime counters
- feature counters
- EV histories
- convergence counters
- bandit / learning state persistence

### Likely failure modes to inspect
- wrong field names:
  - `action` vs `direction`
  - `pnl` vs `net_pnl`
  - `profit` vs `realized_pnl`
  - `regime` missing or stale at close time
- scratch / micro / partial exits bypassing LM update
- summary reading from one collection and LM from another
- compressed trade storage not included in LM rebuild
- closed trade classification written, but LM using only “full TP/SL” closes
- counters updated in memory but overwritten by stale DB snapshot
- convergence based only on `n`, while WR/EV never updated

### Required output behavior
For every closed trade, ensure LM receives:
- symbol
- regime at entry and/or exit (use the correct canonical one)
- side/action
- close_reason canonicalized
- gross pnl
- fees
- slippage
- net pnl
- classified outcome
- feature keys used by the signal
- whether the trade is counted toward EV/WR

### Add per-close audit log
Add a compact audit line for each close, e.g.

```text
[V10.13w LM_CLOSE] BTCUSDT BEAR_TREND SHORT close=SCRATCH_EXIT gross=+0.00000410 fee=-0.00000120 slip=-0.00000040 net=+0.00000250 outcome=WIN lm_pair=yes lm_features=4
```

If LM update is skipped, log exactly why:
```text
[V10.13w LM_SKIP] BTCUSDT close=... reason=missing_regime
```

---

## Fix B — Canonical Decision Score Wiring

### Goal
Make canonical decision log show the **real decision score**, not zero.

### Problem confirmed
- detail log shows nonzero score, e.g. `score=0.210`
- canonical decision log shows `score_raw=0.0000`

### Required fix
Identify the exact score variable actually used in decision logic and pass that into canonical logger.

### Canonical decision log must include
- symbol
- action
- regime
- setup tag / source
- `ev_raw`
- `ev_final`
- `score_raw`
- `score_threshold`
- `confidence`
- `auditor_factor`
- `decision`
- `decision_reason`
- `direction_source`

Example target format:
```text
[V10.13w DECISION] SOLUSDT SHORT BEAR_TREND setup=fake_breakout dir_src=signal_engine ev_raw=0.0500 ev_final=0.0348 score_raw=0.2100 score_threshold=0.1728 confidence=0.5714 auditor_factor=1.00 | ACCEPT reason=score>=threshold
```

If score is unavailable, do **not** silently print zero. Log:
```text
score_raw=NA
```
and fix upstream wiring.

---

## Fix C — PnL / Expectancy / WR Reconciliation

### Goal
All major summary metrics must be derived from the same canonical realized trade dataset.

### Problem
Logs show possible contradictions such as:
- negative total profit
- positive expectancy
- high winrate
- high PF

This may be legitimate only if:
- different metrics use different trade subsets
- or scratch exits are treated inconsistently
- or net vs gross is mixed

### Required action
Create one canonical trade accounting path and use it consistently for:
- total net pnl
- expectancy
- winrate
- profit factor
- per-symbol pnl
- per-regime pnl
- outcome counts

### Explicitly define outcome policy
Document in code comments and apply consistently:
- what counts as WIN
- what counts as LOSS
- what counts as FLAT
- whether scratch counts as win only if **net pnl > 0**
- whether partial-only closes count as separate win/loss or aggregated trade outcome

### Add runtime reconciliation log
Every snapshot or periodic interval, print:

```text
[V10.13w RECON]
summary_trade_count=137 lm_trade_count=137
summary_net_pnl=-0.00014773 lm_net_pnl=-0.00014770
summary_wr=0.8850 lm_wr=0.8832
summary_pf=3.55 lm_pf=3.54
status=OK
```

If mismatch exceeds tolerance:
```text
[V10.13w RECON] status=MISMATCH field=wr delta=0.412
```

Tolerance should be small and explicit.

---

## Fix D — Adaptive Safety Freeze on Integrity Failure

### Goal
Never let adaptive components learn from broken state.

### Required behavior
If reconciliation detects mismatch or LM hydration failure:
- disable / downweight:
  - feature weight adaptation
  - bandit updates
  - learning-based multipliers
  - regime preference boosts
- keep bot operational in a deterministic safe mode if possible
- emit a strong log:

```text
[V10.13w SAFE_MODE] Learning integrity mismatch detected → freezing adaptive updates
```

This freeze should affect adaptation, not necessarily all trading.

---

## Fix E — Exit Attribution Net Contribution

### Goal
Extend Fix 7 so exit attribution shows not only counts, but actual economic contribution.

### Current state
You already have counts like:
- `SCRATCH_EXIT=84`
- `PARTIAL_TP_25=41`
- `MICRO_TP=6`

That is not enough.

### Required additions
For each exit type, track:
- count
- gross pnl sum
- fee sum
- slippage sum
- net pnl sum
- avg net pnl
- median net pnl if easy
- % contribution to total pnl
- win/loss/flat counts

### Example desired output
```text
[V10.13w EXIT_ATTRIBUTION]
SCRATCH_EXIT   count=84  net=+0.00008120 avg=+0.00000097 pct_total=31.4%
PARTIAL_TP_25  count=41  net=+0.00010250 avg=+0.00000250 pct_total=39.6%
MICRO_TP       count=6   net=+0.00000920 avg=+0.00000153 pct_total=3.6%
EARLY_STOP     count=2   net=-0.00000470 avg=-0.00000235 pct_total=-1.8%
FULL_SL        count=1   net=-0.00005089 avg=-0.00005089 pct_total=-19.7%
```

Also provide:
- per-symbol exit attribution
- per-regime exit attribution

Keep it compact.

---

## Fix F — Regime/Direction Explainability

### Goal
Disambiguate logs like `SHORT BULL_TREND`.

This is not necessarily wrong, but it must be explainable.

### Required additions
Add to decision log:
- `setup_tag`
- `direction_source`
- `regime_source`
- `countertrend=yes/no`

Example:
```text
[V10.13w DECISION] ETHUSDT SHORT BULL_TREND setup=fake_breakout countertrend=yes dir_src=pattern_engine regime_src=regime_predictor ...
```

This allows distinguishing:
- valid short against bull regime because setup is reversal/fake breakout
- invalid contradictory state

---

# REQUIRED VALIDATION

After patching, validate with real or replay data and print:

## 1. Learning integrity validation
Show:
- summary trades vs LM trades
- summary WR vs LM WR
- summary net pnl vs LM net pnl
- feature stats nonzero when expected
- pair/regime WR/EV no longer stuck at zero when real trades exist

## 2. Decision score validation
Show at least 3 examples where:
- detail score and canonical `score_raw` match

## 3. Exit attribution validation
Show at least one summary where:
- exit types include net contribution, not only counts

## 4. Safe mode validation
Demonstrate one forced mismatch or explain with code path how integrity freeze would trigger.

---

# IMPORTANT CONSTRAINTS

- Do not redesign the whole bot
- Do not remove existing modules unless necessary
- Do not break live execution path
- Keep backward compatibility as much as possible
- Prefer small, surgical changes
- Preserve existing logging style where possible
- Any new fields added to DB/state must be optional-safe
- If using cached or compressed trade collections, support both old and new schema

---

# DELIVERABLE FORMAT

Return:

## 1. Root-cause analysis
Very short, precise.

## 2. Files changed
List all modified files.

## 3. Full code patches
Provide complete updated functions or full files when necessary.

## 4. Validation summary
Show before/after behavior.

## 5. Remaining risks
Be honest and specific.

---

# SPECIAL NOTE

Do **not** assume current performance is truly good just because summary WR is high.  
Current logs prove the internal state is inconsistent.  
Correctness and consistency are more important than superficial WR.

Your priority is to make sure the bot:
- knows what happened,
- learns from the true realized outcomes,
- reports truthful metrics,
- and disables adaptation when truth is uncertain.
