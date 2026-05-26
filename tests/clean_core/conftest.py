"""Shared fixtures for Clean Core RESET R1 tests."""

import pytest
from src.clean_core.domain import ExecutionTruthClass, MarketSourceIdentity
from src.clean_core.market.binance_usdm_routes import BinanceUsdmRoutes
from src.clean_core.market.local_book import LocalOrderBook, DepthSnapshot, DepthEvent
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.provenance.epoch import CleanPaperEpoch
from src.clean_core.provenance.journal import CleanCoreJournal
import tempfile
import os


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def routes():
    """BinanceUsdmRoutes instance for testing."""
    return BinanceUsdmRoutes()


@pytest.fixture
def market_source_futures():
    """Sample Futures market source."""
    return MarketSourceIdentity(
        venue="binance_usdm",
        instrument="BTCUSDT",
        price_source="public_book",
        execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
        rpi_visibility=False,
        route_version="R1",
    )


@pytest.fixture
def market_source_futures_rpi():
    """Sample Futures market source with RPI."""
    return MarketSourceIdentity(
        venue="binance_usdm",
        instrument="BTCUSDT",
        price_source="rpi_marked",
        execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
        rpi_visibility=True,
        route_version="R1",
    )


@pytest.fixture
def market_source_legacy():
    """Sample legacy Spot source (for negative test)."""
    return MarketSourceIdentity(
        venue="binance_usdm",
        instrument="BTCUSDT",
        price_source="spot_book",
        execution_truth_class=ExecutionTruthClass.LEGACY_SPOT_EXECUTION_UNVERIFIED,
        rpi_visibility=False,
        route_version="R1",
    )


@pytest.fixture
def local_book():
    """LocalOrderBook instance."""
    return LocalOrderBook("BTCUSDT", stale_threshold_ms=1000)


@pytest.fixture
def depth_snapshot():
    """Sample depth snapshot."""
    return DepthSnapshot(
        last_update_id=1000,
        bids=[[50000.0, 1.0], [49999.0, 2.0]],
        asks=[[50001.0, 1.5], [50002.0, 2.5]],
        timestamp_ms=1234567890000,
        source="rest_api",
    )


@pytest.fixture
def fee_schedule():
    """Standard fee schedule."""
    return FeeSchedule.binance_usdm_standard()


@pytest.fixture
def clean_epoch(temp_dir):
    """CleanPaperEpoch instance."""
    return CleanPaperEpoch(
        epoch_id="clean_core_r1_test_001",
        status="active",
        created_utc="2026-05-26T12:00:00Z",
        started_utc="2026-05-26T12:05:00Z",
        commit_hash="abc123",
        config_version="R1",
        market_source_version="R1",
    )


@pytest.fixture
def journal(temp_dir):
    """CleanCoreJournal instance with temp file."""
    journal_path = os.path.join(temp_dir, "test_journal.jsonl")
    return CleanCoreJournal(journal_path)
