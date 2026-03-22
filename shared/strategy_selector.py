class StrategySelector:

    def select(self, features):
        regime = features.get("regime")
        volatility = features.get("volatility")

        # =========================
        # 🚀 BULL TREND
        # =========================
        if regime == "BULL_TREND":
            return "TREND_LONG"

        # =========================
        # 🔻 BEAR TREND
        # =========================
        if regime == "BEAR_TREND":
            return "TREND_SHORT"

        # =========================
        # 🌪️ HIGH VOL
        # =========================
        if volatility == "HIGH":
            return "BREAKOUT"

        # =========================
        # 📊 SIDEWAYS
        # =========================
        return "MEAN_REVERSION"