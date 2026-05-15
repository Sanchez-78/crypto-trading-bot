# CryptoMaster P1.1AJ — Complete Paper Training Diagnostics Wiring

> Incremental Claude Code prompt. Safety-preserving diagnostics patch only.  
> Do **not** change live/real trading decisions, RDE thresholds, position sizing, TP/SL economics, or learning formulas.

---

## Current production evidence

After P1.1AI audit:

```text
PAPER_TRAIN_ENTRY:            3
PAPER_TRAIN_QUALITY_ENTRY:    3
PAPER_TRAIN_QUALITY_EXIT:     2
PAPER_TRAIN_QUALITY_MISMATCH: 0
PAPER_TRAIN_ANOMALY:          5
PAPER_TRAIN_QUALITY_SUMMARY:  1
PAPER_EXIT:                   4
LEARNING_UPDATE ok=True:      0
LM_STATE_AFTER_UPDATE:        0
Latest Total trades in LM:    1
```

Sample current logs:

```text
[PAPER_TRAIN_QUALITY_ENTRY] ... score_raw=na score_final=na score_missing=True ...
[PAPER_TRAIN_ANOMALY] type=score_missing_for_take ...
[PAPER_TRAIN_QUALITY_ENTRY] ... expected_move_pct=0.023 expected_move_src=atr_abs_corrected ...
```

P1.1AI already fixed:

- SELL TP/SL inversion
- expected_move_pct ATR unit mismatch
- partial score propagation
- partial quality exit paths
- audit script counting alignment

Remaining issues:

1. `score_raw` / `score_final` do not reliably reach `open_paper_position()`.
2. Not every `PAPER_EXIT` has a matching `PAPER_TRAIN_QUALITY_EXIT`.
3. LM count can increase while `LEARNING_UPDATE` / `LM_STATE_AFTER_UPDATE` logs are missing.
4. Audit output can still mix old PIDs or false-zero after journal errors.

---

## Goal

Make paper training diagnostics complete and self-verifying.

Expected invariant:

```text
PAPER_TRAIN_ENTRY
→ PAPER_TRAIN_QUALITY_ENTRY
→ PAPER_EXIT
→ PAPER_TRAIN_QUALITY_EXIT
→ LEARNING_UPDATE / LM_STATE_AFTER_UPDATE
→ Total trades in LM increments
```

Pass criteria:

```text
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY
PAPER_TRAIN_QUALITY_EXIT >= PAPER_EXIT for paper training trades
PAPER_TRAIN_QUALITY_MISMATCH = 0
PAPER_TRAIN_QUALITY_EXIT_MISSING = 0
score_missing_for_take = 0 unless canonical score is truly unavailable before RDE
LM_STATE_AFTER_UPDATE appears whenever paper_closed_trade mutates canonical lm_count
Audit script filters only current PID
```

---

## Scope

Modify only diagnostics/data propagation paths:

- `src/services/trade_executor.py`
- `src/services/paper_training_sampler.py`
- `src/services/paper_trade_executor.py`
- `src/services/learning_monitor.py`
- `scripts/p11ag_quality_audit.sh`
- `tests/test_paper_mode.py`

Do **not** modify:

- live/real execution behavior
- RDE accept/reject logic
- trading thresholds
- sizing
- TP/SL formulas except diagnostics-only metadata
- learning formulas

---

## Task 1 — Fix score propagation to paper quality entry

Production still logs:

```text
score_raw=na score_final=na score_missing=True
[PAPER_TRAIN_ANOMALY] type=score_missing_for_take
```

Trace this path:

```text
RDE accepted candidate
→ trade_executor routing/drop path
→ paper_training_sampler
→ open_paper_position()
→ PAPER_TRAIN_QUALITY_ENTRY
```

Ensure the paper trade `extra` / metadata always carries:

```python
score_raw
score_final
decision_score
decision
rde_reason
rde_bucket
source
origin_source
```

Rules:

- Prefer canonical fields already computed by RDE/trade_executor.
- Do not invent fake scores if canonical score exists elsewhere.
- If only one score field exists, copy it into both `score_raw` and `score_final` and set:

```python
score_origin = "fallback_existing_field"
```

- If no score exists, keep `score_missing=True`, but emit a dedicated diagnostic with all available candidate keys:

```text
[PAPER_SCORE_MISSING_CONTEXT] symbol=... source=... keys=[...] ev=... ws=... decision=...
```

Add tests:

- STRICT_TAKE routed candidate preserves `score_raw` / `score_final` into quality entry.
- Portfolio-gate routed candidate preserves score fields.
- Missing score emits `PAPER_SCORE_MISSING_CONTEXT`.
- Missing score is not silently logged only as `na`.
- live/real behavior unchanged.

---

## Task 2 — Guarantee quality exit log for every paper training exit

Production shows:

```text
PAPER_EXIT:               4
PAPER_TRAIN_QUALITY_EXIT: 2
```

Find all paper training close paths:

- TP
- SL
- TIMEOUT
- TIMEOUT_NO_PRICE
- quarantine
- manual/cleanup close if present
- exception/fallback close if present

Centralize quality exit logging so it happens once per closed paper training trade.

Implementation requirement:

Introduce an idempotent helper, for example:

```python
_log_quality_exit_once(
    trade,
    reason,
    exit_price,
    now,
    outcome,
    net_pnl_pct,
    path="unknown",
)
```

Requirements:

- Maintain a set of logged exit `trade_id`s to avoid duplicates.
- Emit quality exit before/after `PAPER_EXIT`, but always within the same close path.
- If a paper training trade closes without quality exit, emit:

```text
[PAPER_TRAIN_QUALITY_EXIT_MISSING] trade_id=... symbol=... reason=... path=...
```

Required quality-exit fields:

```text
trade_id
symbol
side
entry
exit
mfe_pct
mae_pct
exit_efficiency
hold_s
reason
outcome
```

Add tests:

- TP close emits exactly one quality exit.
- SL close emits exactly one quality exit.
- TIMEOUT close emits exactly one quality exit.
- TIMEOUT_NO_PRICE/quarantine emits exactly one quality exit.
- duplicate close does not duplicate quality exit.
- missing required exit fields logs anomaly.

---

## Task 3 — Move LM_STATE_AFTER_UPDATE into canonical lm_update path

Production can show:

```text
Latest Total trades in LM: 1
LEARNING_UPDATE ok=True: 0
LM_STATE_AFTER_UPDATE: 0
```

This means canonical state can mutate without reliable canonical post-update logging.

Patch `src/services/learning_monitor.py` so the canonical mutation function itself logs after incrementing `lm_count`.

Expected log:

```text
[LM_STATE_AFTER_UPDATE] source=paper_closed_trade symbol=... regime=... key=(...,...) before_total=... after_total=... before_key=... after_key=... outcome=... net_pnl_pct=...
```

Rules:

- Log when `source == "paper_closed_trade"` or when caller explicitly passes `source`.
- If `ok=True` but `after_total <= before_total`, emit:

```text
[LM_UPDATE_MISMATCH] ok=True but canonical_total_unchanged ...
```

- Do not depend on caller-side logging for this.
- Keep existing `LEARNING_UPDATE` log if present, but treat `LM_STATE_AFTER_UPDATE` as canonical verification.

Add tests:

- `paper_closed_trade` update increments `lm_count` and logs `LM_STATE_AFTER_UPDATE`.
- mismatch logs if no increment occurs.
- non-paper update behavior unchanged.

---

## Task 4 — Fix audit script PID filtering and journal robustness

Improve `scripts/p11ag_quality_audit.sh`.

Requirements:

Resolve current PID once:

```bash
PID=$(systemctl show -p MainPID --value cryptomaster)
```

All counts and sample logs must filter current PID:

```bash
grep "cryptomaster\[$PID\]"
```

Print:

```text
Service PID
Service start time
Since window
Git HEAD
```

If `journalctl` fails with `Bad message`, do not return false zero counts. Fall back to:

1. smaller time window
2. `--since "$SERVICE_START_TIME"`
3. clear warning explaining journal corruption/iteration failure

Audit must count:

```text
PAPER_TRAIN_ENTRY
PAPER_TRAIN_QUALITY_ENTRY
PAPER_TRAIN_QUALITY_EXIT
PAPER_TRAIN_QUALITY_MISMATCH
PAPER_TRAIN_QUALITY_EXIT_MISSING
PAPER_TRAIN_ANOMALY
PAPER_EXIT
LEARNING_UPDATE ok=True
LM_STATE_AFTER_UPDATE
LM_UPDATE_MISMATCH
Latest Total trades in LM
```

Audit pass criteria:

```text
quality_entry >= paper_train_entry
quality_exit >= paper_exit for paper training trades
quality_mismatch = 0
quality_exit_missing = 0
LM_STATE_AFTER_UPDATE >= paper training exits that call learning
```

---

## Task 5 — Tests

Add regression tests without deleting existing tests.

Run:

```bash
python -m pytest tests/test_paper_mode.py -q
python -m pytest -q
```

Expected:

- all previous tests still pass
- new P1.1AJ tests pass
- no live/real-mode behavior changes

---

## Production validation after deploy

After commit and deploy:

```bash
cd /opt/cryptomaster

git rev-parse --short HEAD
git merge-base --is-ancestor <P1.1AJ_COMMIT> HEAD \
  && echo "OK: P1.1AJ deployed" \
  || echo "BAD: P1.1AJ missing"

sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

Manual verification:

```bash
PID=$(systemctl show -p MainPID --value cryptomaster)

sudo journalctl -u cryptomaster --since "30 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_ENTRY|PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_QUALITY_EXIT_MISSING|PAPER_SCORE_MISSING_CONTEXT|PAPER_TRAIN_ANOMALY|PAPER_EXIT|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|LM_UPDATE_MISMATCH|Total trades in LM" \
| tail -220
```

Expected after 1–2 timeout cycles:

```text
PAPER_TRAIN_ENTRY > 0
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY
PAPER_TRAIN_QUALITY_EXIT >= PAPER_EXIT for paper training trades
PAPER_TRAIN_QUALITY_EXIT_MISSING = 0
PAPER_TRAIN_QUALITY_MISMATCH = 0
LM_STATE_AFTER_UPDATE appears after paper learning updates
Total trades in LM increments after exits
```

Acceptable for now:

```text
LEARNING health=0.0000 [BAD]
```

Reason: current sample size is tiny and early outcomes are mostly LOSS/FLAT. Do not optimize strategy quality in P1.1AJ.

Not acceptable:

```text
tp_sl_invalid
expected_move_extreme caused by ATR absolute units
systematic score_missing_for_take
PAPER_TRAIN_QUALITY_EXIT_MISSING
LM count increments without LM_STATE_AFTER_UPDATE
```

---

## Final response format

When done, report:

```text
P1.1AJ Complete
Commit: <hash>

Changed files:
- ...

Tests:
- ...

Production validation commands:
- ...
```
