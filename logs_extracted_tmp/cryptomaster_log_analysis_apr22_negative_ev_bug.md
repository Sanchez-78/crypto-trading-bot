# CryptoMaster — log analysis update (Apr 22, 2026)

## Executive summary

This log confirms **three critical correctness issues** in the live decision pipeline:

1. **Negative-EV trades are still accepted**
   - The bot logs `decision=TAKE` even when post-coherence EV is negative, for example:
     - `decision=TAKE  ev=-0.0300`
     - `decision=TAKE  ev=-0.0399`
   - That is a **hard logic violation** for an EV-first system.

2. **Score-threshold logic is inconsistent with runtime state**
   - Runtime shows:
     - `n=5822`
     - `EV prah 0.095`
     - `score prah 0.173`
   - Yet the log still repeatedly prints:
     - `[V10.13r] SCORE_THRESHOLD_COLD_START: relaxed to 0.1728`
   - With `n=5822`, this should **not** be using a cold-start label/path unless the label is wrong or the condition is wired incorrectly.

3. **The system still shows “NO LEARNING SIGNAL DETECTED” despite rich pair statistics**
   - Learning monitor clearly has populated pair/regime state:
     - `ETHUSDT_BEAR_TREND n=23 conv=0.798`
     - `BTCUSDT_BEAR_TREND n=24 conv=0.389`
     - many other pair buckets with non-zero `n`, `wr`, `bandit`
   - But runtime still emits:
     - `[!] LEARNING: NO LEARNING SIGNAL DETECTED`
   - This means the learning-health signal and the actual learned state are **not aligned**.

---

## Highest-confidence findings from the log

## 1) Hard correctness bug: negative EV is allowed through

### Evidence

The log explicitly shows accepted decisions with negative EV after coherence adjustment:

```text
decision=TAKE  ev=-0.0300  p=0.5000  af=0.70  coh=0.500
decision=TAKE  ev=-0.0399  p=0.5333  af=0.70  coh=0.797
decision=TAKE  ev=-0.0399  p=0.4793  af=0.70  coh=0.797
```

And the corresponding lines above show the negative EV path:

```text
EV=-0.050 ... coherence[v10.12]: 0.797  ev -0.050→-0.040
...
decision=TAKE  ev=-0.0399
```

### Why this is severe

If the system is described as **EV-only**, then **final EV <= 0 must never result in TAKE**, unless there is a clearly labeled exploration mode with strict bounded size and explicit override reason.

Here, the runtime still writes:

```text
Velikost pozice 1.20x  EV-only · loss streak → scale · DD halt 40%
```

So the current behavior contradicts the strategy contract.

### Conclusion

This is not just a tuning issue.  
This is a **logic bug in final admission criteria**.

---

## 2) Cold-start threshold message is firing in mature runtime

### Evidence

At the same time the runtime shows:

```text
completed_trades: 5822
...
score prah 0.173
```

the log still prints many times:

```text
[V10.13r] SCORE_THRESHOLD_COLD_START: relaxed to 0.1728
```

### Why this is suspicious

A system with `n=5822` is not globally in cold start.  
Possible explanations:

1. The label is wrong, and the code prints the cold-start message even for a different branch.
2. The cold-start condition is scoped per candidate/pair and is being triggered incorrectly.
3. The threshold variable is reused from old code and only the message remains.
4. A fallback path is applying the relaxed threshold unconditionally.

### Practical implication

This makes the logs **misleading** and blocks correct diagnosis.

### Conclusion

This is either:
- a **logging integrity bug**, or
- a **threshold-routing bug**.

---

## 3) Learning state exists, but the system still says no learning signal

### Evidence

The cycle snapshot contains substantial learned state:

```text
"health": 0.0894
"pairs": {
  "BNBUSDT_BEAR_TREND": {"n": 14, "ev": 0.0008, "wr": 0.7143, "bandit": 0.539},
  "ETHUSDT_BEAR_TREND": {"n": 23, "ev": -0.0012, "wr": 0.3043, "conv": 0.798, "bandit": 0.417},
  "BTCUSDT_BEAR_TREND": {"n": 24, "ev": 0.0002, "wr": 0.5, "conv": 0.389, "bandit": 0.458}
}
```

Feature stats also exist:

```text
wick: 0.3817
breakout: 0.3817
vol: 0.3817
...
```

Yet the runtime still says:

```text
[!] LEARNING: NO LEARNING SIGNAL DETECTED
Health: 0.089  [BAD]
```

### Why this matters

The problem is not “no data.”  
The problem is that the code responsible for declaring learning state is disconnected from the actual learned state.

### Conclusion

This is an **observability mismatch** between:
- persisted learning state,
- runtime LM state,
- dashboard/log classification.

---

## 4) Strategy quality is still weak even when pass rate improves

### Evidence

Pre-live audit:

```text
Trades audited         : 100
Passed to execution    : 54
Blocked                : 46
...
net_edge               : 46
velocity_pen < 1.0     : 100
```

Runtime summary:

```text
Winrate       52.2%
Profit Factor 2.12x
Zisk          -0.00009530
Expectancy    +0.00000003
```

### Interpretation

This means:
- the bot is less blocked than before,
- but much of the allowed flow is still weak,
- net-edge rejection is doing much of the true filtering downstream,
- velocity penalty compresses all candidates (`100/100` in audit).

This is no longer a pure “deadlock” bot.  
Now the risk is the opposite: **more flow, still weak quality**.

---

## 5) Feature quality is broadly negative

### Evidence

Feature winrates are all poor:

```text
wick        38%
breakout    38%
vol         38%
bounce      38%
trend       38%
mom         38%
pullback    38%
is_weekend  23%
```

### Interpretation

This strongly suggests one of the following:
- feature attribution is wrong,
- weak signal families dominate too much of the flow,
- exit logic distorts attribution,
- setup tags do not correspond to real edge.

### Conclusion

The current feature layer is not producing robust positive discrimination.

---

## 6) Exit structure still looks unhealthy

### Evidence

```text
[V10.13g EXIT] TP=0 SL=0 micro=3 be=0 partial=(22,0,0) trail=0 scratch=90
Harvest rate: 21.7% (25/115)
```

And:

```text
winners: SCRATCH_EXIT=24 PARTIAL_TP_25=3
near_miss: partial25_near_miss=24121 micro_near_miss=10431
```

### Interpretation

The system is mostly resolving through:
- scratch exits
- partial micro outcomes
- near misses

and **not** through clear TP/SL/trail structure.

That usually produces:
- flat expectancy,
- fragile live edge,
- difficulty learning from outcomes.

---

## 7) Decision reporting is internally contradictory

### Evidence examples

The runtime shows:

```text
ETH  PRODEJ ... ev:-0.034  BEAR
SOL  PRODEJ ... ev:-0.034  BEAR
```

and elsewhere:

```text
BTC  PRODEJ ... p:53%  ev:0.030  BULL
ETH  PRODEJ ... p:53%  ev:0.030  BULL
SOL  PRODEJ ... p:53%  ev:0.030  BULL
```

### Interpretation

Likely causes:
- displayed regime is not the regime used in the final decision,
- sign conventions are mixed,
- UI/log line prints stale or transformed values,
- action direction and EV sign come from different stages.

### Conclusion

The observability layer is not yet trustworthy enough.

---

## Root-cause hypothesis hierarchy

## Tier 1 — most likely

### A. Final TAKE gate does not enforce `final_ev > 0`
Strongest evidence in the log.

### B. Decision logs combine values from different stages
Explains contradictory action / EV / regime combinations.

### C. “Cold start” threshold path or label is leaking into mature runtime
Explains repeated relaxed-threshold messages with `n=5822`.

## Tier 2 — also likely

### D. Learning detector uses the wrong source of truth
Hydrated LM state exists, but “NO LEARNING SIGNAL DETECTED” still prints.

### E. Exit engine is over-biased toward scratch/partial micro outcomes
Reduces discrimination between truly good and weak entries.

### F. Feature attribution is structurally noisy or wrong
All major features clustering near 38% is a red flag.

---

## Immediate fixes — in order

## Fix 1 — hard-enforce positive final EV before TAKE

Add a final gate at the last decision point:

```python
if final_ev <= 0:
    return reject("NEGATIVE_FINAL_EV", details={...})
```

If exploration is allowed, require explicit branch:

```python
if explore_mode and final_ev <= 0:
    size *= explore_cap
    tag = "EXPLORE_NEG_EV"
else:
    reject
```

### Acceptance proof
In logs, **zero** lines of:
```text
decision=TAKE  ev=-...
```

---

## Fix 2 — log canonical decision snapshot only once per candidate

Create a single final structured log line with:
- symbol
- side
- regime_used
- raw_ev
- coherence
- final_ev
- raw_score
- final_score_threshold
- acceptance_factor
- final_decision
- reject_reason / override_reason
- source_stage

### Acceptance proof
For one candidate, exactly one canonical line explains the final outcome.

---

## Fix 3 — separate bootstrap threshold from mature threshold clearly

Do not print `SCORE_THRESHOLD_COLD_START` unless the condition is truly active.

Recommended fields:
- `bootstrap_global`
- `bootstrap_pair`
- `bootstrap_reason`
- `score_threshold_used`
- `score_threshold_source`

### Acceptance proof
When `completed_trades` is high, cold-start message appears only when pair-level bootstrap is explicitly true.

---

## Fix 4 — replace “NO LEARNING SIGNAL DETECTED” with grounded state

Instead of a vague binary message, print:

```text
LEARNING_STATE:
  hydrated_pairs=...
  active_pairs=...
  pairs_with_n>=10=...
  pairs_with_conv>0=...
  last_lm_update_age_s=...
  health=...
```

### Acceptance proof
If pair state exists, the log no longer claims there is no learning signal unless all relevant counters are actually zero.

---

## Fix 5 — audit why net_edge blocks 46% after RDE passed 100%

The audit shows:
- `RDE: 0`
- `net_edge: 46`

So the real bottleneck moved downstream.

Need per-trade decomposition:
- gross_ev
- fees
- slippage
- spread cost
- execution_quality
- net_edge_before_size
- net_edge_after_size
- final block reason

### Acceptance proof
Top 3 reasons for `net_edge` blocking become explicit and quantifiable.

---

## Fix 6 — stop allowing ambiguous EV sign / direction combinations in UI logs

Any displayed action line should come from one canonical object only.

For example:

```python
final_decision = {
    "symbol": sym,
    "side": side,
    "regime": final_regime,
    "p": final_p,
    "final_ev": final_ev,
    "final_score": final_score,
    "decision": decision,
}
```

### Acceptance proof
No contradictory lines like:
- sell + positive bull context with unclear rationale
- sell with negative EV still accepted under EV-only mode

---

## Fix 7 — instrument exit outcome distribution properly

Add:
- realized pnl by exit type
- avg hold time by exit type
- median MFE / MAE by exit type
- fee-adjusted expectancy by exit type
- count of trades that touched partial threshold before scratch exit

### Acceptance proof
You can prove whether scratch exits are saving capital or destroying edge.

---

## What this log says about the current bot state

## Good news
- Warm-start integrity appears OK:
  - `_peak_equity[0] = equity_peak [OK]`
- Pre-live audit still passes CI.
- Some pair-specific learning buckets have meaningful samples.
- Profit Factor is above 1.5 in this slice.

## Bad news
- The core decision contract is broken by negative-EV TAKEs.
- Logs are not trustworthy enough to reason about the final decision path.
- Learning state exists, but the system still claims no learning signal.
- Feature performance is broadly poor.
- Exit profile is dominated by scratch/micro behavior.

## Bottom line
This is **not** just a market-edge problem.  
It is primarily a **correctness + observability problem**.

---

## Most important conclusion

The highest-priority bug is:

> **`decision=TAKE` is possible even when final EV is negative.`**

Until that is fixed, all other tuning is secondary.

---

## Minimal acceptance checklist for next patch

- [ ] No `decision=TAKE` when `final_ev <= 0`
- [ ] Cold-start threshold message only when true bootstrap branch is active
- [ ] Canonical one-line final decision log per candidate
- [ ] Learning status derived from actual hydrated/runtime LM state
- [ ] Net-edge block decomposition visible
- [ ] Exit-type PnL attribution added
- [ ] No contradictory UI/log decision summaries

---

## Suggested patch title

**V10.13t — final decision integrity + learning signal truthfulness**

Recommended scope:
1. hard final EV gate
2. canonical decision object/log
3. bootstrap-threshold source tracing
4. learning-state truth fix
5. net-edge decomposition
