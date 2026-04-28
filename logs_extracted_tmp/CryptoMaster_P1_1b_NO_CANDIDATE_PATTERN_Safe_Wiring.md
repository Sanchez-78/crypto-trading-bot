# CryptoMaster P1.1b Correction — NO_CANDIDATE_PATTERN Safe Wiring

**Purpose:** wire paper exploration into `NO_CANDIDATE_PATTERN` production path without contaminating learning with fake direction.

## Context

P1.1 is enabled in production:

```text
[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True
```

Rejects exist, but no paper exploration logs:

```text
NO_CANDIDATE_PATTERN
REJECT_NEGATIVE_EV
REJECT_ECON_BAD_ENTRY
ECON_BAD_ENTRY_RETURN_TRACE
```

Missing:

```text
PAPER_EXPLORE_ENTRY
PAPER_EXPLORE_SKIP
PAPER_ENTRY
```

## Critical correction

Do **not** hardcode `BUY` for `NO_CANDIDATE_PATTERN`.

Reason: if no valid side/action exists, opening paper trades with fake BUY direction contaminates training data.

Minimum acceptable result:

```text
[PAPER_EXPLORE_SKIP] reason=no_side symbol=...
```

This proves the hook is reached without creating bad data.

## Locate real production path

Run:

```bash
grep -R "NO_CANDIDATE_PATTERN\|edge generation failed\|forced signal failed" -n src bot2 start.py
grep -R "on_price(" -n src bot2 start.py | head -100
```

Wire only the actual code path that emits:

```text
on_price(SYMBOL): NO_CANDIDATE_PATTERN
```

## Safe logic

If side/action is safely inferable from existing variables:

```python
maybe_open_paper_exploration_from_reject(
    signal={
        "symbol": symbol,
        "side": side,
        "action": side,
        "ev": 0.0,
        "score": 0.0,
        "p": 0.0,
        "coh": 0.0,
        "af": 0.0,
        "reject_type": "NO_CANDIDATE_PATTERN",
    },
    ctx={"price": price, "last_price": price},
    original_decision="NO_CANDIDATE_PATTERN",
    reject_reason="no_candidate_pattern",
    current_price=price,
)
```

If side/action is not safely inferable:

```python
log.info(
    "[PAPER_EXPLORE_SKIP] reason=no_side symbol=%s "
    "original_decision=NO_CANDIDATE_PATTERN reject_reason=no_candidate_pattern",
    symbol,
)
```

## Rules

```text
Do not default to BUY.
Do not default to SELL.
Do not infer direction from random fallback.
Use only existing trusted side/action context.
If no trusted side exists, log skip.
No real orders.
No live gate changes.
No replay_train.
No Firebase tick writes.
```

## Active hooks required for P1.1b

Wire all three:

```text
1. ECON_BAD_ENTRY_RETURN_TRACE path
2. REJECT_NEGATIVE_EV path
3. NO_CANDIDATE_PATTERN path
```

## Validation

```bash
python -m py_compile   src/services/paper_exploration.py   src/services/paper_trade_executor.py   src/services/trade_executor.py   src/services/realtime_decision_engine.py

python -m pytest   tests/test_paper_mode.py   tests/test_p0_3_paper_integration.py   tests/test_p1_paper_exploration.py   -v

git diff --check
```

## Commit

```bash
git add src tests
git commit -m "P1.1b: wire paper exploration into active production reject hooks"
git push origin main
```

## Production validation

```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 60

sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_EXPLORE_ENTRY|PAPER_EXPLORE_SKIP|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|REJECT_|NO_CANDIDATE_PATTERN|Traceback|ERROR"
```

## Success criteria

Minimum success:

```text
[PAPER_EXPLORE_SKIP] reason=...
```

Best success:

```text
[PAPER_EXPLORE_ENTRY] bucket=...
[PAPER_ENTRY] ...
```

If no `PAPER_EXPLORE_SKIP` and no `PAPER_EXPLORE_ENTRY`, P1.1b is still not wired into production.
