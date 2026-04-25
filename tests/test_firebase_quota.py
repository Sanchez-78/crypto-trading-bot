import time

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
