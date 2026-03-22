class RiskEngine:

    def __init__(self):
        self.max_risk_per_trade = 0.02
        self.max_drawdown = 0.15

    # =========================
    # 🧠 EDGE
    # =========================
    def compute_edge(self, confidence, winrate):
        return (confidence * 0.6) + (winrate * 0.4)

    # =========================
    # 💰 POSITION SIZE
    # =========================
    def position_size(self, balance, entry, stop_loss, edge):
        if stop_loss is None:
            return 0

        risk_per_unit = abs(entry - stop_loss)

        if risk_per_unit == 0:
            return 0

        capital_risk = balance * self.max_risk_per_trade

        # kolik jednotek můžu koupit
        size = capital_risk / risk_per_unit

        # edge scaling
        size *= max(0.1, edge)

        return size

    # =========================
    # 🚨 KILL SWITCH
    # =========================
    def should_trade(self, drawdown, stabilizer_state):
        if drawdown > self.max_drawdown:
            return False

        if stabilizer_state["cooldown"] > 0:
            return False

        return True