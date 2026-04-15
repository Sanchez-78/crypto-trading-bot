# Claude Code Prompt — CryptoMaster V10.12d Controlled Unblock Patch

Apply an incremental patch to the existing Python crypto trading bot project.
Do NOT rewrite the whole project from scratch.
Do NOT simplify architecture.
Do NOT remove existing features unless strictly necessary to fix a bug.
Preserve current modules, imports, logging style, and integration points as much as possible.

Goal:
The bot is alive but over-filtered and produces no usable live signals.
Implement a controlled unblock patch for V10.12 that restores signal flow without turning the system into an unsafe spam trader.

Use Python 3.11+.
Keep code production-oriented.
Return full modified code for each changed file.
Also include a concise summary of what changed and why.

---

## CONTEXT

Observed behavior from logs:

- `0 zachyceno 0 po filtru`
- `0.0% projde filtrem`
- `NO_SIGNALS`
- watchdog self-heal triggered
- block reasons dominated by:
  - `TIMING`
  - `LOSS_CLUSTER`
  - `OFI_TOXIC`
  - `SKIP_SCORE`

Representative numbers from logs:
- `TIMING: 645`
- `LOSS_CLUSTER: 97`
- `OFI_TOXIC: 55`
- `SKIP_SCORE: 37`

Other important observed behavior:
- EV values often land around `0.03-0.05`
- old threshold appears effectively too high (`thr=0.100`)
- some candidates become TAKE after coherence reduction around `ev=0.030-0.045`
- timeout exits dominate (`timeout 99%`)
- bot can stay idle for 900s+ and still remain blocked by filters/cooldowns

This means:
- the bot is not signal-less
- the pipeline is too aggressive
- hard reject filters must be softened where reasonable
- unblock mode is required, but must be controlled and risk-limited

---

## REQUIRED OUTCOME

Implement **V10.12d Controlled Unblock** with these principles:

1. Keep protection logic, but stop killing almost all signals.
2. Convert selected hard rejects into soft penalties.
3. Introduce a bounded unblock mode when the bot is idle too long or sees no signals for too many cycles.
4. Use micro-size during unblock mode.
5. Add hard rate limits so unblock mode cannot overtrade.
6. Keep logging explicit so we can see why decisions were made.
7. Preserve existing strategy logic, learning logic, and execution architecture.

---

## PATCH REQUIREMENTS

### 1) Add controlled unblock mode detection

Add helper logic similar to:

```python
def is_unblock_mode(state) -> bool:
    return state.no_trades_seconds >= 900 or state.no_signals_cycles >= 40
```

Use actual existing state fields if names differ.
If these counters already exist under different names, reuse them instead of adding duplicates.

Unblock mode must be used by decision filters and position sizing.

---

### 2) Lower EV threshold to realistic values

Replace overly strict EV thresholding with:

- normal mode EV threshold: `0.025`
- unblock mode EV threshold: `0.015`

Implement helper:

```python
def current_ev_threshold(state) -> float:
    return 0.015 if is_unblock_mode(state) else 0.025
```

Use the project’s actual naming conventions and wiring.

Important:
- do not fully remove EV gating
- keep EV as part of selection
- just make it realistic to current signal quality

---

### 3) Lower score threshold in unblock mode

Implement:

- normal score threshold: `0.18`
- unblock mode score threshold: `0.12`

Helper:

```python
def current_score_threshold(state) -> float:
    return 0.12 if is_unblock_mode(state) else 0.18
```

Keep score gating active.
Do not delete score logic.

---

### 4) Replace hard TIMING reject with graded timing penalty

Current timing behavior is too aggressive and is the main blocker.

Replace binary timing rejection with a graded penalty model:

```python
def timing_penalty(candle_progress: float, atr_pct: float) -> tuple[float, bool]:
    late_hard = 0.88 if atr_pct < 0.012 else 0.93

    if candle_progress <= 0.70:
        return 1.00, False
    if candle_progress <= 0.82:
        return 0.92, False
    if candle_progress <= late_hard:
        return 0.80, False
    return 0.0, True
```

Apply it to EV and score:
- if hard late: reject with TIMING
- otherwise multiply EV and score by timing penalty

If the project already has adaptive ATR timing logic, integrate into that structure rather than duplicating it.

Log clearly:
- raw candle progress
- timing multiplier
- whether hard timing reject happened

---

### 5) Make LOSS_CLUSTER cooldown adaptive and shorter

Current cooldown around ~760 seconds is too restrictive.

Implement adaptive cooldown roughly like:

```python
def cluster_cooldown_seconds(regime: str, loss_streak: int, symbol_health: float, state) -> int:
    base = {
        "BULL_TREND": 180,
        "BEAR_TREND": 240,
        "RANGING": 300,
    }.get(regime, 240)

    if loss_streak >= 3:
        base += 120
    if symbol_health < 0.45:
        base += 120

    base = min(base, 420)

    if state.no_trades_seconds >= 900:
        base = min(base, 120)

    return base
```

Requirements:
- if the bot is critically idle, cooldown must shrink
- preserve cluster/loss protection
- use actual project variables if names differ
- do not keep static long lockouts in idle mode

Log:
- final cooldown chosen
- why it was lengthened or shortened

---

### 6) Convert OFI_TOXIC from mostly hard reject into mostly penalty

Current OFI filter is too destructive.

Implement softer OFI handling:

```python
def apply_ofi_gate(side: str, flow: float, spread_pct: float, score: float, size_mult: float):
    against = (side == "BUY" and flow < 0) or (side == "SELL" and flow > 0)
    if not against:
        return score, size_mult, False

    mag = abs(flow)

    if mag >= 1.20 and spread_pct > 0.015:
        return score, size_mult, True
    if mag >= 0.95:
        return score * 0.78, size_mult * 0.50, False
    if mag >= 0.70:
        return score * 0.88, size_mult * 0.75, False

    return score, size_mult, False
```

Behavior:
- only extreme adverse OFI + bad spread remains hard reject
- otherwise OFI becomes score penalty + size penalty

Also:
- if project already has OFI soft penalty partially implemented, consolidate and standardize it
- avoid duplicate competing OFI branches

Log:
- OFI flow
- whether adverse
- score multiplier
- size multiplier
- hard reject or soft penalty

---

### 7) Add unblock size multiplier

During unblock mode, keep sizes intentionally small.

Implement:

```python
def unblock_size_multiplier(state) -> float:
    if state.no_trades_seconds >= 900:
        return 0.25
    if state.no_signals_cycles >= 40:
        return 0.35
    return 1.0
```

Final position size should incorporate:
- existing base size
- existing EV / risk / bandit / regime adjustments
- OFI size penalty
- unblock size multiplier

Important:
- do not bypass existing max position / exposure caps
- do not bypass risk engine
- unblock only reduces size, never expands it

---

### 8) Add hard rate limits for unblock mode

Unblock mode must be bounded.

Implement:

- max unblock trades per hour = `6`
- max unblock open positions = `2`

Behavior:
- if unblock mode is active and the bot already opened 6 unblock trades in last hour -> reject new unblock entries
- if unblock mode is active and there are already 2 open positions -> reject new unblock entries

If the project tracks trades differently, adapt to existing storage.

Suggested helpers:

```python
MAX_UNBLOCK_TRADES_PER_HOUR = 6
MAX_UNBLOCK_POSITIONS = 2
```

And guard in entry decision:
- `UNBLOCK_RATE_LIMIT`
- `UNBLOCK_POS_LIMIT`

Must be clearly logged.

---

### 9) Improve timeout-heavy exit behavior for unblock mode

Observed timeout dominance is unhealthy.
Do not redesign the full exit engine, but improve unblock-mode exits to be shorter and more responsive.

Use approximately:

- normal TP ATR = existing default or `1.2`
- normal SL ATR = existing default or `0.8`

For unblock mode:
- TP ATR = `0.9`
- SL ATR = `0.7`
- timeout seconds = `240`
- enable trailing
- trail trigger around `0.8R`
- trail lock around `0.2R`

Requirements:
- only apply special exit tuning in unblock mode
- preserve normal mode behavior unless needed for compatibility
- do not break RR validation; ensure resulting RR remains valid or adapt the validator safely

If project architecture separates signal generation and risk/execution:
- implement unblock exit profile in the correct layer
- do not hardcode everywhere

---

### 10) Preserve and improve decision logging

This patch is for diagnostics as much as for behavior.

Wherever the bot decides TAKE or SKIP, include clear structured log info for:
- unblock mode on/off
- raw EV
- adjusted EV
- raw score
- adjusted score
- timing multiplier
- OFI multiplier
- size multiplier
- current EV threshold
- current score threshold
- cooldown chosen
- final decision reason

Avoid noisy duplicate logs, but ensure one compact decision log line contains the full adjusted view.

Example style:

```python
decision=TAKE ev=0.050->0.031 score=0.201->0.176 timing=0.80 ofi_size=0.75 ub=0.25 thr_ev=0.015 thr_sc=0.12
```

Use project’s current logging style.

---

## INTEGRATION RULES

1. Inspect the existing code and patch the actual relevant modules.
2. Reuse existing state objects, decision pipeline, risk logic, cooldown tracking, and logging infra.
3. Do not create parallel unused helper systems.
4. If names differ from this prompt, adapt to the real code.
5. If a function already exists with similar purpose, modify it rather than duplicating.
6. Preserve backward compatibility with the rest of the bot.
7. Avoid magic duplication of constants; place new thresholds/config in the project’s existing config/constants location when possible.

---

## SAFETY RULES

Do NOT:
- remove risk guards
- remove RR validation
- remove spread checks
- disable cluster protection entirely
- disable OFI entirely
- allow unlimited trades during unblock
- bypass exposure limits
- bypass cooldowns completely

Do:
- soften the worst blockers
- keep bounded defensive behavior
- keep the bot capable of actually taking trades again

---

## EXPECTED DECISION BEHAVIOR AFTER PATCH

After patch:
- bot should no longer sit at `0 po filtru`
- some signals should pass in controlled fashion
- `TIMING` should stop being the dominant hard killer
- `OFI_TOXIC` should become mostly a penalty, not a kill switch
- `LOSS_CLUSTER` should stop freezing symbols for too long during idle conditions
- unblock trades should be smaller and rate-limited
- logs should show clearly how raw EV/score were adjusted to the final decision

---

## IMPLEMENTATION TARGET

Find and patch the real files responsible for:
- decision gating
- EV thresholding
- score thresholding
- timing filtering
- OFI filter
- cluster/loss cooldowns
- position sizing
- exit profile / timeout / trailing logic
- state/watchdog idle counters if needed
- decision logging

Return:
1. full code for every changed file
2. short explanation per file
3. final summary of behavior changes
4. any assumptions made where the codebase naming differs

Do not return pseudo-code only.
Return real modified Python code.
