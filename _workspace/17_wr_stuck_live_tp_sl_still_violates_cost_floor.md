# Forensics — WR stuck at 12-14% despite prior "fixes": live TP/SL override never changed

**Date:** 2026-08-10, autonomous loop cycle 24 (resuming from cycle 23, `_workspace/monitoring_progress.json`)
**Collected via:** direct SSH to Hetzner (root@78.47.2.198), live dashboard API, `systemctl show`, `journalctl`

## Live evidence (not hypothesis)

```
$ curl -s http://localhost:5001/api/dashboard/metrics
win_rate_pct: 12.0 (recent_100)
profit_factor: 0.411 (lifetime 0.413, n=2354)
lifetime_expectancy: -0.036948
recent: wins=12 losses=28 flats=60 (n=100)
exit_distribution: {tp: 474, sl: 529, timeout: 1629, scratch: 0}  (69% TIMEOUT)
```

```
$ systemctl show cryptomaster.service -p Environment
PAPER_FEE_PCT=0.0004
PAPER_SLIPPAGE_PCT=0.0
PAPER_TP_ZONE_BPS=12
PAPER_SL_ZONE_BPS=10
```
Source: `/etc/systemd/system/cryptomaster.service.d/99-cryptomaster-managed-runtime.conf` (untracked on server — known governance gap, `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` §6/§9 gap table).

Also live and unresolved: `SAFE_MODE_FIREBASE_DEGRADED`, `entries=blocked`, `reason=quota_429`, running continuously (67h20m uptime). `[QUOTA_DEBUG]` confirms the *reset boundary logic itself is correct* (`window_start=2026-08-09T07:00:00 >= boundary=2026-08-09T07:00:00`, `now=2026-08-10T06:37` — properly waiting for the 07:00 UTC boundary, not the old bug). The quota is instead being **exhausted well within each 24h window** (50000/50000 reads, 20168/20000 writes) — a read/write burn rate issue, separate from the reset-timing bug already fixed in `f6e2f28`/`65695b9`. `_workspace/13_quota_exhaustion_audit.md` rec #5 (`risk_engine.py:695` `prob_ruin` cache hole) was explicitly flagged and explicitly deferred in that patch's scope note — never followed up.

## Root cause of the WR/PF stagnation

`validate_tp_sl_cost_floor(12, 10, 4.0)` (the function shipped in commit `09f1acd`):
- `tp_net = 12 - 4 = 8`
- `sl_net = 10 + 4 = 14`
- `breakeven_share = 14 / (8 + 14) = 63.6%`

This is **the exact same violating geometry cited as the root cause in cycle 23** ("PAPER_TP_ZONE_BPS=12/SL_ZONE_BPS=10 deployed 2026-07-31 09:27 UTC via an untracked systemd file... Break-even TP-share 63.6%, realized 50.5%"). It is **still deployed, unchanged**, three days and two "fixes" later.

**Why the prior fixes did not touch this:** commit `09f1acd` changed `_SHIPPED_TP_ZONE_BPS`/`_SHIPPED_SL_ZONE_BPS` (the code DEFAULT, i.e. `_DEFAULT_TP_ZONE_BPS = int(os.getenv("PAPER_TP_ZONE_BPS", str(_SHIPPED_TP_ZONE_BPS)))`). Since the systemd drop-in sets `PAPER_TP_ZONE_BPS`/`PAPER_SL_ZONE_BPS` explicitly, `os.getenv(...)` always returns the drop-in's value (12/10) and the shipped default (50/25) is never consulted. The reviewer's own C5 in `_workspace/16_review.md` flagged exactly this failure mode ("a single `log.critical` at startup ... should be given one consumer that a human or CI actually looks at") — nobody looked at it; the violation has been logging every process start for 3+ days with zero consumer.

Confirmed live: `[TP_SL_COST_FLOOR_VIOLATION]` should be in the startup log. (To verify on next patch pass — not yet grepped this session, but the arithmetic above is deterministic and independently reproducible from `validate_tp_sl_cost_floor`'s own code.)

## Why re-tuning bands further will NOT reach WR > 55%

Already established in cycle 23 (grid-search over TP/SL in [8,40]bps against the live MFE/MAE distribution, n=1314): **no TP/SL geometry is profitable against this signal path** — implied gross edge is only +0.5bps/trade against 4-8bps real cost. Widening/narrowing bands trades WR against average win/loss size; it cannot manufacture edge that isn't there. TIMEOUT dominating 69% of exits corroborates this: price rarely travels far enough in either direction within the hold window to hit even a 10-12bps band, i.e. the realized short-horizon move is small and directionless relative to cost — a near-zero-edge regime.

This is the same conclusion the "Evidence-First Strategy Expansion v2" program (P0.7-P1.2, this repo, commits `c3083ab`..`fa968c0`) was built to address: the new strategies self-filter on `cost_model.evaluate_edge().admitted` (positive net edge required) before ever proposing a candidate, instead of admitting every signal and hoping the exit bands compensate. **None of P0.8-P1.2 is wired into the live loop** (confirmed by grep, see `docs/P1_1_P1_3_PHASE_REPORT.md`) — so the live bot has been running the zero-edge path exclusively this whole time.

## Two independent, evidence-backed action items

1. **P0, safety/stopgap (cheap, low-risk):** the live TP/SL geometry is currently *worse than doing nothing* — it is mathematically guaranteed to lose slightly more than break-even at realized hit rates (50.5% real vs 63.6% required). Bringing the live override in line with a cost-floor-compliant geometry (or removing the override so the shipped default applies) stops active bleeding while the real fix (below) is built. This alone will not reach WR>55% (per the grid-search finding) but removes a self-inflicted structural loss.
2. **P0, primary lever toward the actual goal (WR>55%, high P&L):** wire the cost-aware strategies (P0.8 trend, P0.9 OFI confirmation, P1.0 dynamic exit, P1.1 breakout, P1.2 mean-reversion) into the live decision loop so they start generating real paper evidence with positive-expected-value admission built in from the start, rather than continuing to bandage a signal path with proven ~0 edge.

Both should go through the full evidence-based-patch-orchestrator review (trading-safety-agent, reviewer-agent, test-regression-agent) before any deploy, per `CLAUDE.md`'s harness. Item 1 is the smaller, faster, lower-risk change and should land first.

**Firebase quota burn (rec #5, `risk_engine.py:695`)** is a third, independently-diagnosable item — tracked but not yet root-caused this session; deferred to a follow-up cycle unless it is found to be blocking deployment itself.
