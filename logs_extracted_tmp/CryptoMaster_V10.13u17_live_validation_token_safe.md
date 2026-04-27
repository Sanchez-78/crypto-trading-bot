# CryptoMaster V10.13u+17 Live Validation — Token-Safe Notes

## Live log verdict

V10.13u+17 appears to be working as intended.

Observed:
- No weak `decision=TAKE ev=0.0300 p=0.5000` after guard deployment.
- Forced signals are generated, but unsafe forced signals are rejected.
- `REJECT_NEGATIVE_EV` is correctly blocking EV-only violations.
- `ECON_BAD_ENTRY` counter exists and is active.
- Positions = 0, exposure = 0, no close-lock storm visible.
- PF remains bad at `0.74`, but bot is no longer taking weak churn trades.

## Important interpretation

Recovery probe is NOT expected to fire on these shown signals because they fail hard safety floors:

Example:
```text
FORCED_EXPLORE SOL/ETH
EV=-0.050 raw → coherence adjusted around -0.034
p=0.50
af=0.52
score≈0.115–0.137
decision=REJECT_NEGATIVE_EV
```

This is correct. V10.13u+17 recovery probe must never override:
- negative EV
- `af < 0.70`
- `p < 0.52`
- `coh < 0.55`
- `score < 0.18`
- LOSS_CLUSTER / TOXIC / SPREAD / NEGATIVE_EV / FAST_FAIL

So the absence of `[ECON_BAD_RECOVERY_PROBE]` is not a bug yet. The bot is seeing candidates, but they are too weak or unsafe.

## Current state from logs

```text
PF: 0.74 BAD
Health: 0.049 BAD
Positions: 0
Exposure: 0
Last trade: ~9h ago
Scratch: 323 trades, net -0.00060878
Stagnation: 73 trades, net -0.00025955
ECON_BAD_ENTRY: 5 in current cycle snapshot
FORCED_EXPLORE_GATE: 15
NEGATIVE_EV_REJECTION: 10
LOSS_CLUSTER: 7
```

Main issue is not close-lock anymore. Main issue is poor signal quality / calibration / economic regime.

## Do NOT patch yet unless one of these happens

Do not loosen V10.13u+17 now. Wait longer or collect targeted logs.

Patch only if:
1. No `[ECON_BAD_RECOVERY_PROBE]` after 2–3 hours despite marginal positive EV candidates.
2. `ECON_BAD_ENTRY` grows rapidly but all candidates are close to thresholds.
3. PF remains frozen and no closes happen for >12h.
4. Recovery probes fire but lose repeatedly.
5. Weak `decision=TAKE ev≈0.03 p≈0.50` appears again.

## Validation commands

```bash
sudo journalctl -u cryptomaster -n 5000 --no-pager | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY|ECON_BAD_RECOVERY|REJECT_NEGATIVE_EV|decision=TAKE|FORCED|CLOSE_FORCE|Traceback|EXIT_INTEGRITY"
```

Focused recovery check:

```bash
sudo journalctl -u cryptomaster -n 10000 --no-pager | grep -E "ECON_BAD_RECOVERY_PROBE|ECON_BAD_RECOVERY_BLOCK|ECON_BAD_ENTRY|REJECT_NEGATIVE_EV"
```

Check if weak TAKE still leaks:

```bash
sudo journalctl -u cryptomaster -n 10000 --no-pager | grep "decision=TAKE" | grep -E "ev=0\.03|p=0\.500|af=0\.35|EV=-"
```

Expected result:
- empty output, or only strong TAKE/probe entries.

## Next patch only if needed: V10.13u+18

Purpose: do NOT loosen entry gates. Add adaptive recovery diagnostics and auto-disable safety.

### V10.13u+18 scope

1. Add `[ECON_BAD_RECOVERY_SUMMARY]` every 5–10 min:
```text
blocked_total
probe_allowed
probe_blocked_by_reason
last_trade_age
pf
net_pnl
positions
top_block_reasons
near_miss_count
```

2. Add near-miss tracking:
Track candidates blocked by ECON_BAD_ENTRY that nearly pass recovery floors:
```text
ev >= 0.038
score >= 0.18
p >= 0.52
coh >= 0.55
af >= 0.70
not negative EV
not forced weak
not forbidden tag
```

3. Add auto-disable if probes lose:
If last 2 recovery probes net negative OR PF worsens after probe:
```text
disable recovery probes for 6h
log [ECON_BAD_RECOVERY_DISABLED]
```

4. Add no-trade diagnostic:
If no trade for >12h:
```text
log [ECON_BAD_NO_TRADE_DIAG]
show whether no trades are caused by:
- negative EV
- af floor
- p floor
- coh floor
- score floor
- loss cluster
- spread/toxic
- cooldown
```

5. Do not change:
- PF formula
- EV-only principle
- V10.13u+15 exit guards
- V10.13u+16 entry gate thresholds
- V10.13u+17 probe thresholds
- close-lock logic
- Firebase quota behavior

## Recommended action now

Wait 1–2 more hours and monitor:
```text
ECON_BAD_RECOVERY_PROBE
ECON_BAD_RECOVERY_BLOCK
ECON_BAD_ENTRY
REJECT_NEGATIVE_EV
decision=TAKE
PF
SCRATCH_EXIT net
STAGNATION_EXIT net
```

Current logs show the guard is doing its job. No emergency patch is justified from this snapshot.
