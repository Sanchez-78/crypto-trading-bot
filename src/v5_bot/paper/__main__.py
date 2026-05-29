"""V5 PAPER Bot entry point."""

import asyncio
import logging
import os
from .runner import V5BotRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Run V5 PAPER bot."""
    # Get Firebase credentials path from environment (optional, defaults to None)
    creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")

    runner = V5BotRunner(firebase_creds_path=creds_path)
    logger.info("Starting V5 PAPER Bot...")

    try:
        await runner.run(tick_interval_s=1.0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise
    finally:
        logger.info("V5 PAPER Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
