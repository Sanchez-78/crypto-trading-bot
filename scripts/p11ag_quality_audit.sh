#!/bin/bash

# P1.1AJ: Journal-safe quality diagnostics audit
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

# Get service start time
get_start_time() {
    systemctl show -p ActiveEnterTimestamp --value cryptomaster 2>/dev/null || echo "unknown"
}

# Get git HEAD
get_git_head() {
    git -C /opt/cryptomaster rev-parse --short HEAD 2>/dev/null || echo "N/A"
}

# Safe journalctl with PID filtering and fallback
safe_journalctl() {
    local filter="$1"
    local output

    # Try primary query with PID filter
    output=$(journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" | grep -E "$filter" 2>/dev/null || true)

    # If query failed or is empty and we have a PID, warn about potential journal corruption
    if [ -z "$output" ] && [ "$PID" != "UNKNOWN" ]; then
        # Try fallback with start time
        output=$(journalctl -u cryptomaster --since "$(get_start_time)" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" | grep -E "$filter" 2>/dev/null || true)
        if [ -z "$output" ]; then
            return 0  # Return empty, don't error
        fi
    fi

    echo "$output"
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
echo "P1.1AJ Quality Diagnostics Audit"
echo "============================================================"

PID=$(get_pid)
START_TIME=$(get_start_time)
GIT_HEAD=$(get_git_head)

echo "Service PID: $PID"
echo "Service start: $START_TIME"
echo "Git HEAD: $GIT_HEAD"
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
QUALITY_EXIT_MISSING=$(count_logs "PAPER_TRAIN_QUALITY_EXIT_MISSING")
MISMATCHES=$(count_logs "PAPER_TRAIN_QUALITY_MISMATCH")
ANOMALIES=$(count_logs "PAPER_TRAIN_ANOMALY")
SUMMARIES=$(count_logs "PAPER_TRAIN_QUALITY_SUMMARY")
EXITS=$(count_logs "PAPER_EXIT")
LEARNING=$(count_logs "LEARNING_UPDATE ok=True")
LM_STATE_AFTER=$(count_logs "LM_STATE_AFTER_UPDATE")
LM_MISMATCH=$(count_logs "LM_UPDATE_MISMATCH")
SCORE_MISSING_CTX=$(count_logs "PAPER_SCORE_MISSING_CONTEXT")

echo "PAPER_TRAIN_ENTRY:                $ENTRIES"
echo "PAPER_TRAIN_QUALITY_ENTRY:        $QUALITY_ENTRIES"
echo "PAPER_TRAIN_QUALITY_EXIT:         $QUALITY_EXITS"
echo "PAPER_TRAIN_QUALITY_EXIT_MISSING: $QUALITY_EXIT_MISSING"
echo "PAPER_TRAIN_QUALITY_MISMATCH:     $MISMATCHES"
echo "PAPER_TRAIN_ANOMALY:              $ANOMALIES"
echo "PAPER_TRAIN_QUALITY_SUMMARY:      $SUMMARIES"
echo "PAPER_EXIT:                       $EXITS"
echo "LEARNING_UPDATE ok=True:          $LEARNING"
echo "LM_STATE_AFTER_UPDATE:            $LM_STATE_AFTER"
echo "LM_UPDATE_MISMATCH:               $LM_MISMATCH"
echo "PAPER_SCORE_MISSING_CONTEXT:      $SCORE_MISSING_CTX"
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

if [ "$QUALITY_EXIT_MISSING" -gt 0 ]; then
    echo "⚠️  Found $QUALITY_EXIT_MISSING missing quality exit logs (should be 0)"
fi

if [ "$ANOMALIES" -gt 0 ]; then
    echo "⚠️  Found $ANOMALIES quality anomalies"
fi

if [ "$SCORE_MISSING_CTX" -gt 0 ]; then
    echo "ℹ️  Found $SCORE_MISSING_CTX score missing context logs"
fi

if [ "$EXITS" -gt 0 ] && [ "$QUALITY_EXITS" -eq 0 ]; then
    echo "⚠️  Exits exist ($EXITS) but no quality_exit logs!"
elif [ "$EXITS" -gt 0 ]; then
    echo "✓ Exit logs present ($QUALITY_EXITS)"
fi

if [ "$EXITS" -gt 0 ] && [ "$LEARNING" -eq 0 ] && [ "$LM_STATE_AFTER" -eq 0 ]; then
    echo "⚠️  Paper exits exist but no learning update logs (neither LEARNING_UPDATE ok=True nor LM_STATE_AFTER_UPDATE)"
elif [ "$EXITS" -gt 0 ] && ([ "$LEARNING" -gt 0 ] || [ "$LM_STATE_AFTER" -gt 0 ]); then
    echo "✓ Learning update logs present (LEARNING_UPDATE ok=True: $LEARNING, LM_STATE_AFTER_UPDATE: $LM_STATE_AFTER)"
fi

if [ "$LM_MISMATCH" -gt 0 ]; then
    echo "⚠️  Found $LM_MISMATCH LM update mismatches (should be 0)"
fi

echo ""
echo "Sample logs (last 20):"
echo "-------"
safe_journalctl "PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_QUALITY_SUMMARY|PAPER_TRAIN_ANOMALY|PAPER_SCORE_MISSING_CONTEXT" | tail -20

echo ""
echo "============================================================"
