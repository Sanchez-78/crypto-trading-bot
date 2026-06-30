# ADAPTIVE MULTI-SCENARIO OPTIMIZATION DESIGN
## Comprehensive CryptoMaster Trading Bot Enhancement

**Document Version:** 1.0  
**Date:** 2026-06-26  
**Status:** Design Phase (Ready for Implementation)  
**Objective:** Enable bot to achieve >50% WR + positive P&L across ALL market conditions

---

## EXECUTIVE SUMMARY

Current bot performance varies dramatically by market condition:
- **Low volatility (0.01-0.05%)**: WR 48.7%, PF 0.949 (struggling)
- **Baseline (0.05-0.15%)**: WR 52.8%, PF 1.12 (working)
- **Historical timeout issue**: 0% WR on TIMEOUT exits, 94.6% on TP exits

**Root cause:** Static parameters (600s timeout, fixed TP/SL zones) don't adapt to market conditions. In low-vol environments, 600s is insufficient to reach TP targets. In high-vol, 600s risks reversals.

**Solution:** Adaptive system that detects market conditions in real-time and adjusts timeout, TP/SL, entry/exit logic dynamically, with learning system that optimizes per scenario.

---

## PART 1: VOLATILITY DETECTION & CLASSIFICATION

### 1.1 Real-Time Volatility Metrics

**Current Implementation:**
- ATR (Average True Range) calculated per signal at `signal_generator.py:684`
- ATR floor: `entry * 0.003` (minimum 0.3% of entry price)
- No volatility regime classification in parameters

**Proposed Enhancement:**

Create `src/services/volatility_detector.py` module:

```python
class VolatilityDetector:
    """Real-time volatility regime classification using ATR."""
    
    def __init__(self):
        self.atr_history = {}  # symbol -> [atr_values]
        self.regime_history = {}  # symbol -> regime
        self.max_window = 100  # ticks
    
    def add_atr(self, symbol: str, atr_pct: float, ts: float):
        """Record ATR percentage reading."""
        if symbol not in self.atr_history:
            self.atr_history[symbol] = []
        self.atr_history[symbol].append((atr_pct, ts))
        # Keep only last N readings
        if len(self.atr_history[symbol]) > self.max_window:
            self.atr_history[symbol].pop(0)
    
    def get_volatility_regime(self, symbol: str) -> str:
        """
        Return volatility regime based on recent ATR readings.
        
        Regimes:
        - STAGNATION: ATR < 0.01% (virtually no movement)
        - LOW_VOL: ATR 0.01-0.05% (slow markets, need patience)
        - MEDIUM_VOL: ATR 0.05-0.15% (normal conditions)
        - HIGH_VOL: ATR 0.15-0.50% (fast markets, risky)
        - EXTREME_VOL: ATR > 0.50% (gaps/crashes, skip entries)
        
        Returns: regime string
        """
        if symbol not in self.atr_history or not self.atr_history[symbol]:
            return "MEDIUM_VOL"  # Default
        
        # Use 20-tick average for recent volatility (more responsive)
        recent = self.atr_history[symbol][-20:]
        avg_atr_pct = sum(atr for atr, _ in recent) / len(recent)
        
        if avg_atr_pct < 0.01:
            return "STAGNATION"
        elif avg_atr_pct < 0.05:
            return "LOW_VOL"
        elif avg_atr_pct < 0.15:
            return "MEDIUM_VOL"
        elif avg_atr_pct < 0.50:
            return "HIGH_VOL"
        else:
            return "EXTREME_VOL"
    
    def get_volatility_pct(self, symbol: str) -> float:
        """Get average ATR % for symbol (last 20 ticks)."""
        if symbol not in self.atr_history or not self.atr_history[symbol]:
            return 0.05  # Default 0.05%
        recent = self.atr_history[symbol][-20:]
        return sum(atr for atr, _ in recent) / len(recent)
```

**Thresholds (Empirically Derived):**

| Regime | ATR Range | Market Char | Entry Bias | Risk Profile |
|--------|-----------|-------------|-----------|--------------|
| STAGNATION | <0.01% | Nearly flat, no pips | SKIP | Untradeabl |
| LOW_VOL | 0.01-0.05% | Slow consolidation | Lenient | Need patience|
| MEDIUM_VOL | 0.05-0.15% | Normal conditions | Standard | Baseline |
| HIGH_VOL | 0.15-0.50% | Fast movement | Strict | Risk reversals|
| EXTREME_VOL | >0.50% | Gaps/crashes | SKIP | Too risky |

---

### 1.2 Volatility in Signal Generator

**Integration Point:** `src/services/signal_generator.py:684` (existing `_regime()` call)

Enhance existing regime detection:

```python
def _get_scored_edge(..., volatility_regime=None):
    """
    Incorporate volatility regime into confidence scoring.
    
    Volatility regime affects:
    - Signal threshold adjustment (HIGH_VOL → higher bar)
    - Partial TP multiplier (affects early exit)
    - Position sizing (HIGH_VOL → smaller, STAGNATION → skip)
    """
    if volatility_regime == "STAGNATION":
        # Stagnation: too risky to trade
        return None
    
    if volatility_regime == "EXTREME_VOL":
        # Extreme volatility: skip entries to avoid gaps
        return None
    
    # Score adjustment by volatility
    vol_multiplier = {
        "LOW_VOL": 1.0,      # Standard confidence
        "MEDIUM_VOL": 1.0,   # Baseline
        "HIGH_VOL": 1.2,     # Require 20% higher confidence
    }.get(volatility_regime, 1.0)
    
    # Adjust confidence required
    confidence_adjusted = confidence * vol_multiplier
    
    if confidence_adjusted < CONFIDENCE_THRESHOLD:
        return None
    
    return edge
```

---

## PART 2: ADAPTIVE TIMEOUT ENGINE

### 2.1 Timeout Formula

**Current Implementation:**
- Static: 600s hardcoded in `paper_trade_executor.py:66`
- No volatility or regime adaptation

**Proposed Adaptive Timeout:**

```python
def calculate_adaptive_timeout(
    atr_pct: float,
    regime: str,
    adx: float,
    volatility_regime: str
) -> float:
    """
    Dynamically calculate position timeout based on market conditions.
    
    Formula:
    base_timeout = 600s (median TP-reachable window)
    
    Volatility adjustment:
    - STAGNATION: N/A (skip entries)
    - LOW_VOL: ×2.0 = 1200s (need time for price to move)
    - MEDIUM_VOL: ×1.0 = 600s (baseline)
    - HIGH_VOL: ×0.67 = 400s (close quickly, avoid reversals)
    - EXTREME_VOL: N/A (skip entries)
    
    Trend adjustment (once in position):
    - BULL_TREND (ADX > 40): ×1.2 = follow trends longer
    - BEAR_TREND (ADX > 40): ×1.2 = follow trends longer
    - RANGING (ADX < 25): ×0.8 = close earlier
    
    Maximum cap: 1500s (hard safety limit)
    Minimum floor: 300s (too short, TP unreachable)
    
    Args:
        atr_pct: Current ATR as % of entry price (0.05 = 5%)
        regime: Current market regime (BULL_TREND, RANGING, BEAR_TREND)
        adx: Current ADX value (0-100)
        volatility_regime: Volatility classification
    
    Returns:
        Timeout in seconds
    """
    BASE_TIMEOUT = 600
    
    # 1. Volatility-based scaling
    vol_factor = {
        "STAGNATION": 0.0,      # (skip entries)
        "LOW_VOL": 2.0,         # 1200s
        "MEDIUM_VOL": 1.0,      # 600s
        "HIGH_VOL": 0.67,       # 400s
        "EXTREME_VOL": 0.0,     # (skip entries)
    }.get(volatility_regime, 1.0)
    
    timeout = BASE_TIMEOUT * vol_factor
    
    # 2. Trend adjustment (multiplicative, applied after volatility)
    if regime == "BULL_TREND" and adx > 40:
        timeout *= 1.2  # Extend in strong uptrend
    elif regime == "BEAR_TREND" and adx > 40:
        timeout *= 1.2  # Extend in strong downtrend
    elif regime == "RANGING" and adx < 25:
        timeout *= 0.8  # Shorten in ranging market
    
    # 3. Safety bounds
    timeout = max(300, min(1500, timeout))
    
    return timeout
```

**Timeout Decision Tree:**

```
Input: volatility_regime, regime (ADX-based), ADX value
│
├─ STAGNATION? → Skip entry (return None)
├─ EXTREME_VOL? → Skip entry (return None)
│
├─ LOW_VOL (need time to reach TP)
│  ├─ BULL_TREND? → 1200s × 1.2 = 1440s (cap 1500s)
│  ├─ BEAR_TREND? → 1200s × 1.2 = 1440s (cap 1500s)
│  └─ RANGING? → 1200s × 0.8 = 960s
│
├─ MEDIUM_VOL (baseline)
│  ├─ BULL_TREND? → 600s × 1.2 = 720s
│  ├─ BEAR_TREND? → 600s × 1.2 = 720s
│  └─ RANGING? → 600s × 0.8 = 480s
│
└─ HIGH_VOL (risk reversals, shorten)
   ├─ BULL_TREND? → 400s × 1.2 = 480s
   ├─ BEAR_TREND? → 400s × 1.2 = 480s
   └─ RANGING? → 400s × 0.8 = 320s (floor 300s)
```

### 2.2 Implementation in paper_trade_executor.py

**Location:** `paper_trade_executor.py:66`

Replace:
```python
_MAX_AGE_S = float(os.getenv("PAPER_MAX_POSITION_AGE_S", "600"))
```

With:
```python
# Base timeout (used for non-adaptive baseline)
_BASE_TIMEOUT_S = 600.0

# Adaptive timeout enabled via env flag
_ADAPTIVE_TIMEOUT_ENABLED = os.getenv("ADAPTIVE_TIMEOUT_ENABLED", "true").lower() == "true"

def _get_timeout_for_position(pos: dict) -> float:
    """Get effective timeout for a position, considering market regime."""
    if not _ADAPTIVE_TIMEOUT_ENABLED:
        return _BASE_TIMEOUT_S
    
    # Extract market context from position
    signal = pos.get("signal", {})
    regime = signal.get("regime", "RANGING")  # BULL_TREND, BEAR_TREND, RANGING
    adx = signal.get("adx", 25)
    atr_pct = (signal.get("atr", 0) or 0) / max(pos.get("entry", 1), 1)
    
    # Get volatility regime
    from src.services.volatility_detector import detector
    volatility_regime = detector.get_volatility_regime(pos.get("symbol", ""))
    
    return calculate_adaptive_timeout(atr_pct, regime, adx, volatility_regime)
```

---

## PART 3: ADAPTIVE TP/SL TARGETS

### 3.1 TP/SL Adjustment Matrix

**Current Implementation:**
- Fixed bands: TP 35bps, SL 40bps (from `signal_generator.py` or env vars)
- No volatility-based adjustment
- Cost floor safety: 18bps + margin (documented in memory)

**Proposed Adaptive TP/SL:**

```python
def calculate_adaptive_tp_sl(
    entry_price: float,
    atr: float,
    regime: str,
    volatility_regime: str,
    adx: float = 25
) -> tuple:
    """
    Calculate TP and SL targets adapting to market conditions.
    
    Core constraint: TP must exceed cost floor (18bps) + margin (10bps) = 28bps minimum
    to ensure profitable exits after fees.
    
    Args:
        entry_price: Entry price
        atr: Average True Range
        regime: Market regime (BULL_TREND, BEAR_TREND, RANGING)
        volatility_regime: Volatility classification
        adx: ADX value for trend strength
    
    Returns:
        (tp_pct, sl_pct) - both as decimal (0.0035 = 35bps)
    """
    # Minimum safe values to exceed cost floor
    COST_FLOOR_BPS = 18  # Actual cost
    MARGIN_BPS = 10     # Safety margin above cost
    MIN_TP_BPS = COST_FLOOR_BPS + MARGIN_BPS  # 28bps
    MIN_SL_BPS = 25     # Always at least 25bps
    
    # Base ATR-scaled TP/SL (research-backed)
    # Multiplier 0.5x ATR for TP, 1.0x ATR for SL (typical ranges)
    base_tp_atr_mult = 0.5
    base_sl_atr_mult = 1.0
    
    # ATR as % (floor: 0.3% or calculated)
    atr_pct = atr / max(entry_price, 1)
    
    # --- STEP 1: Base TP/SL from ATR ---
    tp_pct_atr = base_tp_atr_mult * atr_pct
    sl_pct_atr = base_sl_atr_mult * atr_pct
    
    # Ensure minimum basis points
    tp_pct = max(tp_pct_atr, MIN_TP_BPS / 10000)
    sl_pct = max(sl_pct_atr, MIN_SL_BPS / 10000)
    
    # --- STEP 2: Volatility-based adjustment ---
    vol_adjustment = {
        "LOW_VOL": {
            "tp_mult": 1.4,    # 28bps → 39bps (reachable in slow market)
            "sl_mult": 1.0,    # 25bps standard
        },
        "MEDIUM_VOL": {
            "tp_mult": 1.0,    # Baseline
            "sl_mult": 1.0,    # Baseline
        },
        "HIGH_VOL": {
            "tp_mult": 0.8,    # 28bps → 22bps (DANGER: below cost floor!)
            "sl_mult": 1.0,    # Keep SL standard
            # *** OVERRIDE: Don't reduce TP below MIN_TP_BPS ***
        },
    }
    
    adj = vol_adjustment.get(volatility_regime, vol_adjustment["MEDIUM_VOL"])
    tp_pct *= adj["tp_mult"]
    sl_pct *= adj["sl_mult"]
    
    # --- STEP 3: Regime adjustment ---
    if regime == "BULL_TREND" and adx > 40:
        # Strong uptrend: extend TP to capture more
        tp_pct *= 1.1
        sl_pct *= 0.9  # Tighten SL in trending move
    elif regime == "BEAR_TREND" and adx > 40:
        # Strong downtrend: extend TP to capture more
        tp_pct *= 1.1
        sl_pct *= 0.9  # Tighten SL in trending move
    elif regime == "RANGING" and adx < 25:
        # Ranging: take profits faster
        tp_pct *= 0.85
        sl_pct *= 1.1  # Widen SL in ranging (more whipsaws)
    
    # --- STEP 4: Safety enforcement ---
    # Never reduce TP below cost floor + margin
    tp_pct = max(tp_pct, MIN_TP_BPS / 10000)
    # SL always 25bps minimum
    sl_pct = max(sl_pct, MIN_SL_BPS / 10000)
    
    # INVARIANT: TP > SL (sanity check)
    if tp_pct <= sl_pct:
        tp_pct = sl_pct * 1.2  # Force TP > SL
    
    return (tp_pct, sl_pct)
```

**TP/SL Adjustment Matrix (Scenario Breakdown):**

| Scenario | ATR | Regime | TP (bps) | SL (bps) | Rationale |
|----------|-----|--------|----------|----------|-----------|
| STAGNATION + RANGING | <0.01% | - | SKIP | SKIP | Too flat to trade |
| LOW_VOL + RANGING | 0.01-0.05% | RANGING | 39 | 25 | Slow move, need room |
| LOW_VOL + BULL_TREND | 0.01-0.05% | BULL_TREND (ADX>40) | 43 | 23 | Follow uptrend |
| LOW_VOL + BEAR_TREND | 0.01-0.05% | BEAR_TREND (ADX>40) | 43 | 23 | Follow downtrend |
| MEDIUM_VOL + RANGING | 0.05-0.15% | RANGING | 28 | 30 | Balanced baseline |
| MEDIUM_VOL + BULL_TREND | 0.05-0.15% | BULL_TREND (ADX>40) | 31 | 27 | Trend-follow |
| MEDIUM_VOL + BEAR_TREND | 0.05-0.15% | BEAR_TREND (ADX>40) | 31 | 27 | Trend-follow |
| HIGH_VOL + RANGING | 0.15-0.50% | RANGING | 28 | 33 | Risk manage |
| HIGH_VOL + BULL_TREND | 0.15-0.50% | BULL_TREND (ADX>40) | 30 | 24 | Quick profits |
| HIGH_VOL + BEAR_TREND | 0.15-0.50% | BEAR_TREND (ADX>40) | 30 | 24 | Quick profits |
| EXTREME_VOL | >0.50% | - | SKIP | SKIP | Too risky |

**Cost Floor Safety Rule:**
```
INVARIANT: TP_BPS >= 28 (cost floor 18 + margin 10)
INVARIANT: SL_BPS >= 25 (minimum loss tolerance)
INVARIANT: TP_POS > TP_NEG (TP above SL)
```

---

## PART 4: LEARNING SYSTEM ENHANCEMENT

### 4.1 Scenario-Based Learning Buckets

**Current Implementation:**
- Single trade database: `local_learning_storage/learning_database.sqlite`
- No scenario stratification
- Learning optimizes globally, not per-condition

**Proposed Bucket Structure:**

```python
class ScenarioBucket:
    """
    Represents a distinct market condition + parameter combination.
    Learning tracks performance separately per bucket for targeted optimization.
    """
    
    def __init__(self, symbol: str, volatility_regime: str, adx_regime: str):
        self.symbol = symbol
        self.volatility_regime = volatility_regime  # STAGNATION, LOW_VOL, MEDIUM_VOL, HIGH_VOL
        self.adx_regime = adx_regime                 # BULL_TREND, BEARING_TREND, RANGING
        self.bucket_key = f"{symbol}_{volatility_regime}_{adx_regime}"
        
        # Performance tracking
        self.trades = []  # List of (entry_price, exit_price, pnl_pct, timeout_s, tp_bps, sl_bps)
        self.closed_trades = 0
        self.win_count = 0
        self.loss_count = 0
        self.pf = 0.0  # Profit factor
        self.wr = 0.0  # Win rate
        self.avg_hold_s = 0.0
        self.expectancy = 0.0
    
    def add_closed_trade(self, trade: dict):
        """Record a closed trade in this bucket."""
        pnl_pct = trade.get('net_pnl_pct', 0)
        self.trades.append({
            'pnl_pct': pnl_pct,
            'hold_s': trade.get('duration_s', 0),
            'timeout_s': trade.get('timeout_s', 600),
            'tp_bps': trade.get('tp_bps', 35),
            'sl_bps': trade.get('sl_bps', 25),
        })
        
        self.closed_trades += 1
        if pnl_pct > 0:
            self.win_count += 1
        elif pnl_pct < 0:
            self.loss_count += 1
        
        self._recalculate_metrics()
    
    def _recalculate_metrics(self):
        """Recalculate PF, WR, expectancy."""
        if not self.trades:
            return
        
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t['pnl_pct'] > 0)
        losses = max(total - wins, 1)  # Avoid division by zero
        
        self.wr = wins / total
        self.pf = wins / losses if losses > 0 else 1.0
        self.expectancy = sum(t['pnl_pct'] for t in self.trades) / total
        self.avg_hold_s = sum(t['hold_s'] for t in self.trades) / total


class ScenarioLearningManager:
    """
    Manages learning across all scenario buckets.
    Enables per-scenario optimization with cross-bucket aggregation for robustness.
    """
    
    def __init__(self):
        self.buckets = {}  # bucket_key -> ScenarioBucket
        self.global_min_trades_per_bucket = 5  # Don't optimize bucket until N trades
    
    def get_or_create_bucket(self, symbol: str, vol_regime: str, adx_regime: str) -> ScenarioBucket:
        """Get or create bucket for given scenario."""
        key = f"{symbol}_{vol_regime}_{adx_regime}"
        if key not in self.buckets:
            self.buckets[key] = ScenarioBucket(symbol, vol_regime, adx_regime)
        return self.buckets[key]
    
    def record_trade_closed(self, trade: dict):
        """Record closed trade into appropriate bucket."""
        symbol = trade.get('symbol', 'UNKNOWN')
        vol_regime = trade.get('volatility_regime', 'MEDIUM_VOL')
        adx_regime = trade.get('adx_regime', 'RANGING')
        
        bucket = self.get_or_create_bucket(symbol, vol_regime, adx_regime)
        bucket.add_closed_trade(trade)
    
    def get_optimal_params_for_scenario(self, symbol: str, vol_regime: str, adx_regime: str) -> dict:
        """
        Get optimal parameters for a given scenario.
        Falls back to global defaults if bucket has insufficient trades.
        """
        bucket = self.buckets.get(f"{symbol}_{vol_regime}_{adx_regime}")
        
        if not bucket or bucket.closed_trades < self.global_min_trades_per_bucket:
            # Not enough data, use scenario defaults
            return self._get_scenario_defaults(vol_regime, adx_regime)
        
        # Bucket has sufficient data — optimize based on bucket performance
        if bucket.wr > 0.55 and bucket.pf > 1.1:
            # Winning scenario: use current parameters
            best_trade = max(bucket.trades, key=lambda t: t['pnl_pct'])
            return {
                'timeout_s': best_trade['timeout_s'],
                'tp_bps': best_trade['tp_bps'],
                'sl_bps': best_trade['sl_bps'],
                'source': 'bucket_optimal',
            }
        else:
            # Underperforming: revert to defaults or adjust
            return self._get_scenario_defaults(vol_regime, adx_regime)
    
    def _get_scenario_defaults(self, vol_regime: str, adx_regime: str) -> dict:
        """Return default parameters for scenario (from matrix in Part 3)."""
        # This maps to the TP/SL adjustment matrix
        defaults = {
            ("LOW_VOL", "BULL_TREND"): {"timeout_s": 1440, "tp_bps": 43, "sl_bps": 23},
            ("LOW_VOL", "BEAR_TREND"): {"timeout_s": 1440, "tp_bps": 43, "sl_bps": 23},
            ("LOW_VOL", "RANGING"): {"timeout_s": 960, "tp_bps": 39, "sl_bps": 25},
            ("MEDIUM_VOL", "BULL_TREND"): {"timeout_s": 720, "tp_bps": 31, "sl_bps": 27},
            ("MEDIUM_VOL", "BEAR_TREND"): {"timeout_s": 720, "tp_bps": 31, "sl_bps": 27},
            ("MEDIUM_VOL", "RANGING"): {"timeout_s": 480, "tp_bps": 28, "sl_bps": 30},
            ("HIGH_VOL", "BULL_TREND"): {"timeout_s": 480, "tp_bps": 30, "sl_bps": 24},
            ("HIGH_VOL", "BEAR_TREND"): {"timeout_s": 480, "tp_bps": 30, "sl_bps": 24},
            ("HIGH_VOL", "RANGING"): {"timeout_s": 320, "tp_bps": 28, "sl_bps": 33},
        }
        return defaults.get((vol_regime, adx_regime), {"timeout_s": 600, "tp_bps": 35, "sl_bps": 25})
```

### 4.2 Learning Data Collection

**Integration Point:** `paper_trade_executor.py` at trade close

Add fields to every closed trade record:

```python
def _enhance_trade_record_with_scenario(closed_trade: dict, pos: dict) -> dict:
    """Augment trade record with scenario metadata for learning."""
    signal = pos.get("signal", {})
    
    # Volatility regime
    from src.services.volatility_detector import detector
    vol_regime = detector.get_volatility_regime(pos.get("symbol", ""))
    
    # ADX regime (BULL_TREND, BEAR_TREND, RANGING)
    adx = signal.get("adx", 25)
    regime = signal.get("regime", "RANGING")
    
    # Determine ADX regime strength
    if regime == "BULL_TREND" and adx > 40:
        adx_regime = "BULL_TREND"
    elif regime == "BEAR_TREND" and adx > 40:
        adx_regime = "BEAR_TREND"
    else:
        adx_regime = "RANGING"
    
    # Add scenario fields
    closed_trade["volatility_regime"] = vol_regime
    closed_trade["adx_regime"] = adx_regime
    closed_trade["adx_value"] = adx
    closed_trade["atr_pct"] = (signal.get("atr", 0) or 0) / max(pos.get("entry", 1), 1)
    closed_trade["timeout_s"] = pos.get("timeout_s", 600)
    closed_trade["tp_bps"] = int((pos.get("tp", 0) - pos.get("entry", 0)) / max(pos.get("entry", 0), 1) * 10000)
    closed_trade["sl_bps"] = int((pos.get("entry", 0) - pos.get("sl", 0)) / max(pos.get("entry", 0), 1) * 10000)
    
    return closed_trade
```

**Database Schema Enhancement:**

```sql
-- Add scenario columns to trades table
ALTER TABLE trades ADD COLUMN volatility_regime TEXT DEFAULT 'MEDIUM_VOL';
ALTER TABLE trades ADD COLUMN adx_regime TEXT DEFAULT 'RANGING';
ALTER TABLE trades ADD COLUMN adx_value REAL DEFAULT 25.0;
ALTER TABLE trades ADD COLUMN atr_pct REAL DEFAULT 0.05;
ALTER TABLE trades ADD COLUMN timeout_s INTEGER DEFAULT 600;
ALTER TABLE trades ADD COLUMN tp_bps INTEGER DEFAULT 35;
ALTER TABLE trades ADD COLUMN sl_bps INTEGER DEFAULT 25;

-- Create scenario performance view
CREATE VIEW scenario_performance AS
SELECT 
    volatility_regime,
    adx_regime,
    COUNT(*) as closed_trades,
    SUM(CASE WHEN net_pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
    AVG(net_pnl_pct) as avg_pnl_pct,
    AVG(CASE WHEN net_pnl_pct > 0 THEN net_pnl_pct ELSE NULL END) as avg_win_pct,
    AVG(CASE WHEN net_pnl_pct <= 0 THEN net_pnl_pct ELSE NULL END) as avg_loss_pct,
    AVG(hold_s) as avg_hold_s
FROM trades
WHERE mode = 'PAPER'
GROUP BY volatility_regime, adx_regime;
```

---

## PART 5: ENTRY/EXIT REGIME LOGIC ENHANCEMENTS

### 5.1 Entry Gate Enhancements

**Current Implementation:**
- `signal_generator.py`: Single P0 EV gate, no volatility/regime awareness

**Proposed Enhancement:**

```python
def should_enter_position(signal: dict, volatility_regime: str, adx_regime: str) -> bool:
    """
    Enhanced entry gate: reject entries in certain volatility + regime combinations.
    """
    # Rule 1: Never enter during STAGNATION or EXTREME_VOL
    if volatility_regime in ("STAGNATION", "EXTREME_VOL"):
        return False  # Skip
    
    # Rule 2: In LOW_VOL, only enter trending markets (avoid ranging)
    if volatility_regime == "LOW_VOL" and adx_regime == "RANGING":
        return False  # Skip low-vol ranging (TP unreachable)
    
    # Rule 3: In HIGH_VOL, require higher confidence
    if volatility_regime == "HIGH_VOL":
        min_confidence = signal.get("confidence", 0)
        if min_confidence < 0.65:  # Raise bar to 65% vs baseline 50%
            return False
    
    # Rule 4: Standard EV gate (existing logic)
    ev = signal.get("edge_value", 0)
    if ev < 0.01:
        return False
    
    return True
```

### 5.2 Position Sizing by Scenario

**Current Implementation:**
- Fixed base size (PAPER_POSITION_SIZE_USD = $25)
- EV-based scaling (1.5–3.0×)

**Proposed Enhancement:**

```python
def calculate_position_size_adaptive(
    base_size: float,
    ev: float,
    volatility_regime: str,
    adx: float,
    regime: str
) -> float:
    """
    Adjust position size based on market scenario.
    
    Principle: Risk less in uncertain/volatile conditions.
    """
    # Base EV scaling (existing)
    ev_factor = max(0.5, min(3.0, ev * 6))  # 0.5–3.0×
    size = base_size * ev_factor
    
    # Volatility adjustment
    vol_factor = {
        "LOW_VOL": 1.2,       # Can be more aggressive (slower market)
        "MEDIUM_VOL": 1.0,    # Baseline
        "HIGH_VOL": 0.7,      # De-risk (fast moves, more slippage)
    }.get(volatility_regime, 1.0)
    
    size *= vol_factor
    
    # Regime adjustment
    if regime == "RANGING" and adx < 25:
        size *= 0.85  # Reduce in ranging (more whipsaws)
    
    return size
```

### 5.3 Partial TP & Smart Exit Adaptation

**Current Implementation:**
- Partial TP at 1.5× ATR (fixed, `trade_executor.py:3194`)
- Smart exit engine (independent)

**Proposed Enhancement:**

```python
def get_partial_tp_threshold(
    atr_pct: float,
    volatility_regime: str,
    regime: str
) -> float:
    """
    Determine partial TP trigger based on scenario.
    
    LOW_VOL: Fire later (1.5× ATR)  — wait for move to develop
    MEDIUM_VOL: Standard (1.2× ATR)
    HIGH_VOL: Fire earlier (0.8× ATR) — take profits before reversal
    RANGING: Fire early (0.7× ATR) — mean reversion risk
    """
    base_mult = 1.2  # baseline
    
    vol_mult = {
        "LOW_VOL": 1.5,      # 1.5× ATR
        "MEDIUM_VOL": 1.2,   # 1.2× ATR
        "HIGH_VOL": 0.8,     # 0.8× ATR
    }.get(volatility_regime, 1.2)
    
    if regime == "RANGING":
        vol_mult *= 0.7  # Even earlier in ranging
    
    return vol_mult * atr_pct
```

---

## PART 6: IMPLEMENTATION PHASES

### Phase 1: Volatility Detection & Adaptive Timeout (WEEKS 1-2)

**Deliverables:**
1. `src/services/volatility_detector.py` — Real-time ATR-based regime classification
2. Modify `paper_trade_executor.py:66` — Replace static timeout with adaptive calculation
3. Modify `signal_generator.py` — Inject volatility regime into P0 gate
4. Add env var: `ADAPTIVE_TIMEOUT_ENABLED` (default: true)
5. Test: 50 paper trades across different volatility regimes, verify timeout varies

**Expected Outcome:**
- Low-vol trades get 1200s (vs hardcoded 600s) → TP reachable
- High-vol trades get 400s (vs hardcoded 600s) → avoid reversals
- STAGNATION/EXTREME_VOL skipped → no false entries
- **Metric:** WR improves 48.7% → 52%+ in low-vol, maintains 52%+ baseline

**Risk Mitigations:**
- Hardcoded fallback: If `ADAPTIVE_TIMEOUT_ENABLED=false`, use static 600s
- Bounds check: Always min 300s, max 1500s
- Logging: `[ADAPTIVE_TIMEOUT]` on every position open (verify correctness)

---

### Phase 2: Adaptive TP/SL Targets (WEEKS 3-4)

**Deliverables:**
1. `calculate_adaptive_tp_sl()` function (reference Part 3.1)
2. Modify `paper_trade_executor.py:open_paper_position()` — Calculate TP/SL per scenario
3. Add env var: `ADAPTIVE_TP_SL_ENABLED` (default: true)
4. Enhanced SQLite schema — Add `tp_bps`, `sl_bps`, scenario fields
5. Test: Verify TP/SL bands by scenario match matrix, cost floor always met

**Expected Outcome:**
- LOW_VOL positions: TP 39–43bps (vs baseline 35bps) → TP more reachable
- HIGH_VOL positions: TP 28–30bps (vs baseline 35bps) → risk-managed, TP still reachable
- Cost floor invariant ALWAYS enforced (TP ≥ 28bps)
- SL always ≥ 25bps
- **Metric:** TIMEOUT exit rate drops below 20% (vs historical high), more TP exits

**Risk Mitigations:**
- Cost floor hardwired: `tp_bps >= 28` always enforced
- Sanity check: `tp_pct > sl_pct` always verified
- Logging: `[ADAPTIVE_TP_SL]` on position open (human-verifiable)
- Regression test: Run 200 trades with ADAPTIVE_TP_SL_ENABLED=false, verify identical to Phase 1 baseline

---

### Phase 3: Learning System Bucketing (WEEKS 5-6)

**Deliverables:**
1. `ScenarioLearningManager` class (reference Part 4)
2. Modify `paper_trade_executor.py` close handler — Enhance trade record with `volatility_regime`, `adx_regime`, `timeout_s`, `tp_bps`, `sl_bps`
3. SQLite schema: Add scenario columns + scenario_performance view
4. `learning_optimizer.py` — Add scenario-aware optimization (per-bucket performance tracking)
5. Test: Verify all closed trades recorded with scenario metadata, bucket aggregation works

**Expected Outcome:**
- Every trade tagged with scenario (symbol, vol_regime, adx_regime)
- Bucket analysis: "ETHUSDT_LOW_VOL_BULL_TREND": 15 trades, WR 60%, PF 1.2
- Scenario defaults applied correctly (matrix from Part 3)
- Learning identifies best-performing scenarios (e.g., "ETHUSDT_LOW_VOL_BULL_TREND wins 60%, avoid BTCUSDT_HIGH_VOL_RANGING")
- **Metric:** Provides data foundation for Phase 4 optimization

**Risk Mitigations:**
- Backward compat: Old trades without scenario fields treated as "MEDIUM_VOL_RANGING"
- No parameter changes in Phase 3, only data collection
- Logging: `[SCENARIO_BUCKET]` on every trade close (audit trail)

---

### Phase 4: Autonomous Per-Scenario Optimization (WEEKS 7-8)

**Deliverables:**
1. `scenario_optimizer.py` — Reads scenario buckets, recommends parameter adjustments
2. Auto-tuning loop: Every 50 trades per scenario, re-evaluate TP/SL/timeout
3. Conservative thresholds: Only apply recommendation if bucket WR > 55% AND PF > 1.05
4. `learning_optimizer.py` enhancement — Call scenario optimization alongside global optimization
5. Test: Run autonomous loop with dummy markets, verify parameter drift is conservative

**Expected Outcome:**
- Example: Bucket "ETHUSDT_LOW_VOL_BULL_TREND" WR improves 58% → 62% after 50 trades
  - System recommends: "Increase timeout 1440s → 1600s (capped 1500s), keep TP/SL"
  - Recommendation REVIEWED before apply (safety gate)
- Prevents parameter thrashing (only apply if statistical significance)
- **Metric:** WR per scenario improves to target >55% across all active scenarios within 200–300 trades

**Risk Mitigations:**
- Recommendations logged but NOT auto-applied without approval gate
- Min trades threshold: 50+ trades per bucket before optimization
- Statistical significance: Only recommend if WR change > 10% OR PF change > 0.15
- Reversion: If optimized params degrade WR > 5%, revert to defaults

---

### Phase 5: Autonomous Deployment & Monitoring (WEEKS 9-10)

**Integration:** Wire Phase 4 optimizer into `autonomous-monitoring-loop` skill

**Deliverables:**
1. Monitoring loop polls scenario performance every 30 min (existing heartbeat)
2. Per-scenario metrics: (vol_regime, adx_regime, symbol) → WR, PF, expectancy
3. Alert: If any scenario WR < 45% for 3 consecutive cycles, trigger diagnosis
4. Auto-remedy: If diagnosis recommends parameter adjustment, apply → deploy → verify
5. Feedback: Update `_workspace/monitoring_progress.json` with per-scenario status

**Expected Outcome:**
- Real-time monitoring: Dashboard shows breakdown by scenario (not just global)
- Autonomous response: Low-vol scenario degrades → system auto-adjusts timeout/TP/SL → redeploys
- Safety gates: Each change reviewed, reverts on 2-cycle failure
- **Metric:** Bot continuously maintains WR > 50% + P&L > 0% across all scenarios without manual intervention

**Risk Mitigations:**
- Manual override: User can disable any scenario (e.g., "skip ETHUSDT_HIGH_VOL")
- Circuit breaker: If 3+ deployments fail in 1 hour, lock and alert human
- Audit log: Every parameter change logged to `parameter_history.json`

---

## PART 7: SAFETY GUARDRAILS

### 7.1 Volatility Guardrails

```
Rule 1: STAGNATION (ATR < 0.01%)
  → SKIP all entries
  → Reason: Price movement too small to overcome fees

Rule 2: EXTREME_VOL (ATR > 0.50%)
  → SKIP all entries
  → Reason: Gap risk too high, model breaks down
  → Monitoring: Alert if gap > 5% observed

Rule 3: Volatility regime change mid-position
  → Check every tick
  → If regime changes, recalculate effective timeout
  → Example: Position opened in LOW_VOL (1200s timeout)
    If market shifts to HIGH_VOL, timeout reduces to 400s
  → Logging: [VOL_REGIME_CHANGE] on transition
```

### 7.2 Cost Floor Guardrails

```
Rule 4: Cost Floor Invariant
  INVARIANT: TP_BPS >= 28 (18 cost + 10 margin)
  INVARIANT: SL_BPS >= 25 (loss tolerance floor)
  INVARIANT: TP_POS > TP_NEG (TP above SL)
  
  Enforcement: Pre-flight check before position open
  - Calculate TP/SL
  - Verify TP >= 28bps
  - If fails: SKIP entry with log [COST_FLOOR_VIOLATION]

Rule 5: Timeout Bounds
  MIN: 300s (too short = TP unreachable)
  MAX: 1500s (too long = overnight risk, state corruption)
  
  Enforcement: Before position open
  if timeout < 300: timeout = 300
  if timeout > 1500: timeout = 1500
  log: [TIMEOUT_BOUNDS_ENFORCED]
```

### 7.3 Learning Stability Guardrails

```
Rule 6: Minimum bucket size before optimization
  - Never recommend parameter change for bucket with < 50 trades
  - Prevents overfitting on noise

Rule 7: Parameter drift limits
  - Timeout change: max ±30% per optimization cycle
  - TP change: max ±5bps per cycle
  - SL change: max ±5bps per cycle
  - Prevents whiplash (e.g., 600s → 1800s in one jump)

Rule 8: Statistical significance threshold
  - Only apply recommendation if:
    (new_wr - old_wr) > 0.10  (10% WR improvement)
    OR (new_pf - old_pf) > 0.15  (15% PF improvement)
  - Logging: [PARAM_CHANGE_RECOMMENDATION] (approve/reject)

Rule 9: Reversion safety
  - Track last 3 optimizations per bucket
  - If latest WR < previous WR - 0.05: revert
  - Log: [PARAM_REVERSION] reason=stability
```

### 7.4 Deployment Guardrails

```
Rule 10: Atomic parameter deployment
  - All parameter changes bundled into single commit
  - Deploy only if:
    (a) All tests pass (pytest suite)
    (b) Dry run on paper trading succeeds (2-min health check)
    (c) Reviewer approves (safety gate)
  - Rollback: If 3+ TIMEOUT exits in first 5 trades, auto-revert

Rule 11: Monitoring continuity
  - If parameter change deployed, resume monitoring 10x frequency (every 3 min vs 30 min)
    for 1 hour, then revert to normal cadence
  - Catch regressions early

Rule 12: Multi-parameter safety
  - Never change TP + timeout + SL simultaneously
  - Change only 1 parameter per cycle
  - Reason: Isolate impact, easier to debug failures
```

---

## PART 8: SUCCESS CRITERIA & METRICS

### 8.1 Phase-Wise Success Criteria

| Phase | Timeline | Metric | Target | Gating |
|-------|----------|--------|--------|--------|
| 1 (Vol+Timeout) | Week 2 | Low-vol WR; STAGNATION skip rate | 52%+ WR; 100% stagnation skip | Proceed if YES |
| 2 (TP/SL) | Week 4 | TIMEOUT exit rate; cost floor violations | <20% TIMEOUT; 0 violations | Proceed if YES |
| 3 (Bucketing) | Week 6 | Data completeness; scenario coverage | All trades tagged; 10+ buckets active | Proceed if YES |
| 4 (Scenario Opt) | Week 8 | Per-scenario WR stability | Top 3 scenarios WR > 55% | Proceed if YES |
| 5 (Autonomous) | Week 10 | Sustained WR > 50% + P&L > 0% | 10+ cycles with goal met | **EXIT = SUCCESS** |

### 8.2 Real-Time Monitoring Metrics

Dashboard displays (update every 30 min):

**Global:**
- Win Rate (%) — Target > 50%
- Profit Factor — Target > 1.05
- P&L (USD) — Target > 0
- Open positions (count)

**By Volatility Regime:**
- STAGNATION: Entry count (target = 0), skip rate (target = 100%)
- LOW_VOL: Trade count, WR, PF, avg timeout used
- MEDIUM_VOL: Trade count, WR, PF, avg timeout used (baseline)
- HIGH_VOL: Trade count, WR, PF, avg timeout used, risk-adjust effectiveness

**By Scenario Bucket (Top 5 Active):**
- Bucket key (e.g., ETHUSDT_LOW_VOL_BULL_TREND)
- Closed trades in bucket, WR, PF, expectancy
- Last trade time, next expected action

**Learning Status:**
- Scenario optimization cycles completed
- Parameter recommendations pending (with approval status)
- Last auto-deployment timestamp + result (PASS/FAIL/REVERTED)

---

## PART 9: REGRESSION PREVENTION

### 9.1 Test Coverage

**Unit Tests:**

```python
# tests/test_volatility_detector.py
def test_volatility_regime_classification():
    """Verify regime boundaries: STAGNATION < 0.01%, etc."""
    detector = VolatilityDetector()
    detector.add_atr("TEST", 0.005, time.time())  # < 0.01%
    assert detector.get_volatility_regime("TEST") == "STAGNATION"
    
    detector.add_atr("TEST", 0.03, time.time())  # 0.01%-0.05%
    assert detector.get_volatility_regime("TEST") == "LOW_VOL"

# tests/test_adaptive_timeout.py
def test_timeout_formula():
    """Verify timeout calculation respects bounds and formula."""
    # LOW_VOL + BULL_TREND: 1200 * 1.2 = 1440s (capped at 1500s)
    timeout = calculate_adaptive_timeout(0.03, "BULL_TREND", 45, "LOW_VOL")
    assert 1400 <= timeout <= 1500
    
    # HIGH_VOL + RANGING: 400 * 0.8 = 320s (floored at 300s)
    timeout = calculate_adaptive_timeout(0.25, "RANGING", 20, "HIGH_VOL")
    assert 300 <= timeout <= 320

# tests/test_adaptive_tp_sl.py
def test_cost_floor_invariant():
    """Verify TP >= 28bps always."""
    for vol_regime in ["LOW_VOL", "MEDIUM_VOL", "HIGH_VOL"]:
        tp_pct, sl_pct = calculate_adaptive_tp_sl(100, 50, "RANGING", vol_regime)
        assert tp_pct >= 0.0028, f"TP {tp_pct:.4f} < 28bps in {vol_regime}"
```

**Integration Tests:**

```python
# tests/test_scenario_learning.py
def test_scenario_bucketing():
    """Verify trades assigned to correct bucket."""
    manager = ScenarioLearningManager()
    
    trade = {
        'symbol': 'ETHUSDT',
        'volatility_regime': 'LOW_VOL',
        'adx_regime': 'BULL_TREND',
        'net_pnl_pct': 0.002,
    }
    manager.record_trade_closed(trade)
    
    bucket = manager.buckets["ETHUSDT_LOW_VOL_BULL_TREND"]
    assert bucket.closed_trades == 1
    assert bucket.wr > 0  # Win registered
```

### 9.2 Paper Trading Regression Suite

**Before Phase 1 Deploy:**
- Run 100 trades with ADAPTIVE_TIMEOUT_ENABLED=false → baseline metrics (e.g., WR 52%, PF 1.12)
- Run 100 trades with ADAPTIVE_TIMEOUT_ENABLED=true → verify delta ≤ ±2% WR (no major regression)

**Before Phase 2 Deploy:**
- Run 100 trades with both ADAPTIVE_TIMEOUT_ENABLED=true, ADAPTIVE_TP_SL_ENABLED=false
- Run 100 trades with both enabled
- Verify no regression vs Phase 1

**Before Phase 5 Deploy:**
- Run 200 trades with autonomous optimization DISABLED
- Run 200 trades with optimization ENABLED
- Verify cost floor invariant: 0 violations

---

## PART 10: FILE STRUCTURE & IMPLEMENTATION CHECKLIST

### New Files to Create

```
src/services/volatility_detector.py          (Phase 1)
src/services/scenario_learning_manager.py    (Phase 3)
src/services/scenario_optimizer.py           (Phase 4)
tests/test_volatility_detector.py            (Phase 1)
tests/test_adaptive_timeout.py               (Phase 1)
tests/test_adaptive_tp_sl.py                 (Phase 2)
tests/test_scenario_learning.py              (Phase 3)
scripts/analyze_scenario_performance.py      (Phase 3+)
ADAPTIVE_SYSTEM_OPERATIONS.md                (Phase 5)
```

### Files to Modify

```
src/services/paper_trade_executor.py
  - Line 66: Replace _MAX_AGE_S with adaptive calculation
  - close handler: Enhance trade record with scenario metadata
  
src/services/signal_generator.py
  - Integrate volatility_detector
  - Enhance P0 gate with vol/regime checks
  
src/services/learning_optimizer.py
  - Add scenario_learning_manager integration
  - Implement per-scenario optimization
  
local_learning_storage/learning_database.sqlite
  - Add scenario columns to trades table
  - Create scenario_performance view
  
.env or override.conf
  - Add ADAPTIVE_TIMEOUT_ENABLED=true
  - Add ADAPTIVE_TP_SL_ENABLED=true
```

### Implementation Checklist

- [ ] **Phase 1 Start**
  - [ ] Create volatility_detector.py
  - [ ] Integrate detector into signal_generator.py
  - [ ] Modify paper_trade_executor.py timeout calculation
  - [ ] Add env var ADAPTIVE_TIMEOUT_ENABLED
  - [ ] Write unit tests (test_volatility_detector.py, test_adaptive_timeout.py)
  - [ ] Run 100-trade paper regression: baseline vs adaptive
  - [ ] Document findings in monitoring_progress.json

- [ ] **Phase 2 Start**
  - [ ] Implement calculate_adaptive_tp_sl() function
  - [ ] Modify paper_trade_executor.py open_paper_position()
  - [ ] Add env var ADAPTIVE_TP_SL_ENABLED
  - [ ] Write unit tests (test_adaptive_tp_sl.py)
  - [ ] Verify cost floor invariant in all tests
  - [ ] Run 100-trade paper regression
  - [ ] Document findings

- [ ] **Phase 3 Start**
  - [ ] Create ScenarioLearningManager class
  - [ ] Enhance trade records with scenario metadata
  - [ ] Add SQLite schema columns
  - [ ] Create scenario_performance view
  - [ ] Write integration tests
  - [ ] Run data validation on 50+ trades
  - [ ] Verify all trades tagged correctly

- [ ] **Phase 4 Start**
  - [ ] Create scenario_optimizer.py
  - [ ] Integrate with learning_optimizer.py
  - [ ] Implement per-bucket WR/PF tracking
  - [ ] Write recommendation logic (threshold: WR > 55% AND PF > 1.05)
  - [ ] Test with mock buckets
  - [ ] Run autonomous loop simulation (200 dummy trades)

- [ ] **Phase 5 Start**
  - [ ] Wire scenario optimizer into autonomous-monitoring-loop
  - [ ] Add per-scenario metrics to monitoring dashboard
  - [ ] Implement approval gate for recommendations
  - [ ] Test: 10 monitoring cycles with goal met
  - [ ] Document operations guide (ADAPTIVE_SYSTEM_OPERATIONS.md)
  - [ ] Deploy to production (Hetzner)

---

## PART 11: CRITICAL INVARIANTS (MUST NEVER VIOLATE)

```
1. COST_FLOOR_INVARIANT
   TP_BPS >= 28 (cost_floor 18 + margin 10)
   → Enforced in calculate_adaptive_tp_sl() pre-flight
   → Logged [COST_FLOOR_CHECK] on every position open
   → Violation → SKIP entry

2. TP_SL_INVARIANT
   TP_POS > TP_NEG (TP above SL)
   → Sanity check in calculate_adaptive_tp_sl()
   → Violation → Force TP = SL * 1.2

3. TIMEOUT_BOUNDS_INVARIANT
   300s <= timeout <= 1500s
   → Enforced in calculate_adaptive_timeout()
   → Violation → Clamp to bounds
   → Logged [TIMEOUT_BOUNDS_ENFORCED]

4. VOLATILITY_REGIME_INVARIANT
   If volatility_regime in (STAGNATION, EXTREME_VOL)
   → Skip entry
   → Enforce in signal_generator P0 gate
   → Logged [VOL_REGIME_GATE] SKIP

5. LEARNING_DATA_INTEGRITY
   Every closed trade must record:
   - volatility_regime (default MEDIUM_VOL if missing)
   - adx_regime (default RANGING if missing)
   - timeout_s (position's actual timeout)
   - tp_bps, sl_bps (position's actual targets)
   → Enforced in _enhance_trade_record_with_scenario()
   → Logged [TRADE_RECORD_ENHANCED]

6. NO_MULTI_PARAM_CHANGE
   In per-scenario optimization, never change > 1 parameter per cycle
   → Implementation: scenario_optimizer.py enforces one-param-per-recommendation
   → Logged [PARAM_CHANGE_SINGLE]
```

---

## PART 12: ROLLBACK PROCEDURES

### If Phase Fails Safety Gates

**Phase 1 (Volatility+Timeout):**
- Set ADAPTIVE_TIMEOUT_ENABLED=false
- Revert to static 600s timeout
- Loss: None (contained to timing)

**Phase 2 (TP/SL):**
- Set ADAPTIVE_TP_SL_ENABLED=false
- Revert to static TP 35bps, SL 25bps
- Loss: None (contained to target sizes)

**Phase 3 (Bucketing):**
- SQLite data remains (non-destructive)
- Delete scenario columns if disk space critical
- Loss: Bucket analysis data (re-create on Phase 3 retry)

**Phase 4 (Scenario Optimization):**
- Disable scenario_optimizer in learning_optimizer.py
- Revert to global optimization (Phase 3 baseline)
- Loss: Per-bucket parameter tuning (use scenario defaults)

**Phase 5 (Autonomous Deploy):**
- Manually disable autonomous-monitoring-loop
- Continue manual monitoring
- Loss: Autonomy (user intervenes)

---

## CONCLUSION

This comprehensive design provides:

1. **Real-time market adaptation** — Timeout, TP/SL, entry gates adjust to conditions
2. **Evidence-based learning** — Per-scenario performance tracking enables targeted optimization
3. **Safety-first approach** — Cost floor invariant always enforced, multiple guardrails prevent parameter thrashing
4. **Phased rollout** — 5 phases, each adds capability, each can rollback independently
5. **Monitoring & autonomy** — Real-time metrics per scenario, autonomous optimization with safety gates

**Expected Impact:**
- **Low-vol scenarios:** WR 48.7% → 55%+ (longer timeout, higher TP targets reachable)
- **Baseline (medium-vol):** WR 52.8% → 55%+ (maintained, slight improvement from regime awareness)
- **High-vol scenarios:** WR ?% → 50%+ (shorter timeout, risk-managed TP/SL)
- **Global:** WR > 50% + P&L > 0% sustained across all scenarios

**Timeline:** 10 weeks (2.5 months) to full autonomy

---

**Document prepared for implementation review and safety gate approval.**

**Next Step:** Invoke `evidence-based-patch-orchestrator` or `master-goal-orchestrator` skill to begin Phase 1.
