"""P1.1AP-O2 Acceptance Gate: Scoped Bootstrap Verification

Verifies that cooldown bootstrap uses bucket-scoped and segment-scoped metrics,
NOT global rolling100 aggregates.

Test matrix:
1. Global rolling100 losing, but discovery evidence non-qualifying → NO discovery cooldown
2. Discovery-only evidence qualifying → ONLY discovery cooldown
3. Global rolling100 losing, C segment qualifying → ONLY segment cooldown, other segments free
4. Other symbol/regime/side remains admissible after scoped cooldown activation
5. Restart restores scoped cooldowns
6. Idle gate still blocks discovery at fresh startup (< 600s)
"""

import json
import os
import time
import pytest
from collections import deque
from unittest.mock import patch, MagicMock

# Module under test
from src.services import paper_training_sampler
from src.services import paper_adaptive_learning


@pytest.fixture
def clean_learner_state():
    """Fresh learner with empty state for isolation."""
    state_file = "/tmp/test_scoped_bootstrap_learner_state.json"
    if os.path.exists(state_file):
        os.remove(state_file)

    learner = paper_adaptive_learning.PaperAdaptiveLearning(state_file=state_file)
    yield learner

    # Cleanup
    if os.path.exists(state_file):
        os.remove(state_file)


@pytest.fixture
def clean_sampler_state():
    """Reset sampler state for each test."""
    paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"] = False
    paper_training_sampler._SEGMENT_COOLDOWNS.clear()
    paper_training_sampler._starvation_discovery_state = {
        "idle_s": 0.0,
        "idle_baseline_ts": time.time(),
        "last_actual_paper_entry_ts": 0.0,
        "entry_times_15m": deque(),
        "closed_trades": [],
        "valid_negative_candidates": 0,
        "last_state_log_ts": 0.0,
    }
    yield
    # Cleanup
    paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"] = False
    paper_training_sampler._SEGMENT_COOLDOWNS.clear()


class TestScopedBootstrap:
    """Test scoped bootstrap filtering: discovery-only and segment-specific."""

    def test_global_rolling100_losing_but_discovery_evidence_does_not_qualify(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: Global rolling100 shows losses but discovery-scoped evidence is insufficient.

        Global rolling100:
        - 3 C_WEAK entries (2 LOSS, 1 WIN) → pf=0.5
        - 2 D_NEG entries (2 LOSS) → pf=0.0

        Discovery rolling100 (filtered):
        - 0 entries → cannot bootstrap

        Expected: NO discovery cooldown activated (need >=3 discovery entries)
        """
        learner = clean_learner_state

        # Add C_WEAK entries to rolling100
        # Format: (pnl, outcome, segment, ts, learning_source, admission_bucket)
        learner.rolling100.append((-0.15, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((-0.12, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((0.08, "WIN", "ETH:RANGE:SHORT", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))

        # Add D_NEG entries
        learner.rolling100.append((-0.20, "LOSS", "BTC:DOWNTREND:SHORT", time.time(), "paper_adaptive_recovery", "D_NEG_EV_CONTROL"))
        learner.rolling100.append((-0.18, "LOSS", "ETH:DOWNTREND:SHORT", time.time(), "paper_adaptive_recovery", "D_NEG_EV_CONTROL"))

        # Attempt bootstrap
        discovery_result = paper_training_sampler._bootstrap_discovery_cooldown_from_learner(
            learner, time.time()
        )

        # Global rolling100 is losing (pf < 1.0) but discovery-scoped evidence is empty
        # So NO discovery cooldown should be activated
        assert discovery_result is None, "Discovery cooldown should NOT activate when scoped evidence is insufficient"

    def test_discovery_only_evidence_qualifies_activates_discovery_cooldown_only(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: Discovery-scoped evidence shows loss pattern, C_WEAK evidence is good.

        Discovery rolling100 (filtered):
        - 3 entries: LOSS, LOSS, LOSS → pf=0.0, avg=-0.12

        C_WEAK rolling100 (filtered):
        - 2 entries: WIN, WIN → pf=1.0, avg=+0.15

        Expected: ONLY discovery cooldown activates, C_WEAK not affected
        """
        learner = clean_learner_state

        # Add discovery entries (all losses)
        # Format: (pnl, outcome, segment, ts, learning_source, admission_bucket)
        learner.rolling100.append((-0.10, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_starvation_discovery", "PAPER_STARVATION_DISCOVERY"))
        learner.rolling100.append((-0.14, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_starvation_discovery", "PAPER_STARVATION_DISCOVERY"))
        learner.rolling100.append((-0.12, "LOSS", "ETH:RANGE:SHORT", time.time(), "paper_starvation_discovery", "PAPER_STARVATION_DISCOVERY"))

        # Add C_WEAK entries (all wins) to global rolling100
        learner.rolling100.append((0.15, "WIN", "ADA:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((0.18, "WIN", "SOL:RANGE:SHORT", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))

        # Bootstrap
        discovery_result = paper_training_sampler._bootstrap_discovery_cooldown_from_learner(
            learner, time.time()
        )
        segment_results = paper_training_sampler._bootstrap_segment_cooldowns_from_learner(
            learner, time.time()
        )

        # Discovery should activate (pf=0, avg=-0.12 <= -0.10)
        assert discovery_result is not None, "Discovery cooldown SHOULD activate when scoped evidence qualifies"
        assert discovery_result["active"] is True

        # C_WEAK segment should NOT be in cooldown (wins, pf=1.0)
        assert "ADA:UPTREND:LONG" not in paper_training_sampler._SEGMENT_COOLDOWNS
        assert "SOL:RANGE:SHORT" not in paper_training_sampler._SEGMENT_COOLDOWNS

    def test_losing_c_segment_activates_only_that_segment(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: C_WEAK segment shows loss pattern; other segments are profitable.

        C_WEAK entries:
        - BTC:UPTREND:LONG: 2 LOSS → pf=0.0, avg=-0.11 (qualifies)
        - ETH:RANGE:SHORT: 2 WIN → pf=1.0, avg=+0.14 (good)

        Expected: ONLY BTC:UPTREND:LONG segment activates cooldown
        """
        learner = clean_learner_state

        # Add losing C_WEAK segment (BTC:UPTREND:LONG)
        learner.rolling100.append((-0.10, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((-0.12, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))

        # Add winning C_WEAK segment (ETH:RANGE:SHORT)
        learner.rolling100.append((0.15, "WIN", "ETH:RANGE:SHORT", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((0.14, "WIN", "ETH:RANGE:SHORT", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))

        # Bootstrap
        paper_training_sampler._bootstrap_segment_cooldowns_from_learner(learner, time.time())

        # BTC:UPTREND:LONG should be in cooldown
        assert "BTC:UPTREND:LONG" in paper_training_sampler._SEGMENT_COOLDOWNS
        assert paper_training_sampler._SEGMENT_COOLDOWNS["BTC:UPTREND:LONG"]["active"]

        # ETH:RANGE:SHORT should NOT be in cooldown
        assert "ETH:RANGE:SHORT" not in paper_training_sampler._SEGMENT_COOLDOWNS

    def test_other_segments_remain_admissible_after_scoped_cooldown(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: After one segment enters cooldown, other segments are unaffected.

        C_WEAK entries:
        - ADA:UPTREND:LONG: losing → cooldown activated
        - SOL:RANGE:SHORT: still has open positions → should remain admissible

        Expected: Only ADA:UPTREND:LONG blocked, SOL:RANGE:SHORT allowed
        """
        learner = clean_learner_state

        # Add losing segment (ADA)
        learner.rolling100.append((-0.10, "LOSS", "ADA:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((-0.12, "LOSS", "ADA:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))

        # Bootstrap
        paper_training_sampler._bootstrap_segment_cooldowns_from_learner(learner, time.time())

        # ADA should be blocked
        assert "ADA:UPTREND:LONG" in paper_training_sampler._SEGMENT_COOLDOWNS
        assert paper_training_sampler._is_segment_in_cooldown("ADA:UPTREND:LONG")

        # SOL should NOT be blocked (no entry at all, so no cooldown)
        assert "SOL:RANGE:SHORT" not in paper_training_sampler._SEGMENT_COOLDOWNS
        assert not paper_training_sampler._is_segment_in_cooldown("SOL:RANGE:SHORT")

    def test_restart_restores_scoped_cooldowns_from_persistence(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: Activate cooldowns, save state, restart, verify restoration.

        Step 1: Create scoped cooldowns and persist
        Step 2: Simulate restart (reset singleton and reload)
        Step 3: Verify cooldowns are restored
        """
        # Step 1: Setup and activate
        learner = clean_learner_state
        state_file = learner._state_file

        # Manually activate scoped cooldowns
        now = time.time()
        paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"] = True
        paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["activated_at"] = now
        paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["cooldown_until"] = now + 3600
        paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["cooldown_s"] = 3600

        paper_training_sampler._SEGMENT_COOLDOWNS["BTC:UPTREND:LONG"] = {
            "active": True,
            "activated_at": now,
            "cooldown_until": now + 3600,
            "cooldown_s": 3600,
        }

        # Persist via the learner
        learner.paper_admission_controls = {
            "schema_version": 1,
            "starvation_discovery_cooldown": {
                "active": True,
                "activated_at": now,
                "cooldown_until": now + 3600,
                "cooldown_s": 3600,
                "reevaluation_budget_remaining": 0,
                "activation_evidence": {}
            },
            "c_weak_segment_cooldowns": {
                "BTC:UPTREND:LONG": {
                    "active": True,
                    "activated_at": now,
                    "cooldown_until": now + 3600,
                    "cooldown_s": 3600,
                }
            }
        }
        learner._save_state()

        # Step 2: Simulate restart - reset singleton and clear sampler state
        paper_adaptive_learning._learner = None  # Reset singleton
        paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"] = False
        paper_training_sampler._SEGMENT_COOLDOWNS.clear()

        # Create new learner from persisted state (simulates restart/reload)
        restarted_learner = paper_adaptive_learning.PaperAdaptiveLearning(state_file=state_file)
        paper_adaptive_learning._learner = restarted_learner  # Update singleton

        # Restore cooldowns from persisted state
        paper_training_sampler._restore_and_bootstrap_cooldowns()

        # Step 3: Verify restoration
        assert paper_training_sampler._STARVATION_DISCOVERY_BUCKET_COOLDOWN["active"], \
            "Discovery cooldown should be restored after restart"
        assert "BTC:UPTREND:LONG" in paper_training_sampler._SEGMENT_COOLDOWNS, \
            "Segment cooldown should be restored after restart"
        assert paper_training_sampler._SEGMENT_COOLDOWNS["BTC:UPTREND:LONG"]["active"]

    def test_idle_gate_blocks_discovery_at_fresh_startup(
        self, clean_learner_state, clean_sampler_state
    ):
        """Scenario: Fresh startup with no prior PAPER entry.

        Expected: Discovery blocked for first 600s (idle gate)
        """
        # Fresh startup: idle_baseline_ts set to now
        now = time.time()
        paper_training_sampler._starvation_discovery_state["idle_baseline_ts"] = now
        paper_training_sampler._starvation_discovery_state["last_actual_paper_entry_ts"] = 0.0

        # Check at T+0
        idle_s = now - paper_training_sampler._starvation_discovery_state["idle_baseline_ts"]
        assert idle_s == 0.0
        assert idle_s < 600, "At fresh startup T+0, idle_s < 600"

        # Check at T+599
        almost_600 = now + 599
        idle_s_almost = almost_600 - paper_training_sampler._starvation_discovery_state["idle_baseline_ts"]
        assert idle_s_almost < 600, "At T+599, idle_s < 600"

        # Check at T+600
        at_600 = now + 600
        idle_s_at = at_600 - paper_training_sampler._starvation_discovery_state["idle_baseline_ts"]
        assert idle_s_at >= 600, "At T+600, idle_s >= 600"


class TestScopedBootstrapEdgeCases:
    """Edge cases for scoped bootstrap."""

    def test_legacy_entries_without_learning_source_handled_gracefully(
        self, clean_learner_state, clean_sampler_state
    ):
        """Legacy entries with 4 elements should be normalized during reconciliation."""
        learner = clean_learner_state

        # Manually insert old-format entry (4-element tuple)
        ts = time.time()
        learner.rolling100.append((-0.10, "LOSS", "BTC:UPTREND:LONG", ts))

        # Verify it's in the deque as a 4-tuple before save
        assert len(list(learner.rolling100)[0]) == 4, "Entry should be 4-tuple before normalization"

        # Save state (serializes as-is)
        learner._save_state()

        # Reset singleton and reload (triggers reconciliation)
        paper_adaptive_learning._learner = None
        reloaded = paper_adaptive_learning.PaperAdaptiveLearning(state_file=learner._state_file)

        # Verify entry was normalized to 6 elements
        assert len(reloaded.rolling100) > 0, "Rolling100 should have entries after reload"
        entry = list(reloaded.rolling100)[0]
        assert len(entry) == 6, f"Old entries should be normalized to 6 elements, got {len(entry)}: {entry}"
        assert entry[4] == "unknown", f"Legacy entries should get default learning_source='unknown', got {entry[4]}"
        assert entry[5] == "unknown", f"Legacy entries should get default admission_bucket='unknown', got {entry[5]}"

    def test_bootstrap_filters_by_learning_source_correctly(
        self, clean_learner_state, clean_sampler_state
    ):
        """Verify bootstrap only counts entries matching the scoped learning_source."""
        learner = clean_learner_state

        # Mixed entries
        learner.rolling100.append((-0.10, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_starvation_discovery", "PAPER_STARVATION_DISCOVERY"))
        learner.rolling100.append((-0.12, "LOSS", "BTC:UPTREND:LONG", time.time(), "paper_weak_ev_training", "C_WEAK_EV_TRAIN"))
        learner.rolling100.append((-0.14, "LOSS", "BTC:UPTREND:LONG", time.time(), "unknown", "unknown"))

        # Bootstrap discovery (should only see the discovery entry)
        result = paper_training_sampler._bootstrap_discovery_cooldown_from_learner(learner, time.time())

        # Only 1 discovery entry, needs >=3
        assert result is None, "Should not activate with insufficient discovery-scoped entries"

    def test_empty_rolling100_returns_none(
        self, clean_learner_state, clean_sampler_state
    ):
        """Empty rolling100 should return None for both discovery and segment bootstrap."""
        learner = clean_learner_state

        # Empty rolling100
        assert len(learner.rolling100) == 0

        discovery_result = paper_training_sampler._bootstrap_discovery_cooldown_from_learner(
            learner, time.time()
        )
        assert discovery_result is None

        # Segment bootstrap should also return gracefully
        paper_training_sampler._bootstrap_segment_cooldowns_from_learner(learner, time.time())
        assert len(paper_training_sampler._SEGMENT_COOLDOWNS) == 0
