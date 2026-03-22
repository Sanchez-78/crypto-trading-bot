import numpy as np

class MetaEvaluator:

    def evaluate(self, trades):

        preds = []
        real = []

        for t in trades:
            preds.append(t["confidence"])
            real.append(1 if t["result"] == "WIN" else 0)

        preds = np.array(preds)
        real = np.array(real)

        calibration_error = np.mean(np.abs(preds - real))
        bias = np.mean(preds - real)
        accuracy = np.mean((preds > 0.5) == real)
        sharpness = np.std(preds)

        return {
            "calibration_error": calibration_error,
            "bias": bias,
            "accuracy": accuracy,
            "sharpness": sharpness
        }

    def feedback(self, metrics):

        fb = {}

        if metrics["bias"] > 0.2:
            fb["bias"] = -0.1
            fb["scale"] = 0.9

        if metrics["calibration_error"] > 0.3:
            fb["calibration"] = {"a": 1.2, "b": -0.1}

        if metrics["accuracy"] < 0.4:
            fb["trust"] = 0.5

        return fb