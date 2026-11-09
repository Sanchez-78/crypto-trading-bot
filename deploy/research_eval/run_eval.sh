#!/bin/bash
# Offline, read-only evaluation of PAPER learning. Never touches bot code/state,
# never restarts anything, never changes stages (S2/S3 cancelled 2026-11-09).
# One run = one UTC run ID, one read-only DB snapshot shared by every report,
# a manifest of data/code identity, and `latest` only after the whole run succeeded.
set -euo pipefail

BASE=/opt/cryptomaster_research
APP=/opt/cryptomaster
DB=$APP/local_learning_storage/cache.sqlite
EPOCH=$APP/local_learning_storage/performance_epoch.json
POLICY=paper_source_learning_v1
KEEP_DAYS=30
CODE=$BASE/code

exec 9>"$BASE/.run.lock"
flock -n 9 || { echo "another evaluation is running" >&2; exit 0; }

run_id="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BASE/reports/$run_id"
snapshot="$out/snapshot.sqlite"
mkdir -p "$out"
status() { printf '%s %s %s\n' "$(date -u +%FT%TZ)" "$1" "$run_id" > "$BASE/STATUS.tmp"; mv "$BASE/STATUS.tmp" "$BASE/STATUS"; }
fail() { status "FAILED:$1"; echo "$(date -u +%FT%TZ) ERROR $1 run=$run_id" >> "$BASE/verdict.log"; rm -f "$snapshot"; exit 1; }
trap 'fail "line_$LINENO"' ERR
trap 'fail signal' INT TERM

# Consistent read-only snapshot (SQLite online backup) used by every step below.
python3 - "$DB" "$snapshot" <<'PY' || fail snapshot
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY

epoch_since="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["started_at"])' "$EPOCH")"
prereg_after="$(cat "$BASE/prereg_after" 2>/dev/null || true)"

PRERESULT="$BASE/prereg_result.json"
until_args=()
[ -n "$prereg_after" ] && until_args=(--until "$prereg_after")
# Historical epoch is frozen at the preregistration cutoff while C1 is blind.
python3 -B "$CODE/scripts/research/p0_8_plus_epoch_report.py" --db "$snapshot" --since "$epoch_since" "${until_args[@]}" --out "$out"   || fail epoch_report
replay_args=(--db "$snapshot" --since "$epoch_since" --out "$out")
[ -n "$prereg_after" ] && replay_args+=(--prereg-after "$prereg_after" --prereg-result "$PRERESULT")
replay_line="$(python3 -B "$CODE/scripts/research/learner_replay_report.py" "${replay_args[@]}")" || fail replay
cohort_line=""
if [ -n "$prereg_after" ]; then
  if [ -f "$PRERESULT" ]; then
    # Fixed end reached: the full MAX_DATA cohort report may now be computed.
    python3 -B "$CODE/scripts/research/p0_8_plus_epoch_report.py" --db "$snapshot" --since "$prereg_after" --out "$out/cohort"       || fail cohort_report
  else
    # Blind phase: counts only, no outcome statistics on fresh trades.
    cohort_line="$(python3 - "$snapshot" "$prereg_after" <<'PY'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
n, symbols = db.execute("select count(*), count(distinct symbol) from closed_trades where entry_ts > ?",
                        (float(sys.argv[2]),)).fetchone()
print(f"COHORT_BLIND fresh_closed={n} symbols={symbols}")
PY
)" || fail cohort_count
  fi
fi
# Candidate funnel (counts only, from the journal tap); never fails the run.
funnel_line="$(python3 -B "$CODE/scripts/research/funnel_tap.py" summary --out "$BASE/funnel" --hours 12 2>/dev/null || echo "FUNNEL error")"

# Manifest: what exactly this run saw.
python3 - "$out" "$snapshot" "$CODE" "$APP" "$run_id" "$prereg_after" <<'PY' || fail manifest
import hashlib, json, pathlib, sqlite3, subprocess, sys
out, snap, code, app, run_id, prereg = sys.argv[1:7]
sha = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
db = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
rows, last_exit = db.execute("select count(*), max(exit_ts) from closed_trades").fetchone()
shown = subprocess.run(["systemctl", "show", "cryptomaster", "-p", "Environment", "--value"],
                       capture_output=True, text=True)
env = shown.stdout.split() if shown.returncode == 0 else ["UNAVAILABLE:systemctl_rc=%d" % shown.returncode]
manifest = {
    "run_id": run_id, "snapshot_sha256": sha(snap), "closed_trades_rows": rows, "last_exit_ts": last_exit,
    "prereg_after": prereg or None,
    "research_code": {str(p.relative_to(code)): sha(p) for p in sorted(pathlib.Path(code).rglob("*.py"))},
    "bot_code": {f: sha(pathlib.Path(app) / f) for f in ("src/services/paper_source_learning.py",
                 "src/services/paper_learning_budget.py", "src/services/signal_router.py")},
    "bot_env_paper": sorted(kv for kv in env if kv.startswith(("PAPER_", "TRADING_MODE"))),
}
pathlib.Path(out, "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
PY
rm -f "$snapshot"

# Summary lines only after every step succeeded.
python3 - "$out/report.json" "$out/cohort/report.json" "$POLICY" "$run_id" <<'PY' >> "$BASE/verdict.log" || fail summary
import json, sys, datetime, pathlib
report_path, cohort_path, policy, run_id = sys.argv[1:5]
fmt = lambda v: "NA" if v is None else f"{v:+.2f}"
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def lines(path, label):
    report = json.load(open(path))
    total, budget = report["total"], report["total"].get("evidence_budget") or {}
    exp = report["experiments"].get(policy, {}).get("verdict")
    out = [f"{ts} {label} run={run_id} total_n={total.get('n')} total_mean={fmt(total.get('mean_net_bps'))} "
           f"total_lower={fmt(budget.get('lower_bound_bps'))} total_upper={fmt(budget.get('upper_bound_bps'))}"
           + ("" if exp is None else
              f" codes={','.join(exp['codes'])} adaptive_n={exp['adaptive']['n']} control_n={exp['control']['n']} "
              f"diff={fmt(exp['diff_bps'])} ci=[{fmt(exp['diff_low_bps'])},{fmt(exp['diff_high_bps'])}]")]
    diag = report.get("learning_diagnostics", {}).get(policy)
    if diag:
        est, disp, pers = diag["estimate_vs_outcome"], diag["context_dispersion"], diag["context_persistence"]
        curve = ",".join(fmt(q["diff_bps"]) for q in diag["learning_curve"])
        out.append(f"{ts} LEARN_{label} run={run_id} codes={','.join(diag['reasons'])} "
                   f"gross={fmt(diag['signal_gross']['mean_bps'])} n={diag['signal_gross']['n']} "
                   f"ctx_p={'NA' if disp is None else format(disp['p_value'], '.3f')} "
                   f"persist_rho={'NA' if pers is None else fmt(pers['spearman'])} "
                   f"estimate_rho={fmt(est['spearman'])} estimate_n={est['n']} curve_descriptive=[{curve}]")
    return out

result = lines(report_path, "EPOCH")
if pathlib.Path(cohort_path).exists():
    result += lines(cohort_path, "COHORT")
print("\n".join(result))
PY
echo "$(date -u +%FT%TZ) REPLAY run=$run_id $replay_line" >> "$BASE/verdict.log"
[ -n "$cohort_line" ] && echo "$(date -u +%FT%TZ) $cohort_line run=$run_id" >> "$BASE/verdict.log"
echo "$(date -u +%FT%TZ) $funnel_line run=$run_id" >> "$BASE/verdict.log"

find "$BASE/reports" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} + || fail retention
ln -sfn "$out" "$BASE/latest"
trap - ERR INT TERM
status OK
