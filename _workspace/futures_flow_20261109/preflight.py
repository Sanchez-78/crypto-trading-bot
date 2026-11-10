"""TRAIN-only data/schema/resource smoke check, before any TEST calculation."""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.research import futures_flow_screen as screen


def main():
    cache = ROOT / "data/research/binance_futures"
    start, end = screen.stamp("2024-01-01"), screen.stamp("2025-07-01")
    manifest = []
    for kind in ("futures", "spot", "funding", "metrics"):
        periods = ([day.date().isoformat() for day in screen.pd.date_range("2024-01-01", "2025-06-30")]
                   if kind == "metrics" else screen.month_keys("2024-01", "2025-06"))
        for period in periods:
            key = screen.archive_key(kind, "BTCUSDT", period)
            path = cache / key
            checksum = path.with_suffix(".zip.CHECKSUM").read_text().split()[0]
            manifest.append(dict(kind=kind, symbol="BTCUSDT", period=period, key=key,
                                 sha256=checksum, status="OK"))
    begin = time.monotonic()
    sources = {kind: screen.load_series(cache, manifest, kind, "BTCUSDT", start, end)
               for kind in ("futures", "spot", "metrics", "funding")}
    features = screen.build_features(sources["futures"], sources["spot"], sources["metrics"],
                                     sources["funding"], sources["futures"])
    labels = screen.make_targets(sources["futures"])
    assert features.index.equals(labels.index)
    result = dict(period="TRAIN_ONLY", symbol="BTCUSDT", rows={key: len(value) for key, value in sources.items()},
                  complete_features=int(features[list(screen.FEATURES)].notna().all(axis=1).sum()),
                  complete_targets=int(labels.notna().all(axis=1).sum()), seconds=time.monotonic() - begin,
                  source_sha256=hashlib.sha256((ROOT / "scripts/research/futures_flow_screen.py").read_bytes()).hexdigest())
    screen.write_json(Path(__file__).with_suffix(".json"), result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
