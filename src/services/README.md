# Service Layer: Components & Logic

The `src/services` directory contains the core functional blocks of the trading engine. Each service is designed to be as modular as possible, communicating primarily through the `event_bus` or direct dependency injection.

## 1. Data Ingestion & Feeds
Handles raw connectivity to exchanges and price preparation.
- **[market_stream.py](file:///c:/Projects/CryptoMaster_srv/src/services/market_stream.py)**: Combined WebSocket stream for bookTickers and L2 depth.
- **[binance_client.py](file:///c:/Projects/CryptoMaster_srv/src/services/binance_client.py)**: REST API client for orders and account data.
- **[price_feed.py](file:///c:/Projects/CryptoMaster_srv/src/services/price_feed.py)**: Normalized price aggregator.

## 2. Signal Generation & Intelligence
The "Sensors" and "Brain" of the bot.
- **[signal_engine.py](file:///c:/Projects/CryptoMaster_srv/src/services/signal_engine.py)**: Orchestrates the pipeline from raw tick to actionable signal.
- **[feature_extractor.py](file:///c:/Projects/CryptoMaster_srv/src/services/feature_extractor.py)**: Transforms price action into multi-dimensional vectors.
- **[regime_predictor.py](file:///c:/Projects/CryptoMaster_srv/src/services/regime_predictor.py)**: Classifies market state (BULL, BEAR, RANGING).
- **[lstm_model.py](file:///c:/Projects/CryptoMaster_srv/src/services/lstm_model.py)**: Online-learning neural network for price prediction.

## 3. Decision & Execution
The "Drivers" that commit capital.
- **[realtime_decision_engine.py](file:///c:/Projects/CryptoMaster_srv/src/services/realtime_decision_engine.py)**: Applies Bayesian calibration and win-rate gating to raw signals.
- **[trade_executor.py](file:///c:/Projects/CryptoMaster_srv/src/services/trade_executor.py)**: Manages the lifecycle of a position (Open -> SL/TP/Timeout -> Close).
- **[execution_engine.py](file:///c:/Projects/CryptoMaster_srv/src/services/execution_engine.py)**: Low-level order placement and reconciliation.

## 4. Risk & Protection
Safety layers to prevent catastrophic loss.
- **[risk_engine.py](file:///c:/Projects/CryptoMaster_srv/src/services/risk_engine.py)**: Calculates position sizing and portfolio limits.
- **[correlation_shield.py](file:///c:/Projects/CryptoMaster_srv/src/services/correlation_shield.py)**: Prevents over-exposure to correlated assets.
- **[macro_guard.py](file:///c:/Projects/CryptoMaster_srv/src/services/macro_guard.py)**: Broad-market trend filtering.

## 5. Persistence & Observability
System state and reporting.
- **[firebase_client.py](file:///c:/Projects/CryptoMaster_srv/src/services/firebase_client.py)**: Interface for Firestore trade logging and metrics.
- **[state_manager.py](file:///c:/Projects/CryptoMaster_srv/src/services/state_manager.py)**: Redis-backed state synchronization for cold starts.
- **[learning_monitor.py](file:///c:/Projects/CryptoMaster_srv/src/services/learning_monitor.py)**: Real-time health monitoring and convergence tracking.
- **[dashboard_live.py](file:///c:/Projects/CryptoMaster_srv/src/services/dashboard_live.py)**: Logic for the ANSI-colored terminal dashboard.

---

## Service Interactions

```
[ market_stream ] ──Tick──> [ signal_engine ] ──Signal──> [ decision_engine ]
                                                                  │
                                                               Verification
                                                                  │
                                                                  ▼
[ trade_executor ] <──Apply Risk── [ risk_engine ] <───── [ Signal Verified ]
       │
       └─────> [ firebase_client ] (Audit Trace)
       └─────> [ learning_monitor ] (Update Edge)
```
