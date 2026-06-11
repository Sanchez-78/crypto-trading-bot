# CryptoMaster Dashboard V2 - Complete Architecture

## Problem with V1
- Flask/venv kept breaking
- Complex systemd services failing
- Old code scattered everywhere
- Multiple conflicting versions

## V2 Solution: Minimal Pure Python HTTP Server

### Architecture

```
┌─────────────────────────────────────────────────────┐
│ Browser (http://78.47.2.198:9999)                  │
└────────────────┬────────────────────────────────────┘
                 │ HTTP
                 ▼
        ┌────────────────────┐
        │  dashboard_v2.py   │ (Pure Python HTTP Server)
        │  - No Flask        │
        │  - No venv         │
        │  - Single file     │
        └────────┬───────────┘
                 │ Proxy to
                 ▼
        ┌────────────────────┐
        │ Cryptomaster API   │
        │ (localhost:5000)   │
        │ /api/dashboard/    │
        │ metrics            │
        └────────────────────┘
```

### Key Features
1. **Single Python file** - no dependencies beyond stdlib
2. **HTTP server only** - no Flask, no complex frameworks
3. **Pure JSON proxy** - just forwards cryptomaster API
4. **Simple HTML** - basic real-time display
5. **Port 9999** - unique port to avoid conflicts

### File Structure
```
/opt/cryptomaster/
├── dashboard_v2.py          ← ONLY dashboard file (delete all others)
└── (all old dashboard files deleted)
```

### Installation & Startup
```bash
# Clean start
pkill -9 -f dashboard 2>/dev/null || true
rm -rf /opt/cryptomaster/*dashboard* /opt/cryptomaster/*proxy* 2>/dev/null || true

# Start V2
cd /opt/cryptomaster
nohup /usr/bin/python3 dashboard_v2.py > /tmp/dashboard_v2.log 2>&1 &

# Verify
curl http://localhost:9999/
curl http://localhost:9999/api/metrics
```

### What It Does
1. **Listen on port 9999**
2. **Serve HTML** at `/`
3. **Proxy metrics** at `/api/metrics` → cryptomaster 5000
4. **Auto-refresh** every 5 seconds in browser
5. **No dependencies** - uses only Python stdlib

### Why It Works (Forever)
- ✅ No Flask to break
- ✅ No venv issues
- ✅ Pure Python HTTP (built-in)
- ✅ Single file (easy to debug)
- ✅ No systemd complexity
- ✅ Just `nohup python3 dashboard_v2.py &`

### Permanent Startup (One-liner in crontab)
```bash
@reboot nohup /usr/bin/python3 /opt/cryptomaster/dashboard_v2.py > /tmp/dashboard_v2.log 2>&1 &
```

### Access
```
http://78.47.2.198:9999
```

---

**THIS IS THE FINAL VERSION. DELETE ALL OTHER DASHBOARD CODE.**
