#!/bin/bash
# V10.27 HOTFIX: Correct systemd override.conf parameters on Hetzner
# This script fixes the stale override.conf that still has PAPER_MAX_POSITION_AGE_S=900

set -e

SERVICE_DIR="/etc/systemd/system/cryptomaster.service.d"
OVERRIDE_CONF="$SERVICE_DIR/override.conf"

echo "[DEPLOY] V10.27 Systemd Override Fix"
echo "Service directory: $SERVICE_DIR"

# Check if override.conf exists
if [ ! -f "$OVERRIDE_CONF" ]; then
    echo "[ERROR] $OVERRIDE_CONF not found!"
    exit 1
fi

# Backup original
cp "$OVERRIDE_CONF" "$OVERRIDE_CONF.backup.$(date +%s)"
echo "[OK] Backup created"

# Update PAPER_MAX_POSITION_AGE_S from 900 to 600
sed -i 's/PAPER_MAX_POSITION_AGE_S=900/PAPER_MAX_POSITION_AGE_S=600/g' "$OVERRIDE_CONF"

# Verify change
if grep -q "PAPER_MAX_POSITION_AGE_S=600" "$OVERRIDE_CONF"; then
    echo "[OK] PAPER_MAX_POSITION_AGE_S updated to 600"
else
    echo "[ERROR] Update failed"
    exit 1
fi

# Reload systemd
systemctl daemon-reload
echo "[OK] systemd daemon reloaded"

# Restart service
systemctl restart cryptomaster.service
echo "[OK] cryptomaster.service restarted"

# Verify service is running
sleep 2
if systemctl is-active --quiet cryptomaster.service; then
    echo "[OK] Service is running"
    journalctl -u cryptomaster.service -n 5 --no-pager
else
    echo "[ERROR] Service failed to start"
    exit 1
fi

echo "[SUCCESS] V10.27 systemd override fix deployed"
