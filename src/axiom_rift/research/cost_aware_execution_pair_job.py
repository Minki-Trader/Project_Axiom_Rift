"""Job envelope for the corrected STU-0070 paired execution replay.

The first historical member produces one neutral, immutable pair trace.  Both
subject Jobs bind that same trace to their own capability and independently
recompute their scientific measurement.  The cache is an optimization only;
its producer execution, subject trace, neutral bytes, and provenance must all
agree before a later member may consume it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.cost_aware_execution_pair import (
    cost_aware_execution_pair_historical_context,
    cost_aware_execution_pair_producer_implementation_identities,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_pair_engine import (
    COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_REPLAY_CLAIMS,
    COST_AWARE_EXECUTION_REPLAY_CRITERIA,
    COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
    CostAwareExecutionProtocolDefinition,
    build_cost_aware_execution_validation_plan,
    cost_aware_execution_multiplicity_registrations,
)
from axiom_rift.research.cost_aware_execution_trace import (
    bind_cost_aware_execution_subject_trace,
    build_cost_aware_execution_pair_calculation,
    extract_cost_aware_execution_pair_trace,
    validate_cost_aware_execution_pair_trace,
    validate_cost_aware_execution_subject_trace,
    validate_cost_aware_execution_trace_calculation,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.evidence_proofs import (
    build_proof_references,
    parse_proof_requirements,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
)
from axiom_rift.research.replay_coverage import (
    validated_recomputed_criterion_ids,
)
from axiom_rift.research.reproducible_cache import (
    publish_reproducible_cache,
    reproducible_cache_implementation_sha256,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    adjudicate_validation_measurement_v2,
)


ARTIFACT_NAMESPACE = "cost-aware-execution-pair-v1"
COST_AWARE_EXECUTION_CACHE_PROVENANCE_SCHEMA = (
    "cost_aware_execution_pair_cache_provenance.v1"
)
EVIDENCE_DEPTH = "discovery"
_THIS_FILE = Path(__file__).resolve()
_PRODUCER_EXECUTION_FIELDS = {
    "identity",
    "job_hash",
    "job_id",
    "job_permit_id",
    "start_record_id",
}
_PROVENANCE_FIELDS = {
    "cache_output_name",
    "cache_sha256",
    "definition_identity",
    "historical_context",
    "mission_id",
    "producer_executable_id",
    "producer_execution",
    "producer_manifest",
    "producer_trace_output_name",
    "producer_trace_sha256",
    "prospective_family_id",
    "protocol_id",
    "schema",
    "study_id",
}


class CostAwareExecutionJobAuthority(Protocol):
    evidence: Any

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


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


def _namespace(value: object) -> str:
    namespace = _ascii("cost-aware artifact namespace", value)
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in namespace
    ):
        raise ValueError("cost-aware artifact namespace is not path-safe")
    return namespace


def _input_digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    ):
        return text
    return sha256(text.encode("ascii")).hexdigest()


def cost_aware_execution_pair_job_implementation_sha256() -> str:
    return sha256(
        _THIS_FILE.read_bytes()
        + bytes.fromhex(reproducible_cache_implementation_sha256())
    ).hexdigest()


def cost_aware_execution_pair_output_names(
    *,
    study_id: str,
    executable_id: str,
    artifact_namespace: str = ARTIFACT_NAMESPACE,
) -> dict[str, str]:
    study = _ascii("cost-aware study_id", study_id)
    executable = _ascii("cost-aware executable_id", executable_id)
    namespace = _namespace(artifact_namespace)
    prefix = (
        f"scientific/{study}/"
        f"{executable.removeprefix('executable:')[:16]}-{namespace}"
    )
    return {
        "calculation": f"{prefix}/calculation-proof.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
        "trace": f"{prefix}/evaluation-trace.json",
    }


def cost_aware_execution_pair_cache_output_name(
    *,
    definition: CostAwareExecutionProtocolDefinition,
    artifact_namespace: str = ARTIFACT_NAMESPACE,
) -> str:
    namespace = _namespace(artifact_namespace)
    suffix = definition.identity.removeprefix(
        "cost-aware-execution-definition:"
    )[:16]
    return f"local/cache/historical-replay/{namespace}-{suffix}.json"


def cost_aware_execution_pair_cache_provenance_output_name(
    *,
    study_id: str,
    artifact_namespace: str = ARTIFACT_NAMESPACE,
) -> str:
    return (
        f"scientific/{_ascii('cost-aware study_id', study_id)}/"
        f"{_namespace(artifact_namespace)}-family-cache-provenance.json"
    )


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairJobPlan:
    mission_id: str
    study_id: str
    executable_id: str
    definition: CostAwareExecutionProtocolDefinition
    historical_context: HistoricalSearchContext
    artifact_namespace: str
    output_name_items: tuple[tuple[str, str], ...]
    plan: Mapping[str, object]

    @property
    def output_names(self) -> dict[str, str]:
        return dict(self.output_name_items)

    @property
    def plan_hash(self) -> str:
        return sha256(canonical_bytes(self.plan)).hexdigest()

    @property
    def producer_executable_id(self) -> str:
        return self.definition.prospective_executable_ids[0]

    @property
    def produces_family_cache(self) -> bool:
        return self.executable_id == self.producer_executable_id

    @property
    def cache_output_name(self) -> str:
        return cost_aware_execution_pair_cache_output_name(
            definition=self.definition,
            artifact_namespace=self.artifact_namespace,
        )

    @property
    def cache_provenance_output_name(self) -> str:
        return cost_aware_execution_pair_cache_provenance_output_name(
            study_id=self.study_id,
            artifact_namespace=self.artifact_namespace,
        )

    def expected_outputs(self) -> tuple[str, ...]:
        values = set(self.output_names.values())
        if self.produces_family_cache:
            values.update(
                (self.cache_output_name, self.cache_provenance_output_name)
            )
        return tuple(sorted(values))

    def expected_output_classes(self) -> dict[str, str]:
        return {
            name: (
                "reproducible_cache"
                if name == self.cache_output_name
                else "durable_evidence"
            )
            for name in self.expected_outputs()
        }

    def direct_evidence_input_hashes(self) -> tuple[str, ...]:
        return ()

    def job_input_hashes(
        self,
        *,
        cache_sha256: str | None = None,
        cache_provenance_sha256: str | None = None,
        producer_trace_sha256: str | None = None,
    ) -> tuple[str, ...]:
        optional = (
            cache_sha256,
            cache_provenance_sha256,
            producer_trace_sha256,
        )
        missing = tuple(value is None for value in optional)
        if any(missing) and not all(missing):
            raise ValueError(
                "cost-aware cache, provenance, and trace hashes are inseparable"
            )
        context_hash = sha256(
            canonical_bytes(self.historical_context.manifest())
        ).hexdigest()
        values = {
            DATASET_SHA256,
            OBSERVED_MATERIAL_ID,
            ROLLING_SPLIT_SHA256,
            self.definition.identity,
            self.plan_hash,
            context_hash,
            cost_aware_execution_pair_job_implementation_sha256(),
            reproducible_cache_implementation_sha256(),
            *cost_aware_execution_pair_producer_implementation_identities().values(),
        }
        for index, value in enumerate(optional):
            if value is not None:
                values.add(_digest(f"cost-aware cache input {index}", value))
        return tuple(
            sorted(
                _input_digest("cost-aware Job input identity", value)
                for value in values
            )
        )

    def scientific_binding(self) -> dict[str, object]:
        return {
            "evidence_depth": EVIDENCE_DEPTH,
            "evidence_modes": list(COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES),
            "planned_claims": list(COST_AWARE_EXECUTION_REPLAY_CLAIMS),
            "result_manifest_output": self.output_names["result"],
            "validation_plan_hash": self.plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }

    def validated_recomputed_criterion_ids(
        self,
        scientific_facts: Mapping[str, object],
    ) -> tuple[str, ...]:
        return validated_recomputed_criterion_ids(
            scientific_facts,
            expected_evidence_modes=COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
            expected_criteria=COST_AWARE_EXECUTION_REPLAY_CRITERIA,
            context="cost-aware paired execution replay",
        )


def build_cost_aware_execution_pair_job_plan_from_definition(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
    definition: CostAwareExecutionProtocolDefinition,
    historical_context: HistoricalSearchContext,
    artifact_namespace: str = ARTIFACT_NAMESPACE,
) -> CostAwareExecutionPairJobPlan:
    if executable_id not in definition.prospective_executable_ids:
        raise ValueError("cost-aware Job subject is outside its exact pair")
    names = cost_aware_execution_pair_output_names(
        study_id=study_id,
        executable_id=executable_id,
        artifact_namespace=artifact_namespace,
    )
    plan = build_cost_aware_execution_validation_plan(
        definition=definition,
        mission_id=mission_id,
        executable_id=executable_id,
        output_names=names,
    )
    return CostAwareExecutionPairJobPlan(
        mission_id=_ascii("cost-aware mission_id", mission_id),
        study_id=_ascii("cost-aware study_id", study_id),
        executable_id=_ascii("cost-aware executable_id", executable_id),
        definition=definition,
        historical_context=historical_context,
        artifact_namespace=_namespace(artifact_namespace),
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )


def build_cost_aware_execution_pair_job_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
    historical_context_prior_global_exposure_count: int,
    original_family_end_global_exposure_count: int,
    historical_family: HistoricalFamilySpec,
    historical_family_authority_id: str,
    replay_obligation_id: str,
) -> CostAwareExecutionPairJobPlan:
    replay_context = HistoricalFamilyReplayContext(
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
    return build_cost_aware_execution_pair_job_plan_from_definition(
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
        definition=cost_aware_execution_pair_protocol_definition(
            replay_context
        ),
        historical_context=cost_aware_execution_pair_historical_context(
            replay_context
        ),
    )


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairCache:
    content: bytes
    produced: bool
    sha256: str
    _trace: dict[str, object] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or type(self.produced) is not bool:
            raise ValueError("cost-aware cache value is invalid")
        if _digest("cost-aware cache hash", self.sha256) != sha256(
            self.content
        ).hexdigest():
            raise ValueError("cost-aware cache content hash drifted")

    def trace(
        self,
        definition: CostAwareExecutionProtocolDefinition,
    ) -> dict[str, object]:
        value: object = self._trace
        if value is None:
            value = parse_canonical(self.content)
        if not isinstance(value, Mapping) or canonical_bytes(value) != self.content:
            raise ValueError("cost-aware cache bytes are not canonical")
        return validate_cost_aware_execution_pair_trace(
            value,
            definition=definition,
        )


def cost_aware_execution_pair_cache(
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    neutral_trace: Mapping[str, Any],
    produced: bool,
) -> CostAwareExecutionPairCache:
    trace = validate_cost_aware_execution_pair_trace(
        neutral_trace,
        definition=scoped_plan.definition,
    )
    if (
        trace.get("dataset_sha256") != DATASET_SHA256
        or trace.get("split_artifact_sha256") != ROLLING_SPLIT_SHA256
        or trace.get("material_identity") != OBSERVED_MATERIAL_ID
        or trace.get("historical_context")
        != scoped_plan.historical_context.manifest()
    ):
        raise ValueError("cost-aware cache differs from its registered inputs")
    content = canonical_bytes(trace)
    return CostAwareExecutionPairCache(
        content=content,
        produced=produced,
        sha256=sha256(content).hexdigest(),
        _trace=trace,
    )


def materialize_cost_aware_execution_pair_cache(
    repository_root: str | Path,
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    content: bytes,
) -> None:
    publish_reproducible_cache(
        repository_root=Path(repository_root).resolve(),
        relative_path=scoped_plan.cache_output_name,
        content=content,
    )


def _validated_producer_manifest(
    value: Mapping[str, Any],
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    cache_sha256: str,
) -> dict[str, object]:
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict):
        raise ValueError("cost-aware producer manifest is not an object")
    if (
        normalized.get("schema")
        != COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA
        or normalized.get("trace_sha256") != cache_sha256
        or normalized.get("dataset_sha256") != DATASET_SHA256
        or normalized.get("split_artifact_sha256") != ROLLING_SPLIT_SHA256
        or normalized.get("material_identity") != OBSERVED_MATERIAL_ID
        or normalized.get("protocol_id") != scoped_plan.definition.protocol_id
        or normalized.get("protocol_definition_id")
        != scoped_plan.definition.identity
        or normalized.get("prospective_family_id")
        != scoped_plan.definition.prospective_family_id
    ):
        raise ValueError("cost-aware producer manifest authority drifted")
    historical = normalized.get("historical_context")
    if (
        not isinstance(historical, dict)
        or historical.get("current")
        != scoped_plan.historical_context.manifest()
    ):
        raise ValueError("cost-aware producer historical context drifted")
    identities = normalized.get("implementation_identities")
    if identities != dict(
        sorted(
            cost_aware_execution_pair_producer_implementation_identities().items()
        )
    ):
        raise ValueError("cost-aware producer implementation closure drifted")
    return normalized


def build_cost_aware_execution_pair_cache_provenance(
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    execution: RunningJobExecution,
    cache_sha256: str,
    producer_trace_sha256: str,
    producer_manifest: Mapping[str, Any],
) -> dict[str, object]:
    if not scoped_plan.produces_family_cache:
        raise ValueError("cost-aware cache provenance requires the first member")
    cache_hash = _digest("cost-aware cache hash", cache_sha256)
    manifest = _validated_producer_manifest(
        producer_manifest,
        scoped_plan=scoped_plan,
        cache_sha256=cache_hash,
    )
    value = {
        "cache_output_name": scoped_plan.cache_output_name,
        "cache_sha256": cache_hash,
        "definition_identity": scoped_plan.definition.identity,
        "historical_context": scoped_plan.historical_context.manifest(),
        "mission_id": scoped_plan.mission_id,
        "producer_executable_id": scoped_plan.executable_id,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "producer_manifest": manifest,
        "producer_trace_output_name": scoped_plan.output_names["trace"],
        "producer_trace_sha256": _digest(
            "cost-aware producer trace hash",
            producer_trace_sha256,
        ),
        "prospective_family_id": scoped_plan.definition.prospective_family_id,
        "protocol_id": scoped_plan.definition.protocol_id,
        "schema": COST_AWARE_EXECUTION_CACHE_PROVENANCE_SCHEMA,
        "study_id": scoped_plan.study_id,
    }
    validate_cost_aware_execution_pair_cache_provenance(
        value,
        scoped_plan=scoped_plan,
    )
    return value


def validate_cost_aware_execution_pair_cache_provenance(
    value: Mapping[str, Any],
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PROVENANCE_FIELDS:
        raise ValueError("cost-aware cache provenance schema is invalid")
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict):
        raise ValueError("cost-aware cache provenance is not an object")
    if (
        normalized.get("schema")
        != COST_AWARE_EXECUTION_CACHE_PROVENANCE_SCHEMA
        or normalized.get("cache_output_name")
        != scoped_plan.cache_output_name
        or normalized.get("definition_identity")
        != scoped_plan.definition.identity
        or normalized.get("historical_context")
        != scoped_plan.historical_context.manifest()
        or normalized.get("mission_id") != scoped_plan.mission_id
        or normalized.get("producer_executable_id")
        != scoped_plan.producer_executable_id
        or normalized.get("producer_trace_output_name")
        != cost_aware_execution_pair_output_names(
            study_id=scoped_plan.study_id,
            executable_id=scoped_plan.producer_executable_id,
            artifact_namespace=scoped_plan.artifact_namespace,
        )["trace"]
        or normalized.get("prospective_family_id")
        != scoped_plan.definition.prospective_family_id
        or normalized.get("protocol_id")
        != scoped_plan.definition.protocol_id
        or normalized.get("study_id") != scoped_plan.study_id
    ):
        raise ValueError("cost-aware cache provenance is out of scope")
    cache_hash = _digest(
        "cost-aware cache hash",
        normalized.get("cache_sha256"),
    )
    _digest(
        "cost-aware producer trace hash",
        normalized.get("producer_trace_sha256"),
    )
    _validated_producer_manifest(
        normalized["producer_manifest"],
        scoped_plan=scoped_plan,
        cache_sha256=cache_hash,
    )
    producer = normalized.get("producer_execution")
    if not isinstance(producer, dict) or set(producer) != _PRODUCER_EXECUTION_FIELDS:
        raise ValueError("cost-aware cache producer execution is invalid")
    execution = RunningJobExecution.from_mapping(
        {
            name: producer[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if producer.get("identity") != execution.identity:
        raise ValueError("cost-aware cache producer identity drifted")
    return normalized


def verify_cost_aware_execution_pair_cache_producer(
    writer: CostAwareExecutionJobAuthority,
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    repository_root: str | Path,
    input_hashes: Sequence[str],
    expected_callable_identity: str,
    materialize_missing: bool = True,
) -> tuple[CostAwareExecutionPairCache, str, str, dict[str, object]]:
    if scoped_plan.produces_family_cache:
        raise ValueError("cost-aware producer cannot consume its own cache")
    inputs = tuple(input_hashes)
    opened: dict[str, bytes] = {}
    parsed: dict[str, object] = {}
    matches: list[tuple[str, dict[str, object]]] = []
    for input_hash in dict.fromkeys(inputs):
        try:
            content = writer.evidence.read_verified(input_hash)
            value = parse_canonical(content)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            continue
        opened[input_hash] = content
        parsed[input_hash] = value
        if (
            isinstance(value, dict)
            and value.get("schema")
            == COST_AWARE_EXECUTION_CACHE_PROVENANCE_SCHEMA
        ):
            matches.append(
                (
                    input_hash,
                    validate_cost_aware_execution_pair_cache_provenance(
                        value,
                        scoped_plan=scoped_plan,
                    ),
                )
            )
    if len(matches) != 1:
        raise ValueError(
            "cost-aware consumer requires one exact cache provenance input"
        )
    provenance_hash, provenance = matches[0]
    cache_hash = str(provenance["cache_sha256"])
    producer_trace_hash = str(provenance["producer_trace_sha256"])
    for name, value in (
        ("cache", cache_hash),
        ("cache provenance", provenance_hash),
        ("producer trace", producer_trace_hash),
    ):
        if inputs.count(value) != 1:
            raise ValueError(f"cost-aware {name} must be exactly one Job input")
    cache_content = opened.get(cache_hash)
    producer_trace_content = opened.get(producer_trace_hash)
    producer_trace_value = parsed.get(producer_trace_hash)
    if cache_content is None or producer_trace_content is None:
        raise ValueError("cost-aware producer evidence input is unavailable")
    cache_value = parsed.get(cache_hash)
    if not isinstance(cache_value, Mapping) or canonical_bytes(cache_value) != cache_content:
        raise ValueError("cost-aware neutral cache is not canonical")
    cache = cost_aware_execution_pair_cache(
        scoped_plan=scoped_plan,
        neutral_trace=cache_value,
        produced=False,
    )
    if cache.sha256 != cache_hash:
        raise ValueError("cost-aware cache hash differs from opened bytes")
    if (
        not isinstance(producer_trace_value, Mapping)
        or canonical_bytes(producer_trace_value) != producer_trace_content
    ):
        raise ValueError("cost-aware producer subject trace is not canonical")
    producer_trace = validate_cost_aware_execution_subject_trace(
        producer_trace_value,
        definition=scoped_plan.definition,
    )
    neutral = extract_cost_aware_execution_pair_trace(
        producer_trace,
        definition=scoped_plan.definition,
    )
    if sha256(canonical_bytes(neutral)).hexdigest() != cache_hash:
        raise ValueError("cost-aware producer trace differs from its neutral cache")
    producer_payload = provenance["producer_execution"]
    execution = RunningJobExecution.from_mapping(
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
    producer_plan = build_cost_aware_execution_pair_job_plan_from_definition(
        mission_id=scoped_plan.mission_id,
        study_id=scoped_plan.study_id,
        executable_id=scoped_plan.producer_executable_id,
        definition=scoped_plan.definition,
        historical_context=scoped_plan.historical_context,
        artifact_namespace=scoped_plan.artifact_namespace,
    )
    writer.verify_reproducible_cache_producer(
        execution,
        cache_output_name=scoped_plan.cache_output_name,
        cache_hash=cache.sha256,
        expected_callable_identity=_ascii(
            "cost-aware expected callable identity",
            expected_callable_identity,
        ),
        expected_evidence_subject={
            "kind": "Executable",
            "id": scoped_plan.producer_executable_id,
        },
        expected_output_classes=producer_plan.expected_output_classes(),
        expected_study_id=scoped_plan.study_id,
        manifest_output_name=producer_plan.cache_provenance_output_name,
        manifest_hash=provenance_hash,
    )
    target = Path(repository_root).resolve() / scoped_plan.cache_output_name
    if target.exists() or materialize_missing:
        materialize_cost_aware_execution_pair_cache(
            repository_root,
            scoped_plan=scoped_plan,
            content=cache.content,
        )
    return cache, provenance_hash, producer_trace_hash, provenance


def build_cost_aware_execution_pair_measurement(
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    job_id: str,
    job_hash: str,
    calculation: Mapping[str, Any],
    trace_sha256: str,
    calculation_sha256: str,
) -> dict[str, object]:
    metrics = calculation.get("metrics")
    statistics = calculation.get("statistics")
    if not isinstance(metrics, Mapping) or not isinstance(statistics, Mapping):
        raise ValueError("cost-aware calculation metrics are invalid")
    if (
        calculation.get("mission_id") != scoped_plan.mission_id
        or calculation.get("executable_id") != scoped_plan.executable_id
        or calculation.get("job_id") != job_id
        or calculation.get("job_hash") != job_hash
        or calculation.get("protocol_id") != scoped_plan.definition.protocol_id
        or calculation.get("protocol_definition")
        != scoped_plan.definition.manifest()
        or scoped_plan.plan.get("protocol_definition")
        != scoped_plan.definition.manifest()
    ):
        raise ValueError("cost-aware calculation belongs to another Job")
    requirements = parse_proof_requirements(
        scoped_plan.plan["proof_requirements"],
        evidence_modes=COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES,
    )
    registrations = cost_aware_execution_multiplicity_registrations(
        scoped_plan.definition,
        scoped_plan.executable_id,
    )
    assessments = statistics.get("multiplicity_assessments")
    if not isinstance(assessments, Mapping):
        raise ValueError("cost-aware multiplicity assessments are absent")
    rows: list[dict[str, object]] = []
    for registration in registrations:
        criterion_id = str(registration["criterion_id"])
        row = assessments.get(criterion_id)
        if not isinstance(row, Mapping):
            raise ValueError("cost-aware multiplicity assessment is absent")
        expected_prefix = dict(registration)
        if any(row.get(name) != value for name, value in expected_prefix.items()):
            raise ValueError("cost-aware multiplicity registration drifted")
        raw = row.get("raw_pvalue_ppm")
        adjusted = row.get("adjusted_pvalue_ppm")
        if (
            set(row) != {*expected_prefix, "raw_pvalue_ppm", "adjusted_pvalue_ppm"}
            or type(raw) is not int
            or type(adjusted) is not int
            or adjusted < raw
        ):
            raise ValueError("cost-aware multiplicity result is invalid")
        rows.append(dict(row))
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(COST_AWARE_EXECUTION_REPLAY_EVIDENCE_MODES),
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("cost-aware measurement Job hash", job_hash),
        "job_id": _ascii("cost-aware measurement Job", job_id),
        "metrics": metrics,
        "mission_id": scoped_plan.mission_id,
        "multiplicity": rows,
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    scoped_plan.output_names["trace"]: _digest(
                        "cost-aware trace hash",
                        trace_sha256,
                    ),
                    scoped_plan.output_names["calculation"]: _digest(
                        "cost-aware calculation hash",
                        calculation_sha256,
                    ),
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_cost_aware_execution_pair_result(
    *,
    scoped_plan: CostAwareExecutionPairJobPlan,
    job_id: str,
    job_hash: str,
    measurement_sha256: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("cost-aware result Job hash", job_hash),
        "job_id": _ascii("cost-aware result Job", job_id),
        "mission_id": scoped_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": _digest(
                    "cost-aware measurement hash",
                    measurement_sha256,
                ),
            }
            for claim_id in COST_AWARE_EXECUTION_REPLAY_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


def materialize_cost_aware_execution_pair_evidence(
    *,
    writer: CostAwareExecutionJobAuthority,
    scoped_plan: CostAwareExecutionPairJobPlan,
    execution: RunningJobExecution,
    neutral_trace: Mapping[str, Any],
) -> tuple[dict[str, str], str]:
    pair = validate_cost_aware_execution_pair_trace(
        neutral_trace,
        definition=scoped_plan.definition,
    )
    names = scoped_plan.output_names
    subject_trace = bind_cost_aware_execution_subject_trace(
        pair_trace=pair,
        definition=scoped_plan.definition,
        mission_id=scoped_plan.mission_id,
        executable_id=scoped_plan.executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
    )
    trace_hash = writer.evidence.finalize(
        canonical_bytes(subject_trace)
    ).sha256
    calculation = build_cost_aware_execution_pair_calculation(
        trace=subject_trace,
        definition=scoped_plan.definition,
        trace_output_name=names["trace"],
        trace_hash=trace_hash,
    )
    validate_cost_aware_execution_trace_calculation(
        trace=subject_trace,
        calculation=calculation,
        definition=scoped_plan.definition,
    )
    calculation_hash = writer.evidence.finalize(
        canonical_bytes(calculation)
    ).sha256
    measurement = build_cost_aware_execution_pair_measurement(
        scoped_plan=scoped_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        calculation=calculation,
        trace_sha256=trace_hash,
        calculation_sha256=calculation_hash,
    )
    measurement_hash = writer.evidence.finalize(
        canonical_bytes(measurement)
    ).sha256
    result = build_cost_aware_execution_pair_result(
        scoped_plan=scoped_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_sha256=measurement_hash,
    )
    outputs = {
        names["calculation"]: calculation_hash,
        names["measurement"]: measurement_hash,
        names["plan"]: writer.evidence.finalize(
            canonical_bytes(scoped_plan.plan)
        ).sha256,
        names["result"]: writer.evidence.finalize(
            canonical_bytes(result)
        ).sha256,
        names["trace"]: trace_hash,
    }
    adjudication = adjudicate_validation_measurement_v2(
        scoped_plan.plan,
        measurement,
    )
    return outputs, adjudication.state


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairJobPacket:
    adjudication_state: str
    output_manifest: tuple[tuple[str, str], ...]

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


__all__ = [
    "ARTIFACT_NAMESPACE",
    "COST_AWARE_EXECUTION_CACHE_PROVENANCE_SCHEMA",
    "CostAwareExecutionPairCache",
    "CostAwareExecutionPairJobPacket",
    "CostAwareExecutionPairJobPlan",
    "build_cost_aware_execution_pair_cache_provenance",
    "build_cost_aware_execution_pair_job_plan",
    "build_cost_aware_execution_pair_job_plan_from_definition",
    "build_cost_aware_execution_pair_measurement",
    "build_cost_aware_execution_pair_result",
    "cost_aware_execution_pair_cache",
    "cost_aware_execution_pair_cache_output_name",
    "cost_aware_execution_pair_cache_provenance_output_name",
    "cost_aware_execution_pair_job_implementation_sha256",
    "cost_aware_execution_pair_output_names",
    "materialize_cost_aware_execution_pair_cache",
    "materialize_cost_aware_execution_pair_evidence",
    "validate_cost_aware_execution_pair_cache_provenance",
    "verify_cost_aware_execution_pair_cache_producer",
]
