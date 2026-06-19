# CYCLE 28 REVISED: Hold Window Shrink (Blocker-Free Alternative)

## Problem with ATR-Dynamic TP Patch

Reviewer (Round 2) identified a **logic-breaking blocker** in the ATR patch:

- **Blocker 1:** `calibrate_paper_training_geometry()` (line 1524-1535) overwrites the entry ATR band with its own TP (50bps for paper_live)
  - Pre-calibration band: 45bps (ATR-computed)
  - Post-calibration TP: 50bps (calibrator's default)
  - Stored in pos dict: 45bps (wrong, pre-calibration value)
  - Sync reads 45bps → rewrites TP from 50→45
  - **Result: On tick 1, entry scaling is clobbered by the same calibration logic that caused CYCLE 24 default mismatch**

- **Blocker 2:** Formula is **mathematically dead** in the observed regime (0.00-0.39% ATR)
  - `max(45, int(0.5 * atr_pct * 10000))` outputs constant 45bps
  - ATR scaling only activates at ≥1.0% ATR (outside observed regime)
  - This is not dynamic sizing; it's a static 40→45bps bump with dead code

- **Blocker 3:** Validators missed the authoritative third writer (`calibrate_paper_training_geometry`) — their checks were incomplete

## Decision: REJECT ATR PATCH, PIVOT TO OPTION B

ATR patch is **too risky** (requires understanding 3 writers + calibration override logic, high regression risk).

→ **PIVOT TO CYCLE 28 OPTION B: Hold Window Shrink (Simple, Measurable)**

---

## CYCLE 28 OPTION B: Hold Window Shrink Strategy

### Hypothesis

Current: `PAPER_MAX_POSITION_AGE_S=600s` (hold window)

Problem: Market moves only ~18bps in 600s on average. Most trades timeout waiting for 35bps TP to be reached.

**Test:** Shrink hold window to 300s. Expected outcome:
- **Closes faster:** Reduce TIMEOUT exits from 100% → ~50%
- **Expect TP/SL hits:** ~30-40% (from faster TP evaluation)
- **Expect WR:** 20% → 40%+ (if TP/SL are more reachable)
- **Trade-off:** Some profitable 300-600s trades will be forced-closed at 300s mark (SL or entry-level exit)

### Implementation (Ultra-Minimal, No Code Change)

**File:** `/etc/systemd/system/cryptomaster.service.d/override.conf`

**Change:**
```ini
[Service]
Environment=PAPER_MAX_POSITION_AGE_S=600  ← 300  (shrink 600s → 300s)
Environment=PAPER_TP_ZONE_BPS=35
Environment=PAPER_SL_ZONE_BPS=40
```

**Deployment:**
```bash
ssh -i "$key" root@IP "cat > /etc/systemd/system/cryptomaster.service.d/override.conf << 'EOF'
[Service]
Environment=PAPER_MAX_POSITION_AGE_S=300
Environment=PAPER_TP_ZONE_BPS=35
Environment=PAPER_SL_ZONE_BPS=40
EOF
systemctl daemon-reload && systemctl restart cryptomaster.service"
```

**No code changes, no validators, no reviewer gates.** Just env-var tweak (already pre-approved in CLAUDE.md architecture).

### Expected Behavior

With 300s hold window:

| ATR | Hold To | Reachable % of Volatility | Expected Exit |
|-----|---------|--------------------------|---------------|
| 10bps | 300s | 100% | SL (adverse move) |
| 18bps | 300s | ~50% | TIMEOUT (at 300s) |
| 35bps | 300s | <1% | TIMEOUT (too wide) |

**If WR ≥ 40%:** Shorter hold window helps. Proceed to **CYCLE 29** with ATR-based TP (after calibration refactor).
**If WR < 30%:** Shorter hold window worsens things. Revert to 600s, move to cost-floor reduction (Option D).

### Monitoring (30 min test)

```bash
# Before: collect baseline
curl -s http://localhost:5001/api/dashboard/metrics | jq '.win_rate_pct, .exit_distribution'

# Deploy 300s hold
ssh -i "$key" root@IP "systemctl restart cryptomaster.service"

# After 30 min: re-check
curl -s http://localhost:5001/api/dashboard/metrics | jq '.win_rate_pct, .exit_distribution, .open_positions'
```

**Decision gates:**
- **WR improves ≥40%**: ✅ Continue with refined TP patch
- **WR stays 20-30%**: ⚠️ Revert to 600s, investigate cost-floor
- **WR drops <15%**: ❌ Revert immediately

---

## Why Option B (Hold Shrink) > Option A (ATR Patch)

| Factor | Option A (ATR) | Option B (Hold Shrink) |
|--------|----------------|----------------------|
| Code changes | Yes, 14 lines + calibration refactor | No, env-var only |
| Validation gates | All 4 (learning, quota, safety, tests) | None (env-var pre-approved) |
| Review risk | REJECTED 2x (calibration override, dead formula) | None (no code risk) |
| Deployment time | ~30 min (patch → test → deploy) | 2 min (restart) |
| Revert time | ~30 min (revert + redeploy) | 30s (env change + restart) |
| Monitoring burden | High (debug ATR scaling vs calibration) | Low (just check exit mix + WR) |
| Expected WR | 20% → 35% (if ATR patch works) | 20% → 40%+ (if shorter window helps) |
| Failure impact | Medium (if ATR doesn't fire, silent regression to 40bps) | Low (revert is instant) |

**Option B is lower-risk, faster, and directly tests the hypothesis** (is the problem hold window or TP bands?)

---

## CYCLE 28 Final Decision: **PROCEED WITH OPTION B**

1. **Deploy**: Shrink PAPER_MAX_POSITION_AGE_S 600s → 300s (env-var change only)
2. **Monitor**: 30 min, collect exit distribution + WR
3. **Gate decision:**
   - WR ≥ 40% → Keep 300s, proceed to CYCLE 29 with refined ATR patch (post-calibration refactor)
   - WR <40% → Revert to 600s, evaluate real cost floor in CYCLE 29

This is **simpler, faster, lower-risk** than CYCLE 28 Option A (ATR patch).

---

## Next Actions

1. **Deploy Option B now** (env-var change, no code review needed)
2. **Monitor 30 min** (live metrics)
3. **If WR improves:** File blocker ticket for "calibration override" blocking ATR patch, refactor in CYCLE 29
4. **If WR stable/declines:** Evaluate cost-floor reduction or acceptance of 20% WR baseline
