# CryptoMaster V4.1A — SERVER BASELINE DISCOVERY PRECHECK
## Read-only discovery before any Phase 0 audit

**Purpose:** The prior Phase 0 audit correctly failed because it ran in a Windows checkout, not on the Hetzner/Linux runtime host. Run this only on the server that hosts `cryptomaster.service`, or in a Claude Code session with shell access to it.

## Scope

This is **not** Phase 0 acceptance yet. Discover the true server baseline first.

### Absolute constraints
- Read-only only.
- Do not edit code or configuration.
- Do not run tests.
- Do not run `git fetch`, `git pull`, `git checkout`, `git reset`, `git merge`, `git clean`, `git stash`, commit or deploy.
- Do not start, stop or restart `cryptomaster.service`.
- Do not modify, delete or move runtime-state files.
- Do not assume `791d16c` or `b6311c2` is the correct current baseline/candidate.
- REAL trading remains forbidden.

## Task 1 — Verify Linux production host and service state

```bash
set -euo pipefail
echo "=== HOST / USER / TIME ==="
hostname
whoami
date -u --iso-8601=seconds
uname -a
pwd

echo "=== SERVICE STATE — READ ONLY ==="
systemctl status cryptomaster.service --no-pager -l 2>&1 | sed -n '1,50p' || true
systemctl is-active cryptomaster.service 2>&1 || true
systemctl is-enabled cryptomaster.service 2>&1 || true
systemctl cat cryptomaster.service --no-pager 2>&1 || true
```

If `systemctl` is unavailable or this is not the Linux runtime host, stop and report `FAIL_WRONG_ENVIRONMENT`.

## Task 2 — Identify actual runtime repository

Use `WorkingDirectory` and `ExecStart` from the service unit as primary evidence. You may read likely directories:

```bash
echo "=== POSSIBLE REPOSITORIES ==="
for d in /opt/CryptoMaster_srv /opt/cryptomaster /home/*/CryptoMaster_srv /root/CryptoMaster_srv; do
  if [ -d "$d/.git" ]; then echo "FOUND_GIT_REPO=$d"; fi
done
```

If the repository matching the service cannot be identified unambiguously, report `FAIL_REPO_NOT_IDENTIFIED`.

## Task 3 — Read Git baseline without changing anything

```bash
RUNTIME_REPO="<verified path from Task 2>"
cd "$RUNTIME_REPO"

echo "=== VERIFIED RUNTIME REPO ==="
echo "RUNTIME_REPO=$RUNTIME_REPO"
echo "HEAD_FULL=$(git rev-parse HEAD)"
echo "HEAD_SHORT=$(git rev-parse --short HEAD)"
git log --oneline --decorate -25
git status --short --untracked-files=all
git remote -v
git branch -avv --no-abbrev
git show-ref --heads --tags || true

echo "=== RELEVANT LOCAL COMMITS ==="
git log --all --oneline --decorate --grep='O1A1\|isolation\|adaptive\|runtime artifact\|paper' -60 || true

echo "=== PREVIOUSLY REFERENCED HASHES — CHECK ONLY, NO FETCH ==="
for h in 791d16c b6311c2 97e6777 6c52cc0; do
  if git cat-file -e "${h}^{commit}" 2>/dev/null; then
    echo "FOUND_COMMIT $h -> $(git show -s --oneline "$h")"
  else
    echo "MISSING_COMMIT $h"
  fi
done
```

## Task 4 — Read critical runtime-state evidence

```bash
cd "$RUNTIME_REPO"
echo "=== CRITICAL RUNTIME STATE FILES ==="
for f in data/paper_open_positions.json server_local_backups/paper_adaptive_learning_state.json; do
  if [ -e "$f" ]; then
    echo "EXISTS $f"
    sha256sum "$f"
    stat "$f"
    wc -c "$f"
  else
    echo "ABSENT $f"
  fi
done

echo "=== RUNTIME ARTIFACT INVENTORY — READ ONLY ==="
find data server_local_backups -maxdepth 2 -type f -printf '%p\t%s bytes\t%TY-%Tm-%TdT%TH:%TM:%TS\n' 2>/dev/null   | sort | sed -n '1,200p' || true
```

Do not print secrets or read credential material.

## Task 5 — Read recent service context only

```bash
echo "=== RECENT SERVICE CONTEXT ==="
journalctl -u cryptomaster.service --no-pager -n 160 2>&1  | grep -Ei 'Started|Stopped|Traceback|UnboundLocalError|PAPER_POSITION_QUARANTINED|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|epoch|adaptive'  | tail -100 || true
```

This is context only; do not declare learning valid from log snippets.

## Required output

```markdown
# CryptoMaster V4.1A Server Baseline Discovery Report

## Verdict
PASS_SERVER_BASELINE_DISCOVERED | FAIL_WRONG_ENVIRONMENT | FAIL_REPO_NOT_IDENTIFIED | FAIL_READ_ONLY_DISCOVERY

## Safety declaration
- No code edited:
- No git mutation/fetch/pull/checkout/reset:
- No tests executed:
- No systemd action:
- No runtime state modified:

## Host and service evidence
| Item | Observed |
|---|---|
| Hostname | ... |
| OS | ... |
| UTC time | ... |
| Service state | ... |
| WorkingDirectory / ExecStart | ... |

## Verified runtime repository
| Item | Value |
|---|---|
| Repo path | ... |
| HEAD full SHA | ... |
| HEAD short SHA | ... |
| Working tree status | ... |
| Relevant branches/remotes | ... |

## Previously referenced commits
| Commit | Present locally? | Description if present |
|---|---:|---|
| 791d16c | ... | ... |
| b6311c2 | ... | ... |
| 97e6777 | ... | ... |
| 6c52cc0 | ... | ... |

## Runtime state evidence
| Path | Exists/Absent | SHA256 | Size / modified |
|---|---|---|---|
| data/paper_open_positions.json | ... | ... | ... |
| server_local_backups/paper_adaptive_learning_state.json | ... | ... | ... |

## Recent runtime context
- ...

## Decision
- Do not run Phase 0 acceptance yet.
- Do not restart the service.
- Return this report so a corrected audit prompt can be prepared from the actual server baseline.
```

## Stop conditions
Stop with FAIL if this is not the production host, if the service repository cannot be identified, if permissions block the discovery, or if any next action would require modification.
