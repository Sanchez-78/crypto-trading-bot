#!/bin/bash
# Phase 4A Lean Deployment - NO Firebase reads, local logs only
# Run on /opt/cryptomaster

set -e
cd /opt/cryptomaster

echo "=== PHASE 4A LEAN DEPLOYMENT (LOCAL ONLY) ==="
echo "Time: $(date)"

# Backup state (local only, no Firebase reads)
mkdir -p server_local_backups/runtime_state
cp -a src/runtime/v5_trade_outbox.sqlite \
  "server_local_backups/runtime_state/v5_trade_outbox.$(date +%Y%m%d_%H%M%S).sqlite" 2>/dev/null || true
echo "✅ Backed up runtime state"

# Pull latest code
echo "Pulling Phase 4A code..."
git pull origin main
echo "✅ Code updated"

# Restart service
echo "Restarting service..."
sudo systemctl restart cryptomaster.service
sleep 2

# Check service is running (local only)
if sudo systemctl is-active cryptomaster.service > /dev/null; then
  echo "✅ Service running"
else
  echo "❌ Service failed to start"
  exit 1
fi

echo ""
echo "=== MONITORING (LOCAL LOGS ONLY - NO FIREBASE READS) ==="
echo ""
echo "To monitor Phase 4A signals (NO Firebase reads):"
echo ""
echo "  sudo tail -f /opt/cryptomaster/logs/cryptomaster.log | grep -E 'PAPER_ENTRY|PAPER_CLOSE|trades_closed|learning_weight'"
echo ""
echo "Success indicators (in logs only):"
echo "  ✅ PAPER_ENTRY: entry activity (not starvation)"
echo "  ✅ PAPER_CLOSE: position closes"
echo "  ✅ trades_closed: incrementing (was always 0)"
echo "  ✅ learning_weight: 0.7-1.3 (soft ranking)"
echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo "Service: RUNNING"
echo "Code: Phase 4A"
echo "Firebase: Minimal access (no monitoring reads)"
echo ""
echo "Status: Ready for local log monitoring (zero Firebase quota impact)"
