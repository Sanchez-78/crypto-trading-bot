#!/bin/bash
# Post-Deployment Verification Script
# Automatically runs after every deployment to verify dashboard is functional

set -e

echo "=========================================="
echo "🔍 POST-DEPLOYMENT VERIFICATION"
echo "=========================================="
echo ""

# Wait for services to start
echo "Waiting for services to stabilize..."
sleep 3

# Check dashboard service
echo "Checking dashboard service..."
if pgrep -f "dashboard_web.py" > /dev/null; then
    echo "✅ Dashboard service running"
else
    echo "❌ Dashboard service NOT running!"
    echo "Starting dashboard..."
    cd /opt/cryptomaster
    nohup /opt/cryptomaster/venv/bin/python3 -u src/services/dashboard_web.py > /tmp/dashboard.log 2>&1 &
    sleep 3
fi

# Check main bot service
echo "Checking cryptomaster bot service..."
if systemctl is-active --quiet cryptomaster.service; then
    echo "✅ Bot service running"
else
    echo "⚠️  Bot service status unknown"
fi

# Run dashboard health check
echo ""
echo "Running dashboard health checks..."
cd /opt/cryptomaster

/opt/cryptomaster/venv/bin/python3 dashboard_health_check.py
HEALTH_RESULT=$?

echo ""
if [ $HEALTH_RESULT -eq 0 ]; then
    echo "=========================================="
    echo "✅ DEPLOYMENT VERIFIED - All systems OK"
    echo "=========================================="
    exit 0
else
    echo "=========================================="
    echo "⚠️  DEPLOYMENT ISSUES DETECTED"
    echo "Check dashboard logs: tail -50 /tmp/dashboard.log"
    echo "=========================================="
    exit 1
fi
