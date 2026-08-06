# Critical review: dashboard staleness finding

Forensic agent's report is unusually strong evidence for a live-ops finding:
competing hypotheses (WAL/read-consistency, reverse-proxy, broken write path)
were each tested directly and refuted with concrete commands/output, not
assumed away. Key facts, independently sane-checked against what I already
knew this session:

- `cryptomaster-dashboard.service` is a **separate systemd unit** from
  `cryptomaster.service` — consistent with CLAUDE.md's own dashboard section
  existing as a distinct topic, though CLAUDE.md's description of *how* it
  runs (`python3 -u src/services/dashboard_web.py` directly) is now shown to
  be **stale/inaccurate** — actual `ExecStart` is
  `/opt/dashboard_venv/bin/python3 -u /opt/cryptomaster/start_flask_dashboard.py`
  per `systemd/cryptomaster-dashboard.service:42`.
- Deploy workflows (`hetzner-deploy-apply.yml`, `deploy.yml`) restart only
  `cryptomaster` (the bot). Neither references `cryptomaster-dashboard` —
  grep-confirmed, not assumed. This is a real, structural gap: every future
  code deploy will leave the dashboard process running old code /
  accumulating staleness again unless this is fixed.
- The specific freeze timestamp (10:42:21Z) coinciding with a code deploy
  10:42:27Z is circumstantial (6s apart, same minute) but not proven causal
  by the agent — correctly flagged as an open question, not overclaimed.
- Two different `cryptomaster-dashboard.service` unit *files* exist in the
  repo (`deploy/cryptomaster-dashboard.service` using `simple_dashboard.py`,
  `systemd/cryptomaster-dashboard.service` using `start_flask_dashboard.py`)
  — confirmed the live server matches the `systemd/` one; the `deploy/` one
  is stale/misleading, matching this session's recurring "which file is
  actually live" pattern (execution_engine.py, learning_monitor_v2.py, the
  old parameter_tuner — this project has many of these).

## What this is NOT
Not a code bug in `dashboard_read_model.py` — the on-disk code, run fresh,
correctly reads live cache.sqlite (verified: fresh in-process run returned
22/51/27, matching the DB's actual current state at query time, not the
frozen 45/53/2). No patch needed to that file.

## Decision
1. Immediate: restart `cryptomaster-dashboard.service` now (read-only
   reporting service, no open-position/trading state at risk, matches the
   forensic agent's own diagnostic recommendation) to clear the current
   staleness.
2. Root-cause fix (the actual gap that will recur otherwise): add a
   dashboard-service restart step to `hetzner-deploy-apply.yml` so future
   bot deploys keep the dashboard in sync. Narrow, single-purpose addition.
3. Docs: correct CLAUDE.md's stale dashboard entrypoint description and
   flag/remove the stale `deploy/cryptomaster-dashboard.service` file so
   this doesn't mislead the next investigation the way it almost did here.
