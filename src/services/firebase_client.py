# =========================
# MAIN ENTRYPOINT
# =========================

def main():
    print("🚀 BOOTING BOT (REAL DATA MODE)...")

    from src.services.firebase_client import init_firebase

    # 🔥 INIT FIREBASE
    db = init_firebase()

    if not db:
        print("⚠️ DB NOT READY (běží bez ukládání)")
    else:
        print("✅ DB READY")

    # =========================
    # LOAD SERVICES
    # =========================
    import src.services.signal_generator
    import src.services.trade_executor
    import src.services.evaluator
    import src.services.portfolio_event
    import bot2.learning_event

    print("🔥 ALL SERVICES LOADED")

    # =========================
    # START REAL MARKET DATA
    # =========================
    import src.services.market_data_service as market_data

    print("🌐 STARTING REAL MARKET FEED...")
    market_data.run()


# =========================
# LOCAL RUN (optional)
# =========================
if __name__ == "__main__":
    main()