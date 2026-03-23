class RiskManager:
    def __init__(self):
        self.balance = 1000
        self.max_risk_per_trade = 0.01
        self.max_drawdown = 0.2

        self.equity_peak = self.balance

    def get_position_size(self, confidence):
        risk = self.balance * self.max_risk_per_trade

        # confidence scaling
        size = risk * (0.5 + confidence)

        return size

    def update_balance(self, pnl):
        self.balance += self.balance * pnl

        self.equity_peak = max(self.equity_peak, self.balance)

    def is_drawdown_exceeded(self):
        dd = (self.equity_peak - self.balance) / self.equity_peak
        return dd > self.max_drawdown


risk_manager = RiskManager()