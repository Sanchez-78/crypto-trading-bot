class VolatilityFilter:

    def __init__(self):
        # thresholds (laditelné)
        self.low = 0.002
        self.high = 0.02

    def classify(self, features):
        atr = features.get("atr_m15", 0)

        if atr < self.low:
            return "LOW"
        elif atr > self.high:
            return "HIGH"
        return "NORMAL"

    def allow(self, features):
        state = self.classify(features)

        if state == "LOW":
            return False  # ❌ žádný trade

        return True  # NORMAL + HIGH povoleno