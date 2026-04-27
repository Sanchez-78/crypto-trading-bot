# CryptoMaster V10.13u+18g — Live Validation Summary

## Status

✅ **V10.13u+18g is deployed and working in production.**

Confirmed runtime:

```text
commit=4847aa1
branch=main
version=V10.13u+1
host=ubuntu-4gb-nbg1-1
```

## Validation Evidence

The rejection-path diagnostic fallback is now emitting correctly:

```text
[ECON_BAD_DIAG_HEARTBEAT] source=rde_reject pf=0.739 econ_status=BAD pf_source=lm_economic_health pf_fallback=false ...
[ECON_BAD_NEAR_MISS_SUMMARY] pf=0.739 econ_status=BAD pf_source=lm_economic_health pf_fallback=false ...
```

This confirms:

- `source=rde_reject` → V10.13u+18g rejection-path emission works.
- `pf=0.739` → diagnostics now match canonical economic health / dashboard PF.
- `econ_status=BAD` → ECON BAD state is correctly propagated.
- `pf_source=lm_economic_health` → canonical source is used.
- `pf_fallback=false` → no fallback bug remains.
- `total`, `neg_ev`, `weak_ev` counters are accumulating correctly after restart.
- No Traceback shown in provided validation output.

## Current Diagnostic Reading

Latest best near-miss:

```text
best_symbol=XRPUSDT
best_ev=0.0370
best_score=0.183
best_p=0.824
best_coh=0.741
best_af=0.750
probe_ready=False
probe_block=below_probe_ev
```

Interpretation:

The best candidate is close but still below the recovery probe floor:

```text
best_ev=0.0370 < probe_min_ev=0.0380
```

Other quality fields are acceptable:

```text
score=0.183 >= 0.18
p=0.824 >= 0.52
coh=0.741 >= 0.55
af=0.750 >= 0.70
```

So the recovery probe is correctly blocked only by EV, not by a wiring/runtime bug.

## Decision

✅ Do not patch now.

The system is behaving as designed:

- Weak entries are blocked.
- Negative EV is blocked.
- Diagnostics are visible.
- PF source is canonical.
- Probe is not firing because the candidate is below the configured EV floor, not because diagnostics or runtime wiring is broken.

## Monitor Next

Use:

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager \
  | grep -E "ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|ECON_BAD_RECOVERY_PROBE|RUNTIME_VERSION|Traceback"
```

Watch for:

```text
probe_ready=True
[ECON_BAD_RECOVERY_PROBE]
```

Patch only if one of these appears:

- `pf_fallback=true`
- `Traceback`
- weak `decision=TAKE ev≈0.0300`
- `probe_ready=True` but no probe opens repeatedly
- no closes for 12h+ and best near-miss stays consistently around `ev=0.0370–0.0379`

## Optional Future V10.13u+19

Only if the near-miss pattern persists for several hours:

- Add a shadow counter for candidates with `0.037 <= ev < 0.038`.
- Do not lower live probe threshold immediately.
- First collect frequency + outcomes/market context.
- If proven safe, consider a very narrow `probe_near_floor` mode with extra constraints.
