#!/bin/bash
# One-shot deploy of the approved PAPER-only readiness fix to the DASHBOARD service only.
# Files (flat in /tmp/dashboard-readiness/): readiness_monitor.py, dashboard_web.py
# Code review: _workspace/2026-11-18_codex_review_post_c1_remediation.md (APPROVE, code only).
# This script itself needs its own review before it is run (see CODEX prompt of 2026-11-19).
#
# Guarantees: single deploy lock (shared with deploy_bot_files.sh); refuses unless the live
# files are exactly the reviewed preimage; installs only the pinned bytes; restarts only
# cryptomaster-dashboard (the bot does not import these modules); any failure restores both
# files, verifies the restored hashes and restarts the dashboard again.
# Not touched: cryptomaster.service, .env, unit files, credentials, Firebase.
set -euo pipefail

APP=/opt/cryptomaster
SRC=/tmp/dashboard-readiness
UNIT=cryptomaster-dashboard
LOG=/opt/cryptomaster_research/stage.log
BACKUP=/opt/cryptomaster_deploy_backups/dashboard-readiness-$(date -u +%Y%m%dT%H%M%SZ)
URL=http://127.0.0.1:5001
# path=preimage_sha256=new_sha256 (from _workspace/deploy_post_c1_20261119/MANIFEST.json)
PINS="src/services/readiness_monitor.py=854ccfe92ca19bf22bec3a8bf26d330a217feee1b790539aa341e37e7c67c5d6=1f5d9429817f3911b6cdb6c77e6ba9193f0e50c842326380633ed82eaa088144
src/services/dashboard_web.py=0fdbf5c8e9c7864f334fcc48b8c16a886037ff854cf2bf05ba14b7d58b360b62=df8b50411afdd84e9bee685dc4e3457303a3e94d769dc5b5e1a69c1fb1d1e02e"
log() { echo "$(date -u +%FT%TZ) DEPLOY_dashboard-readiness $*" | tee -a "$LOG"; }
h() { sha256sum < "$1" | cut -d' ' -f1; }
meta() { stat -c '%a %u %g' "$1"; }
# The credential systemd actually handed to the running unit (root-readable); covers plain and
# encrypted credstore sources alike (review 2026-11-19 A1).
TOKEN_FILE=/run/credentials/$UNIT.service/dashboard_api_token
code_of() {  # code_of <path> [auth] -> HTTP status; the token reaches curl only via stdin (-H @-)
  if [ "${2:-}" = auth ]; then
    printf 'Authorization: Bearer %s\n' "$(cat "$TOKEN_FILE")" | \
      curl -s -o "$BODY" -w '%{http_code}' -H @- "$URL$1" || true
  else
    curl -s -o "$BODY" -w '%{http_code}' "$URL$1" || true
  fi
}

exec 9>/run/lock/cryptomaster-deploy.lock
flock -n 9 || { echo "another deploy is running" >&2; exit 4; }

# Effective auth profile, observed before any change (docs/remediation/DASHBOARD_DEPLOYMENT.md allows a
# public profile without a token). The deploy must leave it exactly as found.
BODY="$(mktemp)"; trap 'rm -f "$BODY"' EXIT
case "$(code_of /api/dashboard/readiness)" in
  200) PROFILE=public ;;
  401|503) PROFILE=protected
           [ -r "$TOKEN_FILE" ] || { echo "protected dashboard but $TOKEN_FILE unreadable; refusing" >&2; exit 2; }
           [ "$(code_of /api/dashboard/readiness auth)" = 200 ] || { echo "token rejected before deploy; refusing" >&2; exit 2; } ;;
  *) echo "dashboard not answering before deploy; refusing" >&2; exit 2 ;;
esac
log "profile=$PROFILE"

STAGE="$(mktemp -d)"; chmod 700 "$STAGE"; trap 'rm -rf "$STAGE" "$BODY"' EXIT
while IFS='=' read -r f pre new; do
  [ "$(h "$APP/$f")" = "$pre" ] || { echo "live $f is not the reviewed preimage; refusing" >&2; exit 2; }
  install -m 600 "$SRC/$(basename "$f")" "$STAGE/$(basename "$f")"   # read the source exactly once
  [ "$(h "$STAGE/$(basename "$f")")" = "$new" ] || { echo "staged $f differs from pin" >&2; exit 2; }
  /usr/bin/python3 -I -B -c 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")' \
    "$STAGE/$(basename "$f")"
done <<< "$PINS"

mkdir -p "$BACKUP/src/services"
while IFS='=' read -r f pre new; do cp -p "$APP/$f" "$BACKUP/$f"; done <<< "$PINS"
( cd "$BACKUP" && find . -type f -exec sha256sum {} + ) > "$BACKUP/PREIMAGE.sha256"

restart_and_wait() {
  systemctl restart "$UNIT"
  for _ in $(seq 1 30); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/healthz" || true)" = 200 ] && return 0
    sleep 2
  done
  return 1
}

rollback() {
  trap - ERR INT TERM
  set +e
  log "ROLLBACK: $1"
  bad=0
  while IFS='=' read -r f pre new; do
    install -m "$(stat -c %a "$BACKUP/$f")" -o "$(stat -c %u "$BACKUP/$f")" -g "$(stat -c %g "$BACKUP/$f")" \
      "$BACKUP/$f" "$APP/$f"
    [ "$(h "$APP/$f")" = "$pre" ] || bad=1
    [ "$(meta "$APP/$f")" = "$(meta "$BACKUP/$f")" ] || bad=1   # mode, uid, gid too (review A3)
  done <<< "$PINS"
  restart_and_wait; up=$?
  log "after rollback: files_restored=$([ $bad = 0 ] && echo yes || echo NO) healthz=$([ $up = 0 ] && echo 200 || echo FAIL)"
  if [ "$bad" != 0 ] || [ "$up" != 0 ]; then
    echo "$(date -u +%FT%TZ) DEPLOY_dashboard-readiness ROLLBACK INCOMPLETE backup=$BACKUP" >> /opt/cryptomaster_research/ALERT
  fi
  exit 1
}
trap 'rollback "error at line $LINENO"' ERR
trap 'rollback "signal"' INT TERM

while IFS='=' read -r f pre new; do
  # keep the live file's owner and mode; the bytes come only from the stage
  install -m "$(stat -c %a "$APP/$f")" -o "$(stat -c %u "$APP/$f")" -g "$(stat -c %g "$APP/$f")" \
    "$STAGE/$(basename "$f")" "$APP/$f"
  [ "$(h "$APP/$f")" = "$new" ] || rollback "installed $f differs from pin"
done <<< "$PINS"

t0="$(date +%s)"
restart_and_wait || rollback "healthz not 200 after restart"

# The profile must be unchanged, and the readiness contract must hold under it.
if [ "$PROFILE" = protected ]; then
  case "$(code_of /api/dashboard/readiness)" in 401|503) ;; *) rollback "protected profile no longer enforced" ;; esac
  [ -r "$TOKEN_FILE" ] || rollback "credential unreadable after restart"
  MODE=auth
else
  MODE=""
fi
[ "$(code_of /api/dashboard/readiness "$MODE")" = 200 ] || rollback "readiness not HTTP 200"
/usr/bin/python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
ok = (d.get("status") == "paper_only" and d.get("is_ready_for_trading") is False
      and d.get("readiness_score") == 0 and d.get("blocker_reasons") == ["paper_only_policy"])
sys.exit(0 if ok else 1)' "$BODY" || rollback "readiness payload is not the paper_only contract"
[ "$(code_of /api/dashboard/metrics "$MODE")" = 200 ] || rollback "metrics not HTTP 200"

sleep 120   # one more readiness/metrics cycle in the journal
JOURNAL="$(mktemp)"
# An unreadable journal must not pass as "no errors" (review 2026-11-19 A2).
journalctl -u "$UNIT" --since "@$t0" --no-pager > "$JOURNAL" || { rm -f "$JOURNAL"; rollback "journal unreadable"; }
[ -s "$JOURNAL" ] || { rm -f "$JOURNAL"; rollback "journal empty since restart"; }
if grep -qE "Traceback|METRICS_COLLECTION_ERROR|PermissionError|READINESS_CHECK_ERROR" "$JOURNAL"; then
  rm -f "$JOURNAL"; rollback "errors in dashboard journal"
fi
rm -f "$JOURNAL"
systemctl is-active --quiet "$UNIT" || rollback "dashboard not active"
while IFS='=' read -r f pre new; do
  [ "$(h "$APP/$f")" = "$new" ] || rollback "postimage $f differs from pin"
  [ "$(meta "$APP/$f")" = "$(meta "$BACKUP/$f")" ] || rollback "postimage $f mode/owner changed"
done <<< "$PINS"
trap - ERR INT TERM
( cd "$APP" && sha256sum src/services/readiness_monitor.py src/services/dashboard_web.py ) > "$BACKUP/POSTIMAGE.sha256"
log "APPLIED OK backup=$BACKUP pid=$(systemctl show "$UNIT" -p MainPID --value)"
