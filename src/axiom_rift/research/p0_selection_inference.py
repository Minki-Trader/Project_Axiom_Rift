"""Historical P0 adapter for the generic selection-inference engine.

Prospective users import ``selection_inference`` without loading the P0 replay
inventory.  Only an explicit historical P0 caller crosses this adapter.
"""

from __future__ import annotations

from axiom_rift.research.p0_replay_inventory import load_p0_replay_inventory
from axiom_rift.research.selection_inference import (
    DEFAULT_ALPHA_PPM,
    DEFAULT_BASE_SEED,
    DEFAULT_BLOCK_LENGTHS,
    DEFAULT_BOOTSTRAP_SAMPLES,
    DEFAULT_MONTE_CARLO_CONFIDENCE_PPM,
    DailyPnlFamily,
    HistoricalSearchContext,
    SelectionFamilyPlan,
    SelectionHypothesis,
    SelectionInferenceResult,
    infer_concurrent_selection_family,
)


P0_REPLAY_HYPOTHESES = tuple(
    SelectionHypothesis(
        hypothesis_id=member["executable_id"],
        registration_id=f"study:{member['study_id']}",
    )
    for member in load_p0_replay_inventory()
)
P0_REPLAY_EXECUTABLE_IDS = tuple(
    hypothesis.hypothesis_id for hypothesis in P0_REPLAY_HYPOTHESES
)
P0_REPLAY_FAMILY_ID = "family:p0-audit-replay-v1"


def infer_p0_simultaneous_forest(
    daily_pnl_by_executable: DailyPnlFamily,
    *,
    historical_context: HistoricalSearchContext,
    alpha_ppm: int = DEFAULT_ALPHA_PPM,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    block_lengths: tuple[int, ...] = DEFAULT_BLOCK_LENGTHS,
    monte_carlo_confidence_ppm: int = DEFAULT_MONTE_CARLO_CONFIDENCE_PPM,
    base_seed: int = DEFAULT_BASE_SEED,
) -> SelectionInferenceResult:
    """Replay the exact six P0 historical axes as one simultaneous forest."""

    plan = SelectionFamilyPlan(
        family_id=P0_REPLAY_FAMILY_ID,
        stage="discovery",
        hypotheses=P0_REPLAY_HYPOTHESES,
        alpha_ppm=alpha_ppm,
        bootstrap_samples=bootstrap_samples,
        block_lengths=block_lengths,
        monte_carlo_confidence_ppm=monte_carlo_confidence_ppm,
        base_seed=base_seed,
    )
    return infer_concurrent_selection_family(
        plan=plan,
        daily_pnl_by_hypothesis=daily_pnl_by_executable,
        historical_context=historical_context,
    )


__all__ = [
    "P0_REPLAY_EXECUTABLE_IDS",
    "P0_REPLAY_FAMILY_ID",
    "P0_REPLAY_HYPOTHESES",
    "infer_p0_simultaneous_forest",
]
