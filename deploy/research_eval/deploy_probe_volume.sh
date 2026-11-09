#!/bin/bash
# One-off PAPER deploy (2026-11-09): env-configurable probe limits + raised volume.
# Expects the two new source files in /tmp/probe_volume/. Backs up, validates with
# the bot's own validators, restarts only with zero open positions, verifies READY,
# rolls back files and drop-in on any failure. Never touches REAL flags, TP/SL or costs.
set -euo pipefail

APP=/opt/cryptomaster
NEW=/tmp/probe_volume
FILES="src/services/paper_learning_budget.py src/services/paper_source_learning.py"
DROPIN=/etc/systemd/system/cryptomaster.service.d/zzzzzzzzzz-probe-volume.conf
VARS="PAPER_PROBE_DAILY_ENTRIES=480 PAPER_PROBE_HOURLY_ENTRIES=30 PAPER_PROBE_SYMBOL_COOLDOWN_S=300 PAPER_PROBE_MIN_NET_BPS=-25 PAPER_SYMBOL_BLACKLIST="
BACKUP=/opt/cryptomaster_deploy_backups/probe-volume-$(date -u +%Y%m%dT%H%M%SZ)
POSITIONS=$APP/data/paper_open_positions.json
READY=$APP/reports/ready_bot_sha
LOG=/opt/cryptomaster_research/stage.log
log() { echo "$(date -u +%FT%TZ) PROBE_VOLUME $*" | tee -a "$LOG"; }

mkdir -p "$BACKUP/src/services"
for f in $FILES; do cp -p "$APP/$f" "$BACKUP/$f"; done
[ -f "$DROPIN" ] && cp -p "$DROPIN" "$BACKUP/" || true

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
print("config ok", paper_learning_budget.limits(env), paper_source_learning.min_probe_net_bps(env))
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
  log "ROLLBACK: $1"
  for f in $FILES; do cp -p "$BACKUP/$f" "$APP/$f"; done
  if [ -f "$BACKUP/$(basename "$DROPIN")" ]; then cp -p "$BACKUP/$(basename "$DROPIN")" "$DROPIN"; else rm -f "$DROPIN"; fi
  systemctl daemon-reload; systemctl restart cryptomaster || true; sleep 90
  log "after rollback: $(systemctl is-active cryptomaster || true)"
  exit 1
}

for f in $FILES; do install -m 644 "$NEW/$(basename "$f")" "$APP/$f"; done
{ echo "# Managed by deploy_probe_volume.sh (2026-11-09): PAPER learning data volume"
  echo "[Service]"
  for kv in $VARS; do echo "Environment=\"$kv\""; done; } > "$DROPIN"
systemctl daemon-reload
t0="$(date +%s)"
systemctl restart cryptomaster || rollback "restart failed"
for _ in $(seq 1 40); do
  [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ] && break
  sleep 15
done
{ [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ]; } || rollback "READY not refreshed"
sleep 60
systemctl is-active --quiet cryptomaster || rollback "service not active"
if journalctl -u cryptomaster --since "@$t0" --no-pager | grep -qE "Traceback|_requires_|invalid_paper_probe"; then
  rollback "errors in journal"
fi
log "APPLIED OK backup=$BACKUP pid=$(systemctl show cryptomaster -p MainPID --value)"
