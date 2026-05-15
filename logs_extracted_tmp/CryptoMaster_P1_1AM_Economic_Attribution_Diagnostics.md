# CryptoMaster P1.1AM — Paper Training Economic Attribution Diagnostics

## Context

Current production validation after P1.1AL confirms the paper-training chain works:

- `PAPER_TRAIN_ENTRY = PAPER_TRAIN_QUALITY_ENTRY`
- `PAPER_EXIT = PAPER_TRAIN_QUALITY_EXIT` for `training_bucket=C_WEAK_EV_TRAIN`
- `LM_STATE_AFTER_UPDATE` increments `Total trades in LM`
- No quality exit mismatch
- No LM propagation mismatch

Remaining issue is not pipeline connectivity. It is economic quality.

Observed production examples:

- `timeout_rate=1.000`
- `avg_tp_pct=1.2000`
- `avg_sl_pct=1.2000`
- `near_tp_timeout=0`
- `near_sl_timeout=0`
- ADA SELL: `mfe_pct=0.0777` vs `tp_pct=1.200`, `net_pnl=-0.1400`
- ETH SELL: `mfe_pct=0.0413` vs `tp_pct=1.200`, `net_pnl=-0.1778`
- `cost_edge_bypassed` entries exist and can close as LOSS
- Direction may be mildly correct, but move is too small and fees/cost dominate

## Goal

Add diagnostic-only economic attribution for paper_train samples.

Do **not** change live/real trading behavior.  
Do **not** change RDE decision logic.  
Do **not** change actual TP/SL execution yet.  
Do **not** optimize strategy yet.

This patch should explain **why** `C_WEAK_EV_TRAIN` samples are `LOSS/FLAT`:

1. cost-edge bypass admitted weak samples
2. TP/SL geometry unrealistic for 300s hold
3. movement was fee-dominated
4. signal direction was wrong
5. MFE was too small relative to TP
6. MAE was too small relative to SL
7. timeout occurred because target was unreachable

---

## Required Changes

### 1. Add per-exit economic attribution

In `src/services/paper_trade_executor.py`, extend `[PAPER_TRAIN_QUALITY_EXIT]` or add a new log:

```text
[PAPER_TRAIN_ECON_ATTRIB]
```

Required fields:

- `trade_id`
- `symbol`
- `side`
- `entry_regime`
- `exit_regime`
- `source`
- `training_bucket`
- `cost_edge_ok`
- `cost_edge_bypassed`
- `bypass_reason`
- `entry`
- `exit`
- `net_pnl_pct`
- `gross_move_pct_side_aware`
- `fee_drag_pct`
- `mfe_pct`
- `mae_pct`
- `tp_pct`
- `sl_pct`
- `mfe_to_tp_ratio`
- `mae_to_sl_ratio`
- `touched_tp`
- `touched_sl`
- `near_tp`
- `near_sl`
- `hold_s`
- `hold_limit_s`
- `timeout`
- `outcome`
- `attribution`

Attribution must be one stable enum:

- `FEE_DOMINATED_MOVE`
- `TP_TOO_FAR_FOR_MFE`
- `SL_TOO_FAR_UNUSED`
- `WRONG_DIRECTION`
- `COST_EDGE_BYPASS_LOSS`
- `LOW_VOL_TIMEOUT`
- `NEAR_TP_TIMEOUT`
- `NEAR_SL_TIMEOUT`
- `BOTH_TOUCH_AMBIGUOUS`
- `NORMAL_WIN`
- `NORMAL_LOSS`
- `FLAT_NO_SIGNAL`

### Attribution rules

- If side-aware gross move is positive but `net_pnl_pct <= 0` → `FEE_DOMINATED_MOVE`
- If timeout and `mfe_to_tp_ratio < 0.25` → `TP_TOO_FAR_FOR_MFE`
- If `cost_edge_bypassed=True` and `outcome=LOSS` → `COST_EDGE_BYPASS_LOSS`
- If side-aware gross move `< 0` and `outcome=LOSS` → `WRONG_DIRECTION`
- If `touched_tp=True` and `touched_sl=True` → `BOTH_TOUCH_AMBIGUOUS`
- If `near_tp=True` and timeout → `NEAR_TP_TIMEOUT`
- If `near_sl=True` and timeout → `NEAR_SL_TIMEOUT`

Use deterministic priority order:

1. `BOTH_TOUCH_AMBIGUOUS`
2. `NEAR_TP_TIMEOUT`
3. `NEAR_SL_TIMEOUT`
4. `COST_EDGE_BYPASS_LOSS`
5. `FEE_DOMINATED_MOVE`
6. `WRONG_DIRECTION`
7. `TP_TOO_FAR_FOR_MFE`
8. `LOW_VOL_TIMEOUT`
9. `NORMAL_WIN / NORMAL_LOSS / FLAT_NO_SIGNAL`

---

### 2. Add rolling attribution summary

Extend `[PAPER_TRAIN_ECON_SUMMARY]` every 5 minutes with:

- `by_attribution=[ATTR:n=x wr=y avg_pnl=z]`
- `cost_edge_bypassed_n`
- `cost_edge_bypassed_wr`
- `cost_edge_ok_n`
- `cost_edge_ok_wr`
- `avg_mfe_to_tp_ratio`
- `avg_mae_to_sl_ratio`
- `fee_dominated_n`
- `wrong_direction_n`
- `tp_too_far_n`
- `low_vol_timeout_n`

Example:

```text
[PAPER_TRAIN_ECON_SUMMARY] window_s=300 closed=8 timeout_rate=1.000 avg_pnl=-0.1234 avg_mfe_to_tp_ratio=0.07 cost_edge_bypassed_n=3 cost_edge_bypassed_wr=0.00 by_attribution=[TP_TOO_FAR_FOR_MFE:n=4 wr=0.00 avg_pnl=-0.12,FEE_DOMINATED_MOVE:n=2 wr=0.00 avg_pnl=-0.04]
```

---

### 3. Reduce cost-edge bypass log noise

Current logs show `COST_EDGE_BYPASS` can appear many times while real entries are few.

Split logs into two different events:

```text
[COST_EDGE_BYPASS_CANDIDATE]
```

when candidate qualifies for bypass before sampler/caps.

```text
[COST_EDGE_BYPASS_ACCEPTED]
```

only when it actually becomes `PAPER_TRAIN_ENTRY`.

Keep existing `[COST_EDGE_BYPASS]` only if required for backward compatibility, but audit should prefer accepted count.

Update audit script counters:

- `COST_EDGE_BYPASS_CANDIDATE`
- `COST_EDGE_BYPASS_ACCEPTED`
- `PAPER_TRAIN_ENTRY cost_edge_bypassed=True`
- `bypass_candidate_to_entry_ratio`

---

### 4. Audit script update

Update `scripts/p11ag_quality_audit.sh`.

Add counters:

- `PAPER_TRAIN_ECON_ATTRIB`
- `ATTR_FEE_DOMINATED_MOVE`
- `ATTR_TP_TOO_FAR_FOR_MFE`
- `ATTR_COST_EDGE_BYPASS_LOSS`
- `ATTR_WRONG_DIRECTION`
- `ATTR_LOW_VOL_TIMEOUT`
- `COST_EDGE_BYPASS_CANDIDATE`
- `COST_EDGE_BYPASS_ACCEPTED`
- `BYPASS_ACCEPTED_ENTRY_MATCH`

Diagnostics:

Pass:

- `PAPER_TRAIN_ECON_ATTRIB >= PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET`
- `BYPASS_ACCEPTED_ENTRY_MATCH` is consistent with `PAPER_TRAIN_ENTRY cost_edge_bypassed=True`
- `LM_STATE_AFTER_UPDATE` increments after `PAPER_EXIT`

Warn:

- `TP_TOO_FAR_FOR_MFE` dominant
- `FEE_DOMINATED_MOVE` dominant
- `COST_EDGE_BYPASS_LOSS` dominant
- `bypass_candidate_to_entry_ratio` extremely high

---

### 5. Tests

Add tests in `tests/test_paper_mode.py`:

- fee-dominated move attribution
- TP too far for MFE attribution
- cost-edge bypass loss attribution
- wrong direction attribution
- both-touch priority
- rolling summary includes attribution counts
- bypass candidate vs accepted log split
- audit script scalar counters remain safe

All existing tests must pass.

---

## Acceptance Criteria

- All tests pass.
- Live/real modes unchanged.
- Production logs include `[PAPER_TRAIN_ECON_ATTRIB]`.
- Audit can answer whether losses are caused mostly by:
  - cost-edge bypass
  - TP too far
  - fee-dominated tiny moves
  - wrong direction
- No trading logic changes yet.

---

## Production Validation

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)

sudo journalctl -u cryptomaster --since "30 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_ECON_ATTRIB|PAPER_TRAIN_ECON_SUMMARY|COST_EDGE_BYPASS_CANDIDATE|COST_EDGE_BYPASS_ACCEPTED|PAPER_EXIT|LM_STATE_AFTER_UPDATE" \
| tail -200

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

---

## Do Not Implement Yet

Do **not** reduce TP/SL.  
Do **not** change hold time.  
Do **not** disable cost-edge bypass.  
Do **not** alter live execution.

This patch is for attribution only. After the dominant reason is known, create a separate `P1.1AN` economic calibration patch.
