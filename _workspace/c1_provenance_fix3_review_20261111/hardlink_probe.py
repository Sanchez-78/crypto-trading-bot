"""Synthetic, local-only reproduction of a hardlink alias of result.tmp."""

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research import learner_replay_report as producer


def run() -> dict:
    root = Path(__file__).resolve().parent / f"hardlink_case_{uuid.uuid4().hex[:8]}"
    root.mkdir(exist_ok=True)
    result = root / "prereg_result.json"
    manifest = producer.provenance_path(result)
    log = root / "verdict.log"
    tmp = result.with_name(result.name + ".tmp")
    if any(p.exists() for p in (result, manifest, log, tmp)):
        raise RuntimeError("probe directory already used; no files overwritten")
    log.write_text("prior log entry\n", encoding="utf-8")
    os.link(log, tmp)
    before = {
        "different_resolved_paths": log.resolve() != tmp.resolve(),
        "same_existing_file": os.path.samefile(log, tmp),
    }
    producer.validate_freeze_inputs(result, "20261116T174700Z", log)
    original = producer.evaluate_preregistered
    producer.evaluate_preregistered = lambda *args, **kwargs: {
        "verdict": "CONTRARIAN_NOT_SHOWN",
        "scored_after_ms": 123,
    }
    try:
        producer.frozen_preregistered([], 123, result, "20261116T174700Z", log)
    finally:
        producer.evaluate_preregistered = original
    contents = log.read_text(encoding="utf-8")
    return {
        **before,
        "result_exists": result.exists(),
        "manifest_exists": manifest.exists(),
        "provenance_line_in_log": "PROVENANCE run=" in contents,
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "result_sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
        "log_equals_result": log.read_bytes() == result.read_bytes(),
        "log_prefix": contents[:100],
    }


if __name__ == "__main__":
    evidence = run()
    payload = json.dumps(evidence, indent=2) + "\n"
    (Path(__file__).resolve().parent / "hardlink_reproduction.json").write_text(payload, encoding="utf-8")
    print(payload)
