from __future__ import annotations

import numpy as np
import pandas as pd

from axiom_rift.research.drawdown_fixed_hold import (
    compute_drawdown_fixed_hold_score,
    drawdown_fixed_hold_configurations,
    drawdown_fixed_hold_controlled_chassis,
    drawdown_fixed_hold_protocol_definition,
)
from axiom_rift.research.drawdown_state_replay_job import (
    build_drawdown_replay_job_plan,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0049 import (
    STU0049_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0050 import (
    STU0050_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_semantic_transition import (
    NO_SEMANTIC_TRANSITION_POLICY,
)
from axiom_rift.research.volatility_duration_fixed_hold import (
    compute_volatility_duration_fixed_hold_score,
    volatility_duration_fixed_hold_configurations,
    volatility_duration_fixed_hold_controlled_chassis,
    volatility_duration_fixed_hold_protocol_definition,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (
    build_volatility_duration_fixed_hold_job_plan,
)


FAMILY_AUTHORITY_ID = "historical-family-authority:" + "c" * 64
OBLIGATION_ID = "historical-replay-obligation:" + "d" * 64
PRIOR_EXPOSURE = 630


def _context(family, original_end: int) -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=OBLIGATION_ID,
        family=family,
        prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=original_end,
    )


def test_stu0049_drawdown_phase_family_uses_one_current_trace() -> None:
    definition = drawdown_fixed_hold_protocol_definition(
        _context(STU0049_HISTORICAL_FAMILY, 444)
    )
    configurations = drawdown_fixed_hold_configurations(
        STU0049_HISTORICAL_FAMILY
    )
    assert definition.invariance_keys == (
        "depth_duration_interaction_576",
        "drawdown_recovery_velocity_12",
    )
    assert definition.historical_evaluation_artifacts == ()
    assert (
        definition.semantic_transition_policy
        == NO_SEMANTIC_TRANSITION_POLICY
    )
    assert {configuration.holding_bars for configuration in configurations} == {
        12
    }
    assert {configuration.lookback_bars for configuration in configurations} == {
        576
    }
    assert {
        configuration.selector_quantile_bp for configuration in configurations
    } == {8_500}
    chassis = drawdown_fixed_hold_controlled_chassis(
        historical_family=STU0049_HISTORICAL_FAMILY,
        historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=444,
    )
    assert chassis.baseline_executable.identity not in (
        definition.prospective_executable_ids
    )
    plans = tuple(
        build_drawdown_replay_job_plan(
            mission_id="MIS-0006",
            study_id="STU-TEST-0049",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
            original_family_end_global_exposure_count=444,
            historical_family=STU0049_HISTORICAL_FAMILY,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=OBLIGATION_ID,
        )
        for executable_id in definition.prospective_executable_ids
    )
    assert all(plan.definition.identity == definition.identity for plan in plans)
    assert plans[0].produces_family_cache


def test_stu0050_level_duration_family_uses_bound_selector() -> None:
    definition = volatility_duration_fixed_hold_protocol_definition(
        _context(STU0050_HISTORICAL_FAMILY, 448)
    )
    configurations = volatility_duration_fixed_hold_configurations(
        STU0050_HISTORICAL_FAMILY
    )
    assert definition.invariance_keys == (
        "volatility_duration_96_576",
        "volatility_level_96_576",
    )
    assert {configuration.holding_bars for configuration in configurations} == {
        12
    }
    assert {configuration.state_window for configuration in configurations} == {
        576
    }
    assert {
        configuration.selector_quantile_bp for configuration in configurations
    } == {7_000}
    chassis = volatility_duration_fixed_hold_controlled_chassis(
        historical_family=STU0050_HISTORICAL_FAMILY,
        historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=448,
    )
    assert chassis.baseline_executable.identity not in (
        definition.prospective_executable_ids
    )
    plans = tuple(
        build_volatility_duration_fixed_hold_job_plan(
            mission_id="MIS-0006",
            study_id="STU-TEST-0050",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
            original_family_end_global_exposure_count=448,
            historical_family=STU0050_HISTORICAL_FAMILY,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=OBLIGATION_ID,
        )
        for executable_id in definition.prospective_executable_ids
    )
    assert all(plan.definition.identity == definition.identity for plan in plans)
    assert plans[0].produces_family_cache


def test_new_state_kernels_are_prefix_stable() -> None:
    count = 900
    frame = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=count, freq="5min"),
            "close": 15_000.0
            * np.exp(
                np.linspace(0.0, 0.08, count)
                + 0.01 * np.sin(np.arange(count) / 17.0)
            ),
        }
    )
    for builder, profiles in (
        (
            compute_drawdown_fixed_hold_score,
            (
                "depth_duration_interaction_576",
                "drawdown_recovery_velocity_12",
            ),
        ),
        (
            compute_volatility_duration_fixed_hold_score,
            (
                "volatility_level_96_576",
                "volatility_duration_96_576",
            ),
        ),
    ):
        for profile in profiles:
            full = builder(frame, profile)
            prefix = builder(frame.iloc[:800], profile)
            for full_value, prefix_value in zip(full, prefix, strict=True):
                np.testing.assert_allclose(
                    full_value[:800],
                    prefix_value,
                    equal_nan=True,
                )
