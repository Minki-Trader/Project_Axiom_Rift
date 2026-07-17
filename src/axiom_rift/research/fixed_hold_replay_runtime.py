"""Writer-gated runtime shared by exact fixed-hold replay adapters.

Protocol modules own scientific behavior and Executable identity.  This module
owns the repeated operational envelope: implementation closure, frozen family
context recovery, one-producer cache, and evidence materialization.  A durable
record never supplies a callback or import path; the adapter is constructed in
repository code and is selected by the callable entry point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import axiom_rift.research.validation_v2 as validation_v2_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_semantic_equivalence import (
    IMPLEMENTATION_REPAIR_V2_SCHEMA,
    fixed_hold_authority_correction_measurement,
    semantic_equivalence_result_manifest,
)
from axiom_rift.operations.validation import (
    validator_execution_dependency_paths,
)
from axiom_rift.operations.running_job import (
    RunningJobExecution,
)
from axiom_rift.operations.running_job_context import (
    RunningJobEvidence,
    RunningJobExecutionContext,
    RunningJobFixedHoldReplayContext,
    running_job_execution_context_dependency_paths,
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
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
)
from axiom_rift.research.replay_exposure import FrozenFamilyExposureContext
from axiom_rift.storage.index import LocalIndexView


DefinitionBuilder = Callable[[int], FixedHoldProtocolDefinition]
TraceBuilder = Callable[
    [Path, int],
    tuple[dict[str, object], dict[str, dict[str, int]]],
]
BoundDefinitionBuilder = Callable[
    [HistoricalFamilyReplayContext],
    FixedHoldProtocolDefinition,
]
BoundTraceBuilder = Callable[
    [Path, FixedHoldProtocolDefinition],
    tuple[dict[str, object], dict[str, dict[str, int]]],
]
_THIS_FILE = Path(__file__).resolve()


class FixedHoldRuntimeContext(Protocol):
    """Exact capabilities available to a fixed-hold running Job."""

    evidence: RunningJobEvidence
    prior_global_multiplicity_floor: int

    def project_bound_fixed_hold_family_exposure(
        self,
        *,
        study_id: str,
        batch_id: str,
        subject_executable_id: str,
        expected_family_size: int,
        parameter_name: str | None,
    ) -> FrozenFamilyExposureContext: ...

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


class FixedHoldRepairContext(Protocol):
    """Management-only context for an interrupted implementation Repair."""

    evidence: RunningJobEvidence

    def open_stable_index(
        self,
    ) -> AbstractContextManager[
        tuple[dict[str, Any], LocalIndexView]
    ]: ...

    def plan_fixed_hold_authority_correction_repair(
        self,
        *,
        new_implementation_identity: str,
    ) -> dict[str, Any]: ...

    def resolve_fixed_hold_authority_correction_verification(
        self,
        *,
        new_implementation_identity: str,
        evidence_hashes: tuple[str, ...],
    ) -> tuple[str, ...]: ...


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
    definition_builder: DefinitionBuilder | None = None
    trace_builder: TraceBuilder | None = None
    bound_definition_builder: BoundDefinitionBuilder | None = None
    bound_trace_builder: BoundTraceBuilder | None = None

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
        legacy_builders = callable(self.definition_builder) and callable(
            self.trace_builder
        )
        bound_builders = callable(self.bound_definition_builder) and callable(
            self.bound_trace_builder
        )
        if legacy_builders == bound_builders:
            raise TypeError(
                "fixed-hold adapter requires exactly one complete builder pair"
            )
        object.__setattr__(self, "adapter_source_path", source)
        object.__setattr__(self, "dependency_paths", dependencies)
        object.__setattr__(self, "component_source_paths", components)

    def definition(
        self,
        prior_global_exposure_count: int,
    ) -> FixedHoldProtocolDefinition:
        if self.definition_builder is None:
            raise RuntimeError(
                "prospective replay definition requires Writer-bound family data"
            )
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
        if self.trace_builder is None:
            raise RuntimeError(
                "prospective replay trace requires Writer-bound family data"
            )
        return self.trace_builder(repository_root, prior_global_exposure_count)

    def definition_from_context(
        self,
        context: HistoricalFamilyReplayContext,
    ) -> FixedHoldProtocolDefinition:
        """Build a prospective definition from authenticated data only."""

        if not isinstance(context, HistoricalFamilyReplayContext):
            raise TypeError("Writer-bound replay context is not typed")
        if self.bound_definition_builder is None:
            raise RuntimeError(
                "historical compatibility adapter is not prospectively executable"
            )
        value = self.bound_definition_builder(context)
        if not isinstance(value, FixedHoldProtocolDefinition):
            raise TypeError("runtime adapter returned an untyped definition")
        if value.family != context.family:
            raise ValueError("runtime definition replaced its Writer-bound family")
        if value.family.family_size != self.expected_family_size:
            raise ValueError("runtime definition family size drifted")
        if (
            value.historical_prior_global_exposure_count
            != context.prior_global_exposure_count
            or value.original_family_end_global_exposure_count
            != context.original_family_end_global_exposure_count
        ):
            raise ValueError(
                "runtime definition replaced its Writer-derived exposure context"
            )
        return value

    def compute_trace_from_definition(
        self,
        repository_root: Path,
        definition: FixedHoldProtocolDefinition,
    ) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
        """Compute one trace from the exact already-checked definition."""

        if self.bound_trace_builder is None:
            raise RuntimeError(
                "historical compatibility adapter is not prospectively executable"
            )
        if (
            not isinstance(definition, FixedHoldProtocolDefinition)
            or not isinstance(definition.family, HistoricalFamilySpec)
            or definition.family.family_size != self.expected_family_size
        ):
            raise TypeError("Writer-bound fixed-hold definition is invalid")
        return self.bound_trace_builder(repository_root, definition)


def fixed_hold_replay_runtime_dependency_paths(
    adapter: FixedHoldReplayRuntimeAdapter,
) -> tuple[Path, ...]:
    """Return the centrally inferred exact source closure for this runtime."""

    return validator_execution_dependency_paths(
        _THIS_FILE,
        (
            *running_job_execution_context_dependency_paths(),
            *adapter.dependency_paths,
        ),
    )


def fixed_hold_replay_job_implementation_artifact(
    adapter: FixedHoldReplayRuntimeAdapter,
) -> bytes:
    """Return a portable source closure for one code-selected adapter."""

    return _fixed_hold_replay_job_implementation_artifact(
        adapter,
        fixed_hold_replay_runtime_dependency_paths(adapter),
    )


def _fixed_hold_replay_job_implementation_artifact(
    adapter: FixedHoldReplayRuntimeAdapter,
    dependency_paths: tuple[Path, ...],
) -> bytes:
    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in dependency_paths:
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


def _implementation_manifest(
    adapter: FixedHoldReplayRuntimeAdapter,
    dependency_paths: tuple[Path, ...] | None = None,
) -> bytes:
    dependencies = (
        fixed_hold_replay_runtime_dependency_paths(adapter)
        if dependency_paths is None
        else dependency_paths
    )
    closure_hash = sha256(
        _fixed_hold_replay_job_implementation_artifact(adapter, dependencies)
    ).hexdigest()
    dependency_hashes = {
        sha256(path.read_bytes()).hexdigest()
        for path in dependencies
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
    writer: FixedHoldRuntimeContext,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
) -> str:
    """Store every source byte in the exact runtime closure."""

    dependency_paths = fixed_hold_replay_runtime_dependency_paths(adapter)
    closure = _fixed_hold_replay_job_implementation_artifact(
        adapter,
        dependency_paths,
    )
    closure_artifact = writer.evidence.finalize(closure)
    if closure_artifact.sha256 != sha256(closure).hexdigest():
        raise RuntimeError("fixed-hold runtime closure identity drifted")
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
    manifest = _implementation_manifest(
        adapter,
        dependency_paths=dependency_paths,
    )
    implementation = writer.evidence.finalize(manifest)
    expected = sha256(manifest).hexdigest()
    if implementation.sha256 != expected:
        raise RuntimeError("fixed-hold runtime implementation identity drifted")
    return implementation.sha256


def materialize_running_job_implementation_repair_proof(
    writer: FixedHoldRepairContext,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    explanation: str,
    verification_evidence_hashes: tuple[str, ...],
) -> str:
    """Bind a repaired closure and independent verification to one Job."""

    reason = _ascii("running Job Repair explanation", explanation)
    with writer.open_stable_index() as (control, index):
        science = control.get("scientific")
        repair = None if not isinstance(science, Mapping) else science.get(
            "active_repair"
        )
        job = (
            None if not isinstance(science, Mapping) else science.get("active_job")
        )
        if (
            not isinstance(repair, Mapping)
            or not isinstance(job, Mapping)
            or job.get("status") != "interrupted_repair"
            or repair.get("job_id") != job.get("id")
        ):
            raise ValueError("implementation Repair requires one interrupted Job")
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
    requested_verification = tuple(
        sorted(set(verification_evidence_hashes))
    )
    if len(requested_verification) != len(verification_evidence_hashes):
        raise ValueError(
            "implementation Repair verification evidence must be unique"
        )
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
    verification_results = (
        writer.resolve_fixed_hold_authority_correction_verification(
            new_implementation_identity=new_identity,
            evidence_hashes=requested_verification,
        )
    )
    manifest = parse_canonical(writer.evidence.read_verified(new_identity))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "job_implementation_evidence.v1"
        or not isinstance(manifest.get("artifact_hashes"), list)
    ):
        raise ValueError("repaired implementation manifest is invalid")
    plan = writer.plan_fixed_hold_authority_correction_repair(
        new_implementation_identity=new_identity,
    )
    plan_artifact = writer.evidence.finalize(canonical_bytes(plan))
    measurement_hashes: list[str] = []
    for pair in plan["changed_source_pair_bindings"]:
        measurement = writer.evidence.finalize(
            canonical_bytes(
                fixed_hold_authority_correction_measurement(
                    validation_plan_hash=plan_artifact.sha256,
                    relative_path=pair["relative_path"],
                    old_artifact_hash=pair["old_artifact_hash"],
                    new_artifact_hash=pair["new_artifact_hash"],
                )
            )
        )
        measurement_hashes.append(measurement.sha256)
    measurements = tuple(sorted(measurement_hashes))
    result = semantic_equivalence_result_manifest(
        plan=plan,
        validation_plan_hash=plan_artifact.sha256,
        measurement_artifact_hashes=measurements,
        surface_verdicts={
            surface_id: "passed" for surface_id in plan["claims"]
        },
    )
    result_artifact = writer.evidence.finalize(canonical_bytes(result))
    new_evidence = sorted(
        {
            new_identity,
            *manifest["artifact_hashes"],
            plan_artifact.sha256,
            result_artifact.sha256,
            *measurements,
        }
    )
    inner_proof = writer.evidence.finalize(
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
                "schema": IMPLEMENTATION_REPAIR_V2_SCHEMA,
                "semantic_equivalence_measurement_artifact_hashes": list(
                    measurements
                ),
                "semantic_equivalence_result_manifest_hash": (
                    result_artifact.sha256
                ),
                "semantic_equivalence_validation_plan_hash": (
                    plan_artifact.sha256
                ),
                "semantic_equivalence_validator_id": plan["validator_id"],
            }
        )
    )
    attempt_new_evidence = tuple(
        sorted({inner_proof.sha256, *new_evidence})
    )
    check_plan = writer.evidence.finalize(
        canonical_bytes(
            {
                "callable_identity": adapter.callable_identity,
                "changed_dimension": "implementation",
                "job_id": job["id"],
                "new_basis_hash": new_identity,
                "semantic_equivalence_validator_id": plan["validator_id"],
                "schema": "fixed_hold_repair_check_plan.v1",
            }
        )
    )
    verification_receipt = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": repair["cause_hash"],
                "changed_dimension": "implementation",
                "check_plan_hash": check_plan.sha256,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_basis_hash": new_identity,
                "outcome": "repaired",
                "repair_id": repair["id"],
                "result_artifact_hashes": list(verification_results),
                "resume_action": repair["resume_action"],
                "schema": "repair_verification_receipt.v1",
                "scientific_semantics_changed": False,
                "verdict": "passed",
                "verification_method": (
                    "fixed-hold affected-surface verification"
                ),
            }
        )
    )
    verification = (verification_receipt.sha256,)
    if set(reproduction).intersection(attempt_new_evidence) or set(
        reproduction
    ).intersection(
        {check_plan.sha256, *verification_results, *verification}
    ) or set(attempt_new_evidence).intersection(
        {check_plan.sha256, *verification_results, *verification}
    ):
        raise ValueError(
            "implementation Repair evidence surfaces must be distinct"
        )
    attempt = writer.evidence.finalize(
        canonical_bytes(
            {
                "cause_hash": repair["cause_hash"],
                "changed_dimension": "implementation",
                "explanation": reason,
                "failure_observation": None,
                "implementation_proof_hash": inner_proof.sha256,
                "job_hash": job["hash"],
                "job_id": job["id"],
                "new_basis_hash": new_identity,
                "new_evidence_hashes": list(attempt_new_evidence),
                "outcome": "repaired",
                "previous_basis_hash": repair["latest_basis_hash"],
                "prior_attempt_record_id": repair[
                    "latest_attempt_record_id"
                ],
                "repair_id": repair["id"],
                "reproduction_evidence_hashes": sorted(reproduction),
                "resume_action": repair["resume_action"],
                "schema": "running_job_repair_attempt.v1",
                "scientific_semantics_changed": False,
                "verification_evidence_hashes": list(verification),
            }
        )
    )
    return attempt.sha256


def build_fixed_hold_replay_job_plan(
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int | None = None,
    historical_family: HistoricalFamilySpec | None = None,
    historical_family_authority_id: str | None = None,
    replay_obligation_id: str | None = None,
) -> FixedHoldFamilyJobPlan:
    if historical_family is None:
        if (
            original_family_end_global_exposure_count is not None
            or historical_family_authority_id is not None
            or replay_obligation_id is not None
        ):
            raise ValueError(
                "legacy plan cannot accept partial historical family authority"
            )
        definition = adapter.definition(
            historical_context_prior_global_exposure_count
        )
    else:
        if (
            original_family_end_global_exposure_count is None
            or type(original_family_end_global_exposure_count) is not int
            or historical_family_authority_id is None
            or replay_obligation_id is None
        ):
            raise ValueError(
                "prospective plan requires exact historical family authority"
            )
        definition = adapter.definition_from_context(
            HistoricalFamilyReplayContext(
                family_authority_id=historical_family_authority_id,
                replay_obligation_id=replay_obligation_id,
                family=historical_family,
                prior_global_exposure_count=(
                    historical_context_prior_global_exposure_count
                ),
                original_family_end_global_exposure_count=(
                    original_family_end_global_exposure_count
                ),
            )
        )
    return build_fixed_hold_family_job_plan(
        definition=definition,
        artifact_namespace=adapter.artifact_namespace,
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
    )


def registered_fixed_hold_replay_context(
    writer: FixedHoldRuntimeContext,
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    binding: Mapping[str, object],
    subject_executable_id: str,
) -> RunningJobFixedHoldReplayContext:
    """Recover a fully preregistered family and its exact execution prefix."""

    study_id = binding.get("study_id")
    batch_id = binding.get("batch_id")
    if type(study_id) is not str or type(batch_id) is not str:
        raise ValueError("fixed-hold replay Study or Batch binding is invalid")
    prior_floor = writer.prior_global_multiplicity_floor
    if type(prior_floor) is not int or prior_floor < 0:
        raise ValueError("fixed-hold prior multiplicity floor is invalid")
    context = writer.project_bound_fixed_hold_replay_context(
        study_id=study_id,
        batch_id=batch_id,
        subject_executable_id=subject_executable_id,
        expected_family_size=adapter.expected_family_size,
        parameter_name=adapter.context_parameter_name,
    )
    exposure = context.exposure
    if exposure.prior_global_exposure_count < prior_floor:
        raise ValueError("fixed-hold family predates its Foundation floor")
    registered_ids = exposure.family_executable_ids
    if subject_executable_id not in context.batch_family_executable_ids:
        raise ValueError("fixed-hold replay subject is outside its family")
    definition = adapter.definition_from_context(
        HistoricalFamilyReplayContext(
            family_authority_id=context.family_authority_id,
            replay_obligation_id=context.replay_obligation_id,
            family=context.family,
            prior_global_exposure_count=(
                exposure.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                context.original_family_end_global_exposure_count
            ),
        )
    )
    expected_bindings = tuple(
        (
            prospective_id,
            member.historical_reference_executable_id,
        )
        for prospective_id, member in zip(
            definition.prospective_executable_ids,
            definition.family.members,
            strict=True,
        )
    )
    target_ordinal = next(
        member.ordinal
        for member in definition.family.members
        if member.historical_reference_executable_id
        == definition.family.target_historical_executable_id
    )
    expected_target = definition.prospective_executable_ids[
        target_ordinal - 1
    ]
    if (
        registered_ids != definition.prospective_executable_ids
        or context.registered_member_bindings != expected_bindings
        or context.target_prospective_executable_id != expected_target
        or context.batch_family_executable_ids
        != tuple(sorted(definition.prospective_executable_ids))
        or subject_executable_id
        not in definition.prospective_executable_ids
    ):
        raise ValueError(
            "fixed-hold replay family differs from its frozen context"
        )
    subject_ordinal = (
        definition.prospective_executable_ids.index(subject_executable_id)
        + 1
    )
    if (
        context.execution_prefix_executable_ids
        != definition.prospective_executable_ids[:subject_ordinal]
        or context.completed_member_executable_ids
        != definition.prospective_executable_ids[: subject_ordinal - 1]
    ):
        raise ValueError(
            "fixed-hold replay family differs from its frozen context"
        )
    return context


def execute_fixed_hold_replay_job(
    *,
    adapter: FixedHoldReplayRuntimeAdapter,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> FixedHoldFamilyJobPacket:
    """Execute one exact family member under a Writer-issued capability."""

    root = Path(repository_root).resolve()
    running_job_context = RunningJobExecutionContext(root)
    binding = running_job_context.verify_running_job_execution(
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
    replay_context = registered_fixed_hold_replay_context(
        running_job_context,
        adapter=adapter,
        binding=binding,
        subject_executable_id=subject_id,
    )
    historical_count = replay_context.exposure.prior_global_exposure_count
    original_family_end = (
        replay_context.original_family_end_global_exposure_count
    )
    scoped_plan = build_fixed_hold_replay_job_plan(
        adapter=adapter,
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=subject_id,
        historical_context_prior_global_exposure_count=historical_count,
        original_family_end_global_exposure_count=original_family_end,
        historical_family=replay_context.family,
        historical_family_authority_id=(
            replay_context.family_authority_id
        ),
        replay_obligation_id=replay_context.replay_obligation_id,
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
        neutral, _ = adapter.compute_trace_from_definition(
            root,
            scoped_plan.definition,
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
            running_job_context,
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
        writer=running_job_context,
        scoped_plan=scoped_plan,
        execution=execution,
        neutral_trace=neutral,
        shared_trace_sha256=family_cache.sha256,
    )
    if scoped_plan.produces_family_cache:
        if outputs[scoped_plan.output_names["trace"]] != family_cache.sha256:
            raise ValueError(
                "fixed-hold producer trace must share the exact cache identity"
            )
        provenance = build_fixed_hold_cache_provenance(
            scoped_plan=scoped_plan,
            execution=execution,
            cache_sha256=family_cache.sha256,
            producer_trace_sha256=outputs[scoped_plan.output_names["trace"]],
        )
        outputs[scoped_plan.cache_output_name] = family_cache.sha256
        outputs[scoped_plan.cache_provenance_output_name] = (
            running_job_context.evidence.finalize(
                canonical_bytes(provenance)
            ).sha256
        )
    if set(outputs) != set(scoped_plan.expected_outputs()):
        raise ValueError("fixed-hold Job materialized undeclared outputs")
    return FixedHoldFamilyJobPacket(
        adjudication_state=adjudication_state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "DefinitionBuilder",
    "FixedHoldRepairContext",
    "FixedHoldReplayRuntimeAdapter",
    "FixedHoldRuntimeContext",
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
