import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

import funnel_tap as ft  # noqa: E402

P08_ADMIT = ("[P0_8_PLUS_LIVE] ADAUSDT trend_cost_aware BUY regime=BULL_TREND quote=live "
             "admitted=True code=P0_ADMIT_EVIDENCE_COLLECTION net_edge=-15.87bps")
P08_REJECT = ("[P0_8_PLUS_LIVE] DOTUSDT trend_cost_aware BUY regime=BULL_TREND quote=live "
              "admitted=False code=REJECT_NEGATIVE_NET_EDGE net_edge=-23.07bps")
ENTRY = ("[PAPER_ENTRY] symbol=ADAUSDT side=BUY price=0.17590000 size_usd=7.50 ev=-0.0016 "
         "score=0.702 reason=P0_8_PLUS_EVIDENCE_COLLECTION")
EXIT = ("[PAPER_EXIT] trade_id=x symbol=ADAUSDT reason=HARD_STOP_VOLATILITY entry=0.1763 "
        "exit=0.17585 net_pnl_pct=-0.3452 outcome=LOSS hold_s=475")


def test_parse_keys_and_ignores_outcomes():
    assert ft.parse(P08_ADMIT) == "p08|trend_cost_aware|ADAUSDT|admit"
    assert ft.parse(P08_REJECT) == "p08|trend_cost_aware|DOTUSDT|REJECT_NEGATIVE_NET_EDGE"
    assert ft.parse(ENTRY) == "entry|P0_8_PLUS_EVIDENCE_COLLECTION|ADAUSDT"
    assert ft.parse("[PAPER_LEARNING_BUDGET] symbol=ADAUSDT reason=symbol_cooldown") == \
        "budget|symbol_cooldown|ADAUSDT"
    assert ft.parse("[PAPER_EXPLORE_SKIP] reason=no_side symbol=ETHUSDT original_decision=X") == \
        "skip|no_side|ETHUSDT"
    assert ft.parse(EXIT) is None  # blind phase: no outcomes recorded
    assert ft.parse("[P0_8_PLUS_LIVE] tick complete: 1 opened across 1 symbol(s)") is None


def test_tap_writes_hourly_counts_without_outcomes(tmp_path):
    times = iter([3600 * 10 + 5] + [3600 * 10 + 10] * 3 + [3600 * 11 + 1] * 2)
    ft.tap([P08_ADMIT, ENTRY, EXIT, P08_REJECT, ENTRY], tmp_path, clock=lambda: next(times))
    records = [json.loads(x) for x in (tmp_path / "19700101.jsonl").read_text().splitlines()]
    assert [r["hour"] for r in records] == ["1970-01-01T10:00Z", "1970-01-01T11:00Z"]
    assert records[0]["counts"] == {"entry|P0_8_PLUS_EVIDENCE_COLLECTION|ADAUSDT": 1,
                                    "p08|trend_cost_aware|ADAUSDT|admit": 1}
    assert "net_pnl" not in (tmp_path / "19700101.jsonl").read_text()


def test_summary_window_and_unavailable(tmp_path):
    assert ft.summarize(tmp_path, 12, now=3600 * 20).startswith("FUNNEL hours=0/12 unavailable")
    (tmp_path / "19700101.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"hour": "1970-01-01T05:00Z", "partial": False, "counts": {"entry|P|ADAUSDT": 99}},
        {"hour": "1970-01-01T10:00Z", "partial": False,
         "counts": {"p08|t|ADAUSDT|admit": 2, "p08|t|DOTUSDT|REJECT_X": 3, "entry|P|ADAUSDT": 2}},
        {"hour": "1970-01-01T20:00Z", "partial": True, "counts": {"entry|P|ADAUSDT": 50}},
    ]) + "\n")
    line = ft.summarize(tmp_path, 12, now=3600 * 20 + 30)
    assert line.startswith("FUNNEL hours=1/12 p08_candidates=5 ")
    assert "p08:REJECT_X=3" in line and "entry:P=2" in line and "=99" not in line and "=50" not in line
