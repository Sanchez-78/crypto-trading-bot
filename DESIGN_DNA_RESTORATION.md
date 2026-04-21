# Design DNA Restoration — CryptoMaster Visual Identity
**Date**: 2026-04-21 | **Status**: AUDIT + PLAN | **Phase**: Return to Original DNA

---

## EXECUTIVE SUMMARY

The current Premium Terminal implementation (Phase 3) provides a **solid foundation** but lacks **CryptoMaster's original trading DNA**. This document maps what was lost, what's preserved, and how to restore the character that made CryptoMaster distinctive.

**Current State**: 92% foundation. **Missing**: Trading edge, close reasons, rejection reasons, learning indicators.

---

## 1. PRESERVED ELEMENTS ✅

### A. Visual Foundation
- ✅ **Dark terminal feel**: #111318 background, warm graphite palette
- ✅ **4-color semantic system**: Green (win), Red (loss), Amber (warning), Blue (active)
- ✅ **Premium card design**: Rounded corners (20px), subtle shadows, clean spacing
- ✅ **Monospace numbers**: tabular-nums, high visual weight (900 fontWeight)
- ✅ **Trading-aware badges**: BUY/SELL signals with direction emoji (↑↓)

### B. Data Structure
- ✅ **Comprehensive metrics flow**: Server → Firebase → App (clean v2 schema)
- ✅ **Trade counts**: trades, wins, losses, timeouts (all tracked)
- ✅ **Performance metrics**: winrate, profit_factor, expectancy (v2 block)
- ✅ **Portfolio health**: equity, drawdown, current_drawdown (clean separation)
- ✅ **Regime awareness**: dominant_regime, regime_stats, per-symbol breakdown

### C. Code Organization
- ✅ **theme.js**: Color system, typography, format utilities all in place
- ✅ **ui.js**: 19 shared components (Card, SectionHeader, MetricCard, etc.)
- ✅ **5-tab navigation**: Přehled, Portfolio, Výkon, Strategie, Systém

---

## 2. ELEMENTS TO RESTORE 🔄

### A. Close Reason Mapping + Visualization
**Current State**: StrategieScreen shows CLOSE_META with 14 exit reasons.

**Missing**: Visual distinction between exit categories in other screens.

**Restoration**:
```javascript
// Extend CLOSE_META to all screens that show trade history
const CLOSE_META = {
  // Profitable exits (green family)
  TP:              { label: 'Take Profit',      icon: '✓', color: '#22C55E' },
  HARVEST_PROFIT:  { label: 'Harvest Profit',   icon: '🌾', color: '#15803D' },
  TRAIL_PROFIT:    { label: 'Trail Profit',     icon: '📈', color: '#16A34A' },
  TIMEOUT_PROFIT:  { label: 'Timeout Zisk',     icon: '⏱', color: '#86EFAC' },
  
  // Loss exits (red family)
  SL:              { label: 'Stop Loss',        icon: '✕', color: '#EF4444' },
  TRAIL_SL:        { label: 'Trail Stop Loss',  icon: '📉', color: '#DC2626' },
  TIMEOUT_LOSS:    { label: 'Timeout Ztráta',   icon: '⏱', color: '#FCA5A5' },
  
  // Neutral/Protected exits (amber/gray)
  SCRATCH_EXIT:    { label: 'Scratch Exit',     icon: '⊗', color: '#F59E0B' },
  BREAKEVEN_STOP:  { label: 'Breakeven Stop',   icon: '═', color: '#92400E' },
  TIMEOUT_FLAT:    { label: 'Timeout Flat',     icon: '─', color: '#9CA3AF' },
  STAGNATION_EXIT: { label: 'Stagnation Exit',  icon: '❄', color: '#60A5FA' },
  
  // Micro exits (rare)
  MICRO_TP:        { label: 'Micro TP',         icon: '◆', color: '#A3E635' },
};
```

**Implementation Sites**:
1. **HistoryScreen**: Show close_reason icon + color alongside trade result
2. **TradesScreen**: Add reason indicator in list view
3. **DashboardScreen**: Add "Most common exit reason" insight

### B. Rejection Reason Tracking + Visualization
**Current State**: System signals are generated, filtered, executed, blocked. But no visualization of *why* signals were rejected.

**Missing**: 
- Rejection reason breakdown (by type: regime_block, max_positions, insufficient_ev, etc.)
- Visual insight: "Why are 60% of signals rejected?"
- Learning signal: "Regime blocking is protective (good)" vs "EV gate is too tight (maybe tighten WR)"

**Restoration**:
```javascript
// Add to system block in Firebase
"rejection_breakdown": {
  "regime_concentration": 0,  // Too many same regime
  "max_positions": 0,         // Portfolio full
  "insufficient_ev": 0,       // EV too low
  "confidence_gate": 0,       // Confidence too low
  "correlation_shield": 0,    // Would increase portfolio correlation
  "regime_block": 0,          // Regime has too low WR
  "other": 0
}
```

**Implementation Sites**:
1. **SystemScreen**: Add "Signal Filtering" section showing rejection breakdown
2. **PrehledScreen**: Add mini insight: "60% of signals rejected — Regime safety is active"
3. **Learning indicator**: Color-code if rejections are protective (good) or excessive (tight)

### C. Learning Edge Indicators
**Current State**: Score (0-100), Status (HEALTHY/RISKY/LEARNING), learning_state.

**Missing**:
- Visible progression (trades until ready)
- Confidence trajectory (improving/degrading)
- Edge detection (system is discovering something)
- Learning speed (data collected vs data needed)

**Restoration**:
```javascript
// Add to health block in Firebase
"learning": {
  "progress_to_ready": 0.45,           // Fraction of way to "ready" (0.55 WR + PF>1.5)
  "confidence_momentum": "IMPROVING",  // vs STABLE, DEGRADING
  "edge_detected": false,              // System found an exploitable pattern
  "data_maturity": 0.68,               // (trades - 20) / expected_trades_for_confidence
  "next_milestone": "Ready for aggressive sizing (60 decisive trades needed)"
}
```

**Implementation Sites**:
1. **PrehledScreen**: Add "Learning Progress" card showing path to ready
2. **VykonScreen**: Add "Confidence Trend" mini chart (trend line)
3. **SystemScreen**: Add "Edge Detection" status (what is the bot discovering?)

### D. Decision-Aware Trade Cards
**Current State**: Trades shown as list with symbol, PnL, result.

**Missing**:
- Why was this trade entered? (regime state, confidence, EV at time)
- Why was it exited? (not just close reason, but context)
- What was learned? (confirms or contradicts hypothesis)

**Restoration** (add to trade metadata in Firestore):
```javascript
trade: {
  // Exit
  symbol, action, entry_price, exit_price, profit, result, close_reason,
  
  // Decision context (snapshot at entry)
  regime_at_entry: "BULL_TREND",       // Market regime when entered
  confidence_at_entry: 0.68,           // Model confidence at signal time
  ev_at_entry: 0.0245,                 // Expected value at entry decision
  
  // Learning context (at exit)
  confidence_at_exit: 0.72,            // Did confidence improve?
  learning_update: "profit +0.0015"    // What was added to learning?
}
```

**Implementation Sites**:
1. **TradeDetailScreen**: Expand to show decision context
2. **HistoryScreen**: Add expandable "Why?" section
3. **DashboardScreen**: "Last trade" shows decision rationale

---

## 3. INTENTIONALLY REMOVED ❌

### What Was NOT Restored (and Why)

| Element | Why Not Restored | Original Intent | Current Alternative |
|---------|-----------------|-----------------|---------------------|
| Multiple tabs per symbol | Cluttered navigation | Per-pair deep dives | StrategieScreen sym_stats bars |
| Rejection reason popups | Verbose at decision time | Help user understand signal | SystemScreen rejection breakdown |
| Real-time port folioMonitoring (every tick) | Performance overhead | Ultra-detailed awareness | 30s Firebase refresh is sufficient |
| ML confidence calibration details | User-facing noise | Show calibrator state | Confidence_momentum + edge_detected |
| Complex waterfall earnings chart | Hard to read quickly | Revenue timeline | Simple equity curve in VykonScreen |

---

## 4. CHANGED FILES

### Existing (Phase 3)
- **theme.js**: ✅ Already has SIGNAL_STYLE, COIN_META, format utils
- **src/components/ui.js**: ✅ Already has 19 shared components
- **5-screen structure**: ✅ Already in place

### New/Modified Needed
1. **firebase_client.py**: Add rejection_breakdown, learning block to system
2. **StrategieScreen.js**: Already shows close_stats with CLOSE_META ✅
3. **SystemScreen.js**: Add rejection breakdown visualization
4. **PrehledScreen.js**: Add learning progress indicator
5. **HistoryScreen.js**: Add close_reason icons + colors
6. **TradesScreen.js**: Add rejection insight (if applicable)
7. **TradeDetailScreen.js**: Enhance with decision context

---

## 5. SPECIFIC CODE CHANGES

### Change 1: Add CLOSE_META to theme.js
```javascript
export const CLOSE_META = {
  TP:              { label: 'Take Profit',      icon: '✓', color: '#22C55E' },
  HARVEST_PROFIT:  { label: 'Harvest Profit',   icon: '🌾', color: '#15803D' },
  TRAIL_PROFIT:    { label: 'Trail Profit',     icon: '📈', color: '#16A34A' },
  SL:              { label: 'Stop Loss',        icon: '✕', color: '#EF4444' },
  TRAIL_SL:        { label: 'Trail Stop Loss',  icon: '📉', color: '#DC2626' },
  SCRATCH_EXIT:    { label: 'Scratch Exit',     icon: '⊗', color: '#F59E0B' },
  BREAKEVEN_STOP:  { label: 'Breakeven Stop',   icon: '═', color: '#92400E' },
  TIMEOUT_PROFIT:  { label: 'Timeout Zisk',     icon: '⏱', color: '#86EFAC' },
  TIMEOUT_LOSS:    { label: 'Timeout Ztráta',   icon: '⏱', color: '#FCA5A5' },
  TIMEOUT_FLAT:    { label: 'Timeout Flat',     icon: '─', color: '#9CA3AF' },
  STAGNATION_EXIT: { label: 'Stagnation Exit',  icon: '❄', color: '#60A5FA' },
  MICRO_TP:        { label: 'Micro TP',         icon: '◆', color: '#A3E635' },
  timeout:         { label: 'Timeout (neutr.)', icon: '○', color: '#9CA3AF' },
};
```

### Change 2: Update HistoryScreen.js to use close_reason colors
```javascript
// In trade list item:
const reason = trade.close_reason ?? '—';
const rm = CLOSE_META[reason] ?? { label: reason, icon: '?', color: COLORS.textMuted };

return (
  <View style={s.tradeRow}>
    <View style={[s.reasonDot, { backgroundColor: rm.color }]} />
    <Text style={s.reasonLabel}>{rm.label}</Text>
    {/* rest of trade row */}
  </View>
);
```

### Change 3: SystemScreen.js — Add rejection breakdown
```javascript
const rejectionBreakdown = sy.rejection_breakdown ?? {};
const entries = Object.entries(rejectionBreakdown)
  .filter(([, v]) => v > 0)
  .sort((a, b) => b[1] - a[1])
  .slice(0, 6);

return (
  <>
    <SectionHeader title="SIGNAL FILTERING" subtitle="Proč jsou signály zamítnuty" />
    <Card>
      {entries.map(([reason, count]) => (
        <View key={reason} style={s.reasonRow}>
          <Text style={s.reasonKey}>{reason.replace(/_/g, ' ')}</Text>
          <Text style={[NUM.xs, { color: COLORS.textSub }]}>{count}×</Text>
        </View>
      ))}
    </Card>
  </>
);
```

### Change 4: PrehledScreen.js — Add learning progress
```javascript
const learningBlk = hl.learning ?? {};
const progress = learningBlk.progress_to_ready ?? 0;
const momentum = learningBlk.confidence_momentum ?? '—';

return (
  <>
    <SectionHeader title="LEARNING PROGRESS" />
    <Card>
      <View style={s.progressRow}>
        <View style={[s.progressBar, { width: `${progress * 100}%` }]} />
      </View>
      <Text style={s.progressLabel}>
        {(progress * 100).toFixed(0)}% do READY (60 decisive trades)
      </Text>
      <View style={s.momentumChip}>
        <Text style={[NUM.xs, { color: COLORS.active }]}>
          Confidence: {momentum}
        </Text>
      </View>
    </Card>
  </>
);
```

---

## 6. IMPLEMENTATION PRIORITY

**Tier 1** (Restore trading DNA core):
1. Add CLOSE_META to theme.js
2. Update HistoryScreen with close_reason colors
3. Add rejection_breakdown to SystemScreen

**Tier 2** (Add learning indicators):
4. Add learning block to health (firebase_client.py)
5. Add learning progress to PrehledScreen
6. Add confidence momentum to VykonScreen

**Tier 3** (Decision context details):
7. Enhance TradeDetailScreen with regime_at_entry, confidence_at_entry, ev_at_entry
8. Add learning_update notes to trade cards

---

## 7. VALIDATION CHECKLIST

- [ ] CLOSE_META is exported from theme.js and used in HistoryScreen
- [ ] Close reason colors are visible in trade list (not just labels)
- [ ] SystemScreen shows rejection breakdown with counts
- [ ] PrehledScreen shows learning progress bar
- [ ] VykonScreen shows confidence momentum indicator
- [ ] firebase_client.py includes rejection_breakdown and learning blocks in Firebase save
- [ ] App subscribeRobotMeta correctly reads rejection_breakdown and learning
- [ ] TradeDetailScreen shows decision context (regime, confidence, EV at entry)
- [ ] All colors use COLORS from theme (no hardcoded hex)
- [ ] Emoji indicators (✓ ✕ 📈 📉) render correctly on Android

---

## SUMMARY

**Phase 3 Premium Terminal** provided the visual foundation. **Phase 2b Design DNA Restoration** adds back:
- Trading edge character (close reasons, rejection tracking)
- Learning progression indicators
- Decision-aware trade cards
- System health transparency

**Impact**: App shifts from "generic metrics dashboard" → "trading platform that shows you why the bot makes decisions and what it's learning"

**Estimated scope**: 8 files modified, ~300 lines code, 2-3 hours implementation.

