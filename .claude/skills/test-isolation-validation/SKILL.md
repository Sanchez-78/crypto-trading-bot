---
name: test-isolation-validation
description: |
  Validates test suite isolation and regression. Runs full test suite before 
  and after patch. Detects new failures and state leaks between tests. 
  Verifies tests can run in random order without contamination.

---

# Test Isolation Validation Skill

## Regression Testing

### Step 1: Baseline (on main)

```bash
cd /path/to/project
git checkout main
pytest tests/ -v > baseline_results.txt 2>&1
```

Record:
- Total tests: N
- Passed: P
- Failed: F
- Duration: T

### Step 2: Test Patch

```bash
git checkout feature-branch
pytest tests/ -v > patch_results.txt 2>&1
```

### Step 3: Compare

```bash
diff baseline_results.txt patch_results.txt
```

**Fail if:**
- New failures appeared
- Tests that passed before now fail

### Step 4: Isolation Check

Run tests in random order (detect state leaks):

```bash
pytest tests/ -v --random-order > random1.txt
pytest tests/ -v --random-order > random2.txt
diff random1.txt random2.txt
```

**Fail if:**
- Results differ between runs
- Indicates state contamination between tests

## Key Commands

```bash
# Run specific test suite
pytest tests/test_timeout.py -v

# Run with coverage
pytest tests/ --cov=src

# Run in isolation (separate DB/files)
pytest tests/ --forked  # Requires pytest-forked plugin
```

## Gates

- ✅ PASS: All tests pass + no new failures + consistent results with random order
- ⚠️ CAUTION: All tests pass but order-dependent (state leak, needs investigation)
- ❌ FAIL: New test failures found
