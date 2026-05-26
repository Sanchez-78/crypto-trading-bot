"""Configuration constants for Clean Core RESET R1."""

# Binance USDⓈ-M Futures WebSocket routes (fstream.binance.com only)
BINANCE_USDM_WS_BASE = "wss://fstream.binance.com"

# Public market data streams
BINANCE_USDM_DEPTH_STREAM = f"{BINANCE_USDM_WS_BASE}/ws"  # depth@100ms
BINANCE_USDM_BOOK_TICKER_STREAM = f"{BINANCE_USDM_WS_BASE}/ws"  # bookTicker
BINANCE_USDM_MARK_PRICE_STREAM = f"{BINANCE_USDM_WS_BASE}/ws"  # markPrice@1s
BINANCE_USDM_AGG_TRADE_STREAM = f"{BINANCE_USDM_WS_BASE}/ws"  # aggTrade

# Depth update sequence validation
DEPTH_FIRST_UPDATE_ID_KEY = "U"  # first update id
DEPTH_LAST_UPDATE_ID_KEY = "u"  # final update id
DEPTH_PREVIOUS_FINAL_ID_KEY = "pu"  # previous final id (for continuation)

# Local order book integrity states
BOOK_SNAPSHOT_WAIT_MS = 100
BOOK_STALE_THRESHOLD_MS = 1000
BOOK_GAP_THRESHOLD_MESSAGES = 5

# Clean epoch and learning constants
CLEAN_EPOCH_MIN_OBSERVATIONS = 30
CLEAN_EPOCH_STATUS_ACTIVE = "active"
CLEAN_EPOCH_STATUS_COMPLETED = "completed"
CLEAN_EPOCH_LEGACY_POLICY = "archive_comparator_only"

# Fee schedule (basis points)
MAKER_FEE_BPS = 2.0  # 0.02%
TAKER_FEE_BPS = 4.0  # 0.04%
RPI_FEE_BPS = 0.0  # typically 0 or positive rebate

# Journal and provenance constants
JOURNAL_APPEND_ONLY_FORMAT = "jsonl"
JOURNAL_EVENT_SCHEMA_VERSION = "1.0"

# State file isolation
CLEAN_CORE_STATE_DIR = "server_local_backups"
CLEAN_CORE_EPOCH_FILE = "clean_core_epoch_v1.json"
CLEAN_CORE_JOURNAL_FILE = "clean_core_journal_v1.jsonl"
