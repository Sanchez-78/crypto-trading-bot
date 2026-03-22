import numpy as np

class MetaController:

    def __init__(self):
        self.bias = 0
        self.scale = 1
        self.trust = 1.0

        self.calibration = {"a": 1.0, "b": 0.0}

    # =========================
    # 🧠 SELF EVAL
    # =========================
    def evaluate(self, raw_score):
        x = raw_score * self.scale + self.bias

        # logistická kalibrace
        a = self.calibration["a"]
        b = self.calibration["b"]

        calibrated = 1 / (1 + np.exp(-(a * x + b)))

        return max(0, min(1, calibrated))

    # =========================
    # ❓ UNCERTAINTY
    # =========================
    def uncertainty(self, signals):
        return np.std(signals) if signals else 0.5

    # =========================
    # 🚦 TRUST GATE
    # =========================
    def allow_trade(self, confidence, uncertainty):
        if uncertainty > 0.3:
            return False
        if confidence < 0.6:
            return False
        return True

    # =========================
    # 🔁 APPLY BOT2 FEEDBACK
    # =========================
    def apply_feedback(self, fb):

        if "bias" in fb:
            self.bias += fb["bias"]

        if "scale" in fb:
            self.scale *= fb["scale"]

        if "calibration" in fb:
            self.calibration = fb["calibration"]

        if "trust" in fb:
            self.trust = fb["trust"]