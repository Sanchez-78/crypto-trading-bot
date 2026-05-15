#!/bin/bash

# P1.1AH: Journal-safe quality diagnostics audit
# Analyzes paper training quality logs without modifying service state
# Usage: bash p11ag_quality_audit.sh [--since "30 min ago"]

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

# Safe journalctl with fallback
safe_journalctl() {
    local filter="$1"
    journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep -E "$filter" || true
}

# Count logs safely
count_logs() {
    local filter="$1"
    safe_journalctl "$filter" | wc -l || echo "0"
}

# Extract latest "Total trades in LM" value
latest_lm_count() {
    safe_journalctl "Total trades in LM" | tail -1 | grep -oE "[0-9]+" | tail -1 || echo "?"
}

echo "============================================================"
echo "P1.1AG Quality Diagnostics Audit"
echo "============================================================"

PID=$(get_pid)
echo "Service PID: $PID"
echo "Since: $SINCE"
echo ""

# Check if journalctl is working
if ! journalctl -u cryptomaster --since "$SINCE" --no-pager >/dev/null 2>&1; then
    echo "[ERROR] journalctl failed. Consider:"
    echo "  sudo journalctl --verify"
    echo "  sudo journalctl --rotate"
    echo "  sudo journalctl --vacuum-time=2d"
    echo "  sudo systemctl restart systemd-journald"
    echo ""
fi

echo "Log Counts:"
echo "-------"

# Core pipeline counts
ENTRIES=$(count_logs "PAPER_TRAIN_ENTRY")
QUALITY_ENTRIES=$(count_logs "PAPER_TRAIN_QUALITY_ENTRY")
QUALITY_EXITS=$(count_logs "PAPER_TRAIN_QUALITY_EXIT")
MISMATCHES=$(count_logs "PAPER_TRAIN_QUALITY_MISMATCH")
ANOMALIES=$(count_logs "PAPER_TRAIN_ANOMALY")
SUMMARIES=$(count_logs "PAPER_TRAIN_QUALITY_SUMMARY")
EXITS=$(count_logs "PAPER_EXIT")
LEARNING=$(count_logs "LEARNING_UPDATE ok=True")

echo "PAPER_TRAIN_ENTRY:           $ENTRIES"
echo "PAPER_TRAIN_QUALITY_ENTRY:   $QUALITY_ENTRIES"
echo "PAPER_TRAIN_QUALITY_EXIT:    $QUALITY_EXITS"
echo "PAPER_TRAIN_QUALITY_MISMATCH: $MISMATCHES"
echo "PAPER_TRAIN_ANOMALY:         $ANOMALIES"
echo "PAPER_TRAIN_QUALITY_SUMMARY: $SUMMARIES"
echo "PAPER_EXIT:                  $EXITS"
echo "LEARNING_UPDATE ok=True:     $LEARNING"
echo ""

# State
echo "LM State:"
echo "-------"
LM_COUNT=$(latest_lm_count)
echo "Latest Total trades in LM: $LM_COUNT"
echo ""

# Diagnostics
echo "Diagnostics:"
echo "-------"

if [ "$ENTRIES" -gt 0 ] && [ "$QUALITY_ENTRIES" -eq 0 ]; then
    echo "⚠️  [MISMATCH] Entries exist ($ENTRIES) but no quality_entry logs!"
    echo "    Suggests: quality logging not called or filtered"
elif [ "$ENTRIES" -eq 0 ]; then
    echo "ℹ️  No paper training entries in this window"
else
    if [ "$QUALITY_ENTRIES" -eq "$ENTRIES" ]; then
        echo "✓ Quality entry logs match entry count ($ENTRIES = $QUALITY_ENTRIES)"
    else
        echo "⚠️  Quality entry log count mismatch: $ENTRIES entries, $QUALITY_ENTRIES quality logs"
    fi
fi

if [ "$MISMATCHES" -gt 0 ]; then
    echo "⚠️  Found $MISMATCHES quality entry mismatches"
fi

if [ "$ANOMALIES" -gt 0 ]; then
    echo "⚠️  Found $ANOMALIES quality anomalies"
fi

if [ "$EXITS" -gt 0 ] && [ "$QUALITY_EXITS" -eq 0 ]; then
    echo "⚠️  Exits exist ($EXITS) but no quality_exit logs!"
elif [ "$EXITS" -gt 0 ]; then
    echo "✓ Exit logs present ($QUALITY_EXITS)"
fi

if [ "$EXITS" -gt 0 ] && [ "$LEARNING" -eq 0 ]; then
    echo "⚠️  Paper exits exist but learning updates not seen"
fi

echo ""
echo "Sample logs (last 20):"
echo "-------"
safe_journalctl "PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_QUALITY_SUMMARY|PAPER_TRAIN_ANOMALY" | tail -20

echo ""
echo "============================================================"
