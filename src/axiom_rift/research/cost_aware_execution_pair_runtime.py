"""Writer-gated runtime for a corrected historical paired replay."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import (
    RunningJobEvidence,
    RunningJobExecutionContext,
    RunningJobFixedHoldReplayContext,
    running_job_execution_context_dependency_paths,
)
from axiom_rift.operations.validation import (
    validator_execution_dependency_paths,
)
from axiom_rift.research.cost_aware_execution_pair import (
    COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
    cost_aware_execution_pair_historical_context,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_pair_engine import (
    produce_cost_aware_execution_pair_trace,
)
from axiom_rift.research.cost_aware_execution_pair_job import (
    CostAwareExecutionPairJobPacket,
    CostAwareExecutionPairJobPlan,
    build_cost_aware_execution_pair_cache_provenance,
    build_cost_aware_execution_pair_job_plan,
    cost_aware_execution_pair_cache,
    materialize_cost_aware_execution_pair_cache,
    materialize_cost_aware_execution_pair_evidence,
    verify_cost_aware_execution_pair_cache_producer,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.cost_aware_execution_pair_runtime."
    "execute_cost_aware_execution_pair_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = (
    "python.source.cost_aware_execution_pair.v1"
)
_THIS_FILE = Path(__file__).resolve()


class CostAwareExecutionRuntimeContext(Protocol):
    evidence: RunningJobEvidence
    prior_global_multiplicity_floor: int

    def project_bound_fixed_hold_replay_context(
        self,
        *,
        study_id: str,
        batch_id: str,
        subject_executable_id: str,
        expected_family_size: int,
        parameter_name: str | None,
    ) -> RunningJobFixedHoldReplayContext: ...

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


class CostAwareExecutionImplementationContext(Protocol):
    evidence: RunningJobEvidence


def cost_aware_execution_pair_runtime_dependency_paths() -> tuple[Path, ...]:
    """Return the exact recursively imported source closure of this Job."""

    return validator_execution_dependency_paths(
        _THIS_FILE,
        running_job_execution_context_dependency_paths(),
    )


def _source_closure_artifact(
    dependency_paths: tuple[Path, ...],
) -> bytes:
    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in dependency_paths:
        if not path.is_file():
            raise RuntimeError("cost-aware runtime dependency is unavailable")
        try:
            relative = path.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "cost-aware runtime dependency is outside the source root"
            ) from exc
        dependencies.append(
            {
                "path": relative,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    dependencies.sort(key=lambda item: item["path"])
    if len({item["path"] for item in dependencies}) != len(dependencies):
        raise RuntimeError("cost-aware runtime dependency is duplicated")
    return canonical_bytes(
        {
            "callable_identity": CALLABLE_IDENTITY,
            "dependencies": dependencies,
            "schema": "job_implementation_source_closure.v1",
        }
    )


def cost_aware_execution_pair_job_implementation_artifact() -> bytes:
    return _source_closure_artifact(
        cost_aware_execution_pair_runtime_dependency_paths()
    )


def _implementation_manifest(
    dependency_paths: tuple[Path, ...] | None = None,
) -> bytes:
    paths = (
        cost_aware_execution_pair_runtime_dependency_paths()
        if dependency_paths is None
        else dependency_paths
    )
    closure = _source_closure_artifact(paths)
    return canonical_bytes(
        {
            "artifact_hashes": sorted(
                {
                    sha256(closure).hexdigest(),
                    *(sha256(path.read_bytes()).hexdigest() for path in paths),
                }
            ),
            "callable_identity": CALLABLE_IDENTITY,
            "protocol": JOB_IMPLEMENTATION_PROTOCOL,
            "schema": "job_implementation_evidence.v1",
        }
    )


def cost_aware_execution_pair_job_implementation_sha256() -> str:
    return sha256(_implementation_manifest()).hexdigest()


def materialize_cost_aware_execution_pair_job_implementation(
    writer: CostAwareExecutionImplementationContext,
) -> str:
    """Store every source byte, the closure, and its implementation manifest."""

    paths = cost_aware_execution_pair_runtime_dependency_paths()
    dependencies = tuple(
        sorted(writer.evidence.finalize(path.read_bytes()).sha256 for path in paths)
    )
    expected = tuple(
        sorted(sha256(path.read_bytes()).hexdigest() for path in paths)
    )
    if dependencies != expected:
        raise RuntimeError("cost-aware runtime dependency identity drifted")
    closure = _source_closure_artifact(paths)
    closure_artifact = writer.evidence.finalize(closure)
    if closure_artifact.sha256 != sha256(closure).hexdigest():
        raise RuntimeError("cost-aware runtime closure identity drifted")
    manifest = _implementation_manifest(paths)
    implementation = writer.evidence.finalize(manifest)
    if implementation.sha256 != sha256(manifest).hexdigest():
        raise RuntimeError("cost-aware runtime implementation identity drifted")
    return implementation.sha256


def registered_cost_aware_execution_pair_context(
    writer: CostAwareExecutionRuntimeContext,
    *,
    binding: Mapping[str, object],
    subject_executable_id: str,
) -> tuple[
    RunningJobFixedHoldReplayContext,
    HistoricalFamilyReplayContext,
]:
    """Recover the exact Writer-bound family and its sequential Job prefix."""

    study_id = binding.get("study_id")
    batch_id = binding.get("batch_id")
    if type(study_id) is not str or type(batch_id) is not str:
        raise ValueError("cost-aware replay Study or Batch binding is invalid")
    prior_floor = writer.prior_global_multiplicity_floor
    if type(prior_floor) is not int or prior_floor < 0:
        raise ValueError("cost-aware prior multiplicity floor is invalid")
    context = writer.project_bound_fixed_hold_replay_context(
        study_id=study_id,
        batch_id=batch_id,
        subject_executable_id=subject_executable_id,
        expected_family_size=2,
        parameter_name=COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
    )
    exposure = context.exposure
    if exposure.prior_global_exposure_count < prior_floor:
        raise ValueError("cost-aware pair predates its Foundation floor")
    replay_context = HistoricalFamilyReplayContext(
        family_authority_id=context.family_authority_id,
        replay_obligation_id=context.replay_obligation_id,
        family=context.family,
        prior_global_exposure_count=exposure.prior_global_exposure_count,
        original_family_end_global_exposure_count=(
            context.original_family_end_global_exposure_count
        ),
    )
    definition = cost_aware_execution_pair_protocol_definition(replay_context)
    expected_bindings = tuple(
        (
            item.prospective_executable_id,
            item.historical_executable_id,
        )
        for item in definition.member_bindings
    )
    target = definition.prospective_target_executable_id
    if (
        exposure.family_executable_ids
        != definition.prospective_executable_ids
        or context.registered_member_bindings != expected_bindings
        or context.target_prospective_executable_id != target
        or context.batch_family_executable_ids
        != tuple(sorted(definition.prospective_executable_ids))
        or subject_executable_id not in definition.prospective_executable_ids
    ):
        raise ValueError("cost-aware replay differs from its frozen context")
    ordinal = definition.prospective_executable_ids.index(subject_executable_id)
    if (
        context.execution_prefix_executable_ids
        != definition.prospective_executable_ids[: ordinal + 1]
        or context.completed_member_executable_ids
        != definition.prospective_executable_ids[:ordinal]
    ):
        raise ValueError("cost-aware replay execution prefix drifted")
    return context, replay_context


def execute_cost_aware_execution_pair_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> CostAwareExecutionPairJobPacket:
    """Execute one exact pair member under a Writer-issued capability."""

    root = Path(repository_root).resolve()
    running = RunningJobExecutionContext(root)
    binding = running.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("cost-aware running Job specification is invalid")
    subject = spec.get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        raise ValueError("cost-aware Job subject is invalid")
    subject_id = str(subject.get("id"))
    context, replay_context = registered_cost_aware_execution_pair_context(
        running,
        binding=binding,
        subject_executable_id=subject_id,
    )
    scoped_plan = build_cost_aware_execution_pair_job_plan(
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=subject_id,
        historical_context_prior_global_exposure_count=(
            replay_context.prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            replay_context.original_family_end_global_exposure_count
        ),
        historical_family=replay_context.family,
        historical_family_authority_id=replay_context.family_authority_id,
        replay_obligation_id=replay_context.replay_obligation_id,
    )
    if (
        binding.get("effective_implementation_identity")
        != cost_aware_execution_pair_job_implementation_sha256()
        or spec.get("scientific_binding") != scoped_plan.scientific_binding()
        or set(spec.get("expected_outputs", ()))
        != set(scoped_plan.expected_outputs())
        or spec.get("output_classes")
        != scoped_plan.expected_output_classes()
    ):
        raise ValueError(
            "cost-aware Job implementation or output contract drifted"
        )
    input_hashes = tuple(spec.get("input_hashes", ()))
    if len(input_hashes) != len(set(input_hashes)):
        raise ValueError("cost-aware Job inputs are duplicated")

    producer_manifest: Mapping[str, Any] | None = None
    if scoped_plan.produces_family_cache:
        if tuple(sorted(input_hashes)) != scoped_plan.job_input_hashes():
            raise ValueError("cost-aware producer inputs drifted")
        production = produce_cost_aware_execution_pair_trace(
            root,
            definition=scoped_plan.definition,
            historical_context=cost_aware_execution_pair_historical_context(
                replay_context
            ),
        )
        producer_manifest = production.producer_manifest
        cache = cost_aware_execution_pair_cache(
            scoped_plan=scoped_plan,
            neutral_trace=production.trace,
            produced=True,
        )
        cache_artifact = running.evidence.finalize(cache.content)
        if cache_artifact.sha256 != cache.sha256:
            raise ValueError("cost-aware cache evidence identity drifted")
        materialize_cost_aware_execution_pair_cache(
            root,
            scoped_plan=scoped_plan,
            content=cache.content,
        )
    else:
        cache, provenance_hash, producer_trace_hash, provenance = (
            verify_cost_aware_execution_pair_cache_producer(
                running,
                scoped_plan=scoped_plan,
                repository_root=root,
                input_hashes=input_hashes,
                expected_callable_identity=CALLABLE_IDENTITY,
            )
        )
        expected_inputs = scoped_plan.job_input_hashes(
            cache_sha256=cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=producer_trace_hash,
        )
        if tuple(sorted(input_hashes)) != expected_inputs:
            raise ValueError("cost-aware consumer inputs drifted")
        if provenance.get("cache_sha256") != cache.sha256:
            raise ValueError("cost-aware cache provenance drifted")

    neutral = cache.trace(scoped_plan.definition)
    outputs, adjudication_state = (
        materialize_cost_aware_execution_pair_evidence(
            writer=running,
            scoped_plan=scoped_plan,
            execution=execution,
            neutral_trace=neutral,
        )
    )
    if scoped_plan.produces_family_cache:
        if producer_manifest is None:
            raise RuntimeError("cost-aware producer manifest is absent")
        provenance = build_cost_aware_execution_pair_cache_provenance(
            scoped_plan=scoped_plan,
            execution=execution,
            cache_sha256=cache.sha256,
            producer_trace_sha256=outputs[scoped_plan.output_names["trace"]],
            producer_manifest=producer_manifest,
        )
        outputs[scoped_plan.cache_output_name] = cache.sha256
        outputs[scoped_plan.cache_provenance_output_name] = (
            running.evidence.finalize(canonical_bytes(provenance)).sha256
        )
    if set(outputs) != set(scoped_plan.expected_outputs()):
        raise ValueError("cost-aware Job materialized undeclared outputs")
    return CostAwareExecutionPairJobPacket(
        adjudication_state=adjudication_state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "CALLABLE_IDENTITY",
    "JOB_IMPLEMENTATION_PROTOCOL",
    "cost_aware_execution_pair_job_implementation_artifact",
    "cost_aware_execution_pair_job_implementation_sha256",
    "cost_aware_execution_pair_runtime_dependency_paths",
    "execute_cost_aware_execution_pair_job",
    "materialize_cost_aware_execution_pair_job_implementation",
    "registered_cost_aware_execution_pair_context",
]
