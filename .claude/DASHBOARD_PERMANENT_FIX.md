# Dashboard Permanent Fix (v1)

## Problem
Dashboard service crashes with Flask import errors or venv issues.
Systemd auto-restart loops failing (3+ restart limit exceeded).

## Root Cause
- Flask venv gets corrupted
- Systemd service tries to run development Flask server
- No proper production WSGI server (Gunicorn)
- No error recovery mechanism

## Permanent Solution: Gunicorn + Systemd + Health Check

### Step 1: Install Gunicorn
```bash
/opt/cryptomaster/venv/bin/pip install gunicorn -q
```

### Step 2: Update service to use Gunicorn
```ini
[Service]
ExecStart=/opt/cryptomaster/venv/bin/gunicorn \
  --bind 0.0.0.0:5001 \
  --workers 2 \
  --timeout 30 \
  --access-logfile - \
  --error-logfile - \
  src.services.dashboard_web:app

Restart=always
RestartSec=5
StartLimitInterval=60
StartLimitBurst=3
```

### Step 3: Add Health Check
Systemd will monitor port 5001 health.

### Never-Break Rules
1. ✅ Use Gunicorn (not Flask dev server)
2. ✅ Set ExecStart to Gunicorn command
3. ✅ Restart=always with StartLimitBurst=3
4. ✅ Always test: `curl http://localhost:5001/api/dashboard/metrics`
5. ✅ Check logs: `journalctl -u cryptomaster-dashboard.service -f`
6. ✅ If broken, ALWAYS check venv Flask first: `/opt/cryptomaster/venv/bin/python3 -c 'from flask import Flask'`

### Deploy Script
```bash
# Stop service
systemctl stop cryptomaster-dashboard.service

# Install gunicorn
/opt/cryptomaster/venv/bin/pip install gunicorn

# Update service file with ExecStart=gunicorn ...
# (see systemd section above)

# Reload and restart
systemctl daemon-reload
systemctl restart cryptomaster-dashboard.service
sleep 5

# Verify
curl http://localhost:5001/api/dashboard/metrics
```

## Documentation
This file documents the permanent solution.
**DO NOT CHANGE** unless explicitly tested and verified.
