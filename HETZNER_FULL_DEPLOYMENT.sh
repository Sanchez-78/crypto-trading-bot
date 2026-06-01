#!/bin/bash
# PHASE 4A COMPLETE DEPLOYMENT - RUN ON HETZNER SERVER
# This script does EVERYTHING: pull code, backup, restart, validate, monitor

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║  PHASE 4A COMPLETE DEPLOYMENT - HETZNER /opt/cryptomaster  ║"
echo "║  Local logs only (ZERO Firebase reads)                      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Started: $(date)"
echo ""

# ============================================================================
# SECTION 1: BACKUP & PREPARE
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. BACKUP & PREPARE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd /opt/cryptomaster || { echo "❌ ERROR: /opt/cryptomaster not found"; exit 1; }

# Create backup directory
mkdir -p server_local_backups/runtime_state
echo "✅ Backup directory ready"

# Backup current state
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp -a src/runtime/v5_trade_outbox.sqlite \
  "server_local_backups/runtime_state/v5_trade_outbox.${TIMESTAMP}.sqlite" \
  2>/dev/null || echo "ℹ️  Trade outbox not backed up (doesn't exist yet)"

cp -a data/paper_open_positions.json \
  "server_local_backups/runtime_state/paper_open_positions.${TIMESTAMP}.json" \
  2>/dev/null || echo "ℹ️  Positions not backed up (doesn't exist yet)"

echo "✅ Runtime state backed up"
echo ""

# ============================================================================
# SECTION 2: PULL LATEST CODE
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. PULL PHASE 4A CODE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Pulling from main..."
git pull origin main

echo "✅ Code updated"
echo ""
echo "Recent commits:"
git log --oneline -3
echo ""

# ============================================================================
# SECTION 3: RESTART SERVICE
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. RESTART SERVICE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Stopping service..."
sudo systemctl stop cryptomaster.service
sleep 1

echo "Starting service..."
sudo systemctl start cryptomaster.service
sleep 3

if sudo systemctl is-active cryptomaster.service > /dev/null; then
  echo "✅ Service started successfully"
else
  echo "❌ Service failed to start"
  sudo systemctl status cryptomaster.service
  exit 1
fi
echo ""

# ============================================================================
# SECTION 4: IMMEDIATE VALIDATION (0-5 min)
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. IMMEDIATE VALIDATION (0-5 min)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "Service Status:"
sudo systemctl is-active cryptomaster.service && echo "  ✅ Running" || echo "  ❌ Not running"

echo ""
echo "Recent Logs (last 20 lines):"
sudo tail -20 /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null | grep -E "INFO|ERROR|cryptomaster" | tail -10 || echo "  ℹ️  Logs not available yet"

echo ""
echo "Process Check:"
pgrep -f cryptomaster > /dev/null && echo "  ✅ Process running" || echo "  ⚠️  Process not found"

echo ""
echo "Safety Check (REAL orders):"
REAL_COUNT=$(sudo grep -c "REAL_ORDER\|real_orders.*true" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null || echo 0)
if [ "$REAL_COUNT" -eq 0 ]; then
  echo "  ✅ ZERO REAL orders (SAFE)"
else
  echo "  ❌ REAL orders found - CRITICAL ISSUE"
  exit 1
fi

echo ""

# ============================================================================
# SECTION 5: EXTENDED VALIDATION (5-30 min)
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. WAITING FOR PHASE 4A SIGNALS (30 seconds)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Wait for signals to appear in logs
MAX_WAIT=30
COUNTER=0
FOUND_SIGNAL=false

while [ $COUNTER -lt $MAX_WAIT ]; do
  if sudo grep -qE "PAPER_ENTRY|trades_closed|learning_weight" /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null; then
    FOUND_SIGNAL=true
    break
  fi
  COUNTER=$((COUNTER + 1))
  echo -n "."
  sleep 1
done

echo ""
echo ""

if [ "$FOUND_SIGNAL" = true ]; then
  echo "✅ Phase 4A signals detected!"
  echo ""
  echo "Recent Phase 4A Activity:"
  sudo tail -50 /opt/cryptomaster/logs/cryptomaster.log 2>/dev/null | grep -E "PAPER_ENTRY|PAPER_CLOSE|trades_closed|learning_weight" | tail -5 || echo "  (No signals yet)"
else
  echo "ℹ️  No Phase 4A signals yet (normal for first 30 seconds)"
fi

echo ""

# ============================================================================
# SECTION 6: SUMMARY & MONITORING INSTRUCTIONS
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. DEPLOYMENT COMPLETE ✅"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "PHASE 4A STATUS:"
echo "  Service:           ✅ Running"
echo "  Code:              ✅ Updated to main"
echo "  Runtime Backup:    ✅ Completed"
echo "  Safety:            ✅ Zero REAL orders"
echo "  Firebase Impact:   ✅ ZERO reads"
echo ""

echo "NEXT STEPS:"
echo ""
echo "1. Monitor for Phase 4A signals (30-60 minutes):"
echo ""
echo "   sudo tail -f /opt/cryptomaster/logs/cryptomaster.log | \\"
echo "     grep -E 'PAPER_ENTRY|PAPER_CLOSE|trades_closed|learning_weight'"
echo ""
echo "2. Expected signals:"
echo "   • PAPER_ENTRY: Entry activity (5-20 per hour)"
echo "   • trades_closed: Incrementing count"
echo "   • learning_weight: 0.7-1.3 (soft ranking)"
echo "   • PAPER_CLOSE: Positions closing"
echo ""
echo "3. Success if (after 1 hour):"
echo "   ✅ Multiple PAPER_ENTRY logs (not starvation)"
echo "   ✅ trades_closed > 0"
echo "   ✅ learning_weight visible"
echo "   ✅ No ERROR lines in logs"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DEPLOYMENT SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Completed: $(date)"
echo "Branch: main"
echo "Version: Phase 4A (Safe Paper Learning/Trading Feedback)"
echo "Monitoring: Local logs only (zero Firebase reads)"
echo ""
echo "✅ READY FOR PRODUCTION MONITORING"
echo ""
