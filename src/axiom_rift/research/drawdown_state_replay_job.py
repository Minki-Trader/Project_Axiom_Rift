"""Writer-gated prospective Job for the exact STU-0048 replay family."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Mapping

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
from axiom_rift.research.drawdown_state_replay import (
    compute_stu0048_drawdown_family_trace,
    drawdown_replay_protocol_definition,
)
from axiom_rift.research.fixed_hold_family_job import (
    FixedHoldFamilyJobPacket,
    FixedHoldFamilyJobPlan,
    build_fixed_hold_cache_provenance,
    build_fixed_hold_family_job_plan,
    fixed_hold_family_cache,
    materialize_fixed_hold_cache,
    materialize_fixed_hold_evidence,
    verify_fixed_hold_cache_producer,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.drawdown_state_replay_job."
    "execute_drawdown_state_replay_job.v1"
)
ARTIFACT_NAMESPACE = "stu0048-drawdown-replay-v2"
_THIS_FILE = Path(__file__).resolve()


def drawdown_replay_job_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def build_drawdown_replay_job_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldFamilyJobPlan:
    definition = drawdown_replay_protocol_definition(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
    )
    return build_fixed_hold_family_job_plan(
        definition=definition,
        artifact_namespace=ARTIFACT_NAMESPACE,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
    )


def execute_drawdown_state_replay_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> FixedHoldFamilyJobPacket:
    """Execute one member using one producer cache and exact typed lineage."""

    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("drawdown replay running Job specification is invalid")
    subject = spec.get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        raise ValueError("drawdown replay Job subject is invalid")
    historical_count = spec.get(
        "historical_context_prior_global_exposure_count"
    )
    if type(historical_count) is not int:
        raise ValueError("drawdown replay historical context is invalid")
    scoped_plan = build_drawdown_replay_job_plan(
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=str(subject.get("id")),
        historical_context_prior_global_exposure_count=historical_count,
    )
    if (
        spec.get("implementation_identity")
        != drawdown_replay_job_implementation_sha256()
        or spec.get("scientific_binding") != scoped_plan.scientific_binding()
        or set(spec.get("expected_outputs", ()))
        != set(scoped_plan.expected_outputs())
        or spec.get("output_classes")
        != scoped_plan.expected_output_classes()
    ):
        raise ValueError(
            "drawdown replay Job implementation or output contract drifted"
        )
    input_hashes = tuple(spec.get("input_hashes", ()))
    if len(input_hashes) != len(set(input_hashes)):
        raise ValueError("drawdown replay Job inputs are duplicated")

    if scoped_plan.produces_family_cache:
        if tuple(sorted(input_hashes)) != scoped_plan.job_input_hashes():
            raise ValueError("drawdown replay producer inputs drifted")
        neutral, _ = compute_stu0048_drawdown_family_trace(
            root,
            historical_context_prior_global_exposure_count=historical_count,
        )
        family_cache = fixed_hold_family_cache(
            scoped_plan=scoped_plan,
            neutral_trace=neutral,
            produced=True,
        )
        materialize_fixed_hold_cache(
            root,
            scoped_plan=scoped_plan,
            content=family_cache.content,
        )
    else:
        (
            family_cache,
            provenance_hash,
            producer_trace_hash,
            provenance,
        ) = verify_fixed_hold_cache_producer(
            writer,
            scoped_plan=scoped_plan,
            repository_root=root,
            input_hashes=input_hashes,
            expected_callable_identity=CALLABLE_IDENTITY,
        )
        expected_inputs = scoped_plan.job_input_hashes(
            cache_sha256=family_cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=producer_trace_hash,
        )
        if tuple(sorted(input_hashes)) != expected_inputs:
            raise ValueError("drawdown replay consumer inputs drifted")
        if provenance.get("cache_sha256") != family_cache.sha256:
            raise ValueError("drawdown replay cache provenance drifted")

    neutral = family_cache.trace(scoped_plan.definition)
    outputs, adjudication_state = materialize_fixed_hold_evidence(
        writer=writer,
        scoped_plan=scoped_plan,
        execution=execution,
        neutral_trace=neutral,
    )
    if scoped_plan.produces_family_cache:
        provenance = build_fixed_hold_cache_provenance(
            scoped_plan=scoped_plan,
            execution=execution,
            cache_sha256=family_cache.sha256,
            producer_trace_sha256=outputs[
                scoped_plan.output_names["trace"]
            ],
        )
        outputs[scoped_plan.cache_output_name] = family_cache.sha256
        outputs[scoped_plan.cache_provenance_output_name] = (
            writer.evidence.finalize(canonical_bytes(provenance)).sha256
        )
    if set(outputs) != set(scoped_plan.expected_outputs()):
        raise ValueError("drawdown replay Job materialized undeclared outputs")
    return FixedHoldFamilyJobPacket(
        adjudication_state=adjudication_state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "ARTIFACT_NAMESPACE",
    "CALLABLE_IDENTITY",
    "build_drawdown_replay_job_plan",
    "drawdown_replay_job_implementation_sha256",
    "execute_drawdown_state_replay_job",
]
