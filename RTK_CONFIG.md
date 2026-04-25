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

## Critical Patterns for CryptoMaster

### Trade Exit Analysis
```powershell
rtk grep "PARTIAL_TP\|SCRATCH_EXIT\|MICRO_TP" src
rtk read src\services\smart_exit_engine.py
```

### Canonical State Verification
```powershell
rtk grep "canonical_state\|get_authoritative" src
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

## Verification

```powershell
rtk --version                    # Check RTK is installed
rtk gain                         # Show token savings
rtk git status                   # Test compressed output
```

## Integration with Claude Code

Claude Code has automatic RTK hook configured globally. You can:
1. Use RTK commands explicitly: `rtk git status`
2. Or let the hook compress automatically

For Codex, always use explicit `rtk` prefix.

---

**Last Updated:** 2026-04-25  
**Version:** V10.13s.3  
**Status:** Active Integration
