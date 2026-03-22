import time


class TradeGuard:

    def __init__(self):
        self.last_trade_time = {}
        self.cooldown = 30  # sekund

        self.last_signal_hash = None

    # =========================
    # ⏱️ COOLDOWN
    # =========================
    def cooldown_ok(self, symbol):
        now = time.time()

        if symbol not in self.last_trade_time:
            self.last_trade_time[symbol] = 0

        if now - self.last_trade_time[symbol] < self.cooldown:
            return False

        return True

    def mark_trade(self, symbol):
        self.last_trade_time[symbol] = time.time()

    # =========================
    # 🔁 DUPLICATE FILTER
    # =========================
    def is_duplicate(self, features):
        h = f"{features['trend']}_{round(features['price'], 1)}"

        if h == self.last_signal_hash:
            return True

        self.last_signal_hash = h
        return False