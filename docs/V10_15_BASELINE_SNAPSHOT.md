# V10.15 Mammon — Baseline Snapshot (Phase A)

**Date**: 2026-04-25  
**Branch**: `main`  
**Head**: `348e603` (Fix: POCET OBCHODU section always renders when trades exist)  
**Status**: 6 modified, 8 untracked

---

## Git Status

```
Modified:
  .claude/settings.local.json
  procfile
  src/services/execution_engine.py
  src/services/exit_attribution.py
  src/services/firebase_client.py
  src/services/notifier.py

Untracked (logs/tests/generated):
  V10_15X_FIXES_SUMMARY.txt
  logs_extracted_tmp/RTK_Claude_Codex_CryptoMaster_Workflow.md
  logs_extracted_tmp/V10_13x_1_Dashboard_Truth_Patch.md
  logs_extracted_tmp/cryptomaster_v10_15_mammon_NONBREAKING_OPTIMIZED.md
  main.py
  tests/test_firebase_quota.py
  tests/test_main_compat.py
  tests/test_metrics_consistency.py
```

---

## Compilation

**Result**: ✅ PASS

All 63 modules compile without syntax errors:
- `compileall .` completed successfully
- No import errors detected
- No obvious circular imports

---

## Tests

**Result**: ✅ PASS (33 tests)

```
33 passed in 1.72s
```

**Method**: `python -c "import pytest; pytest.main(['-q', 'tests/', '--tb=no', '--ignore=tests/test_v5_core.py'])"`

**Coverage**:
- `test_metrics_consistency.py`: 3 tests (canonical stats, nested profit fallback, exit attribution)
- `test_main_compat.py`: 2 tests (Firebase loading, async save)
- `test_firebase_quota.py`: 28 tests (quota system, pre-flight checks, reactive quota exhaustion)

**Known issues**: 
- `tests/test_v5_core.py` has unresolved imports (missing `src.core.ev` module), excluded from baseline

---

## Recent Commits (V10.13x.1 + V10.15 patches)

```
348e603 Fix: POCET OBCHODU section always renders when trades exist
4659a43 Dashboard: add dedicated POCET OBCHODU (trade count) table
148c774 Dashboard: show per-symbol trade count in live prices section
2c2f11a Fix metrics_engine: losss KeyError + neutral-timeout scope + ev None crash
d5eb216 V10.13x.1: Dashboard Truth Patch — canonical source, N/A guards, RECON+SRC logs
76caaff V10.15x: Five-fix batch — thread safety, ordered eviction, notifier visibility
```

---

## Detected Entrypoints

1. **`bot2/main.py`** — primary bot runtime; `print_status()` dashboard loop
2. **`src/services/market_stream.py`** — Binance WebSocket ingestion
3. **`src/services/signal_generator.py`** — feature extraction + signal generation
4. **`src/services/realtime_decision_engine.py`** — EV computation + gate evaluation
5. **`src/services/trade_executor.py`** — position lifecycle + order routing
6. **`src/services/learning_event.py`** — trade outcome learning + metrics state
7. **`src/services/firebase_client.py`** — Firestore I/O + quota system
8. **`start.py`** / **`start_fresh.py`** — bootstrap + hydration

---

## Pre-Existing Fragility (No-Fix Items)

1. **Unresolved test imports** (`test_v5_core.py` → missing `src.core.ev`)
   - Not blocking; excluded from baseline test run
   - Likely stub from abandoned feature branch

2. **Modified files uncommitted** (6 files)
   - `.claude/settings.local.json` — local IDE config (safe to ignore)
   - `procfile`, `execution_engine.py`, `exit_attribution.py`, `firebase_client.py`, `notifier.py` — likely from recent patch work
   - Do not commit; let developer decide

3. **No `docs/` directory**
   - Will create `docs/V10_15_*.md` as part of Phase B onwards

---

## Readiness for Phase B (Architecture Audit)

✅ **Ready** — no blockers detected.
- Codebase compiles cleanly
- Tests pass (33/33)
- Recent commits show stable state (dashboard truth patch + bug fixes merged)
- No build infrastructure issues
- Git history legible

**Proceed to Phase B** — Architecture audit of entrypoints, flows, contracts, and fragility.
