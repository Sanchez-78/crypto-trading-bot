"""V5 configuration — runtime, trading, quota, and strategy parameters."""

from pathlib import Path
from dataclasses import dataclass
import os

# ==================== Environment & Secrets ====================

def load_env(var_name: str, default: str = "") -> str:
    """Load environment variable safely (no logging of secrets)."""
    return os.getenv(var_name, default)


FIREBASE_CREDENTIALS_PATH = load_env("FIREBASE_CREDENTIALS_PATH", "")
BINANCE_API_KEY = load_env("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = load_env("BINANCE_SECRET_KEY", "")

# ==================== Trading Mode ====================

PAPER_ONLY_MODE = True  # NEVER set to False
REAL_ORDERS_ALLOWED = False  # NEVER set to True without explicit authorization
ENTRIES_ENABLED = True

# ==================== Binance Configuration ====================

BINANCE_USDM_WS_BASE = "wss://fstream.binance.com/public/ws"
BINANCE_USDM_MARKET_WS_BASE = "wss://fstream.binance.com/market/ws"
BINANCE_USDM_REST_BASE = "https://fapi.binance.com"

# Official Futures symbols to trade
TRADING_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "XRPUSDT",
]

# ==================== Position Management ====================

@dataclass
class PositionLimits:
    """Hard limits on open positions."""
    max_open_global: int = 3  # Never exceed 3 simultaneous positions
    max_open_per_symbol: int = 1  # Max 1 per symbol
    max_paper_entries_per_day: int = 300  # Safety cap on entry rate


POSITION_LIMITS = PositionLimits()

# ==================== Firestore Quota ====================

@dataclass
class FirestoreQuotaBudget:
    """Internal quota budget — well below official limits."""
    soft_cap_writes: int = 1500  # Warning state at this
    hard_cap_writes: int = 3000  # HARD_STOP at this
    soft_cap_reads: int = 4000  # Warning state at this
    hard_cap_reads: int = 8000  # HARD_STOP at this

    # Internal V5 active daily hard caps (enforced at runtime)
    v5_active_hard_writes_cap_per_day: int = 10000  # V5 max writes per day
    v5_active_hard_reads_cap_per_day: int = 20000   # V5 max reads per day

    # Official Firestore limits (do not change)
    official_max_writes_per_day: int = 20000
    official_max_reads_per_day: int = 50000


QUOTA_BUDGET = FirestoreQuotaBudget()

# ==================== Learning Configuration ====================

@dataclass
class LearningConfig:
    """Learner behavior configuration."""
    min_sample_per_segment: int = 30  # Min 30 closes before considering downweight
    sample_sufficiency_threshold: int = 100  # After 100 closes, segment is "mature"

    # Eligibility requirements (STRICT)
    require_complete_accounting: bool = True
    require_binance_futures_truth: bool = True
    require_valid_entry_exit_fills: bool = True

    # Policy gates
    min_net_expectancy_bps: float = 0.0  # Cost edge must be positive to admit
    min_profit_factor: float = 1.0  # Profit factor minimum
    max_drawdown_pct: float = 5.0  # Maximum acceptable drawdown


LEARNING_CONFIG = LearningConfig()

# ==================== REAL Readiness (Informational) ====================

@dataclass
class RealReadinessGates:
    """Evidence gates for REAL readiness — used for reporting only."""
    min_eligible_closes: int = 300
    min_days_of_data: int = 7
    min_strategy_regimes: int = 3
    min_expectancy_bps: float = 0.0
    min_profit_factor_rolling100: float = 1.10
    min_profit_factor_overall: float = 1.20
    max_drawdown_pct: float = 5.0


REAL_READINESS_GATES = RealReadinessGates()

# ==================== Strategy Configuration ====================

@dataclass
class StrategyConfig:
    """Base strategy configuration."""
    name: str = ""
    enabled: bool = True
    max_position_qty: float = 0.1  # As fraction of portfolio (not yet implemented for PAPER)


# ==================== Paths ====================

PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# Create directories if needed
for d in [RUNTIME_DIR, DATA_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Database paths
QUOTA_LEDGER_PATH = RUNTIME_DIR / "v5_quota_usage.sqlite"
TRADE_OUTBOX_PATH = RUNTIME_DIR / "v5_trade_outbox.sqlite"
PAPER_STATE_PATH = RUNTIME_DIR / "v5_paper_state.sqlite"

# ==================== Logging ====================

LOG_LEVEL = load_env("LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "v5_bot.log"

# ==================== Debug/Development ====================

DEBUG = load_env("V5_DEBUG", "false").lower() == "true"
FIRESTORE_EMULATOR_HOST = load_env("FIRESTORE_EMULATOR_HOST", "")  # Set for local testing
