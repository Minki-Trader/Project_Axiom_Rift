"""Thin running-Job adapter for prospective STU-0061 fixed-hold replay."""

from __future__ import annotations

from pathlib import Path

import axiom_rift.core.identity as identity_module
import axiom_rift.research.analog_fixed_hold_replay as replay_module
import axiom_rift.research.analog_state_family as family_module
import axiom_rift.research.analog_state_fit_v2 as fit_module
import axiom_rift.research.analog_state_replay_v2 as replay_v2_module
import axiom_rift.research.analog_state_trace as analog_trace_module
import axiom_rift.research.analog_state_trace_rows as trace_rows_module
import axiom_rift.research.chassis as chassis_module
import axiom_rift.research.data as data_module
import axiom_rift.research.discovery as discovery_module
import axiom_rift.research.fixed_hold_family_trace as fixed_hold_trace_module
import axiom_rift.research.governance as governance_module
import axiom_rift.research.historical_family_binding as family_binding_module
import axiom_rift.research.scientific_trace as scientific_trace_module
import axiom_rift.research.selection_inference as selection_inference_module
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.analog_fixed_hold_replay import (
    ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER,
    analog_fixed_hold_replay_protocol_definition,
    compute_analog_fixed_hold_family_trace,
)
from axiom_rift.research.fixed_hold_family_job import (
    FixedHoldFamilyJobPacket,
    FixedHoldFamilyJobPlan,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    FixedHoldRepairContext,
    FixedHoldReplayRuntimeAdapter,
    FixedHoldRuntimeContext,
    build_fixed_hold_replay_job_plan,
    execute_fixed_hold_replay_job,
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_job_implementation_sha256,
    materialize_fixed_hold_replay_job_implementation,
    materialize_running_job_implementation_repair_proof,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.analog_fixed_hold_replay_job."
    "execute_analog_fixed_hold_replay_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.analog_fixed_hold_replay.v1"
ARTIFACT_NAMESPACE = "stu0061-analog-fixed-hold-replay-v3"
_THIS_FILE = Path(__file__).resolve()


def _definition(
    context: HistoricalFamilyReplayContext,
) -> FixedHoldProtocolDefinition:
    return analog_fixed_hold_replay_protocol_definition(context)


def _trace(
    repository_root: Path,
    definition: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    return compute_analog_fixed_hold_family_trace(
        repository_root,
        definition,
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
                Path(replay_module.__file__).resolve(),
                Path(family_module.__file__).resolve(),
                Path(fit_module.__file__).resolve(),
                Path(replay_v2_module.__file__).resolve(),
                Path(analog_trace_module.__file__).resolve(),
                Path(trace_rows_module.__file__).resolve(),
                Path(chassis_module.__file__).resolve(),
                Path(data_module.__file__).resolve(),
                Path(discovery_module.__file__).resolve(),
                Path(fixed_hold_trace_module.__file__).resolve(),
                Path(governance_module.__file__).resolve(),
                Path(family_binding_module.__file__).resolve(),
                Path(scientific_trace_module.__file__).resolve(),
                Path(selection_inference_module.__file__).resolve(),
            },
            key=lambda value: value.as_posix(),
        )
    ),
    component_source_paths=tuple(
        sorted(
            {
                Path(replay_module.__file__).resolve(),
                Path(family_module.__file__).resolve(),
                Path(fit_module.__file__).resolve(),
                Path(replay_v2_module.__file__).resolve(),
                Path(trace_rows_module.__file__).resolve(),
                Path(discovery_module.__file__).resolve(),
            },
            key=lambda value: value.as_posix(),
        )
    ),
    expected_family_size=4,
    context_parameter_name=ANALOG_FIXED_HOLD_REPLAY_CONTEXT_PARAMETER,
    bound_definition_builder=_definition,
    bound_trace_builder=_trace,
)


def analog_fixed_hold_replay_job_implementation_artifact() -> bytes:
    return fixed_hold_replay_job_implementation_artifact(RUNTIME_ADAPTER)


def analog_fixed_hold_replay_job_implementation_sha256() -> str:
    return fixed_hold_replay_job_implementation_sha256(RUNTIME_ADAPTER)


def materialize_analog_fixed_hold_replay_job_implementation(
    writer: FixedHoldRuntimeContext,
) -> str:
    return materialize_fixed_hold_replay_job_implementation(
        writer,
        adapter=RUNTIME_ADAPTER,
    )


def materialize_analog_fixed_hold_running_job_repair_proof(
    writer: FixedHoldRepairContext,
    *,
    verification_evidence_hashes: tuple[str, ...],
) -> str:
    return materialize_running_job_implementation_repair_proof(
        writer,
        adapter=RUNTIME_ADAPTER,
        explanation=(
            "repair the scoped-v2 to fixed-hold proof adapter without "
            "changing its registered scientific family"
        ),
        verification_evidence_hashes=verification_evidence_hashes,
    )


def build_analog_fixed_hold_replay_job_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
    replay_obligation_id: str,
) -> FixedHoldFamilyJobPlan:
    return build_fixed_hold_replay_job_plan(
        adapter=RUNTIME_ADAPTER,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        historical_family=historical_family,
        historical_family_authority_id=historical_family_authority_id,
        replay_obligation_id=replay_obligation_id,
    )


def execute_analog_fixed_hold_replay_job(
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
    "analog_fixed_hold_replay_job_implementation_artifact",
    "analog_fixed_hold_replay_job_implementation_sha256",
    "build_analog_fixed_hold_replay_job_plan",
    "execute_analog_fixed_hold_replay_job",
    "materialize_analog_fixed_hold_replay_job_implementation",
    "materialize_analog_fixed_hold_running_job_repair_proof",
]
