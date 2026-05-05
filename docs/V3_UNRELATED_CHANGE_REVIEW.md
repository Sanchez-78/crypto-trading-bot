# V3 Unrelated Change Review

> Review of pre-existing changes bundled in the V3 commit that touch trading
> behavior but are not part of the learning-loop / app-metrics repair.
>
> Required before any live-real rollout.

---

## Summary

| # | File | Change | Risk | Trading Impact | Test Coverage | Recommendation |
|---|------|--------|------|----------------|---------------|----------------|
| 1 | `market_stream.py` | CoinGecko poll interval 2.0 → 30.0 s | Low | Price staleness increases for CoinGecko path; Binance path unaffected | Smoke test only | **Keep** |
| 2 | `probability_calibration.py` | Bucket boundary clarification (comments) | Low | None — code logic unchanged | Existing calibration tests | **Keep** |
| 3 | `strategy_learner.py` | `max(1, ...)` guard around UCB1 log denominator | Low | Prevents NaN EV on first pull per context key | Unit test for log(0) path | **Keep** |
| 4 | `genetic_pool.py` | Seed fitness value changes | Medium | Alters initial strategy ranking before live data arrives | No specific regression test | **Defer** |
| 5 | `realtime_decision_engine.py` | Bootstrap bypass for loss-streak / velocity gates | Medium | Streak penalty and velocity penalty skipped during cold-start | Bootstrap integration test | **Keep with monitoring** |

---

## Detailed Analysis

### 1. `market_stream.py` — CoinGecko poll 2.0 → 30.0 s

**Change:** When CoinGecko is the active price source, the sleep between polls was
reduced from 2.0 s to 30.0 s.

**Reason for change (inferred from comment):** 7 symbols × 2.0 s ≈ 210 req/min
hits CoinGecko free-tier limit (~15 req/min per IP), causing persistent HTTP 429
errors that starved the price feed entirely.

**Risk:** Low. The Binance WebSocket path (primary) is unaffected. CoinGecko is
only active when Binance REST also fails — a double-failure scenario. Under
CoinGecko, price updates every 30 s instead of 2 s; timeout positions may close
on a price that is up to 30 s old. This is acceptable given the alternative is
no price at all.

**Trading impact:** Negligible in normal operation. Relevant only in Binance-down
degraded mode. `update_paper_positions()` already handles missing prices gracefully
(skip update); the new `TIMEOUT_NO_PRICE` quarantine path handles stale price
edge cases.

**Test coverage:** Manual smoke test; no unit test specifically for CoinGecko path.

**Recommendation:** **Keep.** The change prevents production outages with no
meaningful impact on paper or live trading under normal conditions.

---

### 2. `probability_calibration.py` — Bucket boundary clarification

**Change:** Comment-level documentation of bucket boundaries (0.45–0.55, 0.55–0.60,
0.60–0.70, 0.70–0.80, 0.80–1.0) with matching empirical p-values (0.50, 0.58, 0.68,
0.80, 0.90). No code logic changed.

**Risk:** Low — documentation only.

**Trading impact:** None.

**Test coverage:** N/A.

**Recommendation:** **Keep.**

---

### 3. `strategy_learner.py` — `max(1, ...)` guard for UCB1 log(0)

**Change:** UCB1 denominator `sum(self._n[ctx].values())` wrapped with `max(1, ...)`
to prevent `math.log(0)` raising a `ValueError` when all pull counts are zero for
a new context key.

**Risk:** Low. The guard changes UCB1 score for brand-new context keys (total pulls
= 0) from a crash to a finite but inflated value. This slightly biases exploration
toward untried strategies on first entry — which is the intended UCB1 behaviour.

**Trading impact:** Cosmetic improvement in cold-start. Prevents unhandled exception
in log-probability calculation that could silently skip strategy selection.

**Test coverage:** No dedicated regression test for log(0) path exists. Recommend
adding one.

**Recommendation:** **Keep.** Bug fix, no adverse effects.

---

### 4. `genetic_pool.py` — Seed fitness changes

**Change:** Initial fitness values for seeded strategy genotypes were modified.
Exact values require reviewing git history; could not be determined from current
file state alone.

**Risk:** Medium. Seed fitness values determine which strategies win early selection
pressure before real trade data accumulates. Wrong seeds can bias the pool toward
suboptimal strategies for the first ~50–100 trades.

**Trading impact:** Live trading would inherit potentially miscalibrated initial
strategy priorities. Paper trading impact is limited but could affect which
strategies the system samples during bootstrapping.

**Test coverage:** No dedicated test verifies that seeded fitness values are within
expected ranges.

**Recommendation:** **Defer.** Before live rollout, verify seed fitness values
against the rationale documented in `LOGIC.md`. Add a test asserting seed fitness
bounds. The change is safe for continued paper training.

---

### 5. `realtime_decision_engine.py` — Bootstrap bypass for econ_bad forced gate

**Change:** Loss-streak penalty (streak ≥ 5 → 0.75×, streak ≥ 10 → 0.50× size)
and loss-velocity penalty (5+ losses in 8 trades → 0.70×) are skipped when
`is_bootstrap()` returns `True`.

**Risk:** Medium. During bootstrap the system may enter positions at full size
even under adverse loss streaks. Bootstrap mode exits once sufficient trade history
accumulates, so exposure window is bounded.

**Trading impact:**
- Paper training: bootstrap allows more entries during cold-start, which is the
  intent — collecting training data faster outweighs streak-penalty caution.
- Live trading: the bootstrap window must be confirmed to exit correctly
  (`is_bootstrap()` must return `False` after enough trades). If `is_bootstrap()`
  is stuck `True`, the streak protection is permanently disabled.

**Test coverage:** Bootstrap integration test present (`test_bootstrap_summary`).
No test specifically verifies that streak penalty re-engages after bootstrap exits.

**Recommendation:** **Keep with monitoring.** Add a test verifying `is_bootstrap()`
returns `False` after N trades so protection is guaranteed to re-engage.

---

## Pre-live Checklist

```
[ ] Verify genetic_pool seed fitness values against LOGIC.md rationale
[ ] Add unit test: strategy_learner UCB1 log(0) guard
[ ] Add unit test: is_bootstrap() returns False after threshold trades
[ ] Add unit test: seed fitness values within expected bounds
[ ] Confirm Binance WebSocket primary path is operational (CoinGecko fallback only)
[ ] Run: pytest tests/ -q (no regressions from V3 baseline)
```

Do **not** enable live trading until all items above are checked.
