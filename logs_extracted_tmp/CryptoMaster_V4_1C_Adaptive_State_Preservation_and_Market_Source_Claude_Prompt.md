# CryptoMaster V4.1C — Preserve Running Adaptive Learning State
## Minimal operational permission remediation + futures/spot market-source classification
### Run only on the active Hetzner host `/opt/cryptomaster`

**Situation already established from V4.1B triage:**
- Runtime repository: `/opt/cryptomaster`
- Running deployed HEAD: `b6311c2113f9a6d5e8e0bb1ae317326a489d2911`
- Service: `cryptomaster.service`, active PID `1448746`, started `2026-05-25 13:33:15 UTC`
- Tracked working tree clean; untracked `venv/` hygiene issue only
- `data/paper_open_positions.json` existed as empty JSON at snapshot time
- `server_local_backups/paper_adaptive_learning_state.json` absent
- 6 canonical PAPER adaptive learning updates occurred since PID start
- Every one of those six save attempts failed with:
  `[PAPER_LEARNING_STATE_SAVE] failed: [Errno 13] Permission denied: 'server_local_backups/paper_adaptive_learning_state.json'`
- Directory was observed as `root:root` mode `755`; service runs as user `cryptomaster`, which cannot write to that directory
- D_NEG isolation appeared intact; no REAL execution evidence in reviewed window

## Critical correction to earlier report

Do **not** blindly run `chown cryptomaster:cryptomaster /opt/cryptomaster/server_local_backups` before inspecting the save implementation and directory content.

Reason:
- If saving uses direct overwrite of one state file, the narrowest remediation may be provisioning only that single file with service ownership.
- If saving uses atomic temp-file + rename/replace, directory write permission is required.
- Changing ownership of an entire backup directory may be broader than necessary if it contains forensic/archive files.

## Objective

Preserve the currently running in-memory adaptive learning state with the smallest safe runtime permission change, **without restarting the service** and without touching trading logic.

Secondarily, classify the market stream source correctly: `wss://stream.binance.com:9443` is Binance **Spot** market data, not the USDⓈ-M Futures `fstream` routed market data. Do not patch that source mismatch in this task; report its impact.

---

# Hard constraints

```text
- Do not edit Python/source/config/.env/systemd files.
- Do not run pytest.
- Do not run git fetch/pull/checkout/reset/clean/stash/commit/deploy.
- Do not stop or restart cryptomaster.service.
- Do not alter strategy, thresholds, entries, exits, learning rules, Firebase, Android contract or REAL/live path.
- Do not print secrets or .env contents.
- Permission/state-file creation is allowed only after the gated read-only inspection below proves the narrow remediation.
- If uncertain, stop with REMEDIATION_NOT_SAFE_TO_APPLY.
```

---

# Stage A — Read-only precheck and determine exact save mechanism

```bash
set -euo pipefail
RUNTIME_REPO="/opt/cryptomaster"
STATE_REL="server_local_backups/paper_adaptive_learning_state.json"
STATE_PATH="$RUNTIME_REPO/$STATE_REL"
BACKUP_DIR="$RUNTIME_REPO/server_local_backups"

cd "$RUNTIME_REPO"

echo "=== ACTIVE BASELINE ==="
date -u --iso-8601=seconds
systemctl show cryptomaster.service -p ActiveState -p MainPID -p ActiveEnterTimestamp -p User -p WorkingDirectory -p ExecStart --no-pager
echo "HEAD=$(git rev-parse HEAD)"
git status --short --untracked-files=no

echo "=== PATH PERMISSIONS BEFORE ==="
id cryptomaster
namei -l "$STATE_PATH" || true
stat -c '%A %a %U:%G %n' "$RUNTIME_REPO" "$BACKUP_DIR" 2>&1 || true
if [ -e "$STATE_PATH" ]; then stat -c '%A %a %U:%G %s %y %n' "$STATE_PATH"; else echo "ABSENT $STATE_PATH"; fi
runuser -u cryptomaster -- test -w "$BACKUP_DIR" && echo "SERVICE_DIR_WRITE=YES" || echo "SERVICE_DIR_WRITE=NO"

echo "=== BACKUP DIR CONTENTS — OWNERS/MODE ONLY ==="
find "$BACKUP_DIR" -maxdepth 2 -printf '%M %u:%g %s %TY-%Tm-%TdT%TH:%TM:%TS %p\n' 2>/dev/null | sort | sed -n '1,200p'

echo "=== SAVE IMPLEMENTATION REFERENCES ==="
grep -RInE --exclude-dir=.git --exclude-dir=venv --exclude-dir=__pycache__ \
  'PAPER_LEARNING_STATE_SAVE|paper_adaptive_learning_state|json\.dump|write_text|open\(|NamedTemporaryFile|mkstemp|os\.replace|os\.rename|Path\(' \
  src tests scripts start.py main.py 2>/dev/null | sed -n '1,260p' || true
```

## Mandatory inspection conclusion before mutation

Identify the exact file and function that saves `paper_adaptive_learning_state.json`, and quote the relevant lines in the report.

Classify:

```text
SAVE_METHOD=DIRECT_FILE_WRITE
  if it opens/writes the exact final state path in place and does not create/rename a temp file.

SAVE_METHOD=ATOMIC_DIRECTORY_WRITE
  if it creates a temp sibling file, uses os.replace/os.rename, or otherwise needs directory create/rename access.

SAVE_METHOD=UNRESOLVED
  if code path is ambiguous or cannot be proven.
```

Also classify directory content:

```text
BACKUP_DIR_SCOPE=DEDICATED_RUNTIME_STATE
  only if its contents and code references prove this directory is intended writable runtime-state storage.

BACKUP_DIR_SCOPE=MIXED_OR_UNRESOLVED
  if it contains archives/forensic backups or purpose is unclear.
```

### Stop condition

If `SAVE_METHOD=UNRESOLVED`, do not modify permissions or files. Return `REMEDIATION_NOT_SAFE_TO_APPLY`.

---

# Stage B — Minimal permitted remediation, conditional on Stage A

## Option B1 — Narrow target-file remediation
Use only if:

```text
SAVE_METHOD=DIRECT_FILE_WRITE
AND STATE_PATH is absent
```

Create only the required state target, writable by the service; do not change directory owner:

```bash
set -euo pipefail
RUNTIME_REPO="/opt/cryptomaster"
STATE_PATH="$RUNTIME_REPO/server_local_backups/paper_adaptive_learning_state.json"

# Create an empty initial JSON object as the specific target file only.
# This is an operational persistence repair, not a code/config change.
install -o cryptomaster -g cryptomaster -m 600 /dev/stdin "$STATE_PATH" <<'JSON'
{}
JSON

stat -c '%A %a %U:%G %s %y %n' "$STATE_PATH"
runuser -u cryptomaster -- test -w "$STATE_PATH" \
  && echo "TARGET_FILE_WRITABLE_BY_SERVICE=YES" \
  || { echo "TARGET_FILE_WRITABLE_BY_SERVICE=NO"; exit 51; }
```

## Option B2 — Directory-write remediation
Use only if:

```text
SAVE_METHOD=ATOMIC_DIRECTORY_WRITE
AND BACKUP_DIR_SCOPE=DEDICATED_RUNTIME_STATE
```

Change only ownership required for the established runtime-state directory:

```bash
set -euo pipefail
BACKUP_DIR="/opt/cryptomaster/server_local_backups"

chown cryptomaster:cryptomaster "$BACKUP_DIR"
stat -c '%A %a %U:%G %n' "$BACKUP_DIR"
runuser -u cryptomaster -- test -w "$BACKUP_DIR" \
  && echo "STATE_DIRECTORY_WRITABLE_BY_SERVICE=YES" \
  || { echo "STATE_DIRECTORY_WRITABLE_BY_SERVICE=NO"; exit 52; }
```

## No safe automatic fix
If:

```text
SAVE_METHOD=ATOMIC_DIRECTORY_WRITE
AND BACKUP_DIR_SCOPE=MIXED_OR_UNRESOLVED
```

do not apply permissions. Return `REMEDIATION_REQUIRES_DESIGN_DECISION`, because a code/path migration to a dedicated writable runtime-state directory may be safer than granting write access to a mixed backup directory.

---

# Stage C — Validate preservation WITHOUT restart

## Critical rule

```text
DO NOT RESTART THE SERVICE.
```

There are already six in-memory canonical learning updates that were not durably saved. A restart before a successful natural save may lose them.

## C1 — Immediately after permission remediation

```bash
set -euo pipefail
SINCE_FIX="$(date -u --iso-8601=seconds)"
echo "SINCE_FIX=$SINCE_FIX"

systemctl show cryptomaster.service -p ActiveState -p MainPID -p ActiveEnterTimestamp --no-pager
echo "HEAD=$(cd /opt/cryptomaster && git rev-parse HEAD)"

if [ -e /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json ]; then
  stat -c '%A %a %U:%G %s %y %n' /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json
  sha256sum /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json
else
  echo "STATE_FILE_STILL_ABSENT_PENDING_NATURAL_SAVE"
fi
```

## C2 — Validation state

Do not fabricate a save event and do not open a PAPER trade manually. The repair is confirmed only after the running bot naturally performs a canonical adaptive learning update and successfully persists state.

Check recent logs after a natural new canonical update occurs:

```bash
journalctl -u cryptomaster.service --since "$SINCE_FIX" --no-pager \
 | grep -E 'PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_STATE_SAVE|Traceback|UnboundLocalError|PAPER_POSITION_QUARANTINED' \
 | tail -100 || true

if [ -e /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json ]; then
  echo "=== CREATED/PERSISTED STATE FILE ==="
  stat -c '%A %a %U:%G %s %y %n' /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json
  sha256sum /opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json
fi
```

### Interpret carefully

| Evidence after remediation | Status |
|---|---|
| No new canonical update yet | `REMEDIATION_APPLIED_AWAITING_NATURAL_SAVE_PROOF` |
| New canonical update followed by new permission failure | `REMEDIATION_FAILED` |
| New canonical update, no save failure, state file created/updated non-empty by service | `PERSISTENCE_RESTORED_NO_RESTART` |
| Traceback/quarantine appears | `NEW_INTEGRITY_BLOCKER` |

Do not restart even after persistence is restored; return report for review first.

---

# Stage D — Correct market-source classification, READ-ONLY ONLY

The previous report marked this as Binance Futures compatibility PASS:

```text
wss://stream.binance.com:9443 ... @bookTicker / @depth20@100ms
```

That classification is incorrect for a USDⓈ-M Futures execution-truth claim. Official Binance documentation maps:

```text
wss://stream.binance.com:9443  -> Binance Spot WebSocket market data
wss://fstream.binance.com/...  -> Binance USDⓈ-M Futures WebSocket market data
```

A bot may intentionally use Spot market data as a predictive feature for Futures trading, but:

```text
- Spot book cannot be treated as Futures fill/execution liquidity.
- Spot bid/ask/depth cannot calibrate Futures slippage or execution cost.
- Mixed spot book + futures premium/funding must be explicitly labelled and segmented.
```

Read-only classification:

```bash
cd /opt/cryptomaster

echo "=== MARKET SOURCE CLASSIFICATION ==="
grep -RInE --exclude-dir=.git --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=data --exclude-dir=server_local_backups \
  'stream\.binance\.com|fstream\.binance\.com|@depth|@bookTicker|premiumIndex|fapi\.binance\.com|markPrice|aggTrade' \
  src bot2 start.py main.py scripts 2>/dev/null | sed -n '1,260p' || true

echo "=== USE OF ORDERBOOK/SPREAD IN DECISION OR PNL PATH ==="
grep -RInE --exclude-dir=.git --exclude-dir=venv --exclude-dir=__pycache__ \
  'spread|slippage|order.?book|depth|bookTicker|execution_quality|fill_price|bid|ask' \
  src 2>/dev/null | sed -n '1,300p' || true
```

Required classification:

| Classification | Meaning |
|---|---|
| `SPOT_FEATURE_ONLY_ACCEPTABLE_FOR_NOW` | Spot stream is used only as signal/context, not PAPER futures fill/slippage/cost truth |
| `FUTURES_EXECUTION_TRUTH_BLOCKER` | Spot bid/ask/depth influences PAPER fill, slippage, cost gate or purported futures execution quality |
| `UNRESOLVED_REQUIRES_SCOPED_CODE_REVIEW` | Usage cannot be traced conclusively read-only |

Do not patch WebSocket endpoints or strategy in this task.

---

# Required output

```markdown
# CryptoMaster V4.1C Adaptive-State Preservation & Market-Source Report

## Verdict
REMEDIATION_NOT_SAFE_TO_APPLY | REMEDIATION_REQUIRES_DESIGN_DECISION | REMEDIATION_APPLIED_AWAITING_NATURAL_SAVE_PROOF | PERSISTENCE_RESTORED_NO_RESTART | REMEDIATION_FAILED | NEW_INTEGRITY_BLOCKER

## Safety declaration
- No source/config edit:
- No git mutation:
- No tests:
- No service stop/restart:
- No strategy/economic/REAL change:
- Filesystem mutation performed, if any:

## Baseline
| Item | Evidence |
|---|---|
| Running HEAD | ... |
| PID/start | ... |
| State save failures before repair | ... |
| In-memory canonical updates already at risk | ... |

## Save implementation proof
| Item | Evidence |
|---|---|
| Source file/function | ... |
| Relevant lines | ... |
| Save method | DIRECT_FILE_WRITE / ATOMIC_DIRECTORY_WRITE / UNRESOLVED |
| Directory scope | DEDICATED_RUNTIME_STATE / MIXED_OR_UNRESOLVED |
| Narrow remediation selected | B1 / B2 / NONE |

## Permission remediation
| Path | Before | Action | After |
|---|---|---|---|
| ... | ... | ... | ... |

## Persistence validation without restart
| Evidence | Result |
|---|---|
| Service PID unchanged | ... |
| New natural canonical update after fix? | ... |
| Save error after fix? | ... |
| State file created/updated by running service? | ... |
| Durable adaptive state restored? | PROVEN / AWAITING_PROOF / FALSE |

## Market-source classification
| Source/path | Asset venue | Used for | Assessment |
|---|---|---|---|
| stream.binance.com:9443 | Spot | ... | ... |
| fapi/premiumIndex | USDⓈ-M Futures REST | ... | ... |
| fstream futures stream | Present/absent | ... | ... |

## Decision
- Do not restart service in this task.
- Do not run test acceptance while persistence proof is absent.
- Next separate task permitted: WAIT_FOR_NATURAL_SAVE_VALIDATION | DEDICATED_STATE_PATH_PATCH | FUTURES_MARKET_SOURCE_PATCH_REVIEW | PHASE_0_TEST_ACCEPTANCE_PREPARATION
```

---

# Stop immediately if

```text
- Save implementation cannot be established.
- Required remediation would touch code/config or broad unrelated directory contents.
- Service PID changes unexpectedly.
- New traceback, quarantine or evidence of REAL execution appears.
- A permission fix fails to allow the verified save mechanism.
```
