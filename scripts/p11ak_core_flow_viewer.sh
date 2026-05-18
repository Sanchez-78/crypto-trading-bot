#!/bin/bash

# P1.1AK: Core Flow Log Viewer — highlight actual trading/learning signals
# Shows CORE FLOW (trades, learning) vs DIAGNOSTICS (technical details)
# Usage: bash p11ak_core_flow_viewer.sh [--since "30 min ago"] [--color on|off]

set -e

SINCE="${1:--1h}"
if [ "$1" = "--since" ]; then
    SINCE="$2"
fi

COLOR="${3:-on}"
if [ "$2" = "--color" ]; then
    COLOR="$3"
fi

# Get service PID
PID=$(systemctl show -p MainPID --value cryptomaster 2>/dev/null || echo "UNKNOWN")

echo "============================================================"
echo "CORE FLOW LOG VIEWER"
echo "============================================================"
echo "PID: $PID"
echo "Since: $SINCE"
echo ""

# Color codes
if [ "$COLOR" = "on" ]; then
    BOLD='\033[1m'
    GREEN='\033[92m'
    BLUE='\033[94m'
    YELLOW='\033[93m'
    RED='\033[91m'
    CYAN='\033[96m'
    MAGENTA='\033[95m'
    RESET='\033[0m'
    DIM='\033[2m'
else
    BOLD=""
    GREEN=""
    BLUE=""
    YELLOW=""
    RED=""
    CYAN=""
    MAGENTA=""
    RESET=""
    DIM=""
fi

# Temp file for logs
LOG_TMP="$(mktemp /tmp/p11ak_viewer_XXXXXX 2>/dev/null || mktemp)"
trap 'rm -f "$LOG_TMP"' EXIT

# Read journal into temp file
journalctl -u cryptomaster --since "$SINCE" --no-pager 2>/dev/null | grep "cryptomaster\[$PID\]" > "$LOG_TMP" 2>&1 || true

echo -e "${BOLD}=== CORE FLOW: Trades & Learning ===${RESET}"
echo ""

# ENTRIES
echo -e "${GREEN}${BOLD}→ ENTRIES:${RESET}"
grep "PAPER_TRAIN_ENTRY\|PAPER_NEG_EV_PROBE_ACCEPTED" "$LOG_TMP" 2>/dev/null | tail -20 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    bucket=$(echo "$line" | grep -oE "bucket=[^ ]+" | cut -d= -f2)
    ev=$(echo "$line" | grep -oE "ev=[^ ]+" | cut -d= -f2)
    echo -e "  ${GREEN}✓${RESET} $symbol bucket=$bucket ev=$ev"
done

echo ""

# EXITS (only [PAPER_EXIT] lines, exclude quality/attrib diagnostics)
echo -e "${MAGENTA}${BOLD}← EXITS:${RESET}"
grep "\\[PAPER_EXIT\\]" "$LOG_TMP" 2>/dev/null | grep -v "PAPER_TRAIN_QUALITY_EXIT\|PAPER_TRAIN_ECON_ATTRIB" | tail -20 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    outcome=$(echo "$line" | grep -oE "outcome=[^ ]+" | cut -d= -f2)
    pnl=$(echo "$line" | grep -oE "pnl_pct=[^ ]+" | cut -d= -f2)
    reason=$(echo "$line" | grep -oE "reason=[^ ]+" | cut -d= -f2)
    # Only print if all required fields present
    if [ -n "$symbol" ] && [ -n "$outcome" ] && [ -n "$pnl" ] && [ -n "$reason" ]; then
        echo -e "  ${MAGENTA}✓${RESET} $symbol outcome=$outcome pnl=$pnl reason=$reason"
    fi
done

echo ""

# LEARNING UPDATES
echo -e "${CYAN}${BOLD}📚 LEARNING UPDATES:${RESET}"
grep "\\[LM_STATE_AFTER_UPDATE\\]" "$LOG_TMP" 2>/dev/null | tail -10 | while read line; do
    symbol=$(echo "$line" | grep -oE "symbol=[^ ]+" | cut -d= -f2)
    regime=$(echo "$line" | grep -oE "regime=[^ ]+" | cut -d= -f2)
    before=$(echo "$line" | grep -oE "before_total=[0-9]+" | cut -d= -f2)
    after=$(echo "$line" | grep -oE "after_total=[0-9]+" | cut -d= -f2)
    outcome=$(echo "$line" | grep -oE "outcome=[^ ]+" | cut -d= -f2)
    if [ -n "$symbol" ] && [ -n "$before" ] && [ -n "$after" ]; then
        echo -e "  ${CYAN}✓${RESET} $symbol $regime before_total=$before after_total=$after outcome=$outcome"
    fi
done

echo ""

# ERRORS/MISMATCHES (RED)
echo -e "${RED}${BOLD}⚠️  ERRORS & MISMATCHES:${RESET}"
ERROR_COUNT=$(grep -E "MISMATCH|STATE_MISMATCH|QUALITY_EXIT_MISSING|LM_UPDATE_MISMATCH" "$LOG_TMP" 2>/dev/null | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
    grep -E "MISMATCH|STATE_MISMATCH|QUALITY_EXIT_MISSING|LM_UPDATE_MISMATCH" "$LOG_TMP" 2>/dev/null | tail -10 | while read line; do
        msg=$(echo "$line" | sed 's/.*cryptomaster\[[0-9]*\]: //' | cut -c1-100)
        echo -e "  ${RED}✗${RESET} $msg"
    done
else
    echo -e "  ${GREEN}None${RESET}"
fi

echo ""
echo -e "${BOLD}=== DIAGNOSTICS: Technical Details ===${RESET}"
echo ""

# COUNTERS SUMMARY
echo -e "${DIM}Counters (last 60 min):${RESET}"
ENTRIES=$(grep "PAPER_TRAIN_ENTRY" "$LOG_TMP" 2>/dev/null | wc -l)
EXITS=$(grep "PAPER_EXIT" "$LOG_TMP" 2>/dev/null | wc -l)
PROBES=$(grep "PAPER_NEG_EV_PROBE_ACCEPTED" "$LOG_TMP" 2>/dev/null | wc -l)
LEARNING=$(grep "LM_STATE_AFTER_UPDATE\|LEARNING_UPDATE" "$LOG_TMP" 2>/dev/null | wc -l)
REJECTS=$(grep "REJECT" "$LOG_TMP" 2>/dev/null | wc -l)
SKIPS=$(grep "SKIP" "$LOG_TMP" 2>/dev/null | wc -l)

echo -e "  ${DIM}PAPER_TRAIN_ENTRY:       $ENTRIES${RESET}"
echo -e "  ${DIM}PAPER_EXIT:              $EXITS${RESET}"
echo -e "  ${DIM}PAPER_NEG_EV_PROBE:      $PROBES${RESET}"
echo -e "  ${DIM}LM_STATE_AFTER_UPDATE:   $LEARNING${RESET}"
echo -e "  ${DIM}REJECT:                  $REJECTS${RESET}"
echo -e "  ${DIM}SKIP:                    $SKIPS${RESET}"

echo ""

# THROTTLE LOGS (suppressed by default)
echo -e "${DIM}Throttled/Diagnostic Logs (suppressed):${RESET}"
echo -e "  ${DIM}Use 'journalctl' directly to see HBLOCK, EXPLORE_SKIP, etc.${RESET}"

echo ""
echo "============================================================"
