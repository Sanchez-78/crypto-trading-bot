import websocket
import json
import threading
import time


class MarketStream:
    def __init__(self, symbols):
        self.symbols = symbols
        self.prices = {}
        self.ws = None

        self.running = True
        self.last_update = time.time()

        self.reconnect_delay = 1  # start
        self.max_delay = 60

    # ─────────────────────────────
    # 📩 MESSAGE
    # ─────────────────────────────
    def _on_message(self, ws, message):
        data = json.loads(message)

        if "data" in data:
            data = data["data"]

        if "s" in data and "c" in data:
            symbol = data["s"]
            price = float(data["c"])

            self.prices[symbol] = price
            self.last_update = time.time()

    # ─────────────────────────────
    # ❌ ERROR
    # ─────────────────────────────
    def _on_error(self, ws, error):
        print("❌ WS ERROR:", error)

    # ─────────────────────────────
    # 🔌 CLOSE → RECONNECT
    # ─────────────────────────────
    def _on_close(self, ws, *args):
        print("⚠️ WS CLOSED → reconnecting...")
        self._reconnect()

    # ─────────────────────────────
    # 🔓 OPEN
    # ─────────────────────────────
    def _on_open(self, ws):
        print("🔥 WS CONNECTED")

        # reset delay
        self.reconnect_delay = 1

    # ─────────────────────────────
    # 🔁 RECONNECT LOGIC
    # ─────────────────────────────
    def _reconnect(self):
        if not self.running:
            return

        print(f"⏳ reconnect za {self.reconnect_delay}s")

        time.sleep(self.reconnect_delay)

        # exponential backoff
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_delay)

        self.start()

    # ─────────────────────────────
    # 🔗 START CONNECTION
    # ─────────────────────────────
    def start(self):
        streams = "/".join([f"{s.lower()}@ticker" for s in self.symbols])
        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        thread = threading.Thread(target=self.ws.run_forever)
        thread.daemon = True
        thread.start()

        # 🔥 heartbeat watcher
        watcher = threading.Thread(target=self._watchdog)
        watcher.daemon = True
        watcher.start()

    # ─────────────────────────────
    # ❤️ WATCHDOG (HLÍDÁ TICHÉ SPOJENÍ)
    # ─────────────────────────────
    def _watchdog(self):
        while self.running:
            time.sleep(10)

            if time.time() - self.last_update > 20:
                print("⚠️ žádná data → restart WS")

                try:
                    self.ws.close()
                except:
                    pass

                self._reconnect()

    # ─────────────────────────────
    # 📊 GET PRICES
    # ─────────────────────────────
    def get_prices(self):
        return self.prices

    # ─────────────────────────────
    # 🛑 STOP
    # ─────────────────────────────
    def stop(self):
        self.running = False

        if self.ws:
            self.ws.close()