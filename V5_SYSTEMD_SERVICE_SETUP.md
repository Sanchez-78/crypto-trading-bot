# V5 PAPER Bot Systemd Service Setup

**Issue**: V5 bot startup fails with `google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found`

**Root Cause**: The systemd service `cryptomaster-v5-paper` needs Firebase credentials to be available in the environment when the bot starts.

---

## Solution: Configure Firebase Credentials in Systemd Service

The V5 bot (`python3 -m src.v5_bot.paper`) initializes Firebase during startup. It looks for credentials in this order:

1. **GOOGLE_APPLICATION_CREDENTIALS** environment variable (path to JSON credentials file)
2. **FIREBASE_KEY_BASE64** environment variable (base64-encoded JSON credentials)
3. **Google Cloud Application Default Credentials** (only available on GCP)

Since Hetzner is not on GCP, you must explicitly provide credentials via environment variable.

---

## Setup Instructions for Hetzner Admin

### Option A: Use GOOGLE_APPLICATION_CREDENTIALS (Recommended)

1. **Verify credentials file location** (should exist from legacy bot setup):
   ```bash
   ls -la /opt/cryptomaster/.env
   cat /opt/cryptomaster/.env | grep GOOGLE_APPLICATION_CREDENTIALS
   ```

2. **Create/update systemd service file** at `/etc/systemd/system/cryptomaster-v5-paper.service`:
   ```ini
   [Unit]
   Description=CryptoMaster V5 PAPER Bot
   After=network-online.target
   Wants=network-online.target
   
   [Service]
   Type=simple
   User=cryptomaster
   WorkingDirectory=/opt/cryptomaster_v5_validation
   
   # Environment: Point to Firebase credentials
   EnvironmentFile=/opt/cryptomaster/.env
   Environment="PYTHONUNBUFFERED=1"
   
   # Startup
   ExecStart=/opt/cryptomaster_v5_validation/venv/bin/python3 -m src.v5_bot.paper
   
   # Restart policy
   Restart=on-failure
   RestartSec=10
   StandardOutput=journal
   StandardError=journal
   
   [Install]
   WantedBy=multi-user.target
   ```

3. **Reload systemd** and restart the service:
   ```bash
   systemctl daemon-reload
   systemctl restart cryptomaster-v5-paper
   ```

4. **Verify credentials are available to the service**:
   ```bash
   systemctl show cryptomaster-v5-paper -p Environment
   # Should show GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
   ```

### Option B: Use FIREBASE_KEY_BASE64 (If file-based creds not available)

1. **Encode credentials to base64**:
   ```bash
   export FIREBASE_KEY_BASE64=$(cat /path/to/credentials.json | base64 -w0)
   echo "$FIREBASE_KEY_BASE64"
   ```

2. **Update systemd service** to use environment variable directly:
   ```bash
   systemctl set-environment FIREBASE_KEY_BASE64="<paste-base64-string-here>"
   ```

3. **Modify __main__.py** to use FIREBASE_KEY_BASE64 (requires code change if not already supported)

---

## Verification Checklist

After setting up credentials, verify:

```bash
# 1. Service is active
systemctl is-active cryptomaster-v5-paper
# Expected: active

# 2. Check recent logs for startup
journalctl -u cryptomaster-v5-paper -n 20 --no-pager
# Expected: See "Starting V5 PAPER Bot..." and "Connected to feeds for 5 symbols"
# NOT expected: "DefaultCredentialsError"

# 3. Verify bot is in main loop (logs every 1-5 seconds)
journalctl -u cryptomaster-v5-paper --since "10 seconds ago" | wc -l
# Expected: > 2 lines (should have multiple log entries)

# 4. Check process is running and consuming CPU
ps aux | grep "python3.*paper" | grep -v grep
# Expected: Process present, CPU > 0.0%
```

---

## Expected Log Output After Successful Setup

```
May 29 08:20:58 ubuntu-4gb-nbg1-1 v5-paper[1678912]: INFO:src.v5_bot.paper:Starting V5 PAPER Bot...
May 29 08:20:58 ubuntu-4gb-nbg1-1 v5-paper[1678912]: INFO:src.v5_bot.paper.runner:V5 PAPER Bot startup...
May 29 08:20:59 ubuntu-4gb-nbg1-1 v5-paper[1678912]: INFO:src.v5_bot.market.binance_usdm_feed:Connected to feeds for 5 symbols
May 29 08:20:59 ubuntu-4gb-nbg1-1 v5-paper[1678912]: INFO:src.v5_bot.paper.runner:Created epoch: epoch_20260529_082059
May 29 08:21:00 ubuntu-4gb-nbg1-1 v5-paper[1678912]: DEBUG:src.v5_bot.paper.runner:Processing market tick...
May 29 08:21:00 ubuntu-4gb-nbg1-1 v5-paper[1678912]: DEBUG:src.v5_bot.paper.runner:Evaluating entry signals...
```

**NOT these errors**:
```
google.auth.exceptions.DefaultCredentialsError
ImportError
ModuleNotFoundError
```

---

## Troubleshooting

If the bot still fails to start:

1. **Check environment variables in systemd**:
   ```bash
   systemctl show cryptomaster-v5-paper | grep Environment
   ```

2. **Test credentials loading manually**:
   ```bash
   cd /opt/cryptomaster_v5_validation
   source /opt/cryptomaster/.env
   export GOOGLE_APPLICATION_CREDENTIALS  # Should be set
   ./venv/bin/python3 -c "import os; print('GOOGLE_APPLICATION_CREDENTIALS:', os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))"
   ```

3. **Verify credentials file is readable by cryptomaster user**:
   ```bash
   ls -la $(echo $GOOGLE_APPLICATION_CREDENTIALS)
   # Check permissions - cryptomaster user must be able to read it
   ```

4. **Check full error trace**:
   ```bash
   journalctl -u cryptomaster-v5-paper -n 100 --no-pager
   ```

---

## Notes

- The credentials file is typically located at `/opt/cryptomaster/firebase-credentials.json` (check with legacy bot setup)
- The `EnvironmentFile` directive loads variables from `/opt/cryptomaster/.env` which should already exist from legacy bot deployment
- Credentials must be accessible to the `cryptomaster` system user that runs the service
- The bot requires read-only access to credentials (no write needed)

