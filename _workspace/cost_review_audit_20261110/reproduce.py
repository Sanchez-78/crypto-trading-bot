"""Read-only audit reproductions: synthetic inputs, no actual C1 data."""
import hashlib
import importlib.util
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "scripts/research/cost_and_learning_review.py"
    spec = importlib.util.spec_from_file_location("cost_review_under_audit", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stats = {"gross_bps": 1.0, "ci95_net9": [-9.5, -6.5]}
    fake_report = {block: {"statistics": {"H1": {"n": 300, "r15": stats, "tpsl": stats}},
                          "coverage": [{"sources": {"futures": {"missing_ranges": []}}}]}
                   for block in module.BLOCKS}
    trace = []

    def fake_load(path):
        trace.append(path.name)
        if path.name == "synthetic_report":
            return fake_report, "a" * 64
        if path.name == "synthetic_pending":
            return {"verdict": "PENDING"}, "b" * 64
        if path.name == "synthetic_mu":
            return {"mu_bps": -9.0, "scored_set_sha256": "synthetic"}, "c" * 64
        raise AssertionError("unexpected input")

    original_loader = module.load_json
    module.load_json = fake_load
    try:
        pending = module.build(Path("synthetic_report"), Path("synthetic_pending"), Path("synthetic_mu"))
        pending_proof = {"load_order": trace[:], "status": pending["c1"]["status"],
                         "declared_outcomes_opened": pending["c1"]["post_cutoff_outcomes_opened"],
                         "mu_sha_recorded": pending["inputs"]["mu_sha256"]}
        trace.clear()
        try:
            module.build(Path("synthetic_report"), None, Path("synthetic_mu"))
        except module.ReviewError as exc:
            no_c1_proof = {"load_order": trace[:], "error_after_mu_read": str(exc)}
        else:
            raise AssertionError("expected missing C1 rejection")
    finally:
        module.load_json = original_loader

    invalid_c1 = {"verdict": "CONTRARIAN_CONFIRMED", "scored_after_ms": 0,
                  "scored_trade_ids": ["duplicate", "duplicate"],
                  "variants": {"C1_contrarian": {"upper_n": 520, "lower_n": 480,
                                                   "day_bootstrap": {"blocks": 0}}}}
    accepted = module.c1_section(invalid_c1, None)
    empty = {block: {"statistics": {}} for block in module.BLOCKS}
    empty_table = module.futures_cost_table(empty)
    empty_health = module.four_questions({"status": "PENDING"}, module.coverage_gaps(empty))[0]
    reversed_ci = module.sensitivity({"n": 0, "gross_bps": 1.0, "ci95_net9": [5.0, -10.0]}, "synthetic")

    proof = {
        "code_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "synthetic_only": True, "real_c1_data_read": False,
        "pending_reads_mu": pending_proof,
        "missing_c1_reads_mu_before_error": no_c1_proof,
        "invalid_c1_accepted": accepted,
        "empty_report": {"cost_table": empty_table, "health": empty_health},
        "reversed_ci_and_zero_n_accepted": reversed_ci,
    }
    destination = Path(__file__).resolve().parent / "reproductions.json"
    destination.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(proof, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
