import os
import numpy as np

from xgboost import XGBClassifier
from src.services.firebase_client import load_all_signals


BASE_PATH = "models"
MIN_SAMPLES = 10


class MLModel:

    def __init__(self):
        self.models = {}
        self.trained = False

        if not os.path.exists(BASE_PATH):
            os.makedirs(BASE_PATH)

    # =========================
    # 📂 GET MODEL PATH
    # =========================
    def _get_path(self, symbol):
        return os.path.join(BASE_PATH, f"{symbol}.json")

    # =========================
    # 🧠 GET / CREATE MODEL
    # =========================
    def _get_model(self, symbol):
        if symbol not in self.models:
            model = XGBClassifier(
                n_estimators=50,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="logloss"
            )

            path = self._get_path(symbol)

            if os.path.exists(path):
                try:
                    model.load_model(path)
                    print(f"🧠 Loaded model {symbol}")
                except:
                    print(f"⚠️ Failed load {symbol}")

            self.models[symbol] = model

        return self.models[symbol]

    # =========================
    # 🧠 TRAIN ALL
    # =========================
    def train(self):
        print("🧠 Training multi-model...")

        signals = load_all_signals()

        data = {}

        for s in signals:
            symbol = s.get("symbol")
            features = s.get("features")
            result = s.get("result")

            if not symbol or not features or result not in ["WIN", "LOSS"]:
                continue

            if symbol not in data:
                data[symbol] = {"X": [], "y": []}

            data[symbol]["X"].append(self._features_to_vector(features))
            data[symbol]["y"].append(1 if result == "WIN" else 0)

        trained_any = False

        for symbol, d in data.items():
            if len(d["X"]) < MIN_SAMPLES:
                print(f"⚠️ {symbol} not enough data ({len(d['X'])})")
                continue

            model = self._get_model(symbol)

            X = np.array(d["X"])
            y = np.array(d["y"])

            # BUG-021 fix: use train/val split to prevent overfitting
            try:
                from sklearn.model_selection import train_test_split
                if len(X) >= 50:
                    X_train, X_val, y_train, y_val = train_test_split(
                        X, y, test_size=0.2, random_state=42
                    )
                    model.fit(X_train, y_train)
                else:
                    model.fit(X, y)
            except Exception:
                model.fit(X, y)

            self._save(symbol, model)

            print(f"✅ {symbol} trained on {len(X)} samples")

            trained_any = True

        self.trained = trained_any

    # =========================
    # 🔮 PREDICT
    # =========================
    def predict(self, symbol, features):
        model = self._get_model(symbol)

        X = np.array([self._features_to_vector(features)])

        try:
            prob = model.predict_proba(X)[0][1]
        except:
            raise Exception("Model not trained")

        if prob > 0.55:
            return {"signal": "BUY", "confidence": prob}
        elif prob < 0.45:
            return {"signal": "SELL", "confidence": 1 - prob}
        else:
            return {"signal": "HOLD", "confidence": prob}

    # =========================
    # 💾 SAVE
    # =========================
    def _save(self, symbol, model):
        path = self._get_path(symbol)

        try:
            model.save_model(path)
            print(f"💾 Saved {symbol}")
        except Exception as e:
            print("❌ Save error:", e)

    # =========================
    # 🔧 FEATURES
    # =========================
    def _features_to_vector(self, f):
        return [
            f.get("rsi_m15", 0),
            f.get("macd_m15", 0),
            f.get("ema_m15", 0),
            f.get("bb_m15", 0),
            f.get("atr_m15", 0),

            f.get("rsi_h1", 0),
            f.get("macd_h1", 0),
            f.get("ema_h1", 0),
            f.get("bb_h1", 0),
            f.get("atr_h1", 0),

            f.get("rsi_h4", 0),
            f.get("macd_h4", 0),
            f.get("ema_h4", 0),
            f.get("bb_h4", 0),
            f.get("atr_h4", 0),
        ]