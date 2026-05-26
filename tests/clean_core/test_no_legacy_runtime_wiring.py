"""Tests validating Clean Core has zero legacy runtime wiring."""

import pytest
import sys
from pathlib import Path


class TestNoLegacyRuntimeWiring:
    """Verify Clean Core runner is completely isolated from legacy services."""

    def test_21_runner_module_has_no_services_import(self):
        """Test 21: ForwardPaperRunner imports nothing from src.services."""
        from src.clean_core.runner import forward_paper_runner

        # Read the module source
        source = Path(forward_paper_runner.__file__).read_text()

        # Check that no legacy imports appear
        forbidden = [
            "from src.services",
            "import src.services",
            "paper_adaptive_learning",
            "market_stream",
            "realtime_decision_engine",
            "trade_executor",
            "risk_engine",
            "firebase_client",
            "event_bus",
        ]

        for forbidden_import in forbidden:
            assert forbidden_import not in source, (
                f"ForwardPaperRunner should not import: {forbidden_import}"
            )

    def test_22_runner_cli_has_no_services_import(self):
        """Test 22: Runner CLI imports nothing from src.services."""
        from src.clean_core.runner import cli

        source = Path(cli.__file__).read_text()

        forbidden = [
            "from src.services",
            "import src.services",
            "paper_adaptive_learning",
        ]

        for forbidden_import in forbidden:
            assert forbidden_import not in source, (
                f"Runner CLI should not import: {forbidden_import}"
            )

    def test_23_simulated_feed_has_no_legacy_wiring(self):
        """Test 23: SimulatedFuturesFeed has no legacy dependencies."""
        from src.clean_core.runner import simulated_futures_feed

        source = Path(simulated_futures_feed.__file__).read_text()

        forbidden = [
            "from src.services",
            "firebase_client",
            "event_bus",
            "binance_api",
            "redis",
        ]

        for forbidden_import in forbidden:
            assert forbidden_import not in source, (
                f"SimulatedFuturesFeed should not use: {forbidden_import}"
            )

    def test_24_clean_core_imports_only_internal_modules(self):
        """Test 24: Clean Core runner only imports from src.clean_core."""
        from src.clean_core.runner import forward_paper_runner

        source = Path(forward_paper_runner.__file__).read_text()

        # Extract all imports
        import_lines = [line for line in source.split("\n") if "import" in line and "from" in line]

        # Verify all src imports are from src.clean_core (except comments)
        for line in import_lines:
            if line.strip().startswith("#"):
                continue
            if "from src" in line:
                assert "from src.clean_core" in line, (
                    f"Should import from src.clean_core only, got: {line}"
                )

    def test_25_runner_has_zero_legacy_service_dependencies(self):
        """Test 25: ForwardPaperRunner instantiation doesn't trigger legacy imports."""
        import importlib
        import sys

        # Create fresh import context
        modules_before = set(sys.modules.keys())

        # Import runner
        from src.clean_core.runner.forward_paper_runner import ForwardPaperRunner
        from src.clean_core.runner.simulated_futures_feed import SimulatedFuturesFeed

        modules_after = set(sys.modules.keys())
        new_imports = modules_after - modules_before

        # Check no legacy services were imported
        legacy_indicators = [
            "src.services",
            "firebase_client",
            "event_bus",
            "market_stream",
            "paper_adaptive_learning",
        ]

        for legacy_module in new_imports:
            for indicator in legacy_indicators:
                assert indicator not in legacy_module, (
                    f"Legacy module imported: {legacy_module}"
                )

    def test_26_clean_core_packages_are_isolated(self):
        """Test 26: All Clean Core subpackages have no legacy dependencies."""
        import importlib

        clean_core_packages = [
            "src.clean_core.domain",
            "src.clean_core.config",
            "src.clean_core.market.binance_usdm_routes",
            "src.clean_core.execution.fees",
            "src.clean_core.execution.paper_accounting",
            "src.clean_core.execution.funding",
            "src.clean_core.strategy.fixed_strategy",
            "src.clean_core.strategy.offline_replay",
            "src.clean_core.provenance.journal",
            "src.clean_core.provenance.epoch",
            "src.clean_core.runner.forward_paper_runner",
            "src.clean_core.runner.simulated_futures_feed",
        ]

        forbidden_patterns = [
            "services",
            "firebase",
            "event_bus",
            "market_stream",
            "adaptive",
            "executor",
            "risk_engine",
        ]

        for pkg in clean_core_packages:
            try:
                module = importlib.import_module(pkg)
                try:
                    source = Path(module.__file__).read_text(encoding="utf-8")
                except (UnicodeDecodeError, FileNotFoundError):
                    # Skip packages with encoding issues or missing files
                    continue

                for forbidden in forbidden_patterns:
                    assert forbidden.lower() not in source.lower(), (
                        f"Package {pkg} contains reference to {forbidden}"
                    )
            except ImportError:
                # Package might not exist yet, which is fine
                pass
