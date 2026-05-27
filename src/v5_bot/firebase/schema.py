"""V5 Firebase schema models and validators.

All V5 documents use v5_* collections and strict schema versioning.
No legacy collections are written to.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any
from enum import Enum
from datetime import datetime
import uuid


class QuotaState(Enum):
    """Firestore quota states based on operational caps."""
    NORMAL = "normal"  # reads < 4k, writes < 1500
    WARNING = "warning"  # reads >= 4k or writes >= 1500
    DEGRADED = "degraded"  # reads >= 6k or writes >= 2200
    CRITICAL = "critical"  # reads >= 7500 or writes >= 2800
    HARD_STOP = "hard_stop"  # reads >= 8k or writes >= 3k


class TradeStatus(Enum):
    """Trade lifecycle status."""
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"


class ReadinessStatus(Enum):
    """REAL readiness state machine."""
    NOT_READY_INITIALIZING = "not_ready_initializing"
    NOT_READY_COLLECTING_SAMPLE = "not_ready_collecting_sample"
    NOT_READY_DATA_QUALITY = "not_ready_data_quality"
    NOT_READY_NEGATIVE_AFTER_COSTS = "not_ready_negative_after_costs"
    NOT_READY_RISK = "not_ready_risk"
    NOT_READY_QUOTA = "not_ready_quota"
    NOT_READY_STABILITY = "not_ready_stability"
    PAPER_PERFORMANCE_PROMISING = "paper_performance_promising"
    REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED = "real_review_ready_operator_approval_required"
    REAL_DISABLED_BY_POLICY = "real_disabled_by_policy"


@dataclass
class V5Control:
    """v5_control/active — runtime control flags."""
    schema_version: int = 1
    active_epoch_id: str = ""
    mode: str = "paper"
    real_orders_allowed: bool = False
    entries_enabled: bool = True
    quota_policy_version: str = "v1.0"
    strategy_config_version: str = "v1.0"
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class V5Epoch:
    """v5_epochs/{epoch_id} — epoch metadata and config."""
    schema_version: int = 1
    epoch_id: str = ""
    status: str = "paper_active"  # development | paper_active | frozen
    execution_truth_required: str = "BINANCE_USDM_PUBLIC_BOOK"
    started_at: str = ""
    code_commit: str = ""
    strategy_set: List[str] = field(default_factory=list)
    prior_legacy_learning_imported: bool = False
    updated_at: str = ""

    def __post_init__(self):
        if not self.epoch_id:
            self.epoch_id = f"v5_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        if not self.started_at:
            self.started_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class OpenPosition:
    """Compact representation of one open PAPER trade."""
    trade_id: str
    symbol: str
    side: str  # "long" or "short"
    strategy_id: str
    regime: str
    entry_timestamp: str
    entry_fill: float
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    unrealized_net_pnl_pct: Optional[float] = None


@dataclass
class V5OpenPositions:
    """v5_runtime/open_positions — compact open trade list."""
    schema_version: int = 1
    epoch_id: str = ""
    positions: List[OpenPosition] = field(default_factory=list)
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class V5Trade:
    """v5_trades/{trade_id} — complete trade lifecycle record."""
    schema_version: int = 1
    trade_id: str = ""
    epoch_id: str = ""
    status: str = "open"  # open | closed

    # Symbols and routing
    symbol: str = ""
    side: str = ""  # long | short
    strategy_id: str = ""
    regime: str = ""

    # Timestamps
    signal_timestamp: str = ""
    entry_timestamp: str = ""
    exit_timestamp: Optional[str] = None

    # Entry fills
    entry_bid: float = 0.0
    entry_ask: float = 0.0
    entry_fill: float = 0.0

    # Exit fills
    exit_bid: Optional[float] = None
    exit_ask: Optional[float] = None
    exit_fill: Optional[float] = None

    # Accounting
    entry_fee_pct: float = 0.0
    exit_fee_pct: Optional[float] = None
    spread_cost_bps: float = 0.0
    estimated_slippage_bps: float = 0.0
    funding_cost_pct: float = 0.0

    # PnL
    gross_pnl_pct: Optional[float] = None
    net_pnl_pct: Optional[float] = None
    outcome: Optional[str] = None  # win | loss | flat
    exit_reason: Optional[str] = None  # TP | SL | TIMEOUT | FEED_SAFETY_CLOSE

    # Risk/metrics
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    hold_s: Optional[int] = None

    # Quality flags
    execution_truth_class: str = "BINANCE_USDM_PUBLIC_BOOK"
    eligible_for_learning: bool = False
    eligible_for_real_readiness: bool = False
    market_source_identity: str = ""

    # Snapshots for audit
    feature_snapshot: Dict[str, Any] = field(default_factory=dict)
    decision_score: Optional[float] = None
    expected_move_bps: Optional[float] = None
    required_cost_cover_bps: Optional[float] = None
    cost_edge_passed: bool = False

    # Learning
    learning_update_applied: bool = False
    policy_action_after_close: Optional[str] = None

    updated_at: str = ""

    def __post_init__(self):
        if not self.trade_id:
            self.trade_id = str(uuid.uuid4())[:12]
        if not self.signal_timestamp:
            self.signal_timestamp = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class SegmentMetrics:
    """Learning metrics for one strategy/symbol/regime/side segment."""
    segment_id: str
    strategy_id: str
    symbol: str
    regime: str
    side: str
    n: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    net_expectancy_bps: float = 0.0
    profit_factor: float = 0.0
    fee_drag_bps: float = 0.0
    timeout_rate: float = 0.0
    mfe_avg_bps: float = 0.0
    mae_avg_bps: float = 0.0
    drawdown_contribution_pct: float = 0.0
    sample_sufficiency: str = "insufficient"  # insufficient | adequate | mature
    policy_action: str = "active"  # active | cooled | blocked
    cooldown_until: float = 0.0  # unix timestamp
    allowed_for_paper: bool = True
    candidate_for_real_review: bool = False


@dataclass
class V5LearningState:
    """v5_learning/state — complete learner state."""
    schema_version: int = 1
    epoch_id: str = ""
    closed_eligible_n: int = 0
    policy_stats_by_segment: Dict[str, SegmentMetrics] = field(default_factory=dict)
    rolling20_closes: List[float] = field(default_factory=list)  # net_pnl_pct
    rolling50_closes: List[float] = field(default_factory=list)
    rolling100_closes: List[float] = field(default_factory=list)
    rejected_reason_aggregates: Dict[str, int] = field(default_factory=dict)
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class V5DailyMetrics:
    """v5_metrics/daily_{quota_day_pt} — daily aggregate."""
    schema_version: int = 1
    epoch_id: str = ""
    quota_day_pt: str = ""  # YYYYMMDD PT
    entries: int = 0
    closes: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    net_pnl_pct_sum: float = 0.0
    fees_pct_sum: float = 0.0
    funding_pct_sum: float = 0.0
    strategy_segment_summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class ReadinessGate:
    """One gate in readiness evaluation."""
    gate_name: str
    current_value: Any
    required_value: Any
    pass_: bool = False
    reason_cs: str = ""


@dataclass
class V5Readiness:
    """v5_readiness/current — REAL readiness status."""
    schema_version: int = 1
    epoch_id: str = ""
    paper_only: bool = True
    real_orders_allowed: bool = False
    status: str = "not_ready_initializing"
    status_label_cs: str = "Inicializace..."
    ready_for_operator_real_review: bool = False
    evaluated_at: str = ""
    thresholds_version: str = "v1.0"

    # Gate tracking
    gates: List[ReadinessGate] = field(default_factory=list)
    blocking_reasons_cs: List[str] = field(default_factory=list)

    # Current metrics
    eligible_closes_current: int = 0
    eligible_closes_required: int = 300
    days_current: int = 0
    days_required: int = 7
    overall_expectancy_current_bps: float = 0.0
    overall_expectancy_required_bps: float = 0.0
    rolling100_expectancy_current_bps: float = 0.0
    overall_pf_current: float = 0.0
    overall_pf_required: float = 1.20
    rolling100_pf_current: float = 0.0
    drawdown_current_pct: float = 0.0
    drawdown_limit_pct: float = 5.0

    # Quality checks
    provenance_violations: int = 0
    accounting_missing_count: int = 0
    quota_safe_days: int = 0
    unresolved_incidents: int = 0

    updated_at: str = ""

    def __post_init__(self):
        if not self.evaluated_at:
            self.evaluated_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class V5Quota:
    """v5_quota/{quota_day_pt} — quota usage tracking."""
    schema_version: int = 1
    quota_day_pt: str = ""  # YYYYMMDD PT
    internal_reads_attempted: int = 0
    internal_writes_attempted: int = 0
    internal_deletes_attempted: int = 0
    retry_attempts: int = 0
    state: str = "normal"  # normal | warning | degraded | critical | hard_stop
    soft_cap_reads: int = 4000
    soft_cap_writes: int = 1500
    hard_cap_reads: int = 8000
    hard_cap_writes: int = 3000
    last_flushed_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.quota_day_pt:
            import pytz
            tz = pytz.timezone('America/Los_Angeles')
            self.quota_day_pt = datetime.now(tz).strftime('%Y%m%d')
        if not self.last_flushed_at:
            self.last_flushed_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class V5Dashboard:
    """v5_dashboard/current — operator dashboard snapshot."""
    schema_version: int = 1
    epoch_id: str = ""
    paper_only: bool = True

    # Compact aggregates (no raw trade details)
    open_positions_count: int = 0
    open_positions_notional_usd: float = 0.0
    open_positions_unrealized_net_pct: float = 0.0

    last_closed_trade_id: Optional[str] = None
    last_closed_at: Optional[str] = None
    last_closed_outcome: Optional[str] = None
    last_closed_net_pnl_pct: Optional[float] = None

    # Learning
    eligible_closes_total: int = 0
    net_pnl_pct_sum: float = 0.0
    net_expectancy_bps: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0

    # Readiness
    readiness_status: str = "not_ready_initializing"
    readiness_label_cs: str = "Inicializace..."
    ready_for_real_review: bool = False

    # Quota
    quota_state: str = "normal"
    quota_reads_remaining: int = 8000
    quota_writes_remaining: int = 3000

    # Health
    feed_connected: bool = False
    last_market_event_age_s: Optional[float] = None
    firebase_status: str = "unknown"

    data_freshness: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.data_freshness:
            self.data_freshness = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


@dataclass
class MetricDefinition:
    """One metric in the registry."""
    metric_id: str
    display_name_cs: str
    category: str
    definition_cs: str
    unit: str
    value_type: str  # int | float | str | bool
    firebase_document_path: str
    firebase_field_path: str
    update_trigger: str  # e.g., "CLOSE" or "15min"
    freshness_target_s: int
    android_tab: str
    visibility: str  # summary | detail | diagnostics
    read_cost_note: str
    threshold_interpretation: str = ""


@dataclass
class V5MetricsRegistry:
    """v5_metrics_registry/current — all metrics contract."""
    schema_version: int = 1
    contract_version: str = "1.0"
    generated_at: str = ""
    metrics: List[MetricDefinition] = field(default_factory=list)
    android_supported: bool = True
    updated_at: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.utcnow().isoformat()


def to_firestore_dict(obj) -> Dict[str, Any]:
    """Convert dataclass to Firestore-safe dict (timestamps as strings)."""
    data = asdict(obj)
    # Firestore can handle these natively; just ensure timestamps are strings
    return data


def from_firestore_dict(cls, data: Dict[str, Any]):
    """Reconstruct dataclass from Firestore dict."""
    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
