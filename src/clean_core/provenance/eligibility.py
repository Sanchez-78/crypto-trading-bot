"""Learning eligibility resolver for Clean Core RESET R1."""

from dataclasses import dataclass
from typing import Optional
from src.clean_core.provenance.epoch import CleanPaperEpoch
from src.clean_core.domain import ExecutionTruthClass


@dataclass(frozen=True)
class LearningEligibility:
    """
    Verdict on whether a closed outcome can be used for learning/metrics.

    eligible: True if outcome can influence canonical policy/readiness.
    reason: Explains ineligibility (if eligible=False) or type of eligible observation.
    """

    eligible: bool
    reason: str  # e.g., "valid_clean_futures_observation", "legacy_spot_execution_unverified"

    VALID_CLEAN_FUTURES = "valid_clean_futures_observation"
    INVALID_EPOCH = "invalid_epoch"
    LEGACY_SPOT = "legacy_spot_execution_unverified"
    INVALID_MARKET_TAPE = "invalid_market_tape"
    TEST_GENERATED = "test_generated"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"


class LearningEligibilityResolver:
    """
    Determines whether a closed outcome can be used for canonical learning/metrics.

    Rules:
    - FUTURES_PUBLIC_BOOK_MEASURED and FUTURES_RPI_AWARE_MEASURED outcomes eligible for learning
    - LEGACY_SPOT_EXECUTION_UNVERIFIED marked ineligible (archived as discovery only)
    - Invalid epoch/tape/test/duplicate/quarantined marked ineligible
    """

    def __init__(self, epoch: CleanPaperEpoch):
        self.epoch = epoch

    def resolve(
        self,
        closed_outcome: dict,
    ) -> LearningEligibility:
        """
        Resolve eligibility for a closed outcome.

        closed_outcome dict keys:
          - execution_truth_class: str (ExecutionTruthClass value)
          - readiness_eligible: bool
          - net_pnl_pct: float
          - epoch_id: str
          - learning_source: str ("canonical" or "discovery")
          - test_generated: bool (optional)
          - market_tape_status: str (optional, "synced"/"gap_detected"/"stale")
        """

        # Check epoch validity
        if closed_outcome.get("epoch_id") != self.epoch.epoch_id:
            return LearningEligibility(
                eligible=False,
                reason=LearningEligibility.INVALID_EPOCH,
            )

        # Check test flag
        if closed_outcome.get("test_generated", False):
            return LearningEligibility(
                eligible=False,
                reason=LearningEligibility.TEST_GENERATED,
            )

        # Check market tape integrity
        tape_status = closed_outcome.get("market_tape_status", "synced")
        if tape_status != "synced":
            return LearningEligibility(
                eligible=False,
                reason=LearningEligibility.INVALID_MARKET_TAPE,
            )

        # Check execution truth class
        execution_truth = closed_outcome.get("execution_truth_class")

        if execution_truth == ExecutionTruthClass.LEGACY_SPOT_EXECUTION_UNVERIFIED.value:
            return LearningEligibility(
                eligible=False,
                reason=LearningEligibility.LEGACY_SPOT,
            )

        if execution_truth == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED.value:
            # Public book without RPI is measurable but not full readiness
            return LearningEligibility(
                eligible=True,
                reason=LearningEligibility.VALID_CLEAN_FUTURES,
            )

        if execution_truth == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED.value:
            # Full futures measurement with RPI
            return LearningEligibility(
                eligible=True,
                reason=LearningEligibility.VALID_CLEAN_FUTURES,
            )

        # Unknown or missing execution_truth_class
        return LearningEligibility(
            eligible=False,
            reason=LearningEligibility.INVALID_MARKET_TAPE,
        )
