# Claude Code Prompt — CryptoMaster V10.12g Post-Deployment Validation

Analyze the existing Python trading bot project and the newest runtime logs after V10.12g.

Do NOT rewrite the system.
Do NOT propose speculative architecture changes before first validating actual runtime behavior.
Work incrementally from evidence in logs and existing code.

## GOAL

Validate whether V10.12g actually fixed the runtime blocking issues and determine the next highest-priority fix.

V10.12g was intended to fix 3 production blockers:
1. Redis must be optional and no longer spam logs
2. STALL / idle seconds must be correct and no longer explode to unix-time-sized values
3. Final decision pipeline must be visible enough to diagnose why candidates pass or fail

Your job:
- inspect the newest logs
- verify whether those 3 goals are actually achieved
- quantify live behavior
- identify the next bottleneck
- propose only the smallest high-impact patch needed next

---

## VALIDATION QUESTIONS

Answer these in order:

### 1) Redis validation
Check whether Redis is now degrading gracefully.

Validate:
- Is Redis failure logged only once or very rarely?
- Are repeated per-cycle Redis connection errors gone?
- Does the bot continue running normally without Redis?
- Is runtime status correctly showing Redis unavailable/available?

Return:
- PASS / PARTIAL / FAIL
- evidence from logs
- if failed, exact remaining Redis issue

---

### 2) Idle / STALL validation
Check whether idle time is now computed correctly.

Validate:
- Are STALL values realistic?
- Are there any remaining giant values like `1776251170s`?
- Does self-heal trigger only after genuine inactivity?
- Is cold start handled correctly?

Return:
- PASS / PARTIAL / FAIL
- evidence from logs
- if failed, exact source of remaining timestamp bug

---

### 3) Decision visibility validation
Check whether the final decision path is now diagnosable from logs.

Validate:
- Is there exactly one authoritative final decision line per candidate?
- Do logs contain:
  - symbol
  - regime
  - raw/adjusted EV
  - raw/adjusted score
  - score threshold
  - EV threshold
  - timing penalty
  - OFI multiplier
  - cooldown remaining
  - fallback considered/used
  - anti_deadlock
  - final reason
- Is there a clear cycle-level `no_candidate` log?

Return:
- PASS / PARTIAL / FAIL
- evidence from logs
- which fields are still missing if any

---

### 4) Pipeline health validation
This is the most important section.

Measure from logs:
- pass-through rate
- number of candidates evaluated
- number of TAKE decisions
- number of SKIP decisions by reason
- whether `NORMAL`, `FALLBACK`, and `ANTI_DEADLOCK` are all appearing
- whether pipeline is still effectively deadlocked

Determine:
- Is signal generation the problem?
- Is score gating the problem?
- Is cooldown still too aggressive?
- Is fallback too weak / never used?
- Is anti-deadlock firing too often?
- Is the system alive but only via fallback?

Return a concise diagnosis.

---

### 5) Trade quality validation
If any trades are opening, evaluate whether they look healthy.

Check:
- average size multiplier
- whether unblock trades remain micro-sized
- fallback share of trades
- anti-deadlock share of trades
- whether NORMAL trades dominate or not
- whether timeout exits still dominate

Use this interpretation:
- NORMAL should ideally become majority over time
- FALLBACK can assist flow but should not dominate forever
- ANTI_DEADLOCK should be rare
- timeout-heavy exits indicate entry may be fixed but exit logic still weak

Return:
- HEALTHY / MIXED / UNHEALTHY
- with short explanation

---

## REQUIRED OUTPUT STRUCTURE

Use exactly this structure:

### A. Validation verdict
- Redis: PASS / PARTIAL / FAIL
- STALL/idle: PASS / PARTIAL / FAIL
- Decision visibility: PASS / PARTIAL / FAIL
- Pipeline health: PASS / PARTIAL / FAIL
- Trade quality: HEALTHY / MIXED / UNHEALTHY

### B. Evidence summary
Bullet the strongest direct runtime evidence from logs.

### C. Bottleneck ranking
Rank the top 3 remaining bottlenecks by impact.

### D. Next patch recommendation
Recommend exactly one next patch only:
- name it (example: `V10.13a Exit Quality Patch`)
- explain why it is next
- keep scope minimal and high-impact

### E. Patch plan
Give a concise implementation plan:
- files likely to change
- exact logic to patch
- what not to change

### F. Success criteria
Define what logs/metrics would prove that the next patch worked.

---

## IMPORTANT RULES

- Do not guess if logs do not support the claim.
- Prefer direct evidence over theory.
- Do not propose a major rewrite.
- Do not change thresholds blindly before validating behavior.
- If pipeline is alive but weak, say so clearly.
- If entry is fixed and exit is now the main problem, say that clearly.
- If fallback is doing too much work, say that clearly.
- If anti-deadlock is triggering often, say that clearly.

---

## WHAT TO LOOK FOR SPECIFICALLY

### Healthy signs
- Redis warning appears once, then silence
- STALL values are realistic
- cycle logs clearly show candidate flow
- some TAKE decisions appear
- pass rate becomes low-but-nonzero
- NORMAL trades start appearing
- fallback is present but not dominant
- anti-deadlock is rare

### Unhealthy signs
- repeated Redis connection spam
- giant STALL values
- still no authoritative decision logs
- 0 pass-through
- only fallback trades
- anti-deadlock frequently needed
- timeout exits still ~all closes

---

## FINAL TASK

At the end, give one final conclusion in this form:

`Current state: [deadlocked / partially recovered / operational but weak / healthy enough for live tuning]`

Then state the single best next move.
