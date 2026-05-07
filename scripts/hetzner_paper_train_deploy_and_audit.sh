#!/usr/bin/env bash
set -euo pipefail

# CryptoMaster Hetzner paper_train deploy + audit loop.
# Runs locally on the Hetzner server. Intended for systemd timer execution.
# Safety: refuses live_real / real-orders config and writes mobile-readable reports.

PROJECT_DIR="${CRYPTOMASTER_PROJECT_DIR:-/opt/CryptoMaster_srv}"
SERVICE_NAME="${CRYPTOMASTER_SERVICE_NAME:-cryptomaster}"
REPORT_DIR="${CRYPTOMASTER_REPORT_DIR:-$PROJECT_DIR/reports}"
LOCK_FILE="${CRYPTOMASTER_DEPLOY_LOCK:-/tmp/cryptomaster-paper-train-deploy.lock}"
PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_FULL_TESTS="${RUN_FULL_TESTS:-true}"
REMOTE_NAME="${REMOTE_NAME:-origin}"
BRANCH_NAME="${BRANCH_NAME:-main}"

mkdir -p "$REPORT_DIR"
TODAY="$(date -u +%F)"
RUN_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DATED_DIR="$REPORT_DIR/$TODAY"
mkdir -p "$DATED_DIR"
DEPLOY_JSON="$DATED_DIR/deploy_status.json"
DEPLOY_MD="$DATED_DIR/deploy_status.md"
LATEST_DEPLOY_JSON="$REPORT_DIR/latest_deploy_status.json"
LATEST_DEPLOY_MD="$REPORT_DIR/latest_deploy_status.md"
LOG_FILE="$DATED_DIR/deploy_loop.log"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$RUN_TS] another deploy/audit loop is already running" | tee -a "$LOG_FILE"
  exit 0
fi

status="UNKNOWN"
changed="false"
old_sha="unknown"
new_sha="unknown"
service_active="unknown"
message=""

write_reports() {
  local finished_at
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$DEPLOY_JSON" <<JSON
{
  "schema_version": "cryptomaster_deploy_status_v1",
  "started_at": "$RUN_TS",
  "finished_at": "$finished_at",
  "status": "$status",
  "project_dir": "$PROJECT_DIR",
  "service_name": "$SERVICE_NAME",
  "branch": "$BRANCH_NAME",
  "old_sha": "$old_sha",
  "new_sha": "$new_sha",
  "changed": $changed,
  "service_active": "$service_active",
  "message": "$message",
  "safety": {
    "target_mode": "paper_train",
    "enable_real_orders_allowed": false,
    "live_trading_confirmed_allowed": false,
    "live_real_allowed": false
  }
}
JSON
  cp "$DEPLOY_JSON" "$LATEST_DEPLOY_JSON"

  cat > "$DEPLOY_MD" <<MD
# CryptoMaster Deploy Status

## Status
$status

## Runtime
- Started: $RUN_TS
- Finished: $finished_at
- Project: $PROJECT_DIR
- Service: $SERVICE_NAME
- Branch: $BRANCH_NAME
- Old SHA: $old_sha
- New SHA: $new_sha
- Changed: $changed
- Service active: $service_active

## Safety
- Target mode: paper_train
- live_real allowed: false
- ENABLE_REAL_ORDERS=true allowed: false
- LIVE_TRADING_CONFIRMED=true allowed: false

## Message
$message

## Log
See: $LOG_FILE
MD
  cp "$DEPLOY_MD" "$LATEST_DEPLOY_MD"
}

trap 'status="CRITICAL"; message="deploy loop failed near line $LINENO"; write_reports' ERR

cd "$PROJECT_DIR"
echo "[$RUN_TS] starting deploy/audit loop in $PROJECT_DIR" | tee -a "$LOG_FILE"

if [ ! -d .git ]; then
  status="CRITICAL"
  message="PROJECT_DIR is not a git repository"
  write_reports
  exit 1
fi

# Refuse dangerous local environment config before pulling/restarting.
if [ -f .env ]; then
  if grep -E '^TRADING_MODE=live_real\b' .env >/dev/null; then
    status="CRITICAL"
    message="blocked: .env contains TRADING_MODE=live_real"
    write_reports
    exit 1
  fi
  if grep -E '^ENABLE_REAL_ORDERS=true\b' .env >/dev/null; then
    status="CRITICAL"
    message="blocked: .env contains ENABLE_REAL_ORDERS=true"
    write_reports
    exit 1
  fi
  if grep -E '^LIVE_TRADING_CONFIRMED=true\b' .env >/dev/null; then
    status="CRITICAL"
    message="blocked: .env contains LIVE_TRADING_CONFIRMED=true"
    write_reports
    exit 1
  fi
fi

old_sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
git fetch "$REMOTE_NAME" "$BRANCH_NAME" | tee -a "$LOG_FILE"
remote_sha="$(git rev-parse "$REMOTE_NAME/$BRANCH_NAME")"

if [ "$old_sha" != "$remote_sha" ]; then
  changed="true"
  echo "[$RUN_TS] updating $old_sha -> $remote_sha" | tee -a "$LOG_FILE"
  git checkout "$BRANCH_NAME" | tee -a "$LOG_FILE"
  git reset --hard "$REMOTE_NAME/$BRANCH_NAME" | tee -a "$LOG_FILE"
else
  echo "[$RUN_TS] already up to date: $old_sha" | tee -a "$LOG_FILE"
fi

new_sha="$(git rev-parse HEAD)"

# Compile and selected tests before any restart.
$PYTHON_BIN -m compileall src bot2 daily_log_fix_prompt_bot start.py | tee -a "$LOG_FILE"
if [ "$RUN_FULL_TESTS" = "true" ]; then
  $PYTHON_BIN -m pytest tests/test_paper_mode.py -q | tee -a "$LOG_FILE"
  $PYTHON_BIN -m pytest tests/test_app_metrics_contract.py -q | tee -a "$LOG_FILE"
  $PYTHON_BIN -m pytest tests/test_v3_1_hotfix.py -q | tee -a "$LOG_FILE"
  $PYTHON_BIN -m pytest daily_log_fix_prompt_bot/tests -q | tee -a "$LOG_FILE"
fi

# Restart only when there was a code change. Still run audit every cycle.
if [ "$changed" = "true" ]; then
  echo "[$RUN_TS] restarting $SERVICE_NAME" | tee -a "$LOG_FILE"
  sudo systemctl restart "$SERVICE_NAME"
  sleep 8
fi

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  service_active="true"
else
  service_active="false"
  status="CRITICAL"
  message="service is not active after deploy/audit cycle"
  write_reports
  exit 1
fi

# Always run audit/health report after deploy check if available.
export TRADING_MODE="${TRADING_MODE:-paper_train}"
export ENABLE_REAL_ORDERS="false"
export LIVE_TRADING_CONFIRMED="false"
export LOCAL_REPORT_DIR="$REPORT_DIR"
export SERVICE_NAME="$SERVICE_NAME"
export USE_JOURNALCTL="true"
export SANITIZE_SECRETS="true"
export SAVE_UNSANITIZED_RAW_LOGS="false"

if [ -d daily_log_fix_prompt_bot ]; then
  echo "[$RUN_TS] running audit bot health/report cycle" | tee -a "$LOG_FILE"
  $PYTHON_BIN -m daily_log_fix_prompt_bot.src.daily_log_fix_prompt_bot.main | tee -a "$LOG_FILE" || true
fi

status="OK"
if [ "$changed" = "true" ]; then
  message="deployed new main commit and ran audit/health report"
else
  message="no new commit; service active; audit/health report refreshed"
fi
write_reports

echo "[$RUN_TS] deploy/audit loop complete: $status" | tee -a "$LOG_FILE"
