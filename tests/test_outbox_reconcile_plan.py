# -*- coding: utf-8 -*-
"""Reconciliation planner for terminal outbox rows (disabled, pure; 2026-11-18).

Cloud documents use the real writer contract (event_models.py); the review-2026-11-18
reproductions (incomplete/contradictory/foreign documents, absent -> close -> learning)
are pinned below.
"""
import ast
from pathlib import Path

import pytest

from src.services.v5_legacy_bridge import outbox_reconcile as rec
from src.services.v5_legacy_bridge.event_models import LegacyPaperCloseEvent, LegacyPaperOpenEvent
from src.services.v5_legacy_bridge.outbox_reconcile import Row, UNKNOWN


def open_doc(key):
    return LegacyPaperOpenEvent(trade_id=key, symbol="BTCUSDT", side="BUY", strategy_id="s",
                                entry_ts=1.0, entry_price=100.0).to_dict()


def close_doc(key):
    return LegacyPaperCloseEvent(trade_id=key, symbol="BTCUSDT", side="BUY", exit_ts=2.0, exit_price=101.0).to_dict()


def close_after_learning_merge(key):
    # build_learning_update() carries no event_type, so the merged close keeps "paper_close".
    return {**close_doc(key), "source": "legacy_v5_bridge", "learning_source": "x", "entry_price": 100.0,
            "readiness_eligible": False, "timestamp": "2026-11-18T00:00:00"}


def _without(doc, *keys):
    return {k: v for k, v in doc.items() if k not in keys}


def _by(actions):
    return {(a.event_type, a.key): a.action for a in actions}


def test_document_state_follows_the_writer_contract():
    assert rec.doc_state(None, "t") == "absent"
    assert rec.doc_state(open_doc("t"), "t") == "open"
    assert rec.doc_state(close_doc("t"), "t") == "closed"
    assert rec.doc_state(close_after_learning_merge("t"), "t") == "closed"


@pytest.mark.parametrize("doc", [
    {"status": "closed", "trade_id": "t"},                                   # invented field
    {"event_type": "paper_close", "trade_id": "t"},                          # bare event_type (review repro)
    {"exit_ts": None, "exit_price": None, "trade_id": "t"},                  # null exit fields (review repro)
    {"event_type": "paper_open", "exit_ts": None, "exit_price": None, "trade_id": "t"},  # review repro
    {**close_doc("t"), "event_type": "paper_open"},                          # open + exit contradiction
    {**close_doc("t"), "exit_ts": True},                                     # bool is not a timestamp
    {**close_doc("t"), "exit_price": float("nan")},
    {**close_doc("t"), "symbol": ""},
    {**open_doc("t"), "entry_price": None},
    {"event_type": "paper_close", "trade_id": "other"},                      # foreign trade_id (review repro)
    {**close_doc("other")},                                                  # complete but foreign
    {k: v for k, v in close_doc("t").items() if k != "trade_id"},            # missing identity
    {}, "not-a-mapping", UNKNOWN,
    # re-review 2026-11-18 repros
    {"trade_id": "t", "event_type": "paper_open", "entry_ts": 1.0, "entry_price": 100.0},  # no symbol/side
    _without(open_doc("t"), "symbol"), _without(open_doc("t"), "side"),
    {**open_doc("t"), "side": "OTHER"}, {**open_doc("t"), "symbol": 5},
    {**open_doc("t"), "entry_price": 0.0}, {**open_doc("t"), "entry_ts": -1.0},
    {**close_doc("t"), "side": "OTHER"}, _without(close_doc("t"), "side"),
    {**close_doc("t"), "event_type": "quota_publish"},                       # foreign type with exit fields
    {**close_doc("t"), "event_type": "learning_update"},                     # undocumented merged shape
    _without(close_doc("t"), "event_type"),
    {**close_doc("t"), "exit_price": 0.0}, {**close_doc("t"), "exit_price": -5.0},
    {**close_doc("t"), "exit_ts": 0},
])
def test_incomplete_contradictory_or_foreign_documents_are_unknown(doc):
    assert rec.doc_state(doc, "t") == "unknown"
    rows = [Row("paper_close", "t"), Row("learning_update", "t"), Row("paper_open", "t")]
    assert {a.action for a in rec.plan(rows, {"t": doc}, max_writes=10)} == {"UNKNOWN"}


def test_truncated_close_from_review_is_unknown_not_merged():
    """Review 2026-11-19 A1: a close without the trade result used to be 'closed' + MERGE_LEARNING."""
    doc = {"trade_id": "t", "symbol": "BTCUSDT", "side": "BUY",
           "event_type": "paper_close", "exit_ts": 2.0, "exit_price": 101.0}
    assert rec.doc_state(doc, "t") == "unknown"
    actions = rec.plan([Row("paper_close", "t"), Row("learning_update", "t")], {"t": doc}, max_writes=2)
    assert [a.action for a in actions] == ["UNKNOWN", "UNKNOWN"]


@pytest.mark.parametrize("field", sorted(rec._CLOSE_FIELDS))
def test_close_missing_any_writer_field_is_unknown(field):
    assert rec.doc_state(_without(close_doc("t"), field), "t") == "unknown"


@pytest.mark.parametrize("field", sorted(rec._OPEN_FIELDS))
def test_open_missing_any_writer_field_is_unknown(field):
    assert rec.doc_state(_without(open_doc("t"), field), "t") == "unknown"


@pytest.mark.parametrize("bad", [
    {"symbol": " "}, {"symbol": " BTCUSDT"}, {"symbol": "btcusdt"}, {"symbol": "BTC-USDT"},
    {"real_orders_allowed": True}, {"real_orders_allowed": None},
    {"exit_reason": ""}, {"exit_reason": None}, {"net_pnl": None}, {"fees": "0.1"}, {"net_pnl_pct": float("inf")},
    {"duration_seconds": -1.0}, {"learning_eligible": 1}, {"readiness_eligible": None},
    {"exit_price": 10 ** 1000}, {"net_pnl": 10 ** 1000},  # OverflowError in isfinite -> unknown, not a crash
    {"metadata": None}, {"created_at": ""},
])
def test_close_with_invalid_field_value_is_unknown(bad):
    assert rec.doc_state({**close_doc("t"), **bad}, "t") == "unknown"


@pytest.mark.parametrize("bad", [
    {"size": 0}, {"size": None}, {"expected_move_bps": None}, {"cost_edge_ok": "yes"},
    {"strategy_id": 5}, {"real_orders_allowed": True}, {"symbol": " "},
])
def test_open_with_invalid_field_value_is_unknown(bad):
    assert rec.doc_state({**open_doc("t"), **bad}, "t") == "unknown"


def test_existing_close_is_skipped_and_never_rewritten():
    rows = [Row("paper_close", k) for k in ("a", "b", "c", "d")]
    cloud = {"a": close_doc("a"), "b": close_after_learning_merge("b"), "c": open_doc("c"), "d": None}
    got = _by(rec.plan(rows, cloud, max_writes=10))
    assert got == {("paper_close", "a"): "SKIP_PRESENT", ("paper_close", "b"): "SKIP_PRESENT",
                   ("paper_close", "c"): "WRITE_CLOSE", ("paper_close", "d"): "WRITE_CLOSE"}


def test_open_never_overwrites_existing_or_closing_trade():
    rows = [Row("paper_open", "t1"), Row("paper_open", "t2"), Row("paper_open", "t3"), Row("paper_close", "t3"),
            Row("paper_open", "t4")]
    cloud = {"t1": close_doc("t1"), "t2": None, "t3": None, "t4": open_doc("t4")}
    got = _by(rec.plan(rows, cloud, max_writes=10))
    assert got[("paper_open", "t1")] == "SKIP_PRESENT"   # set() without merge would revert the close
    assert got[("paper_open", "t2")] == "WRITE_OPEN"
    assert got[("paper_open", "t3")] == "SKIP_PRESENT"   # close of the same key supersedes the open
    assert got[("paper_close", "t3")] == "WRITE_CLOSE"
    assert got[("paper_open", "t4")] == "SKIP_PRESENT"


def test_unknown_cloud_state_means_no_action():
    rows = [Row("paper_close", "x"), Row("paper_open", "y"), Row("learning_update", "z")]
    got = rec.plan(rows, {"z": UNKNOWN}, max_writes=10)
    assert {a.action for a in got} == {"UNKNOWN"}


@pytest.mark.parametrize("observed", ["absent", "open"])
def test_learning_after_planned_close_depends_on_it(observed):
    """Review repro: absent -> WRITE_CLOSE -> learning used to be DEFERRED_NO_TRADE_DOC."""
    cloud = {"t": None if observed == "absent" else open_doc("t")}
    actions = rec.plan([Row("paper_close", "t"), Row("learning_update", "t")], cloud, max_writes=2)
    close, learning = actions
    assert (close.action, close.expect, close.depends_on) == ("WRITE_CLOSE", observed, "")
    assert (learning.action, learning.expect, learning.depends_on) == ("MERGE_LEARNING", "closed", "paper_close:t")


@pytest.mark.parametrize("observed", ["absent", "open"])
def test_learning_without_budget_for_its_close_is_deferred(observed):
    cloud = {"t": None if observed == "absent" else open_doc("t")}
    actions = rec.plan([Row("paper_close", "t"), Row("learning_update", "t")], cloud, max_writes=0)
    assert [a.action for a in actions] == [
        "DEFERRED_QUOTA", "DEFERRED_NO_TRADE_DOC" if observed == "absent" else "DEFERRED_CLOSE_MISSING"]
    assert all(a.depends_on == "" for a in actions)
    one = rec.plan([Row("paper_close", "t"), Row("learning_update", "t")], cloud, max_writes=1)
    assert [a.action for a in one] == ["WRITE_CLOSE", "DEFERRED_QUOTA"] and one[1].depends_on == ""


def test_learning_merges_only_into_closed_or_planned_close():
    rows = [Row("learning_update", "a"), Row("learning_update", "b"), Row("learning_update", "d")]
    cloud = {"a": close_doc("a"), "b": None, "d": open_doc("d")}
    actions = rec.plan(rows, cloud, max_writes=10)
    got = _by(actions)
    assert got == {("learning_update", "a"): "MERGE_LEARNING", ("learning_update", "b"): "DEFERRED_NO_TRADE_DOC",
                   ("learning_update", "d"): "DEFERRED_CLOSE_MISSING"}
    assert [(a.key, a.expect, a.depends_on) for a in actions if a.key == "a"] == [("a", "closed", "")]


def test_write_cap_defers_and_order_is_close_learning_open():
    rows = [Row("paper_open", "o"), Row("learning_update", "l"), Row("paper_close", "c")]
    actions = rec.plan(rows, {"o": None, "l": close_doc("l"), "c": None}, max_writes=2)
    assert [a.event_type for a in actions] == ["paper_close", "learning_update", "paper_open"]
    assert [a.action for a in actions] == ["WRITE_CLOSE", "MERGE_LEARNING", "DEFERRED_QUOTA"]
    with pytest.raises(ValueError):
        rec.plan(rows, {}, max_writes=-1)


def test_snapshots_superseded_and_error_classes():
    got = rec.plan([Row("quota_publish", "quota_2026-06-02"), Row("dashboard_publish", "dashboard_current")],
                   {}, max_writes=10)
    assert {a.action for a in got} == {"SKIP_SUPERSEDED"}
    assert rec.classify_error("Invalid path (must end on doc, not collection): v5") == "deterministic_code_error"
    assert rec.classify_error("'Client' object has no attribute 'set'") == "deterministic_code_error"
    assert rec.classify_error("429 Quota exceeded") == "quota_rejected"
    assert rec.classify_error("Firebase write failed") == "ambiguous"


def test_planner_is_disabled_and_has_no_io_or_executor():
    assert rec.ENABLED is False
    source = Path(rec.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "dataclasses", "typing", "math"}
    body = source.split('"""', 2)[2]  # code after the module docstring
    for forbidden in (".set(", "sqlite3", "connect(", "DELETE", "retry_count"):
        assert forbidden not in body, forbidden
