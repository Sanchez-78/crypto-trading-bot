# CryptoMaster log analysis — regression snapshot

## Executive summary

This log shows a **real regression in the live decision pipeline**, not just weak market conditions.

The bot is **alive**, it is still producing forced decisions, positions open/close, and the pre-live audit passes.  
But the **live funnel is effectively jammed**, the **learning state is internally inconsistent**, and the **exit engine is not monetizing edge**.

---

## 1) Main failure: live thresholds are hardened again

### Evidence
```text
EV prah              0.150  score prah 0.180  t15=5/6  t60=30  aktivni
Filtrace             0.0%  projde filtrem
Signaly (THIS CYCLE) 0 kandidati / 1 kandidát
```

### Why this matters
These thresholds are far stricter than the relaxed values seen in the healthier logs before.  
With `EV=0.050` on incoming candidates, the RDE line still shows:

```text
RDE[v10.10b]: ev=0.050 thr=0.150
```

So the bot is again running a **harder threshold regime** where the candidate EV is below the threshold almost all the time.

### Conclusion
The system is back in a **funnel-compression / starvation state**:
- many cycles
- almost no true candidates
- forced explore still fires
- normal live flow remains nearly dead

---

## 2) Learning pipeline is still not proven end-to-end

### Evidence
```text
=== LEARNING MONITOR ===
(waiting for 10 closed trades per pair)
[!] LEARNING: NO LEARNING SIGNAL DETECTED
Health: 0.000 [BAD]
```

But at the same time:

```text
Obchody    4967
Kalibrace  KALIBROVAN ✓ (4967 obchodu celkem)
Trend uceni STABILNÍ
```

And in the cycle snapshot:

```json
"learning": {
  "health": 0.0,
  "pairs": {},
  "features": {},
  "completed_trades": 4967
}
```

### Why this matters
This is a strong contradiction:

- UI says the model is calibrated and stable
- live monitor says no learning signal detected
- structured snapshot says `pairs={}` and `features={}`

### Conclusion
The learning system is **not coherently wired to one canonical state source**.  
Most likely one of these is happening:

1. dashboard/summary is rendered from aggregate metrics only,
2. live learning state is empty/not hydrated,
3. pair-level learning updates are not reaching the state used by the monitor,
4. state is reset or overwritten between cycles,
5. the “waiting for 10 closed trades per pair” gate is reading a different structure than the UI.

This is still the most important unresolved correctness issue.

---

## 3) Pre-live audit passes, but it does not represent live reality

### Evidence
```text
PRE-LIVE AUDIT ... [CI] PASS
Trades audited      : 100
Passed to execution : 94
Blocked             : 6
```

But live dashboard shows:

```text
Filtrace 0.0% projde filtrem
```

### Why this matters
A passing replay audit is supposed to be a safety check, but here it is **not predictive of live behavior**.

### Conclusion
The audit and live path are **not testing the same effective funnel**.  
Possible causes:

- replay inputs are too clean / synthetic,
- forced explore or replay scaffolding bypasses real live blockers,
- live OFI/frequency gates are stronger than replay,
- live thresholds differ from replay thresholds,
- audit does not sample the same candidate distribution.

A “CI PASS” here is operationally misleading.

---

## 4) Exit engine still converts most trades into scratch / micro outcomes

### Evidence
```text
[V10.13g EXIT] TP=0 SL=0 micro=0 be=0 partial=(26,0,0) trail=0 scratch=87
Harvest rate: 23.0% (26/113)
winners: SCRATCH_EXIT=18 PARTIAL_TP_25=6
near_miss: partial25_near_miss=44017 micro_near_miss=21049
```

And UI summary also says:

```text
Uzavreni  TP 0%  SL 0%  trail 0%  timeout 0%
```

### Why this matters
This means the bot is not letting trades resolve into meaningful distributions:

- no full TP
- no SL
- no trail
- almost everything becomes scratch or tiny partials

That destroys signal quality for learning and keeps expectancy near zero.

### Conclusion
The exit engine is still **over-defensive and under-harvesting**.  
Even when entry decisions are taken, the realized outcome distribution is too flat to teach the model useful edge.

---

## 5) The system is trading, but the edge is not being monetized

### Evidence
```text
Winrate      52.1%
ProfitFactor 1.05x
Zisk         -0.00012476
Expectancy   +0.00000000
```

### Interpretation
This is the classic pattern of:
- decent hit rate,
- no payoff asymmetry,
- too many scratches / micro wins / weak exits,
- cost drag overwhelms weak edge.

### Conclusion
The issue is no longer “bot is dead”.  
The issue is now:

**bot is active, but structurally incapable of converting its weak predictive edge into positive realized PnL.**

---

## 6) OFI and frequency caps are major live blockers

### Evidence
Cycle snapshot:
```json
"block_reasons": {
  "OFI_TOXIC_HARD": 149,
  "OFI_TOXIC_SOFT": 3,
  "FREQ_CAP": 450
}
```

And many replay lines show:
```text
decision=OFI_TOXIC_HARD ...
```

### Conclusion
The current dominant blockers are:
1. `FREQ_CAP`
2. `OFI_TOXIC_HARD`
3. hardened EV threshold

So the live pipeline is not just starved by EV threshold.  
It is being squeezed by **multiple independent gates at once**.

---

## 7) Structured snapshot and human dashboard disagree

### Evidence
Human dashboard shows:
- calibrated
- stable
- regime WR
- coin-by-coin stats
- EV performance

Structured snapshot shows:
```json
"pairs": {},
"features": {},
"best_edge": "Unknown"
```

### Conclusion
There are at least **two incompatible views of system state**:
- one used by the pretty dashboard,
- one used by the machine-readable snapshot / learning monitor.

This is dangerous because it makes debugging misleading.

---

## Final diagnosis

### What is confirmed working
- bot process is alive
- price stream is alive
- forced signals can still open trades
- positions are managed
- audit tool runs
- DB / metrics are not totally dead

### What is confirmed broken
1. **live funnel is re-hardened** (`thr=0.150`, `score=0.180`)  
2. **learning state is not coherent** (`pairs={}`, `features={}`, yet “calibrated”)  
3. **pre-live audit is not representative of live**  
4. **exit engine still collapses outcomes into scratch/partial instead of TP/SL/trail**
5. **edge is not monetized** (PF ~1.05, PnL negative, expectancy ~0)
6. **OFI + FREQ_CAP are major live blockers**

---

## Priority order for fixes

### Priority 1 — prove canonical learning path
Add hard counters and logs for exactly this chain:

```text
trade close
→ classify result
→ lm_update called
→ pair state mutated
→ persisted
→ hydrated next cycle
→ rendered by learning monitor
```

Required proof:
- one exact trade ID
- before/after pair stats
- persistence write log
- next-cycle read log
- same values in dashboard and snapshot

---

### Priority 2 — expose full candidate funnel
For every cycle print:

```text
generated
→ strategy_valid
→ timing_pass
→ spread_pass
→ ofi_pass
→ freq_cap_pass
→ score_pass
→ ev_pass
→ final_take
```

Without this, “0.0% filtered” is not actionable.

---

### Priority 3 — stop live threshold starvation
Current live thresholds are too hard for this regime.

At minimum investigate why the system reverted to:
- `EV thr = 0.150`
- `score thr = 0.180`
- `t15=5/6`
- `t60=30`

The important question is not tuning yet.  
The important question is:

**why is live using these values again?**

Possible root causes:
- old config loaded
- replay values leaking into live
- maturity/bootstrap logic flipped
- reset/hydration bug
- dynamic threshold code path not executing

---

### Priority 4 — audit exit realism
The exit distribution is unhealthy.

Instrument exact counts for:
- partial fired
- scratch fired
- TP reached but skipped
- SL reached but skipped
- trail armed vs trail executed
- time-in-trade distribution
- MAE/MFE before close

The huge near-miss counts strongly suggest exits are too conservative or misaligned with actual price path.

---

### Priority 5 — align audit with live
The pre-live audit should fail or warn when live funnel is effectively dead.

Add a consistency check:

```text
if live_pass_rate << replay_pass_rate:
    AUDIT = WARN/FAIL
```

Otherwise CI PASS gives false confidence.

---

## Concrete implementation request for Claude Code

Apply correctness-first instrumentation only.  
Do not retune strategy parameters until the following are proven:

1. single canonical runtime threshold source,
2. single canonical learning state source,
3. explicit live funnel counters,
4. exact close→learn→persist→hydrate proof,
5. exact exit reason distribution with TP/SL/partial/scratch truth.

Reject cosmetic changes.  
Reject dashboard-only fixes.  
Reject any claim that learning works unless it is proven on one real trade end-to-end.

---

## Short verdict

This is **not a dead bot** anymore.  
This is now a **misleadingly alive bot**:

- it trades,
- it logs,
- it passes replay audit,
- but live selection is starved,
- learning state is inconsistent,
- and realized edge is being flattened by the exit layer.
