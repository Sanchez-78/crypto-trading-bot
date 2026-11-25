#!/usr/bin/env bash
# Release "exit-taxonomy": 4 pinned dashboard files, restart ONLY cryptomaster-dashboard.
#   deploy_exit_taxonomy.sh preflight          # no write to /opt/cryptomaster
#   deploy_exit_taxonomy.sh install            # preflight + backup + ordered install + verify (auto-rollback)
#   deploy_exit_taxonomy.sh rollback <backup>  # only from the exact installed POST set; verify afterwards
# Run as root from the uploaded release directory (contains postimage/ and verify_staging.py).
# Every check is fail-closed: a check that cannot be performed counts as failed (review D4/D5).
# The file can be sourced (tests); main runs only when executed.
set -uo pipefail

LIVE="${EXIT_TAXONOMY_TEST_LIVE:-/opt/cryptomaster}"   # test override only; unset on the server
REL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
# The authorised access profile today: every endpoint 200 locally and publicly (2026-11-25).
EXPECTED_PROFILE="/api/dashboard/metrics=200/200 /api/trades/recent=200/200 /=200/200 /api/metrics=200/200"

log() { echo "$(date -u +%FT%TZ) $*"; }
die() { log "FAIL: $*"; exit 1; }
sha() { [[ -f "$1" && ! -L "$1" ]] && sha256sum "$1" | cut -d' ' -f1; }
absent() { [[ ! -e "$1" && ! -L "$1" ]]; }   # a dangling symlink is NOT absent (review D1)

bot_pid() {   # prints a positive numeric PID or fails (review D5)
  local out
  out="$(systemctl show -p MainPID --value cryptomaster.service)" || return 1
  [[ "$out" =~ ^[1-9][0-9]*$ ]] || return 1
  echo "$out"
}

http_code() {   # prints a 3-digit code or fails; curl errors never become "000" (review D5)
  local code
  code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$1")" || return 1
  [[ "$code" =~ ^[1-5][0-9][0-9]$ ]] || return 1
  echo "$code"
}

profile() {   # all eight codes or failure
  local out="" u l p
  for u in "${ENDPOINTS[@]}"; do
    l="$(http_code "http://127.0.0.1:5001$u")" || return 1
    p="$(http_code "http://78.47.2.198:5001$u")" || return 1
    out+="$u=$l/$p "
  done
  echo "${out% }"
}

journal_clean_since() {   # $1 = "YYYY-mm-dd HH:MM:SS UTC"; fail-closed (review D4)
  local tmp rc
  tmp="$(mktemp)" || return 1
  journalctl -u cryptomaster-dashboard --since "$1" --no-pager > "$tmp" 2>/dev/null
  rc=$?
  if [[ $rc -ne 0 || ! -s "$tmp" ]]; then rm -f "$tmp"; return 1; fi   # unreadable or empty = not proven
  if grep -q 'Traceback' "$tmp"; then rm -f "$tmp"; return 1; fi       # grep on a finished file: no SIGPIPE
  rm -f "$tmp"
  return 0
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
  absent "$LIVE/$NEW_MODULE" || die "$NEW_MODULE already exists (file or symlink)"
}

backups_ok() {   # ALL three backups verified before the first rollback write (review: partial rollback)
  local backup="$1" rel
  for rel in "${EXISTING[@]}"; do
    [[ "$(sha "$backup/$(basename "$rel")")" == "${PRE[$rel]}" ]] || { log "backup $rel missing/corrupt"; return 1; }
  done
}

rollback_state_ok() {   # $1 = auto|manual; live paths must be OUR state, never a foreign deploy
  local mode="$1" rel h
  if [[ "$mode" == manual ]]; then   # exactly the installed POST set
    for rel in "${ORDER[@]}"; do
      [[ "$(sha "$LIVE/$rel")" == "${POST[$rel]}" ]] || { log "live $rel is not the installed postimage"; return 1; }
    done
    return 0
  fi
  for rel in "${EXISTING[@]}"; do   # auto: any PRE/POST mix of a partially finished install
    h="$(sha "$LIVE/$rel")"
    [[ "$h" == "${PRE[$rel]}" || "$h" == "${POST[$rel]}" ]] || { log "live $rel is neither PRE nor POST"; return 1; }
  done
  absent "$LIVE/$NEW_MODULE" || [[ "$(sha "$LIVE/$NEW_MODULE")" == "${POST[$NEW_MODULE]}" ]] \
      || { log "live $NEW_MODULE is foreign"; return 1; }
}

stage_and_verify() {   # D2: import exactly the pinned bytes with the dashboard interpreter
  local stage pyc rel rc
  stage="$(mktemp -d "$REL/stage-XXXXXX")" || die "mktemp"
  pyc="$(mktemp -d "$REL/pycache-XXXXXX")" || die "mktemp"
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '*.pyo' \
        --exclude '*.sqlite*' --exclude '*.db' "$LIVE/src/" "$stage/src/" || die "rsync stage"
  for rel in "${ORDER[@]}"; do cp "$REL/postimage/$(basename "$rel")" "$stage/$rel" || die "overlay $rel"; done
  (cd "$REL" && "$DASH_PY" -I -B -X "pycache_prefix=$pyc" "$REL/verify_staging.py" "$stage") > "$REL/staging_result.txt" 2>&1
  rc=$?
  cat "$REL/staging_result.txt"
  rm -rf "$stage" "$pyc"
  [[ $rc -eq 0 ]] && [[ "$(tail -n 1 "$REL/staging_result.txt")" == STAGING_VERIFIED ]] || die "staging verification"
}

restart_and_wait() {
  systemctl restart cryptomaster-dashboard || return 1
  local i code
  for i in $(seq 1 30); do
    if systemctl is-active --quiet cryptomaster-dashboard \
       && code="$(http_code http://127.0.0.1:5001/api/dashboard/metrics)" && [[ "$code" == 200 ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

api_smoke() {   # $1 = install|rollback; JSON must parse; install also checks the new contract
  curl -sf -m 15 http://127.0.0.1:5001/api/dashboard/metrics > "$REL/metrics_$1.json" || return 1
  curl -sf -m 15 http://127.0.0.1:5001/api/trades/recent > "$REL/recent_$1.json" || return 1
  curl -sf -m 15 http://127.0.0.1:5001/ > "$REL/index_$1.html" || return 1
  /usr/bin/python3 -I -B - "$1" "$REL" <<'PY' || return 1
import json, sys
mode, rel = sys.argv[1], sys.argv[2]
m = json.load(open(f"{rel}/metrics_{mode}.json"))
rows = json.load(open(f"{rel}/recent_{mode}.json"))
assert isinstance(rows, list), "recent trades is not a list"
if mode == "install":
    groups = ("tp", "sl", "scratch", "stagnation", "timeout", "trailing_stop", "signal_exit", "risk_exit", "other")
    d = m["exit_distribution"]
    assert sum(d[g] for g in groups) == d["total"] == m["closed_trades"], d
    assert all("direction" in r and "exit_label" in r for r in rows), "recent rows lack new fields"
    assert "escapeHtml(exitText)" in open(f"{rel}/index_install.html", encoding="utf-8").read()
else:
    assert "exit_distribution" in m
print("API_SMOKE_OK", mode, m.get("closed_trades"), m.get("exit_distribution"))
PY
}

write_file() {   # atomic: temp file in the same directory, mode/owner, rename
  local src="$1" dst="$2" tmp
  tmp="$(dirname "$dst")/.$(basename "$dst").exit-taxonomy.$$"
  cp "$src" "$tmp" && chmod 644 "$tmp" && chown root:root "$tmp" && mv -f "$tmp" "$dst"
}

do_rollback() {   # $1 = backup dir, $2 = auto|manual, $3 = bot PID before; gates first, then writes
  local backup="$1" mode="$2" bot_before="$3" rel since pid prof
  log "ROLLBACK($mode) from $backup"
  backups_ok "$backup" || return 1                 # nothing written yet
  rollback_state_ok "$mode" || return 1           # nothing written yet
  for rel in "${EXISTING[@]}"; do
    write_file "$backup/$(basename "$rel")" "$LIVE/$rel" || { log "restore $rel failed"; return 1; }
  done
  rm -f "$LIVE/$NEW_MODULE"
  for rel in "${EXISTING[@]}"; do [[ "$(sha "$LIVE/$rel")" == "${PRE[$rel]}" ]] || { log "restored $rel != preimage"; return 1; }; done
  absent "$LIVE/$NEW_MODULE" || { log "new module still present"; return 1; }
  since="$(date -u '+%F %T')"
  restart_and_wait || { log "dashboard not active after rollback"; return 1; }
  sleep 3
  api_smoke rollback || { log "API smoke after rollback failed"; return 1; }
  journal_clean_since "$since UTC" || { log "journal unreadable/empty or traceback after rollback"; return 1; }
  prof="$(profile)" || { log "access profile unreadable after rollback"; return 1; }
  [[ "$prof" == "$EXPECTED_PROFILE" ]] || { log "access profile after rollback: $prof"; return 1; }
  pid="$(bot_pid)" || { log "bot PID unreadable after rollback"; return 1; }
  [[ "$pid" == "$bot_before" ]] || { log "bot PID changed $bot_before -> $pid"; return 1; }
  log "ROLLBACK_OK bot_pid=$pid profile=$prof"
}

main() {
  local cmd="${1:-}" rel="" failed="" backup="" bot_before="" bot_after="" prof="" since=""
  [[ $EUID -eq 0 ]] || die "run as root"
  case "$cmd" in
    preflight)
      check_artifact; check_live_pre; stage_and_verify
      bot_before="$(bot_pid)" || die "bot PID unreadable"
      prof="$(profile)" || die "access profile unreadable"
      [[ "$prof" == "$EXPECTED_PROFILE" ]] || die "unexpected access profile: $prof"
      log "PREFLIGHT_OK bot_pid=$bot_before profile=$prof"
      ;;
    install)
      check_artifact; check_live_pre; stage_and_verify
      bot_before="$(bot_pid)" || die "bot PID unreadable (no write done)"
      prof="$(profile)" || die "access profile unreadable (no write done)"
      [[ "$prof" == "$EXPECTED_PROFILE" ]] || die "unexpected access profile (no write done): $prof"
      backup="$BACKUP_ROOT/exit-taxonomy-$(date -u +%Y%m%dT%H%M%SZ)"
      mkdir -p "$backup" || die "backup dir"
      for rel in "${EXISTING[@]}"; do cp -p "$LIVE/$rel" "$backup/$(basename "$rel")" || die "backup $rel"; done
      echo "ABSENT $NEW_MODULE" > "$backup/ABSENT_exit_taxonomy.txt"
      echo "$prof" > "$backup/profile.txt"
      echo "$bot_before" > "$backup/bot_pid_before.txt"
      backups_ok "$backup" || die "backup verification (no write done)"
      log "BACKUP $backup bot_pid=$bot_before profile=$prof"
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
        since="$(date -u '+%F %T')"
        restart_and_wait || failed="dashboard not active"
      fi
      if [[ -z "$failed" ]]; then
        sleep 3
        api_smoke install || failed="API smoke"
      fi
      if [[ -z "$failed" ]]; then
        journal_clean_since "$since UTC" || failed="journal unreadable/empty or traceback"
      fi
      if [[ -z "$failed" ]]; then
        prof="$(profile)" || failed="access profile unreadable"
      fi
      if [[ -z "$failed" && "$prof" != "$EXPECTED_PROFILE" ]]; then failed="access profile changed: $prof"; fi
      if [[ -z "$failed" ]]; then
        bot_after="$(bot_pid)" || failed="bot PID unreadable"
      fi
      if [[ -z "$failed" && "$bot_after" != "$bot_before" ]]; then failed="bot PID changed $bot_before -> $bot_after"; fi
      if [[ -n "$failed" ]]; then
        log "INSTALL_FAILED: $failed -> automatic rollback"
        do_rollback "$backup" auto "$bot_before" || die "ROLLBACK_FAILED (backup $backup)"
        exit 2
      fi
      log "INSTALL_OK backup=$backup bot_pid_before=$bot_before bot_pid_after=$bot_after profile=$prof"
      ;;
    rollback)
      [[ -d "${2:-}" ]] || die "usage: rollback <backup dir>"
      bot_before="$(bot_pid)" || die "bot PID unreadable (no write done)"
      do_rollback "$2" manual "$bot_before" || die "ROLLBACK_FAILED"
      ;;
    *) die "usage: $0 preflight|install|rollback <backup>" ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
