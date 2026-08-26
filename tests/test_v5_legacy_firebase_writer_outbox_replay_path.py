"""Regression test for the 2026-08-26 outbox-replay path fix in
V5LegacyFirebaseWriter.flush_outbox().

Root cause: the learning_update branch of flush_outbox() built the replay
path as f"v5_trades/{trade_id}/learning" -- a 3-segment path ending on a
collection, which Firestore always rejects ("Invalid path (must end on
doc, not collection)"). The live-write path (write_learning_update(), same
file) already used the correct 2-segment f"v5_trades/{trade_id}" with
merge=True. Confirmed live: 60 occurrences of the error in production
journalctl, all starting 2026-08-26 05:19:03, once quota pressure started
pushing learning_update writes into the outbox
(_workspace/46_quota_exhaustion_outbox_path_bug_and_false_crash_alerts_cycle123.md).
"""
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from src.services.v5_legacy_bridge.outbox import DurableOutbox
from src.services.v5_legacy_bridge.firebase_writer import V5LegacyFirebaseWriter
from src.services.v5_legacy_bridge.quota import V5LegacyQuotaGuard
from src.services.v5_legacy_bridge import config


@pytest.fixture
def fresh_outbox():
    if os.path.exists(config.V5_OUTBOX_DB_PATH):
        os.remove(config.V5_OUTBOX_DB_PATH)
    outbox = DurableOutbox()
    yield outbox
    if os.path.exists(config.V5_OUTBOX_DB_PATH):
        os.remove(config.V5_OUTBOX_DB_PATH)


def test_learning_update_outbox_replay_uses_the_same_path_shape_as_the_live_write(fresh_outbox):
    fresh_outbox.enqueue("learning_update", "paper_abc123", {"segment_pf": 1.5})

    fake_firebase_client = MagicMock()
    quota_guard = MagicMock(spec=V5LegacyQuotaGuard)
    quota_guard.check_can_write.return_value = MagicMock(allowed=True)

    writer = V5LegacyFirebaseWriter(
        firebase_client=fake_firebase_client, quota_guard=quota_guard, outbox=fresh_outbox
    )
    result = writer.flush_outbox(limit=10)

    assert result["sent"] == 1, "the (fixed) path must be accepted, not retried forever"
    fake_firebase_client.set.assert_called_once_with(
        "v5_trades/paper_abc123", {"segment_pf": 1.5}, merge=True
    )

    # No entries left pending -- confirms mark_sent() was reached, i.e. the
    # write did not raise (a malformed path would raise inside .set() and
    # the entry would still be pending with an incremented retry_count).
    assert fresh_outbox.get_pending(limit=10) == []


def test_learning_update_outbox_replay_path_is_a_valid_even_segment_count(fresh_outbox):
    """Direct regression against the exact bug shape: the path must never
    end on an odd number of '/'-separated segments (a Firestore collection,
    not a document)."""
    fresh_outbox.enqueue("learning_update", "paper_xyz789", {"x": 1})

    fake_firebase_client = MagicMock()
    quota_guard = MagicMock(spec=V5LegacyQuotaGuard)
    quota_guard.check_can_write.return_value = MagicMock(allowed=True)

    writer = V5LegacyFirebaseWriter(
        firebase_client=fake_firebase_client, quota_guard=quota_guard, outbox=fresh_outbox
    )
    writer.flush_outbox(limit=10)

    used_path = fake_firebase_client.set.call_args[0][0]
    parts = used_path.strip("/").split("/")
    assert len(parts) % 2 == 0, (
        f"path {used_path!r} has an odd number of segments -- ends on a "
        f"collection, not a document; this is the exact bug that caused "
        f"'Invalid path (must end on doc, not collection)' in production"
    )
