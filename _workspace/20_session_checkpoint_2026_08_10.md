# Session checkpoint — 2026-08-10, cycles 1-29

**Goal (user-set):** Win Rate > 55% AND high positive P&L, paper-only, full autonomy granted.

## What changed this session (chronological)

1. **P1.1-P1.3** (Evidence-First Strategy Expansion v2): `strategy_volatility_breakout_v1.py`,
   `strategy_sideways_mean_reversion_v1.py`, `strategy_funding_observer_v1.py`. Evidence-only,
   not wired into the live loop at the time.
2. **P0 hotfix**: live systemd overlay tracked for the first time
   (`systemd/99-cryptomaster-managed-runtime.conf`), removed the cost-floor-violating
   `PAPER_TP_ZONE_BPS=12/PAPER_SL_ZONE_BPS=10` override that had been silently defeating two
   prior "fixes" for 3+ days. Deployed directly (backup+verify+rollback discipline). **Effect
   measured**: WR 12%→~15% (slow drift), PF 0.41→~0.49 — a real but small improvement, exactly as
   predicted (removes an actively-losing config; does not create edge that isn't there).
3. **§17 risk guard** (`p0_risk_guard_v1.py`): closed a standing gap where `signal_router.py` had
   `risk_allowed` hardcoded `False` since its first commit — the whole P0.8+ pipeline could never
   have admitted a signal even if wired in.
4. **Shadow evaluator** (`p0_8_plus_shadow_evaluator.py`, `candle_cache_v1.py`,
   `regime_classifier_v1.py`): the actual live-data wiring. Fetches real candles, classifies
   regime, runs all 3 candidate-generating strategies, evaluates through router+risk-guard.
   **Structurally cannot open a position** (independently audited by trading-safety-agent,
   approved, two real findings fixed before deploy: a freshness-check clock-phase bug that
   would have made ~92% of evidence meaningless, and a vacuous bypass-test fixture).
5. **`live_quote_cache_v1.py`**: closed the shadow evaluator's remaining disclosed gap (no live
   bid/ask feed) by subscribing to the existing `event_bus` `"price_tick"` publication, per
   `CLAUDE.md`'s own architecture rule. Shadow evaluator now prefers real quotes, records
   `quote_source` per evaluation.

**393 tests passing** across the whole Evidence-First family (was 0 net-new coverage for this
area at session start beyond the already-existing 209 from P0.7-P1.0).

## What's deployed vs. pending

- **Live and confirmed working**: the TP/SL systemd-overlay fix (item 2). Verified via direct
  SSH: service healthy, no `TP_SL_COST_FLOOR_VIOLATION` log, WR/PF moving in the predicted
  direction.
- **Committed, pushed, NOT yet deployed**: items 3-5 (risk guard, shadow evaluator, live quote
  cache). Blocked by the deploy workflow's Gate 5 (zero-open-position) — this specific bot
  maintains near-continuous ETHUSDT position occupancy, so a true 0-position window has not
  occurred across 6 deploy attempts this session. **This is not a safety concern**: all of this
  code is independently audited as structurally unable to open a position, so the deploy delay
  has zero cost to trading safety or to the accuracy of any evidence — it just means the shadow
  evaluator isn't accumulating real-world log evidence yet. Also found and documented
  (`_workspace/19_...md`): the deploy workflow reports GH Actions `conclusion: success` even when
  Gate 5 refuses — always verify via `git log -1` on the server, not the Actions UI.

## Central finding, reconfirmed multiple times this session

The OLD signal path (`signal_generator.py` → `realtime_decision_engine.py` →
`paper_trade_executor.open_paper_position()`) has near-zero directional edge. Cycle 23's own
grid-search (TP/SL in [8,40]bps against the live MFE/MAE distribution) already proved this;
this session's own live data reconfirms it independently: current trades are ~all `TIMEOUT` exits
at ~300s hold with sub-0.15%-magnitude pnl, regardless of the (now-fixed) TP/SL band width —
price simply doesn't travel far enough in the hold window for band geometry to matter. **No
further old-path tuning (bands, hold time, symbols) is expected to reach WR>55%** — this has now
been checked from multiple angles across multiple sessions and always lands on the same
conclusion. Do not re-litigate this without genuinely new evidence.

**The only credible path to the stated goal is the new cost-aware pipeline actually opening
positions** — which requires, in order: (a) this session's shadow-evaluator code running live for
a while to validate `regime_classifier_v1.py` against reality and see the real admission rate,
(b) a dedicated, reviewed phase to wire an actual `open_paper_position()` call behind the
already-passing router+risk-guard, (c) monitoring the resulting real WR/PF against the goal.

## Immediate next actions for a future cycle/session

1. Deploy commit `77bb2f3` (or whatever `origin/main` HEAD is by then) opportunistically —
   retry when a position happens to be closed, or consider whether a deliberate, reviewed
   entry-pause mechanism is worth building if this keeps failing (not attempted this session;
   would itself need care).
2. Once deployed and running for a meaningful window (hours, not minutes), review
   `journalctl -u cryptomaster.service | grep P0_8_PLUS_SHADOW` for: candidate generation rate,
   `quote_source=live` vs `synthetic` ratio, admission rate, and whether `regime_classifier_v1.py`'s
   output looks sane against known market conditions.
3. Only after that evidence exists: design the real `open_paper_position()` wiring phase (a new,
   narrow, reviewed change — not a rush job), per `_workspace/18_live_wiring_plan.md`.
4. Separately, `_workspace/19_...md`'s deploy-workflow Gate-5-silent-success bug is real and
   worth a dedicated, careful fix in its own session (do not rush a fix to a safety-critical
   CI file).
5. Firebase read-quota burn (rec #5): investigated this session, found currently healthy
   (~264 reads/hour, ~8 days to exhaust) — likely was a one-time burst before, not a constant
   leak. Re-check if `SAFE_MODE_FIREBASE_DEGRADED` recurs.

## Commits this session (chronological, all on `main`, all pushed)

```
c0d209a  P1.1: volatility_breakout_v1
2402be1  P1.2: sideways_mean_reversion_v1
d00b6b8  P1.3: funding_observer_v1
fa968c0  docs: P1.1-P1.3 phase report
bb8f6f6  P0 hotfix: track live systemd overlay; remove cost-floor-violating TP/SL override [DEPLOYED]
9d75b18  §17: wire central risk guard into signal_router
247c7fc  Gate G7 wiring phase 1: shadow evaluator
d066fd7  chore: cycle progress
8aee326  Gate G7 wiring phase 2: wire shadow evaluator into bot2/main.py
3bb196b  live_quote_cache_v1.py
77bb2f3  chore: cycle progress
```
