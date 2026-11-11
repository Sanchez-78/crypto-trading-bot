#!/bin/bash
# Generic PAPER deploy of bot source files + one managed env drop-in.
# Usage (env): LABEL=name FILES="src/services/a.py ..." VARS="K=V ..." DROPIN_NAME=zzz...-name.conf
#              EXPECTED_SHA256="src/services/a.py=<sha256> ..."  (the reviewed bytes, one per file)
# New files are expected flat in /tmp/$LABEL/. deploy_env_check.py and deploy_pinned.sh must
# sit next to this script. The source is read exactly once into a private stage; validation,
# installation and the final hash check all use the staged bytes (review 78, R1).
#
# Guarantees: single deploy lock; allowlisted files/keys (no TP/SL, costs, REAL or
# execution paths); validation with the bot's own validators before any change;
# restart only with zero open paper positions; any failure after the first change
# restores every file and the drop-in and verifies the restored hashes.
# Known limit: zero open positions is a snapshot, not an entry barrier; the window
# between the check and the restart is a few seconds and positions are persisted.
set -euo pipefail

: "${LABEL:?}" "${FILES:?}" "${VARS?}" "${DROPIN_NAME:?}" "${EXPECTED_SHA256:?}"
HERE="$(dirname "$(readlink -f "$0")")"
CHECK="$HERE/deploy_env_check.py"
for helper in "$CHECK" "$HERE/deploy_pinned.sh"; do
  [ -f "$helper" ] || { echo "missing $helper" >&2; exit 2; }
done
# shellcheck source=deploy_pinned.sh
. "$HERE/deploy_pinned.sh"
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
# 2026-11-11: candle_cache_v1.py + p0_8_plus_live_pipeline.py and the phase-refresh flag
# (completed-candle refresh fix, _workspace/63_codex_candle_refresh_fix.md). The allowlist
# guards paths only, not behaviour: p0_8_plus_live_pipeline.py itself calls the paper
# executor, so every deploy pins the exact reviewed bytes via EXPECTED_SHA256 (review 77).
ALLOWED_FILES="src/services/paper_source_learning.py src/services/paper_learning_budget.py src/services/candle_cache_v1.py src/services/p0_8_plus_live_pipeline.py"
ALLOWED_KEYS="PAPER_PROBE_HOURLY_ENTRIES PAPER_PROBE_DAILY_ENTRIES PAPER_PROBE_SYMBOL_COOLDOWN_S PAPER_PROBE_MIN_NET_BPS PAPER_SYMBOL_BLACKLIST PAPER_LEARNING_CONTROL_FRACTION PAPER_COST_EXPLORATION_ENABLED PAPER_ADAPTIVE_EXPLORATION_ENABLED PAPER_COMPLETED_CANDLE_LEARNING_ENABLED PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED"
for f in $FILES; do
  case " $ALLOWED_FILES " in *" $f "*) ;; *) echo "file not allowed: $f" >&2; exit 2 ;; esac
done
for kv in $VARS; do
  key="${kv%%=*}"
  case " $ALLOWED_KEYS " in *" $key "*) ;; *) echo "key not allowed: $key" >&2; exit 2 ;; esac
done
# Exact reviewed bytes only: copy the mutable source once into a private stage and pin there.
# Everything after this point reads the stage, never $NEW again (review 78, R1).
STAGE_DIR="$(mktemp -d)"; SCRATCH="$(mktemp -d)"; chmod 700 "$STAGE_DIR" "$SCRATCH"
trap 'rm -rf "$STAGE_DIR" "$SCRATCH"' EXIT
PINNED="$STAGE_DIR/pinned"
stage_files "$NEW" "$PINNED" "$FILES"
verify_pinned "$PINNED" "$FILES" "$EXPECTED_SHA256" || exit 2
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

# Validate the new code against the effective env before touching anything live. The tree is
# built from the pinned stage; the sandbox may read it but writes only to SCRATCH.
TREE="$STAGE_DIR/tree"
build_tree "$APP" "$PINNED" "$TREE" "$FILES"  # no bytecode in the tree (review 79, N1)
mkdir -p "$SCRATCH/pycache"  # empty PYTHONPYCACHEPREFIX: Python never looks for .pyc next to sources
cp "$CHECK" "$TREE/deploy_env_check.py"
ENVLINE="$(systemctl show cryptomaster -p Environment --value)"
ENVFILES="$(systemctl show cryptomaster -p EnvironmentFiles --value)"
# Effective env in systemd order (Environment= then EnvironmentFile=, review 77 P1), the bot's
# own validators, and an import of every deployed module (review 77 P2). Runs in a transient
# sandbox where the whole filesystem except SCRATCH is read-only (the pinned stage included),
# so an import cannot write runtime data or alter the staged bytes; any such attempt fails the
# deploy before the service is touched.
systemd-run --quiet --wait --pipe --collect -p ProtectSystem=strict -p ReadWritePaths="$SCRATCH" \
  -p WorkingDirectory="$SCRATCH" --setenv=ENVLINE="$ENVLINE" --setenv=ENVFILES="$ENVFILES" \
  --setenv=VARS="$VARS" --setenv=FILES="$FILES" --setenv=STAGE_DIR="$TREE" \
  --setenv=EXPECTED_SHA256="$EXPECTED_SHA256" --setenv=PYTHONPYCACHEPREFIX="$SCRATCH/pycache" \
  /usr/bin/python3 -B - <<'PY'
import hashlib, importlib, os, sys
sys.path.insert(0, os.environ["STAGE_DIR"])
import deploy_env_check
dotenv_path = "/opt/cryptomaster/.env"
dotenv = open(dotenv_path, encoding="utf-8").read() if os.path.exists(dotenv_path) else ""
try:
    env = deploy_env_check.preflight(os.environ["ENVLINE"], os.environ["ENVFILES"], os.environ["VARS"], dotenv)
except deploy_env_check.Refused as exc:
    sys.exit(f"ENV_CHECK REFUSED: {exc}")
from src.services import paper_source_learning, paper_neural_context, paper_learning_budget
paper_source_learning.validate_config(env)
paper_neural_context.validate_config(env)
pinned = dict(e.split("=", 1) for e in os.environ["EXPECTED_SHA256"].split())
for path in os.environ["FILES"].split():
    source = os.path.join(os.environ["STAGE_DIR"], path)
    raw = open(source, "rb").read()
    assert hashlib.sha256(raw).hexdigest() == pinned[path], f"tree bytes differ from pin: {path}"
    compile(raw, source, "exec")  # the exact pinned bytes must compile
    module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
    # The module must come from that source file and no bytecode cache may have been used.
    assert os.path.realpath(module.__file__) == os.path.realpath(source), f"imported elsewhere: {path}"
    cached = module.__spec__.cached
    assert cached is None or (cached.startswith(os.environ["PYTHONPYCACHEPREFIX"])
                              and not os.path.exists(cached)), f"bytecode cache used for {path}"
print("config ok", paper_learning_budget.limits(env), paper_source_learning.min_probe_net_bps(env),
      paper_source_learning.control_fraction(env))
PY

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

verify_pinned "$PINNED" "$FILES" "$EXPECTED_SHA256" || rollback "staged bytes changed"
install_staged "$PINNED" "$APP" "$FILES"
verify_pinned "$APP" "$FILES" "$EXPECTED_SHA256" || rollback "installed bytes differ from EXPECTED_SHA256"
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
# The values validated above must be the ones the running process actually has: read the real
# environment of MainPID (systemctl's Environment= view ignores EnvironmentFile=, review 77 P1).
pid="$(systemctl show cryptomaster -p MainPID --value)"
[ -n "$pid" ] && [ "$pid" != 0 ] || rollback "no MainPID"
python3 -B "$CHECK" post --environ "/proc/$pid/environ" --dotenv "$APP/.env" --vars "$VARS" \
  || rollback "running env check failed"
verify_pinned "$APP" "$FILES" "$EXPECTED_SHA256" || rollback "postimage differs from EXPECTED_SHA256"
trap - ERR INT TERM
( cd "$APP" && sha256sum $FILES ) > "$BACKUP/POSTIMAGE.sha256"
log "APPLIED OK backup=$BACKUP pid=$(systemctl show cryptomaster -p MainPID --value)"
