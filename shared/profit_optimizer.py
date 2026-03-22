class ProfitOptimizer:

    def __init__(self):
        self.min_confidence = 0.6
        self.max_trades = 5
        self.min_expected_move = 0.002

    def block(self, signal, confidence, features=None, open_signals=None, meta=None):
        if signal == "HOLD":
            return True

        # 🧠 META CONTROL
        if meta:
            unc = meta.get("uncertainty", 0)

            if unc > 0.3 or confidence < meta.get("min_conf", 0.6):
                print("🚫 Meta blocked")
                return True

        if confidence < self.min_confidence:
            print("🚫 Low confidence")
            return True

        if features:
            trend = features.get("trend")

            if trend == "BULL" and signal == "SELL":
                print("🚫 Against trend")
                return True

            if trend == "BEAR" and signal == "BUY":
                print("🚫 Against trend")
                return True

            atr = features.get("atr_m15", 0)

            if atr < self.min_expected_move:
                print("🚫 Move too small")
                return True

        if open_signals and len(open_signals) >= self.max_trades:
            print("🚫 Too many trades")
            return True

        return False