import time

class PipelineDebug:

    def __init__(self):
        self.stats = {
            "price": 0,
            "signal": 0,
            "open": 0,
            "close": 0,
            "evaluation": 0,
            "learning": 0
        }
        self.last_print = time.time()

    def log(self, stage, symbol=None):
        self.stats[stage] += 1

        msg = f"🔍 {stage.upper()}"
        if symbol:
            msg += f" | {symbol}"

        print(msg)

        self._print_summary()

    def _print_summary(self):
        now = time.time()

        if now - self.last_print > 10:
            print("\n📊 PIPELINE SUMMARY (last 10s)")
            for k, v in self.stats.items():
                print(f"{k}: {v}")
            print("-" * 30)

            # reset
            for k in self.stats:
                self.stats[k] = 0

            self.last_print = now


pipeline_debug = PipelineDebug()