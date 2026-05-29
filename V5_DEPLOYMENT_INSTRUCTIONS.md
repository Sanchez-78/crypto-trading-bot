# V5 Bot Deployment Instructions — Post-Fix

**Objective**: Deploy the __main__.py fix to Hetzner and restart the V5 PAPER bot  
**Estimated Time**: 5 minutes  
**Risk Level**: LOW (only adding missing entry point, no logic changes)

---

## DEPLOYMENT STEPS

### Step 1: Pull Latest Code on Hetzner
```bash
cd /opt/cryptomaster_v5_validation
git pull origin main
```

**Expected Output**:
```
From github.com:...CryptoMaster_srv
 * branch            main       -> FETCH_HEAD
   51afa2d...(new hash)  main       -> origin/main
Updating 51afa2d...(new hash)
Fast-forward
 src/v5_bot/paper/__main__.py | 33 ++++++++++++++++++++++++++++++++
 1 file changed, 33 insertions(+)
 create mode 100644 src/v5_bot/paper/__main__.py
```

### Step 2: Verify File Exists
```bash
ls -la /opt/cryptomaster_v5_validation/src/v5_bot/paper/__main__.py
```

**Expected**: File should exist with ~33 lines

### Step 3: Restart the Service
```bash
systemctl restart cryptomaster-v5-paper
```

**No output expected** (systemctl restart is silent on success)

### Step 4: Verify Service Started
```bash
systemctl status cryptomaster-v5-paper
```

**Expected Output**:
```
● cryptomaster-v5-paper.service - CryptoMaster V5 PAPER Bot
   Loaded: loaded (/etc/systemd/system/cryptomaster-v5-paper.service; enabled)
   Active: active (running) since ...
   Main PID: XXXX (python3)
   Tasks: N
   Memory: 50M-100M
   CPU: 0.0%-0.1%
```

### Step 5: Monitor Logs for Main Loop Execution
```bash
journalctl -u cryptomaster-v5-paper -f
```

**Expected Logs** (within 5 seconds of restart):
```
2026-05-29 08:15:xx UTC — src.v5_bot.paper — INFO — Starting V5 PAPER Bot...
2026-05-29 08:15:xx UTC — src.v5_bot.paper.runner — INFO — V5 PAPER Bot startup...
2026-05-29 08:15:xx UTC — src.v5_bot.market.binance_usdm_feed — INFO — Connected to feeds for 5 symbols
2026-05-29 08:15:xx UTC — src.v5_bot.paper.runner — INFO — Created epoch: epoch_YYYYMMDD_HHMMSS
2026-05-29 08:15:xx UTC — src.v5_bot.paper.runner — INFO — [Main loop iteration] Processing market tick for BTCUSDT...
2026-05-29 08:15:xx UTC — src.v5_bot.paper.runner — DEBUG — Evaluating entry signals for BTCUSDT...
2026-05-29 08:15:xx UTC — src.v5_bot.paper.runner — DEBUG — Checking exit conditions...
```

**If logs do NOT appear**: 
- Check for error messages: `journalctl -u cryptomaster-v5-paper -n 50`
- Verify Python environment: `python3 -c "import src.v5_bot.paper; print('OK')"`

### Step 6: Verify Quota Is Still Active
```bash
sqlite3 /opt/cryptomaster_v5_validation/runtime/v5_quota_usage.sqlite << EOF
.headers on
.mode column
SELECT state, reads_used, writes_used, reads_remaining, writes_remaining 
FROM quota_state 
ORDER BY timestamp DESC 
LIMIT 1;
EOF
```

**Expected Output**:
```
state      reads_used  writes_used  reads_remaining  writes_remaining
NORMAL     0           0            20000            10000
```

---

## MONITORING CHECKLIST

After restart, verify the following every 30 seconds for 5 minutes:

### ✅ Process Is Running
```bash
ps aux | grep "python3.*paper" | grep -v grep
# Should show: python3 -m src.v5_bot.paper (not grep)
```

### ✅ Logs Are Being Generated
```bash
journalctl -u cryptomaster-v5-paper --since "5 minutes ago" | wc -l
# Should show 50+ lines (main loop logs every 1-5 seconds)
```

### ✅ CPU Usage Is Normal (0.0%-0.5%)
```bash
ps aux | grep "python3.*paper" | awk '{print $3}' # %CPU column
# Should be < 0.5%
```

### ✅ Memory Usage Is Stable (50M-150M)
```bash
ps aux | grep "python3.*paper" | awk '{print $6}' # RSS column
# Should be stable, not growing
```

### ✅ Quota State Remains NORMAL
```bash
curl -s http://localhost:8080/v5/status | jq '.quota_state'
# Should show: "state": "NORMAL"
```

---

## EXPECTED TIMELINE

| Time | Event | Log Evidence |
|------|-------|--------------|
| 0s | Service restart | `[systemd] Starting CryptoMaster V5 PAPER Bot` |
| 1s | Process starts | `Starting V5 PAPER Bot...` |
| 2s | Feeds connect | `Connected to feeds for 5 symbols` |
| 3s | Epoch created | `Created epoch: epoch_...` |
| 4s+ | Main loop | `Processing market tick...` every 1-5s |
| 30s+ | Market evaluation | `Entry signal for BTCUSDT...` (if conditions met) |
| 5-60min | First trade | `Entry ...: BTCUSDT BUY @ 42345.67` |

---

## ROLLBACK (If Issues Occur)

If the bot doesn't start correctly after deployment:

```bash
# Revert to previous commit
cd /opt/cryptomaster_v5_validation
git log --oneline -5
git reset --hard <commit-before-__main__.py>

# Restart
systemctl restart cryptomaster-v5-paper

# Check status
journalctl -u cryptomaster-v5-paper -n 20
```

**Note**: This will revert to the broken state (bot won't enter main loop). Only use if the fix itself causes a Python error.

---

## SUCCESS CRITERIA

✅ **Deployment is successful if:**
1. Service status shows `active (running)`
2. Logs appear in journalctl every 1-5 seconds (main loop is running)
3. No Python errors in logs
4. CPU usage is 0.0%-0.5%
5. Memory is stable at 50M-150M
6. Quota state is `NORMAL`
7. Within 30 minutes: first trade entry or cost-edge rejection logged

✅ **First trade cycle is complete if:**
1. Entry: `Entry ...: SYMBOL SIDE @ price` logged
2. Exit: `Exit ...: REASON @ price` logged  
3. Learning: `LEARNING_UPDATE...` logged to Firebase

---

## SUPPORT

If deployment fails:
1. Check logs: `journalctl -u cryptomaster-v5-paper -n 100 | grep -i error`
2. Verify Python environment: `source /opt/cryptomaster_v5_validation/venv/bin/activate && python3 -c "from src.v5_bot.paper import V5BotRunner; print('OK')"`
3. Check git status: `cd /opt/cryptomaster_v5_validation && git status`
4. If still stuck: `systemctl stop cryptomaster-v5-paper` and restart from Step 1

---

**Status**: Ready for deployment  
**Risk**: Minimal (adding missing entry point)  
**Rollback**: Available and documented above
