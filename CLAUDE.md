# PROJECT: HF-Quant 5.0 (Stabilized)

## ROLE
Senior Python Engineer focused on high-frequency algorithmic trading.

## RULES
- Do NOT overengineer.
- Keep modules small and clear. Stateless wherever possible.
- Always use standard `event_bus` for cross-component signaling.
- Maintain persistent learning state via `firebase_client`.

## MASTER DOCUMENTATION
For detailed context, logic, and architecture, refer to:
- [ARCHITECTURE.md](file:///c:/Projects/CryptoMaster_srv/ARCHITECTURE.md) (High-level design & Data flow)
- [src/services/README.md](file:///c:/Projects/CryptoMaster_srv/src/services/README.md) (Service layer map)
- [src/services/LOGIC.md](file:///c:/Projects/CryptoMaster_srv/src/services/LOGIC.md) (Mathematical models & Calibration)
- [bot2/README.md](file:///c:/Projects/CryptoMaster_srv/bot2/README.md) (Runtime orchestration & Auditor)

## CORE ARCHITECTURE
- **Ingestion**: `market_stream.py` (WebSocket) -> `event_bus.py`.
- **Decision Engine**: `realtime_decision_engine.py` (Bayesian calibration + EV Gating).
- **Execution**: `trade_executor.py` (Position lifecycle) -> `risk_engine.py`.
- **State**: Firestore (Trades/Metrics) + Redis (Hydration).

## WORKFLOW
- One module = one focused responsibility.
- Use `logging` for critical state changes; avoid `print` spam in production.
- If logic is complex → Document in [LOGIC.md](file:///c:/Projects/CryptoMaster_srv/src/services/LOGIC.md).

## DATA FLOW
fetch → event_bus → signal_engine → calibrated_ev → risk_filter → execute → learn
