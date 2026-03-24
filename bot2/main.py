# =========================
# MAIN ENTRYPOINT
# =========================

def main():
    print("🚀 BOOTING BOT (REAL DATA MODE + DEBUG)...")

    # =========================
    # FIREBASE INIT
    # =========================
    from src.services.firebase_client import init_firebase, save_bot_stats

    db = init_firebase()

    if db:
        print("✅ DB READY")

        # 🔥 TEST WRITE (klíčové!)
        print("🧪 TEST FIREBASE WRITE...")
        save_bot_stats({
            "test": True,
            "time": "startup"
        })

    else:
        print("❌ DB NOT READY")

    # =========================
    # LOAD SERVICES
    # =========================
    print("🔄 LOADING SERVICES...")

    try:
        import src.services.signal_generator
        print("✅ signal_generator loaded")

        import src.services.trade_executor
        print("✅ trade_executor loaded")

        import src.services.evaluator
        print("✅ evaluator loaded")

        import src.services.portfolio_event
        print("✅ portfolio_event loaded")

        import bot2.learning_event
        print("✅ learning_event loaded")

    except Exception as e:
        print("❌ SERVICE LOAD ERROR:", e)
        return

    print("🔥 ALL SERVICES LOADED")

    # =========================
    # START MARKET DATA
    # =========================
    print("🌐 STARTING REAL MARKET FEED...")

    try:
        import src.services.market_data_service as market_data
        market_data.run()

    except Exception as e:
        print("❌ MARKET DATA ERROR:", e)


# =========================
# LOCAL RUN
# =========================
if __name__ == "__main__":
    main()