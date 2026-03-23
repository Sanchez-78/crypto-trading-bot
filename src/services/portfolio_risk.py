class PortfolioRisk:

    def __init__(self):
        self.max_risk_per_trade = 0.02
        self.max_open_trades = 5
        self.max_total_risk = 0.1

    def calculate_trade_risk(self, balance):
        return balance * self.max_risk_per_trade

    def can_open_trade(self, *args):
        if len(args) < 2:
            return True

        open_trades = args[0]
        balance = args[1]

        # 🔥 FIX: ensure list
        if not isinstance(open_trades, list):
            print("⚠️ open_trades is not list:", open_trades)
            return True

        if len(open_trades) >= self.max_open_trades:
            print("🛑 BLOCK: too many open trades")
            return False

        total_risk = 0

        for t in open_trades:
            if isinstance(t, dict):
                total_risk += t.get("risk", 0)
            else:
                print("⚠️ invalid trade object:", t)

        if total_risk >= balance * self.max_total_risk:
            print("🛑 BLOCK: too much total risk")
            return False

        return True

    def get_metrics(self, open_trades, balance):
        total_risk = 0

        if isinstance(open_trades, list):
            for t in open_trades:
                if isinstance(t, dict):
                    total_risk += t.get("risk", 0)

        return {
            "open_trades": len(open_trades) if isinstance(open_trades, list) else 0,
            "total_risk": total_risk,
            "balance": balance
        }


portfolio_risk = PortfolioRisk()