#!/bin/bash
# Apply one pre-declared PAPER learning stage (see
# docs/remediation/AUTONOMOUS_LEARNING_LOOP_2026-10-26.md) as a systemd drop-in,
# restart only with zero open paper positions, verify READY, roll back on failure.
# Usage: apply_stage.sh S2|S3 [check]   ("check" validates only, changes nothing)
# Never touches code, TP/SL, costs or REAL flags.
set -euo pipefail

STAGE="${1:-}"
MODE="${2:-apply}"
BASE=/opt/cryptomaster_research
UNIT=cryptomaster
DROPIN=/etc/systemd/system/cryptomaster.service.d/zzzzzzzzz-auto-learning-stage.conf
POSITIONS=/opt/cryptomaster/data/paper_open_positions.json
READY=/opt/cryptomaster/reports/ready_bot_sha
LOG="$BASE/stage.log"
log() { echo "$(date -u +%FT%TZ) $STAGE $*" | tee -a "$LOG"; }

case "$STAGE" in
  S2) VARS="PAPER_COST_EXPLORATION_ENABLED=false" ;;
  S3) VARS="PAPER_COST_EXPLORATION_ENABLED=false PAPER_COMPLETED_CANDLE_LEARNING_ENABLED=false PAPER_STONKFLY_CONTEXT_ENABLED=false PAPER_ADAPTIVE_EXPLORATION_ENABLED=false PAPER_EVIDENCE_STOP_RULE_ENABLED=true" ;;
  *) echo "usage: $0 S2|S3 [check]" >&2; exit 2 ;;
esac

# Effective environment (.env < systemd < new stage) must be PAPER-only and
# accepted by the bot's own validators before anything is written.
ENVLINE="$(systemctl show "$UNIT" -p Environment --value)" VARS="$VARS" \
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
assert env.get("TRADING_MODE") == "paper_train", "TRADING_MODE"
for key in ("ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED"):
    assert env.get(key, "false").lower() in {"false", "0", "no", "off"}, key
sys.path.insert(0, "/opt/cryptomaster")
from src.services import paper_source_learning, paper_neural_context
paper_source_learning.validate_config(env)
paper_neural_context.validate_config(env)
print("config ok")
PY
[ "$MODE" = check ] && exit 0

# Wait (max 30 min) for zero open paper positions so no position is cut by restart.
open=err
for _ in $(seq 1 60); do
  open="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$POSITIONS" 2>/dev/null || echo err)"
  [ "$open" = 0 ] && break
  sleep 30
done
if [ "$open" != 0 ]; then log "SKIPPED: open positions did not drain (open=$open)"; exit 3; fi

prev="$BASE/stage_backups/prev-$(date -u +%Y%m%dT%H%M%SZ).conf"
mkdir -p "$BASE/stage_backups"
had_prev=0; [ -f "$DROPIN" ] && { cp -p "$DROPIN" "$prev"; had_prev=1; }

rollback() {
  log "ROLLBACK: $1"
  if [ "$had_prev" = 1 ]; then cp -p "$prev" "$DROPIN"; else rm -f "$DROPIN"; fi
  systemctl daemon-reload
  systemctl restart "$UNIT" || true
  sleep 90
  log "after rollback: $(systemctl is-active "$UNIT" || true)"
  exit 1
}

{ echo "# Managed by $BASE/apply_stage.sh - autonomous learning stage $STAGE"
  echo "[Service]"
  for kv in $VARS; do echo "Environment=\"$kv\""; done; } > "$DROPIN"
systemctl daemon-reload

t0="$(date +%s)"
systemctl restart "$UNIT" || rollback "restart failed"
for _ in $(seq 1 40); do
  [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ] && break
  sleep 15
done
{ [ -f "$READY" ] && [ "$(stat -c %Y "$READY")" -ge "$t0" ]; } || rollback "READY marker not refreshed within 10 min"
sleep 60
systemctl is-active --quiet "$UNIT" || rollback "service not active 60 s after READY"
if journalctl -u "$UNIT" --since "@$t0" --no-pager | grep -qE "Traceback|_requires_"; then
  rollback "errors in journal after restart"
fi

rm -f "$BASE/DECISION_READY"
date -u +%s > "$BASE/since_override"
echo "$STAGE" > "$BASE/stage"
log "APPLIED OK (pid $(systemctl show "$UNIT" -p MainPID --value))"
