# CryptoMaster P1.1b — Wire Paper Exploration Into Active Reject Hooks

**Problem:** P1.1 is deployed and enabled, but no paper exploration logs appear.

## Production evidence

```text
commit=3d6e6ef
[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True

Active rejects exist:
- REJECT_NEGATIVE_EV
- REJECT_ECON_BAD_ENTRY
- NO_CANDIDATE_PATTERN
- ECON_BAD_ENTRY_RETURN_TRACE

Missing:
- PAPER_EXPLORE_ENTRY
- PAPER_EXPLORE_SKIP
- PAPER_ENTRY
- PAPER_EXIT
- LEARNING_UPDATE
```

## Conclusion

`paper_exploration_override()` exists, but is not called from the actual production reject paths.

## Goal

Wire paper exploration directly into active reject hooks so production shows at least:

```text
[PAPER_EXPLORE_SKIP] reason=...
```

and ideally:

```text
[PAPER_EXPLORE_ENTRY] bucket=...
[PAPER_ENTRY] ...
```

## Hard rules

```text
Paper only.
Real prices only.
Never place real orders.
Never bypass live_trading_allowed().
Do not loosen live trading gates.
No synthetic entry/exit prices.
No tick-level Firebase writes.
Closed paper trades only.
Keep paper/live metrics separated.
No replay_train in this patch.
```

## Task 1 — Add central helper

Add to `src/services/paper_exploration.py` or `src/services/trade_executor.py`:

```python
def maybe_open_paper_exploration_from_reject(
    signal: dict,
    ctx: dict | None = None,
    *,
    original_decision: str,
    reject_reason: str,
    current_price: float | None = None,
) -> bool:
    """
    Try opening a paper exploration trade from a rejected real-price signal.
    Returns True if paper position opened.
    Observability/safety only. Never raises.
    """
```

Required behavior:

```text
if not is_paper_mode(): return False
if not paper_exploration_enabled(): return False

Resolve symbol from signal/ctx.

Resolve real price in order:
1 current_price
2 signal["price"]
3 signal["last_price"]
4 signal["current_price"]
5 ctx["price"]
6 ctx["last_price"]
7 ctx["current_price"]

If price invalid:
  log [PAPER_EXPLORE_SKIP] reason=no_real_price symbol=... original_decision=... reject_reason=...
  return False

Call paper_exploration_override(signal, ctx).

If not allowed:
  log [PAPER_EXPLORE_SKIP] reason=<ov.reason> bucket=<ov.bucket> symbol=... original_decision=... reject_reason=...
  return False

Call open_paper_position(...) with real price and exploration metadata.

Log [PAPER_EXPLORE_ENTRY] bucket=... symbol=... original_decision=... reject_reason=... ev=... score=... price=...

Return True.
```

Required metadata on paper trade:

```text
paper_source=exploration_reject
explore_bucket=<bucket>
original_decision=<reject decision>
reject_reason=<reject reason>
size_mult=<ov.size_mult>
max_hold_s=<ov.max_hold_s>
tags=<ov.tags>
ev, score, p, coh, af, regime if available
```

## Task 2 — Wire active ECON_BAD trace path

Production proves this function runs:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] ... final_decision=REJECT_ECON_BAD_ENTRY
```

Inside `_trace_econ_bad_entry_return(...)`, after the trace log, call:

```python
maybe_open_paper_exploration_from_reject(
    signal=signal or {
        "symbol": symbol,
        "ev": ev,
        "score": score,
        "p": p,
        "coh": coh,
        "af": af,
    },
    ctx=ctx or {},
    original_decision=final_decision or "REJECT_ECON_BAD_ENTRY",
    reject_reason=entry_reason or "unknown",
)
```

This must never raise.

If price is missing, production must show:

```text
[PAPER_EXPLORE_SKIP] reason=no_real_price ...
```

## Task 3 — Wire negative EV reject path

Before active `REJECT_NEGATIVE_EV` returns, call:

```python
maybe_open_paper_exploration_from_reject(
    signal=signal,
    ctx=ctx_or_local_probe_ctx,
    original_decision="REJECT_NEGATIVE_EV",
    reject_reason="negative_ev",
    current_price=last_price_or_price,
)
```

`D_NEG_EV_CONTROL` is capped, so this is safe.

## Task 4 — Wire NO_CANDIDATE_PATTERN path

Production shows:

```text
on_price(...): NO_CANDIDATE_PATTERN
```

In that active `on_price` path, call helper with minimal signal:

```python
maybe_open_paper_exploration_from_reject(
    signal={
        "symbol": symbol,
        "side": inferred_or_default_side,
        "action": inferred_or_default_side,
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

If side cannot be inferred safely, skip and log:

```text
[PAPER_EXPLORE_SKIP] reason=no_side symbol=...
```

## Required logs after patch

Production must show at least one:

```text
[PAPER_EXPLORE_SKIP] reason=...
[PAPER_EXPLORE_ENTRY] bucket=...
```

If neither appears, hook is still not wired into the real path.

## Tests

Add/extend `tests/test_p1_paper_exploration.py`.

Required tests:

```text
_trace_econ_bad_entry_return calls maybe_open_paper_exploration_from_reject
helper logs PAPER_EXPLORE_SKIP when no real price
helper opens paper with valid real price
REJECT_NEGATIVE_EV path calls helper
NO_CANDIDATE_PATTERN path calls helper or logs skip
exploration disabled -> helper no-op
no live executor called
```

## Validate

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

Success:

```text
[RUNTIME_VERSION] commit=<P1.1b commit>
[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True
[PAPER_EXPLORE_ENTRY] bucket=...
[PAPER_ENTRY] ...
```

Minimum acceptable:

```text
[PAPER_EXPLORE_SKIP] reason=...
```

This proves the hook is reached. If only SKIP appears, fix the exact skip reason next. Do not start P1.2.
