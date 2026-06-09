# P0.3F Deployment Notes
**Date:** 2026-06-09  
**Status:** PENDING (waiting for open positions to close)

---

## Deployment Approval Checklist

### Pre-Deployment Verification
- ✅ Git HEAD: 25665d3a9b39f7f86dbe1f1b1b67fcc95b9112a7
- ✅ Unit tests pass: 23/23 (P0.3A)
- ✅ Integration tests pass: 11/11 (P0.3E)
- ✅ REAL trading disabled: REAL_ORDERS_ALLOWED=false, PAPER_ONLY_MODE=true
- 🟡 Open positions: 25 (closing via timeout cycle...)

### Snapshot
- Location: `forensic_snapshots/p0_3f_20260609_101848/`
- Contents:
  - `git_head.txt` - commit hash
  - `git_status.txt` - working tree status
  - `service_unit.txt` - systemd unit file
  - `service_env.txt` - environment variables
  - `cache.sqlite` - learning database
  - `paper_open_positions.json` - positions state before close

---

## Deployment Goals

### Expected Runtime State After Restart
```
PAPER_EVIDENCE_COLLECTION: ON
  - ETHUSDT + BULL_TREND only
  - strict_ev=false
  - readiness_eligible=false
  - learning_source=paper_evidence_collection

STRICT_EV: OFF
  - No segments eligible (insufficient evidence)
  - All entries routed to evidence collection

LEARNING: ON
  - Closed trades logged to cache.sqlite
  - Metadata persisted: strict_ev, readiness_eligible, learning_source, segment_key, p0_gate_reason

REAL: OFF
  - REAL_ORDERS_ALLOWED=false
  - No order placement paths active
```

### Expected Log Output
```
[P0_SEGMENT_GATE] ... strict_ev_allowed=false reason=insufficient_evidence ...
[P0_EVIDENCE_COLLECTION_ADMIT] ... symbol=ETHUSDT regime=BULL_TREND ...
[P0_EVIDENCE_COLLECTION_ENTRY] ... strict_ev=false readiness_eligible=false ...
[PAPER_EXIT] ... symbol=ETHUSDT pnl_usd=±... ...
```

### Prohibited Log Output
```
❌ [PAPER_ENTRY] BTCUSDT (should be blocked)
❌ [PAPER_ENTRY] SOLUSDT (should be blocked)
❌ [PAPER_ENTRY] BEAR_TREND (should be blocked)
❌ strict_ev=true (no eligible segments yet)
❌ readiness_eligible=true (evidence collection only)
❌ REAL order attempt (disabled)
❌ Fixed RR approval (P0 gate mandatory)
```

---

## Post-Deployment Validation (30 min monitoring)

After service restart:

1. **Check logs for P0 gate decisions**
   ```bash
   journalctl -u cryptomaster.service --since "30 minutes ago" --no-pager \
   | grep -E "P0_SEGMENT_GATE|P0_EVIDENCE|PAPER_ENTRY|PAPER_EXIT"
   ```

2. **Verify position metadata**
   ```python
   import json
   with open("data/paper_open_positions.json") as f:
       for tid, pos in json.load(f).items():
           assert pos["strict_ev"] is False
           assert pos["readiness_eligible"] is False
           assert pos["learning_source"] == "paper_evidence_collection"
   ```

3. **Check no REAL order paths triggered**
   ```bash
   journalctl -u cryptomaster.service --since "30 minutes ago" \
   | grep -iE "REAL|ORDER|LIVE" | head -20
   ```

4. **Verify ETHUSDT BULL_TREND entries only**
   ```bash
   journalctl -u cryptomaster.service --since "30 minutes ago" \
   | grep "P0_EVIDENCE_COLLECTION_ADMIT" | grep -v ETHUSDT
   # Should return 0 matches
   ```

---

## Rollback Procedure

If any validation fails:

1. **Stop service immediately**
   ```bash
   sudo systemctl stop cryptomaster.service
   ```

2. **Restore snapshot**
   ```bash
   cp forensic_snapshots/p0_3f_20260609_101848/git_head.txt .deploy.head
   git status  # Verify clean state
   ```

3. **Investigate logs**
   ```bash
   journalctl -u cryptomaster.service -n 500 > /tmp/deploy_failure.log
   ```

4. **Report findings** to development team with:
   - `/tmp/deploy_failure.log`
   - Snapshot location
   - Specific validation that failed

---

## Success Criteria

Deployment is **SUCCESSFUL** when:
- ✅ Service running without errors
- ✅ All new entries have P0 metadata (strict_ev, readiness_eligible, learning_source)
- ✅ Only ETHUSDT + BULL_TREND routed to evidence collection
- ✅ BTCUSDT, SOLUSDT, BEAR_TREND blocked (no entries)
- ✅ Zero REAL order attempts
- ✅ Learning system active ([PAPER_EXIT] logs appearing)
- ✅ 30+ min monitoring shows consistent behavior

---

## Approved By
- **Code Review:** ✅ (P0.3A-E complete, 34 tests pass)
- **Safety Check:** ✅ (REAL disabled, metadata required)
- **Deployment Gate:** ⏳ (Waiting for open positions to close)

---

## Timeline
- **Pre-deploy:** Positions closing via timeout cycle (est. 10 min)
- **Deploy:** Push latest code to Hetzner (auto-via GitHub Actions)
- **Validation:** 30 min log monitoring
- **Success:** Reports clear, ready for Phase 4 (segment validation)
