class DataManager:
    def __init__(self):
        self.pattern_cache = {}

    # 🔥 COMPRESS TRADE
    def compress_trade(self, trade):
        f = trade.get("features", {})

        return {
            "symbol": trade.get("symbol"),
            "signal": trade.get("signal"),
            "profit": round(trade.get("profit", 0), 5),
            "result": trade.get("result"),

            "f": {
                "t": round(f.get("trend_strength", 0), 4),
                "v": round(f.get("vol_10", 0), 4),
                "m": round(f.get("momentum", 0), 4),
                "r": f.get("market_regime", "R")[0],
            },

            "ts": trade.get("timestamp"),
        }

    # 🔥 SMART DELETE
    def should_delete(self, trade):
        f = trade.get("features", {})

        key = (
            round(f.get("trend_strength", 0), 2),
            round(f.get("vol_10", 0), 2),
            trade.get("signal"),
        )

        count = self.pattern_cache.get(key, 0)
        self.pattern_cache[key] = count + 1

        # příliš mnoho stejných patternů
        if count > 30:
            return True

        # low value trades
        if abs(trade.get("profit", 0)) < 0.0002:
            return True

        return False