# CryptoMaster — V10.13v Correctness Prompt (Fix 6 + Fix 7)

## Role
You are a senior quant/backend engineer working on a live Python trading bot.  
Your task is to implement **correctness and observability fixes only**.  
Do **not** retune strategy thresholds unless explicitly required for correctness.

Project context:
- Event-driven live trading bot
- Exchange: Binance Futures
- Core path: signal generation -> RDE -> execution -> exit -> learning monitor -> Firebase
- Existing runtime versions/log markers include: `V10.10b`, `V10.12`, `V10.13r/u`
- Recent fixes already completed:
  - hard positive-EV gate
  - canonical decision logging
  - explicit bootstrap state tracking
  - grounded learning state
  - net-edge decomposition

This prompt implements the next 2 remaining critical fixes:

1. **Fix 6 — Eliminate ambiguous EV/direction/regime combinations in logs**
2. **Fix 7 — Instrument exit outcome distribution and realized edge attribution**

---

## Non-negotiable rules

1. **Correctness first**
   - Prefer rejecting/labeling inconsistent state over silently continuing.
   - Never hide contradictions in logs.

2. **No fake observability**
   - Every printed field must come from real runtime state.
   - Do not print synthetic summaries unless backed by real counters.

3. **Single source of truth**
   - Action, regime, EV, direction, and outcome must each come from canonical fields.
   - No duplicated “best guess” formatting paths.

4. **No strategy retuning**
   - Do not change thresholds, RR, TP/SL, EV limits, or bandit logic unless needed to preserve semantic consistency.

5. **Preserve existing behavior where possible**
   - Only change runtime behavior if current behavior is provably misleading or incorrect.

---

## Goal A — Fix 6: eliminate ambiguous decision combinations

### Problem
Logs still show confusing combinations like:
- action says `PRODEJ/SELL`
- regime says `BULL`
- EV appears negative or positive in conflicting places
- final decision line can disagree with earlier candidate lines

This makes postmortem analysis unreliable even if execution logic is correct.

### Required outcome
For every candidate, there must be exactly **one canonical semantic interpretation** of:
- symbol
- candidate side (`BUY`/`SELL`)
- market regime (`BULL_TREND`, `BEAR_TREND`, `RANGING`, etc.)
- raw EV
- transformed/final EV
- score raw/final
- decision result (`TAKE` or specific reject reason)
- reason chain

### Implement

#### 1. Introduce canonical decision payload
Create a structured payload/dataclass/dict, for example:

```python
decision_ctx = {
    "symbol": sym,
    "side": side,                  # BUY / SELL
    "regime": regime,              # BULL_TREND / BEAR_TREND / ...
    "signal_tag": signal_tag,      # fake_breakout / FORCED_EXPLORE / ...
    "score_raw": score_raw,
    "score_final": score_final,
    "score_threshold": score_threshold,
    "ev_raw": ev_raw,
    "ev_after_coherence": ev_after_coherence,
    "ev_final": ev_final,
    "prob": p,
    "rr": rr,
    "ws": ws,
    "auditor_factor": af,
    "coherence": coh,
    "bootstrap_pair": bootstrap_pair,
    "bootstrap_global": bootstrap_global,
    "decision": decision,          # TAKE / REJECT_NEGATIVE_EV / NET_EDGE_BLOCK / ...
    "decision_stage": stage,       # RDE / NET_EDGE / EXEC_QUALITY / ...
    "reason_chain": [...],         # ordered list of transforms/blocks
}
```

This object must be the **only source** for final decision logging.

#### 2. Separate regime from trade side semantically
Regime is market state. Side is trade direction.  
These are not contradictions by themselves:

- `SELL + BULL_TREND` can be valid if signal is countertrend/reversal/forced explore
- `BUY + BEAR_TREND` can be valid for reversal

But logs must make this explicit.

Add a field such as:
- `alignment = "WITH_REGIME" | "COUNTER_REGIME" | "NEUTRAL"`

Rules:
- BUY + BULL_TREND => WITH_REGIME
- SELL + BEAR_TREND => WITH_REGIME
- BUY + BEAR_TREND => COUNTER_REGIME
- SELL + BULL_TREND => COUNTER_REGIME
- ranging/quiet/high-vol can map to NEUTRAL where appropriate

#### 3. Canonical decision log format
Replace ambiguous output with one final line per candidate like:

```python
[V10.13v DECISION] BTCUSDT SELL BEAR_TREND WITH_REGIME
  tag=FORCED_EXPLORE stage=RDE
  ev_raw=0.0500 ev_coh=0.0348 ev_final=0.0348
  score_raw=0.1850 score_final=0.1850 thr=0.1728
  p=0.533 rr=1.25 ws=0.500 af=0.70 coh=0.500
  bootstrap=pair:False global:False
  result=TAKE
```

or, for rejects:

```python
[V10.13v DECISION] ETHUSDT SELL BEAR_TREND WITH_REGIME
  tag=fake_breakout stage=EV_GATE
  ev_raw=-0.0500 ev_coh=-0.0399 ev_final=-0.0399
  score_raw=0.1310 score_final=0.1310 thr=0.1728
  p=0.479 rr=1.50 ws=0.555 af=0.70 coh=0.797
  bootstrap=pair:False global:False
  result=REJECT_NEGATIVE_EV
```

#### 4. Explicit contradiction detector
Add a validation helper before final logging:

```python
validate_decision_ctx(decision_ctx)
```

It should detect and warn or assert on:
- missing side/regime/decision
- non-finite ev/score/prob
- `result=TAKE` with `ev_final <= 0`
- unknown decision stage
- inconsistent final state after rejection
- invalid alignment label
- duplicate final logs for same candidate id/timestamp

On violation:
- log `[V10.13v DECISION_INTEGRITY_ERROR]`
- include serialized decision_ctx
- fail fast in audit/test mode
- remain safe in live mode (reject candidate rather than accept)

#### 5. Remove conflicting legacy prints
Do not leave old scattered prints that can contradict canonical output.
Either:
- route them through the same canonical formatter, or
- demote them to debug-only pre-transform traces clearly marked as intermediate.

Allowed intermediate format:
```python
[TRACE PRE_DECISION] ...
```

Forbidden:
- old-style final decision text that looks authoritative but is not canonical

---

## Goal B — Fix 7: exit outcome distribution and realized edge attribution

### Problem
Runtime suggests most exits are scratch/micro/partial while TP/SL/trail remain near zero.  
This may flatten expectancy and hide where the edge is actually being realized or lost.

Current reporting is insufficient because it counts exit types but does not connect them to:
- realized pnl
- net contribution
- average hold time
- pair/regime/side context
- whether exits are rescuing bad entries or truncating good trades

### Required outcome
Exit analysis must answer:

1. Which exit types are actually closing trades?
2. Which exit types make or lose money after fees?
3. Are scratch/micro exits protective or destructive?
4. Is realized expectancy coming from a tiny subset of exit types?
5. Are TP/SL labels absent because logic never reaches them, or because other exits pre-empt them?

### Implement

#### 1. Canonical exit classification
Create a single canonical exit type enum/string:

- `TP`
- `SL`
- `TRAIL`
- `PARTIAL_TP_25`
- `PARTIAL_TP_50`
- `BE_EXIT`
- `SCRATCH_EXIT`
- `MICRO_EXIT`
- `TIMEOUT_PROFIT`
- `TIMEOUT_FLAT`
- `TIMEOUT_LOSS`
- `STAGNATION_EXIT`
- `HARVEST_EXIT`
- `WALL_EXIT`
- `MANUAL_EXIT`
- `UNKNOWN_EXIT`

Every closed trade must have exactly one primary exit type.  
If partials occurred before final close, preserve both:
- `partials_taken`
- `final_exit_type`

#### 2. Exit attribution payload
At close, construct canonical exit payload:

```python
exit_ctx = {
    "symbol": sym,
    "regime": regime,
    "side": side,
    "entry_price": entry,
    "exit_price": exit_price,
    "size": size,
    "hold_seconds": hold_seconds,
    "gross_pnl": gross_pnl,
    "fee_cost": fee_cost,
    "slippage_cost": slip_cost,
    "net_pnl": net_pnl,
    "r_multiple": r_multiple,
    "mae": mae,
    "mfe": mfe,
    "partials_taken": ["PARTIAL_TP_25"],
    "final_exit_type": final_exit_type,
    "exit_reason_text": exit_reason_text,
    "was_winner": net_pnl > 0,
    "was_forced": is_forced,
}
```

This payload should be persisted or aggregated exactly once per closed trade.

#### 3. Exit stats aggregator
Maintain rolling and lifetime aggregates by:
- `final_exit_type`
- `symbol`
- `regime`
- optionally `side`

For each exit type track:
- count
- win count
- loss count
- total gross pnl
- total net pnl
- average net pnl
- average hold time
- average MFE
- average MAE
- share of all exits
- contribution to total pnl (%)

#### 4. Add dashboard/log summary
Print a grounded exit contribution block, for example:

```python
=== EXIT ATTRIBUTION ===
  TP              count=3    share=2.6%   net=+0.000081  avg=+0.000027
  SL              count=4    share=3.5%   net=-0.000102  avg=-0.000026
  SCRATCH_EXIT    count=24   share=20.9%  net=-0.000018  avg=-0.000001
  MICRO_EXIT      count=3    share=2.6%   net=+0.000004  avg=+0.000001
  PARTIAL_TP_25   count=22   share=19.1%  net=+0.000031  avg=+0.000001
  TIMEOUT_FLAT    count=0    share=0.0%   net=+0.000000  avg=+0.000000
```

Also print:
- top positive contributor exit type
- top negative contributor exit type
- scratch+micro combined share
- TP+trail share
- partial-to-final conversion rate if available

#### 5. Add “pre-emption” diagnostics
We need to know if TP/SL/trail are absent because other exits happen first.

For each closed trade, track whether at any point during its life:
- TP threshold was touched
- SL threshold was touched
- trail activation threshold was touched
- partial threshold was touched

If feasible from live state, add booleans:
```python
tp_touched
sl_touched
trail_armed
partial_touched
```

Then aggregate:
- `% of scratch exits that had TP touched before scratch`
- `% of micro exits that never reached partial threshold`
- `% of trades where trail armed but final exit was not TRAIL`

This is critical for diagnosing truncation of winners.

#### 6. Grounded exit integrity checks
Add validator:

```python
validate_exit_ctx(exit_ctx)
```

Check:
- exactly one primary final exit type
- net_pnl = gross_pnl - fees - slippage (within tolerance)
- hold_seconds >= 0
- no impossible combo like `TP` with strongly negative realized net unless fees/slippage explain it
- no duplicate persistence for same trade close event

On violation:
- log `[V10.13v EXIT_INTEGRITY_ERROR]`
- fail in audit/test mode
- in live mode, classify as `UNKNOWN_EXIT` and log full context

---

## Acceptance criteria

### Fix 6 accepted only if:
1. No final authoritative decision logs remain outside canonical formatter.
2. Every decision line explicitly contains:
   - symbol
   - side
   - regime
   - alignment
   - ev_raw / ev_final
   - score / threshold
   - result
3. No `TAKE` appears with `ev_final <= 0`.
4. Contradiction validator exists and is exercised in audit/test path.
5. Bootstrap annotation only appears when truly active.

### Fix 7 accepted only if:
1. Every closed trade gets exactly one canonical `final_exit_type`.
2. Exit attribution aggregates show both count and net PnL by exit type.
3. Scratch/micro/partial exits have monetary contribution reporting.
4. At least one pre-emption diagnostic is implemented.
5. Exit integrity validator exists.

---

## Deliverables

Provide all of the following:

1. **Modified full files**, not diffs only
2. Short explanation of what changed in each file
3. Example log output for:
   - accepted decision
   - rejected negative EV decision
   - exit attribution summary
4. Brief note on any assumptions
5. If any part cannot be implemented safely without seeing a specific file, state exactly which file/function is needed

---

## Important implementation guidance

- Search likely files first:
  - `src/services/realtime_decision_engine.py`
  - `src/services/trade_executor.py`
  - `src/services/learning_monitor.py`
  - `src/services/execution_quality.py`
  - `src/services/policy_layer.py`
  - `src/services/pre_live_audit.py`
  - any log helper / utils / metrics module

- Prefer small helper functions:
  - `_build_decision_ctx(...)`
  - `_validate_decision_ctx(...)`
  - `_log_canonical_decision(...)`
  - `_build_exit_ctx(...)`
  - `_validate_exit_ctx(...)`
  - `_update_exit_attribution(...)`
  - `_render_exit_attribution_summary(...)`

- Reuse existing metrics dicts/counters if possible
- Avoid creating heavy new dependencies
- Keep runtime overhead low

---

## Final instruction

Implement Fix 6 and Fix 7 now in a correctness-first way.  
Do not optimize for brevity.  
Do not skip validation guards.  
Prefer explicitness, canonical state, and auditability over cleverness.
