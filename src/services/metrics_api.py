"""
metrics_api.py — REST API for unified trading metrics and dashboard data

Exposes endpoints for:
- /api/metrics/summary
- /api/metrics/by_symbol
- /api/metrics/learning
- /api/metrics/rejected

Returns consistent data for both live and historical modes.
"""

from fastapi import APIRouter
from src.services.metrics_engine import MetricsEngine
from src.services.trade_executor import get_all_trades
from src.services.learning_engine import get_learning_snapshots

router = APIRouter()

@router.get("/api/metrics/summary")
def metrics_summary():
    trades = get_all_trades()
    metrics = MetricsEngine().compute(trades)
    return metrics

@router.get("/api/metrics/by_symbol")
def metrics_by_symbol():
    trades = get_all_trades()
    metrics = MetricsEngine().compute(trades)
    return metrics.get("strategy", {})

@router.get("/api/metrics/learning")
def metrics_learning():
    return get_learning_snapshots()

@router.get("/api/metrics/rejected")
def metrics_rejected():
    # TODO: Implement rejected trades stats
    return {"rejected": 0, "reasons": {}}
