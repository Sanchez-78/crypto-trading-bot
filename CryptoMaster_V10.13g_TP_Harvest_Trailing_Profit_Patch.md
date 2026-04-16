# Claude Code Prompt — CryptoMaster V10.13g TP Harvest / Trailing-Profit Patch

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections.
Patch only the real active runtime integration points responsible for profit harvesting after valid entries.

## GOAL

The system is now operational and improving:

- warmup fallback works
- live candidates are generated
- trades are opening
- exit reporting is more granular
- timeout dominance has decreased
- Profit Factor improved to around `1.13x`
- expectancy turned slightly positive

However, one major weakness remains:

- `TP 0%`
- `trail 0%`

This means the bot is still not harvesting profits well enough.
It is improving via better timeout handling, but not yet through real profit-taking behavior.

---

## CONFIRMED LIVE EVIDENCE

Recent live logs show:

- `TP 0%`
- `SL 7%`
- `timeout 43%`
- exit summary like:
  - `t_profit=2`
  - `t_flat=3`
  - `t_loss=1`
- Profit Factor improved to `1.13x`
- Expectancy is slightly positive
- live entries continue to occur
- thresholds look realistic

This means:
- the system now has enough edge to improve further
- but profit capture is still too weak
- profitable trades are not graduating into true TP/trailing-profit outcomes

---

## ROOT CAUSE HYPOTHESIS

One or more of these are true:

1. hard TP target is too far relative to real move distribution
2. trailing logic activates too late or too weakly
3. profitable trades are not locking gains early enough
4. smart exit engine still allows too many small winners to decay
5. timeout profit exits exist, but they are not being promoted into proper harvested-profit classes
6. scratch / break-even / trail transitions are underused

---

## REQUIRED OUTCOME

After this patch:

1. Some profitable trades should close via true harvested-profit paths.
2. `TP` and/or `TRAIL_PROFIT` should no longer remain at zero over time.
3. Fewer profitable trades should decay into generic timeout exits.
4. Exit mix should better reward valid entries that move in the right direction.
5. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/smart_exit_engine.py`
- `src/services/trailing_stop.py`
- `src/services/trade_executor.py`
- `src/services/execution_engine.py`
- `src/services/execution_quality.py`
- `src/services/reward_system.py`
- any file where TP/trailing/breakeven/scratch logic is decided
- any dashboard/status file that reports exit composition

Patch only the files actually responsible for profit-taking and exit classification.

---

## TASK 1 — MAP THE REAL PROFIT-HARVEST PATH

Identify the active live path for profitable exits:

from open position →
profit detection →
break-even / trailing / micro-take / TP logic →
close reason classification →
reporting/dashboard

Return this mapping clearly in your explanation.

Important:
We need the actual production path, not a conceptual one.

---

## TASK 2 — FIND WHY `TP` AND `TRAIL` STAY AT ZERO

Determine:

- what exact TP target is used
- whether TP is static or volatility-scaled
- when trailing is armed
- how trailing stop distance is computed
- whether break-even promotion happens
- whether profitable trades are timing out before TP/trail can fire

### Required change
Do not remove hard TP.
Instead improve the path between “small profit exists” and “trade finally times out”.

Preferred options:
- earlier trail arming once trade reaches partial progress toward TP
- tighter break-even promotion once trade is safely green
- micro-take-profit / partial harvest for stalled green trades
- volatility-aware trailing that locks small wins sooner

Use the real architecture and choose the smallest effective change.

---

## TASK 3 — PROMOTE PROFITABLE TIMEOUTS INTO SMARTER EXITS

Current exit summary already distinguishes:
- `t_profit`
- `t_flat`
- `t_loss`

That is useful, but profitable timeouts should not remain the main way small winners are realized.

### Required behavior
If a trade is:
- in profit,
- stalled,
- and unlikely to reach full TP soon,

then prefer a smarter profit-harvest path instead of generic timeout.

Possible exit labels:
- `TRAIL_PROFIT`
- `MICRO_TP`
- `SCRATCH_EXIT`
- `BREAKEVEN_STOP`
- `TIMEOUT_PROFIT` only as fallback

This is important so the bot actually realizes edge rather than merely surviving to timeout.

---

## TASK 4 — IMPROVE TRAILING / BREAKEVEN TRANSITIONS

Patch the live trailing/breakeven logic so that:

- once a trade reaches a meaningful fraction of TP progress, the stop can ratchet up
- once a trade is sufficiently green, protect against full round-trip decay
- strong momentum trades still get room to continue
- weak but green trades get harvested more intelligently

Do NOT make trailing overly tight for all cases.
The patch must remain bounded and regime/volatility aware if the architecture supports it.

---

## TASK 5 — ADD BETTER EXIT REASON CLASSES

Current categories improved in V10.13f, but profitable exits still need clearer classification.

After patching, prefer a scheme such as:

- `TP_HARD`
- `TRAIL_PROFIT`
- `MICRO_TP`
- `BREAKEVEN_STOP`
- `SCRATCH_EXIT`
- `TIMEOUT_FLAT`
- `TIMEOUT_LOSS`
- `TIMEOUT_PROFIT` (fallback)

Use a naming scheme compatible with the existing code.

Goal:
future logs should show whether harvested-profit exits are actually increasing.

---

## TASK 6 — UPDATE EXIT DASHBOARD / SUMMARY

Patch the live status/dashboard so it reflects real harvested-profit outcomes.

At minimum show:
- TP count
- trail profit count
- micro/scratch count if added
- breakeven count if added
- timeout_profit / timeout_flat / timeout_loss
- average hold duration if available

Do not keep the dashboard blind to the difference between:
- real harvested winners
- profitable timeouts
- flat timeouts

---

## TASK 7 — ADD COMPACT PROFIT-HARVEST SUMMARY

Add one concise status line such as:

```python
print(
    f"[V10.13g EXIT] tp={tp_n} trail={trail_profit_n} micro={micro_tp_n} "
    f"be={breakeven_n} scratch={scratch_n} "
    f"t_profit={timeout_profit_n} t_flat={timeout_flat_n} t_loss={timeout_loss_n}"
)
```

Use the actual active reporting path and real variables.

Goal:
Make it obvious whether:
- harvested-profit exits are increasing
- TP remains stuck at zero
- timeout_profit is being converted into smarter exits

---

## TASK 8 — KEEP THESE SAFETY PROPERTIES

Do NOT remove:
- hard stop loss
- emergency exits
- exposure/risk limits
- max position controls
- risk manager protections
- watchdog/self-heal
- audit/execution checks

This patch is about:
- improving realized profit capture
- promoting profitable exits out of generic timeout
- improving trailing/breakeven behavior
- increasing quality of exit composition

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. `TP` and/or `TRAIL_PROFIT` no longer remain stuck at zero over time.
2. More profitable trades are harvested before generic timeout.
3. Exit mix becomes more profit-aware and less passive.
4. Dashboard/status reflects the improved exit composition.
5. Safety protections remain intact.
6. Live quality metrics should plausibly improve further beyond the V10.13f baseline.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact live profit-harvest path mapping
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
