# P1.1AP-J — Paper Exploration Telemetry Clarity (Compressed Patch Prompt)

## Task
Implement a **diagnostic-only** patch that removes ambiguity around `B_RECOVERY_READY` and false `[LEARNING_UPDATE]` telemetry. Do not tune economics or change decision behavior.

## Proven facts
- Production is on `07fc451`; P1.1AP-I2 is validated: D_NEG is shadow-only, has real `trade_id`, and no post-I2 `LEARNING_UPDATE.*D_NEG_EV_CONTROL`.
- `paper_exploration.py` selects B using:
  ```python
  if ev >= 0.038 or recovery_ready or probe_ready:
  ```
- Thus `bucket=B_RECOVERY_READY recovery_ready=False probe_ready=False ev=0.0399` is allowed by design via `ev >= 0.038`, not a routing bug.
- Tests explicitly expect `B_RECOVERY_READY` for `EV >= 0.038`.
- Current post-I2 B observations:
  ```text
  B_RECOVERY_READY: n=5, WIN=0, LOSS=4, FLAT=1, PF=0.00,
  timeout_rate=100%, all XRPUSDT BUY
  ```
- B shows legacy:
  ```text
  [LEARNING_UPDATE] source=paper_closed_trade ... bucket=B_RECOVERY_READY ...
  ```
  but no visible B `LM_STATE_AFTER_UPDATE` / canonical `[LEARNING_UPDATE] ok=True ... regime=...`.

## Hard boundaries
Do **not** change:
- `ev >= 0.038` routing threshold or bucket selection logic
- internal bucket name `B_RECOVERY_READY`
- live/real behavior, RDE/ECON_BAD gates, TP/SL, sizing, holds, sampler caps
- P1.1AO probe logic/caps
- P1.1AP-I/I2 D_NEG isolation
- canonical LM mutation behavior
- Firebase schema/collection contracts or Android snapshots

This patch is observability/telemetry only.

## Required changes

### 1. Add explicit B route trigger
File: `src/services/paper_exploration.py`

Where B is selected, keep routing unchanged but calculate a deterministic trigger:
```python
if recovery_ready:
    route_trigger = "recovery_ready"
elif probe_ready:
    route_trigger = "probe_ready"
else:
    route_trigger = "ev_threshold"
```

Return/propagate it through override metadata/tags/reason. Current cases must be explainable as:
```text
bucket=B_RECOVERY_READY route_trigger=ev_threshold recovery_ready=False probe_ready=False ev=0.0399
```

### 2. Include `route_trigger` in `PAPER_EXPLORE_ENTRY`
Update the active production log path in `paper_exploration.py` (found near its `PAPER_EXPLORE_ENTRY` log) and any wrapper only if needed.

Preserve existing fields; add:
```text
route_trigger=<ev_threshold|recovery_ready|probe_ready|other>
```

### 3. Rename misleading Firebase paper-save telemetry
File: `src/services/trade_executor.py`, in the `trades_paper` save path.

Rename the non-shadow save log:
```text
[LEARNING_UPDATE] source=paper_closed_trade ...
```
to:
```text
[PAPER_TRADE_SAVED] source=paper_closed_trade symbol=... bucket=... outcome=... net_pnl_pct=... ok=True
```

Rules:
- Keep `db.collection(col("trades_paper")).add(paper_record)` unchanged.
- Preserve I2: D_NEG must still use `PAPER_TRADE_SAVED_SHADOW` or no normal save log, never `LEARNING_UPDATE`.
- Do **not** rename the real canonical log in `paper_trade_executor.py`:
  ```text
  [LEARNING_UPDATE] ok=True source=paper_closed_trade ... regime=...
  ```

### 4. Add B quality/economic attribution, without changing learning
`B_RECOVERY_READY` emits `PAPER_EXIT` and bucket metrics but lacks useful attribution because `training_bucket=None`.

Add diagnostic attribution for exploratory B exits (`explore_bucket == "B_RECOVERY_READY"` or canonical bucket B):
- Reuse existing quality/econ attribution code; do not invent a parallel calculation.
- Include at least:
  ```text
  trade_id symbol side bucket entry_regime exit_regime reason outcome
  net_pnl_pct gross_move_pct fee_drag_pct mfe_pct mae_pct hold_s hold_limit_s attribution
  ```
- Keep bucket metrics.
- Do not newly call canonical learning for B.
- Do not change exit geometry or entry routing.

## Tests
Add/update narrow tests.

1. `ev >= 0.038`, `recovery_ready=False`, `probe_ready=False`:
   - allowed remains true;
   - bucket remains `B_RECOVERY_READY`;
   - `route_trigger == "ev_threshold"`.

2. `recovery_ready=True` gives B with `route_trigger="recovery_ready"`.

3. `probe_ready=True` gives B with `route_trigger="probe_ready"`.

4. Normal paper Firebase save emits `[PAPER_TRADE_SAVED]`, not legacy `[LEARNING_UPDATE]`.

5. Real canonical C_WEAK log remains:
   ```text
   [LEARNING_UPDATE] ok=True source=paper_closed_trade ...
   ```

6. D_NEG I2 invariants remain:
   - shadow skip with real `trade_id`;
   - no `LEARNING_UPDATE`;
   - no `LM_STATE_AFTER_UPDATE`.

7. B exit emits attribution diagnostics but does not newly mutate canonical LM.

## Validation
```bash
python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_p11ap_i_d_neg_learning_isolation.py   tests/test_v10_13u_patches.py

python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_p11ap_i_d_neg_learning_isolation.py   tests/test_v10_13u_patches.py

python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

## Post-deploy validation
```bash
sudo systemctl restart cryptomaster
sleep 120

sudo journalctl -u cryptomaster --since "15 min ago" --no-pager | grep -E "PAPER_EXPLORE_ENTRY|PAPER_TRADE_SAVED|PAPER_TRADE_SAVED_SHADOW|PAPER_TRAIN_ECON_ATTRIB|PAPER_LEARNING_SHADOW_SKIP|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|B_RECOVERY_READY|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Acceptance:
- B logs include `route_trigger`.
- Paper-save telemetry is `[PAPER_TRADE_SAVED]`, not fake `[LEARNING_UPDATE]`.
- Real canonical `[LEARNING_UPDATE] ok=True ...` remains.
- D_NEG stays shadow-only.
- B has diagnostic attribution.
- No behavior/threshold change or runtime crash.

## Commit
```text
P1.1AP-J: Clarify paper exploration telemetry and B route trigger
```

Do not commit runtime/local artifacts: `data/paper_open_positions.json`, `.env*`, `venv/`, backups, archives, or shell-output files.
