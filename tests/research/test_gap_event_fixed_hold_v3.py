from __future__ import annotations

from pathlib import Path

from axiom_rift.operations.job_implementation_authority import (
    hardcoded_control_ids,
)
from axiom_rift.core.canonical import parse_canonical
import numpy as np
import pytest
import axiom_rift.research.gap_event_fixed_hold_v3 as v3_module
import axiom_rift.research.gap_event_fixed_hold_v3_job as v3_job_module

from axiom_rift.research.discovery import DiscoveryBoundaryError
from axiom_rift.research.gap_event_fixed_hold_v3 import (
    GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS,
    calibrate_gap_event_fixed_hold_v3_selector,
    gap_event_fixed_hold_v3_controlled_chassis,
    gap_event_fixed_hold_v3_protocol_definition,
)
from axiom_rift.research.gap_event_fixed_hold_v3_job import (
    build_gap_event_fixed_hold_v3_job_plan,
    gap_event_fixed_hold_v3_job_implementation_artifact,
)
from axiom_rift.research.gap_fixed_hold import gap_fixed_hold_protocol_definition
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0046 import (
    STU0046_HISTORICAL_FAMILY,
)


FAMILY_AUTHORITY_ID = "historical-family-authority:" + "a" * 64
OBLIGATION_ID = "historical-replay-obligation:" + "b" * 64
PRIOR_EXPOSURE = 638
ORIGINAL_END = 432


def _context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=OBLIGATION_ID,
        family=STU0046_HISTORICAL_FAMILY,
        prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=ORIGINAL_END,
    )


def test_v3_is_distinct_and_registers_only_the_feasible_train_floor() -> None:
    context = _context()
    legacy = gap_fixed_hold_protocol_definition(context)
    revised = gap_event_fixed_hold_v3_protocol_definition(context)
    chassis = gap_event_fixed_hold_v3_controlled_chassis(
        historical_family=context.family,
        historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=ORIGINAL_END,
    )
    selector_specs = tuple(
        component.specification()
        for component in chassis.baseline_executable.components
        if component.protocol.startswith("selector.")
    )

    assert revised.identity != legacy.identity
    assert set(revised.prospective_executable_ids).isdisjoint(
        legacy.prospective_executable_ids
    )
    assert len(selector_specs) == 1
    assert selector_specs[0]["minimum_train_observations"] == 350
    assert selector_specs[0]["observed_train_event_count_range"] == [386, 392]
    assert selector_specs[0]["outcome_values_used_for_floor"] is False

    plans = tuple(
        build_gap_event_fixed_hold_v3_job_plan(
            mission_id="MIS-0006",
            study_id="STU-0117",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
            original_family_end_global_exposure_count=ORIGINAL_END,
            historical_family=context.family,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=OBLIGATION_ID,
        )
        for executable_id in revised.prospective_executable_ids
    )
    assert all(plan.definition.identity == revised.identity for plan in plans)


def test_v3_selector_floor_is_exact() -> None:
    values = np.arange(GAP_EVENT_V3_MINIMUM_TRAIN_OBSERVATIONS, dtype=float)
    mask = np.ones(len(values), dtype=bool)
    assert np.isfinite(calibrate_gap_event_fixed_hold_v3_selector(values, mask))

    with pytest.raises(DiscoveryBoundaryError, match="too small"):
        calibrate_gap_event_fixed_hold_v3_selector(values[:-1], mask[:-1])


def test_v3_runtime_closure_binds_new_and_frozen_sources() -> None:
    artifact = parse_canonical(
        gap_event_fixed_hold_v3_job_implementation_artifact()
    )
    assert isinstance(artifact, dict)
    paths = {str(value["path"]) for value in artifact["dependencies"]}
    assert "axiom_rift/research/gap_event_fixed_hold_v3.py" in paths
    assert "axiom_rift/research/gap_fixed_hold.py" in paths
    assert "axiom_rift/research/historical_family_stu0046.py" not in paths


def test_v3_runtime_sources_use_declarative_control_binding() -> None:
    assert hardcoded_control_ids(
        Path(v3_module.__file__).read_bytes()
    ) == ()
    assert hardcoded_control_ids(
        Path(v3_job_module.__file__).read_bytes()
    ) == ()
