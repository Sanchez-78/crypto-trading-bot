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
# F2/F3 (round 2): decide restart off the READY marker (written by the bot ONLY
# after full init), not the early BOOT marker — a crash-looping build that writes
# BOOT but never reaches READY is treated as stale, not healthy. Missing READY is
# FAIL-CLOSED (we cannot prove a healthy process on the current code).
read_marker() { { cat "$1" 2>/dev/null || true; } | tr -d '[:space:]'; }
ready_sha="$(read_marker "$PROJECT_DIR/reports/ready_bot_sha")"; [ -n "$ready_sha" ] || ready_sha="unknown"
boot_sha="$(read_marker "$PROJECT_DIR/reports/running_bot_sha")"; [ -n "$boot_sha" ] || boot_sha="unknown"
git fetch "$REMOTE_NAME" "$BRANCH_NAME" | tee -a "$LOG_FILE"
remote_sha="$(git rev-parse "$REMOTE_NAME/$BRANCH_NAME")"

deployed_sha="$(read_marker "$PROJECT_DIR/reports/deployed_bot_sha")"; [ -n "$deployed_sha" ] || deployed_sha="unknown"

# ── Audit v5 §12: OPERATOR-APPROVAL model. This timer is READ-ONLY. It fetches,
# classifies the pending change, validates the INCOMING code in a THROWAWAY
# staging worktree, and NOTIFIES — it NEVER resets the live checkout and NEVER
# restarts the trading service. Deploying is a separate MANUAL step
# (hetzner-deploy-apply.yml) an operator triggers. A live paper position can
# therefore never be killed, and no code is swapped under the running process.
new_sha="$old_sha"          # the live working tree is intentionally NOT advanced
update_available="false"
code_impact_pending=""
staging_compile="not_run"
if [ "$old_sha" != "$remote_sha" ]; then
  update_available="true"
  # classify code vs docs from fetched objects (no working-tree mutation)
  if impact="$(git diff --name-only "$old_sha" "$remote_sha" 2>/dev/null)"; then
    code_impact_pending="$(printf '%s\n' "$impact" \
      | grep -Ev '^(docs/|\.github/|tests/|.*\.md$|AUDIT_|EXTERNAL_|HANDOVER)' || true)"
  fi
  # Staging validation: compile the incoming SHA in a detached throwaway worktree
  # so the operator learns whether it is safe to deploy — without touching live.
  STAGING="$(mktemp -d /tmp/cm-staging.XXXXXX 2>/dev/null || echo "")"
  if [ -n "$STAGING" ] && git worktree add --detach "$STAGING" "$remote_sha" >/dev/null 2>&1; then
    if ( cd "$STAGING" && $PYTHON_BIN -m compileall -q src bot2 daily_log_fix_prompt_bot start.py ) >>"$LOG_FILE" 2>&1; then
      staging_compile="ok"
    else
      staging_compile="FAILED"
    fi
    git worktree remove --force "$STAGING" >/dev/null 2>&1 || rm -rf "$STAGING" 2>/dev/null || true
  else
    staging_compile="worktree_error"; [ -n "$STAGING" ] && rm -rf "$STAGING" 2>/dev/null || true
  fi
  echo "[$RUN_TS] UPDATE AVAILABLE $old_sha -> $remote_sha (code_impact=$([ -n "$code_impact_pending" ] && echo yes || echo docs-only) staging_compile=$staging_compile) — operator deploy required (hetzner-deploy-apply.yml)" | tee -a "$LOG_FILE"
else
  echo "[$RUN_TS] repo already up to date: $old_sha" | tee -a "$LOG_FILE"
fi

# Operator-facing marker. It NEVER claims a deployment — it reports what is live,
# what is ready, and what is available. (Audit v5 §4: report distinguishes
# live_head / deployed / ready / remote_available; no "deployed" claim on fetch.)
cat > "$PROJECT_DIR/reports/update_available.json" <<UJSON 2>/dev/null || true
{
  "checked_at": "$RUN_TS",
  "live_head_sha": "$old_sha",
  "remote_sha": "$remote_sha",
  "deployed_bot_sha": "$deployed_sha",
  "ready_bot_sha": "$ready_sha",
  "boot_bot_sha": "$boot_sha",
  "update_available": $update_available,
  "code_impact": $([ -n "$code_impact_pending" ] && echo true || echo false),
  "staging_compile": "$staging_compile",
  "needs_operator_deploy": $update_available
}
UJSON

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

# ── Audit v5 §12: READ-ONLY health check. The operator-approval timer NEVER
# restarts the trading service and NEVER writes deployed_bot_sha (only the manual
# deploy workflow does, after it converges). It only observes and reports so an
# operator can decide. A stale/crash-looped process is surfaced, not auto-healed.
if systemctl is-active --quiet "$SERVICE_NAME"; then
  service_active="true"
  if [ "$update_available" = "true" ]; then
    message="update available ($old_sha -> $remote_sha, staging_compile=$staging_compile) — run hetzner-deploy-apply.yml to deploy"
  fi
  if [ "$ready_sha" != "unknown" ] && [ "$ready_sha" != "$deployed_sha" ]; then
    echo "[$RUN_TS] note: ready_sha=$ready_sha deployed_sha=$deployed_sha (operator may re-deploy to converge)" | tee -a "$LOG_FILE"
  fi
else
  service_active="false"
  status="CRITICAL"
  message="service is NOT active — timer does not auto-restart (operator-approval). Investigate or run hetzner-deploy-apply.yml."
  echo "[$RUN_TS] CRITICAL: $SERVICE_NAME inactive; NOT auto-restarting (operator-approval model)" | tee -a "$LOG_FILE"
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
