import time

print("🚀 Starting multi-symbol event-driven BOT SYSTEM")

# =========================
# INIT FIREBASE (optional)
# =========================
try:
    from src.services.firebase_client import init_firebase
    db = init_firebase()
    print("🔥 Firebase initialized")
except Exception as e:
    print("⚠️ Firebase disabled:", e)
    db = None


# =========================
# LOAD CORE SERVICES
# =========================
print("⚙️ Loading services...")

# 🔥 MARKET DATA
from src.services.market_data import fake_market_tick

# 🔥 SIGNAL
import src.services.signal_generator

# 🔥 TRADE
import src.services.trade_executor

# 🔥 PORTFOLIO
import src.services.portfolio_manager
from src.services.portfolio_manager import process_portfolio

# 🔥 EVALUATION
import src.services.evaluator

# 🔥 LEARNING
import src.services.learning_event

# 🔥 PERFORMANCE TRACKING (bonus)
try:
    import src.services.performance_tracker
except:
    pass

print("✅ ALL SERVICES LOADED")


# =========================
# MAIN LOOP
# =========================
def main():
    print("🟢 BOT RUNNING...\n")

    tick_count = 0

    while True:
        try:
            # =========================
            # MARKET TICK
            # =========================
            fake_market_tick()

            # =========================
            # PORTFOLIO UPDATE
            # =========================
            process_portfolio()

            tick_count += 1

            # =========================
            # DEBUG INFO (každých 10 ticků)
            # =========================
            if tick_count % 10 == 0:
                print(f"\n📊 TICKS: {tick_count}")

            time.sleep(1)

        except Exception as e:
            print("❌ MAIN LOOP ERROR:", e)
            time.sleep(2)


# =========================
# ENTRYPOINT
# =========================
if __name__ == "__main__":
    main()