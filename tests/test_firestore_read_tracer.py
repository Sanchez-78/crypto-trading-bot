"""Tests for the diagnostic Firestore read-call-site tracer added to
firebase_client.py (2026-08-12) to find the unattributed quota burn
confirmed in _workspace/22_quota_burn_confirmed_dashboard_lies.md.
"""
import importlib

import pytest
from google.cloud.firestore_v1.base_collection import BaseCollectionReference
from google.cloud.firestore_v1.base_query import BaseQuery

from src.services import firebase_client as fc


@pytest.fixture(autouse=True)
def _reset_tracer_state(monkeypatch):
    """Isolate each test's view of the module-level aggregation state, and
    always undo any class-level patching this test applied so other tests
    (and other test files importing the real SDK classes) never see a
    leftover wrapper."""
    monkeypatch.setattr(fc, "_READ_TRACE_COUNTS", {})
    monkeypatch.setattr(fc, "_read_trace_last_summary_ts", [0.0])
    original_get = BaseCollectionReference.__dict__.get("get")
    original_stream = BaseCollectionReference.__dict__.get("stream")
    original_query_get = BaseQuery.__dict__.get("get")
    original_query_stream = BaseQuery.__dict__.get("stream")
    yield
    if original_get is not None:
        BaseCollectionReference.get = original_get
    if original_stream is not None:
        BaseCollectionReference.stream = original_stream
    if original_query_get is not None:
        BaseQuery.get = original_query_get
    if original_query_stream is not None:
        BaseQuery.stream = original_query_stream


def test_disabled_by_default_does_not_patch(monkeypatch):
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", False)
    before = BaseCollectionReference.__dict__.get("get")
    fc._install_firestore_read_tracer()
    after = BaseCollectionReference.__dict__.get("get")
    assert before is after  # untouched


def test_enabled_patches_get_and_stream_on_both_classes(monkeypatch):
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    for cls in (BaseCollectionReference, BaseQuery):
        for method_name in ("get", "stream"):
            method = getattr(cls, method_name)
            assert getattr(method, "_read_traced", False) is True


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    wrapped_once = BaseCollectionReference.get
    fc._install_firestore_read_tracer()
    wrapped_twice = BaseCollectionReference.get
    assert wrapped_once is wrapped_twice  # not re-wrapped


def test_traced_get_still_calls_through_and_preserves_return_value(monkeypatch):
    """Replace the CLASS-level `get` with a known fake BEFORE installing the
    tracer, so the wrapper's captured `original` is that fake -- proves the
    wrapper genuinely calls through with the same args/kwargs and returns
    whatever the original returned, unmodified."""
    sentinel = object()
    calls = []

    def _fake_get(self, *a, **kw):
        calls.append((a, kw))
        return sentinel

    monkeypatch.setattr(BaseCollectionReference, "get", _fake_get, raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()

    result = BaseCollectionReference.get(object(), "posarg", kw="kwval")
    assert result is sentinel
    assert calls == [(("posarg",), {"kw": "kwval"})]


def test_read_trace_record_aggregates_by_caller_key():
    fc._READ_TRACE_COUNTS.clear()
    fc._read_trace_record("some_file.py:42")
    fc._read_trace_record("some_file.py:42")
    fc._read_trace_record("other_file.py:7")
    assert fc._READ_TRACE_COUNTS["some_file.py:42"] == 2
    assert fc._READ_TRACE_COUNTS["other_file.py:7"] == 1


def test_read_trace_record_never_raises_on_summary_logging(monkeypatch):
    """Force the summary branch to fire and confirm it doesn't blow up."""
    fc._READ_TRACE_COUNTS.clear()
    fc._read_trace_last_summary_ts[0] = 0.0
    fc._read_trace_record("x.py:1")  # first call after ts=0 always triggers summary
    # No assertion beyond "didn't raise" -- logging.warning is the only side effect.


def test_traced_method_records_the_real_caller(monkeypatch):
    monkeypatch.setattr(BaseCollectionReference, "get", lambda self, *a, **kw: "ok", raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    fc._READ_TRACE_COUNTS.clear()

    BaseCollectionReference.get(object())
    assert len(fc._READ_TRACE_COUNTS) == 1
    (key,) = fc._READ_TRACE_COUNTS.keys()
    assert "test_firestore_read_tracer.py" in key


def test_import_error_is_handled_gracefully(monkeypatch):
    """If the Firestore base classes ever become unimportable (SDK version
    change), the tracer must not crash module import."""
    import builtins
    real_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if "firestore_v1" in name:
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    fc._install_firestore_read_tracer()  # must not raise
