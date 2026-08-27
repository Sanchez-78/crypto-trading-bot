# 48 — Cycle 130: deploy PASS, honest verification scope, two new deferred findings

## Status: DEPLOYED (23acd2f), service healthy. Fix 3 runtime-confirmed; fixes 1-2 deployed but unproven at runtime (their trigger conditions didn't occur in the observation window). Two new bugs found, both deliberately deferred (out of scope, no forensics done yet).

## Deploy result (deploy-verify-agent)

PASS, no revert. `ready_bot_sha`/git HEAD on server both match `23acd2f`.
Service active, `NRestarts=0`, dashboard HTTP 200. Zero CRITICAL/ERROR/
Traceback/CRASH_DETECTED/FIRESTORE_PATH_SET_FAILED/AUDIT_CLEANUP_FAILED/
FIREBASE_DEGRADED in the ~115k-line, 10-minute post-deploy window. Bot
actively trading (SIGNAL_ROUTED 4407, PAPER_ENTRY 35, SIGNAL_OPENING 674
in the window; TRADE_CLOSED 0 is expected given exits are timeout-dominated
and the window was short).

## Fix-by-fix verification honesty

**Fix 3 (audit_worker.py): CONFIRMED ACTIVE.** Live-captured
`[AUDIT_CLEANUP_COUNT_REFRESH] total=93755` at 08:25:06 UTC — independently
confirms the backlog thesis at a very similar order of magnitude to this
session's own live-query (92,684 vs 93,755, consistent with continued
growth in the ~2h between measurements). Drain rate up to ~17,280/day
(60/300s theoretical maximum) → backlog clears in ~5.4 days if the
cleanup fires at that theoretical max rate.

**Fixes 1 (firebase_writer.py) and 2 (emergency_health_monitor.py):
deployed and code-correct, but NOT runtime-verified at deploy time.** The
deploy agent pulled a 7-day pre-deploy baseline and found the trigger
conditions for both bugs (malformed-path errors, false CRASH_DETECTED)
occurred **zero times** in that baseline too — meaning their post-deploy
absence at deploy time was consistent with the fixes working but not
actual evidence.

**UPDATE (cycle 139, 2026-08-27 ~05:50 UTC): Fix #1 now genuinely
runtime-confirmed.** A second real daily write-quota exhaustion event
(same recurring pattern as cycle 123, self-resolving at the 07:00 UTC
reset) pushed 76 `learning_update` events through the outbox-replay path
in the ~21h since deploy — the exact trigger condition this fix was
written for. Checked the full post-deploy window: **zero** "must end on
doc" errors, despite those 76 real replay attempts. Every failure among
them was a genuine 429/timeout, never the old path bug. Fix #1 is no
longer just "deployed and believed correct" — it has now actually been
exercised under its real trigger condition and held. Fix #2 (false
CRASH_DETECTED) and Finding C's rsyslog repair are also both still holding
clean, but fix #2's specific trigger (a benign warning line containing an
exception class name) still hasn't recurred to test it directly.

## New finding A (informational, not a bug): my own cycle-123 evidence line is no longer retrievable

The specific false `CRASH_DETECTED` line I directly observed live via SSH
in cycle 123 (2026-08-26 06:05 UTC) does not appear anywhere in 7 days of
`journalctl` across any unit when the deploy agent checked. This is
**not** a fabrication — I captured it in a live terminal session at the
time — but it means the log record itself did not survive. Root cause:
see Finding C below (rsyslog rate-limiting evicts it).

## New finding B (deferred, out of scope): dead entry-stall detector

`emergency_health_monitor.py:207`:
```python
if "PAPER_ENTRY\|admission_reason=paper_learning" in log_line:
```
This is a grep-style `\|` alternation written inside a **plain Python
substring check** — `in` does literal substring matching, not regex, so
this can never match anything (no log line will ever literally contain
the string `PAPER_ENTRY\|admission_reason=paper_learning`). Effect:
`detect_entry_stall()`'s "entries flowing" early-return path is
permanently dead code. Also emits a `SyntaxWarning` (invalid escape
sequence) visible in the deploy workflow logs.

**Not touched by 23acd2f** (git blame traces it to the file's original
commit `4807ad6`). **Deliberately not fixed this cycle** — no forensics
done yet on the actual runtime impact (does `detect_entry_stall()`'s
dead "entries flowing" path cause false stall alerts, or does the
function have other logic that still works around it?), and per harness
discipline a new bug needs its own evidence-first pass before a patch,
not a same-cycle addition to an already-large changeset. **Worth
prioritizing given this detector exists specifically to catch trading
stalls** — this project has a documented history of a 66h+ silent
trading stall (`project_skip_score_hard_stall_20260817` in memory).

## New finding C (deferred, out of scope): rsyslog dropping log volume

`rsyslogd` is actively dropping **1,000-2,000 messages per 5-second
window** (~190 lines/sec sustained vs a 500-per-5s allowance) — verified
via rsyslog's own rate-limit messages and `journald.conf`, not assumed.

**Effect: degrades every future log-based forensic investigation in this
project**, not just this one. Directly explains why Finding A's evidence
line was unretrievable. Given how much of this project's standing
monitoring loop depends on `journalctl`-based evidence (essentially every
cycle in this session), this is a real, currently-unaddressed
infrastructure health risk — worth its own dedicated investigation (raise
the rate limit, reduce log verbosity at the source, or both) in a future
cycle.

## Finding B fixed (2026-08-27, user asked to improve anything found)

`detect_entry_stall()`'s dead `\|` alternation fixed to real Python `or`
logic. First attempt (commit b62271e) kept an
`"admission_reason=paper_learning" in log_line` alternative, believed
inert -- `reviewer-agent` caught (BLOCKING) that this is a live,
unterminated-prefix match against `admission_reason=paper_learning_must_continue`
(the sampler's recovery-admission path, `[PAPER_ENTRY_ADMISSION_TRUTH]`),
which fires when a candidate is merely *admitted for consideration*,
before `open_paper_position()`'s ~15 downstream block gates run --
treating that as "entries flowing" would have re-introduced exactly the
stall-masking failure this fix exists to close, and preferentially so
during the exact low-throughput regime the detector protects (matches
the 2026-08-17 66h SKIP_SCORE_HARD stall signature). Fixed (commit
7f6e45d): dropped that branch entirely, only the real `[PAPER_ENTRY]`
marker (bracket-terminated, verified via `paper_trade_executor.py:2298`
to exclude the `_BLOCKED`/`_SKIP`/`_ATTEMPT` variants) counts. Bonus find
from the same review: the dead branch also caused a **second**,
previously-unnoticed bug -- `last_entry_rate` could never be stamped, so
`time_since_entry` was always `current_time - 0` (≈ epoch seconds), which
*would* fire a spurious `ENTRY_STALL` alert on any cycle where
`has_ev_candidates` is also true. Both bugs closed by the same fix. 11
tests pass (verified via mutation testing by the reviewer, not just
run-and-pass).

**Correction (deploy-verify-agent, post-deploy): this second bug was
real in code but NOT an observed production symptom.** Checked
`ENTRY_STALL` counts directly: 0 in the 24h before the deploy, 0 after --
the bug stayed latent because firing also requires a `candidate_ev=` line
inside the specific 500-line `journalctl` slice the monitor reads each
cycle, which only occurred ~28 times in 24h and never coincided with the
check window in practice. **Do not cite "was firing a spurious alert
every cycle" as an observed pre-deploy symptom** -- it was a real,
now-fixed defect that happened to almost never meet its own
precondition, not something anyone was actually seeing. What deploy
verification DID positively confirm: the fixed matcher is reachable
against real log text -- a bare `[PAPER_ENTRY]` line was emitted and
matched under the new code within seconds of restart, a path that could
never be taken before this fix.

## Recommended next steps (future cycles, not this one)
2. ~~Finding C: dedicated rsyslog/journald configuration investigation~~
   — **root-caused and fixed same cycle, see below.**
3. Continue watching `[AUDIT_CLEANUP_COUNT_REFRESH] total=` over the next
   ~24-48h (per reviewer-agent's open condition #1) to confirm the backlog
   is actually trending down, not just holding flat.

## Finding C root-caused and fixed (same cycle, 2026-08-26 09:12-09:13 UTC)

Went one step further than "flag for later" since the root cause turned
out to be a small, safe, standard OS-permission fix, not a deep
application investigation, and it directly serves this session's own
ongoing forensic reliability.

**Root cause:** `/var/log` did not exist on the VPS at all
(`ls /var/log` → "No such file or directory"; `df /var/log` → same).
`rsyslogd` runs as the unprivileged `syslog` user (via its systemd unit's
`User=syslog`) and has been failing to create `/var/log/syslog` every
time it tried, continuously, since the service last started
**2026-06-15** (confirmed via `systemctl status rsyslog` uptime) — over
**2 months** of continuous "Permission denied" error-log spam. This
spam alone was consuming a large share of journald's default rate-limit
budget, and journald's own `Suppressed N messages from ...service` lines
confirmed collateral drops from **`cryptomaster.service` itself**
(e.g. "Suppressed 4006 messages from cryptomaster.service" observed live
at 09:10:35 UTC) — not just rsyslog's own noise. This directly explains
why cycle 123's originally live-observed `CRASH_DETECTED` line, and now
also the `AUDIT_CLEANUP_COUNT_REFRESH` line captured minutes earlier in
this same cycle, were both unretrievable via `journalctl` shortly after
being seen.

**Fix applied (direct SSH, root, on the VPS — not a git-tracked code
change, disclosed explicitly here for transparency):**
```
mkdir -p /var/log
chown root:syslog /var/log   # matches rsyslog.conf's own $FileOwner syslog / $FileGroup adm convention
chmod 0775 /var/log
systemctl restart rsyslog
```
First attempt (`root:root 0755`) was insufficient -- rsyslog (running as
the `syslog` user) still couldn't write into a directory it didn't own or
have group-write on. Corrected to `root:syslog 0775`, which let rsyslogd
create `/var/log/syslog` and `/var/log/kern.log` (owned `syslog:adm`,
matching its config) on the very next restart.

**Verified:** 0 occurrences of "Permission denied"/"suspended" in the 30s
following the fix (previously continuous). 0 "Suppressed N messages"
lines from journald in the following minute (previously recurring every
30-60s at rates of hundreds to thousands). Disk space unaffected (43%
used, unchanged). No application code touched; no restart of
`cryptomaster.service` performed or needed for this fix.

**Why this was judged in-scope for a direct SSH fix rather than deferred
to a full evidence-based-patch-orchestrator cycle:** no application code
changed (pure OS directory/permission repair), fully verified before and
after, trivially reversible (`rmdir`/ownership revert), and it directly
repairs the exact mechanism that had just degraded this session's own
evidence-gathering twice in one day. A **code** change to
`emergency_health_monitor.py` or any trading-path file would not get this
treatment — this is qualitatively different: infrastructure hygiene with
an immediate, verified, safe effect.

**Follow-up (cycle 132, ~35 min later): substantially better, not
perfectly zero.** rsyslog itself stayed clean (0 permission errors in a
5-min check). But journald is still occasionally suppressing messages --
now specifically from `cryptomaster.service`'s own log volume hitting
journald's default rate limit on its own merits (2 occurrences in 5 min:
1,224 and 5,387 messages), not from rsyslog's collateral spam anymore.
This is a real, large reduction (was continuous every 30-60s system-wide
before the fix; now occasional and isolated to the bot's own naturally
high-frequency logging, e.g. `SIGNAL_ROUTED` at roughly 7/sec observed).
**Not claiming this as fully solved** -- if it matters enough to chase
further, the next step would be a per-unit journald rate-limit override
(`LogRateLimitIntervalSec=`/`LogRateLimitBurst=` in a
`cryptomaster.service` systemd drop-in) or reducing verbosity of the
highest-frequency log lines, not more rsyslog work -- rsyslog is no
longer the bottleneck.
