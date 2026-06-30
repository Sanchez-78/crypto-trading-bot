# CYCLE 52 Autonomous Monitoring Plan (30 minutes)

## Timeline
- **T+0 min**: Deployment verification starts (deploy-verifier agent)
- **T+5 min**: All validators report (learning, quota, safety, tests, contract)
- **T+10 min**: Orchestrator summary (APPROVED/REJECT)
- **T+30 min**: Final metrics collection and goal assessment

## Metrics to Track (every 5 minutes)

### From journalctl
```bash
journalctl -u cryptomaster_trading_bot -n 50 --no-pager | grep -E "CYCLE|closed_today|WR|PF|TP_LEARNING"
```

Track:
- Closed trades count
- Win rate (WR %)
- Profit factor (PF)
- [TP_LEARNING_ENABLED] event (should fire at 500 closes)
- [TP_LEARNING_ADAPT] events (should fire every 50 closes after 500-close warmup)
- Entry quality gate status (should_adapt_tp() blocks bad cycles)
- Cost floor enforcement (TP never goes below 0.0023 = 23bps)

### From dashboard API
```bash
curl -s http://localhost:5001/api/dashboard/metrics | jq '.win_rate, .profit_factor, .total_trades'
```

Track:
- WR > 50% (goal threshold)
- P&L > 0% (goal threshold)
- PF > 1.05 (healthy expectancy)
- No regression from Cycle 51 baseline

## Success Criteria

### GOAL REACHED (monitoring stops)
- WR > 50% AND P&L > 0%
- PF > 1.05 (consistent edge)
- Learning fires every 50 closes (TP_LEARNING_ADAPT logs)
- No crashes or errors in 30 min

### CAUTION (continue monitoring, no changes)
- WR 45-50% (marginal, let learning converge)
- PF 0.9-1.05 (breakeven territory)
- Learning active but still ramping (< 500 closes)
- All validators PASS (no code issues)

### FAIL (trigger auto-fix)
- WR < 45% (regression, possible blocker)
- PF < 0.90 (significant edge loss)
- New errors in logs (code issue)
- Any validator REJECT (safety/quota/learning issue)
- Service crash

## Auto-Fix Procedure (on FAIL)
1. Collect forensic logs (last 500 journalctl lines)
2. Run evidence-based-patch-orchestrator with fresh forensics
3. Identify blocker (learning gate? cost floor? warmup? entry quality?)
4. Patch and re-deploy
5. Return to monitoring (max 3 cycles)

## Expected Behavior

### Early Phase (0-10 min)
- Learning system initializes
- [TP_LEARNING_ENABLED] fires if trading already > 500 closes
- First [TP_LEARNING_ADAPT] event fires on next 50-close boundary

### Mid Phase (10-20 min)
- TP targets adapt based on WR:
  - If WR < 45%: TP tightens (max(TP - 0.01, 0.0023))
  - If WR > 55%: TP tightens (max(TP - 0.01, 0.0023))
  - Cost floor prevents TP < 23bps
- Entry quality gate blocks adaptation if > 25% TIMEOUT exits

### Late Phase (20-30 min)
- WR converges to new equilibrium
- PF stabilizes
- Learning reaches terminal state (WR stable, no more adaptation)

## Logging Focus
- [TP_LEARNING_ADAPT] → TP changes (watch direction: should tighten, not widen)
- [TP_LEARNING_ENABLED] → Learning activation (should be at 500 closes, not 100)
- should_adapt_tp() behavior → Entry quality gate working
- COST_FLOOR_PERCENT enforcement → TP never < 0.0023

