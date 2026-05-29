"""V5 PAPER Bot entry point."""

import asyncio
import logging
import os
import base64
import json
import tempfile
from .runner import V5BotRunner

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Run V5 PAPER bot."""
    creds_path = None

    # Try to get credentials from multiple sources
    # 1. Explicit path
    creds_path = os.environ.get("FIREBASE_CREDENTIALS_PATH")

    # 2. Base64-encoded credentials (environment variable)
    if not creds_path:
        firebase_key_b64 = os.environ.get("FIREBASE_KEY_BASE64")
        if firebase_key_b64:
            try:
                # Decode base64 to JSON
                credentials_json = base64.b64decode(firebase_key_b64).decode('utf-8')

                # Write to temporary file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                    f.write(credentials_json)
                    creds_path = f.name
                    logger.info(f"Loaded Firebase credentials from FIREBASE_KEY_BASE64")
            except Exception as e:
                logger.error(f"Failed to decode FIREBASE_KEY_BASE64: {e}")

    # 3. Google Application Default Credentials (automatic)

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
