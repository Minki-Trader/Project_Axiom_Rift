from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.operations.running_job_context import (
    RunningJobFixedHoldReplayContext,
    running_job_operational_identity_boundary_paths,
    running_job_scientific_projection_dependency_paths,
)
from axiom_rift.operations.job_implementation_authority import (
    hardcoded_control_ids,
)
from axiom_rift.research.cost_aware_execution_pair import (
    COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_pair_runtime import (
    CALLABLE_IDENTITY,
    cost_aware_execution_pair_job_implementation_sha256,
    cost_aware_execution_pair_runtime_dependency_paths,
    materialize_cost_aware_execution_pair_job_implementation,
    registered_cost_aware_execution_pair_context,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.implementation_closure import (
    require_current_job_source_closure,
)
from axiom_rift.research.replay_exposure import FrozenFamilyExposureContext


@dataclass(frozen=True)
class _Artifact:
    sha256: str


class _Evidence:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def finalize(self, content: bytes) -> _Artifact:
        digest = sha256(content).hexdigest()
        self.values[digest] = content
        return _Artifact(digest)

    def read_verified(self, digest: str) -> bytes:
        return self.values[digest]


class _ImplementationWriter:
    def __init__(self) -> None:
        self.evidence = _Evidence()


def _replay_context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id="historical-family-authority:" + "a" * 64,
        replay_obligation_id="historical-replay-obligation:" + "b" * 64,
        family=STU0070_HISTORICAL_FAMILY,
        prior_global_exposure_count=700,
        original_family_end_global_exposure_count=(
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


def _running_context(subject_id: str) -> RunningJobFixedHoldReplayContext:
    replay = _replay_context()
    definition = cost_aware_execution_pair_protocol_definition(replay)
    ordinal = definition.prospective_executable_ids.index(subject_id)
    return RunningJobFixedHoldReplayContext(
        family_authority_id=replay.family_authority_id,
        replay_obligation_id=replay.replay_obligation_id,
        family=replay.family,
        original_family_end_global_exposure_count=(
            replay.original_family_end_global_exposure_count
        ),
        exposure=FrozenFamilyExposureContext(
            prior_global_exposure_count=replay.prior_global_exposure_count,
            family_executable_ids=definition.prospective_executable_ids,
            first_family_authority_sequence=100,
        ),
        batch_family_executable_ids=tuple(
            sorted(definition.prospective_executable_ids)
        ),
        registered_member_bindings=tuple(
            (
                item.prospective_executable_id,
                item.historical_executable_id,
            )
            for item in definition.member_bindings
        ),
        execution_prefix_executable_ids=(
            definition.prospective_executable_ids[: ordinal + 1]
        ),
        completed_member_executable_ids=(
            definition.prospective_executable_ids[:ordinal]
        ),
        target_prospective_executable_id=(
            definition.prospective_target_executable_id
        ),
    )


class _RuntimeWriter:
    prior_global_multiplicity_floor = 500

    def __init__(self, context: RunningJobFixedHoldReplayContext) -> None:
        self.context = context

    def project_bound_fixed_hold_replay_context(self, **kwargs):
        assert kwargs["expected_family_size"] == 2
        assert kwargs["parameter_name"] == (
            COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER
        )
        assert kwargs["subject_executable_id"] in (
            self.context.exposure.family_executable_ids
        )
        return self.context


def test_runtime_implementation_closure_is_current_and_complete() -> None:
    dependencies = set(cost_aware_execution_pair_runtime_dependency_paths())
    assert set(running_job_scientific_projection_dependency_paths()).issubset(
        dependencies
    )
    assert set(running_job_operational_identity_boundary_paths()).isdisjoint(
        dependencies
    )
    assert any(path.name == "validation_identity.py" for path in dependencies)
    writer = _ImplementationWriter()
    identity = materialize_cost_aware_execution_pair_job_implementation(writer)
    assert identity == cost_aware_execution_pair_job_implementation_sha256()
    manifest = parse_canonical(writer.evidence.read_verified(identity))
    assert isinstance(manifest, dict)
    authority = require_current_job_source_closure(
        callable_identity=CALLABLE_IDENTITY,
        job_artifact_hashes=tuple(manifest["artifact_hashes"]),
        artifact_reader=writer.evidence.read_verified,
        source_root=Path("src").resolve(),
    )
    assert authority["callable_module_path"].endswith(
        "cost_aware_execution_pair_runtime.py"
    )


def test_runtime_closure_has_no_hardcoded_mission_or_study_identity() -> None:
    for path in cost_aware_execution_pair_runtime_dependency_paths():
        assert hardcoded_control_ids(path.read_bytes()) == (), path


@pytest.mark.parametrize("ordinal", [0, 1])
def test_registered_runtime_context_preserves_exact_historical_prefix(
    ordinal: int,
) -> None:
    replay = _replay_context()
    definition = cost_aware_execution_pair_protocol_definition(replay)
    subject = definition.prospective_executable_ids[ordinal]
    projected = _running_context(subject)
    context, opened = registered_cost_aware_execution_pair_context(
        _RuntimeWriter(projected),
        binding={"study_id": "STU-SYNTHETIC", "batch_id": "batch:" + "c" * 64},
        subject_executable_id=subject,
    )
    assert context == projected
    assert opened == replay


def test_registered_runtime_context_rejects_reversed_prefix() -> None:
    replay = _replay_context()
    definition = cost_aware_execution_pair_protocol_definition(replay)
    subject = definition.prospective_target_executable_id
    projected = _running_context(subject)
    drifted = replace(
        projected,
        execution_prefix_executable_ids=tuple(
            reversed(projected.execution_prefix_executable_ids)
        ),
    )
    with pytest.raises(ValueError, match="execution prefix"):
        registered_cost_aware_execution_pair_context(
            _RuntimeWriter(drifted),
            binding={
                "study_id": "STU-SYNTHETIC",
                "batch_id": "batch:" + "c" * 64,
            },
            subject_executable_id=subject,
        )
