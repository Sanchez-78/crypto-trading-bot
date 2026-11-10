"""Check frozen result arithmetic and provenance without replaying any data."""
import hashlib
import json
import math
from pathlib import Path


def main():
    artifacts = Path(__file__).resolve().parent
    screen = artifacts / "screen"
    result = json.loads((screen / "report.json").read_text(encoding="utf-8"))
    signatures = set()
    starts = []
    checked = 0
    hashes = {}
    for name in ("TRAIN", "TEST", "HOLDOUT"):
        path = screen / f"{name.lower()}.json"
        frozen = json.loads(path.read_text(encoding="utf-8"))
        assert frozen == result[name], name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        signatures.add(frozen["signature"])
        started = json.loads(path.with_suffix(".started.json").read_text(encoding="utf-8"))
        starts.append(started["started_utc"])
        assert started["signature"] == frozen["signature"]
        for family, stats in frozen["statistics"].items():
            if stats is None:
                continue
            assert 0 <= stats["bootstrap_valid"] <= result["study"]["protocol"]["bootstrap"]
            if family == "H6":
                assert stats["symbols"]["BTCUSDT"]["n"] == 0
            for target in ("r15", "tpsl"):
                values = stats[target]
                if stats["n"]:
                    assert math.isclose(values["gross_bps"] - 9, values["net9_bps"], abs_tol=1e-8)
                    assert math.isclose(values["gross_bps"] - 18, values["net18_bps"], abs_tol=1e-8)
                    if values["ci95_net9"]:
                        assert all(math.isclose(a - 9, b, abs_tol=1e-8)
                                   for a, b in zip(values["ci95_net9"], values["ci95_net18"]))
                    assert 0 <= values["wr_net18"] <= values["wr_net9"] <= values["wr_gross"] <= 1
                for key in ("side", "regime", "market", "symbols"):
                    groups = stats[key].values()
                    assert sum(group["n"] for group in groups) == stats["n"], (name, family, key)
                    if stats["n"]:
                        total = sum(group["n"] * group[target]["gross_bps"] for group in groups if group["n"])
                        assert math.isclose(total / stats["n"], values["gross_bps"], abs_tol=1e-8)
                checked += 1
    assert len(signatures) == 1
    assert starts == sorted(starts)
    proof = dict(status="PASS", target_summaries_checked=checked, stage_sha256=hashes,
                 started_utc=starts, no_market_data_read=True, no_re_evaluation=True)
    (artifacts / "result_integrity.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
