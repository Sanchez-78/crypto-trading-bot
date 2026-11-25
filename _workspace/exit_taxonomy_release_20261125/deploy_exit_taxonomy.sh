#!/usr/bin/env bash
# Release "exit-taxonomy": 4 pinned dashboard files, restart ONLY cryptomaster-dashboard.
#   deploy_exit_taxonomy.sh preflight          # no write to /opt/cryptomaster
#   deploy_exit_taxonomy.sh install            # preflight + backup + ordered install + verify (auto-rollback)
#   deploy_exit_taxonomy.sh rollback <backup>  # restore originals, then remove the new module, verify
# Run as root from the uploaded release directory (contains postimage/ and verify_staging.py).
set -uo pipefail

LIVE=/opt/cryptomaster
REL="$(cd "$(dirname "$0")" && pwd)"
DASH_PY=/opt/dashboard_venv/bin/python3
BACKUP_ROOT=/opt/cryptomaster_deploy_backups
NEW_MODULE=src/services/exit_taxonomy.py
# Install order (D1): the new module first, then the files that import it.
ORDER=(src/services/exit_taxonomy.py src/services/performance_epoch.py
       src/services/dashboard_read_model.py src/services/dashboard_web.py)
# Rollback order (D1): originals first, the new module last.
EXISTING=(src/services/dashboard_web.py src/services/dashboard_read_model.py src/services/performance_epoch.py)
declare -A PRE=(
  [src/services/dashboard_web.py]=df8b50411afdd84e9bee685dc4e3457303a3e94d769dc5b5e1a69c1fb1d1e02e
  [src/services/dashboard_read_model.py]=12c3e91c0d0fb1b130e75b7c68982e23be0c37ee51e9b99e9644b29f9f39680c
  [src/services/performance_epoch.py]=b2b19bd9f9271bf2e29ab68867e25a6283da3ff950f60d4c7b5335027cd062bd
)
declare -A POST=(
  [src/services/exit_taxonomy.py]=590cd21983052f53d5a9bedbc869fa27c66b4f097a6fcc51b874206bf4f4e94c
  [src/services/performance_epoch.py]=58c560cc3702934180c50f293050ba32c1569c40d1ee2b76207782e7c900d2e6
  [src/services/dashboard_read_model.py]=31ba1f98394ed9c07c7da6f229046e9dc5f5336b357f2a08ce0a17adea6a7fe5
  [src/services/dashboard_web.py]=2446e0c19d37a61d8c8647834eb41085a9340b66e852988708fa600b3deef21e
)
ENDPOINTS=(/api/dashboard/metrics /api/trades/recent / /api/metrics)

log() { echo "$(date -u +%FT%TZ) $*"; }
die() { log "FAIL: $*"; exit 1; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
bot_pid() { systemctl show -p MainPID --value cryptomaster.service; }

profile() {   # "<path>=<local code>/<public code>" for every endpoint (public access profile)
  local out="" u
  for u in "${ENDPOINTS[@]}"; do
    out+="$u=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:5001$u")/"
    out+="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://78.47.2.198:5001$u") "
  done
  echo "$out"
}

check_artifact() {
  local rel
  for rel in "${ORDER[@]}"; do
    [[ "$(sha "$REL/postimage/$(basename "$rel")")" == "${POST[$rel]}" ]] || die "artifact $rel != pin"
  done
}

check_live_pre() {   # live = preimage pins and the new module absent; else stop WITHOUT writing
  local rel
  for rel in "${EXISTING[@]}"; do
    [[ "$(sha "$LIVE/$rel")" == "${PRE[$rel]}" ]] || die "live $rel != preimage (foreign change?)"
    [[ "$(stat -c '%a %U:%G' "$LIVE/$rel")" == "644 root:root" ]] || die "live $rel mode/owner changed"
  done
  [[ ! -e "$LIVE/$NEW_MODULE" ]] || die "$NEW_MODULE already exists"
}

stage_and_verify() {   # D2: import exactly the pinned bytes with the dashboard interpreter
  local stage pyc rel
  stage="$(mktemp -d "$REL/stage-XXXXXX")" || die "mktemp"
  pyc="$(mktemp -d "$REL/pycache-XXXXXX")" || die "mktemp"
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '*.pyo' \
        --exclude '*.sqlite*' --exclude '*.db' "$LIVE/src/" "$stage/src/" || die "rsync stage"
  for rel in "${ORDER[@]}"; do cp "$REL/postimage/$(basename "$rel")" "$stage/$rel" || die "overlay $rel"; done
  (cd "$REL" && "$DASH_PY" -I -B -X "pycache_prefix=$pyc" "$REL/verify_staging.py" "$stage") \
      | tee "$REL/staging_result.txt"
  local ok=$?
  rm -rf "$stage" "$pyc"
  grep -q '^STAGING_VERIFIED$' "$REL/staging_result.txt" && [[ $ok -eq 0 ]] || die "staging verification"
}

restart_and_wait() {
  systemctl restart cryptomaster-dashboard || return 1
  local i
  for i in $(seq 1 30); do
    if systemctl is-active --quiet cryptomaster-dashboard \
       && [[ "$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:5001/api/dashboard/metrics)" == 200 ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

api_smoke() {   # $1 = install|rollback; JSON must parse; install also checks the new contract
  curl -s -m 15 http://127.0.0.1:5001/api/dashboard/metrics > "$REL/metrics_$1.json" || return 1
  curl -s -m 15 http://127.0.0.1:5001/api/trades/recent > "$REL/recent_$1.json" || return 1
  curl -s -m 15 http://127.0.0.1:5001/ > "$REL/index_$1.html" || return 1
  /usr/bin/python3 -I -B - "$1" "$REL" <<'PY' || return 1
import json, sys
mode, rel = sys.argv[1], sys.argv[2]
m = json.load(open(f"{rel}/metrics_{mode}.json"))
recent = json.load(open(f"{rel}/recent_{mode}.json"))
rows = recent if isinstance(recent, list) else recent.get("trades", recent.get("data", []))
if mode == "install":
    groups = ("tp", "sl", "scratch", "stagnation", "timeout", "trailing_stop", "signal_exit", "risk_exit", "other")
    d = m["exit_distribution"]
    assert sum(d[g] for g in groups) == d["total"] == m["closed_trades"], d
    assert all("direction" in r and "exit_label" in r for r in rows), "recent rows lack new fields"
    assert "escapeHtml(exitText)" in open(f"{rel}/index_install.html", encoding="utf-8").read()
else:
    assert "exit_distribution" in m and isinstance(rows, list)
print("API_SMOKE_OK", mode, m.get("closed_trades"), m.get("exit_distribution"))
PY
}

no_traceback_since() {
  ! journalctl -u cryptomaster-dashboard --since "$1" --no-pager | grep -q 'Traceback'
}

write_file() {   # atomic: temp file in the same directory, mode/owner, rename
  local src="$1" dst="$2" tmp
  tmp="$(dirname "$dst")/.$(basename "$dst").exit-taxonomy.$$"
  cp "$src" "$tmp" && chmod 644 "$tmp" && chown root:root "$tmp" && mv -f "$tmp" "$dst"
}

do_rollback() {   # $1 = backup dir; originals first, then the new module (D1); then verify (D3)
  local backup="$1" rel since
  log "ROLLBACK from $backup"
  for rel in "${EXISTING[@]}"; do
    [[ "$(sha "$backup/$(basename "$rel")")" == "${PRE[$rel]}" ]] || { log "backup $rel corrupt"; return 1; }
    write_file "$backup/$(basename "$rel")" "$LIVE/$rel" || { log "restore $rel failed"; return 1; }
  done
  rm -f "$LIVE/$NEW_MODULE"
  for rel in "${EXISTING[@]}"; do [[ "$(sha "$LIVE/$rel")" == "${PRE[$rel]}" ]] || { log "restored $rel != preimage"; return 1; }; done
  [[ ! -e "$LIVE/$NEW_MODULE" ]] || { log "new module still present"; return 1; }
  since="$(date -u '+%F %T')"
  restart_and_wait || { log "dashboard not active after rollback"; return 1; }
  sleep 3
  api_smoke rollback || { log "API smoke after rollback failed"; return 1; }
  no_traceback_since "$since UTC" || { log "traceback after rollback"; return 1; }
  [[ -f "$backup/profile.txt" ]] && [[ "$(profile)" == "$(cat "$backup/profile.txt")" ]] \
      || { log "public profile differs after rollback: $(profile)"; return 1; }
  log "ROLLBACK_OK bot_pid=$(bot_pid) dashboard_active=$(systemctl is-active cryptomaster-dashboard)"
}

cmd="${1:-}"
[[ $EUID -eq 0 ]] || die "run as root"
case "$cmd" in
  preflight)
    check_artifact; check_live_pre; stage_and_verify
    log "PREFLIGHT_OK bot_pid=$(bot_pid) profile=$(profile)"
    ;;
  install)
    check_artifact; check_live_pre; stage_and_verify
    BOT_BEFORE="$(bot_pid)"; PROFILE_BEFORE="$(profile)"
    BACKUP="$BACKUP_ROOT/exit-taxonomy-$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$BACKUP" || die "backup dir"
    for rel in "${EXISTING[@]}"; do cp -p "$LIVE/$rel" "$BACKUP/$(basename "$rel")" || die "backup $rel"; done
    echo "ABSENT $NEW_MODULE" > "$BACKUP/ABSENT_exit_taxonomy.txt"
    echo "$PROFILE_BEFORE" > "$BACKUP/profile.txt"
    echo "$BOT_BEFORE" > "$BACKUP/bot_pid_before.txt"
    for rel in "${EXISTING[@]}"; do
      [[ "$(sha "$BACKUP/$(basename "$rel")")" == "${PRE[$rel]}" ]] || die "backup $rel != preimage"
    done
    log "BACKUP $BACKUP bot_pid=$BOT_BEFORE profile=$PROFILE_BEFORE"
    check_live_pre   # D1: re-check immediately before the first write
    failed=""
    for rel in "${ORDER[@]}"; do
      write_file "$REL/postimage/$(basename "$rel")" "$LIVE/$rel" || { failed="write $rel"; break; }
      log "INSTALLED $rel $(sha "$LIVE/$rel")"
    done
    if [[ -z "$failed" ]]; then
      for rel in "${ORDER[@]}"; do
        [[ "$(sha "$LIVE/$rel")" == "${POST[$rel]}" && "$(stat -c '%a %U:%G' "$LIVE/$rel")" == "644 root:root" ]] \
            || { failed="installed $rel != pin"; break; }
      done
    fi
    if [[ -z "$failed" ]]; then
      SINCE="$(date -u '+%F %T')"
      restart_and_wait || failed="dashboard not active"
      sleep 3
      [[ -z "$failed" ]] && { api_smoke install || failed="API smoke"; }
      [[ -z "$failed" ]] && { no_traceback_since "$SINCE UTC" || failed="traceback in journal"; }
      if [[ -z "$failed" ]]; then
        PROFILE_AFTER="$(profile)"
        [[ "$PROFILE_AFTER" == "$PROFILE_BEFORE" ]] || failed="public profile changed: $PROFILE_AFTER"
      fi
    fi
    BOT_AFTER="$(bot_pid)"
    [[ -n "$failed" || "$BOT_AFTER" == "$BOT_BEFORE" ]] || failed="bot PID changed $BOT_BEFORE -> $BOT_AFTER"
    if [[ -n "$failed" ]]; then
      log "INSTALL_FAILED: $failed -> automatic rollback"
      do_rollback "$BACKUP" || die "ROLLBACK_FAILED (backup $BACKUP)"
      [[ "$(bot_pid)" == "$BOT_BEFORE" ]] || log "WARNING bot PID changed during rollback window"
      exit 2
    fi
    log "INSTALL_OK backup=$BACKUP bot_pid_before=$BOT_BEFORE bot_pid_after=$BOT_AFTER profile=$(profile)"
    ;;
  rollback)
    [[ -d "${2:-}" ]] || die "usage: rollback <backup dir>"
    BOT_BEFORE="$(bot_pid)"
    do_rollback "$2" || die "ROLLBACK_FAILED"
    [[ "$(bot_pid)" == "$BOT_BEFORE" ]] || die "bot PID changed during rollback"
    ;;
  *) die "usage: $0 preflight|install|rollback <backup>" ;;
esac
