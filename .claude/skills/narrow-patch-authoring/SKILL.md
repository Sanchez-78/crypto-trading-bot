---
name: narrow-patch-authoring
description: |
  Author minimal code patches from forensic evidence. Change only root cause, 
  preserve invariants, no refactoring, no tech debt cleanup unless it's the 
  bug. Commit with evidence citation.

---

# Narrow Patch Authoring Skill

## Workflow

### Step 1: Review Evidence

Before writing ANY code:
1. Read forensic report from runtime-forensic-agent
2. Identify ROOT CAUSE (not symptom)
3. Note exact file:line from evidence
4. Confirm evidence is concrete (logs + code + state, not hypothesis)

### Step 2: Minimal Fix

**Write ONLY the change needed to fix root cause:**

```python
# BEFORE (buggy code)
effective_hold = _effective_paper_hold_s(pos)  # Returns 300 incorrectly
...
elif age_s >= effective_hold:  # Uses wrong variable
    exit_reason = "TIMEOUT"

# AFTER (minimal fix)
timeout_s = pos.get("timeout_s", _MAX_AGE_S)  # Use correct field
...
elif age_s >= timeout_s:  # Fixed
    exit_reason = "TIMEOUT"
```

**DON'T do this:**
```python
# BAD: Refactoring while fixing
- effective_hold = _effective_paper_hold_s(pos)
- max_hold = pos.get("max_hold_s", ...)
- timeout_s = pos.get("timeout_s", max_hold)
+ timeout_s = pos.get("timeout_s", _MAX_AGE_S)
+ # Also clean up unused _effective_paper_hold_s call
+ # And rename variables for clarity
```

### Step 3: Self-Review Diff

```bash
git diff src/services/paper_trade_executor.py
```

Checklist:
- ✓ Only lines needed to fix root cause?
- ✓ No unrelated refactoring?
- ✓ No variable renames for clarity?
- ✓ Diagnostics only if blocking investigation?
- ✓ Invariants preserved?

### Step 4: Commit

```bash
git commit -m "Root Cause: brief explanation

Evidence: Log lines + code path + state

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

## Diagnostic Rules

**Add logging ONLY if:**
- Evidence is incomplete
- Next investigation will be blocked without it
- Temporary (remove after diagnosis confirms fix)

**DON'T add:**
- Comprehensive state dumps "just in case"
- Debug info for adjacent code
- Comments explaining what the code does (good variable names are enough)

## Invariant Checks

**Before committing, verify:**
- Position entry still works
- Position closure still works
- Learning state still propagates
- Dashboard metrics still correct
- Android contract still compliant
