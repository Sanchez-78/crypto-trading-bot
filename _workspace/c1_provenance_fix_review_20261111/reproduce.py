"""Independent synthetic crash and binding probes for the C1 provenance producer."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research import learner_replay_report as producer

CUTOFF = 1_794_209_516_000
NOW = CUTOFF + 8 * 86_400_000


def fake_evaluator(_trades, *, scored_after_ms, now_ms):
    return {"verdict": "CONTRARIAN_NOT_SHOWN", "scored_after_ms": scored_after_ms,
            "evaluated_for_probe_ms": now_ms, "scored_trade_ids": ["SYNTHETIC-1"]}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def references(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [dict(part.split("=", 1) for part in line.split(" PROVENANCE ", 1)[1].split())
            for line in path.read_text(encoding="utf-8").splitlines() if " PROVENANCE " in line]


def freeze(path: Path, log: Path, run_id: str):
    return producer.frozen_preregistered([], CUTOFF, path, run_id, log)


def main() -> None:
    results: dict = {}
    with tempfile.TemporaryDirectory(prefix="c1_provenance_review_", dir=Path(__file__).parent) as temp:
        base = Path(temp)
        assert base.resolve().is_relative_to(Path(__file__).resolve().parents[2])
        with (patch.object(producer, "evaluate_preregistered", fake_evaluator),
              patch.object(producer.time, "time", return_value=NOW / 1000)):
            result_path = base / "valid" / "prereg_result.json"
            result_path.parent.mkdir()
            log = base / "valid" / "verdict.log"
            first, sha = freeze(result_path, log, "R1")
            manifest_path = producer.provenance_path(result_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rows = references(log)
            assert sha == digest(manifest_path) == rows[0]["manifest_sha256"]
            assert manifest["result_sha256"] == digest(result_path) == rows[0]["result_sha256"]
            assert manifest["evaluated_at_ms"] == first["evaluated_for_probe_ms"] == NOW
            assert manifest["run_id"] == rows[0]["run"] == "R1"
            second, second_sha = freeze(result_path, log, "R2")
            assert second == first and second_sha is None and len(references(log)) == 1
            results["normal_freeze_and_repeat"] = "PASS: exact hashes; one line; unchanged frozen result"

            pending_path = base / "pending" / "prereg_result.json"
            pending_path.parent.mkdir()
            with patch.object(producer, "evaluate_preregistered", return_value={"verdict": "PENDING"}):
                pending, psha = producer.frozen_preregistered([], CUTOFF, pending_path)
            assert pending["verdict"] == "PENDING" and psha is None
            assert not pending_path.exists() and not producer.provenance_path(pending_path).exists()
            results["pending_library_without_provenance_args"] = "PASS"

            for stage in ("manifest", "append", "result"):
                branch = base / stage
                branch.mkdir()
                path = branch / "prereg_result.json"
                logfile = branch / "verdict.log"
                real_write = producer._write_frozen
                real_append = producer._append_reference

                def crash_write(target, payload):
                    if (stage == "manifest" and target.name == "prereg_provenance.json") or (
                            stage == "result" and target.name == "prereg_result.json"):
                        raise OSError("SYNTHETIC_CRASH")
                    return real_write(target, payload)

                def crash_append(*args):
                    if stage == "append":
                        raise OSError("SYNTHETIC_CRASH")
                    return real_append(*args)

                with (patch.object(producer, "_write_frozen", crash_write),
                      patch.object(producer, "_append_reference", crash_append)):
                    try:
                        freeze(path, logfile, "FIRST")
                    except OSError as exc:
                        assert str(exc) == "SYNTHETIC_CRASH"
                    else:
                        raise AssertionError(f"{stage}: expected crash")
                assert not path.exists()
                count = len(references(logfile))
                assert count == (1 if stage == "result" else 0)
                old = references(logfile)
                if old:
                    assert old[0]["run"] == "FIRST"
                # Next locked run creates a fresh manifest and marker. The old log line
                # can be disambiguated by both run ID and result/manifest hashes.
                if os.name == "nt" and producer.provenance_path(path).exists():
                    # Windows forbids replace over a readonly destination; the server
                    # uses POSIX rename, so only the disposable fixture is made writable.
                    producer.provenance_path(path).chmod(0o666)
                freeze(path, logfile, "SECOND")
                current = references(logfile)[-1]
                assert current["run"] == "SECOND"
                assert current["manifest_sha256"] == digest(producer.provenance_path(path))
                assert current["result_sha256"] == digest(path)
                assert len(references(logfile)) == count + 1
                results[f"crash_{stage}_and_retry"] = {
                    "orphan_lines": count, "final_lines": count + 1,
                    "latest_run_matches_frozen": True}

            for missing in ("run_id", "provenance_log"):
                branch = base / missing
                branch.mkdir()
                path = branch / "prereg_result.json"
                logfile = branch / "verdict.log"
                try:
                    producer.frozen_preregistered([], CUTOFF, path,
                        None if missing == "run_id" else "RUN",
                        None if missing == "provenance_log" else logfile)
                except ValueError as exc:
                    assert "run_id and provenance_log" in str(exc)
                else:
                    raise AssertionError(f"{missing}: expected fail-closed")
                assert not path.exists() and not logfile.exists()
                results[f"missing_{missing}"] = "PASS: no result/log"

            # Boundaries on the claim of a single parseable log line. The server's
            # date-generated run_id is safe; the public CLI currently accepts this.
            injected = base / "injected"
            injected.mkdir()
            fake_line = ("2026-11-16T17:47:00Z PROVENANCE run=FAKE "
                         f"manifest_sha256={'0' * 64} result_sha256={'1' * 64}")
            freeze(injected / "prereg_result.json", injected / "verdict.log", "A\n" + fake_line)
            results["unvalidated_run_id_newline"] = {
                "line_count": len((injected / "verdict.log").read_text(encoding="utf-8").splitlines()),
                "parsed_provenance_records": len(references(injected / "verdict.log")),
                "note": "manual caller can insert a second apparently complete reference"}

            aliased = base / "aliased_log"
            aliased.mkdir()
            result_path = aliased / "prereg_result.json"
            returned, manifest_sha = freeze(result_path, result_path, "SAME_PATH")
            assert returned["verdict"] == "CONTRARIAN_NOT_SHOWN"
            assert result_path.exists() and manifest_sha == digest(producer.provenance_path(result_path))
            results["log_aliased_to_result"] = {
                "result_exists": result_path.exists(),
                "logged_reference_lines": len(references(result_path)),
                "result_is_json": json.loads(result_path.read_text(encoding="utf-8"))["verdict"]}

    out = Path(__file__).with_name("reproductions.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
