"""
market_stream.py — Real-time price feed via Binance WebSocket with REST fallback.

Primary:  wss://stream.binance.com:9443  (bookTicker + depth20)
Fallback: REST polling — Binance /api/v3/ticker/bookTicker (1 s interval)
          If Binance REST also returns 451 → CoinGecko /simple/price (2 s interval,
          no OBI — prices only; OBI set to 0.0)

451 geo-restriction detection: if WebSocket handshake returns HTTP 451,
_geo_blocked flag is set and start() immediately switches to _rest_poll_loop()
instead of retrying the WebSocket endlessly.

Reconnect: exponential back-off (1 s → 2 s → 4 s … capped at 30 s).
Back-off resets to 1 s after a healthy session (> 60 s uptime).
"""

import json
import time
import urllib.request
import urllib.error

try:
    import websocket
except ImportError:
    websocket = None

from src.core.event_bus import publish
from src.services.learning_event import track_price
from src.services.portfolio_discovery import get_active_symbols

# ── Geo-block flag — set on HTTP 451; survives reconnect attempts ─────────────
_geo_blocked: bool = False


# ── Shared tick dispatcher ────────────────────────────────────────────────────

def _dispatch(sym: str, bid: float, ask: float, bid_qty: float = 0.0, ask_qty: float = 0.0) -> None:
    """Compute OBI, publish price_tick, push into SignalEngine."""
    if not sym or bid <= 0 or ask <= 0:
        return
    p     = (bid + ask) / 2.0
    vol_b = bid * bid_qty
    vol_a = ask * ask_qty
    total = vol_b + vol_a
    obi   = (vol_b - vol_a) / total if total > 0 else 0.0

    track_price(sym, p)
    publish("price_tick", {"symbol": sym, "price": p, "obi": obi})
    try:
        from src.services.signal_engine import SIGNAL_ENGINE_ENABLED, push_tick
        if SIGNAL_ENGINE_ENABLED:
            push_tick({"symbol": sym, "price": p, "obi": obi,
                       "bid": bid, "ask": ask,
                       "bid_qty": bid_qty, "ask_qty": ask_qty})
    except Exception:
        pass


# ── WebSocket helpers ─────────────────────────────────────────────────────────

def _stream_url(symbols: list[str]) -> str:
    parts = []
    for s in symbols:
        sl = s.lower()
        parts.append(f"{sl}@bookTicker")
        parts.append(f"{sl}@depth20@100ms")
    return f"wss://stream.binance.com:9443/stream?streams={'/'.join(parts)}"


def _on_open(ws):
    short = "/".join(s.replace("USDT", "") for s in get_active_symbols())
    print(f"📡 MARKET LIVE (WebSocket bookTicker) — {short}")


def _on_message(ws, raw):
    try:
        msg    = json.loads(raw)
        stream = msg.get("stream", "")
        data   = msg.get("data", {})

        if "@depth20" in stream:
            sym  = stream.split("@")[0].upper()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if sym and (bids or asks):
                try:
                    from src.services.order_book_depth import update_depth
                    update_depth(sym, bids, asks)
                except Exception:
                    pass
            return

        _dispatch(
            sym     = data.get("s", "").upper(),
            bid     = float(data.get("b", 0)),
            ask     = float(data.get("a", 0)),
            bid_qty = float(data.get("B", 0)),
            ask_qty = float(data.get("A", 0)),
        )
    except Exception:
        pass


def _on_error(ws, error):
    global _geo_blocked
    err_str = str(error)
    if "451" in err_str:
        _geo_blocked = True
        print("⚠️  WebSocket geo-blocked (HTTP 451) — switching to REST polling fallback")
    else:
        print(f"⚠️  WebSocket error: {error}")


def _on_close(ws, code, msg):
    print(f"📡 WebSocket closed (code={code})")


# ── REST polling fallback — Binance ───────────────────────────────────────────

def _binance_rest_poll(symbols: list[str]) -> bool:
    """
    Poll Binance /api/v3/ticker/bookTicker for all symbols.
    Returns True on success, False on 451 / connection error.
    """
    sym_json = json.dumps(symbols).replace(" ", "")
    url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbols={urllib.request.quote(sym_json)}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            if resp.status == 451:
                return False
            tickers = json.loads(resp.read())
            for t in tickers:
                _dispatch(
                    sym     = t.get("symbol", "").upper(),
                    bid     = float(t.get("bidPrice", 0)),
                    ask     = float(t.get("askPrice", 0)),
                    bid_qty = float(t.get("bidQty", 0)),
                    ask_qty = float(t.get("askQty", 0)),
                )
            return True
    except urllib.error.HTTPError as e:
        if e.code == 451:
            return False
        return False
    except Exception:
        return False


# ── REST polling fallback — CoinGecko (prices only, no OBI) ──────────────────

# CryptoMaster symbol → CoinGecko id
_CG_IDS: dict[str, str] = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "ADAUSDT": "cardano",
    "BNBUSDT": "binancecoin",
    "DOTUSDT": "polkadot",
    "SOLUSDT": "solana",
    "XRPUSDT": "ripple",
    "LTCUSDT": "litecoin",
    "AVAXUSDT": "avalanche-2",
    "MATICUSDT": "matic-network",
    "LINKUSDT": "chainlink",
    "DOGEUSDT": "dogecoin",
}


def _coingecko_poll(symbols: list[str]) -> bool:
    """Poll CoinGecko /simple/price — price only, OBI=0. Returns True on success."""
    ids = [_CG_IDS[s] for s in symbols if s in _CG_IDS]
    if not ids:
        return False
    ids_str = ",".join(ids)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoMaster/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            id_to_sym = {v: k for k, v in _CG_IDS.items()}
            for cg_id, vals in data.items():
                sym = id_to_sym.get(cg_id)
                if sym and sym in symbols:
                    p = float(vals.get("usd", 0))
                    if p > 0:
                        # No bid/ask from CoinGecko — use midprice with zero spread proxy
                        _dispatch(sym=sym, bid=p * 0.9999, ask=p * 1.0001)
            return True
    except Exception:
        return False


def _rest_poll_loop() -> None:
    """
    Main loop when WebSocket is geo-blocked.
    Priority: Binance REST (1 s) → CoinGecko (2 s)
    Prints source on first successful poll; retries silently on error.
    """
    symbols = get_active_symbols()
    short   = "/".join(s.replace("USDT", "") for s in symbols)

    # Test Binance REST first
    if _binance_rest_poll(symbols):
        print(f"📡 MARKET LIVE (REST polling — Binance) — {short}")
        poll_interval = 1.0
        use_cg        = False
    else:
        print(f"📡 MARKET LIVE (REST polling — CoinGecko fallback) — {short}")
        poll_interval = 2.0
        use_cg        = True

    consecutive_errors = 0
    while True:
        t0 = time.time()
        try:
            ok = _coingecko_poll(symbols) if use_cg else _binance_rest_poll(symbols)
            if ok:
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors >= 5 and not use_cg:
                    print("📡 Binance REST also blocked — switching to CoinGecko")
                    use_cg        = True
                    poll_interval = 2.0
                    consecutive_errors = 0
        except Exception:
            consecutive_errors += 1

        elapsed = time.time() - t0
        sleep_t = max(0.0, poll_interval - elapsed)
        time.sleep(sleep_t)


# ── Entry point ───────────────────────────────────────────────────────────────

def start():
    """
    Open a persistent combined bookTicker stream.
    On HTTP 451 geo-block, switch to REST polling fallback automatically.
    """
    global _geo_blocked
    import sys

    print(f"📡 market_stream.start() — WebSocket available: {websocket is not None}", file=sys.stderr, flush=True)

    if websocket is None:
        print("⚠️  websocket-client not installed — using REST polling fallback")
        _geo_blocked = True

    if _geo_blocked:
        print("📡 Starting REST polling fallback...", file=sys.stderr, flush=True)
        _rest_poll_loop()
        return

    print(f"📡 Attempting WebSocket connection to Binance bookTicker...", file=sys.stderr, flush=True)
    backoff = 1
    connection_attempts = 0
    while True:
        connection_attempts += 1
        t_start = time.time()
        try:
            print(f"📡 WebSocket attempt #{connection_attempts}...", file=sys.stderr, flush=True)
            ws = websocket.WebSocketApp(
                _stream_url(get_active_symbols()),
                on_open    = _on_open,
                on_message = _on_message,
                on_error   = _on_error,
                on_close   = _on_close,
            )
            print(f"📡 Calling ws.run_forever() (ping=30s, timeout=10s)...", file=sys.stderr, flush=True)
            ws.run_forever(ping_interval=30, ping_timeout=10)
            print(f"📡 ws.run_forever() returned (closed)", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"⚠️  WebSocket exception (attempt #{connection_attempts}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)

        if _geo_blocked:
            print(f"📡 Geo-blocked detected — switching to REST polling fallback...", file=sys.stderr, flush=True)
            _rest_poll_loop()
            return

        uptime = time.time() - t_start
        if uptime > 60:
            backoff = 1
            print(f"📡 WebSocket was healthy for {uptime:.1f}s — resetting backoff", file=sys.stderr, flush=True)

        print(f"🔄 WebSocket reconnecting in {backoff} s (uptime={uptime:.1f}s, attempt #{connection_attempts})...", file=sys.stderr, flush=True)
        time.sleep(backoff)
        backoff = min(backoff * 2, 30)
