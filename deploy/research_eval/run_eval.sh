#!/bin/bash
# Offline, read-only evaluation of the PAPER learning experiment.
# Never touches /opt/cryptomaster (bot code/state) and never restarts anything.
# Output: $BASE/reports/<UTC date>/report.{json,md}, $BASE/latest -> newest,
#         one summary line appended to $BASE/verdict.log,
#         $BASE/DECISION_READY when the ADAPTIVE vs CONTROL effect is decidable.
set -euo pipefail

BASE=/opt/cryptomaster_research
DB=/opt/cryptomaster/local_learning_storage/cache.sqlite
EPOCH=/opt/cryptomaster/local_learning_storage/performance_epoch.json
POLICY=paper_source_learning_v1
KEEP_DAYS=45

day="$(date -u +%F)"
out="$BASE/reports/$day"
since="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["started_at"])' "$EPOCH")"

ok=0
for attempt in 1 2 3; do
  if python3 -B "$BASE/code/scripts/research/p0_8_plus_epoch_report.py" \
      --db "$DB" --since "$since" --out "$out"; then
    ok=1; break
  fi
  sleep 20
done
if [ "$ok" != 1 ]; then
  echo "$(date -u +%FT%TZ) ERROR report failed after 3 attempts" >> "$BASE/verdict.log"
  exit 1
fi
ln -sfn "$out" "$BASE/latest"

python3 - "$out/report.json" "$POLICY" "$BASE" <<'PY' >> "$BASE/verdict.log"
import json, sys, datetime, pathlib
report, policy, base = json.load(open(sys.argv[1])), sys.argv[2], pathlib.Path(sys.argv[3])
total = report["total"]
exp = report["experiments"].get(policy, {}).get("verdict")
fmt = lambda v: "NA" if v is None else f"{v:+.2f}"
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if exp is None:
    print(f"{ts} total_n={total.get('n')} {policy}=NO_DATA")
    sys.exit(0)
a, c = exp["adaptive"], exp["control"]
print(f"{ts} total_n={total.get('n')} total_mean={fmt(total.get('mean_net_bps'))} "
      f"codes={','.join(exp['codes'])} adaptive_n={a['n']} adaptive_mean={fmt(a['mean_bps'])} "
      f"control_n={c['n']} control_mean={fmt(c['mean_bps'])} diff={fmt(exp['diff_bps'])} "
      f"ci=[{fmt(exp['diff_low_bps'])},{fmt(exp['diff_high_bps'])}]")
marker = base / "DECISION_READY"
if "EFFECT_INSUFFICIENT_DATA" not in exp["codes"] and not marker.exists():
    marker.write_text(f"{ts} {','.join(exp['codes'])}\n")
PY

find "$BASE/reports" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
