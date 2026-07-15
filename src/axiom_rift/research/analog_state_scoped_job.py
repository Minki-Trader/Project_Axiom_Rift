"""Authority-gated prospective Job for the decision-scoped analog family.

The historical v1 replay remains immutable evidence.  This module computes a
new scoped-v2 family trace, binds it to scoped-v2 Executable identities, and
reuses the established analog statistic formulas only through an explicit,
non-authoritative identifier projection.  Projected v1 rows are never emitted
as evidence.

One first-member Job produces the neutral family cache.  Every later member
must bind both the cache hash and the durable producer trace hash.  A missing
local cache can therefore be reconstructed only from the exact completed
producer trace after read-only running-Job authority verifies its provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import (
    RunningJobExecutionContext,
    running_job_execution_context_dependency_paths,
)
from axiom_rift.operations.validation import (
    validator_execution_dependency_paths,
)
from axiom_rift.research import analog_state_replay_v2 as replay_v2
from axiom_rift.research.adjudication import adjudicate_plan_measurement
from axiom_rift.research.analog_state_family import (
    AnalogFamilyConfiguration,
    analog_family_executable,
    analog_family_implementation_sha256,
)
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_fit_v2 import (
    analog_fit_v2_implementation_sha256,
)
from axiom_rift.research.analog_state_replay import (
    analog_replay_multiplicity_registrations,
    build_analog_replay_multiplicity_results,
)
from axiom_rift.research.analog_state_replay_v2 import (
    ANALOG_SCOPED_QUERY_SCOPE_ID,
    analog_family_executable_scoped_v2,
    analog_family_trace_v2_implementation_identities,
    analog_replay_v2_bundle_sha256,
    compute_analog_family_trace_scoped_v2,
    expected_analog_family_inventory_scoped_v2,
    validate_analog_family_trace_scoped_v2,
)
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CLAIMS,
    ANALOG_REPLAY_CRITERIA,
    ANALOG_REPLAY_EVIDENCE_MODES,
    analog_calculation_parameters,
    analog_family_execution_contracts,
    analog_original_family_provenance,
    analog_trace_implementation_sha256,
    bind_analog_family_trace,
    build_analog_trace_calculation,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    discovery_implementation_sha256,
    loader_implementation_sha256,
)
from axiom_rift.research.evidence_proofs import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    build_proof_references,
    parse_proof_requirements,
)
from axiom_rift.research.reproducible_cache import publish_reproducible_cache
from axiom_rift.research.scientific_trace import (
    ANALOG_SCOPED_TRACE_PROTOCOL_ID,
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    build_validation_plan_v2,
)


CALLABLE_IDENTITY = (
    "axiom_rift.research.analog_state_scoped_job."
    "execute_analog_state_scoped_job.v1"
)
JOB_IMPLEMENTATION_PROTOCOL = "python.source.analog_state_scoped_v2.v1"
ANALOG_SCOPED_CACHE_MANIFEST_SCHEMA = (
    "analog_family_trace_scoped_v2_cache_manifest.v1"
)
EVIDENCE_DEPTH = "discovery"
_THIS_FILE = Path(__file__).resolve()


def _legacy_original_family_provenance() -> dict[str, object]:
    """Compatibility provenance for the frozen pre-authority scoped adapter."""

    return analog_original_family_provenance(P1_STU0061_ANALOG_FAMILY)

_SUBJECT_TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "job_hash",
    "job_id",
    "material_identity",
    "mission_id",
    "ordered_family",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
_CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}
_NEUTRAL_COMMON_FIELDS = {
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "material_identity",
    "ordered_family",
    "split_artifact_sha256",
    "trade_observations",
    "windows",
}
_FAMILY_BINDING_FIELDS = {
    "cache_manifest",
    "clock_contract",
    "cost_contract",
    "family_trace_sha256",
    "implementation_identities",
    "neutral_protocol_id",
    "original_family_provenance",
    "query_scope_id",
    "schema",
}
_CACHE_MANIFEST_FIELDS = {
    "cache_output_name",
    "cache_schema",
    "cache_sha256",
    "claim_authority",
    "dataset_sha256",
    "family_id",
    "implementation_identities",
    "manifest_output_name",
    "material_identity",
    "mission_id",
    "neutral_protocol_id",
    "producer_executable_id",
    "producer_execution",
    "protocol_id",
    "query_scope_id",
    "schema",
    "split_artifact_sha256",
    "study_id",
}
_PRODUCER_EXECUTION_FIELDS = {
    "identity",
    "job_hash",
    "job_id",
    "job_permit_id",
    "start_record_id",
}


class AnalogScopedJobContext(Protocol):
    """Minimum evidence and read-only Job authority used by scoped-v2."""

    evidence: Any

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


def analog_scoped_job_dependency_paths() -> tuple[Path, ...]:
    """Bind the centrally inferred execution closure of the scoped-v2 Job."""

    return validator_execution_dependency_paths(
        _THIS_FILE,
        (
            *running_job_execution_context_dependency_paths(),
        ),
    )


def analog_scoped_job_source_closure_artifact() -> bytes:
    """Return the portable source closure for the prospective Job adapter."""

    return _analog_scoped_job_source_closure_artifact(
        analog_scoped_job_dependency_paths()
    )


def _analog_scoped_job_source_closure_artifact(
    dependency_paths: tuple[Path, ...],
) -> bytes:
    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in dependency_paths:
        try:
            relative = path.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "analog scoped Job dependency is outside the source root"
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


def analog_scoped_job_implementation_artifact() -> bytes:
    """Return the canonical implementation-evidence manifest."""

    dependencies = analog_scoped_job_dependency_paths()
    return _analog_scoped_job_implementation_artifact(dependencies)


def _analog_scoped_job_implementation_artifact(
    dependencies: tuple[Path, ...],
) -> bytes:
    closure = _analog_scoped_job_source_closure_artifact(dependencies)
    closure_hash = sha256(closure).hexdigest()
    return canonical_bytes(
        {
            "artifact_hashes": sorted(
                {
                    closure_hash,
                    *(sha256(path.read_bytes()).hexdigest() for path in dependencies),
                }
            ),
            "callable_identity": CALLABLE_IDENTITY,
            "protocol": JOB_IMPLEMENTATION_PROTOCOL,
            "schema": "job_implementation_evidence.v1",
        }
    )


def analog_scoped_job_implementation_sha256() -> str:
    dependencies = analog_scoped_job_dependency_paths()
    return sha256(
        _analog_scoped_job_implementation_artifact(dependencies)
    ).hexdigest()


def materialize_analog_scoped_job_implementation(
    writer: AnalogScopedJobContext,
) -> str:
    """Store every source byte and the exact scoped-v2 implementation."""

    dependency_paths = analog_scoped_job_dependency_paths()
    for path in dependency_paths:
        artifact = writer.evidence.finalize(path.read_bytes())
        if artifact.sha256 != sha256(path.read_bytes()).hexdigest():
            raise RuntimeError("analog scoped dependency identity drifted")
    closure = _analog_scoped_job_source_closure_artifact(dependency_paths)
    closure_artifact = writer.evidence.finalize(closure)
    if closure_artifact.sha256 != sha256(closure).hexdigest():
        raise RuntimeError("analog scoped source closure identity drifted")
    manifest = _analog_scoped_job_implementation_artifact(dependency_paths)
    implementation = writer.evidence.finalize(manifest)
    expected = sha256(manifest).hexdigest()
    if implementation.sha256 != expected:
        raise RuntimeError("analog scoped implementation identity drifted")
    return implementation.sha256


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _scoped_configuration_map() -> dict[str, AnalogFamilyConfiguration]:
    return {
        analog_family_executable_scoped_v2(configuration).identity: configuration
        for configuration in P1_STU0061_ANALOG_FAMILY.configurations()
    }


def analog_scoped_family_trace_cache_output_name() -> str:
    implementation = analog_replay_v2_bundle_sha256()[:16]
    return (
        "local/cache/analog-state/"
        f"stu0061-family-trace-scoped-v2-{implementation}.json"
    )


def analog_scoped_output_names(
    executable_id: str,
    *,
    study_id: str,
) -> dict[str, str]:
    executable = _ascii("scoped executable_id", executable_id)
    study = _ascii("scoped study_id", study_id)
    prefix = (
        f"scientific/{study}/"
        f"{executable.removeprefix('executable:')[:16]}-scoped-v2"
    )
    return {
        "calculation": f"{prefix}/calculation-proof.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
        "trace": f"{prefix}/evaluation-trace.json",
    }


def _atomic_proof_requirements(
    output_names: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    """Declare the shared atomic envelope without claiming the v1 protocol.

    The proof kind and artifact schemas are protocol-neutral envelopes.  The
    opened trace and calculation select the scoped-v2 recomputer through their
    protocol id.  The central dispatcher must register that protocol before a
    completion can validate.
    """

    requirements = [
        {
            "artifact_schema": artifact_schema,
            "evidence_mode": mode,
            "output_name": output_names[output_key],
            "proof_kind": proof_kind,
        }
        for mode in ANALOG_REPLAY_EVIDENCE_MODES
        for proof_kind, artifact_schema, output_key in (
            (
                ATOMIC_TRACE_PROOF_KIND,
                SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
                "trace",
            ),
            (
                CALCULATION_PROOF_KIND,
                SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
                "calculation",
            ),
        )
    ]
    return tuple(
        sorted(
            requirements,
            key=lambda item: (
                item["evidence_mode"],
                item["proof_kind"],
                item["output_name"],
            ),
        )
    )


def build_analog_state_scoped_validation_plan(
    *,
    mission_id: str,
    executable_id: str,
    output_names: Mapping[str, str],
) -> dict[str, object]:
    try:
        configuration = _scoped_configuration_map()[executable_id]
    except KeyError as exc:
        raise ValueError(
            "analog scoped validation subject is outside the exact family"
        ) from exc
    family_ids = tuple(
        str(item["executable_id"])
        for item in expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )
    )
    registrations = analog_replay_multiplicity_registrations(
        subject_executable_id=executable_id,
        subject_configuration_id=configuration.configuration_id,
        ordered_family_executable_ids=family_ids,
    )
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": list(registrations),
        "promotion_criterion_ids": [],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    return build_validation_plan_v2(
        mission_id=_ascii("scoped mission_id", mission_id),
        executable_id=_ascii("scoped executable_id", executable_id),
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=ANALOG_REPLAY_CLAIMS,
        evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
        criteria=ANALOG_REPLAY_CRITERIA,
        adjudication_profile=profile,
        proof_requirements=_atomic_proof_requirements(output_names),
        candidate_eligible_on_pass=False,
    )


@dataclass(frozen=True, slots=True)
class AnalogStateScopedJobPlan:
    mission_id: str
    study_id: str
    configuration: AnalogFamilyConfiguration
    executable_id: str
    output_name_items: tuple[tuple[str, str], ...]
    plan: Mapping[str, object]

    @property
    def output_names(self) -> dict[str, str]:
        return dict(self.output_name_items)

    @property
    def plan_hash(self) -> str:
        return sha256(canonical_bytes(self.plan)).hexdigest()

    def expected_outputs(
        self,
        *,
        produce_family_cache: bool = False,
    ) -> tuple[str, ...]:
        values = set(self.output_names.values())
        if produce_family_cache:
            values.add(analog_scoped_family_trace_cache_output_name())
        return tuple(sorted(values))

    def expected_output_classes(
        self,
        *,
        produce_family_cache: bool = False,
    ) -> dict[str, str]:
        cache_name = analog_scoped_family_trace_cache_output_name()
        return {
            output_name: (
                "reproducible_cache"
                if output_name == cache_name
                else "durable_evidence"
            )
            for output_name in self.expected_outputs(
                produce_family_cache=produce_family_cache
            )
        }

    def job_input_hashes(
        self,
        *,
        family_trace_cache_hash: str | None = None,
        producer_trace_hash: str | None = None,
    ) -> tuple[str, ...]:
        values = {
            DATASET_SHA256,
            OBSERVED_MATERIAL_ID,
            ROLLING_SPLIT_SHA256,
            self.plan_hash,
            analog_family_implementation_sha256(),
            analog_fit_v2_implementation_sha256(),
            analog_replay_v2_bundle_sha256(),
            analog_scoped_job_implementation_sha256(),
            analog_trace_implementation_sha256(),
            discovery_implementation_sha256(),
            loader_implementation_sha256(),
            selection_inference_implementation_sha256(),
        }
        if (family_trace_cache_hash is None) != (producer_trace_hash is None):
            raise ValueError(
                "scoped family cache and producer trace hashes are inseparable"
            )
        if family_trace_cache_hash is not None:
            cache_hash = _digest(
                "scoped family trace cache hash",
                family_trace_cache_hash,
            )
            trace_hash = _digest(
                "scoped producer trace hash",
                producer_trace_hash,
            )
            if cache_hash == trace_hash:
                raise ValueError(
                    "scoped family cache and producer trace hashes must differ"
                )
            values.update((cache_hash, trace_hash))
        return tuple(sorted(values))

    def scientific_binding(self) -> dict[str, object]:
        return {
            "evidence_depth": EVIDENCE_DEPTH,
            "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
            "planned_claims": list(ANALOG_REPLAY_CLAIMS),
            "result_manifest_output": self.output_names["result"],
            "validation_plan_hash": self.plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }


def build_analog_state_scoped_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
) -> AnalogStateScopedJobPlan:
    try:
        configuration = _scoped_configuration_map()[executable_id]
    except KeyError as exc:
        raise ValueError(
            "analog scoped Job subject is outside the scoped-v2 family"
        ) from exc
    names = analog_scoped_output_names(executable_id, study_id=study_id)
    plan = build_analog_state_scoped_validation_plan(
        mission_id=mission_id,
        executable_id=executable_id,
        output_names=names,
    )
    return AnalogStateScopedJobPlan(
        mission_id=mission_id,
        study_id=study_id,
        configuration=configuration,
        executable_id=executable_id,
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )


def validate_analog_scoped_cache_manifest(
    value: Mapping[str, Any],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _CACHE_MANIFEST_FIELDS:
        raise ValueError("analog scoped cache manifest schema is invalid")
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict):
        raise ValueError("analog scoped cache manifest is not an object")
    producer_value = normalized.get("producer_execution")
    if (
        not isinstance(producer_value, dict)
        or set(producer_value) != _PRODUCER_EXECUTION_FIELDS
    ):
        raise ValueError("analog scoped cache producer execution is invalid")
    producer = RunningJobExecution.from_mapping(
        {
            name: producer_value[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    first_executable_id = str(
        expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )[0]["executable_id"]
    )
    if (
        producer_value.get("identity") != producer.identity
        or normalized.get("schema")
        != ANALOG_SCOPED_CACHE_MANIFEST_SCHEMA
        or normalized.get("cache_output_name")
        != analog_scoped_family_trace_cache_output_name()
        or normalized.get("cache_schema") != ANALOG_FAMILY_TRACE_SCHEMA
        or normalized.get("claim_authority") is not False
        or normalized.get("dataset_sha256") != DATASET_SHA256
        or normalized.get("family_id")
        != P1_STU0061_ANALOG_FAMILY.family_id
        or normalized.get("implementation_identities")
        != analog_family_trace_v2_implementation_identities()
        or normalized.get("material_identity") != OBSERVED_MATERIAL_ID
        or normalized.get("neutral_protocol_id")
        != ANALOG_STATE_TRACE_PROTOCOL_ID
        or normalized.get("producer_executable_id") != first_executable_id
        or normalized.get("protocol_id")
        != ANALOG_SCOPED_TRACE_PROTOCOL_ID
        or normalized.get("query_scope_id")
        != ANALOG_SCOPED_QUERY_SCOPE_ID
        or normalized.get("split_artifact_sha256")
        != ROLLING_SPLIT_SHA256
    ):
        raise ValueError("analog scoped cache manifest binding drifted")
    _digest("analog scoped cache sha256", normalized.get("cache_sha256"))
    _ascii(
        "analog scoped manifest output",
        normalized.get("manifest_output_name"),
    )
    _ascii("analog scoped manifest Mission", normalized.get("mission_id"))
    _ascii("analog scoped manifest Study", normalized.get("study_id"))
    return normalized


def build_analog_scoped_cache_manifest(
    *,
    scoped_plan: AnalogStateScopedJobPlan,
    execution: RunningJobExecution,
    cache_sha256: str,
) -> dict[str, object]:
    if not isinstance(scoped_plan, AnalogStateScopedJobPlan) or not isinstance(
        execution,
        RunningJobExecution,
    ):
        raise TypeError("analog scoped cache manifest inputs are invalid")
    first_executable_id = str(
        expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )[0]["executable_id"]
    )
    if scoped_plan.executable_id != first_executable_id:
        raise ValueError("analog scoped cache producer is not the first member")
    contracts = analog_family_execution_contracts()
    value = {
        "cache_output_name": analog_scoped_family_trace_cache_output_name(),
        "cache_schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "cache_sha256": _digest(
            "analog scoped cache sha256",
            cache_sha256,
        ),
        "claim_authority": False,
        "dataset_sha256": DATASET_SHA256,
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_v2_implementation_identities()
        ),
        "manifest_output_name": scoped_plan.output_names["trace"],
        "material_identity": OBSERVED_MATERIAL_ID,
        "mission_id": scoped_plan.mission_id,
        "neutral_protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "producer_executable_id": first_executable_id,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "protocol_id": ANALOG_SCOPED_TRACE_PROTOCOL_ID,
        "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
        "schema": ANALOG_SCOPED_CACHE_MANIFEST_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "study_id": scoped_plan.study_id,
    }
    if set(contracts) != {"clock_contract", "cost_contract"}:
        raise RuntimeError("analog scoped execution contracts drifted")
    return validate_analog_scoped_cache_manifest(value)


def _subject_neutral_trace(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    attribution = trace.get("attribution")
    if (
        not isinstance(attribution, Mapping)
        or set(attribution) != {"family_trace_binding", "protocol_attribution"}
    ):
        raise ValueError("analog scoped subject attribution is invalid")
    binding = attribution.get("family_trace_binding")
    if not isinstance(binding, Mapping) or set(binding) != _FAMILY_BINDING_FIELDS:
        raise ValueError("analog scoped family trace binding is invalid")
    neutral = {
        **{name: trace[name] for name in _NEUTRAL_COMMON_FIELDS},
        "attribution": attribution["protocol_attribution"],
        "clock_contract": binding["clock_contract"],
        "cost_contract": binding["cost_contract"],
        "implementation_identities": binding["implementation_identities"],
        "original_family_provenance": binding[
            "original_family_provenance"
        ],
        "protocol_id": binding["neutral_protocol_id"],
        "schema": binding["schema"],
    }
    return validate_analog_family_trace_scoped_v2(
        neutral,
        family=P1_STU0061_ANALOG_FAMILY,
        original_family_provenance=_legacy_original_family_provenance(),
    )


def validate_analog_scoped_subject_trace(
    trace: Mapping[str, Any],
) -> dict[str, object]:
    if not isinstance(trace, Mapping) or set(trace) != _SUBJECT_TRACE_FIELDS:
        raise ValueError("analog scoped subject trace schema is invalid")
    normalized = parse_canonical(canonical_bytes(trace))
    if not isinstance(normalized, dict):
        raise ValueError("analog scoped subject trace is not an object")
    if (
        normalized.get("schema") != SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or normalized.get("protocol_id")
        != ANALOG_SCOPED_TRACE_PROTOCOL_ID
        or normalized.get("adapter_implementation_sha256")
        != analog_scoped_job_implementation_sha256()
    ):
        raise ValueError("analog scoped subject trace authority drifted")
    _ascii("analog scoped trace Mission", normalized.get("mission_id"))
    _ascii("analog scoped trace Job", normalized.get("job_id"))
    _digest("analog scoped trace Job hash", normalized.get("job_hash"))
    subject_id = _ascii(
        "analog scoped trace executable",
        normalized.get("subject_executable_id"),
    )
    neutral = _subject_neutral_trace(normalized)
    attribution = normalized["attribution"]
    assert isinstance(attribution, dict)
    binding = attribution["family_trace_binding"]
    assert isinstance(binding, dict)
    neutral_hash = sha256(canonical_bytes(neutral)).hexdigest()
    manifest = validate_analog_scoped_cache_manifest(
        binding["cache_manifest"]
    )
    contracts = analog_family_execution_contracts()
    if (
        binding.get("family_trace_sha256") != neutral_hash
        or manifest.get("cache_sha256") != neutral_hash
        or binding.get("clock_contract") != contracts["clock_contract"]
        or binding.get("cost_contract") != contracts["cost_contract"]
        or binding.get("implementation_identities")
        != analog_family_trace_v2_implementation_identities()
        or binding.get("neutral_protocol_id")
        != ANALOG_STATE_TRACE_PROTOCOL_ID
        or binding.get("original_family_provenance")
        != analog_original_family_provenance()
        or binding.get("query_scope_id") != ANALOG_SCOPED_QUERY_SCOPE_ID
        or binding.get("schema") != ANALOG_FAMILY_TRACE_SCHEMA
        or manifest.get("mission_id") != normalized.get("mission_id")
        or subject_id
        not in {
            str(item["executable_id"])
            for item in neutral["ordered_family"]  # type: ignore[index]
        }
    ):
        raise ValueError("analog scoped subject trace binding drifted")
    return normalized


def bind_analog_scoped_family_trace(
    *,
    family_trace: Mapping[str, Any],
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
    cache_manifest: Mapping[str, Any],
) -> dict[str, object]:
    neutral = validate_analog_family_trace_scoped_v2(
        family_trace,
        family=P1_STU0061_ANALOG_FAMILY,
        original_family_provenance=_legacy_original_family_provenance(),
    )
    subject_id = _ascii("analog scoped executable", executable_id)
    if subject_id not in {
        str(item["executable_id"])
        for item in neutral["ordered_family"]  # type: ignore[index]
    }:
        raise ValueError("analog scoped subject is outside its family")
    manifest = validate_analog_scoped_cache_manifest(cache_manifest)
    neutral_content = canonical_bytes(neutral)
    if manifest["cache_sha256"] != sha256(neutral_content).hexdigest():
        raise ValueError("analog scoped cache manifest differs from family rows")
    family_binding = {
        "cache_manifest": manifest,
        "clock_contract": neutral["clock_contract"],
        "cost_contract": neutral["cost_contract"],
        "family_trace_sha256": sha256(neutral_content).hexdigest(),
        "implementation_identities": neutral["implementation_identities"],
        "neutral_protocol_id": neutral["protocol_id"],
        "original_family_provenance": neutral["original_family_provenance"],
        "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
        "schema": neutral["schema"],
    }
    value = {
        **{name: neutral[name] for name in _NEUTRAL_COMMON_FIELDS},
        "adapter_implementation_sha256": (
            analog_scoped_job_implementation_sha256()
        ),
        "attribution": {
            "family_trace_binding": family_binding,
            "protocol_attribution": neutral["attribution"],
        },
        "job_hash": _digest("analog scoped Job hash", job_hash),
        "job_id": _ascii("analog scoped Job", job_id),
        "mission_id": _ascii("analog scoped Mission", mission_id),
        "protocol_id": ANALOG_SCOPED_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
        "subject_executable_id": subject_id,
    }
    return validate_analog_scoped_subject_trace(value)


def extract_analog_scoped_cache_material(
    trace: Mapping[str, Any],
    *,
    require_producer: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    if type(require_producer) is not bool:
        raise ValueError("analog scoped producer requirement must be boolean")
    normalized = validate_analog_scoped_subject_trace(trace)
    neutral = _subject_neutral_trace(normalized)
    attribution = normalized["attribution"]
    assert isinstance(attribution, dict)
    binding = attribution["family_trace_binding"]
    assert isinstance(binding, dict)
    manifest = validate_analog_scoped_cache_manifest(
        binding["cache_manifest"]
    )
    if require_producer:
        producer = manifest["producer_execution"]
        assert isinstance(producer, dict)
        if (
            normalized.get("subject_executable_id")
            != manifest.get("producer_executable_id")
            or normalized.get("job_id") != producer.get("job_id")
            or normalized.get("job_hash") != producer.get("job_hash")
        ):
            raise ValueError(
                "analog scoped cache manifest belongs to another producer trace"
            )
    if sha256(canonical_bytes(neutral)).hexdigest() != manifest["cache_sha256"]:
        raise ValueError("analog scoped producer trace cache bytes drifted")
    return neutral, manifest


def _scoped_recalculation_material(
    trace: Mapping[str, Any],
) -> tuple[
    dict[str, object],
    dict[str, dict[str, int]],
    dict[str, object],
]:
    """Recompute metrics from scoped rows through a transparent ID adapter."""

    normalized = validate_analog_scoped_subject_trace(trace)
    neutral = _subject_neutral_trace(normalized)
    subject_id = str(normalized["subject_executable_id"])
    configuration = _scoped_configuration_map()[subject_id]

    # This projection changes identifiers only and is never emitted.  The v1
    # pure calculator remains the formula authority while the scoped trace is
    # the sole atomic evidence authority.
    projected = replay_v2._project_analog_v2_trace_to_v1(  # noqa: SLF001
        neutral,
        scoped=True,
    )
    projected_subject_id = analog_family_executable(configuration).identity
    projected_bound = bind_analog_family_trace(
        family_trace=projected,
        mission_id=str(normalized["mission_id"]),
        executable_id=projected_subject_id,
        job_id=str(normalized["job_id"]),
        job_hash=str(normalized["job_hash"]),
    )
    projected_bound_hash = sha256(canonical_bytes(projected_bound)).hexdigest()
    legacy_calculation = build_analog_trace_calculation(
        trace=projected_bound,
        trace_output_name="internal/non-authoritative-identifier-projection",
        trace_hash=projected_bound_hash,
    )
    parameters = {
        **analog_calculation_parameters(),
        "identifier_projection_claim_authority": False,
        "identifier_projection_purpose": (
            "pure_metric_recomputation_only_not_evidence"
        ),
        "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
    }
    statistics = {
        **legacy_calculation["statistics"],
        "scoped_query_projection": {
            "claim_authority": False,
            "emitted_as_evidence": False,
            "projected_family_trace_sha256": sha256(
                canonical_bytes(projected)
            ).hexdigest(),
            "projected_v1_subject_executable_id": projected_subject_id,
            "purpose": "identifier_projection_for_pure_metric_recomputation",
            "query_scope_id": ANALOG_SCOPED_QUERY_SCOPE_ID,
            "source_scoped_executable_id": subject_id,
            "source_scoped_family_trace_sha256": sha256(
                canonical_bytes(neutral)
            ).hexdigest(),
        },
    }
    metrics = legacy_calculation["metrics"]
    if not isinstance(metrics, dict):
        raise RuntimeError("analog scoped metric recomputation is invalid")
    canonical_bytes(parameters)
    canonical_bytes(metrics)
    canonical_bytes(statistics)
    return parameters, metrics, statistics


def build_analog_scoped_calculation(
    *,
    trace: Mapping[str, Any],
    trace_output_name: str,
    trace_hash: str,
) -> dict[str, object]:
    normalized = validate_analog_scoped_subject_trace(trace)
    parameters, metrics, statistics = _scoped_recalculation_material(
        normalized
    )
    value = {
        "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
        "executable_id": normalized["subject_executable_id"],
        "job_hash": normalized["job_hash"],
        "job_id": normalized["job_id"],
        "metrics": metrics,
        "mission_id": normalized["mission_id"],
        "parameters": parameters,
        "protocol_id": ANALOG_SCOPED_TRACE_PROTOCOL_ID,
        "schema": SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        "statistics": statistics,
        "trace": {
            "output_name": _ascii(
                "analog scoped trace output",
                trace_output_name,
            ),
            "sha256": _digest("analog scoped trace hash", trace_hash),
        },
    }
    canonical_bytes(value)
    return value


def _validate_analog_scoped_trace_calculation(
    *,
    trace: Mapping[str, Any],
    calculation: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    normalized = validate_analog_scoped_subject_trace(trace)
    if (
        not isinstance(calculation, Mapping)
        or set(calculation) != _CALCULATION_FIELDS
        or calculation.get("schema")
        != SCIENTIFIC_CALCULATION_PROOF_SCHEMA
        or calculation.get("protocol_id")
        != ANALOG_SCOPED_TRACE_PROTOCOL_ID
        or calculation.get("mission_id") != normalized.get("mission_id")
        or calculation.get("executable_id")
        != normalized.get("subject_executable_id")
        or calculation.get("job_id") != normalized.get("job_id")
        or calculation.get("job_hash") != normalized.get("job_hash")
        or calculation.get("evidence_modes")
        != list(ANALOG_REPLAY_EVIDENCE_MODES)
    ):
        raise ValueError("analog scoped trace calculation binding drifted")
    trace_reference = calculation.get("trace")
    if not isinstance(trace_reference, Mapping) or set(trace_reference) != {
        "output_name",
        "sha256",
    }:
        raise ValueError("analog scoped calculation trace reference is invalid")
    _ascii("analog scoped calculation trace output", trace_reference["output_name"])
    _digest("analog scoped calculation trace hash", trace_reference["sha256"])
    parameters, metrics, statistics = _scoped_recalculation_material(
        normalized
    )
    if (
        calculation.get("parameters") != parameters
        or calculation.get("metrics") != metrics
        or calculation.get("statistics") != statistics
    ):
        raise ValueError("analog scoped calculation drifted from atomic rows")
    return metrics


def validate_analog_scoped_trace_calculation(
    *,
    trace: Mapping[str, Any],
    calculation: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    """Closed-dispatch adapter with the common scientific error contract."""

    try:
        return _validate_analog_scoped_trace_calculation(
            trace=trace,
            calculation=calculation,
        )
    except ScientificTraceError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ScientificTraceError(
            "analog scoped trace calculation is invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class AnalogScopedFamilyTraceCache:
    content: bytes
    produced: bool
    sha256: str

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or type(self.produced) is not bool:
            raise ValueError("analog scoped cache value is invalid")
        if (
            _digest("analog scoped cache content hash", self.sha256)
            != sha256(self.content).hexdigest()
        ):
            raise ValueError("analog scoped cache content hash drifted")

    def trace(self) -> dict[str, object]:
        value = parse_canonical(self.content)
        if not isinstance(value, dict) or canonical_bytes(value) != self.content:
            raise ValueError("analog scoped cache bytes are not canonical")
        return validate_analog_family_trace_scoped_v2(
            value,
            family=P1_STU0061_ANALOG_FAMILY,
            original_family_provenance=_legacy_original_family_provenance(),
        )


def _materialize_analog_scoped_cache(
    repository_root: Path,
    *,
    content: bytes,
) -> None:
    publish_reproducible_cache(
        repository_root=repository_root,
        relative_path=analog_scoped_family_trace_cache_output_name(),
        content=content,
    )


def compute_analog_scoped_family_cache(
    repository_root: str | Path,
) -> AnalogScopedFamilyTraceCache:
    root = Path(repository_root).resolve()
    family_trace, _ = compute_analog_family_trace_scoped_v2(
        root,
        family=P1_STU0061_ANALOG_FAMILY,
        original_family_provenance=_legacy_original_family_provenance(),
    )
    neutral = validate_analog_family_trace_scoped_v2(
        family_trace,
        family=P1_STU0061_ANALOG_FAMILY,
        original_family_provenance=_legacy_original_family_provenance(),
    )
    content = canonical_bytes(neutral)
    _materialize_analog_scoped_cache(root, content=content)
    return AnalogScopedFamilyTraceCache(
        content=content,
        produced=True,
        sha256=sha256(content).hexdigest(),
    )


def _advertises_scoped_cache_manifest(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    attribution = value.get("attribution")
    binding = (
        attribution.get("family_trace_binding")
        if isinstance(attribution, Mapping)
        else None
    )
    manifest = (
        binding.get("cache_manifest")
        if isinstance(binding, Mapping)
        else None
    )
    return (
        value.get("schema") == SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        and value.get("protocol_id") == ANALOG_SCOPED_TRACE_PROTOCOL_ID
        and isinstance(manifest, Mapping)
        and manifest.get("schema") == ANALOG_SCOPED_CACHE_MANIFEST_SCHEMA
    )


def verify_analog_scoped_cache_producer(
    writer: AnalogScopedJobContext,
    *,
    scoped_plan: AnalogStateScopedJobPlan,
    repository_root: str | Path,
    input_hashes: Sequence[str],
    materialize_missing: bool = True,
) -> tuple[AnalogScopedFamilyTraceCache, str, dict[str, object]]:
    if not isinstance(scoped_plan, AnalogStateScopedJobPlan):
        raise TypeError("analog scoped cache consumer plan is invalid")
    if type(materialize_missing) is not bool:
        raise ValueError("analog scoped cache materialization signal is invalid")
    root = Path(repository_root).resolve()
    inputs = tuple(input_hashes)
    matches: list[
        tuple[str, AnalogScopedFamilyTraceCache, dict[str, object]]
    ] = []
    for input_hash in dict.fromkeys(inputs):
        try:
            content = writer.evidence.read_verified(input_hash)
            value = parse_canonical(content)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            continue
        if not _advertises_scoped_cache_manifest(value):
            continue
        if not isinstance(value, dict) or canonical_bytes(value) != content:
            raise ValueError("analog scoped producer trace is not canonical")
        try:
            neutral, manifest = extract_analog_scoped_cache_material(
                value,
                require_producer=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("analog scoped producer trace is invalid") from exc
        neutral_content = canonical_bytes(neutral)
        matches.append(
            (
                input_hash,
                AnalogScopedFamilyTraceCache(
                    content=neutral_content,
                    produced=False,
                    sha256=str(manifest["cache_sha256"]),
                ),
                manifest,
            )
        )
    if len(matches) != 1:
        raise ValueError(
            "Job inputs require one exact analog scoped cache producer trace"
        )
    producer_trace_hash, family_cache, manifest = matches[0]
    if inputs.count(family_cache.sha256) != 1:
        raise ValueError(
            "analog scoped cache hash must be exactly one Job input"
        )
    if inputs.count(producer_trace_hash) != 1:
        raise ValueError(
            "analog scoped producer trace must be exactly one Job input"
        )
    producer_executable_id = str(
        expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )[0]["executable_id"]
    )
    producer_plan = build_analog_state_scoped_plan(
        mission_id=scoped_plan.mission_id,
        study_id=scoped_plan.study_id,
        executable_id=producer_executable_id,
    )
    if (
        manifest.get("cache_output_name")
        != analog_scoped_family_trace_cache_output_name()
        or manifest.get("cache_sha256") != family_cache.sha256
        or manifest.get("mission_id") != scoped_plan.mission_id
        or manifest.get("study_id") != scoped_plan.study_id
        or manifest.get("producer_executable_id") != producer_executable_id
        or manifest.get("manifest_output_name")
        != producer_plan.output_names["trace"]
    ):
        raise ValueError("analog scoped cache producer manifest is out of scope")
    producer_payload = manifest.get("producer_execution")
    if not isinstance(producer_payload, Mapping):
        raise ValueError("analog scoped cache producer execution is invalid")
    producer = RunningJobExecution.from_mapping(
        {
            name: producer_payload[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if producer_payload.get("identity") != producer.identity:
        raise ValueError("analog scoped cache producer identity drifted")
    writer.verify_reproducible_cache_producer(
        producer,
        cache_output_name=analog_scoped_family_trace_cache_output_name(),
        cache_hash=family_cache.sha256,
        expected_callable_identity=CALLABLE_IDENTITY,
        expected_evidence_subject={
            "kind": "Executable",
            "id": producer_executable_id,
        },
        expected_output_classes=producer_plan.expected_output_classes(
            produce_family_cache=True
        ),
        expected_study_id=scoped_plan.study_id,
        manifest_output_name=producer_plan.output_names["trace"],
        manifest_hash=producer_trace_hash,
    )
    target = root / analog_scoped_family_trace_cache_output_name()
    if target.exists() or materialize_missing:
        _materialize_analog_scoped_cache(root, content=family_cache.content)
    return family_cache, producer_trace_hash, manifest


def build_analog_scoped_measurement(
    *,
    scoped_plan: AnalogStateScopedJobPlan,
    job_id: str,
    job_hash: str,
    calculation: Mapping[str, Any],
    trace_hash: str,
    calculation_hash: str,
) -> dict[str, object]:
    requirements = parse_proof_requirements(
        scoped_plan.plan["proof_requirements"],
        evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
    )
    metrics = calculation.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("analog scoped calculation metrics are invalid")
    profile = scoped_plan.plan.get("adjudication_profile")
    registrations = (
        None if not isinstance(profile, Mapping) else profile.get("multiplicity")
    )
    if not isinstance(registrations, list):
        raise ValueError("analog scoped multiplicity plan is malformed")
    registration_by_criterion = {
        str(item["criterion_id"]): item for item in registrations
    }
    paired = registration_by_criterion.get(
        "D02-opposite-sign-uncertainty"
    )
    if not isinstance(paired, Mapping):
        raise ValueError("analog scoped paired-control registration is absent")
    projected_family_ids = tuple(
        sorted(
            analog_family_executable(configuration).identity
            for configuration in P1_STU0061_ANALOG_FAMILY.configurations()
        )
    )
    projected_subject_id = analog_family_executable(
        scoped_plan.configuration
    ).identity
    multiplicity = build_analog_replay_multiplicity_results(
        calculation=calculation,
        registrations=registrations,
        statistical_bindings={
            "D02-opposite-sign-uncertainty": {
                "family_id": paired["family_id"],
                "member_id": paired["member_id"],
                "ordered_member_ids": sorted(
                    str(value)
                    for value in paired["ordered_member_ids"]  # type: ignore[index]
                ),
            },
            "E01-familywise-selection": {
                "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
                "member_id": projected_subject_id,
                "ordered_member_ids": list(projected_family_ids),
            },
        },
    )
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("analog scoped measurement Job hash", job_hash),
        "job_id": _ascii("analog scoped measurement Job", job_id),
        "metrics": metrics,
        "mission_id": scoped_plan.mission_id,
        "multiplicity": list(multiplicity),
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    scoped_plan.output_names["trace"]: trace_hash,
                    scoped_plan.output_names["calculation"]: calculation_hash,
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_analog_scoped_result(
    *,
    scoped_plan: AnalogStateScopedJobPlan,
    job_id: str,
    job_hash: str,
    measurement_hash: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("analog scoped result Job hash", job_hash),
        "job_id": _ascii("analog scoped result Job", job_id),
        "mission_id": scoped_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": _digest(
                    "analog scoped measurement hash",
                    measurement_hash,
                ),
            }
            for claim_id in ANALOG_REPLAY_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class AnalogStateScopedJobPacket:
    adjudication_state: str
    output_manifest: tuple[tuple[str, str], ...]

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def execute_analog_state_scoped_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> AnalogStateScopedJobPacket:
    """Run one scoped-v2 family member from a writer-derived Job permit."""

    root = Path(repository_root).resolve()
    writer = RunningJobExecutionContext(root)
    binding = writer.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    spec = binding.get("spec")
    if not isinstance(spec, Mapping):
        raise ValueError("analog scoped running Job specification is invalid")
    subject = spec.get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        raise ValueError("analog scoped Job subject is invalid")
    scoped_plan = build_analog_state_scoped_plan(
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=str(subject.get("id")),
    )
    if (
        spec.get("implementation_identity")
        != analog_scoped_job_implementation_sha256()
        or spec.get("scientific_binding") != scoped_plan.scientific_binding()
    ):
        raise ValueError("analog scoped Job implementation or science drifted")
    expected_outputs = set(spec.get("expected_outputs", []))
    cache_output_name = analog_scoped_family_trace_cache_output_name()
    produce_family_cache = cache_output_name in expected_outputs
    producer_executable_id = str(
        expected_analog_family_inventory_scoped_v2(
            P1_STU0061_ANALOG_FAMILY
        )[0]["executable_id"]
    )
    if produce_family_cache != (
        scoped_plan.executable_id == producer_executable_id
    ):
        raise ValueError(
            "analog scoped family cache producer must be the first member"
        )
    if (
        expected_outputs
        != set(
            scoped_plan.expected_outputs(
                produce_family_cache=produce_family_cache
            )
        )
        or spec.get("output_classes")
        != scoped_plan.expected_output_classes(
            produce_family_cache=produce_family_cache
        )
    ):
        raise ValueError("analog scoped Job output contract drifted")
    input_hashes = tuple(spec.get("input_hashes", []))
    if not set(scoped_plan.job_input_hashes()).issubset(set(input_hashes)):
        raise ValueError("analog scoped Job omits a registered dependency")

    if produce_family_cache:
        family_cache = compute_analog_scoped_family_cache(root)
        cache_manifest = build_analog_scoped_cache_manifest(
            scoped_plan=scoped_plan,
            execution=execution,
            cache_sha256=family_cache.sha256,
        )
    else:
        family_cache, _, cache_manifest = verify_analog_scoped_cache_producer(
            writer,
            scoped_plan=scoped_plan,
            repository_root=root,
            input_hashes=input_hashes,
            materialize_missing=True,
        )
    neutral = family_cache.trace()
    trace = bind_analog_scoped_family_trace(
        family_trace=neutral,
        mission_id=scoped_plan.mission_id,
        executable_id=scoped_plan.executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        cache_manifest=cache_manifest,
    )
    names = scoped_plan.output_names
    trace_hash = writer.evidence.finalize(canonical_bytes(trace)).sha256
    calculation = build_analog_scoped_calculation(
        trace=trace,
        trace_output_name=names["trace"],
        trace_hash=trace_hash,
    )
    calculation_hash = writer.evidence.finalize(
        canonical_bytes(calculation)
    ).sha256
    measurement = build_analog_scoped_measurement(
        scoped_plan=scoped_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        calculation=calculation,
        trace_hash=trace_hash,
        calculation_hash=calculation_hash,
    )
    measurement_hash = writer.evidence.finalize(
        canonical_bytes(measurement)
    ).sha256
    result = build_analog_scoped_result(
        scoped_plan=scoped_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_hash=measurement_hash,
    )
    outputs = {
        names["calculation"]: calculation_hash,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(
            canonical_bytes(scoped_plan.plan)
        ).sha256,
        names["result"]: writer.evidence.finalize(canonical_bytes(result)).sha256,
        names["trace"]: trace_hash,
    }
    if family_cache.produced:
        outputs[cache_output_name] = family_cache.sha256
    if set(outputs) != expected_outputs:
        raise ValueError("analog scoped Job materialized undeclared outputs")
    adjudication = adjudicate_plan_measurement(scoped_plan.plan, measurement)
    return AnalogStateScopedJobPacket(
        adjudication_state=adjudication.state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "ANALOG_SCOPED_CACHE_MANIFEST_SCHEMA",
    "ANALOG_SCOPED_TRACE_PROTOCOL_ID",
    "CALLABLE_IDENTITY",
    "AnalogScopedFamilyTraceCache",
    "AnalogScopedJobContext",
    "AnalogStateScopedJobPacket",
    "AnalogStateScopedJobPlan",
    "analog_scoped_family_trace_cache_output_name",
    "analog_scoped_job_dependency_paths",
    "analog_scoped_job_implementation_artifact",
    "analog_scoped_job_source_closure_artifact",
    "analog_scoped_job_implementation_sha256",
    "analog_scoped_output_names",
    "bind_analog_scoped_family_trace",
    "build_analog_scoped_cache_manifest",
    "build_analog_scoped_calculation",
    "build_analog_scoped_measurement",
    "build_analog_scoped_result",
    "build_analog_state_scoped_plan",
    "build_analog_state_scoped_validation_plan",
    "compute_analog_scoped_family_cache",
    "execute_analog_state_scoped_job",
    "materialize_analog_scoped_job_implementation",
    "extract_analog_scoped_cache_material",
    "validate_analog_scoped_cache_manifest",
    "validate_analog_scoped_subject_trace",
    "validate_analog_scoped_trace_calculation",
    "verify_analog_scoped_cache_producer",
]
