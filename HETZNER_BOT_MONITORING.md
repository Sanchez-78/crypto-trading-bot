# V5 Bot Monitoring on Hetzner Server

## Bot Status Overview

### Current Bot Server
- **IP**: 78.47.2.198
- **Port**: 5000 (metrics API)
- **SSH**: `ssh -i ~/.ssh/hetzner_root root@78.47.2.198`

---

## How to Check Bot Status

### Quick Method: Bash Script

```bash
# SSH into Hetzner
ssh -i ~/.ssh/hetzner_root root@78.47.2.198

# Run monitoring script
bash -s < <(cat scripts/monitor_bot_status.sh)

# Or download script first
curl https://raw.githubusercontent.com/yourrepo/scripts/monitor_bot_status.sh | bash
```

**Output includes:**
- Process status (running/stopped)
- Metrics API server status
- Bot logs (last 20 lines)
- Resource usage (CPU, memory, threads)
- API connectivity test
- Firebase quota status
- Server info (uptime, memory, disk)

### Detailed Method: Python Analysis

```bash
# SSH into Hetzner
ssh -i ~/.ssh/hetzner_root root@78.47.2.198

# Run Python analyzer
python3 bot_status_analyzer.py

# Or specify custom API URL
python3 bot_status_analyzer.py http://localhost:5000
```

**Output shows:**
- ✓ Bot status (running/stopped)
- 💹 Trading activity (entries, success rate, trades closed)
- 📈 Current positions (count, notional value)
- 🎯 Session performance (PnL, win rate, profit factor)
- 🔥 Firebase quota usage
- 📡 Current trading signals per symbol
- 🎓 Learning metrics (win rate, PnL, per-symbol breakdown)
- 📋 Recent trades with entry/exit details

---

## Direct API Calls

### Check Bot Health

```bash
curl -s http://78.47.2.198:5000/health | python3 -m json.tool

# Example response:
{
  "status": "healthy",
  "running": true,
  "feed_connected": true,
  "firebase_quota_ok": true
}
```

### Get Metrics Snapshot

```bash
curl -s http://78.47.2.198:5000/metrics | python3 -m json.tool

# Key fields to check:
# - running: true/false
# - open_positions: number of open trades
# - total_net_pnl_usd: profit/loss
# - win_rate: percentage of winning trades
# - entries_attempted, entries_successful
# - quota_state: NORMAL/WARNING/EXHAUSTED
```

### Get Complete Learning History

```bash
curl -s http://78.47.2.198:5000/metrics/learning-history | python3 -m json.tool

# Key fields:
# - total_trades_closed: total trades executed
# - total_wins, total_losses: win/loss counts
# - win_rate: overall success rate
# - total_net_pnl_usd: cumulative profit
# - per_symbol_summary: breakdown by trading symbol
# - closed_trades: detailed history of each trade
```

### Check Signals

```bash
curl -s http://78.47.2.198:5000/metrics/signals | python3 -m json.tool

# Shows current trading signals for each symbol
# ACCEPTED or REJECTED signals
# Current market regime
# Bid-ask spreads
# Mid prices
```

---

## View Bot Logs on Hetzner

### Method 1: Tail Live Logs

```bash
# SSH into server
ssh -i ~/.ssh/hetzner_root root@78.47.2.198

# Watch logs in real-time (last 100 lines, follow)
tail -f /root/v5_bot.log

# Or last 50 lines
tail -50 /root/v5_bot.log

# Stop with Ctrl+C
```

### Method 2: Search Logs

```bash
# Find all ERROR lines
grep "ERROR" /root/v5_bot.log

# Find all signal rejections
grep "REJECTED" /root/v5_bot.log

# Find successful entries
grep "Entry.*:" /root/v5_bot.log

# Find trades closed
grep "Exit" /root/v5_bot.log

# Count trades closed today
grep "Exit" /root/v5_bot.log | wc -l

# Show logs from last 10 minutes
grep "$(date -d '10 minutes ago' '+%Y-%m-%d %H')" /root/v5_bot.log
```

### Method 3: Systemd Journal (if running as service)

```bash
# View bot service logs
journalctl -u v5-bot -n 100 --no-pager

# Follow logs live
journalctl -u v5-bot -f

# View only errors
journalctl -u v5-bot -p err
```

### Method 4: Python Log Parser

```bash
# Create log analyzer
cat > /root/analyze_logs.py << 'EOF'
import re
from datetime import datetime, timedelta

def analyze_logs(filename='/root/v5_bot.log', hours=1):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    entries_attempted = 0
    entries_successful = 0
    entries_rejected = 0
    trades_closed = 0
    errors = []
    
    with open(filename) as f:
        for line in f:
            if "[Entry" in line and "attempted" in line:
                entries_attempted += 1
            elif "[Entry" in line and "successful" in line:
                entries_successful += 1
            elif "[Entry" in line and "rejected" in line:
                entries_rejected += 1
            elif "Exit" in line:
                trades_closed += 1
            elif "ERROR" in line or "error" in line:
                errors.append(line.strip())
    
    print(f"Last {hours} hour(s) statistics:")
    print(f"Entries attempted: {entries_attempted}")
    print(f"Entries successful: {entries_successful}")
    print(f"Entries rejected: {entries_rejected}")
    print(f"Trades closed: {trades_closed}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for error in errors[-5:]:  # Last 5 errors
            print(f"  - {error}")

if __name__ == "__main__":
    import sys
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    analyze_logs(hours=hours)
EOF

# Run analyzer (last 24 hours)
python3 /root/analyze_logs.py 24
```

---

## Monitoring Dashboard

### Create Real-Time Dashboard

```bash
# Option 1: Watch command (updates every 2 seconds)
watch -n 2 'echo "=== V5 Bot Status ==="; curl -s http://localhost:5000/metrics | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Running: {data[\"running\"]}\")
print(f\"Open positions: {data[\"open_positions\"]}\")
print(f\"PnL: \${data[\"total_net_pnl_usd\"]:.2f}\")
print(f\"Entries: {data[\"entries_successful\"]}/{data[\"entries_attempted\"]}\")
print(f\"Trades closed: {data[\"trades_closed\"]}\")
print(f\"Quota: {data[\"quota_state\"]}\")
"'

# Press Ctrl+C to exit
```

### Create Persistent Log Viewer

```bash
# Screen session (persistent, detachable)
screen -S v5bot-monitor

# Inside screen, run:
tail -f /root/v5_bot.log

# Detach: Ctrl+A then D
# Reattach: screen -r v5bot-monitor
```

---

## Understanding Bot Status

### Trading Metrics Explained

| Metric | Meaning | Good Range |
|--------|---------|-----------|
| entries_attempted | Total entry signals evaluated | > 0 |
| entries_successful | Entries that passed cost-edge gate | > 50% of attempted |
| entries_rejected_by_gate | Entries rejected due to insufficient edge | < 50% of attempted |
| open_positions | Current open trades | 0-3 (max 3) |
| total_net_pnl_usd | Profit/loss after fees | > 0 |
| win_rate | Percentage of winning trades | > 50% |
| profit_factor | Total wins / total losses | > 1.0 |

### Learning Metrics Explained

| Metric | Meaning | Shows |
|--------|---------|-------|
| total_trades_closed | Total completed trades (all-time) | Historical performance |
| total_wins / total_losses | Count of profitable vs losing trades | Win distribution |
| win_rate | Percentage of winning trades | Overall success rate |
| total_net_pnl_usd | Cumulative profit/loss | Total earnings |
| per_symbol_summary | Breakdown by trading pair | Which symbols work best |
| avg_pnl_per_trade | Average profit per trade | Trade quality |
| best_trade_pnl_usd | Largest single win | Profit potential |
| worst_trade_pnl_usd | Largest single loss | Risk level |

### Firebase Quota Explained

| Status | Usage | Action |
|--------|-------|--------|
| NORMAL | < 70% of limit | OK, no action |
| WARNING | 70-90% of limit | Monitor closely |
| EXHAUSTED | > 90% of limit | Reduce API calls or wait for reset |

**Daily Limits** (resets at midnight PT = 9:00 GMT+2):
- Reads: 20,000/day (typical usage: 300-1200/day)
- Writes: 10,000/day (typical usage: 200-600/day)

---

## Troubleshooting

### Bot Not Running

```bash
# Check if process exists
ps aux | grep python | grep v5_bot

# If not, check last lines of log for errors
tail -20 /root/v5_bot.log

# Restart bot
cd /root && python3 -m src.v5_bot.paper > v5_bot.log 2>&1 &
```

### No API Response

```bash
# Test connectivity
curl -v http://localhost:5000/health

# Check if port 5000 is open
netstat -tlnp | grep 5000

# Check firewall
ufw status
ufw allow 5000/tcp
```

### Firebase Quota Exhausted

```bash
# Check current usage
curl -s http://localhost:5000/metrics/firebase | python3 -m json.tool

# If exhausted, options:
# 1. Wait for quota reset (midnight PT)
# 2. Reduce logging frequency
# 3. Upgrade Firebase plan
```

### Trades Not Closing

```bash
# Check exit logs
grep "Exit" /root/v5_bot.log | tail -10

# Check if exit evaluator is working
grep "Exit condition" /root/v5_bot.log | tail -5

# Check position hold time
grep "hold_seconds" /root/v5_bot.log | tail -5
```

### High CPU/Memory Usage

```bash
# Monitor resource usage
watch -n 1 'ps aux | grep python | grep v5_bot'

# If high, check:
# 1. Number of trades (memory grows with history)
# 2. Firebase sync frequency
# 3. Logging level
# 4. Number of strategies being evaluated

# Restart if needed
pkill -f "python.*v5_bot"
cd /root && python3 -m src.v5_bot.paper > v5_bot.log 2>&1 &
```

---

## Automated Monitoring (Optional)

### Cron Job for Status Checks

```bash
# Edit crontab
crontab -e

# Add (checks status every hour, logs to file):
0 * * * * python3 /root/bot_status_analyzer.py >> /root/bot_status.log 2>&1

# View status history
tail -100 /root/bot_status.log
```

### Email Alerts on Errors

```bash
# Install mail utility if needed
apt-get install mailutils

# Create alert script
cat > /root/check_bot_health.sh << 'EOF'
#!/bin/bash
if ! curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo "Bot is DOWN at $(date)" | mail -s "V5 Bot Alert" admin@example.com
fi
EOF

# Add to crontab
*/5 * * * * bash /root/check_bot_health.sh
```

---

## Summary

**To check bot status:**

```bash
# Quick check
curl -s http://78.47.2.198:5000/health | python3 -m json.tool

# Detailed analysis
python3 /root/bot_status_analyzer.py

# View logs
ssh -i ~/.ssh/hetzner_root root@78.47.2.198 'tail -f /root/v5_bot.log'

# Full diagnostic
bash <(cat scripts/monitor_bot_status.sh)
```

**Key Metrics to Watch:**
- ✓ Running status (true/false)
- 📊 Open positions (should be 0-3)
- 💰 Total PnL (should be positive)
- 📈 Win rate (should be > 50%)
- 🔥 Firebase quota (should be NORMAL)
- 📡 Feed connected (should be true)

All tools are ready to use - just run the scripts and analyze the output!
