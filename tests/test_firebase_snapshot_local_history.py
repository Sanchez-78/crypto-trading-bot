from src.services import firebase_client
from src.services import local_persistent_cache


def test_snapshot_history_prefers_local_ledger(monkeypatch):
    local_rows = [{"trade_id": "local-1"}]
    monkeypatch.setattr(
        local_persistent_cache,
        "get_closed_trades",
        lambda limit: local_rows,
    )

    def fail_remote(*, limit):
        raise AssertionError(f"unexpected Firebase history read: {limit}")

    monkeypatch.setattr(firebase_client, "load_history", fail_remote)

    assert firebase_client._load_snapshot_history(limit=500) == local_rows


def test_snapshot_history_uses_bounded_firebase_fallback(monkeypatch):
    calls = []
    monkeypatch.setenv("FIREBASE_SNAPSHOT_HISTORY_FALLBACK_LIMIT", "80")
    monkeypatch.setattr(
        local_persistent_cache,
        "get_closed_trades",
        lambda limit: [],
    )

    def load_remote(*, limit):
        calls.append(limit)
        return [{"trade_id": "remote-1"}]

    monkeypatch.setattr(firebase_client, "load_history", load_remote)

    assert firebase_client._load_snapshot_history(limit=500) == [
        {"trade_id": "remote-1"}
    ]
    assert calls == [80]
