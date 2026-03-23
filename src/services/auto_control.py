class AutoControl:
    def __init__(self):
        self.status = "UNKNOWN"
        self.risk_multiplier = 1.0
        self.trading_enabled = True

    def update(self, metrics):
        health = metrics.get("health", {})
        status = health.get("status", "UNKNOWN")

        self.status = status

        # =========================
        # CONTROL LOGIC
        # =========================

        if status == "BROKEN":
            self.trading_enabled = False
            self.risk_multiplier = 0
            print("🛑 AUTO CONTROL: STOP TRADING")

        elif status == "BAD":
            self.trading_enabled = True
            self.risk_multiplier = 0.5
            print("⚠️ AUTO CONTROL: REDUCE RISK")

        elif status == "RISKY":
            self.trading_enabled = True
            self.risk_multiplier = 0.7
            print("⚠️ AUTO CONTROL: CAUTION MODE")

        elif status == "HEALTHY":
            self.trading_enabled = True
            self.risk_multiplier = 1.2
            print("🚀 AUTO CONTROL: AGGRESSIVE")

        else:
            self.trading_enabled = True
            self.risk_multiplier = 1.0


auto_control = AutoControl()