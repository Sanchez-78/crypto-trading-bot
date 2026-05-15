# CryptoMaster P1.1AH — Verify/Fix P1.1AG Quality Diagnostics

## Goal
Analyze the current production logs after P1.1AG and implement only the minimal safe fix needed so paper-training quality diagnostics are complete and trustworthy.

## Current Production Evidence
- P1.1AD/AE/AF are working:
  - `PAPER_TRAIN_ENTRY` appears.
  - `PAPER_EXIT` appears.
  - `LEARNING_UPDATE ok=True` appears.
  - `Total trades in LM` increments after paper exits.
- P1.1AG is only partially verified:
  - `PAPER_TRAIN_QUALITY_EXIT` appears at least sometimes.
  - `PAPER_TRAIN_QUALITY_ENTRY` count is `0` in the sampled window.
  - `PAPER_TRAIN_ANOMALY` count is `0`.
  - `PAPER_TRAIN_QUALITY_SUMMARY` not yet confirmed.
- Logs show poor early quality:
  - Example: SOLUSDT timeout LOSS, `net_pnl_pct=-0.4268`, `exit_efficiency=0.0000`.
  - LM count stuck at `4` after the last exits because no more closed samples arrived in the window.
- Operational issue:
  - `journalctl` sometimes returns `Failed to iterate through journal: Bad message`.
  - Avoid relying on fragile one-liners only; provide robust verification commands.

## Hard Constraints
- Do NOT change live/real trading behavior.
- Do NOT tune TP/SL, EV, score gates, cost-edge, sizing, or learning logic yet.
- Do NOT make broad refactors.
- This patch is diagnostics-only unless a clear wiring bug is found.
- Preserve all P1.1AD/AE/AF behavior.
- All tests must pass.

## Tasks

### 1. Verify deployment and runtime
Add or confirm runtime/version logging includes:
- git short hash
- service PID
- paper_train mode
- P1.1AG diagnostic enabled marker

Expected startup log:
```text
[RUNTIME_VERSION] git=<hash> pid=<pid> mode=paper_train p11ag_quality_diag=True
```

### 2. Find why QUALITY_ENTRY count is 0
Inspect all real paper-training entry paths:
- `paper_trade_executor.py`
- `trade_executor.py`
- `paper_training_sampler.py`
- any bridge/router path from `STRICT_TAKE_ROUTED_TO_TRAINING`
- any `PORTFOLIO_GATE:*` training route

Confirm `_log_paper_train_quality_entry()` is called for every successful `PAPER_TRAIN_ENTRY`.

Important: the log must happen after the final position/trade dict exists and has:
- `trade_id`
- `symbol`
- `side`
- `entry`
- `bucket` / `training_bucket`
- `regime`
- `source`
- `ev`
- `score_raw`
- `score_final`
- `tp_pct`
- `sl_pct`
- `rr`
- `expected_move_pct`
- `opened_at`

If there are multiple paper entry constructors, do not duplicate logic. Create a single helper/wrapper if needed.

### 3. Add mismatch detector
If `PAPER_TRAIN_ENTRY` is emitted but no `PAPER_TRAIN_QUALITY_ENTRY` is emitted for the same trade, log:

```text
[PAPER_TRAIN_QUALITY_MISMATCH] type=missing_quality_entry trade_id=<id> symbol=<sym> source=<source>
```

This should be a diagnostic warning only. It must not block entries.

### 4. Improve exit diagnostics integrity
For each `PAPER_TRAIN_QUALITY_EXIT`, ensure it includes:
```text
trade_id symbol side entry exit outcome net_pnl_pct mfe_pct mae_pct exit_efficiency hold_s reason entry_regime exit_regime source bucket training_bucket
```

If `mfe_pct`, `mae_pct`, or `exit_efficiency` cannot be computed, log:
```text
[PAPER_TRAIN_ANOMALY] type=quality_exit_missing_fields trade_id=<id> symbol=<sym> missing=<fields>
```

### 5. Add compact per-window diagnostics
Every 5 minutes, log one summary even if closed count is zero:
```text
[PAPER_TRAIN_QUALITY_SUMMARY] window_s=300 opened=<n> closed=<n> win=<n> loss=<n> flat=<n> wr=<x> avg_pnl=<x> avg_mfe=<x> avg_mae=<x> zero_entry_logs=<n> anomalies=<n> by_source=[...] by_regime=[...]
```

The summary must make it obvious whether:
- entries are being created but entry-quality logs are missing
- exits are mostly LOSS/FLAT
- MFE is too low to ever hit TP
- MAE is too adverse immediately after entry
- source/regime is responsible

### 6. Journal-safe validation helper
Add a small read-only script:

```text
scripts/p11ag_quality_audit.sh
```

Requirements:
- Does not modify service/state.
- Uses current MainPID.
- Accepts optional `--since`.
- Handles `journalctl` failure gracefully.
- Prints counts:
  - `PAPER_TRAIN_ENTRY`
  - `PAPER_TRAIN_QUALITY_ENTRY`
  - `PAPER_TRAIN_QUALITY_EXIT`
  - `PAPER_TRAIN_QUALITY_MISMATCH`
  - `PAPER_TRAIN_ANOMALY`
  - `PAPER_TRAIN_QUALITY_SUMMARY`
  - `PAPER_EXIT`
  - `LEARNING_UPDATE ok=True`
  - latest `Total trades in LM`
- If `journalctl` fails with `Bad message`, print suggested manual recovery commands but do not run destructive cleanup automatically.

Suggested recovery text only:
```bash
sudo journalctl --verify
sudo journalctl --rotate
sudo journalctl --vacuum-time=2d
sudo systemctl restart systemd-journald
```

### 7. Tests
Add regression tests covering:
1. Every successful paper-training entry emits `PAPER_TRAIN_QUALITY_ENTRY`.
2. `PAPER_TRAIN_ENTRY` without quality entry emits `PAPER_TRAIN_QUALITY_MISMATCH`.
3. Quality exit contains MFE/MAE/efficiency fields.
4. Missing exit fields create `quality_exit_missing_fields` anomaly.
5. Summary logs even with zero closed trades.
6. Live/real modes remain unaffected.
7. Existing P1.1AD/AE/AF tests still pass.

## Acceptance Criteria
- `pytest` passes.
- No live/real behavior changes.
- Production validation after deploy shows:
```text
PAPER_TRAIN_ENTRY >= 1
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY for current PID/window
PAPER_TRAIN_QUALITY_EXIT >= PAPER_EXIT for closed paper-training trades
PAPER_TRAIN_QUALITY_MISMATCH = 0 after fix
LEARNING_UPDATE ok=True increments Total trades in LM
```

## Production validation command
```bash
cd /opt/cryptomaster
PID=$(systemctl show -p MainPID --value cryptomaster)

bash scripts/p11ag_quality_audit.sh --since "30 min ago"

sudo journalctl -u cryptomaster --since "30 min ago" --no-pager | grep "cryptomaster\[$PID\]" | grep -E "PAPER_TRAIN_ENTRY|PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_QUALITY_MISMATCH|PAPER_TRAIN_QUALITY_SUMMARY|PAPER_TRAIN_ANOMALY|PAPER_EXIT|LEARNING_UPDATE|Total trades in LM" | tail -220
```

## Output Required
After implementation, report:
- files changed
- exact root cause for missing `QUALITY_ENTRY`
- whether it was a logging-window issue or real wiring bug
- test count
- commit hash
- production validation commands
