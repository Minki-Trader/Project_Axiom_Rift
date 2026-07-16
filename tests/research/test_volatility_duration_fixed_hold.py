from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_replay import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.research.volatility_duration_fixed_hold import (
    causal_volatility_duration_fixed_hold_spread,
    compute_volatility_duration_fixed_hold_score,
    volatility_duration_fixed_hold_configurations,
    volatility_duration_fixed_hold_controlled_chassis,
    volatility_duration_fixed_hold_protocol_definition,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (
    RUNTIME_ADAPTER,
    build_volatility_duration_fixed_hold_job_plan,
    volatility_duration_fixed_hold_job_implementation_artifact,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.implementation_closure import (
    require_current_job_source_closure,
)


FAMILY = historical_family_from_manifest(STU0051_HISTORICAL_FAMILY.manifest())
FAMILY_AUTHORITY_ID = "historical-family-authority:" + "a" * 64
OBLIGATION_ID = "historical-replay-obligation:" + "b" * 64
PRIOR_EXPOSURE = 630
ORIGINAL_FAMILY_END = 452


def _context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=OBLIGATION_ID,
        family=FAMILY,
        prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
    )


def test_definition_uses_only_writer_bound_family_and_exposure_context() -> None:
    definition = volatility_duration_fixed_hold_protocol_definition(_context())
    configurations = volatility_duration_fixed_hold_configurations(FAMILY)

    assert definition.family == FAMILY
    assert definition.historical_context_id == FAMILY_AUTHORITY_ID
    assert definition.historical_prior_global_exposure_count == PRIOR_EXPOSURE
    assert (
        definition.original_family_end_global_exposure_count
        == ORIGINAL_FAMILY_END
    )
    assert len(definition.prospective_executable_ids) == 4
    assert len(set(definition.prospective_executable_ids)) == 4
    assert tuple(
        configuration.historical_reference_executable_id
        for configuration in configurations
    ) == tuple(
        member.historical_reference_executable_id for member in FAMILY.members
    )
    assert set(definition.prospective_executable_ids).isdisjoint(
        {
            member.historical_reference_executable_id
            for member in FAMILY.members
        }
    )


def test_chassis_and_job_plans_share_one_exact_definition() -> None:
    definition = volatility_duration_fixed_hold_protocol_definition(_context())
    chassis = volatility_duration_fixed_hold_controlled_chassis(
        historical_family=FAMILY,
        historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
        original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
    )
    assert chassis.baseline_executable.identity not in (
        definition.prospective_executable_ids
    )

    plans = tuple(
        build_volatility_duration_fixed_hold_job_plan(
            mission_id="MIS-0006",
            study_id="STU-0114",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=PRIOR_EXPOSURE,
            original_family_end_global_exposure_count=ORIGINAL_FAMILY_END,
            historical_family=FAMILY,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=OBLIGATION_ID,
        )
        for executable_id in definition.prospective_executable_ids
    )
    assert all(plan.definition.identity == definition.identity for plan in plans)
    assert plans[0].produces_family_cache
    assert all(not plan.produces_family_cache for plan in plans[1:])


def test_runtime_closure_excludes_reconstruction_and_raw_evidence() -> None:
    artifact = parse_canonical(
        volatility_duration_fixed_hold_job_implementation_artifact()
    )
    assert isinstance(artifact, dict)
    paths = {str(value["path"]) for value in artifact["dependencies"]}
    forbidden = {
        "axiom_rift/research/historical_family_replay.py",
        "axiom_rift/research/historical_family_stu0051.py",
        "axiom_rift/research/volatility_duration_replay.py",
        "axiom_rift/research/volatility_duration_replay_parity.py",
    }
    assert paths.isdisjoint(forbidden)
    assert "axiom_rift/research/historical_family_binding.py" in paths
    assert "axiom_rift/research/volatility_duration_fixed_hold.py" in paths
    assert RUNTIME_ADAPTER.definition_builder is None
    assert RUNTIME_ADAPTER.trace_builder is None
    assert callable(RUNTIME_ADAPTER.bound_definition_builder)
    assert callable(RUNTIME_ADAPTER.bound_trace_builder)

    artifacts: dict[str, bytes] = {}
    for path in fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER):
        content = path.read_bytes()
        artifacts[sha256(content).hexdigest()] = content
    closure = volatility_duration_fixed_hold_job_implementation_artifact()
    artifacts[sha256(closure).hexdigest()] = closure
    authority = require_current_job_source_closure(
        callable_identity=RUNTIME_ADAPTER.callable_identity,
        job_artifact_hashes=sorted(artifacts),
        artifact_reader=artifacts.__getitem__,
        source_root=(Path(__file__).resolve().parents[2] / "src").resolve(),
    )
    assert authority["callable_module_path"] == (
        "axiom_rift/research/volatility_duration_fixed_hold_job.py"
    )


def test_source_has_no_historical_address_or_global_family_binding() -> None:
    root = Path(__file__).resolve().parents[2]
    sources = "\n".join(
        (
            root
            / "src"
            / "axiom_rift"
            / "research"
            / name
        ).read_text(encoding="ascii")
        for name in (
            "volatility_duration_fixed_hold.py",
            "volatility_duration_fixed_hold_job.py",
        )
    )
    for forbidden in (
        "EvidenceStore",
        "STU0051_HISTORICAL_EVALUATION_HASHES",
        "STU0051_HISTORICAL_FAMILY",
        "bind_prospective_historical_family",
        "raw_parity_validator",
        "historical-replay-obligation:",
    ):
        assert forbidden not in sources


def test_feature_kernel_and_completed_period_spread_are_causal() -> None:
    time = pd.date_range("2024-01-01", periods=1_500, freq="5min")
    frame = pd.DataFrame(
        {
            "time": time,
            "close": 15_000.0
            * np.exp(
                np.linspace(0.0, 0.2, len(time))
                + 0.015 * np.sin(np.arange(len(time)) / 17.0)
            ),
        }
    )
    for profile in (
        "mature_state_age_24_47",
        "persistent_state_age_72_143",
    ):
        score, volatility, run = compute_volatility_duration_fixed_hold_score(
            frame,
            profile,
        )
        assert len(score) == len(frame)
        assert len(volatility) == len(frame)
        assert len(run) == len(frame)

    spread = np.array([2.0, 0.0, 0.0, 3.0, 0.0, 0.0])
    time_ns = np.array([0, 300, 600, 1_200, 1_500, 1_800]) * 1_000_000_000
    observed = causal_volatility_duration_fixed_hold_spread(spread, time_ns)
    np.testing.assert_allclose(
        observed,
        np.array([2.0, 2.0, 2.0, 3.0, 3.0, 3.0]),
    )


def test_wrong_family_shape_and_unordered_exposure_are_rejected() -> None:
    with pytest.raises(ValueError, match="parameter surface"):
        volatility_duration_fixed_hold_configurations(
            historical_family_from_manifest(
                STU0061_HISTORICAL_FAMILY.manifest()
            )
        )

    with pytest.raises(ValueError, match="original family end exposure"):
        volatility_duration_fixed_hold_protocol_definition(
            HistoricalFamilyReplayContext(
                family_authority_id=FAMILY_AUTHORITY_ID,
                replay_obligation_id=OBLIGATION_ID,
                family=FAMILY,
                prior_global_exposure_count=ORIGINAL_FAMILY_END - 1,
                original_family_end_global_exposure_count=(
                    ORIGINAL_FAMILY_END
                ),
            )
        )
