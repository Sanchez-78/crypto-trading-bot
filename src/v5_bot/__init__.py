"""V5 Integrated PAPER Trading Bot with Firebase Durable State & Hard Quota Guard.

This is a complete new PAPER trading implementation isolated from legacy services.
It does NOT import from src.services.* or use legacy learning state.

Core responsibilities:
  - Single integrated lifecycle: market → signal → entry/close → learning → Firebase
  - Firestore as durable source of truth
  - Hard quota enforcement (3,000 writes/day hard cap)
  - Complete metrics visibility for operator review
  - Deterministic REAL readiness evaluator (but REAL stays disabled)
  - Strict learning eligibility (cost edge must be positive)
"""

__version__ = "5.0"
__author__ = "CryptoMaster V5 Team"

# Core modules
from src.v5_bot.config import (
    PAPER_ONLY_MODE, REAL_ORDERS_ALLOWED, TRADING_SYMBOLS,
    POSITION_LIMITS, LEARNING_CONFIG
)
from src.v5_bot.firebase import (
    QuotaAwareFirestoreRepository, QuotaGuard, TradeOutbox,
    V5Control, V5Epoch, V5Trade, V5Dashboard, V5Readiness
)

__all__ = [
    "PAPER_ONLY_MODE", "REAL_ORDERS_ALLOWED", "TRADING_SYMBOLS",
    "POSITION_LIMITS", "LEARNING_CONFIG",
    "QuotaAwareFirestoreRepository", "QuotaGuard", "TradeOutbox",
    "V5Control", "V5Epoch", "V5Trade", "V5Dashboard", "V5Readiness"
]
