import httpx
import threading
import logging
from src.services.firebase_client import load_push_token

log = logging.getLogger(__name__)

def send_trade_notification(symbol, action, profit_pct, reason):
    """
    Send trade close notification via Expo push service.
    Queries Firebase config for mobile app push token and sends async notification.
    """
    try:
        token = load_push_token()
        if not token:
            log.debug("No push token available, skipping notification")
            return

        is_win = profit_pct > 0
        icon = "✅" if is_win else "❌"
        pct_str = f"+{profit_pct*100:.2f}%" if is_win else f"{profit_pct*100:.2f}%"

        title = f"{icon} Trade Closed"
        if is_win:
            body = f"{action} {symbol} closed at profit {pct_str} ({reason})"
        else:
            body = f"{action} {symbol} closed at loss {pct_str} ({reason})"

        message = {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": { "symbol": symbol, "profit": profit_pct }
        }

        def _send():
            try:
                resp = httpx.post("https://exp.host/--/api/v2/push/send", json=message, timeout=5)
                if resp.status_code == 200:
                    log.info(f"📱 Push notification sent: {title}")
                else:
                    log.warning(f"Push notification failed (HTTP {resp.status_code}): {title}")
            except Exception as e:
                log.warning(f"⚠️  Push notification network error: {e}")

        threading.Thread(target=_send, daemon=True).start()
    except Exception as e:
        log.warning(f"⚠️  Error loading push token: {e}")
