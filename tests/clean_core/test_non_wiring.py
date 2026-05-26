"""Tests ensuring clean core has NO legacy wiring (tests 21-23)."""

import pytest
import sys
import importlib


class TestNonWiring:
    """Verify clean core is isolated from legacy systems."""

    def test_21_clean_core_no_firebase_import(self):
        """Test 21: Clean core modules never import Firebase."""
        # Check all clean core modules
        clean_core_modules = [
            "src.clean_core.domain",
            "src.clean_core.config",
            "src.clean_core.market.binance_usdm_routes",
            "src.clean_core.market.local_book",
            "src.clean_core.execution.fees",
            "src.clean_core.execution.funding",
            "src.clean_core.execution.paper_accounting",
            "src.clean_core.provenance.epoch",
            "src.clean_core.provenance.journal",
            "src.clean_core.provenance.eligibility",
        ]

        for module_name in clean_core_modules:
            module = importlib.import_module(module_name)
            source = importlib.util.find_spec(module_name)

            # If module has source file, check it
            if source and source.origin:
                try:
                    with open(source.origin, "r", encoding="utf-8") as f:
                        content = f.read()
                        assert (
                            "firebase" not in content.lower()
                        ), f"{module_name} contains firebase reference"
                except UnicodeDecodeError:
                    # Skip files with encoding issues
                    pass

    def test_22_clean_core_no_live_socket_creation(self):
        """Test 22: Clean core routes define URLs but never create live connections."""
        from src.clean_core.market.binance_usdm_routes import BinanceUsdmRoutes

        routes = BinanceUsdmRoutes()

        # Routes should return URLs, not websocket connections
        url, identity = routes.depth_stream("BTCUSDT")
        assert isinstance(url, str)
        assert url.startswith("wss://")

        # Should not have websocket connection object
        assert not hasattr(routes, "websocket")
        assert not hasattr(routes, "_ws")
        assert not hasattr(routes, "connection")

    def test_23_clean_core_no_data_file_writes(self, temp_dir):
        """Test 23: Clean core test fixtures never write to data/ or production paths."""
        import os

        # Get full paths to forbidden directories
        data_dir = os.path.abspath("data")
        backups_dir = os.path.abspath("server_local_backups")

        # Before test: record state
        data_files_before = set()
        if os.path.exists(data_dir):
            for root, dirs, files in os.walk(data_dir):
                for f in files:
                    data_files_before.add(os.path.join(root, f))

        backup_files_before = set()
        if os.path.exists(backups_dir):
            for root, dirs, files in os.walk(backups_dir):
                for f in files:
                    backup_files_before.add(os.path.join(root, f))

        # Run a simple clean core operation with temp files
        from src.clean_core.provenance.journal import CleanCoreJournal
        from src.clean_core.provenance.epoch import CleanPaperEpoch

        journal_path = os.path.join(temp_dir, "test.jsonl")
        journal = CleanCoreJournal(journal_path)
        journal.append_event("test_event", {"data": "test"})

        epoch = CleanPaperEpoch(
            epoch_id="test_e001",
            status="active",
            created_utc="2026-05-26T12:00:00Z",
            started_utc="2026-05-26T12:00:00Z",
        )
        epoch.add_closed_trade(0.5, True, "futures_rpi_aware_measured")

        # After test: verify no new files in forbidden directories
        data_files_after = set()
        if os.path.exists(data_dir):
            for root, dirs, files in os.walk(data_dir):
                for f in files:
                    data_files_after.add(os.path.join(root, f))

        backup_files_after = set()
        if os.path.exists(backups_dir):
            for root, dirs, files in os.walk(backups_dir):
                for f in files:
                    backup_files_after.add(os.path.join(root, f))

        data_new_files = data_files_after - data_files_before
        backup_new_files = backup_files_after - backup_files_before

        assert (
            len(data_new_files) == 0
        ), f"Clean core wrote to data/: {data_new_files}"
        assert (
            len(backup_new_files) == 0
        ), f"Clean core wrote to server_local_backups/: {backup_new_files}"
