"""Independent synthetic checks of the two hardlink guards and a path-swap race."""

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research import learner_replay_report as producer


def new_case(base: Path, name: str) -> Path:
    path = base / f"{name}_{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path


def samefile_guards(base: Path) -> dict:
    checks = {}
    for target_name in ("prereg_result.json", "prereg_result.json.tmp",
                        "prereg_provenance.json", "prereg_provenance.json.tmp"):
        case = new_case(base, "identity")
        log = case / "verdict.log"
        log.write_text("prior\n", encoding="utf-8")
        target = case / target_name
        os.link(log, target)
        result = case / "prereg_result.json"
        try:
            producer.validate_freeze_inputs(result, "20261116T174700Z", log)
        except ValueError as exc:
            rejected = "must not alias" in str(exc)
        else:
            rejected = False
        checks[target_name] = {
            "samefile": os.path.samefile(log, target),
            "different_resolved_paths": log.resolve() != target.resolve(),
            "rejected": rejected,
            "log_unchanged": log.read_text(encoding="utf-8") == "prior\n",
        }
    return checks


def second_guard_alone(base: Path) -> dict:
    case = new_case(base, "writer_guard")
    result = case / "prereg_result.json"
    log = case / "verdict.log"
    log.write_text("prior\n", encoding="utf-8")
    os.link(log, case / "prereg_result.json.tmp")
    real_validate = producer.validate_freeze_inputs
    real_evaluate = producer.evaluate_preregistered
    producer.validate_freeze_inputs = lambda *args: None
    producer.evaluate_preregistered = lambda *args, **kwargs: {
        "verdict": "CONTRARIAN_NOT_SHOWN", "scored_after_ms": 123,
    }
    try:
        _, manifest_sha = producer.frozen_preregistered([], 123, result, "20261116T174700Z", log)
    finally:
        producer.validate_freeze_inputs = real_validate
        producer.evaluate_preregistered = real_evaluate
    manifest = producer.provenance_path(result)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    log_text = log.read_text(encoding="utf-8")
    return {
        "log_preserved": log_text.startswith("prior\n"),
        "reference_present": f"manifest_sha256={manifest_sha}" in log_text,
        "result_exists": result.exists(),
        "result_matches_manifest": hashlib.sha256(result.read_bytes()).hexdigest() == manifest_data["result_sha256"],
        "manifest_hash_matches": hashlib.sha256(manifest.read_bytes()).hexdigest() == manifest_sha,
        "result_distinct_from_log": not result.samefile(log),
    }


def identity_error(base: Path) -> bool:
    case = new_case(base, "identity_error")
    log = case / "verdict.log"
    log.write_text("prior\n", encoding="utf-8")
    real_samefile = producer.os.path.samefile

    def denied(*args):
        raise PermissionError("synthetic identity-check failure")

    producer.os.path.samefile = denied
    try:
        try:
            producer.validate_freeze_inputs(case / "prereg_result.json", "R1", log)
        except ValueError as exc:
            return "cannot verify" in str(exc)
        return False
    finally:
        producer.os.path.samefile = real_samefile


def post_open_path_swap(base: Path) -> dict:
    """Model an untrusted concurrent writer swapping the .tmp pathname after close."""
    case = new_case(base, "path_swap")
    result = case / "x.json"
    tmp = case / "x.json.tmp"
    log = case / "verdict.log"
    log.write_text("unrelated log\n", encoding="utf-8")
    real_replace = producer.Path.replace

    def swapped(self, target):
        if self == tmp:
            self.unlink()
            os.link(log, tmp)
        return real_replace(self, target)

    producer.Path.replace = swapped
    try:
        producer._write_frozen(result, b'{"intended": true}')
    finally:
        producer.Path.replace = real_replace
    return {
        "result_is_unrelated_log": result.read_bytes() == log.read_bytes(),
        "result_samefile_as_log": result.samefile(log),
        "intended_payload_published": result.read_bytes() == b'{"intended": true}',
    }


def main() -> None:
    evidence = Path(__file__).resolve().parent
    output = {
        "samefile_guards": samefile_guards(evidence),
        "second_guard_alone": second_guard_alone(evidence),
        "identity_error_rejected": identity_error(evidence),
        "post_open_path_swap": post_open_path_swap(evidence),
    }
    (evidence / "synthetic_checks.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    if not all(x["rejected"] and x["log_unchanged"] for x in output["samefile_guards"].values()):
        raise SystemExit(1)
    if not all(output["second_guard_alone"].values()) or not output["identity_error_rejected"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
