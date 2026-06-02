"""
V5 Legacy Bridge Configuration

All caps and operational constants for the V5→Legacy integration.
"""

import os

# ════════════════════════════════════════════════════════════════════════════
# SAFETY FLAGS
# ════════════════════════════════════════════════════════════════════════════

# Always False - REAL trading must never be enabled in this integration
REAL_ORDERS_ALLOWED = False
ENABLE_REAL_ORDERS = os.getenv("ENABLE_REAL_ORDERS", "false").lower() == "true"
PAPER_ONLY_MODE = os.getenv("PAPER_ONLY_MODE", "true").lower() == "true"
TRADING_MODE = os.getenv("TRADING_MODE", "paper_train")

# Verify safety
assert not ENABLE_REAL_ORDERS, "ENABLE_REAL_ORDERS must be False"
assert PAPER_ONLY_MODE, "PAPER_ONLY_MODE must be True"
assert TRADING_MODE == "paper_train", "TRADING_MODE must be paper_train"


# ════════════════════════════════════════════════════════════════════════════
# QUOTA CAPS (Firebase operations)
# ════════════════════════════════════════════════════════════════════════════

V5_ACTIVE_HARD_READS_CAP_PER_DAY = 20000
V5_ACTIVE_HARD_WRITES_CAP_PER_DAY = 10000

# Safety margins
QUOTA_CLOSE_RESERVE = 500  # Keep this many writes free for closing positions
QUOTA_LIFECYCLE_RESERVE = 200  # Keep for entry/exit persistence
QUOTA_EMERGENCY_RESERVE = 100  # Keep for critical operations

TOTAL_WRITE_RESERVE = QUOTA_CLOSE_RESERVE + QUOTA_LIFECYCLE_RESERVE + QUOTA_EMERGENCY_RESERVE


# ════════════════════════════════════════════════════════════════════════════
# TRADING LIMITS
# ════════════════════════════════════════════════════════════════════════════

MAX_PAPER_ENTRIES_PER_DAY = 50
MAX_OPEN_GLOBAL = 2  # Max 2 open positions globally
MAX_OPEN_PER_SYMBOL = 1  # Max 1 position per symbol


# ════════════════════════════════════════════════════════════════════════════
# INTERVALS AND TIMING
# ════════════════════════════════════════════════════════════════════════════

DASHBOARD_SNAPSHOT_INTERVAL_S = 300  # Publish metrics every 5 minutes
OUTBOX_RETRY_INTERVAL_S = 60  # Check outbox every 60 seconds (legacy, use FLUSH_INTERVAL)
OUTBOX_FLUSH_INTERVAL_S = 10  # Phase 4D: Flush worker polls outbox every 10 seconds
OUTBOX_MAX_RETRIES = 3  # Max retry attempts per entry
QUOTA_SNAPSHOT_INTERVAL_S = 300  # Publish quota every 5 minutes


# ════════════════════════════════════════════════════════════════════════════
# RUNTIME PATHS
# ════════════════════════════════════════════════════════════════════════════

RUNTIME_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "runtime")
V5_QUOTA_DB_PATH = os.path.join(RUNTIME_DIR, "v5_quota_usage.sqlite")
V5_OUTBOX_DB_PATH = os.path.join(RUNTIME_DIR, "v5_trade_outbox.sqlite")

# File permissions (never use 777 or 666)
RUNTIME_DIR_PERMS = 0o700  # rwx------
RUNTIME_FILE_PERMS = 0o600  # rw-------


# ════════════════════════════════════════════════════════════════════════════
# FIREBASE PATHS
# ════════════════════════════════════════════════════════════════════════════

FIREBASE_DASHBOARD_PATH = "v5_dashboard/current"
FIREBASE_READINESS_PATH = "v5_readiness/current"
FIREBASE_QUOTA_PATH_TEMPLATE = "v5_quota/{date}"  # v5_quota/2026-06-01
FIREBASE_METRICS_RUNTIME_PATH = "v5_metrics/runtime_current"
FIREBASE_METRICS_SEGMENTS_PATH = "v5_metrics/segments_current"
FIREBASE_TRADES_PATH_TEMPLATE = "v5_trades/{trade_id}"
FIREBASE_EPOCHS_PATH_TEMPLATE = "v5_epochs/{epoch_id}"


# ════════════════════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════════════════════

LOG_TAG_OPEN_SAVED = "[V5_BRIDGE_OPEN_SAVED]"
LOG_TAG_CLOSE_SAVED = "[V5_BRIDGE_CLOSE_SAVED]"
LOG_TAG_LEARNING_UPDATE = "[V5_BRIDGE_LEARNING_UPDATE]"
LOG_TAG_DASHBOARD_PUBLISH = "[V5_BRIDGE_DASHBOARD_PUBLISH]"
LOG_TAG_QUOTA_STATE = "[V5_BRIDGE_QUOTA_STATE]"
LOG_TAG_OUTBOX_RETRY = "[V5_BRIDGE_OUTBOX_RETRY]"
LOG_TAG_REAL_DISABLED = "[V5_BRIDGE_REAL_DISABLED]"


# ════════════════════════════════════════════════════════════════════════════
# LEARNING & READINESS
# ════════════════════════════════════════════════════════════════════════════

# Minimum trades to consider for learning eligibility
MIN_TRADES_FOR_LEARNING = 10

# Minimum trades for readiness (V5-style)
MIN_TRADES_FOR_READINESS = 50

# Win rate threshold for "READY" status
READY_WIN_RATE_THRESHOLD = 0.55  # 55% win rate

# Cost edge threshold for "READY" status
READY_COST_EDGE_THRESHOLD = 0.5  # 0.5% positive edge


# ════════════════════════════════════════════════════════════════════════════
# ANDROID METRICS CONTRACT
# ════════════════════════════════════════════════════════════════════════════

# Required fields for Android dashboard
ANDROID_REQUIRED_FIELDS = [
    "service_name",
    "mode",
    "real_orders_allowed",
    "legacy_runtime",
    "v5_bridge_enabled",
    "open_positions",
    "closed_today",
    "entries_attempted",
    "quota_state",
    "readiness_status",
]
