"""
Firebase recovery — One-shot rehydration when Firebase recovers from degradation.

When safe mode clears and Firebase comes back online, reload authoritative state
to avoid entering cold-start mode. Load:
1. model_state (learning weights, calibration)
2. trade history (recent trades for bootstrap)
3. Rebuild canonical/bootstrap only if data loaded successfully

Never treat failed recovery read as empty DB.
"""

import logging
import time

_LAST_RECOVERY_ATTEMPT = 0
_RECOVERY_COOLDOWN = 60  # Don't retry recovery more than once per 60s


def attempt_recovery_rehydrate():
    """
    One-shot rehydration when Firebase recovers from degradation.

    Loads model_state and recent history, rebuilds state if data available.
    Never treats failed read as empty DB.

    Returns (success: bool, trades_loaded: int, model_state_loaded: bool)
    """
    global _LAST_RECOVERY_ATTEMPT

    now = time.time()
    # Cooldown: don't attempt recovery more than once per 60 seconds
    if (now - _LAST_RECOVERY_ATTEMPT) < _RECOVERY_COOLDOWN:
        return False, 0, False

    _LAST_RECOVERY_ATTEMPT = now
    trades_loaded = 0
    model_state_loaded = False

    try:
        from src.services.firebase_client import (
            load_history,
            load_model_state,
            get_firebase_health,
        )

        health = get_firebase_health()

        # Only attempt recovery if read is available (not degraded)
        if health["read_degraded"]:
            logging.warning(
                "[SAFE_MODE] Recovery rehydrate skipped: reads still degraded"
            )
            return False, 0, False

        logging.info("[SAFE_MODE] Firebase recovered; rehydrating state...")

        # Step 1: Load model state
        try:
            model_state = load_model_state()
            if model_state and len(model_state) > 0:
                model_state_loaded = True
                logging.info(
                    f"[SAFE_MODE] Rehydrate: model_state loaded "
                    f"({len(model_state)} entries)"
                )
            else:
                logging.warning("[SAFE_MODE] Rehydrate: model_state empty or unavailable")
        except Exception as e:
            logging.warning(f"[SAFE_MODE] Rehydrate: model_state load failed: {e}")

        # Step 2: Load recent trade history
        try:
            history = load_history(limit=200)  # Load last 200 trades
            if history and len(history) > 0:
                trades_loaded = len(history)
                logging.info(
                    f"[SAFE_MODE] Rehydrate: trade history loaded ({trades_loaded} trades)"
                )

                # Step 3: Rebuild canonical/bootstrap state from loaded data
                try:
                    from src.services.canonical_state import (
                        initialize_canonical_state,
                    )
                    from src.services.learning_event import bootstrap_from_history

                    initialize_canonical_state(history)
                    bootstrap_from_history(history)
                    logging.critical(
                        f"[SAFE_MODE] Recovery rehydrate OK: trades={trades_loaded} "
                        f"model_state={model_state_loaded}"
                    )
                    return True, trades_loaded, model_state_loaded
                except Exception as e:
                    logging.warning(
                        f"[SAFE_MODE] Rehydrate: canonical/bootstrap rebuild failed: {e}"
                    )
                    return False, trades_loaded, model_state_loaded
            else:
                logging.info(
                    "[SAFE_MODE] Rehydrate: trade history empty "
                    "(first run or all trades closed)"
                )
                # Empty history is OK on first run, just don't bootstrap
                return True, 0, model_state_loaded
        except Exception as e:
            logging.warning(f"[SAFE_MODE] Rehydrate: history load failed: {e}")
            return False, 0, model_state_loaded

    except Exception as e:
        logging.critical(f"[SAFE_MODE] Recovery rehydrate failed: {e}")
        return False, 0, False
