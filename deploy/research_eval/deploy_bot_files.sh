#!/bin/bash
# Generic PAPER deploy of bot source files + one managed env drop-in.
# Usage (env): LABEL=name FILES="src/services/a.py ..." VARS="K=V ..." DROPIN_NAME=zzz...-name.conf
#              EXPECTED_SHA256="src/services/a.py=<sha256> ..."  (the reviewed bytes, one per file)
#              EXPECTED_PREIMAGE_SHA256="src/services/a.py=<sha256> ..."  (the live bytes the change was
#              reviewed against; checked under the lock before the backup and again right before install)
# New files are expected flat in /tmp/$LABEL/. deploy_env_check.py and deploy_pinned.sh must
# sit next to this script. The source is read exactly once into a private stage; validation,
# installation and the final hash check all use the staged bytes (review 78, R1).
#
# Guarantees: single deploy lock; allowlisted files/keys (keys exclude TP/SL, costs and REAL;
# files are explicitly reviewed exceptions, incl. the PAPER executor and the decision engine,
# always pinned by EXPECTED_SHA256); validation with the bot's own validators before any change;
# restart only with zero open paper positions (unless ALLOW_OPEN_POSITIONS=1 and the state file passes
# deploy_env_check.py positions); any failure after the first change
# restores every file and the drop-in and verifies the restored hashes.
# Known limit: zero open positions is a snapshot, not an entry barrier; the window
# between the check and the restart is a few seconds and positions are persisted.
set -euo pipefail

: "${LABEL:?}" "${FILES?}" "${VARS?}" "${DROPIN_NAME:?}" "${EXPECTED_SHA256?}" "${EXPECTED_PREIMAGE_SHA256?}"
# Env-only deploy (2026-11-23, Stonkfly off): FILES="" installs no code, the drop-in is the whole
# change, so VARS must be set and no pinned hashes may be given. With FILES both pins are required.
if [ -z "$FILES" ]; then
  if [ -z "$VARS" ] || [ -n "$EXPECTED_SHA256" ] || [ -n "$EXPECTED_PREIMAGE_SHA256" ]; then
    echo "env-only deploy needs VARS and empty EXPECTED_SHA256/EXPECTED_PREIMAGE_SHA256" >&2; exit 2
  fi
elif [ -z "$EXPECTED_SHA256" ] || [ -z "$EXPECTED_PREIMAGE_SHA256" ]; then
  echo "FILES need EXPECTED_SHA256 and EXPECTED_PREIMAGE_SHA256" >&2; exit 2
fi
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
# 2026-11-19: v5_legacy_bridge/outbox.py + outbox_flush_worker.py (terminal-backlog visibility,
# read-only SELECT + local log; code APPROVE _workspace/2026-11-18_codex_review_post_c1_remediation.md).
# paper_trade_executor.py + PAPER_EXPLORE_MAX_OPEN_PER_BUCKET were removed again: the bucket-cap
# review is REJECT (_workspace/2026-11-19_codex_review_explore_bucket_cap.md). They return only
# with their own approved review, so installing this tool approves no executor deploy.
# 2026-11-23: re-added; bucket-cap code APPROVE (_workspace/2026-11-19_codex_rereview_post_c1_deploy_and_bucket_cap.md), deploy step review _workspace/2026-11-23_codex_review_bucket_cap_deploy_step.md.
# 2026-11-23: realtime_decision_engine.py + RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED (journal volume: rate-limits
# only the REJECT_ECON_BAD_ENTRY detail lines, decisions unchanged; code APPROVE
# _workspace/2026-11-23_codex_rereview_econ_bad_log_limit_r2.md). Strict true/false in deploy_env_check.py.
ALLOWED_FILES="src/services/paper_source_learning.py src/services/paper_learning_budget.py src/services/candle_cache_v1.py src/services/p0_8_plus_live_pipeline.py src/services/paper_trade_executor.py src/services/v5_legacy_bridge/outbox.py src/services/v5_legacy_bridge/outbox_flush_worker.py src/services/realtime_decision_engine.py"
# 2026-11-23: STONKFLY_ENABLED, STONKFLY_PAIRED_ENABLED, PAPER_STONKFLY_CONTEXT_ENABLED (switch the shadow
# neural research source and its decision context off; evaluation NO EDGE
# _workspace/stonkfly_eval_20261123/REPORT.md). Strict true/false in deploy_env_check.py.
ALLOWED_KEYS="PAPER_PROBE_HOURLY_ENTRIES PAPER_PROBE_DAILY_ENTRIES PAPER_PROBE_SYMBOL_COOLDOWN_S PAPER_PROBE_MIN_NET_BPS PAPER_SYMBOL_BLACKLIST PAPER_LEARNING_CONTROL_FRACTION PAPER_COST_EXPLORATION_ENABLED PAPER_ADAPTIVE_EXPLORATION_ENABLED PAPER_COMPLETED_CANDLE_LEARNING_ENABLED PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED PAPER_EXPLORE_MAX_OPEN_PER_BUCKET RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED STONKFLY_ENABLED STONKFLY_PAIRED_ENABLED PAPER_STONKFLY_CONTEXT_ENABLED"
for f in $FILES; do
  case " $ALLOWED_FILES " in *" $f "*) ;; *) echo "file not allowed: $f" >&2; exit 2 ;; esac
done
# The source dir is flat (stage_files reads $NEW/<basename>): two files with one basename would
# install the same bytes twice under different paths.
dup="$(for f in $FILES; do basename "$f"; done | sort | uniq -d)"
[ -z "$dup" ] || { echo "duplicate basename in FILES: $dup" >&2; exit 2; }
# The live files must still be the bytes the change was reviewed against, or a newer live change
# would be silently overwritten (review 2026-11-19 B4). Checked here under the lock, and again
# immediately before the first write below.
verify_pinned "$APP" "$FILES" "$EXPECTED_PREIMAGE_SHA256" || { echo "live files are not the reviewed preimage; refusing" >&2; exit 2; }
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

mkdir -p "$BACKUP"  # also for an env-only deploy, which copies no file into it
for f in $FILES; do mkdir -p "$BACKUP/$(dirname "$f")"; cp -p "$APP/$f" "$BACKUP/$f"; done
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
  --setenv=EXPECTED_SHA256="$EXPECTED_SHA256" --setenv=PYCACHE_PREFIX="$SCRATCH/pycache" \
  /usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" - <<'PY'
import os, sys
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
from src.services.stonkfly.config import StonkflyConfig
StonkflyConfig.from_env(env)  # the Stonkfly switches are deployable keys; their combination must validate
pinned = dict(e.split("=", 1) for e in os.environ["EXPECTED_SHA256"].split())
# Explicit refusals (never assert, review 80 N2): exact pinned bytes compile and are what got imported,
# with no bytecode cache. -I above also ignores PYTHON* variables such as PYTHONOPTIMIZE.
try:
    deploy_env_check.verify_staged_import(os.environ["STAGE_DIR"], os.environ["FILES"].split(), pinned,
                                          os.environ["PYCACHE_PREFIX"])
except deploy_env_check.Refused as exc:
    sys.exit(f"STAGED_IMPORT REFUSED: {exc}")
print("config ok", paper_learning_budget.limits(env), paper_source_learning.min_probe_net_bps(env),
      paper_source_learning.control_fraction(env))
PY

open=err
# ALLOW_OPEN_POSITIONS=1 (explicit operator opt-in, 2026-11-23): restart even with open PAPER
# positions, only if deploy_env_check.py positions accepts the state (every record restorable,
# closable and safe for the tick path; reviews A1, R1-R4). Limits of a restart with open positions
# (a close interrupted before its journal commit, rollback restarting again) are in
# docs/OPERATING_STATE.md. The default (unset) keeps waiting for zero open positions.
if [ "${ALLOW_OPEN_POSITIONS:-0}" = 1 ]; then
  # Structural check against the executor's canonical state, not just len(json) (review A1).
  open="$(python3 -I -B "$CHECK" positions --file "$POSITIONS" 2>/dev/null || echo err)"
  [ "$open" != err ] || { log "SKIPPED positions state not restorable (ALLOW_OPEN_POSITIONS refused)"; exit 3; }
  log "OPEN_POSITIONS_ALLOWED open=$open (operator opt-in)"
  open=0
fi
for _ in $(seq 1 60); do
  [ "$open" = 0 ] && break
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

# Second preimage check right before the first write (validation and the positions wait can take
# up to 30 min). Nothing has been written yet: exit without rollback, which would otherwise copy the
# backup over the newer live change.
if ! verify_pinned "$APP" "$FILES" "$EXPECTED_PREIMAGE_SHA256"; then
  trap - ERR INT TERM
  log "REFUSED live files changed since preflight; nothing written"
  exit 2
fi
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
# An unreadable journal must not pass as "no errors" (review 2026-11-19 B1).
journalctl -u cryptomaster --since "@$t0" --no-pager > "$JOURNAL" || { rm -f "$JOURNAL"; rollback "journal unreadable"; }
[ -s "$JOURNAL" ] || { rm -f "$JOURNAL"; rollback "journal empty since restart"; }
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
# No FILES: sha256sum without arguments would read stdin.
if [ -n "$FILES" ]; then ( cd "$APP" && sha256sum $FILES ) > "$BACKUP/POSTIMAGE.sha256"; else : > "$BACKUP/POSTIMAGE.sha256"; fi
log "APPLIED OK backup=$BACKUP pid=$(systemctl show cryptomaster -p MainPID --value)"
