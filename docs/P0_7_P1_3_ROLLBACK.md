# Rollback Instructions — P0.7–P1.0 + Live Wiring (§27.6)

Covers everything shipped under the Evidence-First Strategy Expansion v2
program: P0.7 (`c3083ab`), central contract/router (`d4d69ee`), P0.8
(`85ef6b2`), P0.9 (`b0dc132`), P1.0 module (`fd2baa1`), live wiring +
scope widening + exit wiring (`_workspace/33`/`35`/`36`, 2026-08-17/18).

## Fastest, lowest-risk rollback: flags only, no code revert

Every behavior this program added beyond pure-diagnostic modules is
gated by an environment flag that can be flipped without a deploy cycle:

```bash
# Stop the live pipeline from opening any new positions (existing open
# positions, if any, continue to be managed normally by whichever exit
# path they're already on):
# systemd/99-cryptomaster-managed-runtime.conf on the server:
#   remove or set: PAPER_P0_8_PLUS_LIVE_ENABLED=false
sudo systemctl daemon-reload
sudo systemctl restart cryptomaster

# Also stop the read-only shadow evaluator (rarely needed -- it cannot
# open a position, structurally, per its own bypass tests):
#   PAPER_P0_8_PLUS_SHADOW_ENABLED=false
```

This is reversible in seconds and requires no code change, no
redeploy, no schema migration. It is the recommended first response to
any anomaly involving this program's live behavior.

## Full code rollback (if flags alone are insufficient)

Revert order matters — later commits depend on earlier ones:

```bash
# 1. Live wiring, scope widening, exit wiring (2026-08-17/18) --
#    revert these FIRST, they depend on everything below.
git revert <exit-wiring-commit> <scope-widening-commit> <live-wiring-commit>

# 2. P1.0 module
git revert fd2baa1

# 3. P0.9
git revert b0dc132

# 4. P0.8
git revert 85ef6b2

# 5. Central signal contract + router
git revert d4d69ee

# 6. P0.7
git revert c3083ab
```

Each phase's own acceptance report (`docs/P0_7_ACCEPTANCE.md` ..
`docs/P1_0_ACCEPTANCE.md`) documents that phase's isolated revert safety
— all are additive at their own commit time (zero live-behavior change
until a LATER commit added a caller), so reverting from the top down is
safe; reverting from the bottom up (e.g. `c3083ab` while `85ef6b2` still
depends on `cost_model.py`) would break the build.

After any code revert: redeploy via the existing gated workflow
(`gh workflow run hetzner-deploy-apply.yml -f confirm=PLAN`, verify
`[DEPLOY_PLAN_OK]`, then `-f confirm=DEPLOY`) — never a raw `git push`
or manual server edit (see `_workspace/17_...md`'s history of exactly
this kind of untracked drift causing a multi-week production incident).

## Systemd overlay rollback

The overlay itself is tracked (`systemd/99-cryptomaster-managed-runtime.conf`).
To roll back a bad overlay change specifically:

```bash
git log --oneline systemd/99-cryptomaster-managed-runtime.conf
git show <good-commit>:systemd/99-cryptomaster-managed-runtime.conf > /tmp/good-overlay.conf
scp -i ~/.ssh/hetzner_root /tmp/good-overlay.conf root@78.47.2.198:/etc/systemd/system/cryptomaster.service.d/99-cryptomaster-managed-runtime.conf
ssh -i ~/.ssh/hetzner_root root@78.47.2.198 "systemctl daemon-reload && systemctl restart cryptomaster"
```

## Firestore schema compatibility

No new Firestore document schema was introduced by this program. New
position-dict fields added this session (`strategy_id`,
`dynamic_exit_initial_stop`, `_dyn_exit_trend_features`,
`_dyn_exit_atr_bps`, `_dyn_exit_features_ts`) are additive keys on the
existing in-memory/local-cache position dict, not a Firestore schema
change — no migration, no read-compatibility concern, no rollback step
needed beyond the code revert itself.

## Strategy flags (per-strategy disable without a full rollback)

Each strategy's `StrategyRegistration.enabled` flag (`strategy_registry.py`)
can disable one strategy without touching the pipeline or the others —
not currently exposed as an environment variable (a real gap against
document §20's suggested `ENABLE_TREND_COST_AWARE_V1`-style flags per
strategy; see `_workspace/37_document_compliance_gap_analysis.md`).
Until that gap is closed, disabling one specific strategy requires a
code change (`registration.enabled = False` in `ensure_registered()`) or
the blanket `PAPER_P0_8_PLUS_LIVE_ENABLED=false` flag above, which
affects all three.

## Verification after any rollback

```bash
curl http://localhost:5001/api/dashboard/metrics   # dashboard responsive
journalctl -u cryptomaster.service --since '2 min ago' | grep -E '\[STARTUP\]|Traceback'
```

Confirm `systemctl is-active cryptomaster.service` is `active` and no
tracebacks appear in the startup window.
