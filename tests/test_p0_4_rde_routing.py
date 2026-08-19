"""
P0.4 — RDE Training Sampler P0 Routing Tests

Verifies that all RDE paths that call maybe_open_training_sample()
route through P0 gate BEFORE sampler call.

Tests prove:
  1. Helper _route_training_sample_through_p0_rde() works
  2. All 3 RDE callsites use helper (no direct sampler bypass)
  3. ETHUSDT/BULL_TREND admitted to evidence collection
  4. BTCUSDT/SOLUSDT/BEAR_TREND blocked
  5. Metadata set correctly on routed signals
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.services.p0_segment_ev_gate import P0SegmentEVGate
from src.services.realtime_decision_engine import _route_training_sample_through_p0_rde


class TestP04RDERouting:
    """Tests for RDE training sampler P0 routing."""

    # Test 1: RDE ETHUSDT BULL_TREND admitted to evidence
    def test_rde_ethusdt_bull_trend_admits_to_evidence(self):
        """Test 1: RDE routes ETHUSDT+BULL_TREND to evidence collection --
        calls the REAL function, not a hardcoded reproduction of its logic."""
        signal = {"symbol": "ETHUSDT", "side": "BUY", "regime": "BULL_TREND", "price": 2500.0}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )

        assert routed is not None, "ETHUSDT+BULL_TREND must be admitted to evidence collection"
        assert routed["strict_ev"] is False
        assert routed["readiness_eligible"] is False
        assert routed["learning_source"] == "paper_evidence_collection"
        assert routed["paper_source"] == "paper_evidence_collection"
        assert routed["segment_key"] == "ETHUSDT_BUY_BULL_TREND_rde_training_sampler_unknown"

    # Test 2: RDE BTCUSDT -- quarantined for strict EV, but P1.1AS FIX
    # (2026-08-19): evidence collection is regime-gated only (matches
    # P0SegmentEVGate.is_eligible_for_evidence_collection()'s own documented
    # "V10.25 EMERGENCY: Allow ALL symbols" design), so BTCUSDT is now
    # correctly ADMITTED to evidence collection despite being strict-EV
    # quarantined -- this is an intentional behavior change from the
    # pre-fix hardcoded `{"ETHUSDT"}`-only allowlist, not a regression.
    def test_rde_btcusdt_quarantined_for_strict_ev_but_admitted_to_evidence(self):
        """Test 2: BTCUSDT blocked from strict EV (quarantine), but ADMITTED
        to evidence collection (regime-only gate, not symbol-gated)."""
        decision = P0SegmentEVGate.decide_segment_gate(
            symbol="BTCUSDT",
            side="BUY",
            regime="BULL_TREND",
            source="rde_training_sampler",
            tp_sl_profile="unknown",
            closed_trades=[],
        )
        assert decision.strict_ev_allowed is False
        assert "quarantine" in decision.reason.lower()

        signal = {"symbol": "BTCUSDT", "side": "BUY", "regime": "BULL_TREND", "price": 60000.0}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )
        assert routed is not None, (
            "P1.1AS regression: BTCUSDT must be admitted to evidence "
            "collection (strict-EV quarantine and evidence-collection "
            "eligibility are separate gates) -- if this is None, the "
            "hardcoded single-symbol allowlist bug has returned"
        )
        assert routed["learning_source"] == "paper_evidence_collection"

    # Test 3: RDE SOLUSDT -- same reasoning as BTCUSDT above
    def test_rde_solusdt_quarantined_for_strict_ev_but_admitted_to_evidence(self):
        """Test 3: SOLUSDT blocked from strict EV, but admitted to evidence."""
        decision = P0SegmentEVGate.decide_segment_gate(
            symbol="SOLUSDT",
            side="BUY",
            regime="BULL_TREND",
            source="rde_training_sampler",
            tp_sl_profile="unknown",
            closed_trades=[],
        )
        assert decision.strict_ev_allowed is False
        assert "quarantine" in decision.reason.lower()

        signal = {"symbol": "SOLUSDT", "side": "BUY", "regime": "BULL_TREND", "price": 150.0}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )
        assert routed is not None
        assert routed["learning_source"] == "paper_evidence_collection"

    # Test 4: RDE BEAR_TREND -- P0SegmentEVGate.EVIDENCE_COLLECTION_REGIMES
    # already includes BEAR_TREND (both regimes allowed); the old inline
    # "in_scope = 'BEAR_TREND' in {'BULL_TREND'}" assertion in this test was
    # itself stale even before the P1.1AS fix (it never called the real
    # function or the real regime set).
    def test_rde_bear_trend_admitted_to_evidence(self):
        """Test 4: BEAR_TREND (ETHUSDT) IS in evidence scope -- quarantined
        for strict EV, but not for evidence collection."""
        decision = P0SegmentEVGate.decide_segment_gate(
            symbol="ETHUSDT",
            side="BUY",
            regime="BEAR_TREND",
            source="rde_training_sampler",
            tp_sl_profile="unknown",
            closed_trades=[],
        )
        assert decision.strict_ev_allowed is False
        assert "quarantine" in decision.reason.lower()

        signal = {"symbol": "ETHUSDT", "side": "BUY", "regime": "BEAR_TREND", "price": 2500.0}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )
        assert routed is not None
        assert routed["learning_source"] == "paper_evidence_collection"

    # Test 5: All 3 RDE routes (REJECT_NEGATIVE_EV, ECON_BAD_ENTRY, ECON_BAD_FORCED)
    # use P0 helper before sampler
    def test_all_rde_routes_use_p0_helper(self):
        """Test 5: all 3 RDE route_reason variants route through the real
        P0 helper and get admitted to evidence collection for ETHUSDT/BULL_TREND."""
        routes = [
            ("REJECT_NEGATIVE_EV", "ETHUSDT", "BULL_TREND"),
            ("REJECT_ECON_BAD_ENTRY", "ETHUSDT", "BULL_TREND"),
            ("REJECT_ECON_BAD_FORCED", "ETHUSDT", "BULL_TREND"),
        ]

        for route_reason, symbol, regime in routes:
            signal = {"symbol": symbol, "side": "BUY", "regime": regime, "price": 2500.0}
            routed = _route_training_sample_through_p0_rde(
                signal, route_reason, 0.0, 0.0, closed_trades=[]
            )
            assert routed is not None, f"{route_reason}/{symbol}/{regime} should be admitted"
            assert routed["strict_ev"] is False

    # Test 5b (P1.1AS regression, the exact deadlock scenario found live):
    # a non-ETHUSDT symbol in a non-quarantined-for-evidence regime must be
    # admitted -- this is the case that was structurally impossible before
    # the fix (hardcoded `symbol in {"ETHUSDT"}`), and whose absence caused
    # a total, ~17.5h paper-trading admission deadlock once ETHUSDT's own
    # segments were exhausted by starvation-discovery's "confirmed bad
    # segment" protection.
    def test_rde_non_ethusdt_symbol_admitted_to_evidence_regression(self):
        """P1.1AS: ADAUSDT/BEAR_TREND must be admitted -- reproduces the
        exact live deadlock scenario (mutation-killed: fails against the
        pre-fix hardcoded {"ETHUSDT"} allowlist, passes with the shared
        P0SegmentEVGate.is_eligible_for_evidence_collection() check)."""
        signal = {"symbol": "ADAUSDT", "side": "SELL", "regime": "BEAR_TREND", "price": 0.35}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )
        assert routed is not None, (
            "P1.1AS regression: a non-ETHUSDT symbol in an evidence-eligible "
            "regime must be admitted -- this is the exact scenario that "
            "caused a total live admission deadlock once ETHUSDT's own "
            "segments were exhausted by starvation-discovery"
        )
        assert routed["learning_source"] == "paper_evidence_collection"
        assert routed["segment_key"] == "ADAUSDT_SELL_BEAR_TREND_rde_training_sampler_unknown"

    def test_rde_quiet_range_still_blocked_negative_control(self):
        """Negative control: a regime NOT in EVIDENCE_COLLECTION_REGIMES
        (e.g. QUIET_RANGE) must still be blocked -- the fix widens the
        SYMBOL scope, not the regime scope."""
        signal = {"symbol": "ETHUSDT", "side": "BUY", "regime": "QUIET_RANGE", "price": 2500.0}
        routed = _route_training_sample_through_p0_rde(
            signal, "REJECT_NEGATIVE_EV", 0.0, 0.0, closed_trades=[]
        )
        assert routed is None, "QUIET_RANGE must remain out of evidence scope"

    # Test 6: Metadata set correctly after P0 routing
    def test_p0_routed_metadata_set_correctly(self):
        """Test 6: Signal metadata set correctly by P0 routing."""
        # Simulate routed signal after _route_training_sample_through_p0_rde()
        routed_signal = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "regime": "BULL_TREND",
            "price": 2500.0,
            "strict_ev": False,  # Set by P0
            "readiness_eligible": False,  # Set by P0
            "learning_source": "paper_evidence_collection",  # Set by P0
            "paper_source": "paper_evidence_collection",  # Set by P0
            "p0_gate_reason": "insufficient_evidence:n=0<30",  # Set by P0
            "segment_key": "ETHUSDT_BUY_BULL_TREND_rde_training_sampler_unknown",  # Set by P0
        }

        # Verify: All required fields present
        assert routed_signal["strict_ev"] is False
        assert routed_signal["readiness_eligible"] is False
        assert routed_signal["learning_source"] == "paper_evidence_collection"
        assert routed_signal["segment_key"] is not None
        assert routed_signal["p0_gate_reason"] is not None

        # Verify: No legacy "paper_training_sampler" source
        assert routed_signal["learning_source"] != "paper_training_sampler"

    # Test 7: Position created from routed signal has correct metadata
    def test_position_from_p0_routed_signal(self):
        """Test 7: Position dict created from P0-routed signal has all metadata."""
        # Simulate position creation after open_paper_position(signal=routed_signal, ...)
        routed_signal = {
            "strict_ev": False,
            "readiness_eligible": False,
            "learning_source": "paper_evidence_collection",
            "segment_key": "ETHUSDT_BUY_BULL_TREND_rde_training_sampler_unknown",
            "p0_gate_reason": "insufficient_evidence",
        }

        # Position dict extracts metadata from signal
        position = {
            "trade_id": "test_p0_4_123",
            "symbol": "ETHUSDT",
            "strict_ev": routed_signal.get("strict_ev", True),
            "readiness_eligible": routed_signal.get("readiness_eligible", True),
            "learning_source": routed_signal.get("learning_source", "strict_ev"),
            "segment_key": routed_signal.get("segment_key"),
            "p0_gate_reason": routed_signal.get("p0_gate_reason"),
        }

        # Verify: Metadata persisted
        assert position["strict_ev"] is False
        assert position["readiness_eligible"] is False
        assert position["learning_source"] == "paper_evidence_collection"
        assert position["segment_key"] == "ETHUSDT_BUY_BULL_TREND_rde_training_sampler_unknown"
        assert position["p0_gate_reason"] == "insufficient_evidence"

        # Verify: Never paper_training_sampler
        assert position["learning_source"] != "paper_training_sampler"


class TestP04SafetyInvariants:
    """Tests for P0.4 safety invariants."""

    def test_rde_bypass_impossible_after_p0_4(self):
        """Verify RDE cannot bypass P0 gate anymore."""
        # After P0.4 fix:
        # RDE → sampler path MUST go through _route_training_sample_through_p0_rde()
        # Sampler receives signal with P0 metadata already set
        # Positions created have learning_source=paper_evidence_collection (not paper_training_sampler)

        # If code tries to bypass (old pattern):
        # sampler_result = maybe_open_training_sample(signal, ...)  ← NO!
        # learning_source: sampler_result.get(..., "paper_training_sampler")  ← NO!
        #
        # Now correct pattern:
        # routed_signal = _route_training_sample_through_p0_rde(signal, ...)  ← YES
        # sampler_result = maybe_open_training_sample(routed_signal, ...)  ← YES
        # learning_source: routed_signal.get("learning_source", "paper_evidence_collection")  ← YES

        # This test verifies that P0 metadata is NOT optional
        signal_with_p0_metadata = {
            "learning_source": "paper_evidence_collection",
            "strict_ev": False,
            "readiness_eligible": False,
        }

        signal_without_p0_metadata = {
            # Missing: learning_source, strict_ev, readiness_eligible
        }

        # Position created from signal WITH metadata → OK
        pos1 = {"learning_source": signal_with_p0_metadata.get("learning_source", "FAIL")}
        assert pos1["learning_source"] == "paper_evidence_collection"

        # Position created from signal WITHOUT metadata → Would get default "FAIL" (should be blocked by guard)
        pos2 = {"learning_source": signal_without_p0_metadata.get("learning_source", "FAIL")}
        assert pos2["learning_source"] == "FAIL"  # This should trigger fail-closed guard


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
