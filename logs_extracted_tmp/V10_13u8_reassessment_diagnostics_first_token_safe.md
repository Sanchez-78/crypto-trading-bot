# CryptoMaster V10.13u+8 — Reassessment Before Anti-Churn Patch

## Decision

Do NOT apply the previous emergency anti-churn patch yet.

Reason: the previous patch is logically valid but too aggressive as a first step. It mixes 3 different concerns:
1. economic BAD entry gating,
2. forced-explore blocking,
3. scratch/stagnation exit behavior.

Because the bot is live and still collecting data, applying all at once may reduce churn but can also hide the real root cause and make later tuning harder.

## Current Confirmed State

The consistency/safety patch is working:

```text
Economic: 0.340 [BAD]
PF: 0.75-0.76
[ECON_SAFETY_BAD] pf=0.75 net_pnl<0 action=conservative_mode
```

The previous PF source drift is fixed:
- dashboard PF and economic PF now match,
- status is BAD,
- no more false GOOD with PF < 1.

## Current Problem

Safety status is now correct, but behavior is not conservative enough.

Live evidence:

```text
[ECON_SAFETY_BAD] pf=0.75 ... action=conservative_mode
decision=TAKE ev=0.0300 p=0.5000 coh=0.500
STAGNATION_EXIT / SCRATCH_EXIT dominate negative PnL
```

This means:
- Economic health detects BAD mode.
- But BAD mode does not reliably affect final entry acceptance.
- Low-edge trades are still allowed.
- Exit churn remains the main leak.

## Reassessment

Do NOT start by rewriting exit behavior.

First prove where the safety signal is lost:
- Is `economic_status=BAD` passed into RDE?
- Is conservative mode only logged but not used?
- Are thresholds changed but later overwritten by bootstrap/unblock logic?
- Are forced signals bypassing economic safety?
- Are `decision=TAKE ev=0.0300` trades generated from fallback/forced path instead of normal path?

## New Safer Patch Plan

Apply a diagnostics-first patch with one small behavioral clamp only.

---

# Patch A — Wire Trace for Economic Safety

Add one compact log at the final decision point, only when economic BAD is active:

```text
[ECON_GATE_TRACE] symbol=... side=... pf=... net_pnl=... econ_status=BAD conservative=True forced=... bootstrap=... idle=... ev=... score=... p=... coh=... final_threshold_ev=... final_threshold_score=... decision=...
```

Purpose:
- prove whether BAD mode reaches the final decision,
- prove whether forced/bootstrapped/unblock paths bypass it,
- show exact thresholds used when TAKE happens.

Throttle:
- max once per symbol per 60 seconds,
- always log if decision is TAKE during BAD.

---

# Patch B — Minimal Entry Clamp During Economic BAD

Only block the weakest low-edge entries.

When:
```python
pf < 1.0 and net_pnl <= 0
```

Reject only if all of these are weak:
```python
ev < 0.040
p <= 0.52
coherence <= 0.52
```

Reject reason:

```text
decision=REJECT_ECON_BAD_WEAK_EDGE ev=... p=... coh=... pf=... net_pnl=...
```

This blocks the observed bad pattern:

```text
decision=TAKE ev=0.0300 p=0.5000 coh=0.500
```

But still allows genuinely better candidates.

Do NOT require ev 0.050 / p 0.55 / coherence 0.55 yet. That was too strict for first deployment.

---

# Patch C — Forced Explore Safety Only

During Economic BAD:

```python
pf < 1.0 and net_pnl <= 0
```

Forced explore may still create/log candidates, but cannot execute if:
```python
ev <= 0.0
```

Reject:

```text
decision=REJECT_FORCED_EXPLORE_NEG_EV_ECON_BAD
```

Do NOT fully disable forced explore yet. Only block negative/zero-EV forced execution.

---

# Patch D — Observe Exits, Do Not Change Yet

Do not change `STAGNATION_EXIT` or `SCRATCH_EXIT` behavior in this patch.

Instead add compact exit-quality diagnostics:

```text
[EXIT_LEAK_TRACE] reason=STAGNATION_EXIT count=... net=... avg=... share_trades=... share_loss=...
[EXIT_LEAK_TRACE] reason=SCRATCH_EXIT count=... net=... avg=... share_trades=... share_loss=...
```

Throttle:
- once per 60 seconds.

Purpose:
- confirm whether losses are from exit logic itself or from weak entries.
- avoid changing entries and exits at the same time.

---

# Patch E — Fix Log Formatting Bug

Current log contains malformed bracket:

```text
WARNING:src.services.learning_monitor:ECON_SAFETY_BAD]
```

Fix to:

```text
WARNING:src.services.learning_monitor:[ECON_SAFETY_BAD]
```

No logic impact.

---

# Tests Required

1. Economic BAD + weak edge is rejected:

```python
pf=0.75
net_pnl=-0.0005
ev=0.030
p=0.500
coh=0.500
=> REJECT_ECON_BAD_WEAK_EDGE
```

2. Economic BAD + better edge is allowed:

```python
pf=0.75
net_pnl=-0.0005
ev=0.045
p=0.54
coh=0.54
=> not rejected by ECON_BAD_WEAK_EDGE
```

3. Economic BAD + negative forced explore is rejected:

```python
forced=True
pf=0.75
net_pnl=-0.0005
ev=-0.01
=> REJECT_FORCED_EXPLORE_NEG_EV_ECON_BAD
```

4. Economic BAD trace logs on TAKE.

5. Exit leak trace is throttled.

6. Existing canonical PF tests still pass.

---

# Acceptance Criteria

After deploy/restart:

```bash
sudo systemctl restart cryptomaster
sleep 10
sudo journalctl -u cryptomaster -n 1500 --no-pager | grep -E "RUNTIME_VERSION|ECON_SAFETY_BAD|ECON_GATE_TRACE|REJECT_ECON_BAD_WEAK_EDGE|REJECT_FORCED_EXPLORE_NEG_EV_ECON_BAD|EXIT_LEAK_TRACE|decision=TAKE|Traceback|ERROR"
```

Success:
- `[ECON_GATE_TRACE]` appears for decisions during BAD mode.
- Weak pattern is blocked:
  - no repeated `decision=TAKE ev=0.0300 p=0.5000 coh=0.500` during PF < 1.
- New reject appears:
  - `REJECT_ECON_BAD_WEAK_EDGE`
- Negative forced explore is blocked:
  - `REJECT_FORCED_EXPLORE_NEG_EV_ECON_BAD`
- Exit behavior is not changed yet.
- No Traceback.

---

# Observation Window

Run 30-60 minutes.

Collect:

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager | grep -E "ECON_GATE_TRACE|REJECT_ECON_BAD_WEAK_EDGE|decision=TAKE|EXIT_LEAK_TRACE|STAGNATION_EXIT|SCRATCH_EXIT|ECON_SAFETY_BAD" > /tmp/v10_13u8_observation.log
```

Then evaluate:
- Are weak TAKEs gone?
- Did trade count slow down?
- Are STAGNATION/SCRATCH losses still growing?
- Are good edges still allowed?
- Is forced explore still producing negative-EV candidates?

Only after that decide whether to apply exit guards.

---

# Next Patch Only If Needed

If after 30-60 minutes:
- weak entries are gone,
- but STAGNATION/SCRATCH still bleed,

then create a separate V10.13u+9 patch only for exit guards:
- fee-aware SCRATCH,
- young-negative STAGNATION hold,
- churn cooldown.

Do not combine it with entry gating.

## Commit Message

```text
fix: trace and lightly gate economic bad low-edge entries
```
