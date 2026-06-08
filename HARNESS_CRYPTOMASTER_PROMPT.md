Build a harness for this project.

Domain:
CryptoMaster is a PAPER-only crypto trading bot running on Hetzner Ubuntu with Binance USDâ“-M Futures public feeds, Firebase/Firestore metrics, Android dashboard contract, SQLite quota/outbox safety, and strict no-real-trading policy.

Goal:
Create a Claude Code agent team that prevents patch treadmill behavior and forces evidence-based development. The team must support runtime log analysis, PAPER learning verification, Firebase quota safety, Android metrics contract consistency, narrow patch authoring, and regression validation.

Architecture pattern:
Use Supervisor + Producer-Reviewer.
The Supervisor assigns tasks but cannot approve deployment.
Every implementation must be reviewed by an independent Safety/Regression reviewer before acceptance.

Create these agents:
1. runtime-forensic-agent
   - Reads logs, journalctl snippets, state files, and code paths.
   - Must separate evidence from hypothesis.
   - Must never recommend patches without concrete runtime proof.

2. paper-learning-agent
   - Verifies PAPER entries, exits, learning updates, rolling metrics, adaptive policy changes, and segment cooldown behavior.
   - Must prove that learning changes future admission behavior, not only records data.

3. firebase-quota-agent
   - Enforces no per-tick Firebase reads/writes.
   - Checks read/write quota caps, outbox behavior, retry safety, batching, and fail-closed modes.

4. trading-safety-agent
   - Enforces REAL trading disabled.
   - Checks no real order path, no accidental live execution, no auto-deploy unless explicitly authorized.
   - Blocks changes that affect real trading.

5. test-regression-agent
   - Selects targeted and full regression suites.
   - Verifies tests do not contaminate runtime state files.
   - Requires before/after evidence.

6. android-contract-agent
   - Maintains Czech Android dashboard contract.
   - Verifies metrics are consistent: total trades, winrate, PF, learning status, open positions, symbol stats, recommendations, timestamps.

7. patch-author-agent
   - Writes minimal diffs only after evidence is accepted.
   - Must preserve existing invariants.
   - Must not add diagnostics unless they answer a concrete blocker.

8. reviewer-agent
   - Reviews every patch.
   - Must try to reject it.
   - Must check safety, tests, persistence, quota, state contamination, and deploy risk.

Skills to generate:
- runtime-log-forensics
- paper-learning-validation
- firebase-quota-safety
- no-real-trading-gate
- test-isolation-validation
- android-dashboard-contract
- narrow-patch-authoring
- deployment-readiness-review

Hard rules:
- Do not restart or deploy unless explicitly instructed.
- Do not push to main unless explicitly instructed.
- Do not modify real trading paths.
- Do not write Firebase per tick.
- Do not trust historical PF/global metrics as proof of current learning.
- Do not accept â€śtests passedâ€ť without checking runtime state contamination.
- Prefer partial, narrow fixes over broad refactors.
- Every final answer must include: evidence, changed files, tests run, safety impact, deployment status, remaining risks.

Generate the full .claude/agents/ and .claude/skills/ structure for this repository.
