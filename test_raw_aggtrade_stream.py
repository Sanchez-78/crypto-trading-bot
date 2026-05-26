#!/usr/bin/env python3
"""Raw WebSocket probe for Binance aggTrade stream."""

import websocket
import json
import sys
import time

def test_raw_aggtrade_stream():
    """Connect directly to /market/ws/ and log first aggTrade event."""
    symbol = "btcusdt"
    stream_name = f"{symbol}@aggTrade"

    # Exact routed URL from spec
    url = f"wss://fstream.binance.com/market/ws/{stream_name}"

    print(f"[PROBE] Testing raw stream: {url}")
    print(f"[PROBE] Stream name: {stream_name}")
    print(f"[PROBE] Connection timeout: 10s, recv timeout: 15s")
    print("-" * 60)

    try:
        ws = websocket.create_connection(url, timeout=10)
        print(f"[SUCCESS] WebSocket connected to {url}")
        print(f"[PROBE] Waiting for first aggTrade event (max 15s)...")

        event_count = 0
        start_time = time.time()

        while event_count < 3:  # Collect 3 events to verify stream health
            try:
                msg = ws.recv()
                if msg:
                    data = json.loads(msg)
                    event_count += 1

                    # Extract relevant fields
                    price = data.get("p", "N/A")
                    qty = data.get("q", "N/A")
                    trade_id = data.get("a", "N/A")
                    timestamp = data.get("T", "N/A")

                    elapsed = time.time() - start_time

                    print(f"\n[EVENT {event_count}] aggTrade received at {elapsed:.2f}s")
                    print(f"  price={price} qty={qty} trade_id={trade_id} timestamp={timestamp}")
                    print(f"  Raw: {msg[:200]}...")

            except websocket.WebSocketTimeoutException:
                elapsed = time.time() - start_time
                if elapsed > 15:
                    print(f"\n[TIMEOUT] No event received after {elapsed:.1f}s")
                    break
                continue
            except json.JSONDecodeError as e:
                print(f"\n[PARSE_ERROR] Failed to parse message: {e}")
                print(f"  Raw data: {msg[:100]}")
                break

        ws.close()
        print("\n" + "-" * 60)
        print(f"[RESULT] Successfully received {event_count} aggTrade event(s)")
        return event_count > 0

    except websocket.WebSocketBadStatusException as e:
        print(f"[FAIL_HANDSHAKE] WebSocket handshake failed: {e}")
        print(f"[FAIL_REASON] Possible invalid URL, routing, or subscription issue")
        return False
    except websocket.WebSocketConnectionClosedException as e:
        print(f"[FAIL_CLOSED] Connection closed: {e}")
        return False
    except websocket.WebSocketTimeoutException as e:
        print(f"[FAIL_TIMEOUT] Connection timeout after 10s: {e}")
        print(f"[FAIL_REASON] Endpoint not responding or network issue")
        return False
    except Exception as e:
        print(f"[FAIL_ERROR] {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    success = test_raw_aggtrade_stream()
    sys.exit(0 if success else 1)
