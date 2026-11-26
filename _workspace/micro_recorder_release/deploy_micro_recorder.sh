#!/usr/bin/env bash
# Pinned, phased deploy of the research recorder (design: _workspace/2026-11-26_micro_recorder_design.md).
# Run as root from the release directory that holds micro_recorder.py and cryptomaster-micro-recorder.service.
#   bash deploy_micro_recorder.sh stop-tick   # separate step: forensics of the dead tick-recorder, then stop it
#   bash deploy_micro_recorder.sh preflight   # read-only checks
#   bash deploy_micro_recorder.sh install     # preflight + install + 120 s checks; any failure -> rollback
#   bash deploy_micro_recorder.sh verify      # later checks (rows written and readable)
#   bash deploy_micro_recorder.sh rollback    # stop + remove exactly the pinned files
# Never touches cryptomaster.service, its config, /opt/cryptomaster or the bot's data.
set -euo pipefail

SCRIPT_SHA="252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172"
UNIT_SHA="35b35cc039cdb7e1fb007548bfa2f75f4e35f5e366ea419fe2eb20ff9f40d0a8"
HERE="$(cd "$(dirname "$0")" && pwd)"
UNIT=cryptomaster-micro-recorder.service
TICK=tick-recorder.service
# Production targets are fixed and must equal the unit's ExecStart / StateDirectory.
PROD_PY=/usr/bin/python3
PROD_APP_DIR=/opt/cryptomaster-micro
PROD_DATA=/var/lib/cryptomaster-micro
PROD_EXEC="ExecStart=$PROD_PY -I $PROD_APP_DIR/micro_recorder.py --out $PROD_DATA"
TICK_DB=/opt/cryptomaster/local_learning_storage/tick_l1.sqlite
OVERRIDABLE=(UNIT_DIR APP_DIR DATA_DIR PY MEMINFO TICK_LOG FORENSICS_ROOT CHECK_WAIT PROC_ROOT)
if [[ "${MICRO_DEPLOY_TEST_MODE:-0}" == 1 ]]; then
  echo "TEST MODE: path overrides allowed" >&2
else
  for name in "${OVERRIDABLE[@]}"; do
    [[ -z "${!name+x}" ]] || { echo "FAIL: $name override not allowed outside MICRO_DEPLOY_TEST_MODE=1" >&2; exit 1; }
  done
fi
UNIT_PATH="${UNIT_DIR:-/etc/systemd/system}/$UNIT"
APP_DIR="${APP_DIR:-$PROD_APP_DIR}"
APP="$APP_DIR/micro_recorder.py"
DATA="${DATA_DIR:-$PROD_DATA}"
PY="${PY:-$PROD_PY}"
MEMINFO="${MEMINFO:-/proc/meminfo}"
TICK_LOG="${TICK_LOG:-/tmp/tick_recorder.log}"
FORENSICS_ROOT="${FORENSICS_ROOT:-/root}"
CHECK_WAIT="${CHECK_WAIT:-120}"
PROC="${PROC_ROOT:-/proc}"
MIN_FREE_KB=$((6 * 1024 * 1024))
MIN_AVAIL_KB=$((1024 * 1024))
MEM_MAX=$((128 * 1024 * 1024))

die() { echo "FAIL: $*" >&2; exit 1; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
bot_pid() {
  local pid
  pid="$(systemctl show -p MainPID --value cryptomaster.service)"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "cryptomaster.service has no valid MainPID ($pid)"
  echo "$pid"
}
dash_code() { curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:5001/api/dashboard/metrics || true; }

held_tick_db_fd() {  # prints the fd path whose link target is exactly the deleted tick DB, else fails
  local pid="$1" fd
  for fd in "$PROC/$pid"/fd/*; do
    [[ "$(readlink "$fd" 2>/dev/null || true)" == "$TICK_DB (deleted)" ]] && { echo "$fd"; return 0; }
  done
  return 1
}

stop_tick() {
  # Fail closed: stop ONLY the exact broken state seen in the read-only audit (2026-11-26).
  local pid cmd fd stamp dir before after
  [[ "$(systemctl is-active "$TICK" || true)" == active ]] || die "$TICK not active: state changed, not stopping"
  pid="$(systemctl show -p MainPID --value "$TICK")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "$TICK has no valid MainPID ($pid)"
  cmd="$(tr '\0' ' ' < "$PROC/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *tick_recorder.py* ]] || die "MainPID $pid is not tick_recorder.py ($cmd)"
  fd="$(held_tick_db_fd "$pid")" || die "process $pid does not hold the deleted $TICK_DB: state changed, not stopping"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dir="$FORENSICS_ROOT/tick-recorder-forensics-$stamp"
  ( umask 077; mkdir "$dir" )
  {
    echo "utc=$stamp"
    systemctl show "$TICK" -p ActiveState -p ActiveEnterTimestamp -p MainPID -p NRestarts
    echo "cmdline=$cmd"
    echo "held_fd=$fd -> $(readlink "$fd")"
    echo "held_deleted_db_bytes=$(stat -L -c %s "$fd")"
    if [[ -f "$TICK_LOG" ]]; then
      echo "log_path=$TICK_LOG"
      echo "log_bytes=$(stat -c %s "$TICK_LOG")"
      echo "log_sha256=$(sha "$TICK_LOG")"
      echo "readonly_errors=$(grep -c 'readonly database' "$TICK_LOG" || true)"
    fi
  } > "$dir/state.txt"
  if [[ -f "$TICK_LOG" ]]; then
    head -n 50 "$TICK_LOG" > "$dir/log_head.txt"
    tail -n 200 "$TICK_LOG" > "$dir/log_tail.txt"
    gzip -c "$TICK_LOG" > "$dir/tick_recorder.log.gz"     # archived copy; the original stays in place
  fi
  before="$(df --output=avail -k / | tail -1)"
  local bot_before; bot_before="$(bot_pid)"
  systemctl disable --now "$TICK"
  [[ "$(systemctl is-active "$TICK" || true)" != active ]] || die "$TICK still active"
  after="$(df --output=avail -k / | tail -1)"
  [[ "$(bot_pid)" == "$bot_before" ]] || die "bot PID changed"
  echo "free_kb_before=$before free_kb_after=$after" | tee -a "$dir/state.txt"
  [[ -f "$TICK_LOG" ]] || die "tick log disappeared"
  echo "TICK_STOPPED forensics=$dir (log kept at $TICK_LOG)"
}

preflight() {
  [[ "$SCRIPT_SHA" =~ ^[0-9a-f]{64}$ && "$UNIT_SHA" =~ ^[0-9a-f]{64}$ ]] || die "pins not set"
  [[ "$(sha "$HERE/micro_recorder.py")" == "$SCRIPT_SHA" ]] || die "micro_recorder.py != pin"
  [[ "$(sha "$HERE/$UNIT")" == "$UNIT_SHA" ]] || die "$UNIT != pin"
  "$PY" -I -c 'import websocket' || die "websocket-client missing for /usr/bin/python3"
  # syntax check in memory only: no __pycache__ or any other write
  "$PY" -I -B -c 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")' "$HERE/micro_recorder.py"     || die "compile failed"
  grep -Fxq "$PROD_EXEC" "$HERE/$UNIT" || die "unit ExecStart is not the fixed production target"
  grep -Fxq "StateDirectory=cryptomaster-micro" "$HERE/$UNIT" || die "unit StateDirectory mismatch"
  if [[ "${MICRO_DEPLOY_TEST_MODE:-0}" != 1 ]]; then
    [[ "$PY" == "$PROD_PY" && "$APP_DIR" == "$PROD_APP_DIR" && "$DATA" == "$PROD_DATA" ]]       || die "targets differ from the unit"
  fi
  [[ ! -e "$UNIT_PATH" && ! -L "$UNIT_PATH" ]] || die "$UNIT_PATH already exists"
  [[ ! -e "$APP" && ! -L "$APP" ]] || die "$APP already exists"
  local free avail
  free="$(df --output=avail -k / | tail -1)"
  avail="$(awk '/MemAvailable/ {print $2}' "$MEMINFO")"
  (( free >= MIN_FREE_KB )) || die "free disk ${free} kB < ${MIN_FREE_KB}"
  (( avail >= MIN_AVAIL_KB )) || die "MemAvailable ${avail} kB < ${MIN_AVAIL_KB}"
  bot_pid >/dev/null
  echo "PREFLIGHT_OK"
}

place() {  # place SRC DST PIN: temp copy in the target dir, verify the pin, then rename; temp always cleaned
  local src="$1" dst="$2" pin="$3" tmp
  tmp="$(mktemp "$(dirname "$dst")/.micro.XXXXXX")" || die "mktemp failed for $dst"
  if ! cp "$src" "$tmp" || ! chmod 0644 "$tmp" || ! chown root:root "$tmp"; then
    rm -f "$tmp"; die "copy/chmod/chown failed for $dst"
  fi
  if [[ "$(sha "$tmp")" != "$pin" ]]; then rm -f "$tmp"; die "temp copy of $dst != pin"; fi
  mv -f "$tmp" "$dst" || { rm -f "$tmp"; die "rename failed for $dst"; }
}

checks() {  # checks BOT_PID
  local bot="$1" mem
  [[ "$(systemctl is-active "$UNIT")" == active ]] || die "$UNIT not active"
  mem="$(systemctl show -p MemoryCurrent --value "$UNIT")"
  [[ "$mem" =~ ^[0-9]+$ ]] && (( mem < MEM_MAX )) || die "MemoryCurrent '$mem' not below $MEM_MAX"
  if journalctl -u "$UNIT" --no-pager -o cat | grep -qE 'Traceback|write failed'; then die "errors in journal"; fi
  ls "$DATA"/gaps/*.csv.gz >/dev/null 2>&1 || die "no gaps file written yet"
  [[ "$(bot_pid)" == "$bot" ]] || die "bot PID changed"
  [[ "$(dash_code)" == 200 ]] || die "dashboard not 200"
  echo "CHECKS_OK mem=$mem"
}

rollback() {
  systemctl disable --now "$UNIT" 2>/dev/null || true
  if [[ -f "$UNIT_PATH" ]]; then
    [[ "$(sha "$UNIT_PATH")" == "$UNIT_SHA" ]] && rm -f "$UNIT_PATH" || echo "WARN: $UNIT_PATH not the pinned file, left in place"
  fi
  if [[ -f "$APP" ]]; then
    [[ "$(sha "$APP")" == "$SCRIPT_SHA" ]] && rm -f "$APP" || echo "WARN: $APP not the pinned file, left in place"
  fi
  rm -f "$APP_DIR"/.micro.* "$(dirname "$UNIT_PATH")"/.micro.* 2>/dev/null || true
  rmdir "$APP_DIR" 2>/dev/null || true
  systemctl daemon-reload
  [[ "$(systemctl is-active "$UNIT" || true)" != active ]] || die "rollback: unit still active"
  echo "ROLLBACK_OK (data in $DATA kept)"
}

INSTALLING=0
on_exit() {  # any non-zero exit (die, set -e, failed command) after the first write rolls back
  local rc=$?
  if (( rc != 0 && INSTALLING == 1 )); then
    INSTALLING=0
    echo "install failed (rc=$rc) -> rollback" >&2
    rollback || echo "ROLLBACK_FAILED: manual action required" >&2
  fi
  exit "$rc"
}

install() {
  preflight
  local bot; bot="$(bot_pid)"
  trap on_exit EXIT
  INSTALLING=1
  mkdir -p -m 0755 "$APP_DIR"
  place "$HERE/micro_recorder.py" "$APP" "$SCRIPT_SHA"
  place "$HERE/$UNIT" "$UNIT_PATH" "$UNIT_SHA"
  systemctl daemon-reload
  systemd-analyze verify "$UNIT_PATH"
  systemctl enable --now "$UNIT"
  sleep "$CHECK_WAIT"
  checks "$bot"
  INSTALLING=0
  echo "INSTALL_OK"
}

verify() {
  local bot; bot="$(bot_pid)"
  checks "$bot"
  ls "$DATA"/book/*.csv.gz >/dev/null 2>&1 || die "no book file"
  "$PY" -I - "$DATA" <<'EOF' || die "data not readable"
import csv, gzip, sys, pathlib
base = pathlib.Path(sys.argv[1])
for kind in ("book", "gaps"):
    path = sorted((base / kind).glob("*.csv.gz"))[-1]
    with gzip.open(path, "rt") as fh:
        rows = list(csv.DictReader(fh))
    print(kind, path.name, "rows", len(rows))
    assert rows, kind
EOF
  du -sh "$DATA"
  echo "VERIFY_OK"
}

case "${1:-}" in
  stop-tick) stop_tick ;;
  preflight) preflight ;;
  install) install ;;
  verify) verify ;;
  rollback) rollback ;;
  *) die "usage: $0 stop-tick|preflight|install|verify|rollback" ;;
esac
