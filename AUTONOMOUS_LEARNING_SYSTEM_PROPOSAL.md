# Autonomous Learning System for Self-Adjusting Bot Strategy

## Executive Summary

Transform the manual changelog/patch process into a **self-learning adaptive system** that:
1. **Records** every strategy change and result automatically
2. **Analyzes** patterns to identify what works/fails
3. **Learns** gate thresholds, position caps, exit strategies per market condition
4. **Suggests** next moves based on historical success rates
5. **Avoids** repeating failed strategies
6. **Adapts** autonomously without human intervention

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                  AUTONOMOUS LEARNING LOOP                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Monitor    │───>│   Analyze    │───>│   Recommend  │      │
│  │   Metrics    │    │   Patterns   │    │   Changes    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         ^                                         │             │
│         │                                         v             │
│         │                                  ┌──────────────┐     │
│         │                                  │   Learning   │     │
│         │                                  │   Database   │     │
│         │                                  │  (SQLite)    │     │
│         │                                  └──────────────┘     │
│         │                                         │             │
│         └─────────────────────────────────────────┘             │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Execute    │<───│   Validate   │<───│   Decision   │      │
│  │   Change     │    │   Safety     │    │   Engine     │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                                                       │
│         └──────────────────────────────────────────────────────┘
│                                                                 │
│  Every 5 minutes (monitoring cycle):                           │
│    1. Collect metrics (WR, P&L, TIMEOUT rate, etc)            │
│    2. Compare to learned patterns                             │
│    3. If threshold met → suggest change                       │
│    4. Validate against history (repeat prevention)            │
│    5. Execute with safety gates                               │
│    6. Record result in learning database                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component 1: Strategy Learning Database

### Schema

```sql
CREATE TABLE strategy_experiments (
  id INTEGER PRIMARY KEY,
  cycle_number INTEGER,
  timestamp DATETIME,
  
  -- What changed
  parameter TEXT,           -- 'entry_gate_pct', 'tp_zone_bps', 'position_cap', etc
  old_value REAL,
  new_value REAL,
  change_reason TEXT,       -- 'regression', 'plateau', 'volatility', 'optimization'
  
  -- Before metrics
  wr_before REAL,
  pnl_before REAL,
  timeout_exits_before INTEGER,
  trades_count_before INTEGER,
  
  -- After metrics (at next cycle)
  wr_after REAL,
  pnl_after REAL,
  timeout_exits_after INTEGER,
  trades_count_after INTEGER,
  
  -- Analysis
  impact_wr REAL,           -- wr_after - wr_before (delta)
  impact_timeouts REAL,     -- timeout rate change
  impact_volume REAL,       -- new trades per cycle
  success BOOLEAN,          -- TRUE if wr_after >= wr_before - 1.0% (tolerate small dip)
  outcome TEXT,             -- 'SUCCESS', 'MINOR_DEGRIGATION', 'FAILURE', 'CRITICAL'
  
  -- Learning
  repeat_count INTEGER,     -- How many times we've tried this exact change
  learned_threshold REAL,   -- Optimal value discovered for this parameter
  confidence REAL           -- 0-1, confidence in recommendation (based on success rate)
);

CREATE TABLE strategy_rules (
  id INTEGER PRIMARY KEY,
  parameter TEXT,           -- 'entry_gate_pct', etc
  
  -- Learned safe ranges
  min_value REAL,           -- Never go below (safety floor)
  max_value REAL,           -- Never go above (over-tight)
  optimal_value REAL,       -- Best performer from history
  
  -- Conditions
  market_condition TEXT,    -- 'high_volatility', 'trending', 'ranging', 'unknown'
  wr_range_min REAL,
  wr_range_max REAL,
  
  -- Effectiveness
  success_rate REAL,        -- % of times this value worked
  sample_count INTEGER,     -- How many times tested
  last_updated DATETIME
);

CREATE TABLE failed_strategies (
  id INTEGER PRIMARY KEY,
  parameter TEXT,
  value REAL,
  reason TEXT,              -- Why it failed: 'too_strict', 'too_loose', 'timeout_spike', etc
  failure_count INTEGER,    -- How many times we've seen this fail
  last_attempted DATETIME,
  
  -- Blacklist info
  blacklist_until DATETIME, -- Don't retry this until X time has passed
  confidence REAL           -- How sure are we it's bad? 1.0 = very sure
);
```

---

## Component 2: Autonomous Decision Engine

### Logic Flow

```python
class AutonomousLearningEngine:
    
    def should_change_strategy(self, current_metrics):
        """
        Decide if we need to change strategy based on:
        1. Current WR vs learned patterns
        2. Recent trend (improving/declining/stable)
        3. History of what worked in similar conditions
        4. Failure prevention (don't retry failed strategies)
        """
        
        # Check if we've been stuck
        wr_plateaued = self.is_plateau(cycles=5)  # No improvement for 5 cycles
        wr_declining = self.is_declining(cycles=3)  # WR dropping
        wr_critical = current_metrics['wr'] < 45  # Below safety buffer
        
        if wr_critical:
            # Emergency mode: use proven emergency strategies
            return self.recommend_emergency_fix()
        
        elif wr_declining and current_metrics['wr'] > 50:
            # Caution: small adjustment
            return self.recommend_gentle_tightening()
        
        elif wr_plateaued and current_metrics['wr'] >= 54:
            # Optimization: try learned good values
            return self.recommend_optimization()
        
        else:
            # Stable: no change needed
            return None
    
    def recommend_change(self, reason: str):
        """
        Suggest next parameter change based on history and current state
        """
        
        # Get historical successes for similar conditions
        similar_successful = self.db.query("""
            SELECT parameter, new_value, impact_wr, success_rate
            FROM strategy_experiments
            WHERE outcome = 'SUCCESS' 
            AND market_condition = ?
            ORDER BY impact_wr DESC
            LIMIT 5
        """, current_market_condition)
        
        # Get failed strategies to avoid
        known_failures = self.db.query("""
            SELECT parameter, value, reason
            FROM failed_strategies
            WHERE failure_count >= 2
            AND NOT blacklist_expired()
        """)
        
        # For each candidate change
        for param, old_value, new_value in candidates:
            
            # Check: have we tried this before?
            if self.was_recently_tried(param, old_value, new_value):
                continue  # Skip - we already know the result
            
            # Check: is this in blacklist?
            if self.is_in_failed_strategies(param, new_value):
                continue  # Skip - known to fail
            
            # Check: does it violate learned limits?
            if not self.within_safe_bounds(param, new_value):
                continue  # Skip - outside safe range
            
            # This is a good candidate!
            return {
                'parameter': param,
                'old_value': old_value,
                'new_value': new_value,
                'reason': reason,
                'confidence': self.calculate_confidence(param, new_value),
                'expected_impact': self.estimate_impact(param, new_value)
            }
        
        return None  # No good candidate found
    
    def execute_and_learn(self, change, metrics_before):
        """
        1. Execute the change
        2. Monitor results
        3. Record in learning database
        4. Update strategy rules
        5. Mark as success or failure
        """
        
        # Apply the change
        self.apply_parameter_change(change)
        
        # Wait for effect (1-2 cycles)
        time.sleep(300 * 2)  # 10 minutes
        
        # Get results
        metrics_after = self.collect_metrics()
        impact_wr = metrics_after['wr'] - metrics_before['wr']
        
        # Record experiment
        self.db.record_experiment({
            'parameter': change['parameter'],
            'old_value': change['old_value'],
            'new_value': change['new_value'],
            'wr_before': metrics_before['wr'],
            'wr_after': metrics_after['wr'],
            'impact_wr': impact_wr,
            'success': impact_wr > -1.0,  # Success if didn't drop >1%
            'timeout_impact': metrics_after['timeout_rate'] - metrics_before['timeout_rate']
        })
        
        # Update learned rules
        if impact_wr > 0.5:
            # Great success - update optimal value
            self.update_learned_threshold(change['parameter'], change['new_value'], confidence=0.9)
        
        elif impact_wr < -2.0:
            # Significant failure - add to blacklist
            self.add_to_failed_strategies(change['parameter'], change['new_value'], reason=reason)
        
        return impact_wr
```

---

## Component 3: History Validation (Repeat Prevention)

### Before Every Change

```python
def validate_against_history(self, proposed_change):
    """
    MANDATORY CHECK before executing any change
    Prevents repeating failed strategies
    """
    
    param = proposed_change['parameter']
    new_value = proposed_change['new_value']
    
    # Check 1: Have we tried this exact change recently?
    recent_identical = self.db.query("""
        SELECT wr_before, wr_after, outcome, timestamp
        FROM strategy_experiments
        WHERE parameter = ? AND new_value = ?
        ORDER BY timestamp DESC
        LIMIT 3
    """, param, new_value)
    
    if recent_identical:
        last_attempt = recent_identical[0]
        if last_attempt['outcome'] == 'FAILURE':
            # We tried this and it failed!
            days_since = (now() - last_attempt['timestamp']).days
            
            if days_since < 7:
                return {
                    'allowed': False,
                    'reason': f'Already tried {param}={new_value} on {last_attempt["timestamp"]}, resulted in {last_attempt["outcome"]}'
                }
    
    # Check 2: Is this in the failure blacklist?
    is_blacklisted = self.db.query("""
        SELECT reason, failure_count, blacklist_until
        FROM failed_strategies
        WHERE parameter = ? AND value = ?
    """, param, new_value)
    
    if is_blacklisted and is_blacklisted[0]['blacklist_until'] > now():
        return {
            'allowed': False,
            'reason': f'Strategy blacklisted until {is_blacklisted[0]["blacklist_until"]} (failed {is_blacklisted[0]["failure_count"]} times)'
        }
    
    # Check 3: Does it violate learned safe bounds?
    learned_bounds = self.get_learned_bounds(param)
    if new_value < learned_bounds['min'] or new_value > learned_bounds['max']:
        return {
            'allowed': False,
            'reason': f'{param} optimal range is {learned_bounds["min"]}-{learned_bounds["max"]}, proposed {new_value} is outside'
        }
    
    # All checks passed
    return {
        'allowed': True,
        'confidence': self.calculate_confidence_score(param, new_value),
        'expected_impact': self.estimate_impact(param, new_value)
    }
```

---

## Component 4: Learning Rules Engine

### Automatic Rule Updates

```python
def learn_from_experiment(self, experiment):
    """
    After each experiment, update the strategy rules
    """
    
    param = experiment['parameter']
    value = experiment['new_value']
    success = experiment['success']
    
    # Get or create rule
    rule = self.db.get_rule(param) or create_rule(param)
    
    # Update success rate
    new_sample_count = rule['sample_count'] + 1
    new_success_rate = (
        (rule['success_rate'] * rule['sample_count'] + (1 if success else 0))
        / new_sample_count
    )
    
    # Update learned optimal value
    if experiment['impact_wr'] > 0.5:  # Major improvement
        rule['optimal_value'] = value
        rule['confidence'] = min(1.0, rule['confidence'] + 0.1)
    
    elif experiment['impact_wr'] < -1.0:  # Major failure
        # Widen bounds to avoid this value
        if value < rule['optimal_value']:
            rule['min_value'] = value + 0.005  # Back off slightly
        else:
            rule['max_value'] = value - 0.005
    
    # Save updated rule
    self.db.update_rule(rule)
```

---

## Component 5: Safety Gates (Prevent Runaway)

### Immutable Safety Rules

```python
class SafetyGates:
    """
    Hard limits that NEVER get bypassed, even by learning system
    """
    
    # Entry quality gate bounds (learned from 6 patches)
    ENTRY_GATE_MIN = 0.0010  # 0.10% - below this = too loose
    ENTRY_GATE_MAX = 0.0100  # 1.00% - above this = no entries
    ENTRY_GATE_OPTIMAL = 0.0035  # 0.35% - proven sweet spot
    
    # Position cap (NEW - prevents accumulation)
    MAX_CONCURRENT_POSITIONS = 100
    RECOMMENDED_CAP = 50
    
    # TP/SL zone bounds
    TP_ZONE_MIN = 20  # bps
    TP_ZONE_MAX = 100  # bps
    SL_ZONE_MIN = 30  # bps
    SL_ZONE_MAX = 80  # bps
    
    # WR safety thresholds
    WR_CRITICAL = 40.0  # Auto-revert if below
    WR_CAUTION = 45.0   # Extra safety mode
    WR_OPTIMAL = 55.0   # Goal threshold
    
    # Change frequency limits
    MAX_CHANGES_PER_HOUR = 1
    MIN_CYCLES_BETWEEN_CHANGES = 5
    
    def validate_proposed_change(self, parameter, new_value):
        """All changes MUST pass these gates"""
        
        if parameter == 'entry_gate_pct':
            if new_value < self.ENTRY_GATE_MIN or new_value > self.ENTRY_GATE_MAX:
                return False, f"Entry gate {new_value} outside [{self.ENTRY_GATE_MIN}, {self.ENTRY_GATE_MAX}]"
        
        # ... other parameter validations
        
        return True, "APPROVED"
```

---

## Component 6: Learning Metrics Dashboard

### What the System Tracks Over Time

```
Cycle 1-50 Data:
┌──────────────┬────────┬────────┬────────┬────────┬────────┐
│ Cycle | Gate | WR     | TIMEOUT| Trades | Outcome│
├──────────────┼────────┼────────┼────────┼────────┼────────┤
│   1  | 0.30 | 47.96% |   -    |   -    | START  │
│   2  | 0.30 | 54.05% |   -    |   -    | GOOD   │
│   3  | 0.30 | 54.05% |   -    |   -    | STABLE │
│   4  | 0.40 | 49.47% |   -    |   -    | FAIL   │  ← too strict
│   5  | 0.40 | 49.47% |   -    |   -    | FAIL   │
│   6  | 0.35 | 54.65% |  ✓ 9   |   86   | SUCCESS│  ← sweet spot found
│  ... |      |        |        |        |        │
│  18  | 0.35 | 56.18% |  ✓ 9   |   -    | PEAK   │  ← got 56%!
│  19  | 0.35 | 52.25% |  ✗ 30  |  120   | DEGRADE│  ← position accumulation
│  23  | 0.50 | 44.12% |  ✗ 59  |  136   | CRIT   │  ← WR 44% (4 from revert)
│  24  | 0.60 | 54.65% |  ✓ 9   |   86   | RECOVERED│  ← emergency worked

LEARNED PATTERN:
  0.35% = OPTIMAL sweet spot (54-55% WR, 9 timeouts)
  0.40% = TOO STRICT (kills entries, WR drops)
  0.50% = ALLOWS BAD ENTRIES (position accumulation, timeout spike)
  0.60% = EMERGENCY ONLY (full circuit breaker, allows recovery)

BLOCKING RULE: Never use 0.50% unless WR < 40% (emergency)
RETRY RULE: 0.35% always recovers WR to 54-55% range
```

---

## Implementation Timeline

### Phase 1: Setup (Week 1)
- [ ] Create `strategy_learning.db` with schemas above
- [ ] Implement data recording (every cycle → log metrics + change)
- [ ] Build history validation checks
- [ ] Add safety gates enforcement

### Phase 2: Learning (Week 2-4)
- [ ] Run autonomous system for 30 cycles with manual oversight
- [ ] Accumulate experiment data (successes/failures)
- [ ] Build confidence in learned rules
- [ ] Refine blacklist/safe-zone logic

### Phase 3: Autonomous (Week 4+)
- [ ] Enable auto-suggestion (system recommends changes)
- [ ] Enable auto-execution (system applies changes after validation)
- [ ] Monitor for runaway behavior
- [ ] Adjust learning parameters based on performance

---

## Current Dataset (6 Patches)

The system already has data to learn from:

| Gate | WR Before | WR After | Impact | Outcome | Repeat Risk |
|------|-----------|----------|--------|---------|------------|
| 0.30 | 47.96 | 54.05 | +6.09 | ✅ SUCCESS | N/A (baseline) |
| 0.40 | 54.05 | 49.47 | -4.58 | ❌ FAIL | HIGH - avoid |
| 0.35 | 49.47 | 54.65 | +5.18 | ✅ SUCCESS | SAFE - repeat |
| 0.50 | 54.65 | 44.12 | -10.53 | ❌ CRITICAL | BLACKLIST |
| 0.35→0.50→0.60 | (emergency sequence) | ✅ RECOVERED | EMERGENCY PROTOCOL |

**Learned Rules from 6 experiments:**
- ✅ **0.35% = SAFE & OPTIMAL** (tested 2x, both successful)
- ❌ **0.40% = DO NOT USE** (caused -4.58% WR drop)
- ❌ **0.50% = EMERGENCY ONLY** (caused -10.53% drop, position accumulation)
- ✅ **0.60% = CRISIS RECOVERY** (worked to prevent auto-revert)

---

## Expected Benefits

1. **No more repeated mistakes** - Blacklist prevents retrying failed strategies
2. **Faster convergence** - System learns optimal values across market conditions
3. **Autonomous tuning** - No human needed to decide next change
4. **Explainable decisions** - Every change backed by experiment history
5. **Safer experiments** - Safety gates + history validation = no catastrophic failures
6. **Knowledge accumulation** - Each cycle teaches the system something

---

## Example: Next 10 Cycles with Learning System

```
Current: WR 54.65%, Gate 0.60% (conservative)

Cycle 25: Monitor (no change suggested - WR above 50%)
Cycle 26: Monitor
Cycle 27: Suggest gradual relaxation
  - History shows: 0.35% worked well with 54.65% WR
  - Proposed: 0.60% → 0.45% (gradual)
  - Validation: Not in blacklist, within safe bounds ✅
  - Execute and record result
  
Cycle 28: If WR improved → update optimal_value(0.45%) + confidence
         If WR declined → tighten back to 0.60%, blacklist 0.45%
         
Cycle 29-50: Continued learning in 0.35-0.50% range
           Eventually stabilizes at optimal gate for current market
           
Result: System converges on BEST gate value automatically
```

---

## Integration with Existing Bot

Replace manual patch decisions with:

```python
# Current (manual):
# "WR dropped, apply patch manually, check logs manually"

# New (autonomous + learning):
change = learning_engine.should_change_strategy(metrics)
if change:
    validation = learning_engine.validate_against_history(change)
    if validation['allowed']:
        learning_engine.execute_and_learn(change, metrics_before)
    else:
        logging.info(f"Change blocked by history: {validation['reason']}")
```

This transforms the bot from "requires manual intervention every crisis" to "learns and self-adjusts autonomously while respecting learned safety boundaries."
