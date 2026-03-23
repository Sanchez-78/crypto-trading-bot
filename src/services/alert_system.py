import time


class AlertSystem:
    def __init__(self):
        self.last_alert_time = {}
        self.cooldown = 60  # sec (anti spam)

    def can_alert(self, key):
        now = time.time()

        if key not in self.last_alert_time:
            self.last_alert_time[key] = now
            return True

        if now - self.last_alert_time[key] > self.cooldown:
            self.last_alert_time[key] = now
            return True

        return False

    # =========================
    # ALERTS
    # =========================
    def send(self, key, message):
        if not self.can_alert(key):
            return

        print(f"🚨 ALERT [{key}] {message}")

        # 🔥 ZDE můžeš přidat:
        # send_telegram(message)
        # send_email(message)
        # send_webhook(message)

    # =========================
    # CHECK METRICS
    # =========================
    def check_metrics(self, metrics):
        health = metrics.get("health", {})
        perf = metrics.get("performance", {})
        equity = metrics.get("equity", {})
        learning = metrics.get("learning", {})

        status = health.get("status")
        drawdown = equity.get("drawdown", 0)
        winrate = perf.get("winrate", 0)
        trend = learning.get("trend")

        # =========================
        # CRITICAL
        # =========================
        if status == "BROKEN":
            self.send("BROKEN", "🛑 BOT STOPPED (BROKEN)")

        if drawdown > 0.2:
            self.send("DRAWDOWN", f"📉 High DD: {drawdown:.2%}")

        # =========================
        # WARNING
        # =========================
        if status == "RISKY":
            self.send("RISKY", "⚠️ Bot in RISKY state")

        if trend == "WORSENING":
            self.send("TREND", "📉 Performance worsening")

        # =========================
        # POSITIVE
        # =========================
        if status == "HEALTHY":
            self.send("HEALTHY", "🚀 Bot performing well")

        if winrate > 0.6:
            self.send("WINRATE", f"🎯 High winrate: {winrate:.2f}")

    # =========================
    # TRADE ALERT
    # =========================
    def on_trade(self, trade):
        result = trade["evaluation"]["result"]
        pnl = trade["evaluation"]["profit"]
        symbol = trade["symbol"]

        if result == "WIN":
            self.send("WIN", f"💰 {symbol} WIN {pnl:.4f}")

        elif result == "LOSS":
            self.send("LOSS", f"❌ {symbol} LOSS {pnl:.4f}")

        if pnl > 0.01:
            self.send("BIG_WIN", f"🚀 BIG PROFIT {symbol} {pnl:.2%}")


alert_system = AlertSystem()