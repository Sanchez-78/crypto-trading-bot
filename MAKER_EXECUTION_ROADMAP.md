# Maker-Execution Corrected Experiment — Roadmap (M1–M5)

**Why:** six strategy classes fail the ~18 bp/leg cost wall (`RESEARCH_COSTWALL_FINDINGS.md`); the
binding constraint is **execution cost, not signal**. Auditor v6 verdict C said the earlier maker
refutation was over-claimed (midpoint ≠ executable fill). The one credible path to the goal is
**properly-modeled maker/passive execution** — if realistic round-trip lands ≤ ~3–6 bp, several
signals move toward viability. This roadmap is the auditor's M1–M5, done in small reviewed steps
(observation-only, default-off; no real-order path; REAL = NO-GO throughout).

## M1 — enrich the shadow recorder to executable data
- [x] **M1.1 — coverage integrity** (#118, merged). `_data_quality` now density-first + verifies the
      1s path reached ≥90% of the horizon; shutdown-truncated paths tagged `partial_shutdown`.
      Trustworthy horizon data. reviewer REJECT→fix→APPROVE, trading-safety SAFE, 25/25 tests.
- [x] **M1.2 — capture executable spread (bid/ask)** (#120, merged). market_stream→price_tick→
      on_price→recorder; mean `spread_bps` per 1s bucket + `shadow_path_1s.spread_bps` column +
      idempotent ALTER migration. reviewer APPROVE + trading-safety SAFE, 28/28. Original spec:
      1. `market_stream.py:~97` — add `bid`/`ask` to the `price_tick` publish dict
         (`publish("price_tick", {... , "bid": bid, "ask": ask})`). Backward-compatible (extra keys).
      2. `signal_generator.py:683` — pass them through:
         `_shadow.record_tick(s, float(p), ts_ms, bid=data.get("bid"), ask=data.get("ask"))`.
      3. `shadow_excursion_recorder.py` — `record_tick`/`on_tick`/`_Observer.update` accept optional
         bid/ask; store **mean `spread_bps` per 1s bucket**; `path_rows()` + `_persist` write it.
      4. Schema: `ALTER TABLE shadow_path_1s ADD COLUMN spread_bps REAL` — idempotent via
         `PRAGMA table_info` in `_db()` (SQLite ADD COLUMN backfills NULL; safe on the live DB).
      Gates: reviewer + trading-safety (touches ingestion — small, additive, default-off).
- [x] **M1.3a — capture admission context** (#122, merged). observe hook records the P0 decision
      (p0_reason/strict_ev_allowed/is_blocked), signal strength (edge/ev/score/obi), and exposure
      snapshot (open_total/open_symbol) into features_json (schema v2) — offline can reconstruct
      the *admissible-trade* subset (auditor §3.5). reviewer APPROVE + trading-safety SAFE.
- [ ] **M1.3b — capture aggTrade.** New Binance `@aggTrade` WS subscription
      (aggressor side/price/volume) so fills can be modelled against *traded-through*, not midpoint;
      record the P0/EV/exposure `admission` outcome so analysis can separate raw-signal edge from
      *executable* (admissible-trade) edge (auditor §3.5). Bigger — its own PR(s).

## Live deploy status (2026-07-20)
M1.1 + M1.2 + M1.3a are **DEPLOYED LIVE** (server `332acba`, deploy-apply DEPLOY_OK, READY
converged). The bot observes (0 positions, REAL NO-GO) and now records coverage-integrity +
`spread_bps` + admission context — the enriched dataset is accruing. M1.3b/M2 changes are
NOT yet live.

## M2–M5 — the model (on enriched data, after collection)
- [~] **M2 — executable fill model scaffold BUILT (`scripts/maker_fill_model_v2.py`), PR #124
      RE-REVIEW PENDING (do not merge).** optimistic (midpoint ceiling — non-executable) /
      conservative (spread-adjusted, executable — GO taken on THIS). Fixes all audit v6 flaws:
      admissible-trade filter, data_quality=ok, spread-aware fills, fill-time/TIF, exit-clock
      A/B grid, horizon-aware embargo, REAL moving-block bootstrap CI, full §8 GO bar
      (expectancy + CI lower>0 + ≥200 fills + PF≥1.20 + no-symbol>50% + coverage), hard-locked
      off on thin/legacy/single-regime data. 7 tests green. Reviewer REJECTED v1 (fake
      bootstrap + dead exit-B) → all fixed → **re-review interrupted by the session limit
      (resets 15:00 UTC); needs independent re-approval before merge.** `base` scenario
      (traded-through) still needs aggTrade (M1.3b).
- [ ] **M3 — pre-registered execution policies:** offset E ∈ {1,2,3,4,6}, TIF ∈ {1,3,5,10,30}s,
      exit clock A (signal expiry) / B (fixed hold from fill); maker→cancel→conditional-taker hybrid.
- [ ] **M4 — purged nested walk-forward:** embargo ≥ one horizon, cluster-bootstrap by time/regime,
      effective sample size (overlapping paths ≠ independent), CI excludes 0.
- [ ] **M5 — realistic venue costs:** maker fee/rebate + taker exit + spread + slippage +
      partial-fill/cancel + latency, from a concrete tier — not abstract 0/3/18.

## GO bar (auditor §8) — before any gated paper forward test
OOS PF ≥ 1.20 · net expectancy > 0 with ≥ +2–3 bp reserve after realistic cost · cluster-bootstrap
95% CI lower > 0 · ≥ 200 OOS fills · stable in ≥ 2 regimes (or regime-gated) · no symbol > 50% of
profit · survives the conservative fill scenario. If the base/conservative model fails →
**retire DEV_FADE definitively.** If data adequacy isn't reached within a bounded budget
(~30 days / 500 valid range-like effective obs) → archive and pivot. **REAL = absolute NO-GO.**

## Honest odds
Auditor-blessed and the best remaining lever, but the prior is modest: even at low maker cost the
gross edge is thin, and adverse selection on fade entries is real. Most likely M-series outcome is a
*rigorous, executable-data* confirmation of NO-GO — but that is a definitive answer worth the
bounded budget, and it is the only path that attacks the actual binding constraint (cost).
