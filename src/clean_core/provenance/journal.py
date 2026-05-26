"""Append-only journal for Clean Core RESET R1 provenance."""

import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class CleanCoreJournal:
    """
    Append-only JSONL journal for clean core events.

    Each entry is immutable, includes timestamp, event type, data.
    Used for complete audit trail of epoch lifecycle and decisions.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.event_counter = 0
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create journal file if it doesn't exist."""
        if not os.path.exists(self.file_path):
            # Create with empty list for compatibility (optional header)
            with open(self.file_path, "w") as f:
                f.write("")

    def append_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        clean_core_version: str = "R1",
        config_hash: str = "",
    ) -> Dict[str, Any]:
        """
        Append a new event to journal.

        Args:
            event_type: e.g., "epoch_created", "trade_closed", "learning_update"
            data: event-specific dict
            clean_core_version: version identifier
            config_hash: hash of configuration at time of event

        Returns:
            Complete event record including metadata
        """
        self.event_counter += 1

        event = {
            "event_id": self.event_counter,
            "event_type": event_type,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "clean_core_version": clean_core_version,
            "config_hash": config_hash,
            "data": data,
        }

        # Append to file
        with open(self.file_path, "a") as f:
            f.write(json.dumps(event) + "\n")

        return event

    def read_events(
        self,
        event_type_filter: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """
        Read all events from journal.

        Args:
            event_type_filter: if provided, only return events of this type

        Returns:
            list of event records
        """
        events = []

        if not os.path.exists(self.file_path):
            return events

        with open(self.file_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event_type_filter is None or event.get("event_type") == event_type_filter:
                        events.append(event)
                except json.JSONDecodeError:
                    # Skip malformed lines
                    pass

        return events

    def last_event_of_type(self, event_type: str) -> Optional[Dict[str, Any]]:
        """Get the most recent event of a given type."""
        events = self.read_events(event_type_filter=event_type)
        return events[-1] if events else None

    def event_count(self, event_type: Optional[str] = None) -> int:
        """Count events, optionally filtered by type."""
        return len(self.read_events(event_type_filter=event_type))
