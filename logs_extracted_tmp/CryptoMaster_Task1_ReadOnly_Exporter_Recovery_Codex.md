# CryptoMaster — Task 1 Recovery: Read-Only Paper Training Dataset Exporter

## Situation

The production server is on:

```bash
HEAD: 9a7f9ce P1.1AU: Fix canonical training trade count source for bootstrap/probe decisions
```

The checks show that the paper-training dataset exporter is **not present** in the repository. Only related scripts currently found:

```text
scripts/p11ag_quality_audit_cs.sh
scripts/p11ag_quality_audit.sh
```

## Goal

Implement **Task 1 only**: a safe, read-only paper-training dataset exporter.

This task must not change trading behavior. It is a research/analysis utility only.

## Hard Rules

Do **not** modify:

```text
src/services/realtime_decision_engine.py
src/services/paper_training_sampler.py
src/services/paper_trade_executor.py
src/services/learning_monitor.py
src/services/risk_engine.py
```

Do **not** add Firebase writes.

Do **not** tune:

```text
EV
RDE
TP/SL
risk logic
paper sampler behavior
live/real execution
```

Do **not** import hot-path trading modules unless absolutely necessary for harmless constants. Prefer pure parsing.

## Files to Create

Create exactly:

```text
scripts/export_paper_training_dataset.py
tests/test_export_paper_training.py
```

No dashboards, daemons, app code, or trading patches.

## Script Behavior

The script must read a journal/log text file and export correlated paper-training samples to JSONL.

Example usage:

```bash
python3 scripts/export_paper_training_dataset.py /tmp/cryptomaster_72h.log \
  --output data/research/paper_training_dataset_72h.jsonl
```

The script must:

1. Read input log file line by line.
2. Parse these log event types when available:
   - `[PAPER_TRAIN_QUALITY_ENTRY]`
   - `[PAPER_TRAIN_QUALITY_EXIT]`
   - `[PAPER_TRAIN_ECON_ATTRIB]`
   - `[PAPER_TRAIN_ECON_SUMMARY]` only if useful for aggregate metadata; do not require it per trade.
3. Correlate trade-level data by `trade_id`.
4. Output one JSON object per completed trade to JSONL.
5. Keep partially missing fields as `null`, not crash.
6. Be robust to duplicate lines.
7. Be robust to fields appearing in different order.
8. Be robust to non-matching journal lines.
9. Create output directory if needed.
10. Print a short summary to stdout:
    - parsed entries
    - parsed exits
    - parsed attributions
    - completed records written
    - output path

## Required JSONL Schema

Each output line must contain all these keys:

```json
{
  "trade_id": "string",
  "symbol": "string|null",
  "side": "BUY|SELL|null",
  "source": "string|null",
  "bucket": "string|null",
  "training_bucket": "string|null",
  "entry_regime": "string|null",
  "exit_regime": "string|null",

  "entry": "float|null",
  "exit": "float|null",
  "tp_pct": "float|null",
  "sl_pct": "float|null",
  "tp_pct_before": "float|null",
  "sl_pct_before": "float|null",

  "mfe_pct": "float|null",
  "mae_pct": "float|null",
  "net_pnl_pct": "float|null",
  "gross_move_pct": "float|null",
  "fee_drag_pct": "float|null",

  "outcome": "WIN|LOSS|FLAT|null",
  "reason": "string|null",
  "attribution": "string|null",

  "hold_s": "float|null",
  "hold_limit_s": "float|null",
  "timeout": "bool|null",
  "touched_tp": "bool|null",
  "touched_sl": "bool|null",
  "near_tp": "bool|null",
  "near_sl": "bool|null",

  "cost_edge_ok": "bool|null",
  "cost_edge_bypassed": "bool|null",
  "bypass_reason": "string|null",
  "geometry_calibrated": "bool|null",

  "entry_ts_raw": "string|null",
  "exit_ts_raw": "string|null"
}
```

Notes:

- `entry_ts_raw` and `exit_ts_raw` can be the journal timestamp prefix if easy to extract; otherwise `null`.
- Convert numeric fields to floats.
- Convert `True/False` and `true/false` to booleans.
- Preserve unknown strings as strings.
- Do not infer missing values if absent.

## Parsing Examples

Handle log snippets like:

```text
[PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_x symbol=ETHUSDT side=BUY source=training_sampler bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN regime=BULL_TREND entry=2137.77500000 tp_pct=0.273 sl_pct=0.450 geometry_calibrated=True tp_pct_before=1.200 sl_pct_before=1.200
```

```text
[PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_x symbol=ETHUSDT side=BUY source=training_sampler entry_regime=BULL_TREND exit_regime=BULL_TREND training_bucket=C_WEAK_EV_TRAIN reason=TP outcome=WIN entry=2137.77500000 exit=2143.62000000 net_pnl_pct=0.0934 mfe_pct=0.2734 mae_pct=0.0000 hold_s=52 hold_limit_s=300 touched_tp=True touched_sl=False
```

```text
[PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_x symbol=ETHUSDT side=BUY entry_regime=BULL_TREND exit_regime=BULL_TREND source=training_sampler training_bucket=C_WEAK_EV_TRAIN cost_edge_ok=True cost_edge_bypassed=False bypass_reason=none entry=2137.77500000 exit=2143.62000000 net_pnl_pct=0.0934 gross_move_pct=0.2734 fee_drag_pct=0.1800 mfe_pct=0.2734 mae_pct=0.0000 tp_pct=0.2733 sl_pct=0.4500 touched_tp=True touched_sl=False near_tp=False near_sl=False hold_s=52 hold_limit_s=300 timeout=False outcome=WIN attribution=NORMAL_WIN
```

## Tests Required

Create tests in:

```text
tests/test_export_paper_training.py
```

Minimum coverage:

1. Parses one complete ENTRY + EXIT + ATTRIB into one JSONL record.
2. Handles missing ATTRIB but valid ENTRY + EXIT.
3. Handles ATTRIB without ENTRY but with EXIT.
4. Converts floats correctly.
5. Converts booleans correctly.
6. Handles duplicate lines without duplicate output.
7. Ignores unrelated log lines.
8. Creates output directory.
9. Keeps missing fields as `None`.
10. CLI exits non-zero for missing input file.
11. CLI writes valid JSONL.
12. Schema contains all required keys in every row.

Use small fixture strings in tests. Do not require real journal files.

## Validation Commands

Run:

```bash
python3 -m pytest tests/test_export_paper_training.py -q
python3 -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
git diff -- src/services/realtime_decision_engine.py src/services/paper_training_sampler.py src/services/paper_trade_executor.py src/services/learning_monitor.py src/services/risk_engine.py
```

Expected:

```text
- exporter tests pass
- paper mode tests pass or only known unrelated failures are clearly explained
- bash syntax OK
- git diff for listed src/services/* files is empty
```

## Commit

If validation passes:

```bash
git add scripts/export_paper_training_dataset.py tests/test_export_paper_training.py
git commit -m "Research: add read-only paper training dataset exporter"
git push origin main
```

## After Commit: Production Usage

```bash
cd /opt/cryptomaster

journalctl -u cryptomaster --since "72 hours ago" > /tmp/cryptomaster_72h.log

python3 scripts/export_paper_training_dataset.py /tmp/cryptomaster_72h.log \
  --output data/research/paper_training_dataset_72h.jsonl

wc -l data/research/paper_training_dataset_72h.jsonl
head -n 3 data/research/paper_training_dataset_72h.jsonl
```

## Important Context

Current bot state:

- P1.1AT complete: rate-cap reservation fixed.
- P1.1AN complete: paper-training TP/SL geometry calibration active.
- P1.1AU complete: bootstrap/probe decisions use canonical LM trade count.
- Latest LM count is high, so cold-start probe/bypass should not activate.
- Current work is offline analysis only, not bot behavior modification.

Do not implement post-bootstrap sampling. Do not patch trading logic.
