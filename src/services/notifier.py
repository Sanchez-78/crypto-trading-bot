import httpx
import threading
from src.services.firebase_client import db

def send_trade_notification(symbol, action, profit_pct, reason):
    """
    Vyžádá si Expo Push Token z Firebase configu mobilní appky
    a ihned asynchronně odpálí notifikaci na mobilní zařízení.
    """
    try:
        doc = db.collection('config').document('push_tokens').get()
        if not doc.exists:
            return
            
        data = doc.to_dict()
        token = data.get("token") if data else None
        if not token:
            return
            
        is_win = profit_pct > 0
        icon = "✅" if is_win else "❌"
        pct_str = f"+{profit_pct*100:.2f}%" if is_win else f"{profit_pct*100:.2f}%"
        
        title = f"{icon} Transakce Dokončena"
        if is_win:
            body = f"{action} pozice {symbol} uzavřena na cíli {pct_str} ({reason})"
        else:
            body = f"{action} pozice {symbol} uzavřena ve ztrátě {pct_str} ({reason})"
             
        message = {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": { "symbol": symbol, "profit": profit_pct }
        }
        
        # Odeslat zprávu na pozadí, abychom nebrzdili Execution engine bota
        def _send():
            try:
                resp = httpx.post("https://exp.host/--/api/v2/push/send", json=message, timeout=5)
                if resp.status_code == 200:
                    print(f"📱 Odeslána Push Notifikace: {title}")
            except Exception as e:
                print(f"⚠️ Push Notifikace network error: {e}")
                
        threading.Thread(target=_send, daemon=True).start()
    except Exception as e:
        print(f"⚠️ Chyba čtení Push Tokenu: {e}")