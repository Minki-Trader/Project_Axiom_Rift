"""Writer-gated runtime shared by exact fixed-hold replay adapters.

Protocol modules own scientific behavior and Executable identity.  This module
owns the repeated operational envelope: implementation closure, frozen family
context recovery, one-producer cache, and evidence materialization.  A durable
record never supplies a callback or import path; the adapter is constructed in
repository code and is selected by the callable entry point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import axiom_rift.operations.writer as writer_module
import axiom_rift.research.fixed_hold_family_job as fixed_hold_job_module
import axiom_rift.research.replay_exposure as replay_exposure_module
import axiom_rift.research.trials as trials_module
import axiom_rift.storage.index as index_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.writer import RunningJobExecution, StateWriter
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
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.replay_exposure import (
    derive_frozen_family_exposure_context,
)
from axiom_rift.research.trials import TrialAccountant
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
)
from axiom_rift.storage.index import LocalIndex


DefinitionBuilder = Callable[[int], FixedHoldProtocolDefinition]
TraceBuilder = Callable[
    [Path, int],
    tuple[dict[str, object], dict[str, dict[str, int]]],
]
_THIS_FILE = Path(__file__).resolve()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _path_tuple(name: str, values: object) -> tuple[Path, ...]:
    if type(values) is not tuple or not values:
        raise ValueError(f"{name} must be a non-empty tuple")
    paths = tuple(Path(value).resolve() for value in values)
    if len(paths) != len(set(paths)) or any(not path.is_file() for path in paths):
        raise ValueError(f"{name} must contain unique existing files")
    return tuple(sorted(paths, key=lambda value: value.as_posix()))


@dataclass(frozen=True, slots=True)
class FixedHoldReplayRuntimeAdapter:
    """Code-owned scientific adapter for the shared operational runtime."""

    callable_identity: str
    job_implementation_protocol: str
    artifact_namespace: str
    adapter_source_path: Path
    dependency_paths: tuple[Path, ...]
    component_source_paths: tuple[Path, ...]
    expected_family_size: int
    context_parameter_name: str
    definition_builder: DefinitionBuilder
    trace_builder: TraceBuilder

    def __post_init__(self) -> None:
        for name in (
            "callable_identity",
            "job_implementation_protocol",
            "artifact_namespace",
            "context_parameter_name",
        ):
            _ascii(name, getattr(self, name))
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
            for character in self.artifact_namespace
        ):
            raise ValueError("artifact_namespace is not path-safe")
        if type(self.expected_family_size) is not int or self.expected_family_size < 2:
            raise ValueError("expected_family_size must be at least two")
        source = Path(self.adapter_source_path).resolve()
        if not source.is_file():
            raise ValueError("adapter source is unavailable")
        dependencies = _path_tuple("dependency_paths", self.dependency_paths)
        components = _path_tuple(
            "component_source_paths",
            self.component_source_paths,
        )
        if source not in dependencies or source not in components:
            raise ValueError(
                "adapter source must bind both runtime and Component closure"
            )
        if not set(components).issubset(dependencies):
            raise ValueError(
                "Component sources must be contained in the runtime closure"
            )
        if not callable(self.definition_builder) or not callable(self.trace_builder):
            raise TypeError("fixed-hold runtime builders must be callable")
        object.__setattr__(self, "adapter_source_path", source)
        object.__setattr__(self, "dependency_paths", dependencies)
        object.__setattr__(self, "component_source_paths", components)

    def definition(
        self,
        prior_global_exposure_count: int,
    ) -> FixedHoldProtocolDefinition:
        value = self.definition_builder(prior_global_exposure_count)
        if not isinstance(value, FixedHoldProtocolDefinition):
            raise TypeError("runtime adapter returned an untyped definition")
        if value.family.family_size != self.expected_family_size:
            raise ValueError("runtime definition family size drifted")
        return value

    def compute_trace(
        self,
        repository_root: Path,
        prior_global_exposure_count: int,
    ) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
        return self.trace_builder(repository_root, prior_global_exposure_count)


def fixed_hold_replay_runtime_dependency_paths(
    adapter: FixedHoldReplayRuntimeAdapter,
) -> tuple[Path, ...]:
    """Return the exact source closure opened by this runtime."""

    return tuple(
        sorted(
            {
                _THIS_FILE,
                Path(writer_module.__file__).resolve(),
                Path(fixed_hold_job_module.__file__).resolve(),
                Path(replay_exposure_module.__file__).resolve(),
                Path(trials_module.__file__).resolve(),
                Path(index_module.__file__).resolve(),
                *adapter.dependency_paths,
                *(
                    Path(value).resolve()
                    for value in SCIENTIFIC_VALIDATION_V2_DEPENDENCIES
                ),
            },
            key=lambda value: value.as_posix(),
        )
    )


def fixed_hold_replay_job_implementation_artifact(
    adapter: FixedHoldReplayRuntimeAdapter,
) -> bytes:
    """Return a portable source closure for one code-selected adapter."""

    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in fixed_hold_replay_runtime_dependency_paths(adapter):
        if not path.is_file():
            raise RuntimeError("fixed-hold runtime dependency is unavailable")
        try:
            relative = path.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "fixed-hold runtime dependency is outside the source root"
            ) from exc
        dependencies.append(
            {"path": relative, "sha256": sha256(path.read_bytes()).hexdigest()}
        )
    return canonical_bytes(
        {
            "callable_identity": adapter.callable_identity,
            "dependencies": dependencies,
            "schema": "job_implementation_source_closure.v1",
        }
    )


def _implementation_manifest(adapter: FixedHoldReplayRuntimeAdapter) -> bytes:
    closure_hash = sha256(
        fixed_hold_replay_job_implementation_artifact(adapter)
    ).hexdigest()
    dependency_hashes = {
        sha256(path.read_bytes()).hexdigest()
        for path in fixed_hold_replay_runtime_dependency_paths(adapter)
    }
    return canonical_bytes(
        {
            "artifact_hashes": sorted({closure_hash, *dependency_hashes}),
            "callable_identity": adapter.callable_identity,
            "protocol": adapter.job_implementation_protocol,
            "schema": "job_implementation_evidence.v1",
        }
    )


def fixed_hold_replay_job_implementation_sha256(
    adapter: FixedHoldReplayRuntimeAdapter,
) -> str:
    return sha256(_implementation_manifest(adapter)).hexdigest()


def materialize_fixed_hold_replay_job_implementation(
    writer: StateWriter,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
) -> str:
    """Store every source byte in the exact runtime closure."""

    closure = fixed_hold_replay_job_implementation_artifact(adapter)
    closure_artifact = writer.evidence.finalize(closure)
    if closure_artifact.sha256 != sha256(closure).hexdigest():
        raise RuntimeError("fixed-hold runtime closure identity drifted")
    dependency_paths = fixed_hold_replay_runtime_dependency_paths(adapter)
    dependency_hashes = tuple(
        sorted(
            writer.evidence.finalize(path.read_bytes()).sha256
            for path in dependency_paths
        )
    )
    expected_dependency_hashes = tuple(
        sorted(
            sha256(path.read_bytes()).hexdigest()
            for path in dependency_paths
        )
    )
    if dependency_hashes != expected_dependency_hashes:
        raise RuntimeError("fixed-hold runtime dependency identity drifted")
    manifest = _implementation_manifest(adapter)
    implementation = writer.evidence.finalize(manifest)
    expected = fixed_hold_replay_job_implementation_sha256(adapter)
    if implementation.sha256 != expected:
        raise RuntimeError("fixed-hold runtime implementation identity drifted")
    return implementation.sha256


def materialize_running_job_implementation_repair_proof(
    writer: StateWriter,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    explanation: str,
) -> str:
    """Bind a repaired source closure to one interrupted running Job."""

    reason = _ascii("running Job Repair explanation", explanation)
    control = writer.read_control()
    science = None if control is None else control.get("scientific")
    repair = None if not isinstance(science, Mapping) else science.get(
        "active_repair"
    )
    job = None if not isinstance(science, Mapping) else science.get("active_job")
    if (
        not isinstance(repair, Mapping)
        or not isinstance(job, Mapping)
        or job.get("status") != "interrupted_repair"
        or repair.get("job_id") != job.get("id")
    ):
        raise ValueError("implementation Repair requires one interrupted Job")
    with LocalIndex(writer.index_path) as index:
        declaration = index.get("job-declared", str(job["id"]))
        opened = index.get("repair-open", str(repair["id"]))
        prior_head = index.event_head(f"job-repair:{job['id']}")
        prior_close = (
            None
            if prior_head is None
            else index.get(prior_head.record_kind, prior_head.record_id)
        )
    spec = None if declaration is None else declaration.payload.get("spec")
    reproduction = (
        None
        if opened is None
        else opened.payload.get("minimum_reproduction_evidence")
    )
    if not isinstance(spec, Mapping) or not isinstance(reproduction, list):
        raise ValueError("implementation Repair provenance is unavailable")
    previous_identity = spec.get("implementation_identity")
    if prior_close is not None:
        previous_identity = prior_close.payload.get(
            "effective_implementation_identity"
        )
    if not isinstance(previous_identity, str):
        raise ValueError("previous implementation identity is unavailable")
    new_identity = materialize_fixed_hold_replay_job_implementation(
        writer,
        adapter=adapter,
    )
    if new_identity == previous_identity:
        raise ValueError("implementation Repair did not change source closure")
    manifest = parse_canonical(writer.evidence.read_verified(new_identity))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "job_implementation_evidence.v1"
        or not isinstance(manifest.get("artifact_hashes"), list)
    ):
        raise ValueError("repaired implementation manifest is invalid")
    new_evidence = sorted({new_identity, *manifest["artifact_hashes"]})
    proof = writer.evidence.finalize(
        canonical_bytes(
            {
                "changed_dimension": "implementation",
                "explanation": reason,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_evidence_hashes": new_evidence,
                "new_implementation_identity": new_identity,
                "previous_implementation_identity": previous_identity,
                "repair_id": repair["id"],
                "reproduction_evidence_hashes": sorted(reproduction),
                "schema": "running_job_implementation_repair.v1",
            }
        )
    )
    return proof.sha256


def build_fixed_hold_replay_job_plan(
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
) -> FixedHoldFamilyJobPlan:
    return build_fixed_hold_family_job_plan(
        definition=adapter.definition(
            historical_context_prior_global_exposure_count
        ),
        artifact_namespace=adapter.artifact_namespace,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
    )


def registered_fixed_hold_replay_context(
    writer: StateWriter,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    binding: Mapping[str, object],
    subject_executable_id: str,
) -> int:
    """Recover the immutable context at the family's first trial sequence."""

    study_id = binding.get("study_id")
    if type(study_id) is not str:
        raise ValueError("fixed-hold replay Study binding is invalid")
    with LocalIndex(writer.index_path) as index:
        all_trials = tuple(index.records_by_kind("trial"))
    prior_floor = TrialAccountant.from_foundation(
        writer.foundation_root
    ).prior_global_multiplicity_floor
    context = derive_frozen_family_exposure_context(
        trials=all_trials,
        prior_global_exposure_floor=prior_floor,
        study_id=study_id,
        expected_family_size=adapter.expected_family_size,
        parameter_name=adapter.context_parameter_name,
        allow_unregistered=False,
    )
    family_ids = set(context.family_executable_ids)
    if subject_executable_id not in family_ids:
        raise ValueError("fixed-hold replay subject is outside its family")
    definition = adapter.definition(context.prior_global_exposure_count)
    if family_ids != set(definition.prospective_executable_ids):
        raise ValueError(
            "fixed-hold replay family differs from its frozen context"
        )
    return context.prior_global_exposure_count


def execute_fixed_hold_replay_job(
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> FixedHoldFamilyJobPacket:
    """Execute one exact family member under a Writer-issued capability."""

    root = Path(repository_root).resolve()
    writer = StateWriter(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=adapter.callable_identity,
    )
    spec = binding.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("fixed-hold running Job specification is invalid")
    subject = spec.get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        raise ValueError("fixed-hold Job subject is invalid")
    subject_id = str(subject.get("id"))
    historical_count = registered_fixed_hold_replay_context(
        writer,
        adapter=adapter,
        binding=binding,
        subject_executable_id=subject_id,
    )
    scoped_plan = build_fixed_hold_replay_job_plan(
        adapter=adapter,
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=subject_id,
        historical_context_prior_global_exposure_count=historical_count,
    )
    if (
        binding.get("effective_implementation_identity")
        != fixed_hold_replay_job_implementation_sha256(adapter)
        or spec.get("scientific_binding") != scoped_plan.scientific_binding()
        or set(spec.get("expected_outputs", ()))
        != set(scoped_plan.expected_outputs())
        or spec.get("output_classes")
        != scoped_plan.expected_output_classes()
    ):
        raise ValueError(
            "fixed-hold Job implementation or output contract drifted"
        )
    input_hashes = tuple(spec.get("input_hashes", ()))
    if len(input_hashes) != len(set(input_hashes)):
        raise ValueError("fixed-hold Job inputs are duplicated")

    if scoped_plan.produces_family_cache:
        if tuple(sorted(input_hashes)) != scoped_plan.job_input_hashes():
            raise ValueError("fixed-hold producer inputs drifted")
        neutral, _ = adapter.compute_trace(root, historical_count)
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
            expected_callable_identity=adapter.callable_identity,
        )
        expected_inputs = scoped_plan.job_input_hashes(
            cache_sha256=family_cache.sha256,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=producer_trace_hash,
        )
        if tuple(sorted(input_hashes)) != expected_inputs:
            raise ValueError("fixed-hold consumer inputs drifted")
        if provenance.get("cache_sha256") != family_cache.sha256:
            raise ValueError("fixed-hold cache provenance drifted")

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
            producer_trace_sha256=outputs[scoped_plan.output_names["trace"]],
        )
        outputs[scoped_plan.cache_output_name] = family_cache.sha256
        outputs[scoped_plan.cache_provenance_output_name] = (
            writer.evidence.finalize(canonical_bytes(provenance)).sha256
        )
    if set(outputs) != set(scoped_plan.expected_outputs()):
        raise ValueError("fixed-hold Job materialized undeclared outputs")
    return FixedHoldFamilyJobPacket(
        adjudication_state=adjudication_state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "DefinitionBuilder",
    "FixedHoldReplayRuntimeAdapter",
    "TraceBuilder",
    "build_fixed_hold_replay_job_plan",
    "execute_fixed_hold_replay_job",
    "fixed_hold_replay_job_implementation_artifact",
    "fixed_hold_replay_job_implementation_sha256",
    "fixed_hold_replay_runtime_dependency_paths",
    "materialize_fixed_hold_replay_job_implementation",
    "materialize_running_job_implementation_repair_proof",
    "registered_fixed_hold_replay_context",
]
