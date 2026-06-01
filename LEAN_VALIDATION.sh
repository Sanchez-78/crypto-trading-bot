#!/bin/bash
# Phase 4A Lean Validation - LOCAL LOGS ONLY, ZERO Firebase reads
# Run on /opt/cryptomaster after deployment

echo "=== PHASE 4A LEAN VALIDATION ==="
echo "Time: $(date)"
echo ""

# 1. Service running check (local only)
echo "1. Service Status:"
sudo systemctl is-active cryptomaster.service && echo "   ✅ Running" || echo "   ❌ Failed"
echo ""

# 2. Log monitoring (local only, no Firebase)
echo "2. Recent Activity (last 20 log lines):"
sudo tail -20 /opt/cryptomaster/logs/cryptomaster.log | grep -E "PAPER_ENTRY|PAPER_CLOSE|trades_closed|learning_weight" || echo "   ℹ️  No Phase 4A signals yet (normal if <5 min)"
echo ""

# 3. Count entries (local logs only)
ENTRY_COUNT=$(sudo grep -c "PAPER_ENTRY" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
echo "3. Entry Count: $ENTRY_COUNT entries logged"
if [ "$ENTRY_COUNT" -gt 0 ]; then
  echo "   ✅ Entries occurring (not starvation)"
else
  echo "   ℹ️  Waiting for first entry"
fi
echo ""

# 4. Check for errors (local logs only)
ERROR_COUNT=$(sudo grep -cE "ERROR|Exception|Traceback" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
echo "4. Error Check: $ERROR_COUNT errors in logs"
if [ "$ERROR_COUNT" -eq 0 ]; then
  echo "   ✅ No errors"
else
  echo "   ⚠️  Review errors: sudo grep -E 'ERROR|Exception' /opt/cryptomaster/logs/cryptomaster.log | head -10"
fi
echo ""

# 5. REAL order check (critical safety - local logs only)
REAL_CHECK=$(sudo grep -cE "REAL_ORDER|real_orders.*true" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
echo "5. Safety Check (REAL orders):"
if [ "$REAL_CHECK" -eq 0 ]; then
  echo "   ✅ ZERO REAL orders (safe)"
else
  echo "   ❌ REAL orders found - ROLLBACK IMMEDIATELY"
fi
echo ""

echo "=== SUMMARY ==="
echo "Status: Monitoring via local logs only"
echo "Firebase: No reads (quota safe)"
echo "Next: Watch logs in real-time:"
echo ""
echo "  sudo tail -f /opt/cryptomaster/logs/cryptomaster.log | \\\"
echo "    grep -E 'PAPER_ENTRY|PAPER_CLOSE|trades_closed|learning_weight'"
echo ""
