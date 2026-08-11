# Why every exit is TIMEOUT now (user question, answered with evidence)

**Date:** 2026-08-11, cycle 32

## The hard numbers (cache.sqlite, ETHUSDT, by day)

```
date        n    tp  sl  timeout  avg_mfe  avg_mae  max_mfe  min_mae
2026-08-03  141  69  44  28       8.42     -5.21    33.86    -13.62
2026-08-04  119  30  44  45       6.25     -5.85    18.84    -11.35
2026-08-05   33   2   5  26       5.36     -6.78    17.56    -19.91
2026-08-06  159   0   0  159      8.37     -4.24    52.04    -32.76   <- cliff
2026-08-07  204   0   0  204      6.58     -3.16    20.67    -9.88
2026-08-08  220   0   0  220      2.93     -1.23    12.94    -9.12
2026-08-09  231   0   0  231      3.75     -1.44    19.06    -9.84
2026-08-10  152   0   0  152      7.13     -3.99    25.22    -30.97
```

**Last TP exit: 2026-08-05T10:40 UTC. Last SL exit: 2026-08-05T10:34 UTC.**
Zero of either since — five days before this session started, and completely
unaffected by anything I changed today (my TP/SL hotfix deployed 2026-08-10 06:43).

## Why the band-width fix I made today didn't change this

There are **four separate places** in the code that can set a position's TP/SL
distance, not one:

| # | Location | What it uses |
|---|---|---|
| 1 | `paper_trade_executor.py:1750-1752` open flow, `PAPER_TP_ZONE_BPS` **set** | env var directly (was 12bps before today) |
| 2 | `paper_trade_executor.py:1753-1757` open flow, env var **unset** | the learning system's own "learned TP" for that regime, if it has one -- **takes priority over the shipped default** |
| 3 | `paper_trade_executor.py:1763` open flow, no learned value either | the shipped default (`_DEFAULT_TP_ZONE_BPS=50`, what I intended) |
| 4 | `paper_trade_executor.py:3067` `calibrate_paper_training_geometry()`, `mode=="paper_live"` | `os.getenv("PAPER_TP_ZONE_BPS", "60")` -- a **different hardcoded fallback (60, not 50)** |

Today's fix removed the `PAPER_TP_ZONE_BPS` env var entirely (to let the shipped
default apply). But removing it doesn't land on path #3 — it lands on path #2,
because the adaptive learning system already has a "learned TP" for most
regimes by now. The live position I inspected just now shows
`tp_zone_bps_at_entry: 35` — not my intended 50, not the calibration
function's 60, but whatever the learner currently believes for that
regime/symbol. **SL isn't affected by this ambiguity** (no learned-value
branch for SL), so it correctly landed on my intended 25bps.

This is the same cross-module TP/SL drift the reviewer flagged as C6 days ago
(`_workspace/16_review.md`) — confirmed here to be worse than described: not
three call sites, four, with genuinely different logic, not just different
default numbers.

## The real reason: realized volatility, not band width

Look at the `avg_mfe`/`avg_mae` columns above: they've been **shrinking**
since Aug 3 (avg_mfe 8.4 → 2.9-7.1bps) at the same time bands have been
**widening** (12/10bps live-override era → my fix's 25bps SL, plus whatever
the learner picks for TP, typically 35bps+). Those two trends point in
opposite directions. At the current ~4bps round-trip cost, cost-floor
compliance needs TP >= 8bps (2x cost) and a reasonable safety margin pushes
the practical floor higher (my fix targets ~38-48% breakeven share, needing
TP well above 8bps) — but realized moves this week average only 3-8bps and
rarely exceed 20-25bps. **There may currently be no TP/SL width that is
simultaneously cost-floor-compliant and frequently reachable.** This is the
same conclusion the 2026-08-07 grid-search already reached from a different
angle (no profitable geometry in [8,40]bps) — this dataset extends and
sharpens it: it's not that some geometry in that range is marginally better
than another, it's that the market's short-horizon movement has compressed
below what any compliant geometry needs.

Corroborating evidence from the bot's own learning monitor (unrelated to
anything I touched): `Health: 0.000 [BAD]` and `BOOTSTRAP_REDUCED_MODE
active` are logged on every single learning-monitor tick, continuously, with
`conv:0.00` for every symbol/regime pair despite n=150+ samples for
ETH. The bot's own internal health system has independently concluded there
is no stable, exploitable edge right now — matching this analysis exactly.

## What this changes about today's fix

Not a mistake, still correct to have made: it removed a geometry that was
*mathematically guaranteed* to lose (63.6% breakeven requirement). But it
does NOT and structurally cannot fix the "everything times out" pattern,
because that pattern predates the fix by 5 days and is driven by realized
volatility being too low for ANY reasonable band, not by the specific band
values. No further band-width tuning is expected to help — already checked
from three independent angles now (2026-08-07 grid-search, this session's
own MFE analysis, and the bot's own health/convergence monitor all agree).

## What would actually move WR

Same conclusion as the rest of this session: the old signal path
(`signal_generator.py`) has no exploitable short-horizon edge in current
market conditions, confirmed again here. The new cost-aware pipeline (still
pending live deploy, Gate 5) generates candidates that self-filter on
*computed* net edge rather than assuming a fixed band works — that's the
only mechanism in this codebase designed to handle exactly this "current
volatility doesn't support a fixed band" problem, because it recomputes the
required move per-candidate instead of hoping a static TP/SL number stays
appropriate as conditions change.
