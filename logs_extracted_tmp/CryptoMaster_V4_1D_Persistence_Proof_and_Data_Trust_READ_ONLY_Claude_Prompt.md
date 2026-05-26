# CryptoMaster V4.1D — Persistence Proof & Data Trust Classification
## READ-ONLY follow-up after V4.1C target-file remediation

**Run only on the active Hetzner runtime host.**

## Established facts from V4.1C

- Runtime repo: `/opt/cryptomaster`
- Running deployment: `b6311c2113f9a6d5e8e0bb1ae317326a489d2911` (`P1.1AP-O1A1G`)
- Service PID observed during remediation: `1448746`, started `2026-05-25 13:33:15 UTC`
- Before remediation: 6 `PAPER_CANONICAL_LEARNING_UPDATE` events and 6 matching `PAPER_LEARNING_STATE_SAVE` permission failures.
- Save implementation proven as `DIRECT_FILE_WRITE` to:
  `server_local_backups/paper_adaptive_learning_state.json`
- Remediation applied at approximately `2026-05-26T06:42:42Z`:
  target file created only, owner `cryptomaster:cryptomaster`, mode `600`, initial content `{}`.
- No restart was performed.
- Independent blocker found: runtime uses Binance Spot `stream.binance.com:9443` book/depth data in execution-quality/fill/slippage/exit paths for a USDⓈ-M Futures bot. Therefore existing learning must not be treated as Futures execution-truth/readiness evidence.

## Objective

Determine whether the running process has naturally persisted its in-memory adaptive state after the narrow permission repair, without changing anything.

Also record the trust classification of the existing adaptive data:
- Preserve it for forensic continuity.
- Do **not** approve it as Futures execution-truth qualification data because it was produced while Spot book/depth influenced futures execution-quality/fill/slippage paths.

## Absolute constraints

```text
- READ ONLY.
- Do not edit source/config/state files.
- Do not run tests.
- Do not run git fetch/pull/checkout/reset/clean/stash/commit/deploy.
- Do not start, stop or restart cryptomaster.service.
- Do not create, truncate, chmod, chown, delete or move any file.
- Do not trigger synthetic PAPER trades.
- Do not expose secrets or .env values.
- REAL remains forbidden.
```

---

# Task 1 — Verify process continuity and current state-file evidence

```bash
set -euo pipefail

RUNTIME_REPO="/opt/cryptomaster"
STATE_PATH="$RUNTIME_REPO/server_local_backups/paper_adaptive_learning_state.json"
FIX_TIME="2026-05-26 06:42:42"
ORIGINAL_PID="1448746"

cd "$RUNTIME_REPO"

echo "=== SERVICE CONTINUITY ==="
date -u --iso-8601=seconds
systemctl show cryptomaster.service -p ActiveState -p MainPID -p ActiveEnterTimestamp -p User -p WorkingDirectory --no-pager
CURRENT_PID="$(systemctl show cryptomaster.service -p MainPID --value)"
echo "ORIGINAL_PID=$ORIGINAL_PID CURRENT_PID=$CURRENT_PID"
if [ "$CURRENT_PID" != "$ORIGINAL_PID" ]; then
  echo "NEW_BLOCKER: PID changed before durability proof; in-memory pre-save state may have been lost."
fi

echo "=== HEAD / TRACKED STATUS ==="
echo "HEAD=$(git rev-parse HEAD)"
git status --short --untracked-files=no

echo "=== STATE FILE CURRENT STATUS ==="
if [ -e "$STATE_PATH" ]; then
  stat -c '%A %a %U:%G %s %y %n' "$STATE_PATH"
  sha256sum "$STATE_PATH"
  python3 - "$STATE_PATH" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
print("JSON_VALID=YES")
print("TOP_LEVEL_TYPE=" + type(data).__name__)
if isinstance(data, dict):
    print("TOP_LEVEL_KEYS=" + ",".join(sorted(map(str, data.keys()))[:40]))
    print("TOP_LEVEL_KEY_COUNT=" + str(len(data)))
print("SIZE_BYTES=" + str(os.path.getsize(path)))
PY
else
  echo "STATE_FILE_ABSENT"
fi
```

Do not print the complete JSON state.

---

# Task 2 — Determine whether a natural update occurred after remediation

```bash
echo "=== EVENTS AFTER PERMISSION REMEDIATION ==="
journalctl -u cryptomaster.service --since "$FIX_TIME" --no-pager \
 | grep -E 'PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_STATE_SAVE|PAPER_LEARNING_SHADOW_SKIP|PAPER_POSITION_QUARANTINED|Traceback|UnboundLocalError|Started|Stopped' \
 | tail -200 || true

echo "=== COUNTS AFTER REMEDIATION ==="
for p in \
  'PAPER_CANONICAL_LEARNING_UPDATE' \
  'PAPER_LEARNING_STATE_SAVE.*failed' \
  'PAPER_LEARNING_SHADOW_SKIP' \
  'PAPER_POSITION_QUARANTINED' \
  'Traceback' \
  'UnboundLocalError' \
  'Started cryptomaster' \
  'Stopped cryptomaster'; do
  printf '%-48s ' "$p"
  journalctl -u cryptomaster.service --since "$FIX_TIME" --no-pager | grep -Ec "$p" || true
done
```

## Persistence decision logic

| Evidence | Verdict |
|---|---|
| PID changed since remediation before proof | `NEW_BLOCKER_STATE_MAY_HAVE_BEEN_LOST` |
| No new canonical update since remediation and file remains initial `{}` | `AWAITING_NATURAL_SAVE_PROOF` |
| New canonical update occurred and is followed by `PAPER_LEARNING_STATE_SAVE ... failed` | `PERSISTENCE_REMEDIATION_FAILED` |
| New canonical update occurred, file mtime/size/hash changed after remediation, JSON valid and non-trivial, with no subsequent save failure | `PERSISTENCE_RESTORED_NO_RESTART` |
| State file disappeared or JSON invalid | `NEW_INTEGRITY_BLOCKER` |

---

# Task 3 — Preserve evidence classification for future design (read-only)

Do not edit stored data. In report only, classify current/pre-fix adaptive history:

```text
trust_classification = LEGACY_SPOT_EXECUTION_UNVERIFIED
eligible_for_future_futures_readiness = FALSE
preserve_for_forensics = TRUE
reason = Runtime Spot book/depth affected execution-quality/fill/slippage/exit logic while bot represents USDⓈ-M Futures PAPER outcomes.
```

This does **not** mean delete current learning state. It means future clean Futures execution-truth epoch must be separated from this legacy dataset.

---

# Required output format

```markdown
# CryptoMaster V4.1D Persistence Proof & Data Trust Report

## Verdict
AWAITING_NATURAL_SAVE_PROOF | PERSISTENCE_RESTORED_NO_RESTART | PERSISTENCE_REMEDIATION_FAILED | NEW_BLOCKER_STATE_MAY_HAVE_BEEN_LOST | NEW_INTEGRITY_BLOCKER

## Safety declaration
- No code/config/state edit:
- No git mutation:
- No tests:
- No service action:
- No synthetic trade:
- No secrets exposed:

## Runtime continuity
| Item | Evidence | Status |
|---|---|---|
| HEAD | ... | ... |
| Original PID | 1448746 | ... |
| Current PID | ... | UNCHANGED / CHANGED |
| Service start timestamp | ... | ... |

## State-file proof
| Item | Evidence | Interpretation |
|---|---|---|
| State file exists | ... | ... |
| Owner/mode | ... | ... |
| Size/hash/mtime | ... | ... |
| JSON validity/summary | ... | ... |
| Natural canonical updates after fix | ... | ... |
| Save failures after fix | ... | ... |

## Persistence determination
- ...

## Runtime integrity events after fix
| Signal | Count | Assessment |
|---|---:|---|
| D_NEG shadow skips | ... | ... |
| Quarantine | ... | ... |
| Traceback / UnboundLocalError | ... | ... |
| Restart evidence | ... | ... |

## Data trust classification
| Dataset | Preserve? | Futures readiness eligible? | Reason |
|---|---:|---:|---|
| Existing adaptive state through current Spot-execution runtime | YES | NO | LEGACY_SPOT_EXECUTION_UNVERIFIED |

## Decision
- Do not restart service until persistence is proven or risk is explicitly accepted.
- Do not run Phase 0 test acceptance while persistence is unproven.
- Do not implement V4 strategy changes.
- If `PERSISTENCE_RESTORED_NO_RESTART`: next separate task is a read-only/scoped `FUTURES_MARKET_SOURCE_PATCH_REVIEW`.
- If `AWAITING_NATURAL_SAVE_PROOF`: rerun this same read-only report after the next natural canonical learning update.
```
