#!/bin/bash
# Generic PAPER deploy of bot source files + one managed env drop-in.
# Usage (env): LABEL=name FILES="src/services/a.py ..." VARS="K=V ..." DROPIN_NAME=zzz...-name.conf
# New files are expected flat in /tmp/$LABEL/.
#
# Guarantees: single deploy lock; allowlisted files/keys (no TP/SL, costs, REAL or
# execution paths); validation with the bot's own validators before any change;
# restart only with zero open paper positions; any failure after the first change
# restores every file and the drop-in and verifies the restored hashes.
# Known limit: zero open positions is a snapshot, not an entry barrier; the window
# between the check and the restart is a few seconds and positions are persisted.
set -euo pipefail

: "${LABEL:?}" "${FILES:?}" "${VARS?}" "${DROPIN_NAME:?}"
APP=/opt/cryptomaster
NEW=/tmp/$LABEL
DROPIN=/etc/systemd/system/cryptomaster.service.d/$DROPIN_NAME
BACKUP=/opt/cryptomaster_deploy_backups/$LABEL-$(date -u +%Y%m%dT%H%M%SZ)
POSITIONS=$APP/data/paper_open_positions.json
READY=$APP/reports/ready_bot_sha
LOG=/opt/cryptomaster_research/stage.log
log() { echo "$(date -u +%FT%TZ) DEPLOY_$LABEL $*" | tee -a "$LOG"; }

exec 9>/run/lock/cryptomaster-deploy.lock
flock -n 9 || { echo "another deploy is running" >&2; exit 4; }

# Positive allowlists (enforced). Extending them is a reviewed change to this script.
ALLOWED_FILES="src/services/paper_source_learning.py src/services/paper_learning_budget.py"
ALLOWED_KEYS="PAPER_PROBE_HOURLY_ENTRIES PAPER_PROBE_DAILY_ENTRIES PAPER_PROBE_SYMBOL_COOLDOWN_S PAPER_PROBE_MIN_NET_BPS PAPER_SYMBOL_BLACKLIST PAPER_LEARNING_CONTROL_FRACTION PAPER_COST_EXPLORATION_ENABLED PAPER_ADAPTIVE_EXPLORATION_ENABLED PAPER_COMPLETED_CANDLE_LEARNING_ENABLED"
for f in $FILES; do
  case " $ALLOWED_FILES " in *" $f "*) ;; *) echo "file not allowed: $f" >&2; exit 2 ;; esac
done
for kv in $VARS; do
  key="${kv%%=*}"
  case " $ALLOWED_KEYS " in *" $key "*) ;; *) echo "key not allowed: $key" >&2; exit 2 ;; esac
done
# The managed drop-in must sort after every other drop-in (byte order, as systemd does),
# otherwise a later file could silently override the validated values.
DROPIN_DIR=$(dirname "$DROPIN")
last="$(cd "$DROPIN_DIR" && ls -1 *.conf 2>/dev/null | grep -vxF "$DROPIN_NAME" | LC_ALL=C sort | tail -1 || true)"
if [ -n "$last" ] && [ "$(printf '%s\n%s\n' "$last" "$DROPIN_NAME" | LC_ALL=C sort | tail -1)" != "$DROPIN_NAME" ]; then
  echo "drop-in $DROPIN_NAME would not sort after $last" >&2; exit 2
fi

mkdir -p "$BACKUP/src/services"
for f in $FILES; do cp -p "$APP/$f" "$BACKUP/$f"; done
had_dropin=0; [ -f "$DROPIN" ] && { cp -p "$DROPIN" "$BACKUP/"; had_dropin=1; }
( cd "$BACKUP" && find . -type f -exec sha256sum {} + ) > "$BACKUP/PREIMAGE.sha256"

# Validate the new code against the effective env before touching anything live.
for f in $FILES; do python3 -m py_compile "$NEW/$(basename "$f")"; done
STAGE_DIR="$(mktemp -d)"; cp -r "$APP/src" "$STAGE_DIR/src"
for f in $FILES; do cp "$NEW/$(basename "$f")" "$STAGE_DIR/$f"; done
ENVLINE="$(systemctl show cryptomaster -p Environment --value)" VARS="$VARS" STAGE_DIR="$STAGE_DIR" \
python3 -B - <<'PY'
import os, shlex, sys
env = {}
for line in open("/opt/cryptomaster/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.removeprefix("export ").split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
for source in (os.environ["ENVLINE"], os.environ["VARS"]):
    env.update(kv.split("=", 1) for kv in shlex.split(source) if "=" in kv)
assert env.get("TRADING_MODE") == "paper_train"
for key in ("ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED"):
    assert env.get(key, "false").lower() in {"false", "0", "no", "off"}, key
sys.path.insert(0, os.environ["STAGE_DIR"])
from src.services import paper_source_learning, paper_neural_context, paper_learning_budget
paper_source_learning.validate_config(env)
paper_neural_context.validate_config(env)
print("config ok", paper_learning_budget.limits(env), paper_source_learning.min_probe_net_bps(env),
      paper_source_learning.control_fraction(env))
PY
rm -rf "$STAGE_DIR"

open=err
for _ in $(seq 1 60); do
  open="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$POSITIONS" 2>/dev/null || echo err)"
  [ "$open" = 0 ] && break
  sleep 30
done
if [ "$open" != 0 ]; then log "SKIPPED open=$open"; exit 3; fi

rollback() {
  trap - ERR INT TERM
  set +e
  log "ROLLBACK: $1"
  for f in $FILES; do cp -p "$BACKUP/$f" "$APP/$f"; done
  if [ "$had_dropin" = 1 ]; then cp -p "$BACKUP/$DROPIN_NAME" "$DROPIN"; else rm -f "$DROPIN"; fi
  bad=0
  for f in $FILES; do
    [ "$(sha256sum < "$APP/$f")" = "$(sha256sum < "$BACKUP/$f")" ] || bad=1
  done
  if [ "$had_dropin" = 1 ]; then
    [ "$(sha256sum < "$DROPIN")" = "$(sha256sum < "$BACKUP/$DROPIN_NAME")" ] || bad=1
  else
    [ ! -e "$DROPIN" ] || bad=1
  fi
  systemctl daemon-reload; t1="$(date +%s)"; systemctl restart cryptomaster
  for _ in $(seq 1 40); do
    [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t1" ] && break
    sleep 15
  done
  ready=no; [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t1" ] && ready=yes
  active="$(systemctl is-active cryptomaster)"
  log "after rollback: active=$active ready=$ready hashes_restored=$([ $bad = 0 ] && echo yes || echo NO)"
  if [ "$bad" != 0 ] || [ "$ready" != yes ] || [ "$active" != active ]; then
    echo "$(date -u +%FT%TZ) DEPLOY_$LABEL ROLLBACK INCOMPLETE backup=$BACKUP" >> /opt/cryptomaster_research/ALERT
  fi
  exit 1
}
trap 'rollback "error at line $LINENO"' ERR
trap 'rollback "signal"' INT TERM

for f in $FILES; do install -m 644 "$NEW/$(basename "$f")" "$APP/$f"; done
if [ -n "$VARS" ]; then
  { echo "# Managed by deploy_bot_files.sh ($LABEL)"
    echo "[Service]"
    for kv in $VARS; do echo "Environment=\"$kv\""; done; } > "$DROPIN"
fi
systemctl daemon-reload
t0="$(date +%s)"
systemctl restart cryptomaster
for _ in $(seq 1 40); do
  [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ] && break
  sleep 15
done
{ [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ]; } || rollback "READY not refreshed"
sleep 60
systemctl is-active --quiet cryptomaster || rollback "service not active"
# Read the journal fully first: `journalctl | grep -q` under pipefail returns 141 on a match.
JOURNAL="$(mktemp)"
journalctl -u cryptomaster --since "@$t0" --no-pager > "$JOURNAL" || true
if grep -qE "Traceback|_requires_|invalid_paper" "$JOURNAL"; then
  rm -f "$JOURNAL"; rollback "errors in journal"
fi
rm -f "$JOURNAL"
# The values validated above must be the ones the running service actually has.
effective="$(systemctl show cryptomaster -p Environment --value)"
for kv in $VARS; do
  case " $effective " in *" $kv "*) ;; *) rollback "effective env missing $kv" ;; esac
done
for f in $FILES; do
  [ "$(sha256sum < "$APP/$f")" = "$(sha256sum < "$NEW/$(basename "$f")")" ] || rollback "postimage mismatch $f"
done
trap - ERR INT TERM
( cd "$APP" && sha256sum $FILES ) > "$BACKUP/POSTIMAGE.sha256"
log "APPLIED OK backup=$BACKUP pid=$(systemctl show cryptomaster -p MainPID --value)"
