# Real-Trading Readiness — Status & Plan (docs only, no guard code touched)

**Scope note:** this document is passive preparation only, per explicit user
confirmation (option 1: "jen příprava/checklist/plán"). Nothing in this file
or its production of it touched `live_trading_allowed()`, `TRADING_MODE`,
`ENABLE_REAL_ORDERS`, or `LIVE_TRADING_CONFIRMED`. Ground rule stays in force:
**REAL trading is an absolute NO-GO until a separate, explicit authorization
step — this document does not constitute that authorization.**

## 1. The gate already exists in code — use it, don't duplicate it

`PaperAdaptiveLearning.check_real_readiness()` in
`src/services/paper_adaptive_learning.py:965-1063` is a fully-built,
unit-tested (`tests/test_p11ap_o1a_completion.py`) readiness gate. It is
**not currently exposed** anywhere (no dashboard card, no API endpoint, no
CLI) — only tests call it. Rather than invent a parallel ad-hoc checklist,
this plan is built around making that existing gate visible and using it as
the single source of truth.

### What it checks (current thresholds, as of this commit)
| Gate | Condition | Purpose |
|---|---|---|
| 1. Sample size | `qualification_n >= 100` post-integration eligible closes | enough post-fix data, not stale pre-fix trades |
| 2. Operator unlock | `operator_unlock == True` | **hard manual flag, no automatic path exists to set it** — see §3 |
| 3. Qualification quality | `qualification_pf >= 1.20`, `expectancy > 0`, `net_pnl > 0` | profitable with margin, not just break-even |
| 4. Recent behavior | `rolling20_pf > 1.00`, `rolling20_expectancy > 0` (last 20 post-epoch closes) | not currently degrading |
| 5. Diversification | `>= 3 symbols`, `max_segment_profit_share <= 0.60` | edge isn't a single lucky symbol/segment |

`eligible = all gates pass AND operator_unlock == True`. The code comment is
explicit: **"No automatic transition."**

### Current live status (queried read-only, 2026-08-05, via `check_real_readiness()`)
```json
{
  "eligible": false,
  "paper_closed": 100,
  "qualification_n": 0,
  "rolling100_pf": 0.697,
  "rolling100_expectancy": -0.0224,
  "rolling20_pf": 1.0,
  "operator_unlock": false,
  "symbols": [],
  "reason": "insufficient_post_integration_samples qualification_n=0<100 operator_unlock_required=True symbols=0<3"
}
```

**Honest read of this, not softened:**
- **`eligible: false`, not close.** Three of five gates fail simultaneously.
- **Most recent 100 closes are net-negative** (rolling100 PF 0.70, expectancy
  -0.0224/trade) — the bot is currently *losing* on its most recent window,
  not just "not yet proven." This is the wrong direction to be moving before
  talking about real capital.
- **`qualification_n` shows a live discrepancy worth a dedicated forensic
  pass, not fixed here:** the raw persisted state file
  (`server_local_backups/paper_adaptive_learning_state.json`) has
  `qualification_window` with 100 entries, but constructing
  `PaperAdaptiveLearning()` fresh and calling `check_real_readiness()`
  reports `qualification_n: 0`. Likely cause (not confirmed): the load-time
  reconciliation logic (`paper_adaptive_learning.py:175-208`, "Filter D_NEG
  entries from rolling windows and normalize format") is dropping all 100
  persisted qualification entries, or the qualification epoch was reset by a
  recent commit ("post-integration eligible closes only" is epoch-scoped by
  design) and the bot genuinely needs 100 *new* closes from here. Either
  explanation is plausible from what I read; distinguishing them needs a
  proper forensic pass (`runtime-log-forensics` skill) — flagged, not
  guessed at.
- **`operator_unlock` has no setter anywhere in the codebase.** It's a
  deliberate, code-level dead end — by design, nothing automated can ever
  flip it. That is almost certainly intentional and should stay that way.

## 2. What "prepare for real trading" can safely mean from here (this session, doc/visibility only)

1. **Expose `check_real_readiness()` read-only** on the dashboard/API
   (`dashboard_read_model.py` already has a similar pattern for
   `cost_floor_bps`) so readiness status is visible without anyone needing
   to SSH in and run a Python snippet, as I just did. Zero risk — read-only,
   additive, no gate logic touched. *Not done yet — proposing it as the
   next concrete, reviewable patch if wanted.*
2. **Resolve the `qualification_n` discrepancy** via a proper forensic pass
   before trusting the gate's number at all — an evidence-based-patch-
   orchestrator cycle, same rigor as the TP/SL fix.
3. **A separate, isolated live instance** per the `no-real-trading-gate`
   skill's "REAL-LIVE authorized" tier: `/opt/cryptomaster-live/`, its own
   `.env` with `TRADING_MODE=real_live`, deployed and restarted independently
   from the paper instance — so a real-trading experiment can never share
   process/state with the paper bot. Not started; would need its own
   dedicated, separately-authorized effort.
4. **A funding/capital/kill-switch plan** (max daily loss, max position
   count, manual kill switch reachable without SSH, alerting) — none of
   this exists yet for a real-money path and would need to before gate §1
   even becomes relevant.

## 3. Bottom line

The honest, unhedged status: **the bot is currently further from real-
trading-ready than "just needs more time" — its most recent 100-trade window
is net-losing.** The right next action is not accelerating toward real
trading; it's the same evidence-based loop already used for the TP/SL fix,
pointed at *why* rolling100 is currently PF 0.70, and at resolving the
qualification_n discrepancy so the readiness signal itself is trustworthy.
`operator_unlock` remains the deliberate, code-enforced manual stop it was
designed to be.
