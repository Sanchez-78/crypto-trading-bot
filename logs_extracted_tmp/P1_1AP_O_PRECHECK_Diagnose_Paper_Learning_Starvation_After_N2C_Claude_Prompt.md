# CLAUDE CODE — P1.1AP-O PRECHECK ONLY
## Diagnose PAPER Learning Starvation After Confirmed N2C Lifecycle

## Do not patch, commit, push, restart or tune anything in this task

This task is a **read-only precheck**. It exists because recent patches fixed concrete wiring bugs, but the current blocker is no longer proven to be a bug.

Do not modify source files.  
Do not commit or push.  
Do not restart the service.  
Do not lower thresholds.  
Do not enable real trading.  
Do not add any shadow lane, new learner or negative-EV canonical sampling.

Return evidence and a single justified next-patch specification only if one root cause is proven.

---

# Confirmed current state

Current production process:

```text
PID=1322564
service active since 2026-05-22 16:03:22 UTC
current audit timestamp: 2026-05-25
```

N2C status:

```text
HEAD: 956a12e P1.1AP-N2C: Fix recovery metadata wiring in actual paper open path
Full suite verified: 912 passed in 3.95s, 0 failures, 0 warnings
```

## N2C has succeeded at its actual purpose

One complete canonical recovery learning lifecycle is proven:

```text
[PAPER_TRAIN_QUALITY_ENTRY]
trade_id=paper_28427715e648
symbol=ADAUSDT side=BUY
source=paper_adaptive_recovery
bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
regime=RANGING ev=0.0300
expected_move_pct=0.005
expected_move_src=atr_abs_price_normalized
cost_edge_ok=False

[PAPER_EXIT]
trade_id=paper_28427715e648
outcome=LOSS net_pnl_pct=-0.1388

[PAPER_CANONICAL_LEARNING_UPDATE]
trade_id=paper_28427715e648
learning_source=paper_adaptive_recovery
outcome=LOSS net_pnl_pct=-0.1388
lifetime_n=99 lifetime_pf=1.764 lifetime_expectancy=0.224540
rolling20_n=20 rolling20_pf=0.000 rolling20_expectancy=-0.235995
rolling50_n=50 rolling50_pf=1.269 rolling50_expectancy=0.076296
rolling100_n=99 rolling100_pf=1.764 rolling100_expectancy=0.224540
segment=ADAUSDT:RANGING:BUY policy_action=continue_learning
```

Conclusion:

```text
recovery entry → paper close → canonical adaptive metric update works.
Do not reopen metadata/wiring patches.
```

One telemetry mismatch remains non-blocking:

```text
PAPER_TRAIN_ECON_ATTRIB for paper_28427715e648 reports source=training_sampler
while PAPER_CANONICAL_LEARNING_UPDATE correctly reports learning_source=paper_adaptive_recovery.
```

Record this as later telemetry cleanup only. Do not patch it in this precheck.

## D_NEG exclusion is proven safe

Current-PID audit shows:

```text
PAPER_LEARNING_SHADOW_SKIP count = 17
D_NEG closed trade IDs checked = 17
PAPER_CANONICAL_LEARNING_UPDATE for D_NEG IDs = none shown
```

Examples:

```text
paper_ef32c0c16b1f ETHUSDT D_NEG LOSS → PAPER_LEARNING_SHADOW_SKIP
paper_bc3a80bb53e0 XRPUSDT D_NEG LOSS → PAPER_LEARNING_SHADOW_SKIP
paper_84b3b47a2073 BTCUSDT D_NEG LOSS → PAPER_LEARNING_SHADOW_SKIP
...
paper_9c271367c7c3 SOLUSDT D_NEG LOSS → PAPER_LEARNING_SHADOW_SKIP
```

Conclusion:

```text
D_NEG currently creates diagnostic activity but does not contaminate canonical adaptive learning.
Do not change D_NEG learning isolation.
```

---

# Newly proven blocker: useful PAPER learning starvation

Current PID count summary:

```text
PAPER_TRAIN_QUALITY_ENTRY              20
source=paper_adaptive_recovery          2   # entry + update for one recovery lifecycle
bucket=D_NEG_EV_CONTROL               137   # multiple D_NEG lifecycle log occurrences
PAPER_CANONICAL_LEARNING_UPDATE         1
PAPER_POLICY_ADAPTATION                 0
REAL_READINESS_CHECK                    0
PAPER_LEARNING_SHADOW_SKIP             17
PAPER_LEARNING_ENTRY_BLOCKED            0
PAPER_ENTRY_BLOCKED                     1
cost_edge_too_low                      60
SELF_HEAL: STALL                     2945
WATCHDOG                             6033
```

Interpretation:

```text
- Only one useful canonical adaptive recovery close occurred in ~62 hours.
- D_NEG activity dominates but is not learned.
- Caps/block logs are not the primary current blocker: PAPER_LEARNING_ENTRY_BLOCKED=0 and PAPER_ENTRY_BLOCKED=1.
- There is not enough new learnable flow for policy adaptation or readiness.
```

## Last 6 hours: current candidates are overwhelmingly negative-EV

Logs repeatedly show:

```text
decision=REJECT_NEGATIVE_EV ev=-0.0300 / -0.0338 / -0.0348 / -0.0399 / -0.0905 / -0.1036 / -0.1202 / -0.3315
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched ... original_decision=REJECT_NEGATIVE_EV
SELF_HEAL: STALL (no trades 900s)
[WATCHDOG] Critical idle (15min) → enabling micro-trades
```

Heartbeat:

```text
[ECON_BAD_DIAG_HEARTBEAT]
pf=0.495 econ_status=BAD pf_source=lm_economic_health
total=26208
neg_ev=26172
weak_ev=35
weak_score=1
best_symbol=BTCUSDT best_ev=0.0471
probe_ready=False probe_block=below_probe_p
```

This is approximately:

```text
negative-EV rejects: 99.86% of heartbeat total
weak-positive EV candidates: 0.13% of heartbeat total
```

Therefore `paper_adaptive_recovery` is not currently starved by a missing admission hook; it is starved because almost no positive weak-EV candidates are being produced/allowed into the route.

---

# Major consistency question to answer

The bot now holds at least two incompatible views:

```text
Dashboard / old economic health:
  canonical trades = 100
  PF = 0.49
  net PnL = -0.00023955
  health = BAD
  STAV says "TRENINK (zisk > 0)" despite negative profit

Learning Monitor:
  Total trades in LM = 225

New adaptive learner update:
  recovery lifetime_n=99
  lifetime_pf=1.764
  rolling100_n=99
  rolling100_pf=1.764
  rolling20_pf=0.000 after recent loss
```

You must determine whether:

```text
A. Adaptive learner metrics are only logged/persisted but are not used in PAPER candidate scoring/admission/policy.
B. RDE EV generation is intentionally using old canonical economic-health state; adaptive learning has no influence before REJECT_NEGATIVE_EV.
C. Adaptive metrics do feed a policy path, but no policy adaptation fires because new eligible recovery sample count/segment count is insufficient.
D. Current negative-EV drought is genuinely generated by market/signals rather than stale old metrics.
```

This distinction determines whether the next work is a correctness fix or a strategy experiment.

---

# Investigation tasks

## 1. Verify deployed source and no dirty runtime source

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -12
git --no-pager show --stat --oneline 956a12e
```

## 2. Locate the complete adaptive learner consumers, not only writers

Search all **writes and reads**:

```bash
grep -R "paper_adaptive_learning\|PAPER_CANONICAL_LEARNING_UPDATE\|PAPER_POLICY_ADAPTATION\|REAL_READINESS_CHECK\|rolling20\|rolling50\|rolling100\|policy_action\|get_segment\|weight" -n src/services tests | head -800
```

Produce a table:

```text
File:function | writes adaptive state? | reads adaptive state for a decision? | changes admissions/scores/weights? | evidence lines
```

Critical result:

```text
Does any runtime decision before RDE REJECT_NEGATIVE_EV read the adaptive rolling state?
```

## 3. Trace where candidate EV becomes negative

Locate functions and state sources for the EV in:

```text
[V10.13w DECISION] ... ev_raw=... ev_final=...
decision=REJECT_NEGATIVE_EV
```

Commands:

```bash
grep -R "REJECT_NEGATIVE_EV\|ev_raw\|ev_final\|V10.13w DECISION\|V10.13t\|true_ev\|risk_ev\|conf_ev\|lm_economic_health\|_get_econ_bad_state" -n src/services | head -1000

grep -R "pf_source\|PF\|profit_factor\|health=0.0000\|ECON_BAD_DIAG_HEARTBEAT\|_econ_bad_entry_quality_gate" -n src/services | head -700
```

Produce exact flow:

```text
signal feature output
→ raw EV calculation
→ adjustments/coherence/auditor/penalty
→ final EV
→ NEGATIVE_EV reject
→ paper sampler eligibility or no_bucket_matched
```

For each step specify:
- file:function:line;
- whether old canonical PF/BAD affects it;
- whether new adaptive rolling metrics affects it;
- whether it applies in PAPER only or also real/live.

## 4. Determine whether one recovery trade is one trade or state inconsistency

The adaptive update reports:

```text
lifetime_n=99
rolling100_n=99
```

while only one current-PID canonical adaptive update exists.

Inspect adaptive state load/restore and origin without editing:

```bash
find data server_local_backups -maxdepth 5 -type f \
  \( -iname '*adaptive*learning*' -o -iname '*learner*state*' -o -iname '*policy*state*' \) -print 2>/dev/null

for F in $(find data server_local_backups -maxdepth 5 -type f \
  \( -iname '*adaptive*learning*' -o -iname '*learner*state*' -o -iname '*policy*state*' \) 2>/dev/null); do
  echo "=== $F ==="
  ls -lh "$F"
  ./venv/bin/python - <<PY
import json
from pathlib import Path
p=Path("$F")
try:
    data=json.loads(p.read_text())
    text=json.dumps(data)
    print("keys=", list(data)[:30] if isinstance(data, dict) else type(data).__name__)
    print("contains_D_NEG=", "D_NEG_EV_CONTROL" in text)
    print("contains_paper_adaptive_recovery=", "paper_adaptive_recovery" in text)
    print("snippet=", text[:1000])
except Exception as e:
    print("read_error=", e)
PY
done
```

Explain whether `lifetime_n=99` represents:
- actual eligible canonical closes from the current integrated learner;
- restored historical/training-sampler closes;
- a migrated/rebuilt sample;
- or a misleading state count.

## 5. Confirm D_NEG does not consume scarce capacity at the exact moment recovery candidates appear

Current high D_NEG count alone is not enough to blame it because `PAPER_ENTRY_BLOCKED=1`.

Extract overlap only around positive recovery-capable events:

```bash
LOG=/tmp/n2c_pid_1322564_full.log
sudo journalctl -u cryptomaster _PID=1322564 --no-pager -o cat > "$LOG"

grep -n -E "paper_adaptive_recovery|REJECT_ECON_BAD_ENTRY|weak_ev|PAPER_ENTRY_BLOCKED|D_NEG_EV_CONTROL|PAPER_EXPLORE_SKIP.*cost_edge_too_low" "$LOG" | tail -250
```

Determine:

```text
Were any valid positive recovery admissions prevented because D_NEG occupied global/per-symbol open caps?
YES / NO / NOT PROVEN
```

Do not propose separate D_NEG capacity unless this is proven.

## 6. Quantify what changed after recovery close

For `paper_28427715e648`, locate persisted policy state and any subsequent decision impact:

```bash
grep -R "paper_28427715e648\|ADAUSDT:RANGING:BUY\|rolling20_pf\|policy_action=continue_learning\|PAPER_POLICY_ADAPTATION" -n data server_local_backups src 2>/dev/null | head -200
```

Answer:

```text
Did this learned loss alter any subsequent paper selection weight, EV, score, gate or only a stored metric/log?
```

---

# Decision gates for the next patch

## Outcome A — Correctness integration bug

If proven that adaptive metrics are updated but never consulted anywhere in PAPER admission/scoring/policy, specify a narrow patch:

```text
P1.1AP-O1: Connect adaptive rolling policy to PAPER-only candidate selection
```

Constraints:
- PAPER mode only;
- does not affect real/live;
- uses existing canonical adaptive state;
- does not canonical-learn D_NEG;
- does not invent positive EV from negative candidates;
- must show policy read → bounded decision impact with tests.

Do not implement in this task; produce the exact patch specification with file:line targets.

## Outcome B — Positive candidates exist but are blocked

If valid positive weak-EV candidates recur and are rejected despite N2C, specify a narrow patch to fix the proven blocker only.

Do not implement in this task.

## Outcome C — Genuine negative-EV proposal drought

If all/near-all recent structurally valid candidates are truly negative EV and adaptive policy is already wired correctly, then **do not propose an admission bypass for negative EV**.

Instead specify an offline PAPER strategy-generation experiment:

```text
Generate/evaluate alternative signal proposals or alternate directions in paper only,
without polluting current canonical learner until positive post-cost edge is demonstrated.
```

This is strategy redesign, not routing repair.

## Outcome D — D_NEG consumes capacity

Only if overlap is proven, specify:

```text
P1.1AP-O1: Reserve canonical learning capacity separately from D_NEG diagnostic controls
```

Do not implement without evidence.

---

# Final report required

Return:

```text
VERDICT: INTEGRATION_BUG | POSITIVE_CANDIDATE_BLOCK | TRUE_NEGATIVE_EV_DROUGHT | DNEG_CAPACITY_BLOCK | INCONCLUSIVE

N2C ACCEPTANCE STATUS:
D_NEG SAFETY STATUS:
CURRENT USEFUL LEARNING RATE:
CURRENT STARVATION CAUSE:
ADAPTIVE STATE ORIGIN:
DO ADAPTIVE METRICS AFFECT NEXT PAPER DECISIONS?:
DO OLD PF=0.495 / BAD METRICS STILL GOVERN RDE?:
DID D_NEG BLOCK RECOVERY CAPACITY?:
ONE NEXT ACTION:
FILES/LINE TARGETS FOR NEXT PATCH OR EXPERIMENT:
DO NOT PATCH UNTIL OPERATOR APPROVES.
```
