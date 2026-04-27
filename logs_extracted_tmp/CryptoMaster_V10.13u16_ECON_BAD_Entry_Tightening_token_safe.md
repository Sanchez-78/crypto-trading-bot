# CryptoMaster V10.13u+16 — ECON BAD Entry Tightening + Churn Control

## Context

Recent Hetzner logs after V10.13u+14/+15 show close-lock/partial-TP issues are no longer the main problem. No visible `CLOSE_LOCK_STALE_RELEASE`, `CLOSE_FORCE_RECONCILE`, `EXIT_INTEGRITY_ERROR`, or `Traceback` in the provided window.

Current live state:
- `Economic: 0.340 [BAD]`
- `Profit Factor 0.73x`
- `PARTIAL_TP_25`: 58 trades, WR 97%, net `+0.00049709`, avg `+0.00000857`
- `STAGNATION_EXIT`: 73 trades, net `-0.00025955`, avg `-0.00000356`
- `SCRATCH_EXIT`: 325 trades, net `-0.00063701`, avg `-0.00000196`, 65% trades, 113% pnl drag
- Bot still emits `decision=TAKE` while ECON BAD:
  - `ev=0.0300`, `p=0.5000`, `af=0.70`, `coh=0.500–0.558`
  - sometimes `af=0.35`
  - one forced signal: `Generated FORCED signal LONG`

Interpretation:
- Close-path safety patches likely worked.
- Main remaining issue is economic churn: bot continues taking low-confidence/cold-start trades while PF is bad.
- SCRATCH_EXIT remains the dominant loss source.
- PARTIAL_TP is profitable; do not break it.
- Next patch should be entry-side conservative tightening, not another close-lock patch.

## Goal

Implement V10.13u+16 as a small, surgical safety patch:

1. When `lm_economic_health().status == "BAD"` or canonical PF < 1.0:
   - block weak cold-start `TAKE` decisions
   - reduce forced exploration
   - require stronger EV/coherence/probability before entry
2. Preserve:
   - canonical PF formula
   - EV-only principle
   - close-lock fixes V10.13u+8..u+15
   - PARTIAL_TP behavior
   - Firebase read/write budget
3. Add clear logs and tests.

## Required Behavior

### 1. ECON BAD minimum entry quality

In `src/services/realtime_decision_engine.py`, add/centralize an ECON BAD guard before final `TAKE`.

When ECON BAD is active, reject if any of these are true:

```python
ev < 0.045
score < 0.22
p < 0.54
coh < 0.58
af < 0.70
```

Exception:
- Allow only if this is a mature proven pair/regime:
  - `pair_n >= 25`
  - pair/regime canonical EV > 0
  - pair/regime WR >= 0.58
  - net expectancy > 0
  - not in loss streak / velocity guard

Log on block:

```text
[ECON_BAD_ENTRY_BLOCK] symbol=... reason=weak_quality ev=... score=... p=... coh=... af=... pf=... net_pnl=...
```

Log on allowed exception:

```text
[ECON_BAD_ENTRY_ALLOW] symbol=... reason=proven_pair ev=... score=... p=... coh=... pair_n=... wr=...
```

### 2. Disable/limit forced exploration during ECON BAD

Where forced exploration / fallback / anti-deadlock creates low-quality signals, add:

```python
if econ_bad and pf < 1.0:
    # no forced/cold exploration unless quality is above strict thresholds
```

Strict forced exploration thresholds during ECON BAD:

```python
ev >= 0.050
p >= 0.55
coh >= 0.60
af >= 0.70
```

Block log:

```text
[ECON_BAD_FORCED_BLOCK] symbol=... ev=... p=... coh=... af=... pf=...
```

### 3. Respect PARTIAL_TP profitability

Do not modify:
- `PARTIAL_TP_25`
- partial TP lock bypass
- partial TP counters
- partial TP realization accounting

Current `PARTIAL_TP_25` is profitable and should remain untouched.

### 4. Add rolling observation log

Add one throttled log every 60 seconds:

```text
[ECON_BAD_GUARD_SUMMARY] pf=... blocked=... allowed=... forced_blocked=... scratch_net=... stag_net=... partial_net=...
```

Keep it cheap. Do not add Firestore reads in the hot path. Use existing in-memory/cached metrics only.

## Tests

Add tests to `tests/test_v10_13u_patches.py`:

1. `test_econ_bad_blocks_low_ev_take`
   - ECON BAD, `ev=0.03`, `p=0.50`, `coh=0.50`, `af=0.70`
   - expect reject, log reason `ECON_BAD_ENTRY_BLOCK`

2. `test_econ_bad_blocks_low_af`
   - ECON BAD, otherwise acceptable but `af=0.35`
   - expect reject

3. `test_econ_bad_blocks_forced_explore_low_quality`
   - forced signal under ECON BAD with `ev=0.03`
   - expect blocked

4. `test_econ_bad_allows_strong_signal`
   - ECON BAD but `ev>=0.05`, `p>=0.55`, `coh>=0.60`, `af>=0.70`
   - expect can proceed through normal gates

5. `test_econ_bad_allows_proven_pair_exception`
   - pair_n >= 25, positive EV, WR >= 0.58, positive expectancy
   - expect allowed

6. Regression:
   - no change to canonical PF
   - no change to close-lock helpers
   - no change to PARTIAL_TP_25 bypass

## Validation Commands

After deploy:

```bash
cd /opt/cryptomaster
git pull
sudo systemctl restart cryptomaster
sleep 10

sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY|ECON_BAD_FORCED|ECON_BAD_GUARD|decision=TAKE|Profit Factor|Economic:|SCRATCH_EXIT|STAGNATION_EXIT|PARTIAL_TP_25|CLOSE_LOCK|FORCE_RECONCILE|Traceback"
```

Live monitor:

```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "ECON_BAD_ENTRY|ECON_BAD_FORCED|decision=TAKE|CLOSE_LOCK|FORCE_RECONCILE|Traceback"
```

## Success Criteria

Within 30–60 minutes:

- `decision=TAKE ev=0.0300 p=0.5000 af=0.70` should disappear during ECON BAD.
- `decision=TAKE ... af=0.35` should disappear during ECON BAD.
- `ECON_BAD_ENTRY_BLOCK` appears for weak signals.
- `ECON_BAD_FORCED_BLOCK` appears for weak forced exploration.
- No `CLOSE_LOCK_STALE_RELEASE`.
- No `CLOSE_FORCE_RECONCILE`.
- No `EXIT_INTEGRITY_ERROR`.
- No `Traceback`.
- `PARTIAL_TP_25` remains profitable and unchanged.
- `SCRATCH_EXIT` count/net should stop worsening rapidly.
- PF should stabilize before any further exit tuning.

## Do NOT Change

- `canonical_metrics.py` PF formula
- `lm_economic_health()` canonical source logic
- close lock architecture from V10.13u+8..u+15
- `exit_pnl.py`
- PARTIAL_TP accounting or lock bypass
- TP/SL distances
- Firestore read/write frequency
- global reset / DB wipe logic
- position sizing except through already existing conservative multipliers

## Implementation Style

Be surgical. Minimal diff. No broad refactor.

Prefer:
- one helper for ECON BAD quality gate
- one helper for forced-explore ECON BAD gate
- throttled logs
- tests first or immediately after implementation

Do not reimplement old patches.
