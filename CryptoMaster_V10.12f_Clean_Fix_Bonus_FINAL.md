# Claude Code Prompt — CryptoMaster V10.12f Clean Decision Flow Fix + Bonus Anti-Deadlock Guard

(continued)

---

## IMPLEMENTATION TARGET

Inspect and patch the real files responsible for:
- final decision gating
- score/EV thresholding
- unblock mode state propagation
- fallback acceptance logic
- executor size application
- unblock trade rate limiting
- status/dashboard threshold display
- final decision logging

Most likely at least:
- realtime_decision_engine.py
- signal_filter.py
- trade_executor.py
- any dashboard/status/logging file if separate

If cluster cooldown enforcement still interferes with reachable unblock decisions:
- ensure cooldown is applied AFTER unblock adjustment
- ensure unblock mode can reduce effective lock time

Reuse existing architecture.
Modify real integration points.
Do not leave dead helper code.
Do not add parallel unused systems.

---

## FINAL CHECKLIST (MUST PASS)

Before returning implementation, ensure:

[ ] Fallback logic is reachable before score gate rejection  
[ ] Score threshold uses unblock-aware value  
[ ] EV threshold is consistent and not misleading (no fake 0.000)  
[ ] LOSS_CLUSTER cannot lock symbols indefinitely during idle  
[ ] Unblock trades are micro-sized (0.25–0.35x)  
[ ] Rate limits (6/h, max 2 positions) enforced on fallback  
[ ] Logs clearly show fallback_used and unblock state  
[ ] At least one path guarantees non-zero pass-through  

---

## RETURN FORMAT

Return:

1. Full code for every changed file (no truncation)
2. Short explanation per file (what changed and why)
3. Root cause summary (why V10.12e still deadlocked)
4. Fix summary (how V10.12f resolves decision ordering)
5. Bonus guard explanation (how anti-deadlock works)
6. Any assumptions if actual code differs

Do NOT return pseudo-code only.
Return real, production-ready Python code integrated into the existing project.

---

## FINAL NOTE

This patch is not about strategy improvement.
It is about restoring a functioning decision pipeline.

The system must:
- stop being stuck at 0%
- remain safe
- remain bounded
- produce observable, debuggable behavior

Only after this patch is validated should further strategy tuning continue.
