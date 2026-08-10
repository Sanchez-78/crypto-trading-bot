# Finding: `hetzner-deploy-apply.yml` reports `success` even when Gate 5 refuses to deploy

**Date:** 2026-08-10, cycle 27
**Severity:** Medium (operational confusion, not a safety hole -- the gate itself correctly refused)

## What happened

Ran `Hetzner Deploy Apply (manual, gated)` with `confirm=DEPLOY` to ship
today's session's work (commit `869a62f6`, includes the P0.8+ shadow
evaluator live wiring). GitHub Actions reported the run as
`conclusion: success` with all green checkmarks (`gh run watch` and
`gh api .../runs/<id> --jq '{status,conclusion}'` both agree).

**But the remote script's own log shows it refused to deploy:**
```
live=f54cdd55f3ca08ca9c38252d3ac8834f84d3387b target=869a62f69796b99d34afa6a4024c8828df1077fc confirm=DEPLOY
CRITICAL: open-position state = '1' (fail-closed) — not deploying
```
Confirmed independently via direct SSH: `git log --oneline -1` on the
server still showed `f54cdd55` (the old HEAD) minutes after the "successful"
run, and `curl .../api/dashboard/metrics` showed `open_positions: 1`
(one ETHUSDT position, opened 08:51:36 UTC, right around when the
workflow ran).

## Root cause (not fully diagnosed, flagged for a future patch)

Gate 5 in `.github/workflows/hetzner-deploy-apply.yml` is inside a
heredoc executed over SSH (`ssh ... "... bash -s" << 'REMOTE_EOF' ... exit 1 ... REMOTE_EOF`).
The `exit 1` inside that remote script should propagate as a non-zero
exit from the `ssh` command, which should fail the GH Actions step (bash
steps run with `set -e` per the job's own `shell: /usr/bin/bash -e {0}`
seen in the log). It evidently does not propagate correctly in this case
-- possibly the SSH command's own exit code is being swallowed by a
pipe/tee (e.g. logging to `artifacts/` alongside), or a `|| true` /
similar elsewhere in the step masks it. Not investigated further this
session -- this is a workflow-infrastructure bug, out of scope for the
trading-logic work this session was doing, and touching CI/CD workflow
internals deserves its own dedicated, careful pass (this exact
`hetzner-deploy-apply.yml` file is the safety-critical gate protecting
every future deploy; editing it hastily is exactly the kind of risk this
whole session has been trying to avoid elsewhere).

## Practical impact today

None beyond a few minutes of confusion -- the gate itself worked
correctly (refused to deploy over an open position, exactly as designed).
No stranded position, no bad deploy, no live behavior change happened.
The fix is simply: retry once the position count reads 0.

## Recommendation (not actioned this session)

A future, dedicated session should add an explicit final step to
`hetzner-deploy-apply.yml` that checks the SSH command's actual exit code
(e.g. `ssh ... || { echo "::error::remote script failed"; exit 1; }`
explicitly, rather than relying on step-level `set -e` propagation through
what may be a piped/subshell context) so a Gate 5 (or any gate) refusal
surfaces as a red X, not a green check. Until fixed: **always verify a
"successful" deploy by checking `git log -1` on the server directly**, not
just the GH Actions conclusion -- this session's own practice going
forward.
