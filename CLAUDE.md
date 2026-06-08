# PROJECT: HF-Quant 5.0 (Stabilized)

## ROLE
Senior Python Engineer focused on high-frequency algorithmic trading.

## RULES
- Do NOT overengineer.
- Keep modules small and clear. Stateless wherever possible.
- Always use standard `event_bus` for cross-component signaling.
- Maintain persistent learning state via `firebase_client`.

## MASTER DOCUMENTATION
For detailed context, logic, and architecture, refer to:
- [ARCHITECTURE.md](file:///c:/Projects/CryptoMaster_srv/ARCHITECTURE.md) (High-level design & Data flow)
- [src/services/README.md](file:///c:/Projects/CryptoMaster_srv/src/services/README.md) (Service layer map)
- [src/services/LOGIC.md](file:///c:/Projects/CryptoMaster_srv/src/services/LOGIC.md) (Mathematical models & Calibration)
- [bot2/README.md](file:///c:/Projects/CryptoMaster_srv/bot2/README.md) (Runtime orchestration & Auditor)

## CORE ARCHITECTURE
- **Ingestion**: `market_stream.py` (WebSocket) -> `event_bus.py`.
- **Decision Engine**: `realtime_decision_engine.py` (Bayesian calibration + EV Gating).
- **Execution**: `trade_executor.py` (Position lifecycle) -> `risk_engine.py`.
- **State**: Firestore (Trades/Metrics) + Redis (Hydration).

## HARNESS: Evidence-Based Development

**Goal:** Prevent patch treadmill by enforcing evidence-first workflow + multi-agent safety gates.

**Trigger:** Report any bug, ask for code change, or request feature → Invoke `evidence-based-patch-orchestrator` skill

**Workflow:**
1. Runtime forensics (collect evidence)
2. Parallel validation (safety, learning, quota, tests, contract)
3. Minimal patch authoring (root cause only)
4. Independent review (safety gates)
5. Deployment readiness
6. Deploy

**Agents:** runtime-forensic, paper-learning, firebase-quota, trading-safety, test-regression, android-contract, patch-author, reviewer

**Skills:** 8 domain-specific skills + 1 orchestrator

**Critical rule:** No patch without forensic evidence. No deployment without all agent approvals.

See `.claude/agents/` and `.claude/skills/` for full agent/skill definitions.

**Change History:**
| Date | Change | Scope | Reason |
|------|--------|-------|--------|
| 2026-06-08 | Initial harness + V10.19 timeout fix | Full system | Prevent patch treadmill, fix timeout bug |

## WORKFLOW
- One module = one focused responsibility.
- Use `logging` for critical state changes; avoid `print` spam in production.
- If logic is complex → Document in [LOGIC.md](file:///c:/Projects/CryptoMaster_srv/src/services/LOGIC.md).

## DATA FLOW
fetch → event_bus → signal_engine → calibrated_ev → risk_filter → execute → learn

## RTK WORKFLOW (Token Optimization)
For long/noisy outputs, use RTK to compress context for Claude/Codex analysis.

**Quick Commands:**
```bash
rtk git status          # Compressed git status
rtk git diff            # Filtered diff summary
rtk pytest              # Test results condensed
rtk ruff check .        # Lint issues summarized
rtk grep "PATTERN" .    # Search results filtered
rtk read path/file.py   # File summary
rtk log logs/app.log    # Log analysis
```

**Before Commits:**
```bash
rtk git status
rtk git diff
rtk pytest
rtk ruff check .
```

**Token Savings:** RTK has saved 1.2M+ tokens (98.7% efficiency) across this project.

**Reference:** See [RTK_CONFIG.md](file:///c:/Projects/CryptoMaster_srv/RTK_CONFIG.md) for detailed workflow patterns and critical command examples for trade exit analysis, canonical state verification, Firebase quota monitoring, and event bus health checks.

**Snapshot Tool:** Run `.\rtk_snapshot.ps1` to capture all diagnostics at once.
