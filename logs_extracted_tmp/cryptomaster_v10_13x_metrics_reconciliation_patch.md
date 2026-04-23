# CryptoMaster — V10.13x Metrics Reconciliation + Exit Truth Patch

## Role
You are a senior quant/backend engineer patching an existing live Python crypto trading bot.
Do not redesign the system. Apply targeted, production-safe fixes inside the current architecture.

Your priority is truthfulness of metrics and internal consistency.

---

## Current observed state from latest production logs

The previous learning-integrity issue is partially improved.

### What is now clearly better
- Learning Monitor is no longer totally dead/stale.
- Pair/regime stats now contain non-zero WR values.
- Feature WR values are now non-zero.
- Example:
  - `BNB BEAR_TREND n:11 EV:+0.001 WR:45%`
  - `ETH BULL_TREND n:10 EV:-0.003 WR:70%`
  - feature WR values around `46%`
- Hydration reporting now says:
  - `Hydrated pairs: 12 with n≥5, 5 with n≥10, 3 with conv>0`
  - `Total trades in LM: 124`

So the previous “LM completely disconnected from reality” failure has improved.

---

## But the latest logs still show critical correctness problems

### Problem 1 — Summary trade count is still inconsistent
The bot prints:

- `Obchody 124`
- but then inside the same line:
  - `(OK 3173  X 2993  ~ 3758)`

This is impossible if all values refer to the same canonical trade set.

That means the summary header and outcome counters still come from different sources or incompatible aggregation layers.

This is a hard metrics integrity failure.

---

### Problem 2 — Summary PnL still contradicts per-symbol PnL
At the same time the bot prints:

- total `Zisk = -0.00011821`

but per-symbol totals shown are all positive:
- BTC `+0.00005212`
- ETH `+0.00000587`
- ADA `+0.00000686`
- BNB `+0.00002755`
- DOT `+0.00003326`
- SOL `+0.00002076`
- XRP `+0.00001290`

These sum to a positive value, not a negative one.

So total PnL and per-symbol PnL are not coming from the same realized-trade dataset.

This is another hard truth mismatch.

---

### Problem 3 — Winrate mismatch across modules
Same timestamp block shows:
- Summary WR: `51.5%`
- Execution engine WR: `45.83%`

These may only differ if they intentionally represent different windows or different subsets.
If so, the UI/logs must explicitly label them.

Right now they look like the same KPI, which is misleading.

---

### Problem 4 — Exit reporting is still not truthful enough
Logs show:
- `TP=0 SL=0 trail=0 timeout=0`
- `micro=8`
- `partial=(25,0,0)`
- `scratch=80`

And:
- `winners: SCRATCH_EXIT=15 PARTIAL_TP_25=5`

This means:
- most closes are still scratch/partial/micro based
- the bot still behaves like a micro-harvest/defensive exit engine
- but summary metrics do not clearly explain how these exits contribute to total realized PnL

The exit layer is still under-instrumented.

---

### Problem 5 — Health is still suspiciously near zero despite decent WR values
Current state:
- Health = `0.004 [BAD]`
- some regimes show WR 45–70%
- some EV values slightly positive/negative
- features around 46%
- calibration p looks reasonable: `p=50.1% WR=51.5% odchylka 1.4pp dobre`

This suggests health formula may be:
- too harsh,
- dependent on convergence only,
- or using different inputs than the displayed WR/EV metrics.

Maybe not a bug, but at minimum it is poorly grounded and potentially misleading.

---

## Main diagnosis

The system is now in a half-fixed state:

- Learning Monitor hydration: improved
- Global metrics truth/reconciliation: still broken

The highest priority is now:

# Build one canonical realized-trade accounting layer and force every user-facing metric to use it.

---

# REQUIRED PATCH — V10.13x

Implement the following focused fixes.

---

## Fix 1 — Canonical Stats Source of Truth

Create one canonical stats aggregation path for realized closed trades.

This canonical dataset must be the only source for:
- total trade count
- win count
- loss count
- flat count
- winrate
- net pnl
- gross pnl
- fees
- slippage
- profit factor
- expectancy
- per-symbol stats
- per-regime stats
- exit-type contribution

### Requirements
- use only closed realized trades
- use one canonical outcome policy
- do not mix:
  - live candidates
  - historical legacy totals
  - Firebase legacy counters
  - batch-compressed aggregates
  - in-memory rolling counters
unless clearly labeled and intentionally separated

### Add one helper
Example shape:

```python
compute_canonical_trade_stats(trades) -> dict
```

It should return a full structure used everywhere else.

---

## Fix 2 — Repair summary header line

This line is currently invalid:

```text
Obchody    124  (OK 3173  X 2993  ~ 3758)
```

Replace it with something truthful.

### Required format
If the canonical set contains 124 closed trades:

```text
Obchody    124  (OK 64  X 52  ~ 8)
```

Where:
- `OK` = realized wins
- `X` = realized losses
- `~` = realized flats

And:
`OK + X + ~ == Obchody`

Always.

Add assert/log protection if not true.

---

## Fix 3 — Repair total PnL vs per-symbol PnL reconciliation

The following must always reconcile:

```text
sum(symbol_net_pnl) == total_net_pnl
```

within a tiny tolerance.

### Add periodic reconciliation log
```text
[V10.13x RECON]
trades_total=124
wins=64 losses=52 flats=8
total_net_pnl=-0.00011821
sum_symbol_net_pnl=-0.00011820
sum_regime_net_pnl=-0.00011821
status=OK
```

If mismatch:
```text
[V10.13x RECON] status=MISMATCH field=sum_symbol_net_pnl delta=0.000143
```

If mismatch exists:
- freeze adaptive updates
- mark UI/log status as degraded
- do not silently continue learning from inconsistent state

---

## Fix 4 — Label every WR with its scope

Current logs show:
- summary WR 51.5%
- execution WR 45.83%

This is ambiguous.

Every WR must include scope in code and log label.

### Required examples
- `WR_closed_alltime`
- `WR_execution_window`
- `WR_learning_monitor`
- `WR_last_24`
- `WR_ex_timeout`
- `WR_canonical`

The user-facing terminal should display labels that are human-readable, for example:

```text
Winrate (all closed, bez timeoutu)   51.5%
WR engine (rolling window)           45.8%
```

No two different WRs may share the same unlabeled `WR`.

---

## Fix 5 — Exit truth instrumentation

Current exit logs still show only counts.
You must extend them into economic attribution.

For each exit type track:
- count
- gross pnl total
- fee total
- slippage total
- net pnl total
- avg net pnl
- win/loss/flat counts
- contribution to total pnl %

### Required output example
```text
[V10.13x EXIT_ATTR]
SCRATCH_EXIT   count=80  net=+0.00004120 avg=+0.00000052 wins=15 losses=22 flats=43 pct_total=34.9%
PARTIAL_TP_25  count=25  net=+0.00005810 avg=+0.00000232 wins=5 losses=0 flats=20 pct_total=49.1%
MICRO_TP       count=8   net=+0.00000680 avg=+0.00000085 wins=8 losses=0 flats=0 pct_total=5.8%
FULL_LOSS      count=... net=...
```

This should explain where the actual edge comes from.

---

## Fix 6 — Define canonical outcome policy

Write explicit code comments and enforce one classification policy.

### Required policy
For each closed trade determine:
- `WIN` if net_pnl > +eps
- `LOSS` if net_pnl < -eps
- `FLAT` otherwise

Where `eps` is a tiny explicit threshold.

Do not classify by exit label alone.
Examples:
- `SCRATCH_EXIT` can be WIN, LOSS, or FLAT depending on net pnl
- `PARTIAL_TP_25` is not automatically a full-trade win if final realized net is <= 0
- `MICRO_TP` must still be evaluated by final net pnl

All summary stats must use this same policy.

---

## Fix 7 — Health formula grounding

Health currently prints:
- `health=0.004 [BAD]`

even though:
- calibration looks acceptable
- features have non-zero WR
- some regimes have moderate WR

This may be valid, but it is not transparent.

### Required action
Refactor health output to expose components:

```text
[V10.13x HEALTH]
edge_component=0.08
convergence_component=0.12
calibration_component=0.74
stability_component=0.21
penalty_component=-0.91
final=0.004
status=BAD
```

If health is near zero, user must know why.

Do not hide it inside one opaque scalar.

---

## Fix 8 — Remove duplicate learning diagnostics spam

Current logs print the same learning diagnostic block multiple times in the same cycle:
- `[!] LEARNING: health=0.0040 [BAD]`
- repeated again
- then repeated again inside snapshot

That creates noise and makes debugging harder.

### Required fix
Per cycle:
- print one compact human-readable learning summary
- print one machine snapshot block only if needed
- avoid duplicate repeated identical messages

---

## Fix 9 — Preserve good parts already working

Do not break the improvements that are already visible:
- hydrated pair counts
- non-zero feature WR
- per-regime WR display
- negative EV rejection
- loss cluster blocking
- bootstrap diagnostics
- canonical direction logging where already correct

This patch is about reconciliation and truth, not another architectural rewrite.

---

# VALIDATION REQUIREMENTS

After patching, demonstrate:

## Validation A — Header consistency
Show:
- `Obchody`
- `OK`
- `X`
- `~`
and prove they sum exactly.

## Validation B — PnL consistency
Show:
- total net pnl
- sum of per-symbol pnl
- sum of per-regime pnl
all match within tolerance.

## Validation C — WR scope clarity
Show at least 3 WR metrics with explicit labels and explain their dataset/window.

## Validation D — Exit attribution truth
Show exit types with real net contributions, not only counts.

## Validation E — Health transparency
Show health decomposition so that a near-zero health score is explainable.

---

# DELIVERABLE FORMAT

Return:

## 1. Root-cause analysis
Very short and precise.

## 2. Files changed
List all touched files.

## 3. Code patches
Provide complete updated functions or full files where needed.

## 4. Validation output
Show before/after examples.

## 5. Remaining risks
Be explicit.

---

# CRITICAL NOTE

Do not be fooled by superficial logs like:
- high PF
- positive expectancy
- “FIRE” streak
- decent regime WR

The system is only trustworthy if:
- trade counts reconcile,
- PnL reconciles,
- WR labels are scoped,
- exit contribution is economically grounded,
- and health is explainable.

Correctness first. Always.
