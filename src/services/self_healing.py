import time


class SelfHealing:
    def __init__(self):
        self.mode = "NORMAL"

        self.last_heal = 0
        self.cooldown = 120  # sec

        self.recovery_start = None

    # =========================
    # HEAL TRIGGER
    # =========================
    def should_heal(self, metrics):
        health = metrics.get("health", {})
        learning = metrics.get("learning", {})
        equity = metrics.get("equity", {})

        status = health.get("status")
        trend = learning.get("state")
        dd = equity.get("drawdown", 0)

        if status == "BROKEN":
            return "CRITICAL"

        if dd > 0.2:
            return "DRAWDOWN"

        if trend == "DEGRADING":
            return "LEARNING"

        return None

    # =========================
    # APPLY HEAL
    # =========================
    def apply(self, reason, auto_control):
        now = time.time()

        if now - self.last_heal < self.cooldown:
            return

        self.last_heal = now

        print(f"🧠 SELF HEAL TRIGGERED: {reason}")

        # =========================
        # CRITICAL
        # =========================
        if reason == "CRITICAL":
            auto_control.trading_enabled = False
            auto_control.risk_multiplier = 0.2
            self.mode = "PAUSED"

        # =========================
        # DRAWDOWN
        # =========================
        elif reason == "DRAWDOWN":
            auto_control.risk_multiplier = 0.5
            self.mode = "SAFE"

        # =========================
        # LEARNING
        # =========================
        elif reason == "LEARNING":
            auto_control.risk_multiplier = 0.7
            self.mode = "ADAPT"

        self.recovery_start = time.time()

    # =========================
    # RECOVERY
    # =========================
    def recover(self, auto_control):
        if not self.recovery_start:
            return

        elapsed = time.time() - self.recovery_start

        # postupný návrat
        if elapsed > 60:
            auto_control.trading_enabled = True
            auto_control.risk_multiplier = 0.8
            self.mode = "RECOVERING"

        if elapsed > 180:
            auto_control.risk_multiplier = 1.0
            self.mode = "NORMAL"
            self.recovery_start = None

    # =========================
    # MAIN
    # =========================
    def update(self, metrics, auto_control):
        reason = self.should_heal(metrics)

        if reason:
            self.apply(reason, auto_control)

        self.recover(auto_control)

    def get_status(self):
        return {
            "mode": self.mode,
            "recovery": self.recovery_start is not None
        }


self_healing = SelfHealing()