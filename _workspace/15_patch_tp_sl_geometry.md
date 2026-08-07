# Patch 15 — TP/SL cost-floor geometry

**Status:** PARTIAL FIX + BLOCKING FINDING.
**I could NOT determine a profitable TP/SL pair from the available data.** No band
geometry has positive expectancy in the current market regime. Details in
"Finding that changes the conclusion" below. Read that section before deploying
anything based on this.

---

## 1. Cost model — independently verified (forensics was right, for the wrong default)

Recomputed from code, not from the forensic report.

- `paper_trade_executor.py:1004-1008` — `net = gross - fee_pct*100 - slippage_pct*100`.
  Fee is applied **once**, as a round-trip charge (comment `# Round-trip`).
  Confirmed by the existing golden test `tests/test_calculate_pnl_golden.py:48-54`.
- Shipped defaults (`paper_trade_executor.py:146-147`): `_FEE_PCT=0.0015`,
  `_SLIPPAGE_PCT=0.0003` → **18 bps** round-trip.
- **Live production** (`/etc/systemd/system/cryptomaster.service.d/99-cryptomaster-managed-runtime.conf:45-46`):
  `PAPER_FEE_PCT=0.0004`, `PAPER_SLIPPAGE_PCT=0.0` → **4 bps** round-trip.

So the forensic report's 4 bps is correct **for the live config**, but that config
understates real cost: Binance futures taker is 0.04% *per side* = 8 bps round-trip,
plus non-zero slippage. **Paper P&L is optimistic by roughly 2x on cost.** Flagged,
not patched (out of scope).

Break-even math confirmed: TP=12/SL=10 @ 4bps → win +8, loss −14 →
`14/(8+14) = 63.6%` required TP-share.

## 2. Data used — live, current, not the 07-31 snapshot

`/opt/cryptomaster/local_learning_storage/cache.sqlite`, `closed_trades`, n=1948.

**MFE/MAE IS persisted now** — the Cycle 21 "MFE is NULL" note is stale. Columns
`mfe_gross_bps` / `mae_gross_bps` / `time_to_mfe_ms` / `time_to_mae_ms` are populated
for 1659/1948 rows and 100% of rows since 2026-08-01.

Window 2026-08-01 → 08-07, n=1314:

| exit_reason | n | avg net bps | avg MFE bps | avg MAE bps |
|---|---|---|---|---|
| TIMEOUT | 627 | −3.50 | 8.7 | −6.8 |
| TP | 347 | +8.74 | 12.7 | −3.2 |
| SL | 340 | −14.59 | 3.0 | −10.6 |

Realised TP-share = 347/687 = **50.5%** vs **63.6%** required. Overall expectancy
**−3.14 bps/trade**. Confirms the diagnosis.

**Censoring caveat:** MFE is truncated at ~12 and MAE at ~−10 for band-exits, so the
full population cannot answer "what would TP=35 have done". The uncensored subset is
the 627 TIMEOUT trades (ran the full 900s hold without a band binding).

## 3. Finding that changes the conclusion

### 3a. The regime shifted; the old "stable" numbers are not restorable

Natural experiment in the data (bands switched 2026-07-31 ~09:00 UTC):

| day | bands (implied) | n | TP | SL | TIMEOUT | E[net bps] |
|---|---|---|---|---|---|---|
| 07-30 | TP≈20 / SL≈28 | 198 | 59 | 3 | 136 | **+4.29** |
| 08-01..08-05 | TP=12 / SL=10 | 953 | 347 | 340 | 266 | **−0.5 to −8.1** |

But 07-30 was a **different volatility regime**, not just different bands.
P(MFE ≥ 20bps) among uncensored TIMEOUT trades:

| threshold | 07-30 window | Aug window |
|---|---|---|
| MFE ≥ 10 | 64.4% | 34.1% |
| MFE ≥ 20 | 37.8% | 7.3% |
| MFE ≥ 30 | 32.2% | **0.6%** |

**Restoring TP=35/SL=40 today would make TP essentially unreachable** (0.6% of trades
reach 30 bps) — everything would ride to TIMEOUT. This is exactly the "widen both and
hope" mistake, in reverse. The historical numbers in CLAUDE.md/memory are not
transferable to the current regime.

### 3b. There is no profitable geometry, because there is no gross edge

Grid search over TP ∈ [10,40] × SL ∈ [8,40], expectancy computed on the uncensored
TIMEOUT subset (n=628):

| cost | best pair by margin | achievable share | break-even needed | E[bps] |
|---|---|---|---|---|
| 4 bps (live) | TP=14 / SL=13 | 69.9% | 63.0% | **−1.99** |
| 4 bps | *current* 12/10 | 68.5% | 63.6% | −1.94 |
| 8 bps (realistic) | TP=14 / SL=26 | 78.8% | 85.0% | **−3.24** |
| 8 bps | *current* 12/10 | 68.5% | 81.8% | −3.30 |

**Every pair is negative at 4 bps. Every pair has negative margin at 8 bps.**

Root cause: mean net P&L of the uncensored TIMEOUT subset is −3.50 bps, i.e. the
**implied gross edge is +0.50 bps/trade** against a 4-8 bps cost. Cross-checked
against the full 1314-trade population: −3.14 net → +0.86 gross. The strategy is
scalping moves barely larger than its own costs. MFE decays sharply (34% → 0.6% from
10→30 bps) while MAE decays slowly (10.7% → 5.3%) — favorable excursions mean-revert,
adverse ones run.

**TP/SL geometry is a real defect but not the reason the bot is unprofitable.** Fixing
the bands cannot produce a positive expectancy; that requires either a genuine
directional edge, lower cost (maker fills), or holding for larger moves.

### 3c. Two secondary defects found (flagged, NOT patched — separate scope)

1. **Bands do not always fire.** 146/627 TIMEOUT trades had MFE ≥ 12 bps and 67 had
   MAE ≤ −10 bps, yet exited on timeout instead of TP/SL — ~23% of trades breach a
   band without acting on it. On 08-06 and 08-07 there are **zero** TP and SL exits
   across 361 trades (100% TIMEOUT). Needs its own forensic pass.
2. **`hetzner-set-paper-tp.yml` is inert.** It writes `PAPER_TP_ZONE_BPS` to
   `/opt/cryptomaster/.env` (line 82), but the systemd drop-in sets the same key as a
   systemd `Environment=`, which python-dotenv does not override. Live `.env` says
   TP=35/SL=25 while the effective values are 12/10. The sanctioned tracked path for
   changing TP is silently a no-op.
3. Local `.env` has **duplicate** `PAPER_TP_ZONE_BPS` keys (line 2 = 50, line 20 = 35).

## 4. What this patch does

Because I cannot justify specific "correct" numbers, this patch deliberately does
**not** push new band values at production. It fixes what is provable:

1. **Shipped default SL 40 → 25.** At the shipped 18 bps cost, TP=50/SL=40 required a
   `58/(32+58)` = **64.4%** TP-share — a genuine violation of the 60% ceiling, not a
   borderline case. 50/25 requires 57.3% at 18 bps and 38.7% at 4 bps. TP default
   unchanged at 50.
   *(Correction: the first revision of this document and the original commit message
   said 60.0% here. That was arithmetic on SL=30, not SL=40. Caught by the direct
   validator probe during review follow-up. The change is more justified than
   originally stated, not less.)*
2. **`_SHIPPED_TP_ZONE_BPS` / `_SHIPPED_SL_ZONE_BPS`** introduced so the shipped
   geometry is assertable independently of ambient env (a stray `PAPER_TP_ZONE_BPS`
   in a dev/CI shell previously made the module constants untestable — this bit me
   while writing the test).
3. **`validate_tp_sl_cost_floor(tp, sl, cost)`** — pure function encoding the
   both-legs invariant: `tp ≥ 2·cost`, `sl ≥ cost`, break-even share ≤ 60%.
4. **Startup `log.critical("[TP_SL_COST_FLOOR_VIOLATION] …")`** when the *effective*
   configured geometry violates it. Logs, does not raise — it must not crash a running
   bot. **This is what makes the live 12/10 config visible without an SSH audit.**
5. **`tests/test_tp_sl_cost_floor_invariant.py`** — the gap test-regression-agent
   identified. Asserts shipped defaults pass under both cost models, and that 12/10 is
   rejected at 4 bps and 18 bps.

### Why no tracked systemd conf was added

The lead asked me to find where these values should live rather than telling someone
to SSH in. The honest answer: **the mechanism should be a tracked drop-in installed by
`hetzner-deploy-apply.yml`, but adding one now would be wrong**, because it would
overwrite live config with numbers I have just shown I cannot justify. Shipping a
deploy-time config overwrite carrying unvalidated values is the same failure mode that
caused this incident. That mechanism should land together with a decision on values.

## 4b. Review follow-up (patch 16 conditions)

### C3 — BLOCKING, fixed
`validate_tp_sl_cost_floor(0, 0, 0)` raised `ZeroDivisionError`: with `cost_bps=0`
both preceding guards are `0 < 0` → False, so execution reached `sl_net / (tp_net +
sl_net)` = `0/0`. Since the validator runs at module scope this was an import-time
crash risk, and it contradicted the "logs, never raises" contract. Added a
`tp_net + sl_net <= 0` guard returning `(False, "degenerate geometry: …")` before the
division. Covered by 5 new parametrized cases including `(0,0,0)`, `(-5,-5,0)` and
`(-40,40,0)` (the exact-zero-sum case). Direct probe confirms no raise.

### C4 — fixed, but the risk was theoretical
`parameter_tuner._increase_tp_sl_zones()` now calls `validate_tp_sl_cost_floor()` on
the proposed `tp*1.5 / sl*1.5` and returns `False` with a
`[PARAMETER_TUNER_REJECTED]` warning instead of writing a violating geometry to
`.env`. The reviewer's reasoning is right: scaling both legs by the same factor does
not preserve the economics, because the fixed round-trip cost moves the required
break-even share as the bands scale.

**Two things the supervisor should know about this path:**
1. `_increase_tp_sl_zones()` has **zero callers** — it was disabled at
   `parameter_tuner.py:44-46` by CYCLE 23 ("TP/SL bands controlled manually via
   override.conf").
2. `parameter_tuner.py` **cannot be imported at all**, on clean HEAD as well as after
   this patch: line 17 `from src.services.learning_optimizer import get_optimizer`
   raises `ImportError` because `learning_optimizer.py` defines no `get_optimizer`.
   Verified by stashing the patch and re-importing.

So the whole module is dead code. The guard is correct defense-in-depth and costs
nothing, but it is not closing a live hole. **This contradicts project memory**
(`project_learning_revision_v2.md`: "learning feedback loop (optimizer + tuner) now
auto-adjusts parameters every 5 min") — that loop is not running. Worth its own
intake; I did not touch it.

### C5 — partially addressed
Added `get_tp_sl_cost_floor_status()` returning
`{tp_zone_bps, sl_zone_bps, round_trip_cost_bps, cost_floor_ok, violation_reason}`,
so the violation is consumable as data rather than only as a log line. The module has
no existing health/status surface to fold it into (checked), so **nothing consumes it
yet**.

**Follow-up still needed (not done here, to avoid scope creep):** a Gate-7-style
`journalctl` check in `hetzner-deploy-apply.yml` asserting
`[TP_SL_COST_FLOOR_VIOLATION]` is absent after restart, or a dashboard field reading
`get_tp_sl_cost_floor_status()`. Without one of those, the guard still depends on
someone reading logs — the same failure mode as the 23.5h stale-dashboard incident.

## 5. Diff summary

```
src/services/paper_trade_executor.py     | +117 -2
src/services/parameter_tuner.py          | +22 -1
tests/test_tp_sl_cost_floor_invariant.py | +98 (new)
```

No refactoring. No changes to entry logic, TP/SL evaluation, position persistence,
learning propagation, or any real-order path. Paper-only.

## 6. Tests

- New: `tests/test_tp_sl_cost_floor_invariant.py` — 11 tests, all pass (incl. 5 C3 degenerate-input cases).
- `tests/test_calculate_pnl_golden.py` — 13 pass (cost model unchanged).
- Regression, before vs after (identical, no new failures):
  - `test_paper_close_pipeline / test_paper_hold_hard_cap / test_hotfix_paper_state_wrapper / test_p0_3_paper_integration / test_paper_mode_p1_1ai`: **69 passed, 8 failed** both sides (8 pre-existing).
  - `test_paper_mode.py`: **213 passed, 1 failed, 4 skipped** both sides (1 pre-existing, unrelated env assertion).

## 7. Commit

`caeacf8` — local only, not pushed.

## 8. Recommendation to supervisor

1. **Do not deploy a band change on this evidence alone.** It will not restore
   profitability and may make things worse (all-TIMEOUT).
2. Treat 3c.1 (bands not firing; 100% TIMEOUT on 08-06/07) as the **next forensic
   priority** — it is a larger effect than the geometry.
3. Correct `PAPER_FEE_PCT` to a realistic 0.0008 round-trip with non-zero slippage, so
   paper P&L stops flattering itself. Expect reported metrics to get worse; that is
   the point.
4. The real lever is gross edge (+0.5 bps/trade vs 4-8 bps cost), not band placement.
