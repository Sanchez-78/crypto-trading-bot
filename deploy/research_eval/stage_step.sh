#!/bin/bash
# Executes a stage transition requested by run_eval.sh (file next_action).
# Only S2 -> S3 is automated here; S3 is terminal. Exit 3 from apply_stage.sh
# (open positions) leaves next_action in place for the next run.
set -uo pipefail
BASE=/opt/cryptomaster_research
want="$(cat "$BASE/next_action" 2>/dev/null || true)"
stage="$(cat "$BASE/stage" 2>/dev/null || echo S1)"
[ "$want" = S3 ] && [ "$stage" = S2 ] || exit 0
"$BASE/apply_stage.sh" S3 check || { echo "$(date -u +%FT%TZ) S3 check failed" >> "$BASE/stage.log"; exit 1; }
"$BASE/apply_stage.sh" S3
rc=$?
if [ "$rc" = 0 ]; then
  rm -f "$BASE/next_action"
  touch "$BASE/FINISHED"
  systemctl start cryptomaster-research-eval.service || true
elif [ "$rc" != 3 ]; then
  rm -f "$BASE/next_action"
  touch "$BASE/BLOCKED"
fi
exit "$rc"
