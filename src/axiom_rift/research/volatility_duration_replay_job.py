"""Thin Writer-gated Job entry point for the STU-0051 replay adapter."""

from __future__ import annotations

from pathlib import Path

import axiom_rift.core.identity as identity_module
import axiom_rift.research.chassis as chassis_module
import axiom_rift.research.data as data_module
import axiom_rift.research.discovery as discovery_module
import axiom_rift.research.fixed_hold_family_trace as fixed_hold_trace_module
import axiom_rift.research.fixed_hold_trace_engine as trace_engine_module
import axiom_rift.research.governance as governance_module
import axiom_rift.research.historical_family_replay as historical_family_module
import axiom_rift.research.scientific_trace as scientific_trace_module
import axiom_rift.research.selection_inference as selection_inference_module
import axiom_rift.research.volatility_duration_replay as replay_module
import axiom_rift.storage.evidence as evidence_module
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.fixed_hold_family_job import (
    FixedHoldFamilyJobPacket,
    FixedHoldFamilyJobPlan,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    FixedHoldReplayRuntimeAdapter,
    build_fixed_hold_replay_job_plan,
    execute_fixed_hold_replay_job,
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_job_implementation_sha256,
    materialize_fixed_hold_replay_job_implementation,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.volatility_duration_replay import (
    compute_stu0051_volatility_duration_family_trace,
    volatility_duration_replay_protocol_definition,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.volatility_duration_replay_job."
    "execute_volatility_duration_replay_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.volatility_duration_replay.v1"
ARTIFACT_NAMESPACE = "stu0051-volatility-duration-replay-v1"
_THIS_FILE = Path(__file__).resolve()


def _definition(prior_global_exposure_count: int) -> FixedHoldProtocolDefinition:
    return volatility_duration_replay_protocol_definition(
        historical_context_prior_global_exposure_count=(
            prior_global_exposure_count
        )
    )


def _trace(
    repository_root: Path,
    prior_global_exposure_count: int,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    return compute_stu0051_volatility_duration_family_trace(
        repository_root,
        historical_context_prior_global_exposure_count=(
            prior_global_exposure_count
        ),
    )


RUNTIME_ADAPTER = FixedHoldReplayRuntimeAdapter(
    callable_identity=CALLABLE_IDENTITY,
    job_implementation_protocol=JOB_IMPLEMENTATION_PROTOCOL,
    artifact_namespace=ARTIFACT_NAMESPACE,
    adapter_source_path=Path(replay_module.__file__).resolve(),
    dependency_paths=tuple(
        sorted(
            {
                _THIS_FILE,
                Path(identity_module.__file__).resolve(),
                Path(chassis_module.__file__).resolve(),
                Path(data_module.__file__).resolve(),
                Path(discovery_module.__file__).resolve(),
                Path(evidence_module.__file__).resolve(),
                Path(fixed_hold_trace_module.__file__).resolve(),
                Path(governance_module.__file__).resolve(),
                Path(historical_family_module.__file__).resolve(),
                Path(replay_module.__file__).resolve(),
                Path(scientific_trace_module.__file__).resolve(),
                Path(selection_inference_module.__file__).resolve(),
                Path(trace_engine_module.__file__).resolve(),
            },
            key=lambda value: value.as_posix(),
        )
    ),
    component_source_paths=tuple(
        sorted(
            {
                Path(discovery_module.__file__).resolve(),
                Path(fixed_hold_trace_module.__file__).resolve(),
                Path(replay_module.__file__).resolve(),
            },
            key=lambda value: value.as_posix(),
        )
    ),
    expected_family_size=4,
    context_parameter_name=(
        "historical_context_prior_global_exposure_count"
    ),
    definition_builder=_definition,
    trace_builder=_trace,
)


def volatility_duration_replay_job_implementation_artifact() -> bytes:
    return fixed_hold_replay_job_implementation_artifact(RUNTIME_ADAPTER)


def volatility_duration_replay_job_implementation_sha256() -> str:
    return fixed_hold_replay_job_implementation_sha256(RUNTIME_ADAPTER)


def materialize_volatility_duration_replay_job_implementation(
    writer: StateWriter,
) -> str:
    return materialize_fixed_hold_replay_job_implementation(
        writer,
        adapter=RUNTIME_ADAPTER,
    )


def build_volatility_duration_replay_job_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldFamilyJobPlan:
    return build_fixed_hold_replay_job_plan(
        adapter=RUNTIME_ADAPTER,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
    )


def execute_volatility_duration_replay_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> FixedHoldFamilyJobPacket:
    return execute_fixed_hold_replay_job(
        adapter=RUNTIME_ADAPTER,
        repository_root=repository_root,
        execution=execution,
    )


__all__ = [
    "ARTIFACT_NAMESPACE",
    "CALLABLE_IDENTITY",
    "JOB_IMPLEMENTATION_PROTOCOL",
    "RUNTIME_ADAPTER",
    "build_volatility_duration_replay_job_plan",
    "execute_volatility_duration_replay_job",
    "materialize_volatility_duration_replay_job_implementation",
    "volatility_duration_replay_job_implementation_artifact",
    "volatility_duration_replay_job_implementation_sha256",
]
