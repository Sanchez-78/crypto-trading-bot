"""
V5 Legacy Bridge — Metrics Publisher

Publishes bounded aggregate metrics to Firebase for Android dashboard.

Includes: service status, quota state, trading stats, learning metrics, readiness.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List

from . import config
from .quota import V5LegacyQuotaGuard
from .outbox import DurableOutbox

logger = logging.getLogger(__name__)


class V5MetricsPublisher:
    """
    Publishes bounded aggregate metrics for dashboard and Android visibility.
    """

    def __init__(self, quota_guard: Optional[V5LegacyQuotaGuard] = None, outbox: Optional[DurableOutbox] = None):
        """
        Initialize metrics publisher.

        Args:
            quota_guard: Quota guard instance
            outbox: Outbox instance
        """
        self.quota_guard = quota_guard or V5LegacyQuotaGuard()
        self.outbox = outbox

    def build_dashboard_metrics(
        self,
        runtime_state: dict,
        quota_snapshot: dict,
        trading_stats: dict,
        learning_stats: dict,
        paper_metrics: dict = None,
    ) -> dict:
        """
        Build complete dashboard metrics for Firebase and Android.

        Args:
            runtime_state: Service/mode info
            quota_snapshot: Quota guard snapshot
            trading_stats: Entry/exit counts and stats
            learning_stats: Learning eligibility and readiness
            paper_metrics: Live PAPER training metrics (entries_1h, exits_1h, learning_updates_1h, etc)

        Returns:
            Dashboard dict with all required fields
        """
        try:
            # Service/Runtime info
            dashboard = {
                "timestamp": datetime.utcnow().isoformat(),
                "service_name": "cryptomaster.service",
                "mode": "paper_train",
                "real_orders_allowed": False,
                "legacy_runtime": True,
                "v5_bridge_enabled": True,
            }

            # Quota metrics
            if quota_snapshot:
                dashboard.update({
                    "internal_reads_cap": quota_snapshot.get("internal_reads_cap", 20000),
                    "internal_writes_cap": quota_snapshot.get("internal_writes_cap", 10000),
                    "reads_used": quota_snapshot.get("reads_used", 0),
                    "writes_used": quota_snapshot.get("writes_used", 0),
                    "reads_remaining": quota_snapshot.get("reads_remaining", 20000),
                    "writes_remaining": quota_snapshot.get("writes_remaining", 10000),
                    "quota_state": quota_snapshot.get("state", "normal"),
                })

            # Trading metrics
            if trading_stats:
                dashboard.update({
                    "open_positions": trading_stats.get("open_positions", 0),
                    "closed_today": trading_stats.get("closed_today", 0),
                    "entries_attempted": trading_stats.get("entries_attempted", 0),
                    "entries_accepted": trading_stats.get("entries_accepted", 0),
                    "entries_rejected": trading_stats.get("entries_rejected", 0),
                    "reject_reasons": trading_stats.get("reject_reasons", {}),
                    "cost_edge_pass": trading_stats.get("cost_edge_pass", 0),
                    "cost_edge_fail": trading_stats.get("cost_edge_fail", 0),
                })

            # Live PAPER training metrics (1-hour rolling windows)
            if paper_metrics:
                dashboard.update({
                    "paper_entries_1h": paper_metrics.get("paper_entries_1h", 0),
                    "paper_exits_1h": paper_metrics.get("paper_exits_1h", 0),
                    "paper_learning_updates_1h": paper_metrics.get("paper_learning_updates_1h", 0),
                    "starvation_bypass_accepted_1h": paper_metrics.get("starvation_bypass_accepted_1h", 0),
                    "last_paper_entry_age_s": paper_metrics.get("last_paper_entry_age_s"),
                    "last_paper_exit_age_s": paper_metrics.get("last_paper_exit_age_s"),
                    "last_learning_update_age_s": paper_metrics.get("last_learning_update_age_s"),
                })
                # Use live exits as closed_today if not provided
                if dashboard.get("closed_today", 0) == 0 and paper_metrics.get("paper_exits_1h", 0) > 0:
                    dashboard["closed_today"] = paper_metrics.get("paper_exits_1h", 0)

            # Learning/readiness metrics
            if learning_stats:
                dashboard.update({
                    "learning_updates": learning_stats.get("learning_updates", 0),
                    "eligible_closes": learning_stats.get("eligible_closes", 0),
                    "readiness_status": learning_stats.get("readiness_status", "NOT_READY"),
                    "readiness_status_cs": learning_stats.get("readiness_status_cs", "NEBYLI PŘIPRAVENI"),
                    "readiness_reason": learning_stats.get("readiness_reason", "insufficient_data"),
                    "readiness_reason_cs": learning_stats.get("readiness_reason_cs", "nedostatek_dat"),
                })

            # Outbox pending (if available)
            if self.outbox:
                dashboard["outbox_pending"] = self.outbox.pending_count()

            # Note: Android validation moved to prepare_publish_payload after readiness injection
            # (so that readiness_status can be added before validation)

            # Log with detailed metrics
            logger.info(
                f"[V5_BRIDGE_DASHBOARD_METRICS] "
                f"closed_today={dashboard.get('closed_today', 0)} "
                f"paper_exits_1h={dashboard.get('paper_exits_1h', 0)} "
                f"learning_updates={dashboard.get('paper_learning_updates_1h', 0)} "
                f"open={dashboard.get('open_positions', 0)} "
                f"quota_state={dashboard.get('quota_state', 'unknown')} "
                f"source={'paper_metrics' if paper_metrics else 'fallback'}"
            )

            # Also log the summary for monitoring
            logger.info(
                f"[V5_BRIDGE_DASHBOARD_PUBLISH] "
                f"open={dashboard.get('open_positions', 0)} "
                f"closed_today={dashboard.get('closed_today', 0)} "
                f"quota_state={dashboard.get('quota_state', 'unknown')} "
                f"readiness={dashboard.get('readiness_status', 'unknown')}"
            )

            return dashboard

        except Exception as e:
            logger.error(f"[V5_BRIDGE] build_dashboard_metrics failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "service_name": "cryptomaster.service",
                "mode": "paper_train",
                "error": str(e),
            }

    def build_readiness_metrics(self, learning_stats: dict, paper_metrics: dict = None) -> dict:
        """
        Build readiness status snapshot.

        Args:
            learning_stats: Learning eligibility and outcomes
            paper_metrics: Live PAPER training metrics (learning_updates_1h, etc)

        Returns:
            Readiness dict
        """
        try:
            readiness = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "NOT_READY",
                "status_cs": "NEBYLI PŘIPRAVENI",
                "reason": "insufficient_data",
                "reason_cs": "nedostatek_dat",
                "eligible_closes": 0,
                "learning_updates": 0,
                "min_trades_required": config.MIN_TRADES_FOR_READINESS,
                "readiness_status": "NOT_READY",
            }

            if learning_stats or paper_metrics:
                eligible = learning_stats.get("eligible_closes", 0) if learning_stats else 0

                # Use live paper_metrics learning_updates if available, fallback to learning_stats
                if paper_metrics and paper_metrics.get("paper_learning_updates_1h") is not None:
                    total_learning = paper_metrics.get("paper_learning_updates_1h", 0)
                    learning_source = "paper_metrics_1h"
                else:
                    total_learning = learning_stats.get("learning_updates", 0) if learning_stats else 0
                    learning_source = "learning_stats"

                readiness.update({
                    "eligible_closes": eligible,
                    "learning_updates": total_learning,
                    "learning_source": learning_source,
                })

                # Determine readiness
                if total_learning >= config.MIN_TRADES_FOR_READINESS:
                    win_rate = learning_stats.get("win_rate", 0.0) if learning_stats else 0.0
                    cost_edge = learning_stats.get("cost_edge_pct", 0.0) if learning_stats else 0.0

                    if win_rate >= config.READY_WIN_RATE_THRESHOLD and cost_edge >= config.READY_COST_EDGE_THRESHOLD:
                        readiness.update({
                            "status": "READY",
                            "status_cs": "PŘIPRAVENI",
                            "readiness_status": "READY",
                            "reason": "sufficient_performance",
                            "reason_cs": "dostatečná_výkonnost",
                        })
                    else:
                        readiness.update({
                            "status": "EVALUATING",
                            "status_cs": "VYHODNOCOVÁNÍ",
                            "readiness_status": "EVALUATING",
                            "reason": f"win_rate={win_rate:.1%} cost_edge={cost_edge:.2f}%",
                            "reason_cs": f"win_rate={win_rate:.1%} cost_edge={cost_edge:.2f}%",
                        })
                else:
                    remaining = config.MIN_TRADES_FOR_READINESS - total_learning
                    readiness.update({
                        "status": "LEARNING",
                        "status_cs": "UČENÍ",
                        "readiness_status": "LEARNING",
                        "reason": f"need_{remaining}_more_trades",
                        "reason_cs": f"potřeba_{remaining}_více_obchodů",
                    })

            logger.info(
                f"[V5_BRIDGE_READINESS_METRICS] "
                f"status={readiness.get('status', 'unknown')} "
                f"readiness_status={readiness.get('readiness_status', 'unknown')} "
                f"learning_updates={readiness.get('learning_updates', 0)} "
                f"learning_source={readiness.get('learning_source', 'unknown')} "
                f"reason={readiness.get('reason', 'unknown')}"
            )

            return readiness

        except Exception as e:
            logger.error(f"[V5_BRIDGE] build_readiness_metrics failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "NOT_READY",
                "error": str(e),
            }

    def build_quota_metrics(self) -> dict:
        """
        Build quota status snapshot.

        Returns:
            Quota dict
        """
        try:
            quota_snap = self.quota_guard.snapshot()

            quota = {
                "timestamp": datetime.utcnow().isoformat(),
                "date": quota_snap.get("date", "unknown"),
                "internal_reads_cap": quota_snap.get("internal_reads_cap", 20000),
                "internal_writes_cap": quota_snap.get("internal_writes_cap", 10000),
                "reads_used": quota_snap.get("reads_used", 0),
                "writes_used": quota_snap.get("writes_used", 0),
                "reads_remaining": quota_snap.get("reads_remaining", 20000),
                "writes_remaining": quota_snap.get("writes_remaining", 10000),
                "state": quota_snap.get("state", "normal"),
            }

            # Add reserves info
            quota.update({
                "close_reserve": config.QUOTA_CLOSE_RESERVE,
                "lifecycle_reserve": config.QUOTA_LIFECYCLE_RESERVE,
                "emergency_reserve": config.QUOTA_EMERGENCY_RESERVE,
            })

            # Estimate utilization
            reads_used = quota["reads_used"]
            writes_used = quota["writes_used"]
            quota["reads_utilization_pct"] = min(100, (reads_used / quota["internal_reads_cap"]) * 100)
            quota["writes_utilization_pct"] = min(100, (writes_used / quota["internal_writes_cap"]) * 100)

            logger.info(
                f"[V5_BRIDGE_QUOTA_STATE] "
                f"reads={reads_used}/{quota['internal_reads_cap']} "
                f"writes={writes_used}/{quota['internal_writes_cap']} "
                f"state={quota['state']}"
            )

            return quota

        except Exception as e:
            logger.error(f"[V5_BRIDGE] build_quota_metrics failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }

    def prepare_publish_payload(
        self,
        runtime_state: dict = None,
        quota_snapshot: dict = None,
        trading_stats: dict = None,
        learning_stats: dict = None,
        paper_metrics: dict = None,
    ) -> dict:
        """
        Prepare complete publish payload for Firebase.

        Args:
            runtime_state: Service/mode info
            quota_snapshot: Quota snapshot (or None to fetch fresh)
            trading_stats: Entry/exit counts
            learning_stats: Learning metrics
            paper_metrics: Live PAPER training metrics (1-hour rolling windows)

        Returns:
            Complete payload dict
        """
        try:
            # Fetch fresh quota if not provided
            if quota_snapshot is None:
                quota_snapshot = self.quota_guard.snapshot()

            # Build all metrics
            dashboard = self.build_dashboard_metrics(
                runtime_state or {},
                quota_snapshot,
                trading_stats or {},
                learning_stats or {},
                paper_metrics=paper_metrics,
            )

            readiness = self.build_readiness_metrics(learning_stats or {}, paper_metrics=paper_metrics)
            quota = self.build_quota_metrics()

            # Phase 4E-R1: Propagate readiness_status into dashboard for Android validation
            if readiness:
                # Copy critical readiness fields into dashboard so Android validation passes
                dashboard.update({
                    "readiness_status": readiness.get("readiness_status", "NOT_READY"),
                    "readiness_status_cs": readiness.get("status_cs", "NEBYLI PŘIPRAVENI"),
                    "readiness_reason": readiness.get("reason", "insufficient_data"),
                    "readiness_reason_cs": readiness.get("reason_cs", "nedostatek_dat"),
                    "readiness": readiness.get("readiness_status", "NOT_READY"),  # Legacy alias
                    "learning_updates": readiness.get("learning_updates", 0),
                })
            else:
                # Fallback if readiness unavailable
                dashboard.update({
                    "readiness_status": "NOT_READY",
                    "readiness": "NOT_READY",
                    "readiness_reason": "insufficient_data",
                })

            # Validate Android schema (now that readiness fields are injected)
            missing_fields = []
            for field in config.ANDROID_REQUIRED_FIELDS:
                if field not in dashboard:
                    missing_fields.append(field)

            if missing_fields:
                logger.warning(f"[V5_BRIDGE] Missing required fields for Android: {','.join(missing_fields)}")
            else:
                logger.info(f"[V5_BRIDGE_ANDROID_SCHEMA_OK] readiness_status={dashboard.get('readiness_status')}")

            # Combine into publish payload
            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "dashboard": dashboard,
                "readiness": readiness,
                "quota": quota,
            }

            return payload

        except Exception as e:
            logger.error(f"[V5_BRIDGE] prepare_publish_payload failed: {e}")
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }
