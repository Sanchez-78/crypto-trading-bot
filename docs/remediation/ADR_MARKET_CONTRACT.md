# ADR: Market Contract (SPOT vs USD-M Futures)

**Status:** `NOT_RUN` this session — `TARGET_MARKET=UNDECIDED` per the
governing contract's execution parameters, and this session's available
time was spent entirely on the contract's mandatory gating item
(STATE-01, see `AUDIT_REMEDIATION_REPORT.md`). No comparison work, no
fail-closed validator, and no market-dependent code change was performed.

## What is confirmed (static reads only, this session)

Not independently re-verified this session — carried forward from the
governing contract's own starting evidence, which cites:

- Spot WebSocket + `/api/v3/ticker/bookTicker` in `market_stream.py`.
- Spot `/api/v3/klines` in `binance_client.py`.
- Spot `/api/v3/order` in `execution_engine.py`.
- Futures/funding/short assumptions present elsewhere in cost and
  strategy code (e.g. `strategy_trend_cost_aware_v1.py`'s
  `ALLOWED_SHORT_REGIMES` and funding-aware cost terms in
  `cost_model.py`).

This session did not re-derive the exact endpoint list, symbol/quantity
semantics, fee schedule source, or exchange-filter behavior for either
market from current code — the comparison table required by the
governing contract (REST/WS endpoints, symbol/quantity semantics,
long/short capability, funding applicability, fee schedule source,
exchange filters/precision, position/order reconciliation semantics,
required migration and tests) is **not populated**.

## External facts

`ALLOW_EXTERNAL_NETWORK=false` for this task. No external Binance
documentation was consulted. Any exchange-behavior claim in the existing
codebase or prior session artifacts must be treated as `NOT VERIFIED`
until checked against the official Binance USDⓈ-M Futures / Spot API
documentation at implementation time (see the governing contract's §36F
reference list from the separate, earlier Evidence-First Strategy
Expansion v2 document for the specific URLs this project has previously
used as its authoritative source).

## Decision

**Not made.** `TARGET_MARKET` remains `UNDECIDED`. Per the governing
contract: "implement a fail-closed validator that refuses a mixed
contract, keep real execution disabled, and stop only market-dependent
changes." **The fail-closed validator itself was also not implemented
this session** — this is a real, disclosed gap, not an oversight: it
requires the same verify-current-code-first rigor as every other
finding, and this session's time was allocated to STATE-01 per the
contract's own mandatory dependency order.

## Consequence for other findings

MARKET-01, EXEC-01, and the market-dependent portions of DATA-02,
ECON-01, EXIT-01 all remain `BLOCKED_BY_DECISION` or `NOT_RUN` pending
either this ADR's completion or an explicit `TARGET_MARKET` decision from
the operator.

## Recommended next step

A dedicated session (or a dedicated phase of a future session) should:
1. Re-derive the current market-contract evidence from `market_stream.py`,
   `binance_client.py`, `execution_engine.py`, and the cost/strategy
   modules directly (file:line citations, not memory).
2. Populate the comparison table above.
3. Either implement the fail-closed hybrid-rejection validator (if
   `TARGET_MARKET` stays `UNDECIDED`), or implement the selected
   contract's mocked-metadata test fixtures (if a decision is made) —
   never both at once, and never with live network access.
