"""Tests for the diagnostic Firestore call-site tracer added to
firebase_client.py (2026-08-12/13) to find the unattributed quota burn
confirmed in _workspace/22_quota_burn_confirmed_dashboard_lies.md.

Three generations, each deployed and each found to have zero real coverage
until the last one:
  1. CollectionReference/Query only (Base* classes) -> zero hits on a live
     full quota exhaustion.
  2. + BaseDocumentReference -> STILL zero hits on the next live exhaustion,
     despite dozens of observed 429s in the same window.
  3. Root cause: Base* (BaseCollectionReference/BaseDocumentReference/
     BaseQuery) are abstract bases. The CONCRETE sync classes actually
     returned by db.collection(...)/.document(...) -- google.cloud.
     firestore_v1.collection.CollectionReference, .document.
     DocumentReference, .query.Query -- each define their OWN get/stream/
     set/update/create/delete in their own __dict__, which shadows the Base
     implementation entirely per Python MRO. Patching Base was inert from
     the very first version. This file now proves and covers that directly.
"""
import pytest
from google.cloud.firestore_v1.base_collection import BaseCollectionReference
from google.cloud.firestore_v1.base_document import BaseDocumentReference
from google.cloud.firestore_v1.base_query import BaseQuery
from google.cloud.firestore_v1.collection import CollectionReference
from google.cloud.firestore_v1.document import DocumentReference
from google.cloud.firestore_v1.query import Query

from src.services import firebase_client as fc

# What _install_firestore_read_tracer() actually patches: only methods each
# class defines in its OWN __dict__ (see _wrap's `method_name not in
# cls.__dict__` guard) -- deliberately excludes inherited-only slots so we
# never double-wrap the same underlying function via two different classes.
_ALL_CANDIDATE_CLASSES = (
    BaseCollectionReference, BaseDocumentReference, BaseQuery,
    CollectionReference, DocumentReference, Query,
)
_CANDIDATE_METHODS = ("get", "stream", "collections", "set", "update", "delete", "create")
# The concrete classes are the ones that matter in production (firebase_admin
# uses the sync client, whose collection()/document() calls return these).
_CONCRETE_OWN_METHODS = {
    CollectionReference: ("get", "stream"),
    Query: ("get", "stream"),
    DocumentReference: ("get", "collections", "set", "update", "delete", "create"),
}


def _own_targets(cls, methods):
    return [(cls, m) for m in methods if m in cls.__dict__]


@pytest.fixture(autouse=True)
def _reset_tracer_state(monkeypatch):
    """Isolate each test's view of the module-level aggregation state, and
    always undo any class-level patching this test applied so other tests
    (and other test files importing the real SDK classes) never see a
    leftover wrapper."""
    monkeypatch.setattr(fc, "_READ_TRACE_COUNTS", {})
    monkeypatch.setattr(fc, "_read_trace_last_summary_ts", [0.0])
    originals = {
        (cls, name): cls.__dict__.get(name)
        for cls in _ALL_CANDIDATE_CLASSES for name in _CANDIDATE_METHODS
    }
    yield
    for (cls, name), original in originals.items():
        if original is not None:
            setattr(cls, name, original)
        elif name in cls.__dict__:
            delattr(cls, name)


def test_disabled_by_default_does_not_patch(monkeypatch):
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", False)
    before = DocumentReference.__dict__.get("get")
    fc._install_firestore_read_tracer()
    after = DocumentReference.__dict__.get("get")
    assert before is after  # untouched


@pytest.mark.parametrize(
    "cls,method_name",
    [(c, m) for c, ms in _CONCRETE_OWN_METHODS.items() for m in ms],
)
def test_enabled_patches_the_concrete_class_that_owns_the_method(monkeypatch, cls, method_name):
    """The regression case: these are the classes firebase_admin's sync
    client actually instantiates. If these aren't patched, nothing is."""
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    method = cls.__dict__[method_name]
    assert getattr(method, "_read_traced", False) is True


def test_patching_base_class_alone_would_not_have_covered_the_concrete_class():
    """Documents the exact bug: DocumentReference/CollectionReference/Query
    each define get/stream/etc. in their OWN __dict__, so wrapping only the
    Base* attribute (generations 1 and 2 of this tracer) never affects what
    a real instance resolves via MRO."""
    assert "get" in DocumentReference.__dict__
    assert "get" in CollectionReference.__dict__
    assert "get" in Query.__dict__
    # i.e. these are NOT simply inherited from Base* -- patching Base*.get
    # leaves DocumentReference.get (etc.) completely unaffected.
    assert DocumentReference.__dict__["get"] is not BaseDocumentReference.__dict__.get("get")


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    wrapped_once = DocumentReference.get
    fc._install_firestore_read_tracer()
    wrapped_twice = DocumentReference.get
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

    monkeypatch.setattr(CollectionReference, "get", _fake_get, raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()

    result = CollectionReference.get(object(), "posarg", kw="kwval")
    assert result is sentinel
    assert calls == [(("posarg",), {"kw": "kwval"})]


def test_document_reference_get_is_traced_as_a_read(monkeypatch):
    """The concrete-class gap found live 2026-08-13: single-document reads
    (`db.collection(x).document(y).get()`) resolve to
    DocumentReference.get -- its OWN method, not BaseDocumentReference.get.
    Replace it with a fake BEFORE installing (so the fake, lacking
    `_read_traced`, gets freshly wrapped) and confirm invoking it records a
    READ: hit against the fake, not a real network call."""
    monkeypatch.setattr(DocumentReference, "get", lambda self, *a, **kw: "doc", raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    fc._READ_TRACE_COUNTS.clear()

    DocumentReference.get(object())
    assert len(fc._READ_TRACE_COUNTS) == 1
    (key,) = fc._READ_TRACE_COUNTS.keys()
    assert key.startswith("READ:")


def test_document_reference_writes_are_traced_as_writes(monkeypatch):
    for method_name in ("set", "update", "delete", "create"):
        monkeypatch.setattr(DocumentReference, method_name, lambda self, *a, **kw: None, raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    fc._READ_TRACE_COUNTS.clear()

    DocumentReference.set(object(), {})
    (key,) = fc._READ_TRACE_COUNTS.keys()
    assert key.startswith("WRITE:")


def test_read_trace_record_aggregates_by_caller_key():
    fc._READ_TRACE_COUNTS.clear()
    fc._read_trace_record("READ:some_file.py:42")
    fc._read_trace_record("READ:some_file.py:42")
    fc._read_trace_record("WRITE:other_file.py:7")
    assert fc._READ_TRACE_COUNTS["READ:some_file.py:42"] == 2
    assert fc._READ_TRACE_COUNTS["WRITE:other_file.py:7"] == 1


def test_read_trace_record_never_raises_on_summary_logging(monkeypatch):
    """Force the summary branch to fire and confirm it doesn't blow up."""
    fc._READ_TRACE_COUNTS.clear()
    fc._read_trace_last_summary_ts[0] = 0.0
    fc._read_trace_record("READ:x.py:1")  # first call after ts=0 always triggers summary
    # No assertion beyond "didn't raise" -- logging.warning is the only side effect.


def test_traced_method_records_the_real_caller(monkeypatch):
    monkeypatch.setattr(CollectionReference, "get", lambda self, *a, **kw: "ok", raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    fc._READ_TRACE_COUNTS.clear()

    CollectionReference.get(object())
    assert len(fc._READ_TRACE_COUNTS) == 1
    (key,) = fc._READ_TRACE_COUNTS.keys()
    assert "test_firestore_read_tracer.py" in key
    assert key.startswith("READ:")


def test_query_get_and_stream_are_traced(monkeypatch):
    monkeypatch.setattr(Query, "get", lambda self, *a, **kw: [], raising=True)
    monkeypatch.setattr(Query, "stream", lambda self, *a, **kw: iter([]), raising=True)
    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    fc._install_firestore_read_tracer()
    fc._READ_TRACE_COUNTS.clear()

    list(Query.get(object()))
    list(Query.stream(object()))
    assert len(fc._READ_TRACE_COUNTS) == 2
    assert all(k.startswith("READ:") for k in fc._READ_TRACE_COUNTS)


def test_import_error_is_handled_gracefully(monkeypatch):
    """If the Firestore base/concrete classes ever become unimportable (SDK
    version change), the tracer must not crash module import."""
    import builtins
    real_import = builtins.__import__

    def _blocking_import(name, *args, **kwargs):
        if "firestore_v1" in name:
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(fc, "FIREBASE_READ_TRACE_ENABLED", True)
    monkeypatch.setattr(builtins, "__import__", _blocking_import)
    fc._install_firestore_read_tracer()  # must not raise
