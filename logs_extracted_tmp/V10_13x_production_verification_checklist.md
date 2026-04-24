# V10.13x Production Verification Checklist

## Purpose

This checklist verifies that **V10.13x metrics reconciliation is truly running in the live process**, not just committed in Git or described in deployment notes.

It is focused on one question:

> Is the running bot process actually emitting the new canonical metrics and reconciliation outputs?

---

## Success Criteria

V10.13x should be considered **really live** only if all of the following are true:

1. The running Python process is using the expected code version.
2. The live logs contain the **new V10.13x markers**.
3. The live logs **do not** contain the old broken summary patterns.
4. Trade counts reconcile mathematically.
5. PnL reconciliation logs appear and show `status=OK`.
6. Health output shows decomposed components, not just opaque BAD/GOOD labels.
7. Learning diagnostics are not duplicated multiple times per cycle.

---

## What Must Be Visible In Live Logs

### Required new markers

You should see these in the active runtime logs:

- `[V10.13x RECON]`
- `WR_canonical`
- `[V10.13x HEALTH]`
- exit attribution with economic values such as:
  - `net_pnl=`
  - `avg_pnl=`
  - `pct_of_total=`

### Old patterns that should disappear

These indicate old or partially deployed output is still running:

- `Obchody    124  (OK 3173  X 2993  ~ 3758)`
- repeated `[!] LEARNING:` block multiple times in the same cycle
- unlabeled raw `Winrate` without clear scope
- exit summary with only counts and no economic contribution
- inconsistent dashboard totals where sub-sums exceed the displayed total

---

## Step 1 — Confirm the Running Process

Run:

```bash
ps -fp $(pgrep -f "python.*start.py" | head -n 1)
```

If that does not find the process, try:

```bash
pgrep -af "python|cryptomaster|start.py|bot2"
```

Record:

- PID
- command line
- working directory
- Python executable path

Also verify the current checked-out commit:

```bash
git rev-parse --short HEAD
git log -1 --oneline
```

Expected:

- commit matches the deployment target
- running process points to the same project directory you just updated

---

## Step 2 — Verify V10.13x Code Exists On Disk

Run:

```bash
grep -R "compute_canonical_trade_stats" -n src/
grep -R "lm_health_components" -n src/
grep -R "V10.13x RECON" -n .
grep -R "WR_canonical" -n .
grep -R "V10.13x HEALTH" -n .
```

Expected:

- each symbol is found exactly where intended
- no missing function definitions

If any of these return nothing, the deployed code is incomplete.

---

## Step 3 — Verify The Active Process Emits New Log Markers

For systemd / journalctl:

```bash
journalctl -u cryptomaster -n 500 --no-pager | grep -E "V10.13x RECON|WR_canonical|V10.13x HEALTH|net_pnl=|avg_pnl=|pct_of_total="
```

If process logs are not under that unit, use:

```bash
journalctl -n 500 --no-pager | grep -E "V10.13x RECON|WR_canonical|V10.13x HEALTH|net_pnl=|avg_pnl=|pct_of_total="
```

Expected:

- at least one `[V10.13x RECON]`
- at least one `[V10.13x HEALTH]`
- at least one `WR_canonical`
- at least one exit attribution line that includes actual economics

If none of these appear, then the live process is **not** actually running the new output path.

---

## Step 4 — Check That Old Broken Output Is Gone

Run:

```bash
journalctl -u cryptomaster -n 1000 --no-pager | grep -E "Obchody    .*OK .*X .*~|\[!\] LEARNING:|Winrate     |Uzavreni       TP 0%  SL 0%  trail 0%  timeout 0%"
```

Investigate specifically whether you still see patterns like:

```text
Obchody    124  (OK 3173  X 2993  ~ 3758)
```

If this appears, deployment is either:

- stale
- partial
- or the old dashboard path is still active in parallel

---

## Step 5 — Validate Canonical Trade Count Reconciliation

The following must hold exactly:

```text
wins + losses + flats == trades_total
```

Expected dashboard style:

```text
Obchody    142  (OK 64  X 52  ~ 26)
```

Validation command if reconciliation is logged as structured JSON:

```bash
journalctl -u cryptomaster -n 1000 --no-pager | grep "V10.13x RECON"
```

Expected fields:

- `trades_total`
- `wins`
- `losses`
- `flats`
- reconciliation `status`

Pass condition:

- totals match exactly
- `status=OK`

Fail condition:

- sums do not match
- missing fields
- no reconciliation line emitted

---

## Step 6 — Validate PnL Reconciliation

The canonical system must satisfy:

```text
total_net_pnl == sum(per_symbol_net_pnl) == sum(per_regime_net_pnl) == sum(per_exit_type_net_pnl)
```

Use the reconciliation logs:

```bash
journalctl -u cryptomaster -n 2000 --no-pager | grep "V10.13x RECON"
```

Expected payload should include something equivalent to:

- `total_net_pnl`
- `sum_symbol_net_pnl`
- `sum_regime_net_pnl`
- `status=OK`

Pass condition:

- differences are within rounding tolerance only

Fail condition:

- total PnL is negative while all symbol PnLs are positive
- symbol sum or regime sum diverges from total

---

## Step 7 — Validate Exit Attribution Is Economic, Not Just Count-Based

The new system should show **economic contribution**, not only exit counts.

Look for output like:

```text
[V10.13x EXIT_ATTR] SCRATCH_EXIT count=96 net=+0.000412 avg=+0.0000043 wins=32 losses=48 flats=16 pct_total=67.6%
```

Run:

```bash
journalctl -u cryptomaster -n 2000 --no-pager | grep -E "EXIT_ATTR|SCRATCH_EXIT|PARTIAL_TP|MICRO_TP|EARLY_STOP|net=|avg="
```

Questions to answer from logs:

- Is `SCRATCH_EXIT` actually profitable or loss-making?
- Which exit type contributes most of net PnL?
- Which exit type inflates WR but adds no money?
- Which exit type has the highest average PnL?

Pass condition:

- each major exit type shows `count`, `net_pnl`, `avg_pnl`, and share of total

Fail condition:

- only counts are shown
- no ability to connect exits to economics

---

## Step 8 — Validate Health Decomposition

The health system should no longer be opaque.

Required shape:

```text
[V10.13x HEALTH] final=... edge=... conv=... calib=... stab=... penalty=...
```

Run:

```bash
journalctl -u cryptomaster -n 1000 --no-pager | grep "V10.13x HEALTH"
```

You should be able to answer:

- Is health low because of weak edge?
- because convergence is missing?
- because calibration is broken?
- because stability degraded?
- because a bootstrap or sparsity penalty is active?

Pass condition:

- final score plus all components visible

Fail condition:

- only `Health: 0.004 [BAD]` with no explanation

---

## Step 9 — Check For Duplicate Diagnostic Spam

A healthy deployment should print **one coherent learning summary per cycle**, not multiple repeated blocks.

Run:

```bash
journalctl -u cryptomaster -n 1000 --no-pager | grep "\[!\] LEARNING:"
```

Then visually inspect whether the same learning block repeats several times in the same timestamp window.

Pass condition:

- one summary per cycle
- atomic machine logs can still exist, but human-facing spam should be gone

Fail condition:

- repeated identical learning blocks in one 10-second window

---

## Step 10 — Check Runtime Consistency For 15 Minutes

Monitor live for 15 minutes:

```bash
journalctl -u cryptomaster -f
```

During that time verify:

- reconciliation logs appear on schedule
- no old broken dashboard block returns
- no impossible totals appear
- exit attribution stays economic
- health decomposition stays visible
- no sudden Firebase quota spikes

---

## Expected Good Output

### Good reconciliation example

```text
[V10.13x RECON] trades_total=142 wins=64 losses=52 flats=26 total_net_pnl=-0.000118 sum_symbol_net_pnl=-0.000118 sum_regime_net_pnl=-0.000118 status=OK
```

### Good health example

```text
[V10.13x HEALTH] final=0.236 status=WEAK edge=0.081 conv=0.420 calib=0.301 stab=0.142 penalty=-0.250
```

### Good exit attribution example

```text
[V10.13x EXIT_ATTR] SCRATCH_EXIT count=96 wins=32 losses=48 flats=16 net=-0.000071 avg=-0.00000074 pct_total=67.6%
[V10.13x EXIT_ATTR] PARTIAL_TP_25 count=21 wins=18 losses=2 flats=1 net=+0.000093 avg=+0.00000443 pct_total=14.8%
```

---

## Expected Bad Output

These indicate V10.13x is not really verified yet:

```text
Obchody    124  (OK 3173  X 2993  ~ 3758)
Health: 0.004 [BAD]
Uzavreni       TP 0%  SL 0%  trail 0%  timeout 0%
```

Why bad:

- first line is mathematically impossible
- second line is opaque
- third line contradicts other exit summaries

---

## Interpretation Guide

### If the code exists but markers do not appear
Most likely causes:

- old process still running
- service did not restart correctly
- alternate entrypoint is active
- print/log path is behind a condition that is never reached

### If markers appear but old broken output also appears
Most likely causes:

- both old and new dashboard renderers are active
- partial refactor only replaced one metrics path
- one module still reads legacy aggregates

### If reconciliation status is not OK
Most likely causes:

- more than one metrics accumulator still writes state
- dashboard is mixing historical and session-level stats
- exit classification path differs from main metrics path

---

## Production Go / No-Go Decision

### GO
Production verification passes only if:

- live process confirmed
- `[V10.13x RECON]` visible
- `[V10.13x HEALTH]` visible
- `WR_canonical` visible
- exit attribution includes money contribution
- no impossible dashboard totals
- no duplicate learning spam

### NO-GO
Do **not** treat V10.13x as finished if any of these remain true:

- impossible totals still shown
- health is still opaque
- exit attribution still count-only
- old logs dominate output
- reconciliation logs absent

---

## Recommended Next Move After Verification

If verification passes:

1. let the bot collect 50–100 fresh closed trades
2. inspect which exit types actually contribute positive net PnL
3. compare health components over time
4. then decide whether to tune exits or learning gates

If verification fails:

1. do not tune strategy yet
2. fix deployment/runtime mismatch first
3. remove remaining legacy summary paths
4. repeat this checklist

---

## Quick Command Bundle

```bash
git rev-parse --short HEAD
git log -1 --oneline
pgrep -af "python|cryptomaster|start.py|bot2"
grep -R "compute_canonical_trade_stats" -n src/
grep -R "lm_health_components" -n src/
grep -R "V10.13x RECON" -n .
grep -R "WR_canonical" -n .
grep -R "V10.13x HEALTH" -n .
journalctl -u cryptomaster -n 1000 --no-pager | grep -E "V10.13x RECON|WR_canonical|V10.13x HEALTH|EXIT_ATTR|net_pnl=|avg_pnl=|pct_of_total="
journalctl -u cryptomaster -n 1000 --no-pager | grep -E "Obchody    .*OK .*X .*~|\[!\] LEARNING:|Winrate     |Uzavreni       TP 0%  SL 0%  trail 0%  timeout 0%"
```

---

## Final Rule

Do not trust deployment notes.
Do not trust Git state alone.
Do not trust restart messages alone.

**Trust only the output of the actually running process.**
