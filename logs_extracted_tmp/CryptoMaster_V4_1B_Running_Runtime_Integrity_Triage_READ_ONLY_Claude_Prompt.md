# CryptoMaster V4.1B — Running Runtime Integrity Triage (READ-ONLY)
## Active deployed runtime `b6311c2` · Diagnose persistence failure and compatibility blockers without changing service

**Context from server evidence already observed:**
- Actual runtime repository is `/opt/cryptomaster` via systemd `WorkingDirectory`.
- `cryptomaster.service` is ACTIVE with PID `1448746`; do not stop/restart it in this task.
- Runtime `main` and `origin/main` are both at `b6311c2113f9a6d5e8e0bb1ae317326a489d2911` (`P1.1AP-O1A1G: Isolate full PAPER test suite from runtime files`).
- Current snapshot showed `data/paper_open_positions.json` exists as 2-byte empty JSON and `server_local_backups/paper_adaptive_learning_state.json` is absent.
- Runtime logs show repeated:
  `PAPER_LEARNING_STATE_SAVE failed: [Errno 13] Permission denied: 'server_local_backups/paper_adaptive_learning_state.json'`.
- PAPER learning is running in memory, but adaptive state persistence is not proven durable.
- `D_NEG_EV_CONTROL` logs appear shadow-skipped; do not alter this path.
- Earlier endpoint grep returned an empty section; determine whether this means no matches or missing search tool/source pattern.

## Goal

Perform **read-only forensic triage** only. Determine:
1. Exact permission/ownership cause of adaptive-state save failure.
2. Whether adaptive state is ever persisted elsewhere.
3. Whether there is evidence of invalid learning/quarantine/REAL orders since PID start.
4. Whether runtime source uses Binance legacy WebSocket endpoints.
5. Whether `venv/` untracked artifacts are only audit noise or affect deploy/source verification.

## Absolute constraints

- Do not edit code or configuration.
- Do not run pytest.
- Do not execute `git fetch`, `pull`, `checkout`, `reset`, `clean`, `stash`, commit or deploy.
- Do not start, stop or restart `cryptomaster.service`.
- Do not run `chown`, `chmod`, `mkdir`, `touch`, `rm`, `mv`, redirections into repo paths, or any write-probe.
- Do not print `.env` values, API keys, Firebase credentials, tokens, or private keys.
- REAL trading remains forbidden.
- Return report only; no fix in this session.

---

## Task 1 — Confirm active deployed baseline without untracked venv spam

```bash
set -euo pipefail
RUNTIME_REPO="/opt/cryptomaster"
cd "$RUNTIME_REPO"

echo "=== BASELINE ==="
date -u --iso-8601=seconds
systemctl is-active cryptomaster.service || true
systemctl show cryptomaster.service -p MainPID -p ActiveEnterTimestamp -p User -p WorkingDirectory -p ExecStart --no-pager

echo "HEAD_FULL=$(git rev-parse HEAD)"
echo "HEAD_SHORT=$(git rev-parse --short HEAD)"
git show -s --format='%H %ci %s' HEAD
echo "=== TRACKED MODIFICATIONS ONLY ==="
git status --short --untracked-files=no
echo "=== UNTRACKED SUMMARY TOP LEVEL ONLY ==="
git status --short --untracked-files=normal | sed -n '1,80p'
echo "=== VENV IGNORE CHECK ==="
git check-ignore -v venv venv/pyvenv.cfg 2>&1 || true
```

Report whether any **tracked** source/runtime file is modified. The untracked `venv/` tree is important hygiene evidence but must not overwhelm output.

---

## Task 2 — Diagnose adaptive-state permission failure without writing

```bash
cd "$RUNTIME_REPO"
echo "=== SERVICE USER / DIRECTORY PERMISSIONS ==="
id cryptomaster || true
namei -l /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json || true
ls -ld /opt /opt/cryptomaster /opt/cryptomaster/server_local_backups 2>&1 || true
stat -c '%A %a %U:%G %n' /opt/cryptomaster /opt/cryptomaster/server_local_backups 2>&1 || true

echo "=== NON-WRITING ACCESS CHECKS AS SERVICE USER ==="
runuser -u cryptomaster -- test -x /opt/cryptomaster && echo "cryptomaster can traverse repo" || echo "cryptomaster CANNOT traverse repo"
runuser -u cryptomaster -- test -x /opt/cryptomaster/server_local_backups && echo "cryptomaster can traverse backup dir" || echo "cryptomaster CANNOT traverse backup dir"
runuser -u cryptomaster -- test -w /opt/cryptomaster/server_local_backups && echo "cryptomaster directory writable" || echo "cryptomaster directory NOT writable"

echo "=== EXISTING STATE FILES / OWNERS ONLY ==="
find /opt/cryptomaster/server_local_backups -maxdepth 3 -type f \
  \( -name '*paper_adaptive*' -o -name '*adaptive*state*' -o -name '*paper_open_positions*' \) \
  -printf '%M %u:%g %s %TY-%Tm-%TdT%TH:%TM:%TS %p\n' 2>/dev/null \
  | sort | tail -80 || true
```

Do **not** create a test file. The `test -w` check is sufficient and non-writing.

---

## Task 3 — Determine whether runtime state is lost or persisted elsewhere

```bash
cd "$RUNTIME_REPO"
echo "=== SOURCE PATH REFERENCES FOR ADAPTIVE STATE ==="
grep -RInE --exclude-dir=.git --exclude-dir=venv --exclude-dir=__pycache__ \
  'paper_adaptive_learning_state|PAPER_LEARNING_STATE_SAVE|adaptive.*state|server_local_backups' \
  src tests scripts start.py main.py 2>/dev/null | sed -n '1,220p' || true

echo "=== LOG COUNTS SINCE CURRENT PID START ==="
SINCE="2026-05-25 13:33:15"
journalctl -u cryptomaster.service --since "$SINCE" --no-pager > /tmp/cryptomaster_v41b_journal_readonly.txt
for p in \
  'PAPER_LEARNING_STATE_SAVE.*failed' \
  'PAPER_CANONICAL_LEARNING_UPDATE' \
  'PAPER_LEARNING_SHADOW_SKIP' \
  'PAPER_POSITION_QUARANTINED' \
  'Traceback' \
  'UnboundLocalError' \
  'REAL' \
  'LIVE' \
  'ORDER_TRADE_UPDATE'; do
  printf '%-45s ' "$p"
  grep -Ec "$p" /tmp/cryptomaster_v41b_journal_readonly.txt || true
done

echo "=== LAST STATE-SAVE FAILURES ==="
grep -E 'PAPER_LEARNING_STATE_SAVE.*failed|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|PAPER_POSITION_QUARANTINED|Traceback|UnboundLocalError' \
  /tmp/cryptomaster_v41b_journal_readonly.txt | tail -120 || true
rm -f /tmp/cryptomaster_v41b_journal_readonly.txt
```

`/tmp` output is allowed only as temporary forensic output outside the repo; delete it immediately as above.

For any `[REAL]`/`[LIVE]` text, classify whether it indicates actual live order execution or just log labels/config text. Do not infer REAL safety solely from absence of a grep string.

---

## Task 4 — Binance endpoint compatibility inventory using `grep`, not `rg`

The earlier search returned no content; verify with a portable search excluding `venv/`.

```bash
cd "$RUNTIME_REPO"
echo "=== BINANCE ENDPOINT SOURCE MATCHES ==="
grep -RInE --exclude-dir=.git --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=data --exclude-dir=server_local_backups \
  'fstream\.binance\.com|@depth|@rpiDepth|@bookTicker|@markPrice|@aggTrade|listenKey|listen_key|userDataStream|forceOrder|ALGO_UPDATE' \
  src bot2 start.py main.py scripts tests 2>/dev/null | sed -n '1,260p' || true
```

Classify runtime-used matches:

| Stream/API type | Runtime file:line | Observed path | Required mapping | Status |
|---|---|---|---|---|
| depth / bookTicker | ... | ... | `/public` | PASS/BLOCKER/NOT_USED |
| markPrice / aggTrade | ... | ... | `/market` | PASS/BLOCKER/NOT_USED |
| authenticated user data | ... | ... | `/private` | PASS/BLOCKER/NOT_USED |

If URLs are constructed dynamically and cannot be determined by grep, report `UNRESOLVED_REQUIRES_CODE_REVIEW`; do not declare PASS.

---

## Required output format

```markdown
# CryptoMaster V4.1B Running Runtime Integrity Triage Report

## Verdict
INTEGRITY_BLOCKER_FOUND | READ_ONLY_TRIAGE_INCOMPLETE | NO_IMMEDIATE_INTEGRITY_BLOCKER_DEMONSTRATED

## Safety declaration
- No code/config change:
- No git mutation:
- No tests:
- No service action:
- No repo/runtime-state write:
- Temporary `/tmp` log extract removed:

## Active runtime baseline
| Item | Evidence |
|---|---|
| Repo | /opt/cryptomaster |
| Running HEAD | ... |
| Service/PID/start | ... |
| Tracked working-tree status | ... |
| Untracked `venv/` hygiene status | ... |

## Critical finding: adaptive-state persistence
| Item | Evidence | Severity |
|---|---|---|
| State file exists? | ... | ... |
| State-save failures count | ... | ... |
| Service user write access to directory | ... | ... |
| Root cause supported by evidence | ... | ... |
| Adaptive learning durable across restart? | PROVEN / NOT PROVEN / FALSE | ... |

## Runtime behavior since PID start
| Signal | Count / evidence | Assessment |
|---|---:|---|
| Canonical learning updates | ... | ... |
| D_NEG shadow skips | ... | ... |
| Quarantine | ... | ... |
| Traceback / UnboundLocalError | ... | ... |
| Evidence of actual REAL order | ... | ... |

## Binance compatibility inventory
| Component | File:line | Observed URL/stream | Status |
|---|---|---|---|

## Decision
- Do not run Phase 0 test acceptance while the service is active.
- Do not implement architecture V4.1 yet.
- If permission failure is confirmed: prepare one minimal, reviewed runtime-permission remediation plan; do not bundle strategy changes.
- If Binance runtime endpoint blocker is found: prepare a separate compatibility patch prompt.
```
