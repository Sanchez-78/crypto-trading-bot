class PortfolioManager:
    def __init__(self):
        self.open_trades = []
        self.trade_history = []

    def open_trade(self, s, a, p, c):
        t = {"symbol": s, "action": a, "entry": p, "confidence": c}
        self.open_trades.append(t)
        return t, "OPEN"

    def update_trades(self, prices):
        closed = []

        for t in list(self.open_trades):
            p = prices[t["symbol"]]
            entry = t["entry"]

            change = (p - entry) / entry if t["action"] == "BUY" else (entry - p) / entry

            if abs(change) > 0.001:
                result = "WIN" if change > 0 else "LOSS"
                t["profit"] = change
                t["result"] = result

                self.trade_history.append(t)
                self.open_trades.remove(t)

                closed.append((t, change, result))

        return closed

    def print_status(self):
        print(f"Open: {len(self.open_trades)} Closed: {len(self.trade_history)}")