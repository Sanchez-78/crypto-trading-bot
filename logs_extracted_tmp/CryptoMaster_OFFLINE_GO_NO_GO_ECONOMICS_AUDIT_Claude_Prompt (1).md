# Claude Code Prompt — OFFLINE GO/NO-GO Economics Audit (Runtime Freeze)

## Purpose

Stop runtime patching and determine whether CryptoMaster has any defensible trading edge after fees/slippage.

This is an **offline audit only**. Do not change production trading behavior, thresholds, routing, learning, TP/SL, shadow buckets, Firebase/Android contracts, or restart/deploy the service.

## Trusted safe code state

```text
HEAD: 735ba35 Revert P1.1AP-L shadow sampler experiment
Baseline server-safe tests: 854 passed, 0 failed, 0 warnings
Preserved fixes: P1.1AP-J2, K, I/I2, H2, test hygiene cleanup
Runtime patch freeze: ACTIVE
```

Before audit, verify:

```bash
cd /opt/CryptoMaster_srv
git log --oneline -10
git status --short
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Do not commit or modify:
```text
src/
tests/
data/paper_open_positions.json
.env*
firebase/app schemas
```

## New evidence requiring audit

At 2026-05-22 13:01 UTC, dashboard/model state reports:

```text
Canonical trades: 100 = 11 wins, 4 losses, 85 neutral/other
WR_canonical: 73.3% (11 / (11+4) only)
Net closed PnL: -0.00023955
Profit Factor: 0.49x
Learning health: 0.0000 BAD
LM trades: 200
Last trade: 616h 29m ago
Execution engine: Positions=0, Exposure=0, WR=0.00%, Edge=0.00000
```

Exit attribution:

```text
PARTIAL_TP_25       8   net +0.00005131
MICRO_TP            4   net +0.00000556
TIMEOUT_FLAT        2   net -0.00000788
replaced            3   net -0.00003500
TIMEOUT_LOSS        2   net -0.00003975
SCRATCH_EXIT       47   net -0.00009236
STAGNATION_EXIT    34   net -0.00012143
```

Critical interpretation to verify mathematically:

```text
SCRATCH_EXIT + STAGNATION_EXIT = 81/100 trades
combined net = -0.00021379
combined share of total net loss ≈ 89.25%
```

Per-symbol net totals:

```text
BTC -0.00004517 despite displayed WR 100%
ETH -0.00003778 despite displayed WR 100%
ADA -0.00004278
BNB -0.00004700 despite displayed WR 100%
DOT -0.00007885
SOL -0.00000038 despite displayed WR 100%
XRP +0.00001241 only positive symbol
Sum = -0.00023955
```

Snapshot inconsistencies needing classification, not runtime fixes:

```text
- Display says WR 73.3% while total PnL and PF are negative.
- Display says Expectancy +0.00000146 while total closed PnL is negative.
- Status prints "TRENINK (zisk > 0)" while Zisk is negative.
- learning snapshot says mode="LIVE" while screen says TRENINK and execution positions/exposure are zero.
- completed_trades=7707 versus canonical=100 versus LM=200: identify semantic scopes.
```

## Audit objectives

Produce a single GO/NO-GO report answering:

1. Does any current strategy slice show positive net expectancy after fees/slippage?
2. Is any apparent win rate merely an artifact of excluding scratch/stagnation/flat outcomes?
3. Which exit types cause losses?
4. Which symbol/regime/direction combinations are genuinely positive, with enough samples?
5. Are dashboard fields mathematically consistent with canonical data?
6. Is there any credible justification for real trading? Default answer is NO until proven.

## Data collection — read-only

Create audit outputs only under:

```text
data/research/offline_go_no_go_2026-05-22/
```

Do not modify live state.

Export available data, using existing read-only scripts if present; otherwise write new analysis scripts only under `scripts/research/` or the audit output folder and do not wire them into runtime.

Search for current data sources:

```bash
cd /opt/CryptoMaster_srv
find data -maxdepth 3 -type f | sort | sed -n '1,160p'
find scripts -maxdepth 3 -type f | sort | sed -n '1,160p'
grep -R "canonical_closed_trades\|SCRATCH_EXIT\|STAGNATION_EXIT\|profit.factor\|PAPER_TRAIN_ECON_ATTRIB\|LEARNING_UPDATE" -n src scripts tests | head -240
```

Export relevant journal logs for the most useful windows:

```bash
mkdir -p data/research/offline_go_no_go_2026-05-22

sudo journalctl -u cryptomaster --since "7 days ago" --no-pager -o cat \
  > data/research/offline_go_no_go_2026-05-22/journal_7d.log

sudo journalctl -u cryptomaster --since "24 hours ago" --no-pager -o cat \
  > data/research/offline_go_no_go_2026-05-22/journal_24h.log
```

If Firebase/state exports already exist locally, use them read-only. Do not increase Firebase quota usage without first documenting the minimal export query and asking before execution.

## Mandatory datasets

Separate these populations; never mix them:

```text
A. canonical closed trades used by PF/economic health
B. current paper C_WEAK_EV_TRAIN closes
C. B_RECOVERY_READY diagnostic closes
D. D_NEG_EV_CONTROL shadow-only closes (must be excluded from canonical economics)
E. rejected candidates / ECON_BAD heartbeats / cost_edge_too_low counts
F. legacy model-state/dashboard values and their declared sources
```

## Mandatory calculations

For canonical data and, separately, for each eligible paper bucket:

```text
count total / decisive / neutral
wins / losses / flat / scratch / stagnation / timeout
net PnL after fees/slippage
gross win, gross loss, PF
expectancy using ALL outcomes
expectancy using decisive-only outcomes, clearly labelled non-decision metric
win rate using ALL outcomes
win rate decisive-only, clearly labelled
fees/slippage share of gross movement
exit-reason contribution to total PnL
symbol × regime × side contribution
sample size and confidence caveats
```

### Sanity reconciliation

Prove or fail:

```text
sum(exit type net pnl) == reported net closed pnl
sum(symbol net pnl) == reported net closed pnl
PF equals gross_win / abs(gross_loss)
expectancy definition matches its displayed number
WR_canonical denominator is explicitly declared
completed_trades / LM / canonical count scopes are documented
```

Treat any mismatch as a dashboard/reporting defect for later backlog only; do not patch it during this audit.

## Evaluation rules

### Automatic NO-GO for real trading if any is true

```text
canonical PF <= 1.0
canonical net PnL <= 0
expectancy_all_outcomes <= 0
fewer than 100 clean comparable post-fix outcome samples
result dominated by one symbol, one regime, or tiny subgroup
metric definitions are unreconciled
D_NEG/legacy contamination cannot be separated confidently
```

### Candidate GO for a controlled future experiment only if all are true

```text
PF > 1.20 after fees/slippage on clean post-fix sample
net PnL > 0
expectancy_all_outcomes > 0
at least 100 comparable clean samples
positive result survives symbol/regime segmentation
out-of-sample/time-split remains positive
no hidden dependence on excluded scratch/stagnation losses
```

This GO is **not approval for real money**; it only permits design of one targeted paper validation.

## Required outputs

Create:

```text
data/research/offline_go_no_go_2026-05-22/GO_NO_GO_REPORT.md
data/research/offline_go_no_go_2026-05-22/canonical_summary.csv
data/research/offline_go_no_go_2026-05-22/exit_reason_summary.csv
data/research/offline_go_no_go_2026-05-22/symbol_regime_side_summary.csv
data/research/offline_go_no_go_2026-05-22/rejection_summary.csv
data/research/offline_go_no_go_2026-05-22/data_provenance.md
```

The report must begin with:

```text
VERDICT: GO or NO-GO
REAL TRADING: FORBIDDEN or NOT EVALUATED FOR ENABLEMENT
RUNTIME PATCH FREEZE: ACTIVE
```

Include:
- canonical economics table;
- paper bucket-separated economics;
- loss attribution;
- dashboard consistency findings;
- minimum evidence needed to reconsider NO-GO;
- exactly one recommended next step.

## No coding/commit rule

Do not implement runtime fixes during this audit.
Do not commit anything unless the user later requests committing audit artifacts only.
Do not restart production.
Do not enable real trading.

## Report back in chat

Return a concise summary:

```text
VERDICT:
WHY:
PF / net pnl / all-outcome expectancy:
Main loss source:
Dashboard inconsistencies:
Real trading status:
Next single action:
Files generated:
```
