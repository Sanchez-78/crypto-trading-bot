# Claude Code Prompt — Use CryptoMaster Strategy Research Roadmap

You are working in the CryptoMaster repository.

Input document:
- `cryptomaster_strategy_research_roadmap.md`

If the file is not present, ask me to upload or paste it. Do not guess its contents.

## Context
CryptoMaster has recently completed these phases:
- P1.1AT: paper sampler rate-cap reservation fix
- P1.1AN: paper-training TP/SL calibration
- P1.1AU: canonical training trade count source fix

Current rule: **no blind patching, no live/real behavior changes, no strategy tuning without enough evidence.**

## Task
Read `cryptomaster_strategy_research_roadmap.md` and produce a practical implementation plan, but do **not** change code yet.

Focus on turning the research into a safe, staged roadmap for improving:
1. robot success rate,
2. learning quality,
3. trade selection,
4. Android app observability,
5. future Codex implementation tasks.

## Required Output
Create a new markdown file:

`docs/research/CryptoMaster_Strategy_Research_Implementation_Backlog.md`

The document must include:

### 1. Current-state check
Compare the research roadmap against the current codebase and recent P1.1AT/P1.1AN/P1.1AU state.

Mark each idea as:
- `READY_OFFLINE`
- `READY_SHADOW_ONLY`
- `BLOCKED_BY_DATA`
- `DO_NOT_IMPLEMENT_NOW`

### 2. Priority ranking
Rank by ROI and safety:
1. offline-only first,
2. shadow-only second,
3. paper_train gated third,
4. live/real never changed without separate approval.

### 3. Recommended next modules
Propose concrete modules/scripts, for example:
- offline trade label analyzer,
- triple-barrier label exporter,
- EV/probability calibration report,
- regime performance report,
- cost-aware edge report,
- Android metrics schema extension.

Do not implement them yet. Only specify purpose, inputs, outputs, and validation.

### 4. Android app metrics mapping
Extract which metrics from the research should be displayed in the Android app:
- robot health,
- learning progress,
- signal quality,
- EV calibration,
- paper/live trade performance,
- regime performance,
- cost/fee impact,
- attribution breakdown.

For each metric include:
- display name in Czech,
- internal field/source,
- explanation tooltip in Czech,
- refresh frequency,
- whether it is safe for dashboard or should be hidden in advanced diagnostics.

### 5. Codex implementation prompts
Create compact Codex prompts for the first 3 safe tasks only.

Rules for Codex prompts:
- each task must be isolated,
- offline or read-only first,
- no live/real trading behavior changes,
- no Firebase write amplification,
- include tests,
- include rollback instructions,
- include exact files likely to be touched,
- include acceptance criteria.

### 6. Hard stop rules
Explicitly state when to stop and not implement:
- if sample size is too small,
- if attribution is mixed,
- if metrics contradict each other,
- if code path touches live/real trading,
- if Firebase quota risk increases.

## Constraints
- Do not modify trading logic.
- Do not modify live/real execution.
- Do not tune TP/SL, EV, score thresholds, or RDE gates.
- Do not add new diagnostics unless they are offline/read-only.
- Do not create large logs or high-frequency Firebase writes.
- Prefer local/offline reports and Android read models.

## Final Response
After creating the markdown file, summarize:
- what file was created,
- top 3 safe next steps,
- what must remain frozen.
