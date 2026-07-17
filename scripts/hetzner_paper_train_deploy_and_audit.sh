#!/usr/bin/env bash
set -euo pipefail

# CryptoMaster Hetzner paper_train deploy + audit loop.
# Runs locally on the Hetzner server. Intended for systemd timer execution.
# Safety: refuses live_real / real-orders config and writes mobile-readable reports.

PROJECT_DIR="${CRYPTOMASTER_PROJECT_DIR:-/opt/CryptoMaster_srv}"
SERVICE_NAME="${CRYPTOMASTER_SERVICE_NAME:-cryptomaster}"
REPORT_DIR="${CRYPTOMASTER_REPORT_DIR:-$PROJECT_DIR/reports}"
LOCK_FILE="${CRYPTOMASTER_DEPLOY_LOCK:-/tmp/cryptomaster-paper-train-deploy.lock}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
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
audit_status="not_run"
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
  "audit_status": "$audit_status",
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
- Audit status: $audit_status

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

# Return a normalized .env value for KEY, or empty string when absent.
# Handles export prefix, spaces, quotes, case variants, and inline comments.
env_value() {
  local key="$1"
  local file="${2:-.env}"
  [ -f "$file" ] || return 0
  awk -F= -v key="$key" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      k=$1
      sub(/^[[:space:]]*export[[:space:]]+/, "", k)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
      if (k == key) {
        v=substr($0, index($0, "=") + 1)
        sub(/[[:space:]]+#.*$/, "", v)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
        gsub(/^\047|\047$/, "", v)
        gsub(/^"|"$/, "", v)
        print tolower(v)
      }
    }
  ' "$file" | tail -n 1
}

block_if_env_equals() {
  local key="$1"
  local blocked_value="$2"
  local actual
  actual="$(env_value "$key" .env)"
  if [ "$actual" = "$blocked_value" ]; then
    status="CRITICAL"
    message="blocked: .env contains ${key}=${actual}"
    write_reports
    exit 1
  fi
}

block_if_env_true() {
  local key="$1"
  local actual
  actual="$(env_value "$key" .env)"
  case "$actual" in
    true|1|yes|on)
      status="CRITICAL"
      message="blocked: .env contains ${key}=${actual}"
      write_reports
      exit 1
      ;;
  esac
}

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
  block_if_env_equals "TRADING_MODE" "live_real"
  block_if_env_true "ENABLE_REAL_ORDERS"
  block_if_env_true "LIVE_TRADING_CONFIRMED"
fi

# Git 2.35+ rejects repos owned by a different user. Root cause found
# 2026-07-14 via sandbox reproduction: systemd services do NOT set $HOME,
# and git WITHOUT $HOME never reads /root/.gitconfig at all — so any
# safe.directory written there is invisible to every git call in this
# script. Export HOME for the whole script so the global config is read.
if [ "$(id -u)" = "0" ]; then
  export HOME="${HOME:-/root}"
fi
# Dedup guard: --add on every 2h cycle grew /root/.gitconfig to 77 KB.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx '\*'; then
  git config --global --add safe.directory '*' 2>/dev/null || true
fi

old_sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
# F2/F3: the SHA the trading PROCESS is actually running (written by the bot at
# startup). Used to decide restart, so a repo already fast-forwarded by another
# workflow (e.g. dashboard restore) but with a stale process is still caught.
running_sha="$(tr -d '[:space:]' < "$PROJECT_DIR/reports/running_bot_sha" 2>/dev/null || true)"
[ -n "$running_sha" ] || running_sha="unknown"
git fetch "$REMOTE_NAME" "$BRANCH_NAME" | tee -a "$LOG_FILE"
remote_sha="$(git rev-parse "$REMOTE_NAME/$BRANCH_NAME")"

if [ "$old_sha" != "$remote_sha" ]; then
  changed="true"
  echo "[$RUN_TS] syncing repo $old_sha -> $remote_sha" | tee -a "$LOG_FILE"
  git checkout "$BRANCH_NAME" | tee -a "$LOG_FILE"
  git reset --hard "$REMOTE_NAME/$BRANCH_NAME" | tee -a "$LOG_FILE"
else
  echo "[$RUN_TS] repo already up to date: $old_sha" | tee -a "$LOG_FILE"
fi

new_sha="$(git rev-parse HEAD)"

# Compile and selected tests before any restart.
$PYTHON_BIN -m compileall src bot2 daily_log_fix_prompt_bot start.py | tee -a "$LOG_FILE"
if [ "$RUN_FULL_TESTS" = "true" ]; then
  # Debian 12+ servers lack pytest in system Python (PEP 668) and the test
  # deps (numpy, firebase_admin) are not installed system-wide. CI already
  # runs the full suite on every PR; server-side pytest is a bonus gate.
  # Same pattern as the install workflow (PR #11). compileall above is the
  # real server-side blocker and always runs.
  if $PYTHON_BIN -m pytest --version >/dev/null 2>&1; then
    $PYTHON_BIN -m pytest tests/test_paper_mode.py -q | tee -a "$LOG_FILE"
    $PYTHON_BIN -m pytest tests/test_app_metrics_contract.py -q | tee -a "$LOG_FILE"
    $PYTHON_BIN -m pytest tests/test_v3_1_hotfix.py -q | tee -a "$LOG_FILE"
    $PYTHON_BIN -m pytest daily_log_fix_prompt_bot/tests -q | tee -a "$LOG_FILE"
  else
    echo "[$RUN_TS] pytest not available on server; skipping (suite verified by CI)" | tee -a "$LOG_FILE"
  fi
fi

# ── F2/F3: restart the trading process only when it is genuinely stale AND the
# change touches real code AND it is safe to do so. Decide off the RUNNING
# process SHA (not repo HEAD), so drift introduced by another workflow is caught.
restart_needed="false"
restart_skip_reason=""
if [ "$running_sha" = "unknown" ]; then
  # No marker yet (first run after this change, or older build): fall back to the
  # repo-change signal so we don't get stuck on a stale process forever.
  [ "$changed" = "true" ] && restart_needed="true"
elif [ "$running_sha" != "$new_sha" ]; then
  # Process is stale vs repo. Restart only if the delta touches real code — a
  # docs/workflow/test-only change must not kill a live paper position.
  if impact="$(git diff --name-only "$running_sha" "$new_sha" 2>/dev/null)"; then
    code_impact="$(printf '%s\n' "$impact" \
      | grep -Ev '^(docs/|\.github/|tests/|.*\.md$|AUDIT_|EXTERNAL_|HANDOVER)' || true)"
    if [ -n "$code_impact" ]; then
      restart_needed="true"
    else
      restart_skip_reason="docs/workflow-only change (no code impact)"
    fi
  else
    # Cannot diff (running_sha unknown to git, e.g. after a rebase) — be safe and
    # restart the stale process.
    restart_needed="true"
  fi
fi

# Operator freeze: a root-owned hold file blocks all restarts (health still runs).
if [ "$restart_needed" = "true" ] && [ -f "$PROJECT_DIR/.deploy_hold" ]; then
  restart_needed="false"
  restart_skip_reason="deploy hold file present ($PROJECT_DIR/.deploy_hold)"
fi

# Zero-open-position gate: never kill a live paper position mid-hold; defer to the
# next cycle (positions time out within ~15 min).
if [ "$restart_needed" = "true" ]; then
  POS_JSON="$PROJECT_DIR/data/paper_open_positions.json"
  if [ -s "$POS_JSON" ] && grep -q '"symbol"' "$POS_JSON" 2>/dev/null; then
    restart_needed="false"
    restart_skip_reason="open positions present — deferring restart to next cycle"
  fi
fi

if [ "$restart_needed" = "true" ]; then
  echo "[$RUN_TS] restarting $SERVICE_NAME (running $running_sha -> $new_sha)" | tee -a "$LOG_FILE"
  systemctl restart "$SERVICE_NAME"
  sleep 8
  # Record the SHA we intended to deploy; the process rewrites running_bot_sha
  # itself at startup, so the two converge once it is up.
  echo "$new_sha" > "$PROJECT_DIR/reports/deployed_bot_sha" 2>/dev/null || true
elif [ -n "$restart_skip_reason" ]; then
  echo "[$RUN_TS] restart skipped: $restart_skip_reason (running=$running_sha repo=$new_sha)" | tee -a "$LOG_FILE"
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
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
  set +e
  PYTHONPATH="$PROJECT_DIR/daily_log_fix_prompt_bot/src" \
    $PYTHON_BIN -m daily_log_fix_prompt_bot.main | tee -a "$LOG_FILE"
  audit_rc=${PIPESTATUS[0]}
  set -e
  if [ "$audit_rc" -eq 0 ]; then
    audit_status="ok"
  else
    audit_status="failed:${audit_rc}"
    status="WARNING"
    message="service active, but audit/health report failed with exit code ${audit_rc}"
    write_reports
    echo "[$RUN_TS] deploy/audit loop complete: $status" | tee -a "$LOG_FILE"
    exit 0
  fi
else
  audit_status="skipped:not_found"
fi

status="OK"
if [ "$changed" = "true" ]; then
  message="deployed new main commit and ran audit/health report"
else
  message="no new commit; service active; audit/health report refreshed"
fi
write_reports

echo "[$RUN_TS] deploy/audit loop complete: $status" | tee -a "$LOG_FILE"
