from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.gap_fixed_hold import (
    causal_gap_fixed_hold_spread,
    compute_gap_fixed_hold_score,
    gap_fixed_hold_configurations,
    gap_fixed_hold_controlled_chassis,
    gap_fixed_hold_protocol_definition,
)
from axiom_rift.research.gap_fixed_hold_job import (
    RUNTIME_ADAPTER,
    build_gap_fixed_hold_job_plan,
    gap_fixed_hold_job_implementation_artifact,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0046 import (
    STU0046_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0047 import (
    STU0047_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.research.implementation_closure import (
    require_current_job_source_closure,
)
from axiom_rift.research.scientific_trace import GAP_REPLAY_TRACE_PROTOCOL_ID


FAMILY_AUTHORITY_ID = "historical-family-authority:" + "a" * 64
OBLIGATION_ID = "historical-replay-obligation:" + "b" * 64
PRIOR_EXPOSURE = 630


@pytest.mark.parametrize(
    ("family", "original_end", "holding_bars", "profiles"),
    (
        (
            STU0046_HISTORICAL_FAMILY,
            424,
            12,
            {"open_gap_30m", "first_bar_response_30m"},
        ),
        (
            STU0047_HISTORICAL_FAMILY,
            436,
            6,
            {
                "residual_gap_after_first_bar",
                "gap_fill_fraction_after_first_bar",
            },
        ),
    ),
)
def test_gap_definition_is_exactly_writer_bound(
    family,
    original_end: int,
    holding_bars: int,
    profiles: set[str],
) -> None:
    context = HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=OBLIGATION_ID,
        family=family,
        prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=original_end,
    )
    definition = gap_fixed_hold_protocol_definition(context)
    configurations = gap_fixed_hold_configurations(family)

    assert definition.family == family
    assert definition.protocol_id == GAP_REPLAY_TRACE_PROTOCOL_ID
    assert definition.historical_context_id == FAMILY_AUTHORITY_ID
    assert definition.historical_prior_global_exposure_count == PRIOR_EXPOSURE
    assert definition.original_family_end_global_exposure_count == original_end
    assert definition.invariance_keys == tuple(
        sorted(configuration.profile for configuration in configurations[::2])
    )
    assert len(set(definition.prospective_executable_ids)) == 4
    assert {configuration.profile for configuration in configurations} == profiles
    assert {configuration.holding_bars for configuration in configurations} == {
        holding_bars
    }
    assert tuple(
        configuration.historical_reference_executable_id
        for configuration in configurations
    ) == tuple(
        member.historical_reference_executable_id for member in family.members
    )


def test_gap_chassis_and_job_plans_share_one_definition() -> None:
    family = STU0047_HISTORICAL_FAMILY
    original_end = 436
    context = HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=OBLIGATION_ID,
        family=family,
        prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=original_end,
    )
    definition = gap_fixed_hold_protocol_definition(context)
    chassis = gap_fixed_hold_controlled_chassis(
        historical_family=family,
        historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=original_end,
    )
    assert chassis.baseline_executable.identity not in (
        definition.prospective_executable_ids
    )

    plans = tuple(
        build_gap_fixed_hold_job_plan(
            mission_id="MIS-0006",
            study_id="STU-TEST-GAP",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
            original_family_end_global_exposure_count=original_end,
            historical_family=family,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=OBLIGATION_ID,
        )
        for executable_id in definition.prospective_executable_ids
    )
    assert all(plan.definition.identity == definition.identity for plan in plans)
    assert plans[0].produces_family_cache
    assert all(not plan.produces_family_cache for plan in plans[1:])


def test_gap_feature_profiles_are_causal_and_prefix_stable() -> None:
    count = 720
    time_ns = np.arange(count, dtype=np.int64) * 300_000_000_000
    for boundary in range(120, count, 120):
        time_ns[boundary:] += 1_800_000_000_000
    close = 15_000.0 * np.exp(
        np.linspace(0.0, 0.04, count)
        + 0.002 * np.sin(np.arange(count) / 11.0)
    )
    opening = close * (1 + 0.0001 * np.cos(np.arange(count) / 7.0))
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(time_ns),
            "open": opening,
            "close": close,
        }
    )
    for profile in (
        "open_gap_30m",
        "first_bar_response_30m",
        "residual_gap_after_first_bar",
        "gap_fill_fraction_after_first_bar",
    ):
        full = compute_gap_fixed_hold_score(frame, profile)
        prefix = compute_gap_fixed_hold_score(frame.iloc[:600], profile)
        assert all(len(value) == count for value in full)
        for full_value, prefix_value in zip(full, prefix, strict=True):
            np.testing.assert_allclose(
                full_value[:600],
                prefix_value,
                equal_nan=True,
            )

    spread = np.array([2.0, 0.0, 0.0, 3.0, 0.0, 0.0])
    times = np.array([0, 300, 600, 1_200, 1_500, 1_800]) * 1_000_000_000
    observed = causal_gap_fixed_hold_spread(spread, times)
    np.testing.assert_allclose(
        observed,
        np.array([2.0, 2.0, 2.0, 3.0, 3.0, 3.0]),
    )


def test_gap_runtime_closure_excludes_historical_catalogs() -> None:
    artifact = parse_canonical(gap_fixed_hold_job_implementation_artifact())
    assert isinstance(artifact, dict)
    paths = {str(value["path"]) for value in artifact["dependencies"]}
    assert "axiom_rift/research/gap_fixed_hold.py" in paths
    assert "axiom_rift/research/historical_family_stu0046.py" not in paths
    assert "axiom_rift/research/historical_family_stu0047.py" not in paths
    assert RUNTIME_ADAPTER.definition_builder is None
    assert RUNTIME_ADAPTER.trace_builder is None

    artifacts: dict[str, bytes] = {}
    for path in fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER):
        content = path.read_bytes()
        artifacts[sha256(content).hexdigest()] = content
    closure = gap_fixed_hold_job_implementation_artifact()
    artifacts[sha256(closure).hexdigest()] = closure
    authority = require_current_job_source_closure(
        callable_identity=RUNTIME_ADAPTER.callable_identity,
        job_artifact_hashes=sorted(artifacts),
        artifact_reader=artifacts.__getitem__,
        source_root=(Path(__file__).resolve().parents[2] / "src").resolve(),
    )
    assert authority["callable_module_path"] == (
        "axiom_rift/research/gap_fixed_hold_job.py"
    )


def test_unrelated_historical_family_is_rejected() -> None:
    with pytest.raises(TypeError, match="not Writer-bound"):
        gap_fixed_hold_configurations(STU0061_HISTORICAL_FAMILY)
