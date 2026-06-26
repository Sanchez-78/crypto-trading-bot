# Dashboard Exit Distribution Fix - Test Setup

## Issue
Dashboard `/api/dashboard/metrics` was reporting exit_distribution with all zeros when bot API returned 0 trades, despite database containing actual exit reason counts (tp=37, sl=27, timeout=47, etc.).

## Root Cause
- SQL query (lines 739-745) only fetched total/wins/net_pnl
- Separate query for exit_reason counts (lines 759-781) was unreliable
- Fallback response (line 844) returned hardcoded zeros

## Fix
- Extended primary SQL query to compute exit_reason counts in a single operation (8 aggregations)
- Removed unreliable secondary query
- Use computed counts directly in response

## Manual Test
```bash
# Verify database has trades with exit_reason values
sqlite3 local_learning_storage/learning_database.sqlite "SELECT exit_reason, COUNT(*) FROM trades GROUP BY exit_reason;"

# Call dashboard API (should now return correct exit_distribution)
curl http://localhost:5001/api/dashboard/metrics | jq '.exit_distribution'

# Expected output (example):
# {
#   "tp": 37,
#   "sl": 27,
#   "scratch": 0,
#   "stagnation": 0,
#   "timeout": 47
# }
```

## Test Isolation
- No tests contaminate runtime state
- Paper-only display fix (no order changes)
- Safe aggregation (SUM handles NULL)
