# Claude Prompt — CryptoMaster Offline Strategy Backlog + Android Metrics

## Context

You are working on `CryptoMaster_srv`, an event-driven crypto trading bot. The current priority is **safe observability and offline research**, not live trading changes.

## Current verified state

- P1.1AO is complete: cold-start EV starvation recovery / probe logic exists.
- P1.1AT is complete: paper sampler rate-cap reservation is fixed; rate slots are committed only after successful paper entry creation.
- P1.1AN is complete: paper-training TP/SL geometry calibration is active for `paper_train + training_sampler + C_WEAK_EV_TRAIN`.
- P1.1AU is complete: bootstrap/probe decisions read canonical LearningMonitor trade count, not stale `learning_event.get_metrics()["trades"]`.
- Paper training entries, exits, quality logs, economic attribution, and LM state updates are flowing.
- No broad diagnostic patching is allowed now.
- No live/real trading behavior changes are allowed.
- No new TP/SL tuning is allowed.
- No EV/RDE tuning is allowed.
- No high-frequency Firebase writes are allowed.

## Important correction to the uploaded roadmap

The roadmap text is useful, but parts are outdated:
- Do **not** treat P1.1AO as pending.
- Do **not** treat P1.1AN as stuck at 2 trades.
- Do **not** propose another recovery patch.
- The next safe work is offline/read-only tooling and Android metrics schema.

## Main task

Create the next practical implementation plan for CryptoMaster focused on:

1. Android app metrics for monitoring bot state, learning, signals, trades, and health.
2. Offline/read-only research modules that export and analyze paper-training data.
3. Codex implementation prompts for the safest tasks.

## Required output

### 1. Updated status matrix

Create a table with these statuses:
- DONE
- READY_OFFLINE
- READY_ANDROID
- BLOCKED_BY_DATA
- DO_NOT_IMPLEMENT_NOW

Classify:
- Android dashboard metric schema
- Paper training dataset exporter
- Offline paper-training quality report
- Regime quality analyzer
- Validation framework
- Meta-labeling
- Probability calibration
- Cost-aware gating
- Regime-based gates
- Contextual bandit
- Momentum/mean-reversion split
- Live/real trading changes

### 2. Android app metrics catalog

Create a complete metrics catalog grouped into screens:

- Dashboard
- Bot status
- Paper training
- Live/real safety status
- Open positions
- Trade history
- Learning monitor
- Signal pipeline
- Economic attribution
- Regime quality
- Risk and health
- Firebase/quota/system status
- Alerts and warnings

For each metric define:
- `metric_key`
- Czech UI label
- Czech help text / explanation
- source: Firestore collection, local file, dashboard snapshot, log parser, or unknown
- update frequency
- priority: MUST / SHOULD / NICE
- safe fallback when missing

### 3. Android design proposal

Propose a modern Czech Android UI:

- bottom navigation or top tabs
- dashboard cards
- warning banners
- status chips
- charts
- detail screens
- empty/loading/error states
- color semantics
- beginner-friendly Czech explanations
- terminal/debug mode for advanced users

Focus on readability and trust. The user must quickly see:
- Is the bot alive?
- Is it trading?
- Is learning updating?
- Are there open positions?
- Is performance improving or degrading?
- Is Firebase quota safe?
- Is paper training producing useful samples?

### 4. Offline research modules

Use only read-only/offline tasks:

#### Task 1 — Paper Training Dataset Exporter
- Parse `[PAPER_TRAIN_QUALITY_ENTRY]`, `[PAPER_TRAIN_QUALITY_EXIT]`, `[PAPER_TRAIN_ECON_ATTRIB]`, `[PAPER_TRAIN_ECON_SUMMARY]`.
- Export `data/research/paper_training_dataset.jsonl`.
- Add unit tests.
- No Firebase writes.
- No trading logic changes.

#### Task 2 — Offline Quality Report
- Input: `paper_training_dataset.jsonl`.
- Output:
  - `data/research/paper_training_summary.md`
  - `data/research/paper_training_summary.json`
- Include attribution, winrate by symbol/regime, fee viability, MFE/MAE geometry, calibration bins, data integrity, and a clear `NO LIVE CHANGE` footer.

#### Task 3 — Regime Quality Analyzer
- Input: `paper_training_dataset.jsonl`.
- Output: `data/research/regime_quality_analysis.json`.
- Descriptive only.
- Never recommend live gate changes as direct action.

### 5. Codex prompts

Create 3 compact but complete Codex prompts:

1. Implement Paper Training Dataset Exporter.
2. Implement Offline Quality Report Generator.
3. Implement Regime Quality Analyzer.

Each prompt must include:
- files to create/change
- exact scope
- constraints
- tests
- success criteria
- forbidden changes

### 6. Hard stops

Explicitly forbid:
- live/real trading changes
- TP/SL tuning
- EV/RDE threshold changes
- strategy changes
- Firebase high-frequency writes
- adding dashboards before metrics schema is stable
- contextual bandit deployment
- meta-labeling deployment to live
- broad diagnostics patches

## Style

Be concise but complete. Prefer tables. Use Czech UI labels and explanations. Keep implementation prompts in English for Codex. Treat this as architecture/specification only, not implementation.
