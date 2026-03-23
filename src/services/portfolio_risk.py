class PortfolioRisk:

    def __init__(self):
        self.max_risk_per_trade = 0.02

    def calculate_trade_risk(self, balance):
        return balance * self.max_risk_per_trade

    # 🔥 FIX: přidaná metoda pro learning_event
    def get_metrics(self, open_trades, balance):
        total_risk = sum(t.get("risk", 0) for t in open_trades)

        return {
            "open_trades": len(open_trades),
            "total_risk": total_risk,
            "balance": balance
        }


# instance (musí existovat!)
portfolio_risk = PortfolioRisk()