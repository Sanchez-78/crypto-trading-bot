"""
Clean Core RESET R1: Futures execution-truth foundation for CryptoMaster.

This package provides isolated models for:
- Futures market data sourcing (fstream.binance.com only)
- Local order book integrity (sequence validation)
- Deterministic PAPER fill/fee/funding accounting
- Clean epoch/eligibility/journal provenance
- Isolated PAPER position lifecycle

Non-negotiable constraints:
- No legacy EV/PF/RDE gates
- No Spot market data
- No strategy/admission logic
- No Firebase/live socket connections
- No service wiring (separate from active bot)
- All tests use fixtures only, no network calls
"""
