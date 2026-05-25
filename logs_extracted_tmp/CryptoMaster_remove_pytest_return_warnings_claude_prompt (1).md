# Claude Code Prompt — Test Hygiene: Remove PytestReturnNotNone Warnings in VERIFICATION_V10_13W

## Goal

Remove the 6 `PytestReturnNotNoneWarning` warnings from the server-safe pytest suite by correcting legacy pytest test functions that return `bool` instead of asserting.

This is a **test-only cleanup patch**. Do not change production/runtime code or bot behavior.

## Current baseline

Current HEAD before this cleanup:

```text
eb259e3 P1.1AP-J2: Emit B_RECOVERY_READY exit attribution diagnostics
```

Current server-safe full suite:

```text
854 passed, 6 warnings in 2.87s
```

All 6 warnings come from:

```text
VERIFICATION_V10_13W/test_v10_13w_fixes.py
```

Warnings:

```text
test_fix_a_learning_integrity returned <class 'bool'>
test_fix_b_decision_score returned <class 'bool'>
test_fix_c_pnl_reconciliation returned <class 'bool'>
test_fix_d_safe_mode returned <class 'bool'>
test_fix_e_exit_attribution returned <class 'bool'>
test_fix_f_explainability returned <class 'bool'>
```

Pytest warning meaning:

```text
Test functions must return None.
Returning True/False does not assert test success/failure and triggers PytestReturnNotNoneWarning.
```

## Hard boundaries

Do **not** change:

- Any file in `src/`
- Trading logic, learning logic, paper behavior, telemetry, thresholds, TP/SL, sizing
- P1.1AP-J2, P1.1AP-K, I/I2 behavior
- Test expectations or scenario semantics unless needed to turn returned boolean checks into real assertions
- pytest configuration to suppress warnings
- Warning filters such as `filterwarnings = ignore`

Do not hide the warning. Fix the malformed tests.

## Investigation

Inspect only the affected legacy verification test file first:

```bash
cd /opt/CryptoMaster_srv

sed -n '1,260p' VERIFICATION_V10_13W/test_v10_13w_fixes.py
grep -n "^def test_\|return True\|return False\|return " VERIFICATION_V10_13W/test_v10_13w_fixes.py
```

Determine which pattern is used in each affected test:

### Pattern A — simple boolean return

Bad:

```python
def test_fix_a_learning_integrity():
    result = run_check()
    return result
```

Fix:

```python
def test_fix_a_learning_integrity():
    result = run_check()
    assert result is True
```

or, if result may be truthy/non-bool:

```python
assert result, "learning integrity check failed"
```

### Pattern B — conditional early failure returns

Bad:

```python
def test_fix_b_decision_score():
    if bad_condition:
        return False
    return True
```

Fix:

```python
def test_fix_b_decision_score():
    assert not bad_condition, "describe failing condition"
```

or preserve diagnostics:

```python
if bad_condition:
    pytest.fail("describe failing condition")
```

### Pattern C — helper returns structured status

If a helper returns a tuple/dict/result object, assert the meaningful condition and preserve useful diagnostics:

```python
assert result["ok"], f"check failed: {result}"
```

## Required change

File to edit:

```text
VERIFICATION_V10_13W/test_v10_13w_fixes.py
```

For each of these six functions:

```text
test_fix_a_learning_integrity
test_fix_b_decision_score
test_fix_c_pnl_reconciliation
test_fix_d_safe_mode
test_fix_e_exit_attribution
test_fix_f_explainability
```

Requirements:

1. Test function must return `None` naturally.
2. Replace pass/fail `return True` / `return False` / `return result_bool` with explicit `assert` or `pytest.fail()`.
3. Preserve existing test setup, mocked inputs and intended verification.
4. Preserve or improve assertion failure messages.
5. Do not broadly rewrite the verification module.

If the file has a `__main__` runner that calls these functions and expects bool values, keep CLI/script behavior separately by:
- introducing internal helper functions returning bool and pytest wrappers asserting them; or
- adjusting only the `__main__` runner to catch `AssertionError` and report fail.
Do not break a standalone verification invocation without checking it.

## Required tests

Run affected tests first:

```bash
cd /opt/CryptoMaster_srv

./venv/bin/python -m pytest -q VERIFICATION_V10_13W/test_v10_13w_fixes.py
```

Expected:

```text
6 passed
no PytestReturnNotNoneWarning
```

Then run server-safe full suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Expected:

```text
854 passed, 0 warnings
```

If more tests exist in that verification file, keep the total actual count; key acceptance is no `PytestReturnNotNoneWarning`.

## Diff and commit hygiene

Before commit:

```bash
git diff --stat
git diff -- VERIFICATION_V10_13W/test_v10_13w_fixes.py
git status --short
```

Only commit the affected test file unless a narrowly necessary test-runner compatibility edit exists.

Do not commit:

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary terminal or test-output files
```

## Commit message

```text
Tests: Replace legacy boolean-return pytest checks with assertions
```

Push only after targeted and server-safe full suites pass with zero warnings.

## Report back

Return:
- exact return-to-assert rewrites made;
- whether standalone/`__main__` compatibility required handling;
- targeted test result;
- full server-safe suite result and warning count;
- commit hash if pushed.
