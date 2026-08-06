# Intake: suspected TP-below-cost-floor invariant violation

## Hypothesis (unverified)
Production override: `PAPER_TP_ZONE_BPS=12`, `PAPER_SL_ZONE_BPS=10`,
`PAPER_FEE_PCT=0.0004` (0.04%), `PAPER_SLIPPAGE_PCT=0.0`.
`dashboard_read_model.py: COST_FLOOR_BPS = 18` (stale? comment says "15 fee +
3 slippage" — doesn't match the live 0.04% fee config).
`trade_executor.py: FEE_RT = 0.0015` (0.15%, a DIFFERENT hardcoded default,
possibly unused if env always set).

Historical precedent: project memory records "Cycle 27 Reverted: TP below
cost floor (2026-06-19) — TP=7bps < 18bps cost floor → every TP exit
net-negative, 0% WR. INVARIANT: TP_ZONE must exceed cost floor + margin
(~25-30bps min)."

## What must be verified with real evidence, not config-reading alone
1. What fee/slippage does the LIVE PnL calculation actually apply to a
   closed PAPER trade? Find the exact code (net_pnl_pct computation) and
   confirm which constant/env var it reads at runtime — is it
   `PAPER_FEE_PCT` (0.04%/side?), `trade_executor.FEE_RT` (0.15% RT), or
   something else entirely? One-way vs round-trip matters (2x difference).
2. Given the REAL applied cost, is a 12bps TP actually net-positive,
   net-negative, or borderline after that real cost — not the stale 18bps
   dashboard constant, not the historical 2026-06-19 numbers (config may
   have changed since).
3. Live exit_reason breakdown of RECENT closes (post DEV_FADE-off, last
   ~90 min): what fraction are TP vs SL vs TIMEOUT, and what's the
   PER-EXIT-REASON average net_pnl_pct? If TP exits are averaging negative
   net_pnl_pct, that's the smoking gun, directly observable, no need to
   even reconstruct the fee math.
4. Is `PAPER_MIN_TP_BPS=8` (also in the override) relevant — is that a
   floor genuinely enforced somewhere that should have prevented TP=12bps
   if it were unsafe, or is it a dead/unused config key?

## Explicitly not assumed
- Not assuming the historical 18bps/25-30bps figures are still accurate —
  fee config has visibly changed since that incident (0.04% now vs whatever
  it was on 2026-06-19). Get the REAL current number.
- Not assuming this is THE cause of the current WR=22%/PF=0.207 — could be
  a contributing factor, the dominant factor, or unrelated (e.g. the new
  dominant `fake_breakout` edge could simply have a bad win rate regardless
  of TP/SL sizing). Check the exit_reason breakdown to distinguish.
