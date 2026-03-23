class PortfolioRisk:
    def __init__(self):
        self.max_open_trades = 5
        self.max_portfolio_risk = 0.05  # 5% kapitálu
        self.max_symbol_exposure = 0.3  # 30% na jeden symbol

    def get_total_exposure(self, open_trades):
        return sum(t["size"] for t in open_trades.values())

    def get_symbol_exposure(self, symbol, open_trades):
        return sum(
            t["size"] for s, t in open_trades.items() if s == symbol
        )

    def can_open_trade(self, symbol, size, open_trades, balance):
        # =========================
        # MAX TRADES
        # =========================
        if len(open_trades) >= self.max_open_trades:
            print("🛑 PORTFOLIO: MAX TRADES")
            return False

        # =========================
        # TOTAL RISK
        # =========================
        total_exposure = self.get_total_exposure(open_trades)
        if (total_exposure + size) > balance * self.max_portfolio_risk:
            print("🛑 PORTFOLIO: MAX RISK")
            return False

        # =========================
        # SYMBOL EXPOSURE
        # =========================
        symbol_exposure = self.get_symbol_exposure(symbol, open_trades)
        if (symbol_exposure + size) > balance * self.max_symbol_exposure:
            print("🛑 PORTFOLIO: SYMBOL OVEREXPOSED")
            return False

        return True


portfolio_risk = PortfolioRisk()