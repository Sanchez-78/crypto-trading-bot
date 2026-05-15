#!/bin/bash

# P1.1AK: Snapshot-based quality audit with atomic reads
# Analyzes paper training quality logs from a single journalctl snapshot
# Usage: bash p11ag_quality_audit.sh [--since "30 min ago"]

set -e

# P1.1AL: Safe counter helpers
to_int() {
    local v
    v="$(printf '%s\n' "$1" | head -n1 | tr -dc '0-9')"
    [ -n "$v" ] && echo "$v" || echo 0
}

count_pattern() {
    local pattern="$1"
    local value
    value="$(grep -E "$pattern" "$LOG_TMP" 2>/dev/null | wc -l | tr -d '[:space:]')"
    to_int "$value"
}

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

PID=$(get_pid)
START_TIME=$(get_start_time)
GIT_HEAD=$(get_git_head)

echo "============================================================"
echo "P1.1AK Quality Audit (Snapshot-Based)"
echo "============================================================"
echo "Service PID: $PID"
echo "Service start: $START_TIME"
echo "Git HEAD: $GIT_HEAD"
echo "Since: $SINCE"
echo ""

# P1.1AK: Create atomic snapshot of journalctl output
LOG_TMP="$(mktemp /tmp/p11ak_audit_XXXXXX 2>/dev/null || mktemp)"
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

echo "Audit snapshot lines: $SNAP_LINES"
echo "Audit snapshot first_ts: $SNAP_FIRST"
echo "Audit snapshot last_ts: $SNAP_LAST"
echo ""

# All counters use the snapshot file (no further journalctl calls)
count_logs() {
    local filter="$1"
    count_pattern "$filter"
}

echo "Log Counts:"
echo "-------"

# Core pipeline counts
ENTRIES=$(to_int "$(count_logs "PAPER_TRAIN_ENTRY")")
QUALITY_ENTRIES=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_ENTRY")")
QUALITY_EXITS=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_EXIT")")
QUALITY_EXIT_MISSING=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_EXIT_MISSING")")
MISMATCHES=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_MISMATCH")")
ANOMALIES=$(to_int "$(count_logs "PAPER_TRAIN_ANOMALY")")
SUMMARIES=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_SUMMARY")")
EXITS=$(to_int "$(count_logs "PAPER_EXIT")")
LEARNING=$(to_int "$(count_logs "LEARNING_UPDATE ok=True")")
LM_STATE_AFTER=$(to_int "$(count_logs "LM_STATE_AFTER_UPDATE")")
LM_MISMATCH=$(to_int "$(count_logs "LM_UPDATE_MISMATCH")")
SCORE_MISSING_CTX=$(to_int "$(count_logs "PAPER_SCORE_MISSING_CONTEXT")")

# P1.1AK: Split counters by source and training bucket
ENTRIES_REAL=$(to_int "$(grep "PAPER_TRAIN_ENTRY" "$LOG_TMP" 2>/dev/null | grep -c "bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
EXITS_TRAINING=$(to_int "$(grep "PAPER_EXIT" "$LOG_TMP" 2>/dev/null | grep -c "training_bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
QUALITY_EXITS_TRAINING=$(to_int "$(grep "PAPER_TRAIN_QUALITY_EXIT" "$LOG_TMP" 2>/dev/null | grep -c "training_bucket=C_WEAK_EV_TRAIN" 2>/dev/null || echo "0")")
QUALITY_EXITS_TIMEOUT_NP=$(to_int "$(count_logs "PAPER_TRAIN_QUALITY_EXIT.*reason=TIMEOUT_NO_PRICE")")
COST_EDGE_BYPASS=$(to_int "$(count_logs "COST_EDGE_BYPASS")")
ECON_SUMMARY=$(to_int "$(count_logs "PAPER_TRAIN_ECON_SUMMARY")")

# P1.1AM: Attribution and bypass log split
ECON_ATTRIB=$(to_int "$(count_logs "PAPER_TRAIN_ECON_ATTRIB")")
ATTR_FEE_DOMINATED=$(to_int "$(count_logs "attribution=FEE_DOMINATED_MOVE")")
ATTR_TP_TOO_FAR=$(to_int "$(count_logs "attribution=TP_TOO_FAR_FOR_MFE")")
ATTR_COST_BYPASS_LOSS=$(to_int "$(count_logs "attribution=COST_EDGE_BYPASS_LOSS")")
ATTR_WRONG_DIR=$(to_int "$(count_logs "attribution=WRONG_DIRECTION")")
ATTR_LOW_VOL=$(to_int "$(count_logs "attribution=LOW_VOL_TIMEOUT")")
COST_EDGE_CANDIDATE=$(to_int "$(count_logs "COST_EDGE_BYPASS_CANDIDATE")")
COST_EDGE_ACCEPTED=$(to_int "$(count_logs "COST_EDGE_BYPASS_ACCEPTED")")

echo "PAPER_TRAIN_ENTRY:                $ENTRIES"
echo "PAPER_TRAIN_ENTRY_REAL (training): $ENTRIES_REAL"
echo "PAPER_TRAIN_QUALITY_ENTRY:        $QUALITY_ENTRIES"
echo "PAPER_TRAIN_QUALITY_EXIT:         $QUALITY_EXITS"
echo "PAPER_TRAIN_QUALITY_EXIT_MISSING: $QUALITY_EXIT_MISSING"
echo "PAPER_TRAIN_QUALITY_MISMATCH:     $MISMATCHES"
echo "PAPER_TRAIN_ANOMALY:              $ANOMALIES"
echo "PAPER_TRAIN_QUALITY_SUMMARY:      $SUMMARIES"
echo "PAPER_EXIT:                       $EXITS"
echo "PAPER_EXIT_TRAINING_BUCKET:       $EXITS_TRAINING"
echo "PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET: $QUALITY_EXITS_TRAINING"
echo "PAPER_TRAIN_QUALITY_EXIT_TIMEOUT_NO_PRICE: $QUALITY_EXITS_TIMEOUT_NP"
echo "LEARNING_UPDATE ok=True:          $LEARNING"
echo "LM_STATE_AFTER_UPDATE:            $LM_STATE_AFTER"
echo "LM_UPDATE_MISMATCH:               $LM_MISMATCH"
echo "PAPER_SCORE_MISSING_CONTEXT:      $SCORE_MISSING_CTX"
echo "COST_EDGE_BYPASS:                 $COST_EDGE_BYPASS"
echo "PAPER_TRAIN_ECON_SUMMARY:         $ECON_SUMMARY"
echo ""

echo "Attribution Counts:"
echo "-------"
echo "PAPER_TRAIN_ECON_ATTRIB:          $ECON_ATTRIB"
echo "ATTR_FEE_DOMINATED_MOVE:          $ATTR_FEE_DOMINATED"
echo "ATTR_TP_TOO_FAR_FOR_MFE:          $ATTR_TP_TOO_FAR"
echo "ATTR_COST_EDGE_BYPASS_LOSS:       $ATTR_COST_BYPASS_LOSS"
echo "ATTR_WRONG_DIRECTION:             $ATTR_WRONG_DIR"
echo "ATTR_LOW_VOL_TIMEOUT:             $ATTR_LOW_VOL"
echo "COST_EDGE_BYPASS_CANDIDATE:       $COST_EDGE_CANDIDATE"
echo "COST_EDGE_BYPASS_ACCEPTED:        $COST_EDGE_ACCEPTED"
echo ""

# P1.1AK: Trade-ID correlation (per-trade quality exit verification)
echo "Trade-ID Correlation:"
echo "-------"
MISSING_COUNT=0
MISSING_EXITS=""
while read -r tid sym; do
    if ! grep -q "PAPER_TRAIN_QUALITY_EXIT.*trade_id=$tid" "$LOG_TMP" 2>/dev/null; then
        MISSING_COUNT=$((MISSING_COUNT+1))
        MISSING_EXITS="${MISSING_EXITS}  trade_id=$tid symbol=$sym\n"
    fi
done < <(grep "PAPER_EXIT.*training_bucket=C_WEAK_EV_TRAIN" "$LOG_TMP" 2>/dev/null \
    | grep -oE "trade_id=[^ ]+ symbol=[^ ]+" \
    | awk '{print substr($1,10)" "substr($2,8)}')

echo "QUALITY_EXIT_MISSING_BY_TRADE_ID: $MISSING_COUNT"
if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "Missing quality exits:"
    echo -e "$MISSING_EXITS"
fi
echo ""

# LM State
echo "LM State:"
echo "-------"
LM_COUNT=$(grep "Total trades in LM" "$LOG_TMP" 2>/dev/null | tail -1 | grep -oE "[0-9]+" | tail -1 || true)
LM_COUNT=$(to_int "${LM_COUNT:-0}")
echo "Latest Total trades in LM: $LM_COUNT"
echo ""

# Diagnostics
echo "Diagnostics:"
echo "-------"

if [ "$ENTRIES" -gt 0 ] && [ "$QUALITY_ENTRIES" -eq 0 ]; then
    echo "⚠️  [MISMATCH] Entries exist ($ENTRIES) but no quality_entry logs!"
elif [ "$ENTRIES" -eq 0 ]; then
    echo "ℹ️  No paper training entries in this window"
else
    if [ "$QUALITY_ENTRIES" -ge "$ENTRIES" ]; then
        echo "✓ Quality entry logs match entry count (entries=$ENTRIES quality=$QUALITY_ENTRIES)"
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

if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "⚠️  Found $MISSING_COUNT missing quality exits by trade_id"
fi

if [ "$ANOMALIES" -gt 0 ]; then
    echo "⚠️  Found $ANOMALIES quality anomalies"
fi

if [ "$SCORE_MISSING_CTX" -gt 0 ]; then
    echo "ℹ️  Found $SCORE_MISSING_CTX score missing context logs"
fi

if [ "$COST_EDGE_BYPASS" -gt 0 ]; then
    echo "ℹ️  Found $COST_EDGE_BYPASS cost_edge bypass logs"
fi

if [ "$EXITS_TRAINING" -gt 0 ] && [ "$QUALITY_EXITS_TRAINING" -eq 0 ]; then
    echo "⚠️  Training exits exist ($EXITS_TRAINING) but no training quality_exit logs!"
elif [ "$EXITS_TRAINING" -gt 0 ]; then
    echo "✓ Training exit logs present (exits=$EXITS_TRAINING quality=$QUALITY_EXITS_TRAINING)"
fi

if [ "$EXITS_TRAINING" -gt 0 ] && [ "$LEARNING" -eq 0 ] && [ "$LM_STATE_AFTER" -eq 0 ]; then
    echo "⚠️  Training exits exist but no learning update logs"
elif [ "$EXITS_TRAINING" -gt 0 ] && ([ "$LEARNING" -gt 0 ] || [ "$LM_STATE_AFTER" -gt 0 ]); then
    echo "✓ Learning update logs present (LEARNING_UPDATE=$LEARNING LM_STATE=$LM_STATE_AFTER)"
fi

if [ "$LM_MISMATCH" -gt 0 ]; then
    echo "⚠️  Found $LM_MISMATCH LM update mismatches (should be 0)"
fi

if [ "$ECON_SUMMARY" -gt 0 ]; then
    echo "✓ Economic summary logged (count=$ECON_SUMMARY)"
fi

echo ""
echo "Sample logs (last 25 quality events):"
echo "-------"
grep -E "PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_QUALITY_SUMMARY|PAPER_TRAIN_ANOMALY|PAPER_SCORE_MISSING_CONTEXT|PAPER_TRAIN_ECON_SUMMARY|COST_EDGE_BYPASS" "$LOG_TMP" 2>/dev/null | tail -25

echo ""
echo "Sample attribution logs (last 10):"
echo "-------"
grep "PAPER_TRAIN_ECON_ATTRIB" "$LOG_TMP" 2>/dev/null | tail -10

echo ""
echo "============================================================"
