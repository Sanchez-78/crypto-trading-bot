# P1.1AO Deployment Fix — Server still on P1.1AM

## Diagnosis

Current server state:

```text
Git HEAD: b1375bc
Audit header: P1.1AK Quality Audit
PAPER_TRAIN_STARVATION_STATE: not present
PAPER_NEG_EV_PROBE_ACCEPTED: not present
Starvation/probe audit section: not present
```

Conclusion:

```text
P1.1AO is NOT deployed on production.
Server is still on b1375bc / P1.1AM.
```

Also this command was run incorrectly:

```bash
git merge-base --is-ancestor <P1_1AO_COMMIT> HEAD
```

`<P1_1AO_COMMIT>` is only a placeholder. In bash, angle brackets are interpreted as redirection, so bash tried to open a file named `P1_1AO_COMMIT`.

## Required fix

### 1. On your development machine, find the real P1.1AO commit

Run in the repo where P1.1AO was implemented:

```bash
cd C:/Projects/CryptoMaster_srv
git log --oneline -10
```

Find the commit message for P1.1AO. Example:

```text
abc1234 P1.1AO cold-start paper training probe
```

Then push it:

```bash
git status
git add .
git commit -m "P1.1AO cold-start paper training probe"
git push origin main
```

If it already exists locally, only run:

```bash
git push origin main
```

### 2. On Hetzner production server, deploy the real commit

Replace `abc1234` with the actual P1.1AO commit hash:

```bash
cd /opt/cryptomaster

git fetch origin
git pull --ff-only

git rev-parse --short HEAD
git merge-base --is-ancestor abc1234 HEAD && echo "OK P1.1AO deployed" || echo "BAD P1.1AO missing"

sudo systemctl restart cryptomaster
sleep 15

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

## Expected audit after correct P1.1AO deploy

The audit should include new P1.1AO counters/section, such as:

```text
PAPER_TRAIN_STARVATION_STATE
PAPER_TRAIN_STATE_MISMATCH
NEGATIVE_EV_REJECTS
PAPER_NEG_EV_PROBE_ACCEPTED
C_NEG_EV_PROBE
```

Good signs:

```text
PAPER_TRAIN_ENTRY >= 1
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY
PAPER_TRAIN_QUALITY_MISMATCH = 0
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

If negative-EV starvation continues, we want to see one of these:

```text
PAPER_NEG_EV_PROBE_ACCEPTED > 0
PAPER_TRAIN_ENTRY bucket=C_NEG_EV_PROBE
PAPER_EXIT training_bucket=C_NEG_EV_PROBE
LM_STATE_AFTER_UPDATE increments after probe exits
```

## Current production audit interpretation

Current audit is not a P1.1AO validation. It only proves the older P1.1AM/P1.1AK diagnostics still work:

```text
PAPER_TRAIN_ENTRY: 1
PAPER_TRAIN_QUALITY_ENTRY: 1
PAPER_EXIT: 0
LM total: 0
COST_EDGE_BYPASS_CANDIDATE: 14
COST_EDGE_BYPASS_ACCEPTED: 0
```

This is not enough for P1.1AN. The bot still needs P1.1AO deployed to recover cold-start sample flow.
