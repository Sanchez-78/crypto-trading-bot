# CryptoMaster P1.1AO — Cold-Start EV Starvation + Paper-Train Exploration Recovery

## Goal

Fix the current production blocker where the bot generates many valid signals, but **no paper-training trades are opened**, so learning cannot progress.

This is **not P1.1AN attribution tuning**. P1.1AN remains paused until enough closed training trades exist. P1.1AO is a recovery/diagnostic patch for a new starvation state.

---

## Current Production Evidence

Observed in production logs on `2026-05-18` under PID `934183`:

```text
[ECONOMIC_GATE] Insufficient trade data size_mult=1.00
[HBLOCK] SKIP_SCORE_HARD ... score=-0.151 ... Below hard floor
[V10.13w DECISION] ... ev_raw=-0.6713 ev_final=-0.4297 score_raw=0.0000 ... REJECT (NEGATIVE_EV)
[V10.13t] ... Rejected negative/zero EV ... hard enforcement of EV-only principle
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN original_decision=REJECT_NEGATIVE_EV reject_reason=negative_ev
[V10.13u/PATCH5] bootstrap active (global_trades=0<100 | p20_pair_n=10<15)
idle=234928s
```

Repeated across:

- ETHUSDT
- BTCUSDT
- XRPUSDT
- BNBUSDT

The system is producing valid signal-engine events such as:

```text
on_price(ETHUSDT): Generated valid signal BUY (edge=fake_breakout)
on_price(BTCUSDT): Generated valid signal BUY (edge=fake_breakout)
on_price(BNBUSDT): Generated valid signal BUY (edge=trend_pullback)
```

But the chain ends in:

```text
REJECT_NEGATIVE_EV
PAPER_EXPLORE_SKIP reason=no_bucket_matched bucket=UNKNOWN
```

Result:

- No new `PAPER_TRAIN_ENTRY`
- No new `PAPER_EXIT`
- No new `PAPER_TRAIN_ECON_ATTRIB`
- No path to reach the P1.1AN sample threshold
- Bot appears live, but training is effectively stalled

---

## Root Problem

The system has entered **cold-start EV starvation**:

1. Signal engine generates valid candidates.
2. RDE assigns very negative EV despite insufficient economic data.
3. EV-only hard enforcement rejects the candidate.
4. Paper exploration cannot route it because `REJECT_NEGATIVE_EV` maps to `bucket=UNKNOWN`.
5. No paper trades close.
6. LM/economic sample count cannot increase.
7. Bot stays stuck in `Insufficient trade data` forever.

This is a deadlock. It is especially visible because logs show:

```text
bootstrap active
global_trades=0<100
p20_pair_n=10<15
idle=234928s
```

A bootstrap system must have a safe paper-only way to collect evidence. Live/real trading must remain unchanged.

---

## Non-Negotiable Constraints

- Do **not** change live/real execution behavior.
- Do **not** bypass negative EV for live/real trades.
- Do **not** tune TP/SL or attribution logic in this patch.
- Do **not** implement P1.1AN yet.
- Scope recovery to:
  - `mode == paper_train`
  - cold-start / insufficient-data state
  - diagnostic exploration only
- Preserve P1.1AD–P1.1AM diagnostics.
- Add regression tests.
- Keep Firebase quota impact low.
- Avoid log storms.

---

## Required Implementation

### 1. Add a state-source consistency diagnostic

Add a periodic diagnostic log, for example:

```text
[PAPER_TRAIN_STARVATION_STATE]
mode=paper_train
idle_s=...
global_trades=...
lm_total=...
economic_sample_count=...
closed_training_trades=...
open_paper=...
signals_seen_5m=...
negative_ev_rejects_5m=...
score_hard_rejects_5m=...
paper_explore_skips_5m=...
last_paper_entry_age_s=...
```

Purpose: confirm whether the bot has samples in LM but RDE/economic gate still thinks `global_trades=0` or `insufficient data`.

Add warning if:

```text
lm_total > 0 AND global_trades == 0
```

Emit:

```text
[PAPER_TRAIN_STATE_MISMATCH]
lm_total=<n>
global_trades=<n>
economic_sample_count=<n>
reason=lm_not_visible_to_rde_or_economic_gate
```

This is diagnostic-only.

---

### 2. Add paper-only bucket mapping for negative EV rejects

Current failure:

```text
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN original_decision=REJECT_NEGATIVE_EV reject_reason=negative_ev
```

Add a new diagnostic training bucket or route, for example:

```text
C_NEG_EV_PROBE
```

Only allow this bucket when **all** conditions are true:

```python
mode == "paper_train"
original_decision in {"REJECT_NEGATIVE_EV", "SKIP_SCORE_HARD"}
reject_reason in {"negative_ev", "score_hard"}
economic_data_insufficient is True OR global_trades < 100 OR closed_training_trades < 20
idle_s >= 1800
signal is structurally valid
side in {"BUY", "SELL"}
symbol is allowlisted for paper training
spread <= configured paper max spread
not live_mode
not real_mode
```

Hard caps:

```python
max_open_per_symbol = 1
max_open_bucket = 2
max_new_probe_entries_per_10min = 2
max_total_probe_closed = 20
```

Log every accepted probe:

```text
[PAPER_NEG_EV_PROBE_ACCEPTED]
symbol=...
side=...
regime=...
ev=...
score=...
idle_s=...
reason=cold_start_starvation
bucket=C_NEG_EV_PROBE
```

Log every rejected probe:

```text
[PAPER_NEG_EV_PROBE_SKIP]
symbol=...
reason=cap|spread|not_cold_start|live_mode|invalid_signal|quota
```

Important: This is paper-only evidence collection, not live trading.

---

### 3. Keep EV-only principle intact for live/real

Add explicit guard tests:

- live mode with `REJECT_NEGATIVE_EV` does not open any position
- real mode with `REJECT_NEGATIVE_EV` does not open any position
- paper_train mode can route only under cold-start starvation conditions
- paper_train mode does not route if `idle_s < 1800`
- paper_train mode does not route if caps are full

---

### 4. Fix duplicate/log storm behavior

The logs show many repeated `on_price(... Generated valid signal ...)`, `HBLOCK`, and `REJECT_NEGATIVE_EV` messages in the same second.

Add logging throttles only, not trading logic changes:

- throttle identical `[HBLOCK]` per `(symbol, reason, decision)` to once every 10 seconds
- throttle repeated `PAPER_EXPLORE_SKIP no_bucket_matched` per `(symbol, decision, reject_reason)` to once every 10 seconds
- optionally add aggregate summary:

```text
[PAPER_EXPLORE_SKIP_SUMMARY]
window_s=60
no_bucket_matched=...
negative_ev=...
score_hard=...
by_symbol=[BTCUSDT:n=...,ETHUSDT:n=...]
```

Do not hide important first occurrences.

---

### 5. Add audit script counters

Update `scripts/p11ag_quality_audit.sh` to include:

```text
PAPER_TRAIN_STARVATION_STATE
PAPER_TRAIN_STATE_MISMATCH
PAPER_NEG_EV_PROBE_ACCEPTED
PAPER_NEG_EV_PROBE_SKIP
PAPER_EXPLORE_SKIP no_bucket_matched
REJECT_NEGATIVE_EV
SKIP_SCORE_HARD
```

Add a section:

```text
Starvation / Probe Diagnostics:
-------
NEGATIVE_EV_REJECTS:
SCORE_HARD_REJECTS:
PAPER_EXPLORE_NO_BUCKET:
NEG_EV_PROBE_ACCEPTED:
NEG_EV_PROBE_SKIP:
STATE_MISMATCH:
```

Keep scalar-safe counter helpers from P1.1AL.

---

## Validation Commands

After deployment:

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 15

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

Manual focused check:

```bash
sudo journalctl -u cryptomaster --since "30 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_STARVATION_STATE|PAPER_TRAIN_STATE_MISMATCH|PAPER_NEG_EV_PROBE|PAPER_TRAIN_ENTRY|PAPER_EXIT|LM_STATE_AFTER_UPDATE|PAPER_EXPLORE_SKIP" \
| tail -200
```

Expected after 10–20 minutes in paper_train mode:

```text
PAPER_TRAIN_STARVATION_STATE >= 1
PAPER_NEG_EV_PROBE_ACCEPTED >= 1 if starvation persists
PAPER_TRAIN_ENTRY increases
PAPER_EXIT increases after hold timeout
LM_STATE_AFTER_UPDATE increases after exits
PAPER_TRAIN_ECON_ATTRIB resumes
```

Hard fail if:

```text
live/real opens negative-EV positions
probe entries exceed caps
no state diagnostics appear
probe accepted but no PAPER_TRAIN_ENTRY
PAPER_EXIT occurs without quality/LM diagnostics
```

---

## Required Tests

Add tests for:

1. `REJECT_NEGATIVE_EV` in live mode never routes to paper probe.
2. `REJECT_NEGATIVE_EV` in real mode never routes to paper probe.
3. `REJECT_NEGATIVE_EV` in paper_train cold-start + idle state routes to `C_NEG_EV_PROBE`.
4. `SKIP_SCORE_HARD` in paper_train cold-start + idle state can route only if structurally valid.
5. Probe route obeys max open per symbol.
6. Probe route obeys bucket cap.
7. Probe route obeys rate cap.
8. Probe route does not activate when idle below threshold.
9. Audit script counters are scalar-safe.
10. Duplicate skip/HBLOCK logs are throttled but first event is emitted.

---

## Acceptance Criteria

Patch is complete only when:

```text
All existing tests pass
New P1.1AO tests pass
Live/real behavior unchanged
paper_train has a safe route out of negative-EV starvation
audit script exposes starvation/probe counters
logs are no longer spammed every tick with identical rejects
```

---

## Expected Production Result

Before patch:

```text
valid signals -> REJECT_NEGATIVE_EV -> PAPER_EXPLORE_SKIP no_bucket_matched -> no learning
```

After patch:

```text
valid signals -> REJECT_NEGATIVE_EV -> paper-only starvation probe -> PAPER_TRAIN_ENTRY -> PAPER_EXIT -> LM_STATE_AFTER_UPDATE -> attribution data
```

This allows P1.1AN to remain evidence-based instead of being forced to tune from zero new samples.

---

## Final Note

Do not label this as P1.1AN. This is a prerequisite recovery patch:

```text
P1.1AO = restore paper_train sample flow under cold-start negative-EV starvation.
P1.1AN = later targeted calibration after enough attribution samples exist.
```
