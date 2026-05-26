"""Tests for execution truth class semantics and market observation roles."""

import pytest
from src.clean_core.domain import (
    ExecutionTruthClass,
    MarketObservationRole,
    MarketSourceIdentity,
)


class TestTruthSemantics:
    """Validate execution truth classification and observation roles."""

    def test_1_futures_public_book_is_executable_truth(self):
        """Test 1: FUTURES_PUBLIC_BOOK_MEASURED is valid execution truth."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version="R1",
        )
        assert source.execution_truth_class is not None
        assert source.execution_truth_class == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED

    def test_2_mark_price_is_telemetry_not_execution_truth(self):
        """Test 2: Mark price stream has no execution_truth_class (telemetry only)."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="mark_telemetry",
            execution_truth_class=None,  # Telemetry, not executable
            rpi_visibility=False,
            route_version="R1",
            observation_role=MarketObservationRole.MARK_FUNDING_TELEMETRY,
        )
        assert source.execution_truth_class is None
        assert source.observation_role == MarketObservationRole.MARK_FUNDING_TELEMETRY
        assert source.price_source == "mark_telemetry"

    def test_3_rpi_aware_is_executable_truth(self):
        """Test 3: FUTURES_RPI_AWARE_MEASURED is valid execution truth."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
            rpi_visibility=True,
            route_version="R1",
        )
        assert source.execution_truth_class == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
        assert source.rpi_visibility is True

    def test_4_default_observation_role_is_execution_book(self):
        """Test 4: Default observation role is EXECUTION_BOOK."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version="R1",
        )
        assert source.observation_role == MarketObservationRole.EXECUTION_BOOK

    def test_5_telemetry_role_excludes_execution_truth(self):
        """Test 5: Telemetry observation role requires execution_truth_class=None."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="mark_telemetry",
            execution_truth_class=None,
            rpi_visibility=False,
            route_version="R1",
            observation_role=MarketObservationRole.MARK_FUNDING_TELEMETRY,
        )
        assert source.execution_truth_class is None
        assert source.observation_role == MarketObservationRole.MARK_FUNDING_TELEMETRY

    def test_6_trade_flow_telemetry_is_observable_not_executable(self):
        """Test 6: Trade flow telemetry has no execution truth."""
        source = MarketSourceIdentity(
            venue="binance_usdm",
            instrument="BTCUSDT",
            price_source="public_trades",
            execution_truth_class=None,
            rpi_visibility=False,
            route_version="R1",
            observation_role=MarketObservationRole.TRADE_FLOW_TELEMETRY,
        )
        assert source.execution_truth_class is None
        assert source.observation_role == MarketObservationRole.TRADE_FLOW_TELEMETRY

    def test_7_spot_execution_unverified_exists_for_legacy(self):
        """Test 7: LEGACY_SPOT_EXECUTION_UNVERIFIED enum value exists."""
        assert hasattr(ExecutionTruthClass, "LEGACY_SPOT_EXECUTION_UNVERIFIED")
        assert ExecutionTruthClass.LEGACY_SPOT_EXECUTION_UNVERIFIED is not None

    def test_8_all_execution_truth_classes_enumerated(self):
        """Test 8: All required execution truth classes exist."""
        required = [
            "FUTURES_PUBLIC_BOOK_MEASURED",
            "FUTURES_RPI_AWARE_MEASURED",
            "LEGACY_SPOT_EXECUTION_UNVERIFIED",
        ]
        for cls_name in required:
            assert hasattr(ExecutionTruthClass, cls_name), f"Missing {cls_name}"

    def test_9_all_observation_roles_enumerated(self):
        """Test 9: All observation roles exist."""
        required = [
            "EXECUTION_BOOK",
            "MARK_FUNDING_TELEMETRY",
            "TRADE_FLOW_TELEMETRY",
        ]
        for role_name in required:
            assert hasattr(MarketObservationRole, role_name), f"Missing {role_name}"
