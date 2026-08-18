# Cost-Aware Strategy Design — Evidence-First Strategy Expansion v2 (§27.2)

Companion to `docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md` (system
architecture) and the per-phase acceptance reports
(`docs/P0_7_ACCEPTANCE.md` .. `docs/P1_0_ACCEPTANCE.md`,
`docs/P1_1_P1_3_PHASE_REPORT.md`). This document covers the *design*
(what each piece computes and why); the acceptance reports cover
implementation status and test evidence.

## Cost model (`src/services/cost_model.py`)

`evaluate_edge()` computes, from an explicit set of keyword arguments (no
hidden global state): all-in cost in bps (fees + spread crossing +
slippage proxy scaled by requested-vs-visible notional + a latency
buffer scaled by realized volatility per second + funding crossing cost
when a funding boundary falls inside the expected holding horizon) and
`net_expected_edge_bps = gross_expected_move_bps - all_in_cost_bps -
uncertainty_buffer_bps`. `admitted = net_expected_edge_bps > 0`. Raises
`ValueError` (fail-closed, §2.5) on non-finite or structurally impossible
inputs (negative spread, ask < bid) rather than silently admitting.

## Central signal contract (`src/services/strategy_contracts.py`)

`StrategySignal` (frozen dataclass, `__post_init__`-validated) and
`SignalEvaluation` (the central router's immutable decision). Every new
strategy emits `StrategySignal`; nothing downstream of
`signal_router.evaluate_signal_for_paper_entry()` accepts a different
shape. `evidence_only: bool = True` on every signal (§2.4) — a strategy
or signal marked `evidence_only=True` can never receive
`strict_ev`/`readiness_eligible`, only the bounded
`P0_ADMIT_EVIDENCE_COLLECTION` path, regardless of what the underlying
segment statistics would otherwise allow.

## Central routing (`src/services/signal_router.py`)

The one function every new strategy signal passes through
(`evaluate_signal_for_paper_entry()`). Reuses the existing
`P0SegmentEVGate` (§16 step 7-8, Gate G0 finding: this class already IS
the document's "Central P0 Segment EV Gate") rather than reimplementing
it. Never opens a position itself (no import of any entry primitive,
enforced by `tests/test_signal_router_bypass.py`'s AST scan).

2026-08-18 addition: `quarantine_fn`/`evidence_eligibility_fn` injectable
overrides (same DI pattern as the pre-existing `risk_guard_fn`) —
`P0SegmentEVGate`'s shared `EVIDENCE_COLLECTION_REGIMES`/
`QUARANTINED_REGIMES`/`QUARANTINED_SYMBOLS` constants were tuned for the
legacy signal path (e.g. its BEAR_TREND quarantine assumes "paper
trading is long-only," which is false for `trend_cost_aware_v1`'s own
short support) and would otherwise structurally exclude
`sideways_mean_reversion_v1`/`volatility_breakout_v1` from ever being
admitted. See `_workspace/35_p0_8_plus_evidence_scope_widening.md`.

## Trend logic (`trend_cost_aware_v1`, §10)

`ALLOWED_LONG_REGIMES` = BULL_TREND, `ALLOWED_SHORT_REGIMES` = BEAR_TREND
— this strategy explicitly supports both directions via a dedicated
`short_candidate()` path, not long-only. Features: fast/slow EMA slope
(bps/minute, interval-agnostic via real `open_time` deltas), VWAP offset,
higher-high/higher-low/lower-high/lower-low structure scores, trend
persistence ratio, ATR-derived volatility in bps (reused directly by
`dynamic_trend_exit_v1` — one computation, two consumers). Self-filters
on `cost_model.evaluate_edge()` before ever emitting a candidate (§10.3:
"net expected edge positive after costs" is a candidate-level gate, not
only a router-level one).

## OFI / microprice logic (`order_flow_features.py`, §11)

Diagnostic feature set: top-of-book imbalance, microprice, signed
trade-delta over rolling windows, large-trade-conflict detection
(`FLOW_LARGE_TRADE_CONFLICT` takes precedence over the general
`FLOW_CONFLICT_LONG`/`SHORT` codes). Zero admission authority by design
(§11's own framing: "do not initially create an independent
high-frequency OFI trading strategy") — never imports `P0SegmentEVGate`
or any entry primitive. **Currently has zero live callers** — see
`docs/P0_9_ACCEPTANCE.md` for the gap this leaves in
`dynamic_trend_exit_v1`'s `FLOW_REVERSAL_EXIT` level.

## Dynamic exits (`dynamic_trend_exit_v1.py`, §12)

Nine-level fixed-order hierarchy, first match wins: data-integrity →
hard stop (structural vs volatility, classified by whether the stop has
already trailed) → risk-limit (reserved slot, no check implemented — no
central risk-limit concept exists yet beyond the position-level risk
guard) → opposite-flow (inert, see OFI above) → structural trend failure
(reuses `trend_cost_aware_v1.TrendFeatures` — same representation as
entry, §12.5) → regime invalidation (inert in the current wiring, no
live per-tick reclassification feeds it) → edge decay (inert, no
reviewed decay model) → trailing stop (activates past
`TRAILING_ACTIVATION_ATR_MULTIPLE`, never loosens) → target → max-hold
safety (last resort, legacy-mapped to `"TIMEOUT"` for backward-compatible
dashboards). Wired 2026-08-18 (`docs/P1_0_ACCEPTANCE.md`), scoped to
`trend_cost_aware_v1`-sourced positions only — it is the only strategy
this exit module's own imports (`TrendFeatures`) are designed for.

## Breakout logic (`volatility_breakout_v1`, §13, code exists, unwired exit)

`ALLOWED_REGIMES = {SIDEWAYS, VOLATILE}`. `COMPRESSION_HISTORY = 60`-bar
lookback; `COMPRESSION_CHANNEL_WIDTH_PERCENTILE_MAX = 0.35` — a
"prior compression" gate (only propose a breakout candidate if the
channel was genuinely narrow beforehand, not on every volatility uptick).
`EXIT_PROFILE = "dynamic_breakout_exit_v1"` is a metadata tag only — **no
module by that name exists**; positions from this strategy fall through
to the generic TP/SL/timeout exit (same as `sideways_mean_reversion_v1`,
see the dynamic-exit wiring's explicit scoping in
`docs/P1_0_ACCEPTANCE.md`). Registered and reachable via the live
pipeline since 2026-08-18's scope widening; 0 admitted candidates
observed as of this writing (see `docs/P1_1_P1_3_PHASE_REPORT.md` for
the phase's own original test evidence).

## Mean-reversion restrictions (`sideways_mean_reversion_v1`, §14, code exists, unwired exit)

`ALLOWED_REGIMES = {SIDEWAYS}` only — deliberately narrower than
breakout's two-regime scope, per the document's explicit caution against
mean-reversion strategies trading trending markets. `EXIT_PROFILE =
"mean_reversion_exit_v1"` — same "metadata tag, no module" situation as
breakout above. Registered and reachable via the live pipeline since
2026-08-18.

## Funding observer (`funding_observer_v1`, §15)

**Not a strategy in the P0.8+ sense.** §15 is explicit: "It must not
open a position." Never imports `strategy_contracts.StrategySignal`,
never calls `signal_router` or any entry primitive, has no
`generate_candidates()` function, and is **deliberately NOT registered**
in `strategy_registry.py` — registering it would misrepresent it as a
signal-producing strategy awaiting admission, which it structurally
cannot be. Computes a diagnostic funding-rate score from caller-supplied
inputs only; does not fetch market data, hold credentials, or schedule
itself. Explicitly distinct from this repository's separate,
externally-gated funding-carry *research* thread
(`EXTERNAL_AUDIT_PROMPT_v9.md`, `scripts/research/funding_carry_*.py`) —
that thread investigates an actual delta-neutral two-leg carry trade and
has not been authorized; this observer has no hedge leg and makes no
tradability claim.

## Segment definitions

`P0SegmentEVGate.build_segment_key(symbol, side, regime, source,
tp_sl_profile)` — the same segment-key shape the legacy path already
uses (Gate G0 finding, reused not reimplemented). A second, independently
maintained legacy-format segment key
(`f"{symbol}_{side}_{regime}_{source}_{tp_sl_profile}"`, underscore- not
colon-separated) exists inside `paper_trade_executor.py`'s own internal
P0.3B/P0.3C reroute logic — the two are NOT unified; a P0.8+ position's
`segment_key` as seen by `signal_router.py` differs from the one
ultimately stored on the closed trade record (see
`docs/P0_8_ACCEPTANCE.md`/`_workspace/33` for the full attribution-
overwrite disclosure). A future unification is a real, documented gap,
not yet addressed.

## Versioning rules

Every `StrategySignal` carries `strategy_id`/`strategy_version`;
`signal_router.py` rejects a signal whose `strategy_version` doesn't
match the currently registered `current_version` (§16.3). No formal
"bump version on behavior change" policy has been written down or
enforced by tooling — a real gap against §22A.2's "version the
classifier" / general versioning-discipline spirit, not yet closed.
