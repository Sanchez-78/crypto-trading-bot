"""
V5 Legacy Bridge — Learning Bridge

Builds normalized learning updates from closed PAPER trades.

Legacy learning continues unchanged. This bridge adds V5-style metrics
and readiness eligibility checks after close.
"""

import logging
from datetime import datetime
from typing import Optional

from . import config
from .event_models import LegacyPaperCloseEvent

logger = logging.getLogger(__name__)


class V5LearningBridge:
    """
    Converts legacy paper close events to V5-style learning snapshots.

    Does not replace legacy learning. Adds normalized close outcomes for Android dashboard.
    """

    def __init__(self, readiness_eligible_callback=None):
        """
        Initialize learning bridge.

        Args:
            readiness_eligible_callback: Optional callable to determine readiness eligibility
        """
        self.readiness_eligible_callback = readiness_eligible_callback

    def build_learning_update(self, close_event: LegacyPaperCloseEvent) -> dict:
        """
        Build normalized V5-style learning update from close event.

        Does not require Firebase write - just data preparation.

        Args:
            close_event: LegacyPaperCloseEvent

        Returns:
            Learning update dict with required fields
        """
        try:
            # Determine readiness eligibility
            readiness_eligible = self.check_readiness_eligible(close_event)
            if self.readiness_eligible_callback:
                try:
                    readiness_eligible = self.readiness_eligible_callback(close_event)
                except Exception as e:
                    logger.debug(f"[V5_BRIDGE] readiness_eligible callback failed: {e}")

            # Build learning snapshot
            update = {
                "trade_id": close_event.trade_id,
                "symbol": close_event.symbol,
                "side": close_event.side,
                "regime": getattr(close_event, "regime", "unknown"),
                "exit_reason": close_event.exit_reason,
                "gross_pnl": close_event.gross_pnl,
                "fees": close_event.fees,
                "spread": close_event.spread,
                "net_pnl": close_event.net_pnl,
                "net_pnl_pct": close_event.net_pnl_pct,
                "duration_seconds": close_event.duration_seconds,
                "entry_price": getattr(close_event, "entry_price", None),
                "exit_price": close_event.exit_price,
                "learning_eligible": close_event.learning_eligible,
                "readiness_eligible": readiness_eligible,
                "source": "legacy_v5_bridge",
                "real_orders_allowed": close_event.real_orders_allowed,
                "timestamp": datetime.utcnow().isoformat(),
            }

            logger.info(
                f"[V5_BRIDGE_LEARNING_UPDATE] trade_id={close_event.trade_id} "
                f"net_pnl={close_event.net_pnl:.2f} learning_eligible={close_event.learning_eligible} "
                f"readiness_eligible={readiness_eligible}"
            )

            return update

        except Exception as e:
            logger.error(f"[V5_BRIDGE] build_learning_update failed: {e}")
            return {}

    def apply_learning_from_close(
        self, close_event: LegacyPaperCloseEvent
    ) -> dict:
        """
        Apply learning after close and return update record.

        This is called after a PAPER close completes.
        Legacy learning continues unchanged via existing flow.

        Args:
            close_event: LegacyPaperCloseEvent

        Returns:
            Learning update dict
        """
        try:
            # Verify REAL is disabled
            if close_event.real_orders_allowed:
                logger.error(
                    f"[V5_BRIDGE_REAL_DISABLED] UNEXPECTED: real_orders_allowed=true "
                    f"in V5 bridge. Aborting learning."
                )
                return {"error": "REAL_ORDERS_NOT_ALLOWED"}

            # Build normalized update
            update = self.build_learning_update(close_event)

            # Log learning eligibility
            if close_event.learning_eligible:
                logger.info(
                    f"[V5_BRIDGE_LEARNING_UPDATE] trade_id={close_event.trade_id} "
                    f"eligible=true exit_reason={close_event.exit_reason}"
                )
            else:
                logger.debug(
                    f"[V5_BRIDGE_LEARNING_UPDATE] trade_id={close_event.trade_id} "
                    f"eligible=false exit_reason={close_event.exit_reason}"
                )

            return update

        except Exception as e:
            logger.error(f"[V5_BRIDGE] apply_learning_from_close failed: {e}")
            return {"error": str(e)}

    def check_readiness_eligible(self, close_event: LegacyPaperCloseEvent) -> bool:
        """
        Determine if close event is eligible for readiness.

        Readiness eligibility requires:
        - learning_eligible = true
        - positive net_pnl_pct (profitable trade)
        - exit_reason not in [timeout, max_slippage, manual_close, etc]

        Args:
            close_event: LegacyPaperCloseEvent

        Returns:
            True if eligible for readiness tracking
        """
        try:
            # Must be learning eligible
            if not close_event.learning_eligible:
                return False

            # Must be profitable
            if close_event.net_pnl_pct <= 0:
                return False

            # Exclude certain exit reasons
            excluded_reasons = [
                "timeout",
                "max_slippage",
                "manual_close",
                "error",
                "disconnected",
            ]
            if close_event.exit_reason in excluded_reasons:
                return False

            return True

        except Exception as e:
            logger.debug(f"[V5_BRIDGE] check_readiness_eligible failed: {e}")
            return False
