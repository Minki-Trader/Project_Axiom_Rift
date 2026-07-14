"""Writer-gated prospective Job for the exact STU-0048 replay family."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Mapping

import axiom_rift.research.drawdown_state_replay as drawdown_replay_module
import axiom_rift.research.discovery as discovery_module
import axiom_rift.research.fixed_hold_family_job as fixed_hold_job_module
import axiom_rift.research.fixed_hold_family_trace as fixed_hold_trace_module
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
from axiom_rift.research.trials import TrialAccountant
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
)
from axiom_rift.storage.index import LocalIndex


CALLABLE_IDENTITY = (
    "axiom_rift.research.drawdown_state_replay_job."
    "execute_drawdown_state_replay_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.drawdown_state_replay.v2"
ARTIFACT_NAMESPACE = "stu0048-drawdown-replay-v2"
_THIS_FILE = Path(__file__).resolve()


def _drawdown_replay_job_dependency_paths() -> tuple[Path, ...]:
    return tuple(
        sorted(
            {
                _THIS_FILE,
                Path(drawdown_replay_module.__file__).resolve(),
                Path(fixed_hold_job_module.__file__).resolve(),
                *(Path(value).resolve() for value in SCIENTIFIC_VALIDATION_V2_DEPENDENCIES),
            },
            key=lambda value: value.as_posix(),
        )
    )


def _drawdown_replay_component_source_paths() -> tuple[Path, ...]:
    return tuple(
        sorted(
            {
                Path(discovery_module.__file__).resolve(),
                Path(drawdown_replay_module.__file__).resolve(),
                Path(fixed_hold_trace_module.__file__).resolve(),
            },
            key=lambda value: value.as_posix(),
        )
    )


def drawdown_replay_job_implementation_artifact() -> bytes:
    """Return a portable cryptographic closure over every runtime dependency."""

    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in _drawdown_replay_job_dependency_paths():
        if not path.is_file():
            raise RuntimeError("drawdown replay Job dependency is unavailable")
        try:
            relative = path.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "drawdown replay Job dependency is outside the source root"
            ) from exc
        dependencies.append(
            {
                "path": relative,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    return canonical_bytes(
        {
            "callable_identity": CALLABLE_IDENTITY,
            "dependencies": dependencies,
            "schema": "job_implementation_source_closure.v1",
        }
    )


def _drawdown_replay_job_implementation_manifest() -> bytes:
    closure_hash = sha256(
        drawdown_replay_job_implementation_artifact()
    ).hexdigest()
    return canonical_bytes(
        {
            "artifact_hashes": sorted(
                {
                    closure_hash,
                    *(
                        sha256(path.read_bytes()).hexdigest()
                        for path in _drawdown_replay_component_source_paths()
                    ),
                }
            ),
            "callable_identity": CALLABLE_IDENTITY,
            "protocol": JOB_IMPLEMENTATION_PROTOCOL,
            "schema": "job_implementation_evidence.v1",
        }
    )


def drawdown_replay_job_implementation_sha256() -> str:
    return sha256(
        _drawdown_replay_job_implementation_manifest()
    ).hexdigest()


def materialize_drawdown_replay_job_implementation(
    writer: StateWriter,
) -> str:
    """Store the exact closure and Writer-readable implementation manifest."""

    closure = drawdown_replay_job_implementation_artifact()
    closure_artifact = writer.evidence.finalize(closure)
    if closure_artifact.sha256 != sha256(closure).hexdigest():
        raise RuntimeError("drawdown replay Job closure identity drifted")
    component_hashes = tuple(
        sorted(
            writer.evidence.finalize(path.read_bytes()).sha256
            for path in _drawdown_replay_component_source_paths()
        )
    )
    expected_component_hashes = tuple(
        sorted(
            sha256(path.read_bytes()).hexdigest()
            for path in _drawdown_replay_component_source_paths()
        )
    )
    if component_hashes != expected_component_hashes:
        raise RuntimeError("drawdown replay Component source identity drifted")
    manifest = _drawdown_replay_job_implementation_manifest()
    implementation = writer.evidence.finalize(manifest)
    expected = drawdown_replay_job_implementation_sha256()
    if implementation.sha256 != expected:
        raise RuntimeError("drawdown replay Job implementation identity drifted")
    return implementation.sha256


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


def _registered_historical_context(
    writer: StateWriter,
    *,
    binding: Mapping[str, object],
    subject_executable_id: str,
) -> int:
    """Recover the frozen context from the exact registered Study family."""

    study_id = binding.get("study_id")
    if type(study_id) is not str:
        raise ValueError("drawdown replay Job Study binding is invalid")
    with LocalIndex(writer.index_path) as index:
        all_trials = tuple(index.records_by_kind("trial"))
        family_trials = tuple(
            record
            for record in all_trials
            if record.payload.get("study_id") == study_id
        )
    if (
        len(family_trials) != 4
        or subject_executable_id
        not in {record.record_id for record in family_trials}
    ):
        raise ValueError("drawdown replay registered family is incomplete")
    contexts: set[int] = set()
    for record in family_trials:
        executable = record.payload.get("executable")
        parameters = (
            None
            if not isinstance(executable, Mapping)
            else executable.get("parameters")
        )
        context = (
            None
            if not isinstance(parameters, Mapping)
            else parameters.get(
                "historical_context_prior_global_exposure_count"
            )
        )
        if type(context) is not int:
            raise ValueError(
                "drawdown replay trial historical context is invalid"
            )
        contexts.add(context)
    if len(contexts) != 1:
        raise ValueError("drawdown replay family historical context drifted")
    historical_count = contexts.pop()
    family_ids = {record.record_id for record in family_trials}
    prior_floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    observed_count = prior_floor + sum(
        record.record_id not in family_ids for record in all_trials
    )
    definition = drawdown_replay_protocol_definition(
        historical_context_prior_global_exposure_count=historical_count
    )
    if (
        observed_count != historical_count
        or family_ids != set(definition.prospective_executable_ids)
    ):
        raise ValueError(
            "drawdown replay family differs from its frozen historical context"
        )
    return historical_count


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
    subject_id = str(subject.get("id"))
    historical_count = _registered_historical_context(
        writer,
        binding=binding,
        subject_executable_id=subject_id,
    )
    scoped_plan = build_drawdown_replay_job_plan(
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=subject_id,
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
    "JOB_IMPLEMENTATION_PROTOCOL",
    "build_drawdown_replay_job_plan",
    "drawdown_replay_job_implementation_artifact",
    "drawdown_replay_job_implementation_sha256",
    "execute_drawdown_state_replay_job",
    "materialize_drawdown_replay_job_implementation",
]
