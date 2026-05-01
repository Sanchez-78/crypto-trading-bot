class TrailingStop:

    def __init__(self):
        self.trail_factor = 1.5  # násobek ATR
        self.break_even_trigger = 1.0  # kdy posunout na BE

    # =========================
    # 📈 UPDATE SL
    # =========================
    def update(self, trade, current_price, atr):
        signal = trade["signal"]
        entry = trade["price"]
        sl = trade.get("sl")

        if not sl:
            return sl

        # =========================
        # 🟢 BUY
        # =========================
        if signal == "BUY":
            profit = (current_price - entry) / entry

            # break even — BUG-003 fix: normalize ATR to % before comparing with profit
            atr_pct = atr / entry if entry > 0 else 0.0
            if profit > atr_pct * self.break_even_trigger:
                sl = max(sl, entry)

            # trailing
            new_sl = current_price - atr * self.trail_factor
            sl = max(sl, new_sl)

        # =========================
        # 🔴 SELL
        # =========================
        elif signal == "SELL":
            profit = (entry - current_price) / entry

            # break even — BUG-003 fix: normalize ATR to % before comparing with profit
            atr_pct = atr / entry if entry > 0 else 0.0
            if profit > atr_pct * self.break_even_trigger:
                sl = min(sl, entry)

            # trailing
            new_sl = current_price + atr * self.trail_factor
            sl = min(sl, new_sl)

        return sl