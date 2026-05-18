#!/bin/bash

# P1.1AS: Sampler Rate-Cap State Inspection (Read-Only)
# Inspects current sampler state without writing
# Usage: bash p11as_sampler_state_check.sh [--since "30 min ago"]

set -e

# Parse arguments
SINCE="${2:--1h}"
if [ "$1" = "--since" ]; then
    SINCE="$2"
fi

# Get current service PID safely
get_pid() {
    systemctl show -p MainPID --value cryptomaster 2>/dev/null || echo "UNKNOWN"
}

# Get service start time
get_start_time() {
    systemctl show -p ActiveEnterTimestamp --value cryptomaster 2>/dev/null || echo "unknown"
}

# Get git HEAD
get_git_head() {
    git -C /opt/cryptomaster rev-parse --short HEAD 2>/dev/null || echo "N/A"
}

to_int() {
    local v
    v="$(printf '%s\n' "$1" | head -n1 | tr -dc '0-9')"
    [ -n "$v" ] && echo "$v" || echo 0
}

PID=$(get_pid)
START_TIME=$(get_start_time)
GIT_HEAD=$(get_git_head)

echo "============================================================"
echo "P1.1AS Sampler State Inspection (Read-Only)"
echo "============================================================"
echo "Service PID: $PID"
echo "Service start: $START_TIME"
echo "Git HEAD: $GIT_HEAD"
echo "Since: $SINCE"
echo ""

# Create atomic snapshot of journalctl output
LOG_TMP="$(mktemp /tmp/p11as_state_XXXXXX 2>/dev/null || mktemp)"
trap 'rm -f "$LOG_TMP"' EXIT

# Read journal once into temp file, filtered by PID
if ! journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1; then
    # Fallback: try with service start time
    journalctl -u cryptomaster --since "$START_TIME" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1 || true
fi

# Get snapshot metadata
SNAP_LINES=$(wc -l < "$LOG_TMP" 2>/dev/null || echo "0")
SNAP_FIRST=$(head -1 "$LOG_TMP" 2>/dev/null | awk '{print $1" "$2}' || echo "unknown")
SNAP_LAST=$(tail -1 "$LOG_TMP" 2>/dev/null | awk '{print $1" "$2}' || echo "unknown")

echo "Snapshot lines: $SNAP_LINES"
echo "Snapshot first_ts: $SNAP_FIRST"
echo "Snapshot last_ts: $SNAP_LAST"
echo ""

# Check paper_open_positions.json file
echo "Paper Positions File:"
echo "-------"
POSITIONS_FILE="/opt/cryptomaster/data/paper_open_positions.json"
if [ -f "$POSITIONS_FILE" ]; then
    FILE_SIZE=$(stat -f%z "$POSITIONS_FILE" 2>/dev/null || stat -c%s "$POSITIONS_FILE" 2>/dev/null || echo "unknown")
    FILE_MOD=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$POSITIONS_FILE" 2>/dev/null || stat -c "%y" "$POSITIONS_FILE" 2>/dev/null | cut -d' ' -f1,2 || echo "unknown")
    echo "File size: $FILE_SIZE bytes"
    echo "Last modified: $FILE_MOD"

    # Count open positions safely
    if command -v jq &> /dev/null; then
        OPEN_COUNT=$(jq 'length' "$POSITIONS_FILE" 2>/dev/null || echo "0")
        echo "Open positions count: $OPEN_COUNT"
    else
        echo "Open positions count: (jq not available; install to introspect)"
    fi
else
    echo "File does not exist: $POSITIONS_FILE"
fi
echo ""

# Sampler Rate-Cap State Logs
echo "Recent Rate-Cap State Logs (last 20):"
echo "-------"
grep "PAPER_SAMPLER_RATE_CAP_STATE" "$LOG_TMP" 2>/dev/null | tail -20 || echo "(none found)"
echo ""

# Rate-Cap Drops
echo "Recent Rate-Cap Drops (last 20):"
echo "-------"
grep "COST_EDGE_BYPASS_FLOW.*stage=drop.*sampler_rate_cap" "$LOG_TMP" 2>/dev/null | tail -20 || echo "(none found)"
echo ""

# Candidate/Accepted/Attempt/Entry Flow
echo "Candidate-to-Entry Flow (last 30):"
echo "-------"
grep -E "COST_EDGE_BYPASS_FLOW|COST_EDGE_BYPASS_ACCEPTED|PAPER_ENTRY_ATTEMPT|PAPER_TRAIN_ENTRY" "$LOG_TMP" 2>/dev/null | tail -30 || echo "(none found)"
echo ""

# Counter Summary
echo "Counter Summary (from snapshot):"
echo "-------"
count_pattern() {
    local pattern="$1"
    local value
    value="$(grep -E "$pattern" "$LOG_TMP" 2>/dev/null | wc -l | tr -d '[:space:]')"
    to_int "$value"
}

RATE_CAP_DROPS=$(count_pattern "COST_EDGE_BYPASS_FLOW.*stage=drop.*sampler_rate_cap")
RATE_CAP_STATES=$(count_pattern "PAPER_SAMPLER_RATE_CAP_STATE")
CANDIDATES=$(count_pattern "COST_EDGE_BYPASS_FLOW.*stage=candidate")
ACCEPTED=$(count_pattern "COST_EDGE_BYPASS_ACCEPTED")
ATTEMPTS=$(count_pattern "PAPER_ENTRY_ATTEMPT")
ENTRIES=$(count_pattern "PAPER_TRAIN_ENTRY")

echo "Rate-cap drops: $RATE_CAP_DROPS"
echo "Rate-cap state logs: $RATE_CAP_STATES"
echo "Bypass candidates: $CANDIDATES"
echo "Bypass accepted: $ACCEPTED"
echo "Entry attempts: $ATTEMPTS"
echo "Final entries: $ENTRIES"
echo ""

# Diagnostic interpretation
echo "Diagnostic Interpretation:"
echo "-------"

if [ "$RATE_CAP_DROPS" -gt 0 ] && [ "$RATE_CAP_STATES" -eq 0 ]; then
    echo "❌ RATE_CAP_STATE_MISSING: Rate-cap drops exist but no state logs"
    echo "   Action: Check if P1.1AS rate-cap state logging is enabled"
elif [ "$RATE_CAP_DROPS" -gt 0 ] && [ "$RATE_CAP_STATES" -gt 0 ]; then
    echo "✓ Rate-cap state logging active"
    echo "   Review the state logs above to verify recent_entries, rate_limit, next_allowed_s"
elif [ "$RATE_CAP_DROPS" -eq 0 ]; then
    echo "ℹ️  No rate-cap drops in this window"
fi

if [ "$CANDIDATES" -gt 0 ] && [ "$ACCEPTED" -eq 0 ] && [ "$ENTRIES" -eq 0 ]; then
    echo "⚠️  Candidates exist but none accepted or entered (likely blocked by rate-cap)"
elif [ "$ACCEPTED" -gt 0 ] && [ "$ATTEMPTS" -eq 0 ]; then
    echo "⚠️  Candidates accepted but no entry attempts logged"
elif [ "$ATTEMPTS" -gt 0 ] && [ "$ENTRIES" -eq 0 ]; then
    echo "ℹ️  Entry attempts exist but no final entries (may be in-flight)"
fi

echo ""
echo "============================================================"
