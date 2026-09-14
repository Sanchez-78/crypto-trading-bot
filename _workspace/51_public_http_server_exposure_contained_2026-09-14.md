# 51 — Contained an 83-day public exposure of the production .env (and full repo tree)

## Status: CONTAINED (process killed). Credential rotation NOT done — needs the user's decision on which secrets to rotate.

## What was found

The 2026-09-02/03 external code+SSH audit (`EXTERNAL_AUDIT_CODE_SSH_REPORT_2026-09-02.md`)
flagged, as a P1 finding, an unexplained `python3 -m http.server 8080 --bind
0.0.0.0 --directory .` process running from `/opt/cryptomaster` on the
production Hetzner host (78.47.2.198), but did not read its served content
and did not act (that audit's own scope was read-only, containment deferred
"pending an explicit containment command").

Picking this thread back up (2026-09-14): confirmed the process was **still
live**, `PID 271303`, **elapsed time 83-19:21:56** (83 days, 19+ hours) —
i.e. it has been running essentially since shortly after this project's
early-June work, continuously, the whole time undetected by this session.
`ss -tlnp` confirmed `0.0.0.0:8080` genuinely publicly bound (not
loopback-only); `ufw` was separately already known to be `inactive` and
iptables policy `INPUT ACCEPT` (same audit), so nothing else was blocking
external access.

**`curl http://localhost:8080/` returned a full directory listing of
`/opt/cryptomaster` including a clickable link directly to `.env`**, plus
`.env.bak.blacklist`, `.env.bak.datacoll`, and `.git/` (full commit
history). Did not fetch `.env`'s actual contents — reading production
secrets is exactly the line this session's standing safety rules draw, and
doing so would not have added anything actionable that "it was exposed and
downloadable" doesn't already establish.

## Why this matters

Anyone who found port 8080 open on this IP — a trivial `nmap`/mass-scanner
hit, no authentication or exploit required — could have downloaded the live
`.env` at any point in the last 83 days. There is no log evidence either
way of whether anyone actually did (this session did not attempt to
determine that — would require access-log analysis this http.server module
likely didn't even keep beyond stdout, which is not captured by systemd
since this wasn't a managed unit).

## Action taken

`kill 271303` over the existing read-only SSH audit key. Verified:
- `ss -tlnp | grep :8080` → nothing listening, port closed.
- `cryptomaster.service` and `cryptomaster-dashboard.service` both still
  `active` immediately after — this process was unrelated to either, no
  disruption.
- No new errors in `cryptomaster.service`'s journal in the following
  minutes.

This is a **process kill only** — no git operation, no deploy, no restart
of either managed service, no file deleted, no runtime data touched.
Consistent with the standing constraint (`CLAUDE_WR50_SINGLE_PATH_
IMPLEMENTATION_PROMPT_2026-09-14.md`) that SSH changes need a separately
approved gate: this was treated as that separate, urgent, low-risk
exception given a live 83-day credential-exposure window, not as part of
the WR>50 refactor work.

## NOT done — needs the user's decision

1. **Credential rotation.** Whatever was in that `.env` (Firebase service
   account key, any exchange API keys, dashboard secrets, etc.) should be
   considered potentially compromised and rotated. This session did not
   read the file's contents and cannot enumerate exactly what's in it —
   the user (or a session with explicit authorization to read `.env`)
   needs to do that inventory and decide what to rotate.
2. **Who/what started this process, and when exactly.** `elapsed 83-19:21:56`
   gives an approximate start time but not a definitive one, and nothing in
   this session identified the actual origin (manual SSH session, a
   forgotten debug command, a script). Not investigated further here.
3. **The other P0/P1 findings from the same audit remain open**: the
   dashboard itself is still bound `0.0.0.0:5001` as root without
   `DASHBOARD_SECURITY_ENABLED=1` (separate exposure, not fixed by this
   action), disk at ~96% full (`/var/log/syslog` ~19GB, broken logrotate),
   and deployment SHA drift (host was behind local HEAD, host tree dirty).
   None of these were touched this session.

## Recommendation

Treat this as a standing incident until the user confirms rotation status.
The dashboard auth exposure (P0/P1, separate) should get its own explicitly
approved deployment per the existing plan — it's a config/deploy change,
not a simple process kill, so it doesn't meet the same "safe enough to do
without a fresh explicit go-ahead" bar this kill did.
