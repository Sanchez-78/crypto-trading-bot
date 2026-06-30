# Android App: Learning Adjustment Metrics Implementation

**Document Version:** 1.0  
**Date:** 2026-06-30  
**Status:** Ready for Implementation  
**Audience:** Android Development Team  

---

## Executive Summary

The CryptoMaster trading bot now exposes real-time insights into its autonomous learning and adaptation process. This specification defines the new metrics, API contracts, and UI components needed to display these insights in the Android app.

**Goal:** Make the bot's self-improvement process transparent to users by displaying:
- Real-time learning system status
- Per-regime TP (Take-Profit) target adaptation
- Entry quality assessment
- Historical adaptation trends

---

## API Contract

### Endpoint: `/api/dashboard/learning-state`

**HTTP Method:** GET  
**Response Format:** JSON  
**Refresh Interval:** 5-10 seconds (same as main metrics)  
**Timeout:** 5 seconds

#### Response Schema

```json
{
  "timestamp": 1719744098,
  "learning_enabled": true,
  "learning_blend": 0.45,
  "lifecycle": "PAPER_ADAPTING",
  "lifetime_closes": 568,
  "lifetime_pf": 1.23,
  "lifetime_expectancy": 0.0156,
  "entry_quality_gate": {
    "passing": true,
    "non_timeout_pct": 78.5
  },
  "regime_tp_strategy": {
    "BULL_TREND": {
      "low_vol": {
        "tp_pct": 0.18,
        "wr": 0.65,
        "n": 145
      },
      "mid_vol": {
        "tp_pct": 0.21,
        "wr": 0.58,
        "n": 98
      },
      "high_vol": {
        "tp_pct": 0.26,
        "wr": 0.52,
        "n": 67
      }
    },
    "BEAR_TREND": {
      "low_vol": {
        "tp_pct": 0.16,
        "wr": 0.62,
        "n": 112
      },
      "mid_vol": {
        "tp_pct": 0.19,
        "wr": 0.55,
        "n": 89
      },
      "high_vol": {
        "tp_pct": 0.24,
        "wr": 0.48,
        "n": 51
      }
    },
    "RANGING": {
      "low_vol": {
        "tp_pct": 0.12,
        "wr": 0.68,
        "n": 76
      },
      "mid_vol": {
        "tp_pct": 0.15,
        "wr": 0.60,
        "n": 54
      },
      "high_vol": {
        "tp_pct": 0.21,
        "wr": 0.50,
        "n": 32
      }
    }
  },
  "rolling_windows": {
    "rolling20_size": 20,
    "rolling50_size": 50,
    "rolling50_recent_10_trades": [
      {
        "index": 49,
        "pnl_pct": 0.18,
        "outcome": "WIN",
        "symbol_regime": "ETHUSDT:BULL_TREND:mid_vol",
        "timestamp": 1719744050
      }
    ]
  },
  "status": "active"
}
```

#### Field Definitions

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `timestamp` | Unix timestamp | — | When this snapshot was captured (seconds since epoch) |
| `learning_enabled` | Boolean | true/false | Whether adaptive learning is currently active |
| `learning_blend` | Float | 0.0 - 1.0 | Blend factor (0=no learning, 1=full learning influence) |
| `lifecycle` | String | PAPER_COLLECTING, PAPER_ADAPTING, VALIDATING, REAL_READY | Current bot lifecycle phase |
| `lifetime_closes` | Integer | ≥ 0 | Total closed trades across entire session |
| `lifetime_pf` | Float | ≥ 0.0 | Lifetime profit factor (all trades) |
| `lifetime_expectancy` | Float | any | Lifetime mathematical expectation per trade |
| `entry_quality_gate.passing` | Boolean | true/false | Entry quality gate status (must be >75% non-timeout) |
| `entry_quality_gate.non_timeout_pct` | Float | 0.0 - 100.0 | % of last 50 closes that were NOT timeouts |
| `regime_tp_strategy[regime][vol_band].tp_pct` | Float | 0.001 - 1.0 | Current TP target for this regime/vol combo (% above entry) |
| `regime_tp_strategy[regime][vol_band].wr` | Float | 0.0 - 1.0 | Win rate on this regime/vol combo (0.65 = 65%) |
| `regime_tp_strategy[regime][vol_band].n` | Integer | ≥ 0 | Number of closed trades in this regime/vol combo |
| `rolling_windows.rolling50_size` | Integer | 0 - 50 | Current size of rolling 50-trade window |
| `rolling_windows.rolling50_recent_10_trades[]` | Array | — | Last 10 trades from rolling 50-trade window |
| `status` | String | active, inactive, error | API/learning system status |

#### Regime Values

- `BULL_TREND` - Uptrend detected (price > EMA50, ADX > 25)
- `BEAR_TREND` - Downtrend detected (price < EMA50, ADX > 25)
- `RANGING` - Range-bound market (no strong trend, ADX < 25)
- `QUIET_RANGE` - Flat market (price very stable, low volatility)

#### Volatility Bands

- `low_vol` - ATR < 0.05% (very stable)
- `mid_vol` - ATR 0.05% - 0.15% (normal)
- `high_vol` - ATR > 0.15% (volatile)

#### Outcomes

- `WIN` - Trade closed with profit
- `LOSS` - Trade closed with loss
- `FLAT` - Trade closed at or near entry (break-even)
- `TIMEOUT` - Position held until timeout, then force-closed

---

## UI Components

### 1. Learning Status Card

**Location:** Top section of dashboard (alongside Win Rate, Profit Factor)

**Layout:**
```
┌─────────────────────────────┐
│ 🤖 Learning Status          │
├─────────────────────────────┤
│ Enabled:      ✓ ACTIVE      │
│ Blend:        45.0%         │
│ Entry Gate:   ✓ PASS (78%)  │
│ Lifetime:     568 closes    │
└─────────────────────────────┘
```

**Content:**
- `Enabled`: Green checkmark if `learning_enabled == true`, else gray circle
- `Blend`: Progress bar + percentage (0% → 100%)
- `Entry Gate`: Pass (green ✓) or Fail (red ✗) + non_timeout_pct
- `Lifetime`: Lifetime closes count

**Update Frequency:** 5-10 seconds

**Colors:**
- ✓ ACTIVE: #00FF00 (green)
- ○ INACTIVE: #888888 (gray)
- ✓ PASS: #00FF00 (green)
- ✗ FAIL: #FF4444 (red)

---

### 2. Regime TP Strategy Table

**Location:** Expandable section below main metrics

**Layout:**
```
┌───────────────────────────────────────────────────────────────┐
│ Regime TP Strategy (Adaptive Targets)                         │
├──────────────┬──────────────┬─────────┬──────────┬─────┬──────┤
│ Regime       │ Volatility   │ TP %    │ Win Rate │ N   │ Status
├──────────────┼──────────────┼─────────┼──────────┼─────┼──────┤
│ BULL_TREND   │ low_vol      │ 0.18%   │ 65.0%   │ 145 │ ✓ HIGH
│ BULL_TREND   │ mid_vol      │ 0.21%   │ 58.0%   │ 98  │ • MID
│ BULL_TREND   │ high_vol     │ 0.26%   │ 52.0%   │ 67  │ • MID
│ BEAR_TREND   │ low_vol      │ 0.16%   │ 62.0%   │ 112 │ ✓ HIGH
│ ...          │ ...          │ ...     │ ...     │ ... │ ...
└──────────────┴──────────────┴─────────┴──────────┴─────┴──────┘
```

**Columns:**
1. **Regime** - Market regime (BULL_TREND, BEAR_TREND, RANGING, QUIET_RANGE)
2. **Volatility** - Volatility band (low_vol, mid_vol, high_vol)
3. **TP %** - Current TP target as percentage above entry (e.g., 0.18%)
4. **Win Rate** - Win rate on this regime/vol combo (e.g., 65.0%)
5. **N** - Number of closed trades in this regime
6. **Status** - Quality indicator based on Win Rate:
   - ✓ HIGH (WR ≥ 55%)
   - • MID (45% ≤ WR < 55%)
   - ✗ LOW (WR < 45%)

**Color Coding:**
- TP value: Bold white
- Win Rate ✓ HIGH: Green (#00FF00)
- Win Rate • MID: Orange (#FFAA00)
- Win Rate ✗ LOW: Red (#FF4444)

**Sorting/Filtering:**
- Sort by: Win Rate (descending) | Closes (descending) | Regime | Volatility
- Filter by: Regime | Volatility | Min closes (50, 100, etc.)

**Update Frequency:** 10-15 seconds (less frequent than metrics)

---

### 3. Entry Quality Gauge

**Location:** Within Learning Status Card or as separate mini-component

**Visual:** Circular progress gauge or horizontal bar

```
Entry Quality: ▰▰▰▰▰▰▰▰░░ 78.5% (PASS)
```

**Threshold:**
- ✓ PASS: ≥ 75% non-timeout exits (green)
- ✗ FAIL: < 75% non-timeout exits (red)

**Explanation:** This gate prevents TP adaptation when entry timing is poor. Must reach 75%+ quality before learning can optimize TP targets.

---

### 4. Recent Adaptations Timeline (Optional)

**Location:** Expandable section below Regime TP Strategy

**Purpose:** Show recent changes to TP targets (learning in action)

**Data Source:** Would require new API endpoint `/api/dashboard/learning-adaptations` returning:

```json
[
  {
    "timestamp": 1719744050,
    "regime": "BULL_TREND",
    "vol_band": "mid_vol",
    "old_tp_pct": 0.20,
    "new_tp_pct": 0.21,
    "reason": "wr_increasing_above_55_percent",
    "wr_before": 0.54,
    "wr_after": 0.58,
    "closes_since_last_adapt": 50
  }
]
```

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│ Recent Adaptations (Last 10)                                │
├─────────────────────────────────────────────────────────────┤
│ [14:52] BULL_TREND mid_vol: TP 0.20% → 0.21% (WR 54→58%)   │
│ [14:22] BEAR_TREND low_vol: TP 0.16% → 0.17% (WR 60→62%)   │
│ [13:52] RANGING mid_vol: TP 0.15% → 0.14% (WR 62→60%)      │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Checklist

### Phase 1: API Integration (Priority: HIGH)

- [ ] Add API parsing for `/api/dashboard/learning-state` response
- [ ] Implement periodic fetch (5-10s refresh rate)
- [ ] Add error handling for API unavailability
- [ ] Cache latest response in local state
- [ ] Test with real Hetzner bot (staging URL)

### Phase 2: Core UI Components (Priority: HIGH)

- [ ] Learning Status Card component
  - [ ] Learning enabled/disabled indicator
  - [ ] Learning blend progress bar
  - [ ] Entry quality gate display
  - [ ] Lifetime closes counter
- [ ] Regime TP Strategy Table component
  - [ ] Parse `regime_tp_strategy` from API
  - [ ] Render dynamic table rows
  - [ ] Color-code by Win Rate
  - [ ] Sort/filter controls
- [ ] Update main dashboard layout to include new components
- [ ] Test on Android devices (various screen sizes)

### Phase 3: Enhanced Features (Priority: MEDIUM)

- [ ] Add tap/expand to show detailed regime stats
- [ ] Implement sorting by Win Rate, Closes, Regime
- [ ] Add filtering by regime or volatility
- [ ] Sparkline chart for recent WR trend (optional)
- [ ] Swipe-to-refresh on learning metrics

### Phase 4: Advanced Features (Priority: LOW)

- [ ] Recent Adaptations Timeline (requires new API endpoint)
- [ ] Historical TP strategy chart (heatmap or line chart)
- [ ] Adaptation notifications ("TP target increased for BULL_TREND")
- [ ] Learning blend transition animation

---

## Sample Kotlin Implementation (Reference)

```kotlin
// Data class for API response
data class LearningState(
    val timestamp: Long,
    val learning_enabled: Boolean,
    val learning_blend: Float,
    val lifecycle: String,
    val lifetime_closes: Int,
    val lifetime_pf: Float,
    val lifetime_expectancy: Float,
    val entry_quality_gate: EntryQualityGate,
    val regime_tp_strategy: Map<String, Map<String, RegimeStats>>,
    val rolling_windows: RollingWindows,
    val status: String
)

data class EntryQualityGate(
    val passing: Boolean,
    val non_timeout_pct: Float
)

data class RegimeStats(
    val tp_pct: Float,
    val wr: Float,
    val n: Int
)

data class RollingWindows(
    val rolling20_size: Int,
    val rolling50_size: Int,
    val rolling50_recent_10_trades: List<Trade>
)

// API call example
suspend fun fetchLearningState(apiClient: ApiClient): Result<LearningState> {
    return try {
        val response = apiClient.get("/api/dashboard/learning-state")
        Result.success(response.body() as LearningState)
    } catch (e: Exception) {
        Result.failure(e)
    }
}

// UI composable example (Jetpack Compose)
@Composable
fun LearningStatusCard(learning: LearningState) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("🤖 Learning Status", style = MaterialTheme.typography.titleMedium)
            
            Row(modifier = Modifier.fillMaxWidth()) {
                LabelValue("Enabled", 
                    if (learning.learning_enabled) "✓ ACTIVE" else "○ INACTIVE",
                    if (learning.learning_enabled) Color.Green else Color.Gray)
            }
            
            LearningBlendBar(learning.learning_blend)
            
            Row(modifier = Modifier.fillMaxWidth()) {
                LabelValue("Entry Gate",
                    "${if (learning.entry_quality_gate.passing) "✓" else "✗"} ${
                        learning.entry_quality_gate.non_timeout_pct.toInt()
                    }%",
                    if (learning.entry_quality_gate.passing) Color.Green else Color.Red)
            }
        }
    }
}

@Composable
fun RegimeTPStrategyTable(strategy: Map<String, Map<String, RegimeStats>>) {
    LazyColumn {
        items(
            strategy.flatMap { (regime, volBands) ->
                volBands.map { (vol, stats) ->
                    Triple(regime, vol, stats)
                }
            }
        ) { (regime, vol, stats) ->
            RegimeRow(regime, vol, stats)
        }
    }
}
```

---

## Testing Checklist

### Unit Tests
- [ ] API response parsing (happy path + edge cases)
- [ ] NaN/Infinity handling in metrics
- [ ] Empty regime_tp_strategy handling
- [ ] Null field handling

### Integration Tests
- [ ] Fetch learning state every 10 seconds for 5 minutes
- [ ] Verify no ANR (Application Not Responding) errors
- [ ] Verify UI updates without jank (smooth 60 FPS)
- [ ] Test network timeout handling (5-second timeout)

### UI Tests (on device)
- [ ] Cards render correctly on small phones (5" screens)
- [ ] Cards render correctly on large tablets (10" screens)
- [ ] Table scrolls smoothly horizontally (if needed)
- [ ] No text truncation or overlap
- [ ] Colors match design spec (verify on actual device)

### Real-World Testing
- [ ] Connect to staging Hetzner instance
- [ ] Verify metrics update in real-time as bot trades
- [ ] Verify learning blend increases over time (if enabled)
- [ ] Verify regime TP targets adapt as WR changes

---

## Error Handling

### API Failures
- **Timeout (> 5s):** Show cached data with "Stale" label
- **HTTP 500:** Show error message "Learning data unavailable"
- **Network unreachable:** Show cached data, "Offline" label
- **HTTP 404:** Show "Learning API not available" (unsupported server version)

### Corrupt/Invalid Data
- **Invalid learning_blend (not 0.0-1.0):** Clamp to range, log warning
- **Negative win rates:** Treat as 0.0, log warning
- **Missing regime in strategy:** Show empty row, don't crash
- **NaN profit factor:** Display as "—", don't render

---

## Performance Considerations

- **API call frequency:** 5-10 seconds (balance freshness vs. bandwidth)
- **Local caching:** Keep last response in memory, update every fetch
- **Table rendering:** Use RecyclerView or LazyColumn for efficient scrolling
- **Memory:** Regime data is small (~2-5 KB), no memory concerns
- **Battery:** API calls are lightweight, minimal battery impact

---

## Localization (i18n)

Translate these strings:
- "Learning Status"
- "Entry Quality Gate"
- "Regime TP Strategy"
- "ACTIVE" / "INACTIVE"
- "PASS" / "FAIL"
- "HIGH" / "MID" / "LOW"
- Regime names: BULL_TREND, BEAR_TREND, RANGING, QUIET_RANGE
- Volatility: low_vol, mid_vol, high_vol

---

## Design Specifications

- **Font:** Roboto / System font
- **Icon style:** Material Design (or match app's existing icons)
- **Colors:** 
  - Primary: #1E90FF (bot blue)
  - Success: #00FF00 (green)
  - Warning: #FFAA00 (orange)
  - Error: #FF4444 (red)
  - Background: #0A0E27 (dark blue)
  - Text: #E0E0E0 (light gray)
- **Dark mode:** Yes (required, already in spec)
- **Light mode:** No (trading focus, dark mode only)

---

## Timeline Estimate

- **Phase 1 (API):** 2-3 days (Kotlin + Retrofit)
- **Phase 2 (UI):** 4-5 days (Jetpack Compose or Views)
- **Phase 3 (Features):** 2-3 days (sorting, filtering, polish)
- **Phase 4 (Advanced):** 3-4 days (optional, timeline-based)
- **Testing:** 2-3 days (unit + integration + device)

**Total:** 13-18 days for phases 1-3, +3-4 days for phase 4

---

## Contact & Questions

For questions about this specification:
- Backend: Check `/api/dashboard/learning-state` real-time
- API changes: See `src/services/dashboard_web.py` line 1158+
- Metrics definition: See `src/services/paper_adaptive_learning.py` line 60+
- Test data: Hetzner staging instance (contact ops)

---

**Version History**

| Version | Date       | Author | Changes |
|---------|------------|--------|---------|
| 1.0     | 2026-06-30 | Bot   | Initial spec for learning metrics in Android |

