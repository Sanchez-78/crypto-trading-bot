import time


class PortfolioManager:

    def __init__(self):
        self.trades = []
        self.trade_id = 0

        # 🔥 nastavení
        self.max_positions = 3
        self.pyramiding_limit = 2
        self.trailing_enabled = True

    # =========================
    # 🆔 ID
    # =========================
    def next_id(self):
        self.trade_id += 1
        return self.trade_id

    # =========================
    # 📊 OPEN TRADE (FIXED)
    # =========================
    def open_trade(self, symbol, action, price, size, sl, tp, confidence):
        if len(self.trades) >= self.max_positions:
            return None, "max_positions_reached"

        trade = {
            "id": self.next_id(),
            "symbol": symbol,
            "action": action,
            "entry": price,
            "size": size,
            "stop_loss": sl,
            "take_profit": tp,
            "confidence": confidence,
            "status": "OPEN",
            "pyramids": 0,
            "created_at": time.time(),
            "highest_price": price,
            "lowest_price": price
        }

        self.trades.append(trade)

        print(f"📈 OPEN {symbol} {price} size={round(size,4)}")

        return trade, "opened"

    # =========================
    # 📈 PYRAMIDING
    # =========================
    def try_pyramid(self, trade, price):
        if trade["pyramids"] >= self.pyramiding_limit:
            return

        if trade["action"] == "BUY":
            if price > trade["entry"] * 1.01:  # +1%
                trade["size"] *= 1.5
                trade["pyramids"] += 1
                print(f"📊 PYRAMID BUY {trade['id']} new size={trade['size']}")

        elif trade["action"] == "SELL":
            if price < trade["entry"] * 0.99:
                trade["size"] *= 1.5
                trade["pyramids"] += 1
                print(f"📊 PYRAMID SELL {trade['id']} new size={trade['size']}")

    # =========================
    # 🔁 TRAILING STOP
    # =========================
    def update_trailing(self, trade, price):
        if not self.trailing_enabled:
            return

        if trade["action"] == "BUY":
            if price > trade["highest_price"]:
                trade["highest_price"] = price

                # posun SL
                new_sl = price * 0.995  # 0.5% trailing
                if new_sl > trade["stop_loss"]:
                    trade["stop_loss"] = new_sl
                    print(f"🔒 TRAIL SL BUY {trade['id']} -> {round(new_sl, 2)}")

        elif trade["action"] == "SELL":
            if price < trade["lowest_price"]:
                trade["lowest_price"] = price

                new_sl = price * 1.005
                if new_sl < trade["stop_loss"]:
                    trade["stop_loss"] = new_sl
                    print(f"🔒 TRAIL SL SELL {trade['id']} -> {round(new_sl, 2)}")

    # =========================
    # ❌ CLOSE TRADE
    # =========================
    def close_trade(self, trade, price):
        if trade["action"] == "BUY":
            pnl = (price - trade["entry"]) / trade["entry"]
        else:
            pnl = (trade["entry"] - price) / trade["entry"]

        trade["status"] = "CLOSED"
        trade["exit_price"] = price
        trade["pnl"] = pnl
        trade["closed_at"] = time.time()

        result = "WIN" if pnl > 0 else "LOSS"

        print(f"❌ CLOSE {trade['id']} {result} pnl={round(pnl,4)}")

        return trade, pnl, result

    # =========================
    # 🔄 UPDATE TRADES
    # =========================
    def update_trades(self, prices):
        closed = []

        for trade in list(self.trades):
            if trade["status"] != "OPEN":
                continue

            symbol = trade["symbol"]
            price = prices.get(symbol)

            if price is None:
                continue

            # trailing
            self.update_trailing(trade, price)

            # pyramiding
            self.try_pyramid(trade, price)

            sl = trade["stop_loss"]
            tp = trade["take_profit"]

            hit_sl = False
            hit_tp = False

            if trade["action"] == "BUY":
                if sl and price <= sl:
                    hit_sl = True
                if tp and price >= tp:
                    hit_tp = True

            elif trade["action"] == "SELL":
                if sl and price >= sl:
                    hit_sl = True
                if tp and price <= tp:
                    hit_tp = True

            if hit_sl or hit_tp:
                closed_trade = self.close_trade(trade, price)
                closed.append(closed_trade)
                self.trades.remove(trade)

        return closed

    # =========================
    # 📊 RISK CHECK
    # =========================
    def can_open(self, balance):
        return len(self.trades) < self.max_positions