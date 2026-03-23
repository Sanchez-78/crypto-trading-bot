import time

class TradeGuard:
    def __init__(self):
        self.last_trade_time = {}
        self.last_signal_hash = {}
        self.cooldown = 30

    def cooldown_ok(self, symbol):
        now = time.time()
        if symbol not in self.last_trade_time:
            self.last_trade_time[symbol] = 0
        return now - self.last_trade_time[symbol] >= self.cooldown

    def mark_trade(self, symbol):
        self.last_trade_time[symbol] = time.time()

    def is_duplicate(self, symbol, features):
        h = f"{features['trend']}_{round(features['price'],1)}"
        if symbol not in self.last_signal_hash:
            self.last_signal_hash[symbol] = None
        if h == self.last_signal_hash[symbol]:
            return True
        self.last_signal_hash[symbol] = h
        return False