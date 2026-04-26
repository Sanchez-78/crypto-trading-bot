# CryptoMaster V10.13u+7 — Exit Quality Stabilization Patch (Token-Safe)

## Current Production State

Safety consistency is now fixed.

Validated live:
- Runtime commit is real.
- Dashboard PF and Economic PF now match.
- Economic Health correctly reports BAD when PF < 1 and net PnL < 0.
- Conservative mode activates via `[ECON_SAFETY_BAD]`.
- EV-only hard rejection works for negative EV.

Do NOT modify:
- `canonical_metrics.py` PF parser unless tests fail.
- Economic Health source.
- Maturity oracle.
- Runtime version logic.
- Firebase quota recovery.
- EV-only negative EV rejection.

## Live Problem

The bot is still losing through exit quality, not through PF/maturity source drift.

Recent log proof:
```text
Economic: 0.340 [BAD]
PF: 0.76
[ECON_SAFETY_BAD] pf=0.76 net_pnl=-0.00053555 action=conservative_mode

[CLOSE_LOGIC_START] ADAUSDT reason=STAGNATION_EXIT
ADA BUY ... -0.000024 [STAGNATION_EXIT]
[V10.13w LM_CLOSE] ... net=-0.00002498 outcome=LOSS

[CLOSE_LOGIC_START] SOLUSDT reason=STAGNATION_EXIT
SOL SELL ... -0.000005 [STAGNATION_EXIT]
[V10.13w LM_CLOSE] ... net=-0.00000493 outcome=LOSS

STAGNATION_EXIT 68 net -0.00022750
SCRATCH_EXIT 331 net -0.00071896
```

Main issue:
- `STAGNATION_EXIT` and `SCRATCH_EXIT` dominate loss leakage.
- Bot still opens `decision=TAKE` while Economic BAD/conservative.
- Positions appear to be closed too quickly as stagnation/scratch with fees/slippage turning tiny moves into losses.
- This is an exit/entry-quality problem, not a canonical metrics problem.

## Goal

Implement a minimal, safe patch that reduces churn and fee bleed from bad micro-exits while preserving the working safety layer.

## Required Changes

### 1. Add minimum profitable-hold guard before STAGNATION_EXIT

In exit logic, before allowing `STAGNATION_EXIT`, require:

```python
age_sec >= MIN_STAGNATION_EXIT_AGE_SEC
```

Default:
```python
MIN_STAGNATION_EXIT_AGE_SEC = 180
```

Exception:
Allow early exit only if one of these is true:
- hard SL hit
- hard risk guard / emergency exit
- toxic OFI/L2 hard block
- severe adverse move beyond configured threshold

Do not block TP, SL, emergency, or risk exits.

### 2. Add fee-aware stagnation decision

Before closing with `STAGNATION_EXIT`, compute:

```python
net_if_closed = gross_pnl - fees - slippage_estimate
```

If `net_if_closed < 0` and age is below minimum, do not close as stagnation. Continue holding or convert to managed wait.

Add log:
```text
[STAG_GUARD] HOLD symbol=... age=... net_if_closed=... reason=too_young_fee_negative
```

### 3. Conservative mode entry tightening

When Economic status is BAD or `[ECON_SAFETY_BAD]` active:

Do not increase trade frequency. Tighten entries.

Apply:
```python
if economic_status == "BAD":
    min_ev = max(current_min_ev, 0.04)
    min_score = max(current_min_score, 0.20)
    forced_explore_size_mult = min(current_mult, 0.30)
```

Optional hard rule:
- Disable forced explore if PF < 1.0 and net_pnl < 0, unless explicitly in diagnostic mode.

Log:
```text
[ECON_ENTRY_GUARD] conservative active pf=... min_ev=... min_score=... forced_mult=...
```

### 4. Per-symbol churn cooldown after STAGNATION_EXIT loss

When a symbol closes with `STAGNATION_EXIT` and net PnL < 0:
- Add cooldown for same symbol + same direction for 10 minutes.
- Do not block opposite direction if EV is strong.
- Do not block if emergency/manual mode.

Log:
```text
[CHURN_COOLDOWN] symbol=... direction=... reason=stagnation_loss cd=600s
```

### 5. Exit audit summary should show churn pressure

Add compact per-minute or per-cycle metrics:
```text
[EXIT_QUALITY] scratch_pct=... stag_pct=... fee_bleed=... churn_losses=... action=...
```

Do not spam every tick. Throttle to 60s.

## Acceptance Criteria

After restart and 10-30 minutes observation:

Must remain true:
- `Economic: BAD` while PF < 1.0.
- `PF:` equals dashboard Profit Factor.
- `REJECT_NEGATIVE_EV` still appears for negative EV.
- No `Traceback`.
- No missing `canonical_metrics`.

Expected improvement:
- Fewer immediate `STAGNATION_EXIT` losses.
- `[STAG_GUARD] HOLD` appears for too-young fee-negative exits.
- `[CHURN_COOLDOWN]` appears after stagnation loss.
- TAKE frequency drops during Economic BAD.
- STAGNATION_EXIT count does not keep rising every cycle.

## Validation Commands

```bash
sudo systemctl restart cryptomaster
sleep 10

sudo journalctl -u cryptomaster -n 1200 --no-pager | grep -E "RUNTIME_VERSION|ECON_SAFETY|ECON_ENTRY_GUARD|STAG_GUARD|CHURN_COOLDOWN|EXIT_QUALITY|STAGNATION_EXIT|SCRATCH_EXIT|decision=TAKE|REJECT_NEGATIVE_EV|Traceback|ERROR"
```

Live monitor:
```bash
sudo journalctl -u cryptomaster -f --no-pager | grep -E "ECON_SAFETY|ECON_ENTRY_GUARD|STAG_GUARD|CHURN_COOLDOWN|EXIT_QUALITY|STAGNATION_EXIT|decision=TAKE|REJECT_NEGATIVE_EV|Traceback|ERROR"
```

## Implementation Rules

- Make smallest possible patch.
- Prefer constants/env vars over hardcoded values:
  - `MIN_STAGNATION_EXIT_AGE_SEC=180`
  - `STAGNATION_CHURN_COOLDOWN_SEC=600`
  - `ECON_BAD_MIN_EV=0.04`
  - `ECON_BAD_MIN_SCORE=0.20`
  - `ECON_BAD_FORCED_EXPLORE_MULT=0.30`
- Add tests for:
  - young negative stagnation exit is held
  - SL/emergency still exits immediately
  - churn cooldown blocks same symbol+direction
  - Economic BAD tightens entry gate
- Do not refactor broad architecture.
- Do not change canonical PF logic.
- Do not change Firebase read/write cadence.

## Commit Message

```text
fix: reduce stagnation churn under economic bad mode
```
