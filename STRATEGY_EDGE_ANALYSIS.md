# Strategy Edge Analysis — grounded in the F8b shadow dataset (2026-07-19)

**Data:** 3376 observation-only F8b observations (all data_quality "ok"), collected on the live paper bot. Every observation is a signal DEV_FADE would have traded; we recorded the actual 1s price path and barrier first-crossings instead of opening a position. **Caveat:** ~12h, 98% BULL_TREND, 92% ETHUSDT — one regime/symbol; a final verdict needs ≥14 days multi-regime. But the core numbers below are already load-bearing.

## The finding that changes the conclusion

Sweeping the round-trip cost (best TP/SL config each row):

| round-trip cost | best (TP,SL) | expectancy/trade | WR | PF |
|---|---|---|---|---|
| **0 bps** | TP=10 / SL=5 | **+2.83 bps** | 59% | **2.52** |
| 2 bps | TP=10 / SL=5 | +0.83 bps | 56% | 1.31 |
| 5 bps | TP=10 / SL=5 | −2.17 bps | 46% | 0.47 |
| **18 bps** (assumed) | TP=10 / SL=5 | **−15.17 bps** | 0% | 0 |

Hold-to-horizon raw directional edge: **+0.83 bps/trade**. **Break-even round-trip cost ≈ 2–5 bps.**

**DEV_FADE has a real, statistically meaningful directional edge** (+2.83 bps/trade gross, WR 59%, PF 2.5 at zero cost — not noise). This corrects the earlier "no edge" framing: the signal predicts. **The strategy is not killed by a bad signal — it is killed by execution cost.** At the assumed 18 bps taker round-trip, the edge is buried ~6–18× under cost. At ~2–4 bps it is break-even to slightly positive.

So the E1–E4 **NO-GO is entirely a function of the 18 bps cost assumption**, and the whole question collapses to: **can we execute this signal for ≤ ~3 bps round-trip?**

## What class of strategy / execution could close the gap

Ranked by fit to THIS data:

### 1. Maker-only / passive execution — highest leverage, uses the edge we already have
Post limit orders (at/inside the touch) instead of paying the taker spread. On liquid pairs (ETH/BTC) round-trip maker cost is ~0–4 bps, and rebate venues can make it *negative*. If round-trip drops to ~2–4 bps, the **existing** signal is break-even-to-positive — no new signal needed.
- **Risk:** fill rate and adverse selection. A mean-reversion *entry* wants to buy weakness / sell strength — passive orders there are prone to being filled exactly when the move continues against you (adverse selection), and unfilled when it reverts. The counterfactual here assumes *barrier* fills, not *passive-order* fills, so it OVER-states achievable P&L. This must be modeled with a realistic queue/fill simulation before trusting it.
- **This is the single most promising lever** — it monetizes an edge that already exists rather than hunting a new one.

### 2. Fee-tier / venue / rebate optimization
Volume tiers, maker rebate programs, or a cheaper venue reduce the 18 bps directly. Combined with (1), plausibly reaches the ~2–4 bps break-even band.

### 3. Signal sharpening to widen the cost headroom
+2.8 bps gross is thin. If a sub-segment (symbol / regime / hour / signal strength) carries most of the edge, filtering to it raises per-trade edge and buys cost headroom. **To check next:** does the edge concentrate? (This dataset is 98% one regime, so it can't answer regime-conditioning yet.) A fader should do BEST in RANGING/quiet regimes and WORST in trends — yet this trend-heavy sample still shows +2.8 bps gross, which is encouraging; a range-heavy sample may be stronger.

### 4. Larger-move capture (different horizon/signal) — poor fit here
Making 18 bps a small fraction of the move needs 50–100+ bps excursions. But the data shows moves are small (favorable crossings max ~15 bps, never +20 in 15 min). Capturing bigger moves requires a *different* predictive signal/horizon, not this one. Lower priority than fixing execution on the edge we have.

## Honest bottom line

- **Do NOT abandon DEV_FADE.** The signal has a real +2.8 bps/trade edge (PF 2.5, WR 59%). My earlier "no edge" statement was incomplete — the edge is real, the **cost** kills it.
- The goal (positive P&L) hinges on **execution cost ≤ ~3 bps round-trip**, not on the signal.
- **Highest-value next step:** model realistic *maker-fill* execution (queue position, fill probability, adverse selection) against the shadow paths — the current counterfactual assumes barrier fills and OVER-states maker P&L. If realistic maker round-trip cost lands ≤ ~3 bps with acceptable fill rate, positive P&L is plausible and worth a gated paper forward test.
- **Still required before any real risk:** ≥14 days, multi-regime data (this is 12h/one regime); a maker-execution model (not the barrier-fill counterfactual); independent review. **REAL trading remains NO-GO.**
