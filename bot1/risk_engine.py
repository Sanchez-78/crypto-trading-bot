import math

class RiskEngine:

    def __init__(self):
        self.max_risk_per_trade = 0.02
        self.max_portfolio_risk = 0.1
        self.max_drawdown = 0.15

    # =========================
    # 🧠 EDGE ESTIMATION
    # =========================
    def compute_edge(self, confidence, winrate):
        # kombinuje model confidence + real performance
        return (confidence * 0.6) + (winrate * 0.4)

    # =========================
    # 📊 POSITION SIZE
    # =========================
    def position_size(self, balance, edge, volatility):
        if edge <= 0:
            return 0

        # Kelly-like
        kelly = edge - (1 - edge)

        # volatility adjustment
        vol_adj = 1 / (1 + volatility * 2)

        size = balance * kelly * vol_adj

        # clamp
        size = max(0, size)
        size = min(size, balance * self.max_risk_per_trade)

        return size

    # =========================
    # 🛑 STOP LOSS / TAKE PROFIT
    # =========================
    def compute_sl_tp(self, price, volatility):
        # ATR-like approximation
        move = volatility * 0.02

        sl = price * (1 - move)
        tp = price * (1 + move * 2)

        return sl, tp

    # =========================
    # 🚨 KILL SWITCH
    # =========================
    def should_trade(self, drawdown, stabilizer_state):
        if drawdown > self.max_drawdown:
            return False

        if stabilizer_state["cooldown"] > 0:
            return False

        return True