# CryptoMaster V10.13u+19 — ECON BAD No-Trade Deadlock Near-Miss Probe

Token-safe incremental prompt for Claude Code / Codex. Goal: break 13h+ no-trade deadlock without weakening V10.13u+16/17 safety.

## Live evidence

Current production state:
- Runtime commit: `4847aa1`
- `pf=0.739`, `econ_status=BAD`, `pf_source=lm_economic_health`, `pf_fallback=false`
- No real trades/closes for ~13h
- Rejections continue: mostly `REJECT_NEGATIVE_EV` + `REJECT_ECON_BAD_ENTRY`
- Best near-miss repeatedly:
  - `best_symbol=XRPUSDT`
  - `best_ev=0.0370`
  - `best_score=0.183`
  - `best_p=0.824`
  - `best_coh=0.741`
  - `best_af=0.750`
  - `probe_ready=False`
  - `probe_block=below_probe_ev`

Interpretation:
- Diagnostics are now correct.
- The bot is not failing to log; it is safely over-blocking.
- Candidate quality is good except EV is just below the current recovery probe floor `0.038`.
- After 13h no trade, this qualifies as controlled no-trade deadlock.

## Objective

Add a narrow V10.13u+19 safety valve:

Allow **one tiny near-miss deadlock probe** only when:
1. ECON status is BAD.
2. No closed trade for >= 12h.
3. Recovery probe is blocked only by `below_probe_ev`.
4. Candidate EV is in a tight band: `0.0370 <= ev < 0.0380`.
5. All other quality metrics are strong.
6. No hard safety flags are present.

This must not loosen the main ECON BAD entry guard or existing forced-explore/negative-EV rules.

## Do not change

Do not modify:
- `canonical_metrics.py` PF formula.
- `lm_economic_health()` scoring semantics.
- V10.13u+16 ECON BAD entry gate thresholds.
- V10.13u+17 normal recovery probe thresholds.
- V10.13u+18 diagnostics, except adding V10.13u+19 fields/logs if needed.
- Close-lock / exit guards V10.13u+8..u+15.
- Firebase read/write behavior.
- PARTIAL_TP behavior.
- EV-only hard rule: negative or zero EV must never be probed.

## Add constants

In `src/services/realtime_decision_engine.py` near existing ECON BAD recovery constants:

```python
ECON_BAD_DEADLOCK_PROBE_ENABLED = True
ECON_BAD_DEADLOCK_MIN_IDLE_S = 12 * 3600
ECON_BAD_DEADLOCK_MIN_TOTAL_BLOCKS = 50
ECON_BAD_DEADLOCK_MIN_EV = 0.0370
ECON_BAD_DEADLOCK_MAX_EV = 0.0380
ECON_BAD_DEADLOCK_MIN_SCORE = 0.180
ECON_BAD_DEADLOCK_MIN_P = 0.700
ECON_BAD_DEADLOCK_MIN_COH = 0.700
ECON_BAD_DEADLOCK_MIN_AF = 0.740
ECON_BAD_DEADLOCK_SIZE_MULT = 0.08
ECON_BAD_DEADLOCK_COOLDOWN_S = 3 * 3600
ECON_BAD_DEADLOCK_MAX_OPEN = 1
ECON_BAD_DEADLOCK_MAX_PER_24H = 4
```

Optional env kill switch:
- If existing config/env pattern exists, support `ECON_BAD_DEADLOCK_PROBE_ENABLED=false`.
- If no config pattern exists, keep constant only. Do not add new dependency.

## Add helper

Add:

```python
def _econ_bad_deadlock_nearmiss_probe_allowed(signal: dict, ctx: dict | None = None) -> tuple[bool, str, dict]:
    """V10.13u+19: allow tiny probe after long no-trade ECON BAD deadlock.

    Observability + narrow execution valve.
    Never overrides negative EV, weak p/coh/af/score, toxic/spread/loss-cluster, close-lock, forced weak signals, open-position cap.
    Return: (allowed, reason, meta)
    """
```

Required checks, in this order:
1. Feature enabled.
2. ECON BAD using canonical resolver/snapshot from V10.13u+18f. If status not BAD → block `econ_not_bad`.
3. EV hard floor:
   - `ev <= 0` → block `negative_ev`
   - `ev < 0.0370` → block `below_deadlock_ev`
   - `ev >= 0.0380` → return block `use_normal_recovery_probe` or allow normal V10.13u+17 path first.
4. Strong metric floors:
   - `score >= 0.180`
   - `p >= 0.700`
   - `coh >= 0.700`
   - `af >= 0.740`
5. Forbidden reasons/tags:
   - `LOSS_CLUSTER`, `TOXIC`, `SPREAD`, `NEGATIVE_EV`, `FAST_FAIL`, `FORCED_EXPLORE_GATE`, `OFI_TOXIC`, `PAIR_BLOCK`
   - Match existing field names defensively: `reason`, `reasons`, `tags`, `block_reason`, `reject_reason`.
6. Forced signal:
   - If `signal.get("forced")` is true, block unless it also meets existing strict forced thresholds and is not from unsafe forced exploration.
   - Prefer blocking forced near-miss by default: reason `forced_deadlock_probe_disabled`.
7. Open position cap:
   - block if open positions >= 1, using existing ctx/executor state. Do not add Firebase reads.
8. No-trade idle:
   - Use existing in-memory/dashboard fields if available: `last_close_ts`, `last_trade_ts`, `last_completed_trade_ts`, `last_trade_age_s`.
   - If only text/dashboard exposes age, do not parse logs.
   - If no reliable idle source exists, derive from existing runtime metrics/state. If impossible, block `idle_unknown`.
   - Allow only if idle >= 12h.
9. Diagnostic evidence:
   - Use V10.13u+18 snapshot.
   - Require `total_econ_bad_blocks >= 50`.
   - Require `probe_block == "below_probe_ev"` OR best candidate matches this signal.
10. Cooldown:
   - Max one deadlock probe per 3h.
   - Max four per 24h.
   - Max one open deadlock probe.
11. If allowed:
   - add metadata:
     - `econ_bad_deadlock_probe=True`
     - `deadlock_probe_version="V10.13u+19"`
     - `size_mult=0.08`
     - `probe_reason="no_trade_nearmiss"`
     - `pf`, `econ_status`, `pf_source`, `idle_s`, `total_blocks`
   - return `(True, "deadlock_nearmiss_probe", meta)`.

## Integration

Integrate only in the existing V10.13u+17 recovery probe path.

When V10.13u+16 rejects `weak_ev` and V10.13u+17 recovery probe blocks only because EV is below `0.038`, call `_econ_bad_deadlock_nearmiss_probe_allowed()`.

If allowed:
- Continue to TAKE as probe.
- Apply `ECON_BAD_DEADLOCK_SIZE_MULT` after existing size multipliers, or attach metadata so executor applies it.
- Ensure final size cannot exceed 0.08x normal signal size.
- Log canonical decision as TAKE with probe metadata.
- Increment probe counters.

If blocked:
- Keep existing rejection behavior unchanged.
- Log throttled block reason.

## Logging

Add WARNING logs, throttled to 60s:

```text
[ECON_BAD_DEADLOCK_PROBE] symbol=... ev=... score=... p=... coh=... af=... pf=... idle_s=... total_blocks=... size_mult=0.08 reason=no_trade_nearmiss
[ECON_BAD_DEADLOCK_BLOCK] symbol=... reason=... ev=... score=... p=... coh=... af=... pf=... idle_s=... total_blocks=...
```

Add fields to diagnostic snapshot if cheap/in-memory:
- `deadlock_probe_allowed_last`
- `deadlock_probe_block`
- `deadlock_probe_count_24h`
- `last_deadlock_probe_ts`

No Firebase writes.

## Tests

Add V10.13u+19 tests:

1. Allows near-miss after 12h idle:
   - ECON BAD, pf 0.739
   - total blocks >= 50
   - ev=0.0370, score=0.183, p=0.824, coh=0.741, af=0.750
   - no open positions
   - expected allowed, size_mult=0.08

2. Blocks before 12h idle.

3. Blocks ev < 0.0370.

4. Blocks negative EV.

5. Blocks weak p/coh/af:
   - p < 0.70, coh < 0.70, af < 0.74 each must block.

6. Blocks forbidden tags:
   - LOSS_CLUSTER, TOXIC, SPREAD, FAST_FAIL.

7. Blocks forced exploration by default.

8. Enforces cooldown:
   - second probe within 3h blocked.

9. Enforces max per 24h.

10. Does not change V10.13u+16/17/18 tests.

## Validation commands

Run on server venv:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19 or v10_13u18 or v10_13u17 or v10_13u16" -v
git diff --check
git status --short
```

Commit:

```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19: controlled no-trade ECON BAD near-miss probe"
git push origin main
```

## Deployment validation

After deploy/restart:

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DEADLOCK|ECON_BAD_RECOVERY_PROBE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|Traceback"
```

Expected:
- Runtime commit is the new V10.13u+19 commit.
- Existing diagnostics continue:
  - `pf=0.739`
  - `econ_status=BAD`
  - `pf_source=lm_economic_health`
  - `pf_fallback=false`
- If near-miss repeats:
  - one `[ECON_BAD_DEADLOCK_PROBE]`
  - size multiplier `0.08`
  - no more than one open probe
- If not allowed:
  - `[ECON_BAD_DEADLOCK_BLOCK] reason=<specific>`
- No Traceback.

## Rollback / kill switch

If probe loses immediately or churn returns:
1. Set env/constant `ECON_BAD_DEADLOCK_PROBE_ENABLED=false`.
2. Restart service.
3. Or revert commit.

Do not lower the main EV gate below 0.045. Do not lower normal recovery probe below 0.038 globally.
