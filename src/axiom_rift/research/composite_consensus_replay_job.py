"""Thin Writer-gated Job entry point for the STU-0017 replay adapter."""

from __future__ import annotations

from pathlib import Path

import axiom_rift.research.composite_consensus_discovery as source_module
import axiom_rift.research.composite_consensus_replay as replay_module
import axiom_rift.research.composite_consensus_replay_parity as parity_module
import axiom_rift.research.historical_family_stu0017 as historical_family_binding_module
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.composite_consensus_discovery import (
    calibrate_router,
    compute_composite_sleeve_scores,
    route_consensus_score,
)
from axiom_rift.research.composite_consensus_replay import (
    composite_consensus_replay_configurations,
    composite_consensus_replay_protocol_definition,
)
from axiom_rift.research.composite_consensus_replay_parity import (
    assert_composite_consensus_historical_raw_parity,
)
from axiom_rift.research.discovery import causal_effective_spread
from axiom_rift.research.fixed_hold_family_job import (
    FixedHoldFamilyJobPacket,
    FixedHoldFamilyJobPlan,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    build_fixed_hold_replay_job_plan,
    execute_fixed_hold_replay_job,
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_job_implementation_sha256,
    materialize_fixed_hold_replay_job_implementation,
    materialize_running_job_implementation_repair_proof,
)
from axiom_rift.research.routed_sleeve_replay_job import (
    build_routed_sleeve_runtime_adapter,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.composite_consensus_replay_job."
    "execute_composite_consensus_replay_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.composite_consensus_replay.v1"
ARTIFACT_NAMESPACE = "stu0017-composite-consensus-replay-v1"
_THIS_FILE = Path(__file__).resolve()


RUNTIME_ADAPTER = build_routed_sleeve_runtime_adapter(
    callable_identity=CALLABLE_IDENTITY,
    job_implementation_protocol=JOB_IMPLEMENTATION_PROTOCOL,
    artifact_namespace=ARTIFACT_NAMESPACE,
    adapter_source_path=Path(replay_module.__file__).resolve(),
    job_source_path=_THIS_FILE,
    historical_family_binding_path=Path(
        historical_family_binding_module.__file__
    ).resolve(),
    source_module_path=Path(source_module.__file__).resolve(),
    parity_module_path=Path(parity_module.__file__).resolve(),
    configurations=composite_consensus_replay_configurations,
    protocol_definition=composite_consensus_replay_protocol_definition,
    feature_builder=compute_composite_sleeve_scores,
    router_calibrator=calibrate_router,
    score_router=route_consensus_score,
    spread_builder=causal_effective_spread,
    raw_parity_validator=assert_composite_consensus_historical_raw_parity,
)


def composite_consensus_replay_job_implementation_artifact() -> bytes:
    return fixed_hold_replay_job_implementation_artifact(RUNTIME_ADAPTER)


def composite_consensus_replay_job_implementation_sha256() -> str:
    return fixed_hold_replay_job_implementation_sha256(RUNTIME_ADAPTER)


def materialize_composite_consensus_replay_job_implementation(
    writer: StateWriter,
) -> str:
    return materialize_fixed_hold_replay_job_implementation(
        writer,
        adapter=RUNTIME_ADAPTER,
    )


def materialize_composite_consensus_running_job_repair_proof(
    writer: StateWriter,
) -> str:
    return materialize_running_job_implementation_repair_proof(
        writer,
        adapter=RUNTIME_ADAPTER,
        explanation=(
            "repair routed replay implementation without changing the exact "
            "registered STU-0017 scientific family"
        ),
    )


def build_composite_consensus_replay_job_plan(
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


def execute_composite_consensus_replay_job(
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
    "build_composite_consensus_replay_job_plan",
    "composite_consensus_replay_job_implementation_artifact",
    "composite_consensus_replay_job_implementation_sha256",
    "execute_composite_consensus_replay_job",
    "materialize_composite_consensus_replay_job_implementation",
    "materialize_composite_consensus_running_job_repair_proof",
]
