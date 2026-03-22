class Stabilizer:

    def __init__(self):
        self.min_confidence = 0.6
        self.loss_streak = 0
        self.cooldown = 0

    # =========================
    # 🧠 UPDATE STATE
    # =========================
    def update(self, signals):
        recent = signals[-10:]

        losses = sum(1 for s in recent if s.get("result") == "LOSS")
        wins = sum(1 for s in recent if s.get("result") == "WIN")

        if losses > wins:
            self.loss_streak += 1
        else:
            self.loss_streak = max(0, self.loss_streak - 1)

        if self.loss_streak >= 3:
            self.cooldown = 3
            print("🛑 Activating cooldown")

        total = wins + losses
        winrate = (wins / total) if total > 0 else 0

        if winrate < 0.3:
            self.min_confidence = 0.7
        elif winrate > 0.6:
            self.min_confidence = 0.5
        else:
            self.min_confidence = 0.6

        print("🧠 Stabilizer:",
              {"min_conf": self.min_confidence,
               "loss_streak": self.loss_streak,
               "cooldown": self.cooldown})

    # =========================
    # 📦 RETURN STATE ONLY
    # =========================
    def get_state(self):
        return {
            "min_conf": self.min_confidence,
            "cooldown": self.cooldown,
            "loss_streak": self.loss_streak
        }