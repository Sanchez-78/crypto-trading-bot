# CryptoMaster P1.1AN — Validation-First Economic Calibration Patch

## Status Before This Patch

P1.1AM is complete and deployed.

Confirmed:
- Paper-training pipeline is connected.
- Quality entry/exit logs are matched by trade_id.
- Learning Monitor state increments after paper exits.
- Economic attribution now exists via `[PAPER_TRAIN_ECON_ATTRIB]`.
- Rolling economic summary exists via `[PAPER_TRAIN_ECON_SUMMARY]`.
- Cost-edge bypass is split into candidate vs accepted.

Do **not** implement P1.1AN blindly.  
First read production logs and identify dominant attribution.

---

## First Step: Production Audit

Run:

```bash
cd /opt/cryptomaster

git rev-parse --short HEAD
git merge-base --is-ancestor b1375bc HEAD && echo "OK P1.1AM deployed" || echo "BAD P1.1AM missing"

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "60 min ago"

sudo journalctl -u cryptomaster --since "60 min ago" --no-pager | grep "cryptomaster\[$PID\]" | grep -E "PAPER_TRAIN_ECON_ATTRIB|PAPER_TRAIN_ECON_SUMMARY|PAPER_TRAIN_QUALITY_EXIT|PAPER_EXIT|LM_STATE_AFTER_UPDATE" | tail -250
```

If there are fewer than 10 closed training trades, do not tune yet. Only report:

```text
INSUFFICIENT_SAMPLE_FOR_CALIBRATION closed=<n> required>=10
```

---

## Decision Matrix

Use the attribution distribution from `[PAPER_TRAIN_ECON_ATTRIB]` and `[PAPER_TRAIN_ECON_SUMMARY]`.

### Case A — Dominant: `TP_TOO_FAR_FOR_MFE`

Symptoms:
- `mfe_to_tp_ratio` usually below 0.25
- `timeout_rate` high
- `near_tp_timeout` low
- MFE is positive but much smaller than TP

Interpretation:
TP is too far for 300-second paper-training horizon.

Allowed P1.1AN change:
- Paper-train only.
- Reduce TP/SL geometry for `C_WEAK_EV_TRAIN`.
- Do not change live/real execution.

Suggested calibration:
- For `C_WEAK_EV_TRAIN`:
  - `tp_pct = clamp(max(median_mfe_pct * 1.20, 0.08), 0.08, 0.45)`
  - `sl_pct = clamp(max(abs(median_mae_pct) * 1.30, 0.08), 0.08, 0.45)`
  - Keep RR >= 1.0 for diagnostics.
- Log:
  - `[PAPER_TRAIN_GEOMETRY_CALIBRATION] reason=tp_too_far old_tp_pct=... new_tp_pct=... old_sl_pct=... new_sl_pct=... sample_n=...`

### Case B — Dominant: `FEE_DOMINATED_MOVE`

Symptoms:
- side-aware gross move > 0
- net PnL <= 0 after fees
- `mfe_to_tp_ratio` may be small
- many trades are directionally right but too small

Interpretation:
Signals have tiny edge but trade cost dominates.

Allowed P1.1AN change:
- Paper-train only.
- Add minimum expected net move for accepted training samples, but do not deadlock bootstrap.
- Keep limited bypass quota for exploration.

Suggested calibration:
- For bypassed cold-start samples:
  - allow max 1 bypassed sample per 5 minutes
  - allow max 2 bypassed open positions total
- For non-bypassed samples:
  - require `expected_move_pct >= fee_drag_pct * 2.0`
- Log:
  - `[PAPER_TRAIN_COST_FILTER] allowed=<bool> reason=<fee_dominated|min_move_ok|bootstrap_quota> expected_move_pct=... fee_drag_pct=...`

### Case C — Dominant: `COST_EDGE_BYPASS_LOSS`

Symptoms:
- `cost_edge_bypassed=True`
- `outcome=LOSS`
- bypassed WR is much worse than cost_edge_ok WR

Interpretation:
Bootstrap bypass is admitting weak samples.

Allowed P1.1AN change:
- Paper-train only.
- Keep bypass, but throttle and require a weak sanity floor.

Suggested calibration:
- `cost_edge_bypassed=True` only if:
  - bootstrap closed trades < 50
  - source is `STRICT_TAKE_ROUTED_TO_TRAINING`
  - bucket is `C_WEAK_EV_TRAIN`
  - score_raw or score_final is present
  - `score_final >= 0.12`
  - `expected_move_pct >= 0.05`
- Add cap:
  - max bypass accepted per symbol per 15 minutes = 1
  - max bypass accepted globally per 5 minutes = 2
- Log accepted/rejected separately:
  - `[COST_EDGE_BYPASS_REJECTED] reason=<score_floor|min_move|quota>`

### Case D — Dominant: `WRONG_DIRECTION`

Symptoms:
- side-aware gross move < 0
- MFE tiny
- MAE meaningful
- both BUY and SELL fail in same regime/symbol cells

Interpretation:
Signal direction quality is poor, not just TP/SL.

Allowed P1.1AN change:
- Diagnostics only or paper-train only guard.
- Do not alter live RDE yet.
- Add directional attribution by feature/regime.

Required:
- Add breakdown:
  - by `symbol`
  - by `regime`
  - by `side`
  - by `source`
  - by signal edge if available
- Log:
  - `[PAPER_TRAIN_DIRECTION_QUALITY] symbol=... regime=... side=... n=... wrong_direction_rate=... avg_gross_side_move=...`

### Case E — Dominant: `NEAR_TP_TIMEOUT`

Symptoms:
- many timeouts with `near_tp=True`
- MFE close to TP
- no actual TP hit

Interpretation:
TP is close, but timeout or target threshold is slightly too strict.

Allowed P1.1AN change:
- Paper-train only.
- Add diagnostic shadow close rule, not real close rule:
  - compute `would_close_if_tp_90pct=True`
  - compute shadow outcome if TP were 90% of current distance
- Do not execute shadow result as real learning yet.
- Log:
  - `[PAPER_TRAIN_SHADOW_GEOMETRY] tp90_outcome=... tp80_outcome=...`

### Case F — `BOTH_TOUCH_AMBIGUOUS`

Symptoms:
- both TP and SL touched during hold

Interpretation:
Intraperiod ordering is unknown from sampled price extremes.

Allowed P1.1AN change:
- Improve diagnostics only.
- Track first touch timestamp if tick-by-tick update has enough data.
- Log:
  - `[PAPER_TRAIN_TOUCH_ORDER] first_touch=<TP|SL|unknown>`

---

## Required Implementation Rules

1. Live/real modes must remain unchanged.
2. All tuning must be gated behind:
   - `mode == "paper_train"`
   - `bucket == "C_WEAK_EV_TRAIN"`
3. No global RDE gate changes.
4. No production Firebase schema changes unless strictly additive.
5. Preserve all P1.1AD–P1.1AM logs.
6. Add regression tests for whichever branch is implemented.
7. If sample size is insufficient, do not implement tuning. Add only audit/reporting if needed.

---

## Minimum Tests

Add tests based on selected dominant case:

### Always
- live mode unchanged
- real mode unchanged
- paper_train-only calibration gated correctly
- audit script still scalar-safe

### If TP calibration
- TP/SL reduced only for `C_WEAK_EV_TRAIN`
- RR remains valid
- clamps work
- old TP/SL used outside paper_train

### If cost-edge bypass throttling
- accepted bypass respects quota
- rejected bypass logs reason
- non-bypass cost_edge_ok samples still pass
- bootstrap does not deadlock entirely

### If fee-dominated
- fee filter blocks tiny expected moves
- bootstrap quota still allows limited exploration
- no cap interference with normal cost_edge_ok samples

---

## Expected Output

After implementing P1.1AN, report:

```text
P1.1AN Complete
Commit: <hash>
Dominant attribution found: <ATTR>
Action taken: <calibration|throttle|diagnostics-only>
Live/real behavior changed: NO
Tests: <n> passing
Validation command:
bash scripts/p11ag_quality_audit.sh --since "60 min ago"
```

---

## Stop Conditions

Stop and do not tune if:

- fewer than 10 closed training trades
- audit cannot find `[PAPER_TRAIN_ECON_ATTRIB]`
- quality exit mismatch exists
- LM update mismatch exists
- deployed HEAD does not contain P1.1AM
- journal snapshot is corrupted or PID-mixed

Return a short diagnostic instead of implementing.
