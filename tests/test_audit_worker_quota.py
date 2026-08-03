from src.services import firebase_client as fc
from src.services.audit_worker import AuditWorker, MAX_AUDITS


class _DocRef:
    def __init__(self, doc_id):
        self.id = doc_id


class _Collection:
    def __init__(self):
        self.document_ids = []
        self.query_calls = 0

    def document(self, doc_id=None):
        self.document_ids.append(doc_id)
        return _DocRef(doc_id)

    def order_by(self, *args, **kwargs):
        self.query_calls += 1
        raise AssertionError("audit ring must not issue cleanup reads")


class _Batch:
    def __init__(self):
        self.set_calls = []
        self.commit_calls = 0

    def set(self, ref, payload):
        self.set_calls.append((ref, dict(payload)))

    def commit(self):
        self.commit_calls += 1


class _DB:
    def __init__(self):
        self.audits = _Collection()
        self.last_batch = None

    def collection(self, name):
        assert name == "audits"
        return self.audits

    def batch(self):
        self.last_batch = _Batch()
        return self.last_batch


def _reset_write_budget():
    fc._QUOTA_READS = 0
    fc._QUOTA_WRITES = 0
    fc._READ_ATTRIBUTION.clear()
    fc._WRITE_ATTRIBUTION.clear()
    fc._FIREBASE_WRITE_DEGRADED = False
    fc._FIREBASE_DEGRADED_UNTIL = 0


def test_audit_batch_uses_fixed_slots_without_firestore_reads():
    _reset_write_budget()
    worker = AuditWorker()
    worker._ring_cursor = MAX_AUDITS - 1
    fake_db = _DB()

    worker._sync_batch_write(
        fake_db,
        [
            {"timestamp": 1.0, "reason": "first"},
            {"timestamp": 2.0, "reason": "second"},
        ],
    )

    assert fake_db.audits.document_ids == ["slot_49", "slot_00"]
    assert fake_db.audits.query_calls == 0
    assert fake_db.last_batch.commit_calls == 1
    assert [payload["ring_slot"] for _, payload in fake_db.last_batch.set_calls] == [
        49,
        0,
    ]
    quota = fc.get_quota_status()
    assert quota["reads"] == 0
    assert quota["write_attribution"]["audit_ring"] == 2


def test_audit_batch_caps_one_flush_to_ring_capacity():
    _reset_write_budget()
    worker = AuditWorker()
    worker._ring_cursor = 0
    fake_db = _DB()

    worker._sync_batch_write(
        fake_db,
        [{"timestamp": float(i), "reason": str(i)} for i in range(75)],
    )

    assert len(fake_db.last_batch.set_calls) == MAX_AUDITS
    assert fake_db.audits.document_ids == [
        f"slot_{i:02d}" for i in range(MAX_AUDITS)
    ]
    assert fc.get_quota_status()["write_attribution"]["audit_ring"] == MAX_AUDITS
