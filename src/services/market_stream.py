"""
market_stream.py — Real-time price feed via Binance WebSocket.

Replaces REST polling (1 s per-symbol loop) with a single persistent
combined-stream connection. Latency drops from ~100–300 ms REST round-trip
to <10 ms WebSocket push; zero per-symbol polling overhead.

Combined stream (no auth required):
  wss://stream.binance.com:9443/stream?streams=sym@bookTicker/…

Each push message:
  {"stream": "btcusdt@bookticker",
   "data":   {"s": "BTCUSDT", "b": bid, "B": bidQty, "a": ask, "A": askQty}}

Reconnect: exponential back-off (1 s → 2 s → 4 s … capped at 30 s).
Back-off resets to 1 s after a session that lasted > 60 s (healthy run).
"""

import json
import time
import websocket

from src.core.event_bus import publish
from src.services.learning_event import track_price
from src.services.portfolio_discovery import get_active_symbols

# ── Helpers ───────────────────────────────────────────────────────────────────

def _stream_url(symbols: list[str]) -> str:
    parts = []
    for s in symbols:
        sl = s.lower()
        parts.append(f"{sl}@bookTicker")
        parts.append(f"{sl}@depth20@100ms")
    return f"wss://stream.binance.com:9443/stream?streams={'/'.join(parts)}"


# ── WebSocket callbacks ───────────────────────────────────────────────────────

def _on_open(ws):
    short = "/".join(s.replace("USDT", "") for s in get_active_symbols())
    print(f"📡 MARKET LIVE (WebSocket bookTicker) — {short}")


def _on_message(ws, raw):
    try:
        msg    = json.loads(raw)
        stream = msg.get("stream", "")
        data   = msg.get("data", {})

        # ── @depth20@100ms — Level-2 order book snapshot ─────────────────────
        if "@depth20" in stream:
            sym = stream.split("@")[0].upper()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if sym and (bids or asks):
                from src.services.order_book_depth import update_depth
                update_depth(sym, bids, asks)
            return

        # ── @bookTicker — best bid/ask + OBI ─────────────────────────────────
        bid = float(data.get("b", 0))
        ask = float(data.get("a", 0))
        if bid <= 0 or ask <= 0:
            return

        p       = (bid + ask) / 2.0
        bid_qty = float(data.get("B", 0))
        ask_qty = float(data.get("A", 0))
        vol_b   = bid * bid_qty
        vol_a   = ask * ask_qty
        total   = vol_b + vol_a
        obi     = (vol_b - vol_a) / total if total > 0 else 0.0

        sym = data.get("s", "").upper()
        if sym:
            track_price(sym, p)
            publish("price_tick", {"symbol": sym, "price": p, "obi": obi})
    except Exception:
        pass


def _on_error(ws, error):
    print(f"⚠️  WebSocket error: {error}")


def _on_close(ws, code, msg):
    print(f"📡 WebSocket closed (code={code})")


# ── Entry point ───────────────────────────────────────────────────────────────

def start():
    """Open a persistent combined bookTicker stream; reconnect on disconnect."""
    backoff = 1
    while True:
        t_start = time.time()
        try:
            ws = websocket.WebSocketApp(
                _stream_url(get_active_symbols()),
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"⚠️  WebSocket exception: {e}")

        # Reset back-off after a healthy session (> 60 s uptime)
        if time.time() - t_start > 60:
            backoff = 1

        print(f"🔄 Reconnecting in {backoff} s …")
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
