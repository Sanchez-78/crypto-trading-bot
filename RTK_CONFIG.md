# RTK Workflow Configuration — CryptoMaster

**Purpose:** Use RTK to compress terminal outputs for efficient Claude/Codex analysis

## Quick Commands

### Status & Review
```powershell
rtk git status        # Compressed git status
rtk git diff          # Summary of changes
rtk pytest            # Test results filtered
rtk ruff check .      # Lint issues summarized
```

### Code Search & Review
```powershell
rtk grep "harvest" src           # Find harvest logic
rtk grep "SCRATCH_EXIT" .        # Search exit types
rtk grep "firebase" src          # Firebase operations
rtk read src\services\smart_exit_engine.py  # File summary
```

### Logs
```powershell
rtk log logs\app.log             # Log summary
rtk log logs\bot.log             # Bot log analysis
```

## Daily Routine

**Before committing:**
```powershell
cd C:\Projects\CryptoMaster_srv
rtk git status
rtk git diff
rtk pytest
```

**When debugging:**
```powershell
rtk log logs\app.log
rtk grep "ERROR\|WARN" logs\
```

**When reviewing code:**
```powershell
rtk read src\services\smart_exit_engine.py
rtk grep "partial25\|scratch_exit" src
```

## V10.13s.4 Module Commands — Priority 1-8 Implementation

### Priority 1: Canonical State Initialization
```powershell
# Verify canonical state loading
rtk grep "initialize_canonical_state\|get_canonical_state\|get_authoritative_trade_count" src

# Check startup state initialization in main.py
rtk grep "Canonical state\|canonical_state" bot2\main.py

# Verify canonical state oracle function
rtk read src\services\canonical_state.py

# Search for canonical state usages
rtk grep "canonical_state" src
```

### Priority 3: Economic Health Monitoring
```powershell
# Check economic health calculation
rtk grep "lm_economic_health\|profit_factor\|scratch_rate" src

# Monitor economic gate in decisions
rtk grep "economic_gate\|ECONOMIC_GATE" src

# View economic health metric display
rtk grep "Economic:" src\services\learning_monitor.py

# Check economic warnings/alerts
rtk grep "CAUTION\|FRAGILE\|DEGRADED" src
```

### Priority 4: Bootstrap Risk Mode
```powershell
# Verify bootstrap reduced mode detection
rtk grep "is_bootstrap_reduced_mode\|bootstrap_reduced" src

# Check position size reductions
rtk grep "size \*= 0.50" src\services\execution.py

# Monitor bootstrap mode indicator
rtk grep "BOOTSTRAP_REDUCED_MODE" src

# Check bootstrap data quality thresholds
rtk grep "trades < 150\|min_pair_n\|converged_pairs\|usable_pairs" src
```

### Priority 2: Scratch Exit Forensics (Deep Refactoring)
```powershell
# View scratch forensics module
rtk read src\services\scratch_forensics.py

# Search scratch classification logic
rtk grep "GOOD_DEFENSIVE\|NEUTRAL\|LOSSY_PREMATURE" src

# Monitor scratch instrumentation
rtk grep "instrument_scratch_exit\|get_scratch_diagnostics" src

# Check scratch pressure alerts
rtk grep "scratch_pressure_alert\|LOSSY_PREMATURE" src

# Analyze scratch patterns over time
rtk grep "ScratchEvent\|_scratch_events" src\services\scratch_forensics.py

# View health decomposition v2 integration
rtk grep "health_decomposition_v2" src
```

### Priority 6: Forced-Explore Quality Gates (Deep Refactoring)
```powershell
# View forced explore gates module
rtk read src\services\forced_explore_gates.py

# Check gate enforcement in decisions
rtk grep "is_forced_explore_allowed\|FORCED_EXPLORE_GATE" src

# Monitor individual gate checks
rtk grep "check_spread_quality\|check_execution_quality\|check_ofi_toxicity\|check_coherence\|check_edge_bucket\|check_loss_cluster" src

# View gate results logging
rtk grep "format_forced_explore_result" src

# Search forced-explore bootstrap integration
rtk grep "bootstrap_pair" src\services\realtime_decision_engine.py
```

### Priority 7: Economic Gate Protection
```powershell
# View economic gate function
rtk grep "def economic_gate" src\services\realtime_decision_engine.py

# Check economic gate blocking
rtk grep "SKIP_ECONOMIC\|economic_gate" src

# Monitor health-based trading throttle
rtk grep "profit_factor < 1.0\|scratch_rate > 0.75" src

# View soft/hard blocking logic
rtk grep "FRAGILE\|DEGRADED" src\services\learning_monitor.py
```

### Priority 8: Dashboard Expansion
```powershell
# View dashboard metrics display
rtk grep "Economic:\|Health:" src\services\learning_monitor.py

# Check metric printing functions
rtk grep "print.*health\|print.*economic" src\services\learning_monitor.py

# Monitor bootstrap mode indicator
rtk grep "BOOTSTRAP_REDUCED_MODE" src

# View warning displays
rtk grep "Warnings:" src\services\learning_monitor.py
```

## Critical Patterns for CryptoMaster

### Trade Exit Analysis
```powershell
rtk grep "PARTIAL_TP\|SCRATCH_EXIT\|MICRO_TP" src
rtk read src\services\smart_exit_engine.py
```

### Canonical State Verification
```powershell
rtk grep "canonical_state\|get_authoritative" src
rtk grep "initialize_canonical_state\|canonical_state_audit" bot2\main.py
```

### Firebase Quota Monitoring
```powershell
rtk grep "quota\|_record_read\|_record_write" src\services\firebase_client.py
```

### Event Bus Health
```powershell
rtk grep "subscribe\|publish" src\core\event_bus.py
```

## Why RTK?

- **Clarity**: Removes noise, shows only relevant diffs
- **Context**: Saves tokens so Claude sees the full problem
- **Speed**: Faster analysis of large files/outputs
- **Safety**: Prevents massive diff floods that obscure real changes

## When to Use RTK

| Scenario | Command |
|----------|---------|
| Too many files changed | `rtk git status` |
| Diff is 500+ lines | `rtk git diff` |
| Tests have 100+ lines | `rtk pytest` |
| Lint has many warnings | `rtk ruff check .` |
| Log is huge | `rtk log path` |
| Search returns 50+ matches | `rtk grep PATTERN .` |
| Reading large file | `rtk read path` |

## Diagnostic Commands for V10.13s.4

### Full System Diagnostics
```powershell
# All-in-one snapshot of critical systems
rtk grep "canonical_state\|economic_health\|bootstrap_reduced\|scratch_forensics\|forced_explore" src

# Quick health check
rtk grep "Health:\|Economic:\|BOOTSTRAP_REDUCED" src\services\learning_monitor.py

# Full module compilation check
rtk read src\services\canonical_state.py
rtk read src\services\scratch_forensics.py
rtk read src\services\forced_explore_gates.py

# Verify all gates integrated
rtk grep "economic_gate\|is_forced_explore_allowed\|is_bootstrap_reduced_mode" src\services\realtime_decision_engine.py
```

### State Integrity Checks
```powershell
# Canonical state consistency
rtk grep "trades_total\|trades_won\|trades_lost\|validation" src\services\canonical_state.py

# Economic metrics tracking
rtk grep "profit_factor\|scratch_rate\|recent_trend\|overall_score" src\services\learning_monitor.py

# Bootstrap mode detection
rtk grep "min_pair_n < 15\|converged_pairs < 4\|trades < 150" src\services\execution.py
```

### Decision Chain Verification
```powershell
# All gates in evaluate_signal order
rtk grep "daily_dd\|economic_gate\|forced_explore\|frequency cap" src\services\realtime_decision_engine.py

# Bootstrap pair handling
rtk grep "bootstrap_pair.*=.*True\|_bootstrap_pair" src\services\realtime_decision_engine.py

# Soft filters applied
rtk grep "soft_filter_signal\|timing_mult\|coherence_mult" src\services\realtime_decision_engine.py
```

### Performance & Forensics Analysis
```powershell
# Scratch exit instrumentation
rtk grep "instrument_scratch_exit" src

# Scratch diagnostics collection
rtk grep "get_scratch_diagnostics\|scratch_pressure_alert" src

# Economic health calculations
rtk grep "lm_economic_health" src\services\learning_monitor.py

# Forced-explore gate results
rtk grep "is_forced_explore_allowed.*results" src
```

## Verification

```powershell
rtk --version                    # Check RTK is installed
rtk gain                         # Show token savings
rtk git status                   # Test compressed output
```

### Verify All V10.13s.4 Components
```powershell
# 1. Check all new modules exist and compile
python -m py_compile src\services\canonical_state.py
python -m py_compile src\services\scratch_forensics.py
python -m py_compile src\services\forced_explore_gates.py

# 2. Verify imports in main modules
rtk grep "from src.services.canonical_state\|from src.services.scratch_forensics\|from src.services.forced_explore" src bot2

# 3. Check bot2/main.py startup sequence
rtk grep "initialize_canonical_state\|print_canonical_state" bot2\main.py

# 4. Verify learning_monitor integration
rtk grep "lm_economic_health\|health_decomposition_v2" src\services\learning_monitor.py

# 5. Check execution.py bootstrap mode
rtk grep "is_bootstrap_reduced_mode" src\services\execution.py

# 6. Verify realtime_decision_engine gates
rtk grep "economic_gate\|is_forced_explore_allowed" src\services\realtime_decision_engine.py
```

## Integration with Claude Code

Claude Code has automatic RTK hook configured globally. You can:
1. Use RTK commands explicitly: `rtk git status`
2. Or let the hook compress automatically

For Codex, always use explicit `rtk` prefix.

## Command Quick Reference by Task

| Task | RTK Command |
|------|------------|
| Verify startup state | `rtk grep "canonical_state" bot2\main.py` |
| Check economic health | `rtk grep "lm_economic_health" src` |
| Monitor bootstrap mode | `rtk grep "is_bootstrap_reduced_mode" src` |
| Analyze scratch exits | `rtk grep "LOSSY_PREMATURE" src` |
| Test forced-explore gates | `rtk grep "is_forced_explore_allowed" src` |
| View economic gate logic | `rtk grep "economic_gate" src\services\realtime_decision_engine.py` |
| Dashboard diagnostics | `rtk grep "Health:\|Economic:" src\services\learning_monitor.py` |
| Full system check | `rtk grep "canonical_state\|economic_health\|bootstrap_reduced" src` |

## Module Reference

**New Modules Added (V10.13s.4):**
- `src/services/canonical_state.py` — Startup source-of-truth (Priority 1)
- `src/services/scratch_forensics.py` — Exit quality tracking (Priority 2, Deep)
- `src/services/forced_explore_gates.py` — Bootstrap quality gates (Priority 6, Deep)

**Modified Modules (V10.13s.4):**
- `bot2/main.py` — Canonical state initialization
- `src/services/learning_monitor.py` — Economic health + dashboard
- `src/services/execution.py` — Bootstrap risk reduction
- `src/services/realtime_decision_engine.py` — Economic gate + forced-explore gates

**Integration Points:**
- Startup: `canonical_state.initialize_canonical_state()` in main.py [7/7b-CANONICAL]
- Decisions: `economic_gate()` + `is_forced_explore_allowed()` in evaluate_signal()
- Sizing: `is_bootstrap_reduced_mode()` reduces position sizes in `final_size()`
- Monitoring: `lm_economic_health()` + `health_decomposition_v2()` in dashboard

---

**Last Updated:** 2026-04-25  
**Version:** V10.13s.4 (All Priorities Implemented + Deep Refactoring)  
**Status:** Production Ready — All 8 priorities complete with RTK commands documented
