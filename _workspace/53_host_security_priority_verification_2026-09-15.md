# 53 — Host security priority (5 items) — read-only verification + one urgent fix

## Status: 1 CRITICAL fixed (disk full), 1 root-cause fixed (logrotate), 3 items VERIFIED (still open, need separate approval), production untouched otherwise

Per `CLAUDE_HOST_SECURITY_PRIORITY_2026-09-15.md`'s 5-item priority list
(itself following Q4 of the WR50 external audit verdict). This session has
working SSH access (unlike the concurrent session that wrote that doc,
whose remote commands returned exit 1 — likely a restricted account).

## 1. Dashboard bind/auth + public ports — STILL OPEN (unchanged, not fixed here)

`0.0.0.0:5001`, `User=`/`Group=` empty (runs as root), no
`DASHBOARD_SECURITY_ENABLED` env var on the live unit. Matches the
2026-09-02 audit finding exactly. The hardened draft exists but was
deliberately NOT deployed earlier this session (2026-09-15, see
`_workspace/52_...md`) because an identical change previously broke live
Android app connectivity (commit `c664f3d` → reverted by `fbcd709`). Needs
its own separately-approved deployment decision, not done here.

Port `8080` (the stray public `http.server`): confirmed still closed
(killed earlier this session, `_workspace/51_...md`).

## 2. Non-root systemd + sandboxing — STILL OPEN (unchanged)

Same as #1 — the live unit has none of the hardening (`DynamicUser`,
`ProtectSystem=strict`, etc.). Bundled with #1's deployment decision.

## 3. Disk / log / SQLite capacity — CRITICAL FOUND AND FIXED

**Found**: `/` at **100% full, 0 bytes available** (worse than the
2026-09-02 audit's 96% reading). `/var/log/syslog` was 21GB.
`local_learning_storage/shadow_excursion.sqlite` is a newly-noticed 8.95GB
file (not touched — matches the "never copy/hash/delete SQLite" boundary,
flagged for awareness only).

**Root cause found**: `logrotate.service` was failing with `error creating
stub state file /var/lib/logrotate/status: No such file or directory` — the
directory `/var/lib/logrotate/` didn't exist, so logrotate could never run,
so syslog grew unbounded. This is a stock-Ubuntu-level issue, unrelated to
any of this project's own code/config.

**Fixed**:
1. `truncate -s 0 /var/log/syslog` — immediate relief, 100%→44% used, 21GB
   freed. Safe/standard practice (rsyslog keeps its open file handle;
   journald independently retains ~95MB of the same history).
2. `mkdir -p /var/lib/logrotate` then `systemctl start logrotate.service` —
   fixed the actual root cause. Verified: service now completes
   successfully (`inactive`, not `failed`); `logrotate.service` no longer
   appears in `systemctl --failed`. Real rotation should now run on
   schedule going forward, preventing recurrence.

Verified no disruption: `cryptomaster.service`, `cryptomaster-dashboard.service`,
and `rsyslog` all confirmed `active` before and after.

**Still open, not chased further this session** (`systemctl --failed`
after the fix): `apt-daily-upgrade.service`, `apt-daily.service`,
`daily-log-fix-prompt-bot.service` (project-named, worth a look in a future
session), `man-db.service`. None currently threaten disk capacity the way
the logrotate gap did.

## 4. Host SHA vs. release artifact — VERIFIED, consistent, no new drift

Host `/opt/cryptomaster` HEAD: `f3967fe8701e683347d34fe6accd511e055e1414`
(and `reports/deployed_bot_sha` agrees) — this is exactly the commit
deployed in cycle 204 (dashboard timestamp + EHM window-truncation fix,
2026-09-02). Everything on `origin/main` since then (WR50 audit docs, the
security-kill commit, the first-ever `release_gate.py` commit, etc.) is
correctly **not** deployed — none of it was meant to be; it's
documentation/process work or lives on the separate `wr50/` branch. This
is good discipline holding, not new drift. Host tree still shows ~25 dirty
lines (matches the known "host repo is dirty" finding, unchanged,
not remediated here).

## 5. Rollback / staged deployment — VERIFIED adequate, not re-tested live

`hetzner-deploy-apply.yml`'s existing gate structure already has this
(read earlier this session): PLAN before DEPLOY, staging compile/test of
incoming code before any live switch, zero-open-position gate, rich READY
convergence check post-switch, and automatic rollback-to-previous-SHA on
any post-switch failure. Not exercised live this session (no deploy was
performed) — noted as already-adequate tooling, not a new gap.

## Counts

```text
REAL orders                    = 0
deployments / restarts of cryptomaster.service or cryptomaster-dashboard.service = 0
production trading data writes = 0
SQLite/WAL/SHM files touched   = 0
systemd unit files changed     = 0
Files changed on host          = 1 (/var/log/syslog, truncated -- a log, not app data)
Directories created on host    = 1 (/var/lib/logrotate, stock-Ubuntu path)
Services restarted             = 1 (logrotate.service, a stock oneshot unit -- not this project's own units)
```

## Next step

Items 1-2 (dashboard auth/bind/sandboxing) need an explicit, separately-scoped
deployment decision given the known Android-connectivity regression risk —
this is the one item still requiring a human/operator call, not further
read-only investigation. Items 3-5 are now either fixed or verified
adequate.
