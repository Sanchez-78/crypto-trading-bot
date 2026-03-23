from src.services.auto_control import auto_control


class RiskManager:
    def __init__(self):
        # =========================
        # ACCOUNT
        # =========================
        self.balance = 1000.0
        self.equity_peak = self.balance

        # =========================
        # RISK CONFIG
        # =========================
        self.max_risk_per_trade = 0.01   # 1%
        self.max_drawdown = 0.20         # 20%
        self.min_trade_size = 1

        # =========================
        # CONTROL
        # =========================
        self.consecutive_losses = 0
        self.max_consecutive_losses = 5

    # =========================
    # POSITION SIZING
    # =========================
    def get_position_size(self, confidence):
        """
        Dynamic sizing:
        - base risk
        - confidence scaling
        - auto control scaling
        """

        base_risk = self.balance * self.max_risk_per_trade

        # confidence scaling (0.5 → 1.5x)
        confidence_factor = 0.5 + confidence

        size = base_risk * confidence_factor

        # 🔥 AUTO CONTROL (status based)
        size *= auto_control.risk_multiplier

        # bezpečnostní minimum
        size = max(size, self.min_trade_size)

        return round(size, 2)

    # =========================
    # BALANCE UPDATE
    # =========================
    def update_balance(self, pnl):
        """
        pnl = např. 0.01 = +1%
        """

        old_balance = self.balance

        self.balance *= (1 + pnl)

        # peak update
        self.equity_peak = max(self.equity_peak, self.balance)

        # =========================
        # LOSS TRACKING
        # =========================
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        print("💰 BALANCE UPDATE")
        print(f"   old: {old_balance:.2f}")
        print(f"   new: {self.balance:.2f}")
        print(f"   losses in row: {self.consecutive_losses}")

    # =========================
    # DRAWDOWN CHECK
    # =========================
    def get_drawdown(self):
        if self.equity_peak == 0:
            return 0

        return (self.equity_peak - self.balance) / self.equity_peak

    def is_drawdown_exceeded(self):
        dd = self.get_drawdown()

        if dd > self.max_drawdown:
            print(f"🛑 MAX DRAWDOWN EXCEEDED: {dd:.2%}")
            return True

        return False

    # =========================
    # LOSS STREAK PROTECTION
    # =========================
    def is_loss_streak_exceeded(self):
        if self.consecutive_losses >= self.max_consecutive_losses:
            print("🛑 LOSS STREAK EXCEEDED")
            return True

        return False

    # =========================
    # GLOBAL RISK CHECK
    # =========================
    def can_trade(self):
        """
        Kompletní risk gate
        """

        if self.is_drawdown_exceeded():
            return False

        if self.is_loss_streak_exceeded():
            return False

        if not auto_control.trading_enabled:
            return False

        return True

    # =========================
    # DEBUG STATUS
    # =========================
    def get_status(self):
        return {
            "balance": self.balance,
            "drawdown": self.get_drawdown(),
            "consecutive_losses": self.consecutive_losses,
            "risk_multiplier": auto_control.risk_multiplier,
            "trading_enabled": auto_control.trading_enabled
        }


# =========================
# SINGLETON
# =========================
risk_manager = RiskManager()