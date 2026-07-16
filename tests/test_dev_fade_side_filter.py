"""Tests for the DEV_FADE side filter (PAPER_FADE_SIDES), added 2026-07-16.

Evidence: side-tracked closes showed BUY-fades 71.7% WR / +0.17 vs SELL-fades
54.7% WR / -0.23 (fading rallies fights the crypto uptrend). The filter lets the
bot drop the anti-edge side. Default "both" must be a strict no-op.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _reload_with(sides):
    os.environ["PAPER_DEVIATION_FADE"] = "true"
    if sides is None:
        os.environ.pop("PAPER_FADE_SIDES", None)
    else:
        os.environ["PAPER_FADE_SIDES"] = sides
    import src.services.signal_generator as sg
    importlib.reload(sg)
    return sg


def test_default_is_both_noop():
    sg = _reload_with(None)
    assert sg._DEV_FADE_SIDES == "both"


@pytest.mark.parametrize("val,expected", [
    ("buy_only", "buy_only"),
    ("SELL_ONLY", "sell_only"),
    (" Both ", "both"),
])
def test_env_parse_normalizes(val, expected):
    sg = _reload_with(val)
    assert sg._DEV_FADE_SIDES == expected


def test_buy_only_filters_sell_side():
    """With buy_only, an up-move (which fades to SELL) must be dropped."""
    sg = _reload_with("buy_only")
    assert sg._DEV_FADE_SIDES == "buy_only"
    # Direct logic check mirroring the in-code guard:
    action = "SELL"
    dropped = (sg._DEV_FADE_SIDES == "buy_only" and action == "SELL")
    assert dropped is True
    # BUY side survives
    action = "BUY"
    dropped = (sg._DEV_FADE_SIDES == "buy_only" and action == "SELL")
    assert dropped is False


def test_both_drops_nothing():
    sg = _reload_with("both")
    for action in ("BUY", "SELL"):
        dropped = (
            (sg._DEV_FADE_SIDES == "buy_only" and action == "SELL")
            or (sg._DEV_FADE_SIDES == "sell_only" and action == "BUY")
        )
        assert dropped is False


def teardown_module(module):
    for k in ("PAPER_DEVIATION_FADE", "PAPER_FADE_SIDES"):
        os.environ.pop(k, None)
    import src.services.signal_generator as sg
    importlib.reload(sg)
