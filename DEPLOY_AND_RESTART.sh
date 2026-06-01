#!/bin/bash
# Phase 4A Deployment: Backup & Restart Service on /opt/cryptomaster
# Run this on the Hetzner server with: bash DEPLOY_AND_RESTART.sh

set -e

echo "=== PHASE 4A DEPLOYMENT: RESTART & VALIDATION ==="
echo "Time: $(date)"
echo ""

# Navigate to deployment directory
cd /opt/cryptomaster || { echo "ERROR: /opt/cryptomaster not found"; exit 1; }

# Create backup directory
mkdir -p server_local_backups/runtime_state
echo "✅ Backup directory created"

# Backup current runtime state
echo "Backing up runtime state..."
cp -a src/runtime/v5_trade_outbox.sqlite \
  "server_local_backups/runtime_state/v5_trade_outbox.before_phase4a_restart.$(date +%Y%m%d_%H%M%S).sqlite" \
  2>/dev/null || echo "⚠️  Trade outbox backup skipped (file may not exist yet)"

cp -a data/paper_open_positions.json \
  "server_local_backups/runtime_state/paper_open_positions.before_phase4a_restart.$(date +%Y%m%d_%H%M%S).json" \
  2>/dev/null || echo "⚠️  Paper positions backup skipped"

echo "✅ Runtime state backed up"
echo ""

# Restart service
echo "Restarting cryptomaster service..."
sudo systemctl restart cryptomaster.service
echo "✅ Restart signal sent"

# Wait for service to start
sleep 3

# Check status
echo ""
echo "=== SERVICE STATUS ==="
sudo systemctl status cryptomaster.service --no-pager -l | head -20
echo ""

# Show recent logs
echo "=== RECENT SERVICE LOGS (last 30 lines) ==="
sudo journalctl -u cryptomaster.service -n 30 --no-pager | tail -30
echo ""

# Verify process is running
echo "=== PROCESS VERIFICATION ==="
if pgrep -f cryptomaster > /dev/null; then
  echo "✅ Process is running"
  ps aux | grep cryptomaster | grep -v grep
else
  echo "❌ ERROR: Process not running!"
  exit 1
fi

echo ""
echo "=== INITIAL STATE CHECK ==="
echo "Paper positions file:"
if [ -f data/paper_open_positions.json ]; then
  echo "  ✅ File exists: $(ls -lh data/paper_open_positions.json | awk '{print $5, $9}')"
  echo "  Content preview:"
  head -c 200 data/paper_open_positions.json && echo ""
else
  echo "  ℹ️  No positions file (trading not yet started)"
fi

echo ""
echo "=== DEPLOYMENT COMPLETE ==="
echo "Service: $(systemctl is-active cryptomaster.service)"
echo "Status: Ready for monitoring"
echo ""
echo "Next: Monitor logs for Phase 4A signals:"
echo "  - trades_closed > 0 (after 30 min)"
echo "  - learning_weight visible (0.7-1.3)"
echo "  - PAPER_ENTRY logs (entry activity)"
echo ""
echo "Command to monitor:"
echo "  sudo tail -f /opt/cryptomaster/logs/cryptomaster.log | grep -E 'PAPER_ENTRY|trades_closed|learning_weight'"
