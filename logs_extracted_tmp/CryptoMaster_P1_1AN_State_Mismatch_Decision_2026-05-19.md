# CryptoMaster — P1.1AN / P1.1AO Latest Audit Decision

**Audit date:** 2026-05-19  
**Service PID:** 1070310  
**Git HEAD:** 6b79605  
**Window:** 180 min  
**Decision:** Do not tune economics. Investigate state mismatch before any strategy/TP/SL patch.

---

## 1. Executive Verdict

This audit is different from the previous post-P1.1AN audits.

The bot is not fully blocked, but the audit now shows a **structural state mismatch**:

```text
Latest Total trades in LM: 184
STATE_MISMATCH_LOGS: 4
COST_EDGE_BYPASS_ACCEPTED logs still show trades=0
```

That means at least one part of the cold-start / bootstrap / probe path is still reading stale or wrong trade-count state.

This is **not** a reason for P1.1AN economic tuning.

It is also **not** a reason to add broad diagnostics.

The next step should be a small precheck focused only on why `trades=0` is still used while LM has 184 trades.

---

## 2. What Is Working

| Area | Evidence | Status |
|---|---:|---|
| LM state updates | `LM_STATE_AFTER_UPDATE=11` | Working |
| LM mismatch detection | `LM_UPDATE_MISMATCH=0` | Clean |
| Quality exit missing | `QUALITY_EXIT_MISSING_BY_TRADE_ID=0` | Clean |
| C_WEAK_EV_TRAIN calibration | `geometry_calibrated=True` on C_WEAK entries | Working |
| Probe fallback | `NEG_EV_PROBE_ACCEPTED=4`, `NEG_EV_PROBE_EXITS=3` | Active |
| Rate-cap reservation | `sampler_rate_cap=0`, `PAPER_SAMPLER_RATE_CAP_STATE=0` | Not blocking |

---

## 3. New Structural Problem

### 3.1 Trade-count mismatch

Audit shows:

```text
Latest Total trades in LM: 184
STATE_MISMATCH_LOGS: 4
```

But sample logs still show:

```text
reason=bootstrap_training_sample trades=0
```

This is the key issue.

The bot has learned/closed many trades, but the bootstrap/bypass path still behaves as if it is cold-start with zero trades.

### Likely root cause

One of these is probably true:

1. The sampler uses `learning_event.get_metrics()["trades"]`, but that value is stale or not connected to canonical LM state.
2. The sampler is reading global trade count from a different store than `LM_STATE_AFTER_UPDATE`.
3. The bootstrap bypass condition uses a local/global counter that resets on restart.
4. The audit's `Latest Total trades in LM` is canonical, but the sampler uses a legacy metric path.
5. `STATE_MISMATCH_LOGS` already identifies this exact discrepancy, but the code still treats mismatch as diagnostic-only instead of disabling bootstrap/probe.

---

## 4. Why No Economic Patch Yet

The current C_WEAK attribution sample is too small:

```text
PAPER_TRAIN_ECON_ATTRIB: 5
ATTR_COST_EDGE_BYPASS_LOSS: 4
```

That looks like 80%, but it is only 5 attributed C_WEAK samples in this audit window.

Also, because the system still uses `trades=0`, the sample is polluted by incorrect bootstrap behavior. Any economic tuning based on this would be premature.

---

## 5. D_NEG_EV_CONTROL / C_NEG_EV_PROBE Note

The audit includes entries like:

```text
training_bucket=D_NEG_EV_CONTROL
geometry_calibrated=False
tp_pct=1.200
sl_pct=1.200
```

and:

```text
training_bucket=C_NEG_EV_PROBE
geometry_calibrated=False
tp_pct=1.200
sl_pct=1.200
```

This is expected under the current P1.1AN scope, because P1.1AN calibration was limited to:

```text
paper_train + training_sampler + C_WEAK_EV_TRAIN
```

Do not expand calibration yet.

First fix or explain the `trades=0` state mismatch.

---

## 6. Orphan / Non-Training Exit Note

Audit shows:

```text
PAPER_EXIT_NON_TRAINING: 6
PAPER_EXIT_TRAINING_BUCKET: 5
PAPER_TRAIN_QUALITY_EXIT: 11
```

This is not immediately fatal because:

```text
QUALITY_EXIT_MISSING_BY_TRADE_ID: 0
LM_UPDATE_MISMATCH: 0
```

But it means the 180-minute window mixes several paper paths:

- C_WEAK_EV_TRAIN
- C_NEG_EV_PROBE
- D_NEG_EV_CONTROL
- non-training/orphan exits

Do not evaluate P1.1AN quality from the mixed aggregate alone.

---

## 7. Decision

```text
P1.1AN_TUNING_ALLOWED = NO
NEW_DIAGNOSTIC_EXPANSION = NO
BROAD_PATCHING = NO
STATE_MISMATCH_PRECHECK = YES
```

Allowed next work:

- Inspect existing `STATE_MISMATCH` logs.
- Identify the exact function returning `trades=0`.
- Compare that value to canonical LM total.
- Patch only if the source of the stale count is proven.

Forbidden:

- Do not adjust TP/SL again.
- Do not tune RDE.
- Do not tune EV.
- Do not expand probes.
- Do not add dashboards.
- Do not calibrate D_NEG_EV_CONTROL yet.
- Do not treat 4/5 cost-edge-bypass losses as a valid dominant sample.

---

## 8. Minimal Server Commands

Run from repo root:

```bash
cd /opt/cryptomaster

# 1) Confirm current code
git log --oneline -8
git status

# 2) Inspect exact mismatch logs
journalctl -u cryptomaster --since "3 hours ago" --no-pager \
  | grep -E "PAPER_TRAIN_STATE_MISMATCH|STATE_MISMATCH|bootstrap_training_sample|LM_STATE_AFTER_UPDATE" \
  | tail -n 120

# 3) Locate trade-count source in code
grep -R "get_metrics\|global_trades\|closed_training\|trades.*0\|bootstrap_training_sample" -n src/services tests \
  | head -n 200

# 4) Re-run audit with shorter and longer windows
bash scripts/p11ag_quality_audit.sh --since "60 min ago"
bash scripts/p11ag_quality_audit.sh --since "6 hours ago"
```

---

## 9. Minimal Next Patch Scope If Confirmed

Only if inspection proves the sampler is reading the wrong trade count:

### P1.1AU — Canonical Training Count Source Fix

Goal:

```text
bootstrap/probe/cost-edge bypass must read the same canonical count as LM_STATE_AFTER_UPDATE
```

Allowed code change:

- Replace stale `get_metrics()["trades"]` / local count with canonical LM count.
- Or add a small adapter helper like:

```python
get_canonical_training_trade_count()
```

Requirements:

- If LM total > threshold, bootstrap bypass must stop claiming `trades=0`.
- Keep live/real untouched.
- Keep P1.1AN geometry untouched.
- Keep probes bounded.
- Add only focused tests for state-count source.

Acceptance:

```text
STATE_MISMATCH_LOGS = 0
bootstrap_training_sample logs no longer show trades=0 when LM total is high
C_WEAK_EV_TRAIN entries still flow
LM_UPDATE_MISMATCH = 0
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
```

---

## 10. Final Recommendation

Do not patch economics.

Do not open another broad diagnostic phase.

The only legitimate next target is:

```text
Why does bootstrap/probe still see trades=0 while LM total is 184?
```

After that is fixed or explained, collect a clean bucket-separated sample before deciding any further tuning.
