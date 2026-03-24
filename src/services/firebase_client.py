def init_firebase():
    global db

    try:
        print("🔥 INIT FIREBASE CALLED")

        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase reused")
            return db

        import os, json, base64

        # =========================
        # 1. BASE64 (Railway BEST)
        # =========================
        base64_key = os.getenv("FIREBASE_KEY_BASE64")

        if base64_key:
            print("🔥 Using BASE64 ENV key")

            decoded = base64.b64decode(base64_key).decode("utf-8")
            cred_dict = json.loads(decoded)

            cred = credentials.Certificate(cred_dict)

        # =========================
        # 2. RAW JSON ENV
        # =========================
        elif os.getenv("FIREBASE_CREDENTIALS"):
            print("🔥 Using RAW ENV key")

            cred_dict = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
            cred = credentials.Certificate(cred_dict)

        # =========================
        # 3. FILE FALLBACK
        # =========================
        else:
            print("🔥 Using local file")

            cred = credentials.Certificate("firebase_key.json")

        firebase_admin.initialize_app(cred)
        db = firestore.client()

        print("🔥 Firebase initialized OK")
        return db

    except Exception as e:
        print("❌ Firebase init error:", e)
        db = None
        return None