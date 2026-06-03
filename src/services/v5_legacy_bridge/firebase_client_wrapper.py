"""
Firebase Path Client Wrapper

Converts path-based `.set(path, data)` API to Firestore's
`.collection().document().set()` API.

Allows V5LegacyFirebaseWriter to work with raw Firestore clients.
"""
import logging

log = logging.getLogger(__name__)


class FirestorePathClient:
    """
    Adapter: converts path-based API to Firestore collection/document API.

    Example paths:
    - "v5_trades/trade_123" → db.collection("v5_trades").document("trade_123").set()
    - "v5_quota/2026-06-03" → db.collection("v5_quota").document("2026-06-03").set()
    """

    def __init__(self, firestore_client):
        """
        Initialize wrapper with raw Firestore client.

        Args:
            firestore_client: google.cloud.firestore.Client instance
        """
        self.db = firestore_client

    def set(self, path: str, data: dict, merge: bool = False) -> None:
        """
        Set document at path.

        Args:
            path: Document path like "collection/doc" or "col1/doc1/col2/doc2"
            data: Dictionary to set
            merge: If True, merge with existing data; if False, overwrite
        """
        try:
            parts = path.strip('/').split('/')

            if not parts or len(parts) < 2:
                raise ValueError(f"Invalid path (too short): {path}")

            if len(parts) % 2 == 0:
                raise ValueError(
                    f"Invalid path (must end on doc, not collection): {path}. "
                    f"Path parts: {parts}"
                )

            ref = self.db

            for i, part in enumerate(parts):
                if i % 2 == 0:
                    ref = ref.collection(part)
                else:
                    ref = ref.document(part)

            ref.set(data, merge=merge)

        except Exception as e:
            log.error(f"[FIRESTORE_PATH_SET_FAILED] path={path} error={e}")
            raise

    def update(self, path: str, data: dict) -> None:
        """
        Update document at path (partial update, no overwrite).

        Args:
            path: Document path
            data: Fields to update
        """
        try:
            parts = path.strip('/').split('/')

            if not parts or len(parts) < 2:
                raise ValueError(f"Invalid path (too short): {path}")

            if len(parts) % 2 == 0:
                raise ValueError(
                    f"Invalid path (must end on doc, not collection): {path}"
                )

            ref = self.db

            for i, part in enumerate(parts):
                if i % 2 == 0:
                    ref = ref.collection(part)
                else:
                    ref = ref.document(part)

            ref.update(data)

        except Exception as e:
            log.error(f"[FIRESTORE_PATH_UPDATE_FAILED] path={path} error={e}")
            raise
