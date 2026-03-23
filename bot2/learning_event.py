import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import time

# =========================
# GLOBALS
# =========================
db = None

last_write_time = 0
last_metrics = None
trade_counter = 0

# LIMIT CONFIG
MIN_TIME_INTERVAL = 10     # max 1 write / 10s
BATCH_SIZE = 10            # každých 10 trade
CHANGE_THRESHOLD = 0.01    # změna winrate


# =========================
# INIT FIREBASE
# =========================
def init_firebase():
    global db

    print("\n🔥 INIT FIREBASE START")

    try:
        if not firebase_admin._apps:
            firebase_env = os.environ.get("FIREBASE_CREDENTIALS")

            if firebase_env:
                print("🔍 Using ENV credentials")

                try:
                    cred_dict = json.loads(firebase_env)
                    cred = credentials.Certificate(cred_dict)

                    print(f"👉 PROJECT: {cred.project_id}")

                    firebase_admin.initialize_app(cred)
                    print("✅ Firebase initialized")

                except Exception as e:
                    print(f"❌ JSON ERROR: {e}")
                    return None
            else:
                print("❌ NO FIREBASE_CREDENTIALS")
                return None

        db = firestore.client()
        print("🔥 Firestore READY")

        # TEST WRITE
        try:
            db.collection("debug").add({
                "status": "init_ok",
                "ts": time.time()
            })
            print("🔥 TEST WRITE OK")
        except Exception as e:
            print(f"❌ TEST WRITE FAILED: {e}")

        return db

    except Exception as e:
        print(f"❌ INIT ERROR: {e}")
        return None


db = init_firebase()


# =========================
# SMART WRITE DECISION
# =========================
def should_write(metrics):
    global last_write_time, last_metrics, trade_counter

    now = time.time()

    # 1️⃣ batch trigger
    if trade_counter % BATCH_SIZE == 0:
        print("📦 BATCH TRIGGER")
        return True

    # 2️⃣ time fallback
    if now - last_write_time > MIN_TIME_INTERVAL:
        print("⏱ TIME TRIGGER")
        return True

    # 3️⃣ change detection
    if last_metrics:
        old = last_metrics.get("winrate", 0)
        new = metrics.get("winrate", 0)

        if abs(new - old) > CHANGE_THRESHOLD:
            print("📈 CHANGE TRIGGER")
            return True

    return False


# =========================
# MAIN METRICS WRITE
# =========================
def smart_write(metrics):
    global last_write_time, last_metrics, trade_counter

    trade_counter += 1

    print(f"📡 WRITE CHECK (trade #{trade_counter})")

    if not db:
        print("❌ DB NOT READY")
        return

    if not should_write(metrics):
        print("⏳ SKIP WRITE")
        return

    try:
        payload = {
            **metrics,
            "timestamp": time.time()
        }

        print("📡 WRITING METRICS:", payload)

        db.collection("metrics").document("latest").set(payload)

        last_write_time = time.time()
        last_metrics = metrics

        print("🔥 FIREBASE WRITE OK")

    except Exception as e:
        print("❌ FIREBASE ERROR:", e)


# =========================
# TRADE LOGGING (OPTIONAL)
# =========================
def log_trade(trade):
    if not db:
        return

    try:
        db.collection("trades").add({
            "symbol": trade.get("symbol"),
            "pnl": trade.get("evaluation", {}).get("profit"),
            "result": trade.get("evaluation", {}).get("result"),
            "timestamp": time.time()
        })

        print("📝 TRADE LOGGED")

    except Exception as e:
        print("❌ TRADE LOG ERROR:", e)