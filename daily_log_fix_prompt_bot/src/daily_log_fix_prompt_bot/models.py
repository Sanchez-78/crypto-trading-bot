"""Data models for log analysis."""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum


class Severity(str, Enum):
    """Issue severity levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Issue:
    """Detected issue from log analysis."""
    id: str
    severity: Severity
    confidence: float  # 0.0-1.0
    title: str
    evidence: List[str]  # log snippets
    probable_root_cause: str
    recommended_fix: str
    likely_files: List[str]
    validation_steps: List[str]

    def to_dict(self) -> dict:
        """Convert to dict."""
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class LogMetrics:
    """Aggregated metrics from logs."""
    log_lines_analyzed: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    symbols_seen: List[str] = field(default_factory=list)
    trades_opened: int = 0
    trades_closed: int = 0
    rejection_count: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    timeout_count: int = 0
    exception_count: int = 0
    firebase_warnings: int = 0
    redis_warnings: int = 0
    version_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict."""
        return asdict(self)


@dataclass
class AnalysisResult:
    """Complete log analysis result."""
    metrics: LogMetrics
    issues: List[Issue]
    positive_signals: List[str]
    unknowns: List[str]
    summary: str

    def to_dict(self) -> dict:
        """Convert to dict."""
        return {
            "metrics": self.metrics.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "positive_signals": self.positive_signals,
            "unknowns": self.unknowns,
            "summary": self.summary,
        }
