#!/bin/bash

# V5 Bot Monitoring Script for Hetzner Server
# Usage: ssh root@78.47.2.198 'bash -s' < monitor_bot_status.sh

echo "==============================================="
echo "V5 BOT STATUS MONITORING"
echo "==============================================="
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Check if V5 Bot process is running
echo "1. PROCESS STATUS"
echo "---"
if pgrep -f "python.*v5_bot.*paper" > /dev/null; then
    echo "✓ V5 Bot is RUNNING"
    ps aux | grep -E "python.*v5_bot.*paper" | grep -v grep | head -1
    BOT_PID=$(pgrep -f "python.*v5_bot.*paper")
else
    echo "✗ V5 Bot is STOPPED"
    echo "  Last 5 lines of bot error log:"
    if [ -f "/root/v5_bot.log" ]; then
        tail -5 /root/v5_bot.log
    else
        echo "  No log file found"
    fi
fi
echo ""

# Check if metrics HTTP server is running (port 5000)
echo "2. METRICS API SERVER (Port 5000)"
echo "---"
if netstat -tlnp 2>/dev/null | grep -q ":5000 "; then
    echo "✓ Metrics API is LISTENING on port 5000"
    curl -s http://localhost:5000/health | python3 -m json.tool 2>/dev/null || echo "  (Could not connect locally)"
else
    echo "✗ Metrics API is NOT listening on port 5000"
fi
echo ""

# Check bot logs
echo "3. BOT LOGS (Last 20 lines)"
echo "---"
if [ -f "/root/v5_bot.log" ]; then
    tail -20 /root/v5_bot.log
else
    echo "No log file at /root/v5_bot.log"
    echo "Checking systemd journal..."
    journalctl -u v5-bot -n 20 --no-pager 2>/dev/null || echo "No systemd service found"
fi
echo ""

# Check resource usage
echo "4. RESOURCE USAGE"
echo "---"
if [ -n "$BOT_PID" ]; then
    echo "Process ID: $BOT_PID"
    ps -p $BOT_PID -o %cpu,%mem,rss,vsz,comm
    echo ""
    echo "Threads: $(ps -p $BOT_PID -o nlwp=)"
fi
echo ""

# Check API connectivity
echo "5. API CONNECTIVITY TEST"
echo "---"
echo "Testing /metrics endpoint..."
if curl -s -m 5 http://localhost:5000/metrics > /tmp/metrics.json 2>/dev/null; then
    echo "✓ /metrics endpoint responds"
    TRADES=$(python3 -c "import json; d=json.load(open('/tmp/metrics.json')); print(d.get('trades_closed', 0))" 2>/dev/null)
    OPEN=$(python3 -c "import json; d=json.load(open('/tmp/metrics.json')); print(d.get('open_positions', 0))" 2>/dev/null)
    PNL=$(python3 -c "import json; d=json.load(open('/tmp/metrics.json')); print(d.get('total_net_pnl_usd', 0))" 2>/dev/null)
    echo "  Trades closed: $TRADES"
    echo "  Open positions: $OPEN"
    echo "  Total PnL: \$${PNL}"
else
    echo "✗ /metrics endpoint did NOT respond"
fi
echo ""

echo "Testing /metrics/learning-history endpoint..."
if curl -s -m 5 http://localhost:5000/metrics/learning-history > /tmp/learning.json 2>/dev/null; then
    echo "✓ /metrics/learning-history endpoint responds"
    TOTAL=$(python3 -c "import json; d=json.load(open('/tmp/learning.json')); print(d.get('total_trades_closed', 0))" 2>/dev/null)
    WINS=$(python3 -c "import json; d=json.load(open('/tmp/learning.json')); print(d.get('total_wins', 0))" 2>/dev/null)
    WINRATE=$(python3 -c "import json; d=json.load(open('/tmp/learning.json')); wr=d.get('win_rate', 0); print(f'{wr*100:.1f}%')" 2>/dev/null)
    echo "  Total trades: $TOTAL"
    echo "  Wins: $WINS"
    echo "  Win rate: $WINRATE"
else
    echo "✗ /metrics/learning-history endpoint did NOT respond"
fi
echo ""

# Check Firebase connectivity
echo "6. FIREBASE QUOTA STATUS"
echo "---"
if [ -f "/tmp/metrics.json" ]; then
    python3 << 'EOF'
import json
try:
    with open('/tmp/metrics.json') as f:
        data = json.load(f)
    reads_used = data.get('quota_reads_used', 0)
    reads_limit = data.get('quota_reads_limit', 20000)
    writes_used = data.get('quota_writes_used', 0)
    writes_limit = data.get('quota_writes_limit', 10000)
    quota_state = data.get('quota_state', 'UNKNOWN')

    reads_pct = (reads_used / reads_limit * 100) if reads_limit > 0 else 0
    writes_pct = (writes_used / writes_limit * 100) if writes_limit > 0 else 0

    print(f"State: {quota_state}")
    print(f"Reads: {reads_used}/{reads_limit} ({reads_pct:.1f}%)")
    print(f"Writes: {writes_used}/{writes_limit} ({writes_pct:.1f}%)")
except Exception as e:
    print(f"Error reading quota: {e}")
EOF
fi
echo ""

# System info
echo "7. SERVER INFO"
echo "---"
echo "Hostname: $(hostname)"
echo "Time: $(date)"
echo "Uptime: $(uptime | awk -F'up' '{print $2}' | cut -d',' -f1)"
echo "CPU Cores: $(nproc)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"
echo "Disk: $(df -h / | tail -1 | awk '{print $2, "used:", $3, "available:", $4}')"
echo ""

echo "==============================================="
