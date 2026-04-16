# Claude Code Prompt — CryptoMaster V10.13f Exit Quality / Timeout Dominance Fix

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections.
Patch only the real active runtime integration points responsible for exits and post-entry trade management.

## GOAL

The live trading pipeline is now operational:
- warmup fallback works
- candidates are generated
- live decisions are being taken
- new trades are opening

But trade quality is still weak.

### Confirmed live evidence
Recent live logs show:

- live trades are happening again
- thresholds now look realistic (for example EV threshold around `0.096–0.098`)
- recent trades are being opened in live mode
- but performance quality is still poor:
  - Profit Factor around `0.92x`
  - expectancy slightly negative
  - exits dominated by:
    - `TP 0%`
    - `SL 17%`
    - `timeout 83%`

This means the next bottleneck is no longer signal generation.
It is now exit behavior and trade lifecycle quality.

---

## ROOT CAUSE HYPOTHESIS

One or more of these are true:

1. timeout hold window is too short for the current TP distance
2. TP distance is too ambitious relative to real move distribution
3. trailing / break-even logic is too weak or triggers too late
4. smart exit engine is not harvesting small wins early enough
5. trades that should scratch / partial-win are being left to timeout
6. entry quality is acceptable, but exit policy destroys edge

---

## REQUIRED OUTCOME

After this patch:

1. Timeout dominance should materially decrease.
2. More trades should close via:
   - TP
   - smart profit take
   - controlled scratch / micro-win
3. Exit policy should better match actual holding-time behavior.
4. Trade lifecycle logs should clearly show why exits happen.
5. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/smart_exit_engine.py`
- `src/services/trade_executor.py`
- `src/services/execution_engine.py`
- `src/services/trailing_stop.py`
- `src/services/execution_quality.py`
- `src/services/reward_system.py`
- any file where timeout exits are decided
- any dashboard/status file that reports `TP / SL / timeout`

Patch only the files actually responsible for live exit decisions and exit reporting.

---

## TASK 1 — MAP THE REAL LIVE EXIT PATH

Identify the active live exit path:

from open position →
position monitoring →
smart exit / timeout / SL / TP / trailing →
close decision →
trade result classification

Return this mapping clearly in your explanation.

Important:
We need the actual production path, not a theoretical one.

---

## TASK 2 — DIAGNOSE TIMEOUT DOMINANCE

Find the exact logic that causes timeout exits.

Determine:
- what is the timeout duration
- whether it is static or adaptive
- whether it varies by regime / symbol / volatility
- how often timeout fires relative to unrealized PnL state
- whether timeout is hitting trades that are near flat / near small win / near TP

### Required change
Timeout should stop being a blunt dominant exit.

Preferred behavior:
- losing stagnant trades may still timeout
- slightly profitable trades should be harvested intelligently before timeout
- near-flat trades should have scratch logic
- strong trades should have enough time to reach TP or trail

Examples of acceptable improvements:
- extend timeout for high-quality trades
- shorten timeout for clearly weak stagnant trades
- add micro-take-profit / scratch exit
- add time-decay exit rules based on unrealized PnL and regime

Do NOT blindly apply all ideas. Use the real architecture.

---

## TASK 3 — IMPROVE EXIT QUALITY WITHOUT REMOVING PROTECTION

Keep:
- hard SL
- hard TP
- emergency exits
- exposure/risk limits

But improve the middle area between TP and timeout.

### Required behavior
Add bounded logic for cases like:

- trade slightly green but stalling → take micro-profit instead of timeout
- trade near entry after long time → scratch / reduce rather than full dead timeout
- trade with improving momentum → allow extended hold or smarter trailing
- trade strongly positive but not yet TP → tighter trailing or staged take-profit

Possible structures:
- break-even stop promotion
- volatility-aware trailing
- time-in-profit harvesting
- scratch exit after long stagnation
- regime-aware timeout duration

Do not overcomplicate. Keep the patch incremental.

---

## TASK 4 — SEPARATE EXIT REASONS MORE PRECISELY

Current reporting is too coarse:
- `TP`
- `SL`
- `timeout`

After patching, distinguish more useful exit outcomes where appropriate, for example:

- `TP_HARD`
- `TRAIL_PROFIT`
- `SCRATCH_EXIT`
- `TIMEOUT_FLAT`
- `TIMEOUT_LOSS`
- `TIMEOUT_PROFIT`
- `BREAKEVEN_STOP`

Use whatever reason scheme best fits the current architecture.

This is required so future logs show whether timeout dominance actually improved.

---

## TASK 5 — FIX EXIT REPORTING / DASHBOARD

Patch live status/dashboard so it reflects real exit composition.

At minimum show:
- TP count
- SL count
- timeout count
- scratch/breakeven count if added
- trailing profit count if added
- recent average hold duration if available

Do not keep reporting only coarse timeout dominance if the implementation now has better exit classes.

---

## TASK 6 — ADD COMPACT EXIT QUALITY SUMMARY

At end of each cycle or status block, add one concise exit-quality summary line such as:

```python
print(
    f"[V10.13f EXIT] tp={tp_n} sl={sl_n} trail={trail_n} "
    f"scratch={scratch_n} timeout_flat={timeout_flat_n} "
    f"timeout_loss={timeout_loss_n} timeout_profit={timeout_profit_n} "
    f"avg_hold={avg_hold_sec:.0f}s"
)
```

Use the real variables and active reporting path.

Goal:
Make it obvious whether:
- timeout dominance is shrinking
- more exits are being harvested intelligently
- exit mix is improving or not

---

## TASK 7 — KEEP THESE SAFETY PROPERTIES

Do NOT remove:
- hard stop loss
- max position / exposure rules
- emergency exits
- risk manager protections
- cooldown protections
- audit / execution checks

This patch is about:
- reducing unproductive timeout dominance
- improving extraction of small edge from valid entries
- classifying exits more precisely
- improving live exit observability

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. Timeout exits become less dominant.
2. More exits are classified into useful intermediate categories instead of generic timeout.
3. Exit logic better matches trade state (profit / flat / weak loss / momentum).
4. Dashboard/status reflects the real improved exit composition.
5. Safety protections remain intact.
6. Live edge quality should plausibly improve instead of remaining stuck at timeout-heavy weak expectancy.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact live exit path mapping
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
