"""Golden numerics for paper_trade_executor._calculate_pnl (audit PR3).

PR3 is a contract refactor that MUST NOT change the close math. These golden
values are computed by hand from the formula as it stands *before* the refactor
(gross = directional return * 100; cost = (fee+slippage)*100, round-trip;
net = gross - cost; outcome = ±0.05pp deadband on net). If the delegation of
`outcome` to trade_metrics_contract.classify_outcome ever alters a number, one
of these breaks.

Fee/slippage are passed explicitly so the golden values do not depend on env
(_FEE_PCT / _SLIPPAGE_PCT) defaults.
"""
import pytest

from src.services.paper_trade_executor import _calculate_pnl

FEE = 0.0015       # -> 0.15 pct points round-trip
SLIP = 0.0003      # -> 0.03 pct points
# total modeled cost = 0.18 pct points


def _pnl(side, entry, exit_):
    return _calculate_pnl(side, entry, exit_, size_usd=100.0, fee_pct=FEE, slippage_pct=SLIP)


# (side, entry, exit, expected gross_pct, expected net_pct, expected outcome)
GOLDEN = [
    ("BUY", 100.0, 101.0, 1.0, 0.82, "WIN"),
    ("BUY", 100.0, 100.10, 0.1, -0.08, "LOSS"),     # gross 0.1 - 0.18 = -0.08
    ("BUY", 100.0, 100.20, 0.2, 0.02, "FLAT"),      # gross 0.2 - 0.18 = 0.02 (deadband)
    ("BUY", 100.0, 100.22, 0.22, 0.04, "FLAT"),     # net 0.04, comfortably inside band
    ("BUY", 100.0, 100.24, 0.24, 0.06, "WIN"),      # net 0.06 > 0.05 -> WIN
    ("BUY", 100.0, 99.87, -0.13, -0.31, "LOSS"),
    ("SELL", 100.0, 99.0, 1.0, 0.82, "WIN"),        # short profits when price falls
    ("SELL", 100.0, 101.0, -1.0, -1.18, "LOSS"),
    ("SELL", 100.0, 99.78, 0.22, 0.04, "FLAT"),     # mirror, inside band
]


@pytest.mark.parametrize("side,entry,exit_,g,n,outcome", GOLDEN)
def test_calculate_pnl_golden(side, entry, exit_, g, n, outcome):
    res = _pnl(side, entry, exit_)
    assert res["gross_pnl_pct"] == pytest.approx(g, abs=1e-9)
    assert res["net_pnl_pct"] == pytest.approx(n, abs=1e-9)
    assert res["outcome"] == outcome


def test_costs_are_round_trip_pct_points():
    res = _pnl("BUY", 100.0, 100.0)
    assert res["fee_pct"] == pytest.approx(0.15, abs=1e-9)
    assert res["slippage_pct"] == pytest.approx(0.03, abs=1e-9)
    # flat move, only costs -> net = -0.18, a LOSS
    assert res["net_pnl_pct"] == pytest.approx(-0.18, abs=1e-9)
    assert res["outcome"] == "LOSS"


def test_returned_keys_unchanged():
    res = _pnl("BUY", 100.0, 101.0)
    assert set(res.keys()) == {"gross_pnl_pct", "fee_pct", "slippage_pct", "net_pnl_pct", "outcome"}
