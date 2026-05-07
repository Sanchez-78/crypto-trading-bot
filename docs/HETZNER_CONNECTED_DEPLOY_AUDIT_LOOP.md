# CryptoMaster — Connected Hetzner Deploy + Audit Loop

This document describes the mobile-friendly loop that connects deployment, health reporting, audit reports, and paper_train learning validation directly on Hetzner.

## Goal

```text
main update
→ Hetzner self-deploy checks origin/main
→ compile/tests
→ safety flag check
→ restart cryptomaster only in paper_train-safe mode
→ run audit bot
→ generate health/deploy reports
→ repeat every 2 hours
```

This avoids relying on GitHub Actions and avoids requiring the user to run bash from mobile.

## Files

```text
scripts/hetzner_paper_train_deploy_and_audit.sh
systemd/cryptomaster-autodeploy.service
systemd/cryptomaster-autodeploy.timer
reports/latest_deploy_status.json
reports/latest_deploy_status.md
reports/latest_health.json
reports/latest_health.md
```

## Safety guarantees

The deploy loop refuses dangerous `.env` variants including:

```text
TRADING_MODE=live_real
TRADING_MODE="live_real"
TRADING_MODE=LIVE_REAL
export TRADING_MODE=live_real
ENABLE_REAL_ORDERS=true
ENABLE_REAL_ORDERS="true"
ENABLE_REAL_ORDERS=TRUE
ENABLE_REAL_ORDERS=1
ENABLE_REAL_ORDERS=yes
ENABLE_REAL_ORDERS=on
LIVE_TRADING_CONFIRMED=true
LIVE_TRADING_CONFIRMED="true"
LIVE_TRADING_CONFIRMED=TRUE
LIVE_TRADING_CONFIRMED=1
LIVE_TRADING_CONFIRMED=yes
LIVE_TRADING_CONFIRMED=on
```

The script exports safe runtime defaults for audit/deploy context:

```text
TRADING_MODE=paper_train
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
```

The timer never enables paper_live or live_real.

## Install on Hetzner

Run once on the Hetzner server after pulling this commit:

```bash
cd /opt/CryptoMaster_srv
chmod +x scripts/hetzner_paper_train_deploy_and_audit.sh
sudo cp systemd/cryptomaster-autodeploy.service /etc/systemd/system/cryptomaster-autodeploy.service
sudo cp systemd/cryptomaster-autodeploy.timer /etc/systemd/system/cryptomaster-autodeploy.timer
sudo systemctl daemon-reload
sudo systemctl enable --now cryptomaster-autodeploy.timer
```

## Check status

```bash
systemctl list-timers cryptomaster-autodeploy.timer
systemctl status cryptomaster-autodeploy.service --no-pager
journalctl -u cryptomaster-autodeploy.service -n 200 --no-pager
```

Mobile-readable status files:

```text
reports/latest_deploy_status.md
reports/latest_health.md
```

## Report states

`latest_deploy_status.md` answers:

```text
Was a new commit deployed?
Which old/new sha?
Did tests pass?
Is service active?
Was the audit/health report refreshed?
Did audit bot fail while deploy remained safe?
```

`latest_health.md` answers:

```text
Is Hetzner OK/WARNING/CRITICAL/UNKNOWN?
Is bot in paper_train?
Is live trading off?
Are paper_train entries/exits happening?
Are learning updates happening?
Are app_metrics being saved?
```

## Readiness rules

The loop keeps the bot in paper_train until explicit operator approval.

```text
paper_train → paper_live → shadow_live → live_real_guarded
```

No automatic live transition is allowed.

## Known limitations

This loop assumes:

```text
project path: /opt/CryptoMaster_srv
service name: cryptomaster
origin/main is the deployment source
Python environment is available to systemd service user
```

Override via systemd Environment lines if needed:

```text
CRYPTOMASTER_PROJECT_DIR=/path/to/project
CRYPTOMASTER_SERVICE_NAME=cryptomaster
CRYPTOMASTER_REPORT_DIR=/path/to/reports
PYTHON_BIN=/path/to/python
RUN_FULL_TESTS=true|false
```

## Notes

The systemd service is expected to run as root unless a dedicated deployment user with permission to restart `cryptomaster` is configured. The service is install-only and does not activate until `systemctl enable --now cryptomaster-autodeploy.timer` is run once on Hetzner.
