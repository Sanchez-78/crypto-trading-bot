class PortfolioRisk:

    def __init__(self):
        self.max_risk_per_trade = 0.02
        self.max_open_trades = 5
        self.max_total_risk = 0.1  # 10 % kapitálu

    # =========================
    # BASIC RISK
    # =========================
    def calculate_trade_risk(self, balance):
        return balance * self.max_risk_per_trade

    # =========================
    # 🔥 FIX: kontrola otevření trade
    # =========================
    def can_open_trade(self, open_trades, balance):
        if len(open_trades) >= self.max_open_trades:
            print("🛑 BLOCK: too many open trades")
            return False

        total_risk = sum(t.get("risk", 0) for t in open_trades)

        if total_risk >= balance * self.max_total_risk:
            print("🛑 BLOCK: too much total risk")
            return False

        return True

    # =========================
    # METRICS (pro learning)
    # =========================
    def get_metrics(self, open_trades, balance):
        total_risk = sum(t.get("risk", 0) for t in open_trades)

        return {
            "open_trades": len(open_trades),
            "total_risk": total_risk,
            "balance": balance
        }


# instance (MUSÍ být)
portfolio_risk = PortfolioRisk()