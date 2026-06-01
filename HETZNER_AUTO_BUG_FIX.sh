#!/bin/bash
# Phase 4A Automated Bug Detection & Fixing
# Monitors for known issues and applies fixes automatically

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  PHASE 4A AUTOMATED BUG DETECTION & FIXING                 ║"
echo "║  $(date)                                           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

cd /opt/cryptomaster

# ============================================================================
# 1. DETECT COMMON ISSUES
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. DETECTING TRADING LOGIC ISSUES"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ISSUES=0
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Issue 1: trades_closed still 0 after 1 hour
TRADES_CLOSED=$(sudo grep "trades_closed" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null | tail -1 | grep -oE "trades_closed[^,}]*" || echo "trades_closed: 0")
if echo "$TRADES_CLOSED" | grep -q "0"; then
  echo "⚠️  ISSUE 1: trades_closed metric not incrementing"
  ((ISSUES++))

  # Fix: Check if closes are happening
  CLOSE_COUNT=$(sudo grep -c "PAPER_CLOSE\|position.*closed" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
  if [ "$CLOSE_COUNT" -gt 0 ]; then
    echo "   ROOT CAUSE: Closes happening but metric not counting"
    echo "   FIX: Check runner.py line 220-241 (delta counting)"
  fi
else
  echo "✅ trades_closed working: $TRADES_CLOSED"
fi

# Issue 2: Entry starvation (0 entries for 30+ min)
ENTRY_COUNT=$(sudo grep -c "PAPER_ENTRY" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$ENTRY_COUNT" -eq 0 ]; then
  echo "⚠️  ISSUE 2: No entries in logs (possible starvation)"
  ((ISSUES++))

  # Check cost-edge rejections
  COST_EDGE=$(sudo grep -c "cost_edge\|PAPER_ENTRY_BLOCKED" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
  if [ "$COST_EDGE" -gt 0 ]; then
    echo "   ROOT CAUSE: Entries blocked by cost-edge gate"
    echo "   FIX: Check shadow margin - might need lower threshold"
  fi
else
  echo "✅ Entries occurring: $ENTRY_COUNT logs"
fi

# Issue 3: No learning feedback applied
LEARNING=$(sudo grep -c "learning_weight" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$LEARNING" -eq 0 ]; then
  echo "⚠️  ISSUE 3: Learning feedback not visible in logs"
  ((ISSUES++))
  echo "   ROOT CAUSE: PolicyStateTracker not wired to PolicySelector"
  echo "   FIX: Verify set_policy_state_tracker() called in __init__"
else
  echo "✅ Learning feedback active: $LEARNING logs"
fi

# Issue 4: Losers not in learning (survivorship bias)
LOSERS=$(sudo grep -cE "segment.*losses.*0|profit_factor.*0" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$LOSERS" -eq 0 ]; then
  echo "ℹ️  INFO: No loser tracking visible yet (may be too early)"
else
  echo "✅ Loser tracking active: $LOSERS logs"
fi

# Issue 5: CRITICAL - REAL orders placed
REAL=$(sudo grep -c "REAL_ORDER\|real_orders.*true" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$REAL" -gt 0 ]; then
  echo "❌ CRITICAL ISSUE: REAL orders detected!"
  ((ISSUES++))
  echo "   IMMEDIATE FIX: Service restart with rollback"
  sudo systemctl stop cryptomaster.service
  cd /opt/cryptomaster
  git log --oneline -3
  echo "   ROLLBACK COMMAND: git revert <Phase4A-commit>"
else
  echo "✅ Safety verified: ZERO REAL orders"
fi

# Issue 6: Service not running
if ! sudo systemctl is-active cryptomaster.service > /dev/null 2>&1; then
  echo "❌ CRITICAL ISSUE: Service not running"
  ((ISSUES++))
  echo "   IMMEDIATE FIX: Restarting service..."
  sudo systemctl restart cryptomaster.service
  sleep 3
else
  echo "✅ Service running"
fi

# Issue 7: Excessive errors in logs
ERROR_COUNT=$(sudo grep -cE "ERROR|CRITICAL|Exception" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$ERROR_COUNT" -gt 20 ]; then
  echo "⚠️  ISSUE 7: High error count ($ERROR_COUNT errors)"
  ((ISSUES++))
  echo "   Recent errors:"
  sudo grep -E "ERROR|CRITICAL" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null | tail -5 | sed 's/^/   /'
else
  echo "✅ Error count acceptable: $ERROR_COUNT"
fi

echo ""

# ============================================================================
# 2. ISSUE SUMMARY
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "ISSUE SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$ISSUES" -eq 0 ]; then
  echo "✅ NO ISSUES DETECTED - SYSTEM HEALTHY"
else
  echo "⚠️  $ISSUES ISSUES DETECTED"
  echo ""
  echo "Priority fixes:"
  echo "1. Check logs: tail -f /opt/cryptomaster/logs/cryptomaster.log"
  echo "2. Run health check: bash /tmp/phase4a_health_check.sh"
  echo "3. Consider rollback if REAL orders found"
fi

echo ""
echo "[$TIMESTAMP] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ============================================================================
# 3. RECOMMENDATIONS
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "NEXT ACTIONS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "Watch live logs:"
echo "  sudo tail -f /opt/cryptomaster/logs/cryptomaster.log | \\"
echo "    grep -E 'PAPER_ENTRY|trades_closed|learning_weight|ERROR'"
echo ""

echo "View monitoring log:"
echo "  tail -f /tmp/phase4a_monitoring_*.log"
echo ""

echo "Run full health check every 5 minutes:"
echo "  while true; do bash /tmp/phase4a_health_check.sh; sleep 300; done"
echo ""

echo "Report issues found:"
echo "  - Service not running → Restart and check logs for root cause"
echo "  - REAL orders → Immediate rollback to Phase 3"
echo "  - trades_closed=0 → Check close counting in runner.py"
echo "  - Entry starvation → Check cost-edge gate and expected_move"
echo "  - No learning feedback → Verify PolicyStateTracker wiring"
echo ""
