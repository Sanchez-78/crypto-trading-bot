import os
import time
from datetime import datetime, timezone

from src.services import firebase_client as fc


class FakeSnapshot:
    def __init__(self, data=None, doc_id="doc", exists=None):
        self._data = None if data is None else dict(data)
        self.id = doc_id
        self.exists = exists if exists is not None else data is not None

    def to_dict(self):
        return {} if self._data is None else dict(self._data)


class FakeDocRef:
    def __init__(self, data=None):
        self.data = None if data is None else dict(data)
        self.get_calls = 0
        self.set_calls = 0
        self.last_set = None

    def get(self):
        self.get_calls += 1
        return FakeSnapshot(self.data, exists=self.data is not None)

    def set(self, data, merge=False):
        self.set_calls += 1
        payload = dict(data)
        self.last_set = payload
        if merge and self.data is not None:
            self.data = {**self.data, **payload}
        else:
            self.data = payload


class FakeQuery:
    def __init__(self, docs):
        self._docs = list(docs)
        self._limit = None

    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, count):
        self._limit = count
        return self

    def stream(self):
        docs = self._docs if self._limit is None else self._docs[:self._limit]
        return iter(docs)

    def get(self):
        docs = self._docs if self._limit is None else self._docs[:self._limit]
        return list(docs)


class FakeCollection:
    def __init__(self, docs=None, named_docs=None):
        self.docs = list(docs or [])
        self.named_docs = dict(named_docs or {})

    def document(self, name=None):
        key = "default" if name is None else name
        if key not in self.named_docs:
            self.named_docs[key] = FakeDocRef()
        return self.named_docs[key]

    def where(self, *args, **kwargs):
        return FakeQuery(self.docs)

    def order_by(self, *args, **kwargs):
        return FakeQuery(self.docs)

    def limit(self, count):
        return FakeQuery(self.docs).limit(count)


class FakeDB:
    def __init__(self, collections=None, document_paths=None):
        self.collections = dict(collections or {})
        self.document_paths = dict(document_paths or {})
        self.collection_calls = []

    def collection(self, name):
        self.collection_calls.append(name)
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]

    def document(self, path):
        if path not in self.document_paths:
            self.document_paths[path] = FakeDocRef()
        return self.document_paths[path]


def _reset_firebase_state(fake_db):
    fc.db = fake_db
    fc._QUOTA_WINDOW_START = time.time()
    fc._QUOTA_READS = 0
    fc._QUOTA_WRITES = 0
    fc._LAST_RECON_TS = 0
    fc._PREV_WINDOW_READ_ATTRIBUTION.clear()
    for cache in (
        fc._HISTORY_CACHE,
        fc._WEIGHTS_CACHE,
        fc._SIGNALS_CACHE,
        fc._CONFIG_CACHE,
        fc._ADVICE_CACHE,
        fc._METRICS_CACHE,
        fc._PUSH_TOKEN_CACHE,
    ):
        cache["ts"] = 0
        if "limit" in cache:
            cache["limit"] = 0
        if isinstance(cache.get("data"), list):
            cache["data"] = []
        else:
            cache["data"] = None


def test_load_config_uses_ttl_cache():
    runtime_ref = FakeDocRef({"max_risk": 0.02})
    fake_db = FakeDB(collections={"config": FakeCollection(named_docs={"runtime": runtime_ref})})
    _reset_firebase_state(fake_db)

    assert fc.load_config()["max_risk"] == 0.02
    assert fc.load_config()["max_risk"] == 0.02
    assert runtime_ref.get_calls == 1
    assert fc.get_quota_status()["reads"] == 1


def test_save_bot2_advice_keeps_timestamp_in_cache():
    advice_ref = FakeDocRef()
    fake_db = FakeDB(document_paths={fc._ADVICE_DOC: advice_ref})
    _reset_firebase_state(fake_db)

    fc.save_bot2_advice({"blocked_pairs": ["BTCUSDT|TREND"]})
    cached = fc.load_bot2_advice()

    assert "timestamp" in advice_ref.last_set
    assert cached["blocked_pairs"] == ["BTCUSDT|TREND"]
    assert "timestamp" in cached
    assert advice_ref.get_calls == 0
    assert fc.get_quota_status()["writes"] == 1


def test_load_bot2_metrics_uses_cache():
    latest_ref = FakeDocRef({"health": {"score": 88}})
    fake_db = FakeDB(collections={"metrics": FakeCollection(named_docs={"latest": latest_ref})})
    _reset_firebase_state(fake_db)

    assert fc.load_bot2_metrics()["health"]["score"] == 88
    assert fc.load_bot2_metrics()["health"]["score"] == 88
    assert latest_ref.get_calls == 1
    assert fc.get_quota_status()["reads"] == 1


def test_load_history_counts_documents_and_caches_by_limit():
    docs = [
        FakeSnapshot({"timestamp": 5, "symbol": "BTCUSDT"}, "a"),
        FakeSnapshot({"timestamp": 4, "symbol": "ETHUSDT"}, "b"),
        FakeSnapshot({"timestamp": 3, "symbol": "SOLUSDT"}, "c"),
        FakeSnapshot({"timestamp": 2, "symbol": "XRPUSDT"}, "d"),
        FakeSnapshot({"timestamp": 1, "symbol": "BNBUSDT"}, "e"),
    ]
    fake_db = FakeDB(collections={"trades": FakeCollection(docs=docs)})
    _reset_firebase_state(fake_db)

    history = fc.load_history(limit=5)
    assert len(history) == 5
    assert fc.get_quota_status()["reads"] == 5

    cached = fc.load_history(limit=5)
    assert len(cached) == 5
    assert fc.get_quota_status()["reads"] == 5


def test_load_commands_since_uses_prefixed_collection():
    old_prefix = fc.PREFIX
    fc.PREFIX = "shadow_"
    try:
        docs = [
            FakeSnapshot({"timestamp_ms": 1, "action": "PING"}, "cmd1"),
            FakeSnapshot({"timestamp_ms": 2, "action": "CLOSE_ALL"}, "cmd2"),
        ]
        fake_db = FakeDB(collections={"shadow_commands": FakeCollection(docs=docs)})
        _reset_firebase_state(fake_db)

        commands = fc.load_commands_since(0, limit=10)

        assert [c["id"] for c in commands] == ["cmd1", "cmd2"]
        assert "shadow_commands" in fake_db.collection_calls
        assert fc.get_quota_status()["reads"] == 2
    finally:
        fc.PREFIX = old_prefix


def test_load_push_token_uses_cache():
    token_ref = FakeDocRef({"token": "ExponentPushToken[abc]"})
    fake_db = FakeDB(collections={"config": FakeCollection(named_docs={"push_tokens": token_ref})})
    _reset_firebase_state(fake_db)

    assert fc.load_push_token() == "ExponentPushToken[abc]"
    assert fc.load_push_token() == "ExponentPushToken[abc]"
    assert token_ref.get_calls == 1
    assert fc.get_quota_status()["reads"] == 1


def test_quota_reset_clears_quota_429_degradation(tmp_path):
    """2026-07-14: quota_429 degradation must clear at the 07:00 UTC quota
    reset, not serve out a blind 24h window (kept learning dead all day)."""
    _reset_firebase_state(FakeDB(collections={}))
    # P0-FIX (2026-08-06): isolate the attribution snapshot file this test
    # incidentally now writes (via _mark_quota_exhausted) -- without this it
    # wrote a real file into the repo's local_learning_storage/ on every test
    # run. See test_mark_quota_exhausted_also_persists_a_snapshot below for
    # the dedicated test of that behavior.
    original_path = fc._QUOTA_ATTRIBUTION_FILE
    fc._QUOTA_ATTRIBUTION_FILE = str(tmp_path / "quota_attribution_snapshot.json")
    try:
        fc._mark_quota_exhausted("simulated 429")
        assert fc.get_firebase_health()["available"] is False
        assert fc.get_quota_status()["reads"] == fc._QUOTA_MAX_READS

        # Force the window back before today's 07:00 UTC so a reset is due.
        fc._QUOTA_WINDOW_START = time.time() - 48 * 3600
        fc._reset_quota_if_new_day()

        assert fc.get_quota_status()["reads"] == 0
        assert fc.get_firebase_health()["available"] is True
    finally:
        fc._QUOTA_ATTRIBUTION_FILE = original_path


def test_record_read_attributes_by_label():
    _reset_firebase_state(FakeDB(collections={}))
    fc._READ_ATTRIBUTION.clear()
    fc._record_read(3, label="load_history")
    fc._record_read(2, label="load_history")
    fc._record_read(1, label="load_commands_since")
    assert fc._READ_ATTRIBUTION["load_history"] == 5
    assert fc._READ_ATTRIBUTION["load_commands_since"] == 1
    assert fc.get_quota_status()["reads"] == 6


def test_persist_attribution_snapshot_survives_as_a_durable_file(tmp_path):
    """P0-FIX (2026-08-06): a quota-exhaustion event must leave a durable,
    file-based attribution record -- journald alone was proven insufficient
    (retention collapsed to ~2 min under this process's own log volume
    during the 2026-08-06 10:08 UTC incident, destroying the only evidence
    of which caller drove the read volume). See task 19 in this session's
    evidence trail.
    """
    import json

    _reset_firebase_state(FakeDB(collections={}))
    fc._READ_ATTRIBUTION.clear()
    snapshot_path = str(tmp_path / "quota_attribution_snapshot.json")
    original_path = fc._QUOTA_ATTRIBUTION_FILE
    try:
        fc._QUOTA_ATTRIBUTION_FILE = snapshot_path
        fc._record_read(7, label="load_stats")
        fc._persist_attribution_snapshot(reason="unit_test")

        assert os.path.exists(snapshot_path), "attribution snapshot file must be written"
        with open(snapshot_path) as f:
            data = json.load(f)
        assert data["read_attribution"]["load_stats"] == 7
        assert data["reads"] == 7
        assert data["reason"] == "unit_test"
        assert "generated_at_utc" in data
    finally:
        fc._QUOTA_ATTRIBUTION_FILE = original_path


def test_mark_quota_exhausted_also_persists_a_snapshot(tmp_path):
    """The moment of exhaustion is the single most useful diagnostic point
    -- confirm _mark_quota_exhausted() writes a snapshot immediately,
    not just the periodic (up to 300s-delayed) path."""
    import json

    _reset_firebase_state(FakeDB(collections={}))
    fc._READ_ATTRIBUTION.clear()
    snapshot_path = str(tmp_path / "quota_attribution_snapshot.json")
    original_path = fc._QUOTA_ATTRIBUTION_FILE
    try:
        fc._QUOTA_ATTRIBUTION_FILE = snapshot_path
        fc._record_read(2, label="load_history")
        fc._mark_quota_exhausted("simulated 429 for test")

        assert os.path.exists(snapshot_path)
        with open(snapshot_path) as f:
            data = json.load(f)
        assert data["reason"].startswith("quota_429:")
        assert data["reads"] == fc._QUOTA_MAX_READS  # exhaustion forces reads to max
    finally:
        fc._QUOTA_ATTRIBUTION_FILE = original_path


# ── Quota window boundary (07:00 UTC) ────────────────────────────────────────
# Regression cover for the 2026-08-07 self-perpetuating lockout: the reset
# fired on calendar rollover (00:00 UTC), stamped _QUOTA_WINDOW_START 7h into
# the future, and thereby made the real 07:00 reset unreachable forever.

def _utc(day, hour, minute=0, second=0):
    return datetime(2026, 8, day, hour, minute, second, tzinfo=timezone.utc)


def _arm_window(day, hour, reads=40000):
    """Put the module in a mid-window state: window opened at `day hour` UTC."""
    _reset_firebase_state(FakeDB(collections={}))
    fc._QUOTA_WINDOW_START = _utc(day, hour).timestamp()
    fc._QUOTA_READS = reads
    fc._QUOTA_WRITES = 1000


def test_no_reset_at_calendar_midnight_utc():
    """00:00 UTC is NOT the Firebase reset boundary — 07:00 UTC is."""
    _arm_window(day=6, hour=7)  # window legitimately opened at Aug 6 07:00

    fc._reset_quota_if_new_day(now_utc=_utc(7, 0, 0, 0))

    assert fc._QUOTA_READS == 40000, "midnight must not clear the quota counters"
    assert fc._QUOTA_WINDOW_START == _utc(6, 7).timestamp()
    # The precise defect: the window start must never be stamped in the future.
    assert fc._QUOTA_WINDOW_START <= _utc(7, 0).timestamp()


def test_reset_fires_just_after_0700_utc():
    _arm_window(day=6, hour=7)
    fc._READ_ATTRIBUTION.clear()
    fc._READ_ATTRIBUTION["load_history"] = 40000
    fc._PREV_WINDOW_READ_ATTRIBUTION.clear()

    fc._reset_quota_if_new_day(now_utc=_utc(7, 7, 0, 1))

    assert fc._QUOTA_READS == 0
    assert fc._QUOTA_WRITES == 0
    assert fc._QUOTA_WINDOW_START == _utc(7, 7).timestamp()
    # Attribution of the closed window survives the reset (a 429 arriving
    # moments later must still be diagnosable).
    assert fc._PREV_WINDOW_READ_ATTRIBUTION["load_history"] == 40000
    assert fc._READ_ATTRIBUTION == {}


def test_reset_is_idempotent_within_the_same_window():
    _arm_window(day=6, hour=7)

    fc._reset_quota_if_new_day(now_utc=_utc(7, 7, 0, 1))
    assert fc._QUOTA_READS == 0

    fc._QUOTA_READS = 120  # reads accrued after the reset
    fc._reset_quota_if_new_day(now_utc=_utc(7, 7, 5, 0))
    fc._reset_quota_if_new_day(now_utc=_utc(7, 23, 59, 59))

    assert fc._QUOTA_READS == 120, "reset must not re-fire inside the same window"


def test_midnight_then_0700_still_resets():
    """The exact live failure: a midnight tick must not consume the day's
    reset. Journal evidence 2026-08-07T07:05:53Z showed the 07:00 reset being
    skipped because the 00:00 tick had already moved the window forward."""
    _arm_window(day=6, hour=11)  # service start Aug 6 11:43Z (rounded)

    fc._reset_quota_if_new_day(now_utc=_utc(7, 0, 0, 0))   # midnight: no-op
    assert fc._QUOTA_READS == 40000

    fc._reset_quota_if_new_day(now_utc=_utc(7, 7, 0, 1))   # real boundary
    assert fc._QUOTA_READS == 0
    assert fc._QUOTA_WINDOW_START == _utc(7, 7).timestamp()


def test_future_window_start_from_clock_skew_forces_rearm():
    """A window start ahead of real time is impossible state (the boundary is
    always <= now) and reproduces the original lockout if left alone. Reachable
    when the clock steps forward across 07:00 and is corrected back (NTP, VM
    resume). Reviewer condition C1, _workspace/16_review.md."""
    _arm_window(day=6, hour=7)
    fc._QUOTA_WINDOW_START = _utc(7, 7).timestamp()  # stamped ahead of real time

    fc._reset_quota_if_new_day(now_utc=_utc(7, 3, 0, 0))  # clock corrected backward

    assert fc._QUOTA_READS == 0
    assert fc._QUOTA_WINDOW_START == _utc(6, 7).timestamp(), "re-armed to the real boundary"


def test_pre_0700_hours_compare_against_yesterdays_boundary():
    """At 02:00 UTC the live window is the one opened at yesterday 07:00."""
    _arm_window(day=6, hour=7)
    fc._reset_quota_if_new_day(now_utc=_utc(7, 2, 0, 0))
    assert fc._QUOTA_READS == 40000, "02:00 is inside the Aug 6 07:00 window"

    # A window older than yesterday's boundary is stale and must reset.
    _arm_window(day=5, hour=7)
    fc._reset_quota_if_new_day(now_utc=_utc(7, 2, 0, 0))
    assert fc._QUOTA_READS == 0
    assert fc._QUOTA_WINDOW_START == _utc(6, 7).timestamp()
