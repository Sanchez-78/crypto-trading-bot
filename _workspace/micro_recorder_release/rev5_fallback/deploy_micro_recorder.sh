#!/usr/bin/env bash
# Pinned, phased deploy of the research recorder (design: _workspace/2026-11-26_micro_recorder_design.md).
# Run as root from the release directory that holds micro_recorder.py and cryptomaster-micro-recorder.service.
#   bash deploy_micro_recorder.sh stop-tick   # separate step: forensics of the dead tick-recorder, then stop it
#   bash deploy_micro_recorder.sh preflight   # read-only checks
#   bash deploy_micro_recorder.sh upgrade-check  # read-only, BEFORE the previous release's rollback
#   bash deploy_micro_recorder.sh install     # preflight + install + 120 s checks; any failure -> rollback
#   bash deploy_micro_recorder.sh verify      # later checks (rows written and readable)
#   bash deploy_micro_recorder.sh rollback    # stop + remove exactly the pinned files
# Never touches cryptomaster.service, its config, /opt/cryptomaster or the bot's data.
set -euo pipefail

SCRIPT_SHA="252dd1f73d16c5f4c1de551fae3939e69b06ae39b6ac6aecb858c3f042fd1172"
PREV_SCRIPT_SHA="b09b31b1bf6bc73904a0ec702049f477f07e39ffb1d65369b0d6bcce1847d466"   # installed revision upgrade-check expects
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
OVERRIDABLE=(UNIT_DIR APP_DIR DATA_DIR PY MEMINFO TICK_LOG FORENSICS_ROOT CHECK_WAIT PROC_ROOT FALLBACK_DIR)
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
# fallback release = previous recorder + unit + this script with only SCRIPT_SHA set to PREV_SCRIPT_SHA;
# its `rollback` uninstalls the running previous revision, its `preflight`+`install` restore it
FALLBACK="${FALLBACK_DIR:-/root/micro-recorder-rev6-fallback}"
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

verify_tick_state() {  # prints "PID FD" of the exact broken state, else fails without side effects
  local pid cmd fd
  [[ "$(systemctl is-active "$TICK" || true)" == active ]] || die "$TICK not active: state changed, not stopping"
  pid="$(systemctl show -p MainPID --value "$TICK")"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "$TICK has no valid MainPID ($pid)"
  cmd="$(tr '\0' ' ' < "$PROC/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *tick_recorder.py* ]] || die "MainPID $pid is not tick_recorder.py ($cmd)"
  fd="$(held_tick_db_fd "$pid")" || die "process $pid does not hold the deleted $TICK_DB: state changed, not stopping"
  echo "$pid $fd"
}

stop_tick() {
  # Fail closed: stop ONLY the exact broken state seen in the read-only audit (2026-11-26).
  local state pid fd cmd stamp dir before after
  state="$(verify_tick_state)" || exit 1
  pid="${state%% *}"; fd="${state#* }"
  cmd="$(tr '\0' ' ' < "$PROC/$pid/cmdline")"
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
  # re-verify immediately before stopping: same PID, same command, same held deleted inode
  state="$(verify_tick_state)" || exit 1
  [[ "$state" == "$pid $fd" ]] || die "tick-recorder changed during forensics ($pid $fd -> $state), not stopping"
  systemctl disable --now "$TICK"
  [[ "$(systemctl is-active "$TICK" || true)" != active ]] || die "$TICK still active"
  after="$(df --output=avail -k / | tail -1)"
  [[ "$(bot_pid)" == "$bot_before" ]] || die "bot PID changed"
  echo "free_kb_before=$before free_kb_after=$after" | tee -a "$dir/state.txt"
  [[ -f "$TICK_LOG" ]] || die "tick log disappeared"
  echo "TICK_STOPPED forensics=$dir (log kept at $TICK_LOG)"
}

release_checks() {  # read-only: the new release files, the environment and the target paths
  [[ "$SCRIPT_SHA" =~ ^[0-9a-f]{64}$ && "$UNIT_SHA" =~ ^[0-9a-f]{64}$ ]] || die "pins not set"
  [[ "$(sha "$HERE/micro_recorder.py")" == "$SCRIPT_SHA" ]] || die "micro_recorder.py != pin"
  [[ "$(sha "$HERE/$UNIT")" == "$UNIT_SHA" ]] || die "$UNIT != pin"
  "$PY" -I -B -c 'import websocket' || die "websocket-client missing for /usr/bin/python3"   # -B: no .pyc
  # syntax check in memory only: no __pycache__ or any other write
  "$PY" -I -B -c 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")' "$HERE/micro_recorder.py"     || die "compile failed"
  grep -Fxq "$PROD_EXEC" "$HERE/$UNIT" || die "unit ExecStart is not the fixed production target"
  grep -Fxq "StateDirectory=cryptomaster-micro" "$HERE/$UNIT" || die "unit StateDirectory mismatch"
  if [[ "${MICRO_DEPLOY_TEST_MODE:-0}" != 1 ]]; then
    [[ "$PY" == "$PROD_PY" && "$APP_DIR" == "$PROD_APP_DIR" && "$DATA" == "$PROD_DATA" ]]       || die "targets differ from the unit"
  fi
  check_target_dirs
}

resource_checks() {
  local free avail
  free="$(df --output=avail -k / | tail -1)"
  avail="$(awk '/MemAvailable/ {print $2}' "$MEMINFO")"
  (( free >= MIN_FREE_KB )) || die "free disk ${free} kB < ${MIN_FREE_KB}"
  (( avail >= MIN_AVAIL_KB )) || die "MemAvailable ${avail} kB < ${MIN_AVAIL_KB}"
  bot_pid >/dev/null
}

preflight() {
  release_checks
  [[ ! -e "$UNIT_PATH" && ! -L "$UNIT_PATH" ]] || die "$UNIT_PATH already exists"
  [[ ! -e "$APP" && ! -L "$APP" ]] || die "$APP already exists"
  resource_checks
  echo "PREFLIGHT_OK"
}

upgrade_check() {  # read-only, run while the previous revision is still installed and running
  release_checks
  [[ "$PREV_SCRIPT_SHA" =~ ^[0-9a-f]{64}$ ]] || die "previous pin not set"
  [[ -f "$UNIT_PATH" && ! -L "$UNIT_PATH" && "$(sha "$UNIT_PATH")" == "$UNIT_SHA" ]]     || die "installed unit is not the pinned unit (the previous release's rollback would not remove it)"
  [[ -f "$APP" && ! -L "$APP" && "$(sha "$APP")" == "$PREV_SCRIPT_SHA" ]]     || die "installed recorder is not the previous pinned revision"
  [[ "$(systemctl is-active "$UNIT" || true)" == active ]] || die "$UNIT not active"
  fallback_checks
  resource_checks
  [[ "$(dash_code)" == 200 ]] || die "dashboard not 200 (install would fail its checks after stopping the recorder)"
  echo "UPGRADE_CHECK_OK (next: $FALLBACK rollback, then preflight + install here)"
}

fallback_checks() {  # the release that uninstalls and, if needed, restores the previous revision
  local fb_script="$FALLBACK/deploy_micro_recorder.sh" f
  # independent copies: the rollback below deletes the installed files, so no fallback file may resolve to them
  for f in "$FALLBACK/micro_recorder.py" "$FALLBACK/$UNIT" "$fb_script"; do
    no_symlink_path "$f" && [[ -f "$f" && ! -L "$f" ]] || die "fallback release: $f is not a regular file on a symlink-free path"
  done
  [[ "$(sha "$FALLBACK/micro_recorder.py")" == "$PREV_SCRIPT_SHA" ]]     || die "fallback release: micro_recorder.py is not the previous pinned revision"
  [[ "$(sha "$FALLBACK/$UNIT")" == "$UNIT_SHA" ]] || die "fallback release: unit != pin"
  [[ "$(grep -c '^SCRIPT_SHA=' "$fb_script")" == 1 ]] || die "fallback deploy script malformed"
  grep -Fxq "SCRIPT_SHA=\"$PREV_SCRIPT_SHA\"" "$fb_script" || die "fallback deploy script does not pin the previous revision"
  # byte-identical to this script once only the pin value is swapped back (line order kept)
  cmp -s <(sed "s/^SCRIPT_SHA=\"$PREV_SCRIPT_SHA\"\$/SCRIPT_SHA=\"$SCRIPT_SHA\"/" "$fb_script") "$HERE/deploy_micro_recorder.sh"     || die "fallback deploy script differs from this one beyond SCRIPT_SHA"
}

no_symlink_path() {  # the path (existing or not) must contain no symlink component
  [[ "$(realpath -m "$1")" == "$(realpath -m -s "$1")" ]]
}

PRIV_OWNER=0   # systemd creates <parent>/private as root:root 0700
[[ "${MICRO_DEPLOY_TEST_MODE:-0}" != 1 ]] || PRIV_OWNER="$(id -u)"
data_dir_ok() {  # DATA has no symlink, or is exactly the link systemd made for a DynamicUser StateDirectory
  no_symlink_path "$DATA" && return 0
  local parent name priv
  parent="$(dirname "$DATA")"; name="$(basename "$DATA")"; priv="$parent/private"
  no_symlink_path "$parent" || return 1
  [[ -L "$DATA" && "$(readlink "$DATA")" == "private/$name" ]] || return 1
  [[ -d "$priv" && ! -L "$priv" && "$(stat -c '%u %a' "$priv")" == "$PRIV_OWNER 700" ]] || return 1
  [[ -d "$priv/$name" && ! -L "$priv/$name" ]]
}

check_target_dirs() {
  local d
  for d in "$APP_DIR" "$(dirname "$UNIT_PATH")"; do
    no_symlink_path "$d" || die "target path $d contains a symlink"
  done
  data_dir_ok || die "target path $DATA contains a symlink (not the systemd StateDirectory link)"
  [[ -d "$(dirname "$UNIT_PATH")" ]] || die "unit directory missing"
  if [[ "${MICRO_DEPLOY_TEST_MODE:-0}" != 1 ]]; then
    [[ "$(realpath -m "$APP_DIR")" == "$PROD_APP_DIR" ]] || die "APP_DIR resolves elsewhere"
    [[ "$(realpath -m "$(dirname "$UNIT_PATH")")" == /etc/systemd/system ]] || die "unit dir resolves elsewhere"
  fi
}

TEMPS=()
CREATED=()
APP_DIR_CREATED=0
place() {  # place SRC DST PIN: own temp copy in the target dir, verify the pin, no-clobber link; temp always cleaned
  local src="$1" dst="$2" pin="$3" tmp
  tmp="$(mktemp "$(dirname "$dst")/.micro.XXXXXX")" || die "mktemp failed for $dst"
  TEMPS+=("$tmp")
  if ! cp "$src" "$tmp" || ! chmod 0644 "$tmp" || ! chown root:root "$tmp"; then
    rm -f "$tmp"; die "copy/chmod/chown failed for $dst"
  fi
  if [[ "$(sha "$tmp")" != "$pin" ]]; then rm -f "$tmp"; die "temp copy of $dst != pin"; fi
  # no-clobber: a hard link fails if $dst appeared after preflight, so nothing is ever overwritten
  ln "$tmp" "$dst" 2>/dev/null || { rm -f "$tmp"; die "$dst exists or cannot be created; not overwriting"; }
  CREATED+=("$dst")
  rm -f "$tmp"
  [[ "$(sha "$dst")" == "$pin" ]] || die "$dst != pin after link"
}

checks() {  # checks BOT_PID
  local bot="$1" mem since
  [[ "$(systemctl is-active "$UNIT")" == active ]] || die "$UNIT not active"
  mem="$(systemctl show -p MemoryCurrent --value "$UNIT")"
  [[ "$mem" =~ ^[0-9]+$ ]] && (( mem < MEM_MAX )) || die "MemoryCurrent '$mem' not below $MEM_MAX"
  # journal only since THIS installation (the unit file is placed fresh by install, restarts included);
  # errors of an earlier installation/revision must not fail a later install or a fallback restore
  since="$(date -r "$UNIT_PATH" +%s.%N)"          # nanosecond mtime: no same-second overlap with the old run
  [[ "$since" =~ ^[0-9]+\.[0-9]+$ ]] || die "cannot read install time of $UNIT_PATH"
  # capture first: `journalctl | grep -q` under pipefail turns a match into SIGPIPE (141) = silently "no error"
  local journal rc=0
  journal="$(journalctl -u "$UNIT" --since "@$since" --no-pager -o cat)" || die "journalctl failed"
  grep -qE 'Traceback|write failed' <<<"$journal" || rc=$?
  case "$rc" in
    0) die "errors in journal since installation" ;;
    1) ;;                                             # only "no match" is clean
    *) die "grep on the journal failed (rc=$rc)" ;;
  esac
  ls "$DATA"/gaps/*.csv.gz >/dev/null 2>&1 || die "no gaps file written yet"
  [[ "$(bot_pid)" == "$bot" ]] || die "bot PID changed"
  [[ "$(dash_code)" == 200 ]] || die "dashboard not 200"
  echo "CHECKS_OK mem=$mem"
}

created_here() {  # was PATH created by this run's place()?
  local c
  for c in "${CREATED[@]+"${CREATED[@]}"}"; do [[ "$c" == "$1" ]] && return 0; done
  return 1
}

remove_pinned() {  # remove_pinned PATH PIN MODE: auto removes only targets this run created
  local path="$1" pin="$2" mode="$3"
  [[ -f "$path" ]] || return 0
  if [[ "$mode" == auto ]] && ! created_here "$path"; then
    echo "WARN: $path was not created by this run, left in place"
    return 0
  fi
  if [[ "$(sha "$path")" == "$pin" ]]; then rm -f "$path"; else echo "WARN: $path not the pinned file, left in place"; fi
}

rollback() {  # rollback [auto|manual]: auto (after a failed install) touches only what this run created
  local mode="${1:-manual}" t ours=0
  if [[ "$mode" == manual ]] || created_here "$UNIT_PATH"; then
    ours=1
    systemctl disable --now "$UNIT" 2>/dev/null || true
  fi
  remove_pinned "$UNIT_PATH" "$UNIT_SHA" "$mode"
  remove_pinned "$APP" "$SCRIPT_SHA" "$mode"
  for t in "${TEMPS[@]+"${TEMPS[@]}"}"; do rm -f "$t"; done      # only temp files created by this run
  if [[ "$mode" == manual || "$APP_DIR_CREATED" == 1 ]]; then rmdir "$APP_DIR" 2>/dev/null || true; fi
  systemctl daemon-reload
  if (( ours == 1 )); then   # a unit this run never created is not ours to stop or judge
    [[ "$(systemctl is-active "$UNIT" || true)" != active ]] || die "rollback: unit still active"
  fi
  echo "ROLLBACK_OK (data in $DATA kept)"
}

INSTALLING=0
on_exit() {  # any non-zero exit (die, set -e, failed command) after the first write rolls back
  local rc=$?
  if (( rc != 0 && INSTALLING == 1 )); then
    INSTALLING=0
    echo "install failed (rc=$rc) -> rollback" >&2
    rollback auto || echo "ROLLBACK_FAILED: manual action required" >&2
  fi
  exit "$rc"
}

install() {
  preflight
  local bot; bot="$(bot_pid)"
  trap on_exit EXIT
  INSTALLING=1
  if [[ ! -d "$APP_DIR" ]]; then APP_DIR_CREATED=1; fi
  mkdir -p -m 0755 "$APP_DIR"
  check_target_dirs
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
  du -sh "$DATA/"      # trailing slash: follow the systemd StateDirectory link
  echo "VERIFY_OK"
}

case "${1:-}" in
  stop-tick) stop_tick ;;
  preflight) preflight ;;
  upgrade-check) upgrade_check ;;
  install) install ;;
  verify) verify ;;
  rollback) rollback manual ;;
  *) die "usage: $0 stop-tick|preflight|upgrade-check|install|verify|rollback" ;;
esac
