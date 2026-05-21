# CryptoMaster — Next Safe Step

## Decision
Do **not** patch trading behavior now.

The next safe implementation is **Task 1: Paper Training Dataset Exporter**.

Reason:
- P1.1AO / P1.1AT / P1.1AN / P1.1AU are already marked as done.
- Android metrics schema and UI design are ready.
- Offline exporters/analyzers are marked READY_OFFLINE.
- Live/real trading changes, TP/SL tuning, EV/RDE tuning, strategy changes, high-frequency Firebase writes, and broad diagnostic patches are explicitly forbidden.

## What to implement now
Create a read-only log exporter that parses CryptoMaster paper-training logs into a stable JSONL dataset.

### Files to create
- `scripts/export_paper_training_dataset.py`
- `tests/test_export_paper_training.py`
- output directory: `data/research/`

### Input
A local text log file exported from `journalctl` or existing log files.

Parse these log types:
- `[PAPER_TRAIN_QUALITY_ENTRY]`
- `[PAPER_TRAIN_QUALITY_EXIT]`
- `[PAPER_TRAIN_ECON_ATTRIB]`
- `[LM_STATE_AFTER_UPDATE]`

### Output
`data/research/paper_training_dataset.jsonl`

One JSON object per completed training trade.

Required stable fields:

```json
{
  "timestamp_entry": null,
  "timestamp_exit": null,
  "trade_id": null,
  "symbol": null,
  "side": null,
  "entry_regime": null,
  "exit_regime": null,
  "training_bucket": null,
  "ev": null,
  "p": null,
  "score_raw": null,
  "score_final": null,
  "coherence": null,
  "expected_move_pct": null,
  "entry_price": null,
  "exit_price": null,
  "tp_pct": null,
  "sl_pct": null,
  "mfe_pct": null,
  "mae_pct": null,
  "net_pnl_pct": null,
  "gross_move_pct": null,
  "fee_drag_pct": null,
  "outcome": null,
  "attribution": null,
  "reason": null,
  "touched_tp": null,
  "touched_sl": null,
  "timeout": null,
  "hold_seconds": null,
  "cost_edge_ok": null,
  "cost_edge_bypassed": null,
  "bypass_reason": null,
  "lm_before_total": null,
  "lm_after_total": null,
  "source_log_types": []
}
```

## Implementation requirements

### Parser
Implement generic key-value parsing for log lines:

```python
def parse_kv_tokens(message: str) -> dict:
    ...
```

It must support values like:
- `trade_id=paper_123`
- `symbol=BTCUSDT`
- `net_pnl_pct=-0.1800`
- `touched_tp=False`
- `training_bucket=C_WEAK_EV_TRAIN`

### Functions
Create:

```python
def parse_entry_log(line: str) -> dict | None: ...
def parse_exit_log(line: str) -> dict | None: ...
def parse_attribution_log(line: str) -> dict | None: ...
def parse_lm_state_log(line: str) -> dict | None: ...
def join_trade_records(entries: dict, exits: dict, attrs: dict, lm_updates: dict) -> list[dict]: ...
def export_jsonl(records: list[dict], output_path: str) -> None: ...
```

### CLI
Support:

```bash
python3 scripts/export_paper_training_dataset.py /tmp/cryptomaster.log --output data/research/paper_training_dataset.jsonl
```

Optional:

```bash
journalctl -u cryptomaster --since "24 hours ago" > /tmp/cryptomaster.log
python3 scripts/export_paper_training_dataset.py /tmp/cryptomaster.log --output data/research/paper_training_dataset.jsonl
```

## Tests
Create `tests/test_export_paper_training.py` with:

1. parse entry log
2. parse exit log
3. parse attribution log
4. parse LM state log
5. join entry + exit + attribution by `trade_id`
6. missing attribution still exports record with null fields
7. malformed line skipped without crash
8. JSONL export/reload roundtrip
9. consistent schema for all output records
10. no imports from live trading execution modules except standard utilities if absolutely necessary

## Hard rules
- No trading logic changes.
- No Firebase writes.
- No network calls.
- No live/real behavior changes.
- No TP/SL tuning.
- No EV/RDE tuning.
- No new high-frequency metrics publishing.
- This task is read-only and research-only.

## Validation commands

```bash
python3 -m pytest tests/test_export_paper_training.py -q
python3 -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh

git diff -- src/services/realtime_decision_engine.py src/services/paper_training_sampler.py src/services/paper_trade_executor.py src/services/learning_monitor.py src/services/risk_engine.py src/services/firebase_client.py
```

The final `git diff` must show **no trading behavior changes**.

## Commit message

```text
Research: add paper training dataset exporter
```
