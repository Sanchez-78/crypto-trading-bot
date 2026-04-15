"""
SELF-HEALING SYSTEM — Integration Guide

This module documents how to integrate safe_mode constraints into signal processing
to enable autonomous failure recovery.

────────────────────────────────────────────────────────────────────────────────
ARCHITECTURE OVERVIEW
────────────────────────────────────────────────────────────────────────────────

System Layers (from detecting to healing):

1. ANOMALY DETECTOR (src/core/anomaly.py)
   ↓ Detects: EQUITY_DROP, STALL, NO_SIGNALS, HIGH_DRAWDOWN
   
2. SELF-HEAL ENGINE (src/core/self_heal.py)
   ↓ Responds: reduce risk, boost exploration, loosen filters
   
3. STATE HISTORY (src/core/state_history.py)
   ↓ Saves/Restores: snapshots for rollback
   
4. SAFE MODE CONSTRAINTS (via self_heal functions)
   ↓ Applied: signal.size *= 0.3, signal.confidence *= 0.8
   
5. MAIN LOOP (bot2/main.py)
   ↓ Cycle: detect → heal → save → render
   
────────────────────────────────────────────────────────────────────────────────
INTEGRATION POINTS — WHERE TO APPLY CONSTRAINTS
────────────────────────────────────────────────────────────────────────────────

POINT 1: Signal Processing Pipeline
─────────────────────────────────────

Location: Where signals are prepared before execution

Example (src/services/execution.py or orchestrator.py):

    from src.core.self_heal import apply_safe_mode, apply_position_floor, apply_position_cap
    
    def process_signal(signal, state):
        # ... existing signal processing ...
        
        # Apply self-healing constraints
        signal = apply_safe_mode(signal, state)
        signal = apply_position_floor(signal, state)
        signal = apply_position_cap(signal, state)
        
        return signal

POINT 2: Position Sizing
────────────────────────

Location: Position size calculation

Before:
    size = base_size * ev_multiplier * confidence

After:
    from src.core.self_heal import apply_position_cap
    
    size = base_size * ev_multiplier * confidence
    size = apply_position_cap(size, state)  # Never exceed max
    
    if state.risk_multiplier < 0.5:  # Healing active
        size *= state.risk_multiplier

POINT 3: Filter Thresholds
──────────────────────────

Location: Dynamic filter threshold adjustment

After anomaly is handled, filter_strength is adjusted:

    from src.optimized.filter_pipeline import SignalFilterPipeline
    
    pipeline = SignalFilterPipeline(cfg)
    
    # Normal state:
    filter_strength = 1.0
    
    # If healing active (state.filter_strength < 1.0):
    filter_strength = state.filter_strength
    
    # Apply to filters:
    minimum_ev = 0.01 * filter_strength  # Lower requirement = more signals

POINT 4: Execution Gate
───────────────────────

Location: Final check before trade execution

    from src.core.self_heal import failsafe_halt
    
    def execute_trade(signal, state):
        # Check failsafe
        if failsafe_halt(state):
            return None  # Trading halted
        
        # Otherwise execute
        return execute(signal)

────────────────────────────────────────────────────────────────────────────────
ANOMALY RESPONSE MAPPING
────────────────────────────────────────────────────────────────────────────────

ANOMALY: EQUITY_DROP (>3% drop from peak)
├─ Response:
│  ├─ risk_multiplier *= 0.5      (50% risk cut)
│  ├─ safe_mode = True            (activate constraints)
│  ├─ max_position_size *= 0.5    (position size limit cut)
│  └─ exploration_factor *= 1.2   (try new strategies)
└─ Signal Effect:
   └─ size *= 0.3 × 0.5 = 15% of normal

ANOMALY: HIGH_DRAWDOWN (>35% daily loss)
├─ Response:
│  ├─ risk_multiplier *= 0.3      (70% risk cut)
│  ├─ safe_mode = True
│  ├─ max_position_size *= 0.3
│  └─ filter_strength *= 1.2      (tighten filters)
└─ Signal Effect:
   └─ size *= 0.3 × 0.3 = 9% of normal
   └─ More filters reject signals (exploration needed)

ANOMALY: STALL (no trades for 15 min)
├─ Response:
│  ├─ exploration_factor *= 1.5   (boost exploration 50%)
│  ├─ allow_micro_trade = True    (enable micro-positions)
│  ├─ ev_threshold *= 0.9         (lower EV requirement)
│  └─ filter_strength *= 0.9      (soften filters)
└─ Signal Effect:
   └─ More signals pass filters
   └─ Minimum position allowed: 0.01 BTC
   └─ Lower EV threshold triggered

ANOMALY: NO_SIGNALS (3+ cycles with zero signals)
├─ Response:
│  ├─ ev_threshold *= 0.8         (80% of normal requirement)
│  ├─ filter_strength *= 0.8      (20% softer)
│  ├─ allow_micro_trade = True
│  └─ min_position_floor = 0.01
└─ Signal Effect:
   └─ Pipeline becomes more permissive
   └─ Micro-trades restart signal flow

────────────────────────────────────────────────────────────────────────────────
STATE.PY — REQUIRED FIELDS FOR SELF-HEALING
────────────────────────────────────────────────────────────────────────────────

The State object needs these fields for the system to work:

Required:
├─ equity: float                  # Current account equity
├─ drawdown: float                # Current drawdown (0.0 - 1.0)
├─ no_trade_duration: float       # Seconds since last trade (from last_trade_ts)
└─ signal_count: int              # Number of signals in last cycle

Added by self-healing:
├─ safe_mode: bool (default False)
├─ risk_multiplier: float (default 1.0)
├─ max_position_size: float (default 0.05)
├─ exploration_factor: float (default 1.0)
├─ allow_micro_trade: bool (default False)
├─ min_position_floor: float (default 0.0)
├─ filter_strength: float (default 1.0)
├─ ev_threshold: float
└─ trading_enabled: bool (default True)

────────────────────────────────────────────────────────────────────────────────
SAFETY METRICS — MONITOR THESE
────────────────────────────────────────────────────────────────────────────────

In your dashboard/logging, track:

1. Anomaly Detection Rate
   Format: {anomalies_detected} in last {time_window}
   Alert: > 5 anomalies per hour = system instability

2. Safe Mode Duration
   Format: safe_mode active for {seconds}
   Alert: > 3600 seconds (1 hour) = system not recovering

3. Risk Multiplier
   Format: risk_multiplier = {value}
   Normal: 1.0
   Healing: 0.3 - 0.5

4. Rollback Events
   Format: {rollbacks_executed} rollbacks
   Alert: > 3 rollbacks per 24h = frequent failures

5. Filter Strength
   Format: filter_strength = {value}
   Normal: 1.0
   Loose: 0.8 - 0.9

────────────────────────────────────────────────────────────────────────────────
TESTING SELF-HEALING BEHAVIOR
────────────────────────────────────────────────────────────────────────────────

To test without live trading:

1. EQUITY_DROP test:
   Simulate by manually reducing state.equity by 3%
   Expect: risk_multiplier = 0.5, safe_mode = True

2. STALL test:
   Set last_trade_ts = time.time() - 1000
   Expect: exploration_factor = 1.5, allow_micro_trade = True

3. NO_SIGNALS test:
   Set signal_count = 0 for 3 cycles
   Expect: filter_strength = 0.8, ev_threshold lowered

4. HIGH_DRAWDOWN test:
   Set drawdown = 0.40 (40%)
   Expect: risk_multiplier = 0.3, filter_strength = 1.2

────────────────────────────────────────────────────────────────────────────────
BEST PRACTICES
────────────────────────────────────────────────────────────────────────────────

1. ✅ DO:
   - Call self_heal_cycle() ONCE per main loop cycle
   - Use event_bus for all healing logs (audit trail)
   - Monitor anomaly_detector.status() periodically
   - Keep state_history max_size = 100 (bounded memory)
   - Check failsafe_halt() before execution gate

2. ❌ DON'T:
   - Apply safe_mode multiple times (already done in apply_safe_mode)
   - Rollback more than 10 steps (state divergence)
   - Leave trading_enabled = False manually (use failsafe only)
   - Reduce risk_multiplier below 0.1 (system freeze)

3. 🔍 MONITORING:
   - Log all anomalies with event_bus
   - Track anomaly frequency (sliding window)
   - Alert on > 3 consecutive failsafes
   - Record recovery time (time to exit safe_mode)

────────────────────────────────────────────────────────────────────────────────
COMPLETE CYCLE PSEUDOCODE
────────────────────────────────────────────────────────────────────────────────

while True:
    # Normal operations
    market = fetch_market_data()
    signals = generate_signals(market)
    
    for signal in signals:
        # Apply self-healing constraints
        signal = apply_safe_mode(signal, state)
        signal = apply_position_floor(signal, state)
        signal = apply_position_cap(signal, state)
        
        # Execute (gate prevents execution if needed)
        if not failsafe_halt(state):
            execute(signal)
    
    # CRITICAL POSITION: Self-heal cycle
    anomalies = detector.check(state)
    for anomaly in anomalies:
        handle_anomaly(anomaly, state)
    
    state = history.rollback_if_needed(state, anomalies)
    history.save(state)
    
    # Snapshot and render
    snapshot = build_snapshot(state)
    render(snapshot)
    
    sleep(10)

────────────────────────────────────────────────────────────────────────────────
"""

# No code here — this is pure documentation.
# Integration happens in:
# - src/services/execution.py or orchestrator.py (signal processing)
# - bot2/main.py (main loop)
