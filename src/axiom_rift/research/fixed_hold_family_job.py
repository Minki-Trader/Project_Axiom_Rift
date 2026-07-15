"""Reusable Job envelope for exact fixed-hold replay families.

The family producer remains protocol-specific.  This module owns only the
shared prospective plan, exact concurrent-family registration, atomic proof
envelope, one-producer cache provenance, measurement, and result surfaces.
Durable payloads contain no callback or import path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.evidence_proofs import (
    CALCULATION_PROOF_KIND,
    FIXED_HOLD_FAMILY_TRACE_PROOF_KIND,
    build_proof_references,
    parse_proof_requirements,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_FAMILY_TRACE_SCHEMA,
    FIXED_HOLD_REPLAY_CLAIMS,
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldProtocolDefinition,
    bind_fixed_hold_family_trace,
    extract_fixed_hold_family_trace_from_subject,
    fixed_hold_subject_inference_families,
    fixed_hold_trace_implementation_sha256,
    validate_fixed_hold_family_trace,
)
from axiom_rift.research.fixed_hold_shared_trace import (
    build_fixed_hold_shared_trace_calculation,
    fixed_hold_shared_trace_implementation_sha256,
    validate_fixed_hold_shared_trace_calculation,
)
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
)
from axiom_rift.research.replay_coverage import (
    validated_recomputed_criterion_ids,
)
from axiom_rift.research.reproducible_cache import (
    publish_reproducible_cache,
    reproducible_cache_implementation_sha256,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
    adjudicate_validation_measurement_v2,
    build_validation_plan_v2,
    multiplicity_family_registration_hash,
)


class FixedHoldJobAuthority(Protocol):
    """Minimum evidence and producer-verification surface used by the engine."""

    evidence: Any

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


FIXED_HOLD_CACHE_PROVENANCE_SCHEMA = (
    "fixed_hold_family_cache_provenance.v1"
)
EVIDENCE_DEPTH = "discovery"
_THIS_FILE = Path(__file__).resolve()

_CACHE_PROVENANCE_FIELDS = {
    "cache_output_name",
    "cache_sha256",
    "definition_identity",
    "family_id",
    "mission_id",
    "producer_executable_id",
    "producer_execution",
    "producer_trace_output_name",
    "producer_trace_sha256",
    "protocol_id",
    "schema",
    "study_id",
}
_PRODUCER_EXECUTION_FIELDS = {
    "identity",
    "job_hash",
    "job_id",
    "job_permit_id",
    "start_record_id",
}


def fixed_hold_family_job_implementation_sha256() -> str:
    return sha256(
        _THIS_FILE.read_bytes()
        + bytes.fromhex(reproducible_cache_implementation_sha256())
    ).hexdigest()


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
    namespace = _ascii("fixed-hold artifact namespace", value)
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in namespace
    ):
        raise ValueError("fixed-hold artifact namespace is not path-safe")
    return namespace


def _input_digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    ):
        return text
    return sha256(text.encode("ascii")).hexdigest()


def fixed_hold_output_names(
    *,
    artifact_namespace: str,
    study_id: str,
    executable_id: str,
) -> dict[str, str]:
    namespace = _namespace(artifact_namespace)
    study = _ascii("fixed-hold study_id", study_id)
    executable = _ascii("fixed-hold executable_id", executable_id)
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


def fixed_hold_cache_output_name(
    *,
    artifact_namespace: str,
    definition: FixedHoldProtocolDefinition,
) -> str:
    namespace = _namespace(artifact_namespace)
    suffix = definition.identity.removeprefix("fixed-hold-definition:")[:16]
    return f"local/cache/historical-replay/{namespace}-{suffix}.json"


def fixed_hold_cache_provenance_output_name(
    *,
    artifact_namespace: str,
    study_id: str,
) -> str:
    return (
        f"scientific/{_ascii('fixed-hold study_id', study_id)}/"
        f"{_namespace(artifact_namespace)}-family-cache-provenance.json"
    )


def _proof_requirements(
    output_names: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    return tuple(
        sorted(
            (
                {
                    "artifact_schema": artifact_schema,
                    "evidence_mode": mode,
                    "output_name": output_names[output_key],
                    "proof_kind": proof_kind,
                }
                for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
                for proof_kind, artifact_schema, output_key in (
                    (
                        FIXED_HOLD_FAMILY_TRACE_PROOF_KIND,
                        FIXED_HOLD_FAMILY_TRACE_SCHEMA,
                        "trace",
                    ),
                    (
                        CALCULATION_PROOF_KIND,
                        SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
                        "calculation",
                    ),
                )
            ),
            key=lambda item: (
                item["evidence_mode"],
                item["proof_kind"],
                item["output_name"],
            ),
        )
    )


def fixed_hold_multiplicity_registrations(
    *,
    definition: FixedHoldProtocolDefinition,
    subject_executable_id: str,
) -> tuple[dict[str, object], ...]:
    families = fixed_hold_subject_inference_families(
        definition,
        subject_executable_id,
    )
    specifications = (
        (
            "D02-opposite-sign-uncertainty",
            families["paired_control_family"],
        ),
        (
            "E01-familywise-selection",
            families["selection_family"],
        ),
    )
    registrations: list[dict[str, object]] = []
    for criterion_id, family in specifications:
        family_id = str(family["family_id"])
        members = tuple(str(value) for value in family["ordered_member_ids"])
        member_id = str(family["member_id"])
        registrations.append(
            {
                "alpha_ppm": definition.alpha_ppm,
                "criterion_id": criterion_id,
                "family_id": family_id,
                "family_registration_hash": (
                    multiplicity_family_registration_hash(
                        family_id=family_id,
                        alpha_ppm=definition.alpha_ppm,
                        method=SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
                        ordered_member_ids=members,
                    )
                ),
                "family_size": len(members),
                "member_id": member_id,
                "method": SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
                "ordered_member_ids": list(members),
            }
        )
    return tuple(sorted(registrations, key=lambda item: item["criterion_id"]))


def build_fixed_hold_validation_plan(
    *,
    definition: FixedHoldProtocolDefinition,
    mission_id: str,
    executable_id: str,
    output_names: Mapping[str, str],
) -> dict[str, object]:
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": list(
            fixed_hold_multiplicity_registrations(
                definition=definition,
                subject_executable_id=executable_id,
            )
        ),
        "promotion_criterion_ids": [],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    return build_validation_plan_v2(
        mission_id=_ascii("fixed-hold mission_id", mission_id),
        executable_id=_ascii("fixed-hold executable_id", executable_id),
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=FIXED_HOLD_REPLAY_CLAIMS,
        evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        criteria=FIXED_HOLD_REPLAY_CRITERIA,
        adjudication_profile=profile,
        proof_requirements=_proof_requirements(output_names),
        candidate_eligible_on_pass=False,
        protocol_definition=definition.manifest(),
    )


@dataclass(frozen=True, slots=True)
class FixedHoldFamilyJobPlan:
    mission_id: str
    study_id: str
    executable_id: str
    artifact_namespace: str
    definition: FixedHoldProtocolDefinition
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
        return fixed_hold_cache_output_name(
            artifact_namespace=self.artifact_namespace,
            definition=self.definition,
        )

    @property
    def cache_provenance_output_name(self) -> str:
        return fixed_hold_cache_provenance_output_name(
            artifact_namespace=self.artifact_namespace,
            study_id=self.study_id,
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
                "fixed-hold cache, provenance, and trace hashes are inseparable"
            )
        values = {
            self.definition.dataset_sha256,
            self.definition.material_identity,
            self.definition.split_artifact_sha256,
            self.definition.identity.removeprefix("fixed-hold-definition:"),
            self.plan_hash,
            fixed_hold_family_job_implementation_sha256(),
            fixed_hold_shared_trace_implementation_sha256(),
            fixed_hold_trace_implementation_sha256(),
            selection_inference_implementation_sha256(),
            *dict(
                self.definition.producer_implementation_identities
            ).values(),
        }
        for index, value in enumerate(optional):
            if value is not None:
                values.add(_digest(f"fixed-hold cache input {index}", value))
        return tuple(
            sorted(
                _input_digest("fixed-hold Job input identity", value)
                for value in values
            )
        )

    def scientific_binding(self) -> dict[str, object]:
        return {
            "evidence_depth": EVIDENCE_DEPTH,
            "evidence_modes": list(FIXED_HOLD_REPLAY_EVIDENCE_MODES),
            "planned_claims": list(FIXED_HOLD_REPLAY_CLAIMS),
            "result_manifest_output": self.output_names["result"],
            "validation_plan_hash": self.plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }


def build_fixed_hold_family_job_plan(
    *,
    definition: FixedHoldProtocolDefinition,
    artifact_namespace: str,
    mission_id: str,
    study_id: str,
    executable_id: str,
) -> FixedHoldFamilyJobPlan:
    if executable_id not in definition.prospective_executable_ids:
        raise ValueError("fixed-hold Job subject is outside its exact family")
    names = fixed_hold_output_names(
        artifact_namespace=artifact_namespace,
        study_id=study_id,
        executable_id=executable_id,
    )
    plan = build_fixed_hold_validation_plan(
        definition=definition,
        mission_id=mission_id,
        executable_id=executable_id,
        output_names=names,
    )
    return FixedHoldFamilyJobPlan(
        mission_id=_ascii("fixed-hold mission_id", mission_id),
        study_id=_ascii("fixed-hold study_id", study_id),
        executable_id=_ascii("fixed-hold executable_id", executable_id),
        artifact_namespace=_namespace(artifact_namespace),
        definition=definition,
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )


@dataclass(frozen=True, slots=True)
class FixedHoldFamilyCache:
    content: bytes
    produced: bool
    sha256: str

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or type(self.produced) is not bool:
            raise ValueError("fixed-hold cache value is invalid")
        if _digest("fixed-hold cache hash", self.sha256) != sha256(
            self.content
        ).hexdigest():
            raise ValueError("fixed-hold cache content hash drifted")

    def trace(
        self,
        definition: FixedHoldProtocolDefinition,
    ) -> dict[str, object]:
        value = parse_canonical(self.content)
        if not isinstance(value, dict) or canonical_bytes(value) != self.content:
            raise ValueError("fixed-hold cache bytes are not canonical")
        return validate_fixed_hold_family_trace(
            value,
            definition=definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )


def materialize_fixed_hold_cache(
    repository_root: str | Path,
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    content: bytes,
) -> None:
    root = Path(repository_root).absolute()
    publish_reproducible_cache(
        repository_root=root,
        relative_path=scoped_plan.cache_output_name,
        content=content,
    )


def fixed_hold_family_cache(
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    neutral_trace: Mapping[str, Any],
    produced: bool,
) -> FixedHoldFamilyCache:
    normalized = validate_fixed_hold_family_trace(
        neutral_trace,
        definition=scoped_plan.definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    content = canonical_bytes(normalized)
    return FixedHoldFamilyCache(
        content=content,
        produced=produced,
        sha256=sha256(content).hexdigest(),
    )


def build_fixed_hold_cache_provenance(
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    execution: RunningJobExecution,
    cache_sha256: str,
    producer_trace_sha256: str,
) -> dict[str, object]:
    if not scoped_plan.produces_family_cache:
        raise ValueError("fixed-hold cache provenance requires the first member")
    value = {
        "cache_output_name": scoped_plan.cache_output_name,
        "cache_sha256": _digest("fixed-hold cache hash", cache_sha256),
        "definition_identity": scoped_plan.definition.identity,
        "family_id": scoped_plan.definition.family_id,
        "mission_id": scoped_plan.mission_id,
        "producer_executable_id": scoped_plan.executable_id,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "producer_trace_output_name": scoped_plan.output_names["trace"],
        "producer_trace_sha256": _digest(
            "fixed-hold producer trace hash",
            producer_trace_sha256,
        ),
        "protocol_id": scoped_plan.definition.protocol_id,
        "schema": FIXED_HOLD_CACHE_PROVENANCE_SCHEMA,
        "study_id": scoped_plan.study_id,
    }
    validate_fixed_hold_cache_provenance(value)
    canonical_bytes(value)
    return value


def validate_fixed_hold_cache_provenance(
    value: Mapping[str, Any],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _CACHE_PROVENANCE_FIELDS:
        raise ValueError("fixed-hold cache provenance schema is invalid")
    normalized = parse_canonical(canonical_bytes(value))
    if not isinstance(normalized, dict):
        raise ValueError("fixed-hold cache provenance is not an object")
    if normalized.get("schema") != FIXED_HOLD_CACHE_PROVENANCE_SCHEMA:
        raise ValueError("fixed-hold cache provenance version is invalid")
    for name in (
        "cache_output_name",
        "definition_identity",
        "family_id",
        "mission_id",
        "producer_executable_id",
        "producer_trace_output_name",
        "protocol_id",
        "study_id",
    ):
        _ascii(f"fixed-hold cache provenance {name}", normalized.get(name))
    _digest("fixed-hold cache hash", normalized.get("cache_sha256"))
    _digest(
        "fixed-hold producer trace hash",
        normalized.get("producer_trace_sha256"),
    )
    producer = normalized.get("producer_execution")
    if not isinstance(producer, dict) or set(producer) != (
        _PRODUCER_EXECUTION_FIELDS
    ):
        raise ValueError("fixed-hold cache producer execution is invalid")
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
        raise ValueError("fixed-hold cache producer identity drifted")
    return normalized


def verify_fixed_hold_cache_producer(
    writer: FixedHoldJobAuthority,
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    repository_root: str | Path,
    input_hashes: Sequence[str],
    expected_callable_identity: str,
    materialize_missing: bool = True,
) -> tuple[FixedHoldFamilyCache, str, str, dict[str, object]]:
    if scoped_plan.produces_family_cache:
        raise ValueError("fixed-hold producer cannot consume its own cache")
    inputs = tuple(input_hashes)
    matches: list[tuple[str, dict[str, object]]] = []
    for input_hash in dict.fromkeys(inputs):
        try:
            value = parse_canonical(writer.evidence.read_verified(input_hash))
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == FIXED_HOLD_CACHE_PROVENANCE_SCHEMA
        ):
            matches.append(
                (input_hash, validate_fixed_hold_cache_provenance(value))
            )
    if len(matches) != 1:
        raise ValueError(
            "fixed-hold consumer requires one exact cache provenance input"
        )
    provenance_hash, provenance = matches[0]
    producer_trace_hash = str(provenance["producer_trace_sha256"])
    cache_hash = str(provenance["cache_sha256"])
    for name, value in (
        ("cache", cache_hash),
        ("cache provenance", provenance_hash),
        ("producer trace", producer_trace_hash),
    ):
        if inputs.count(value) != 1:
            raise ValueError(
                f"fixed-hold {name} hash must be exactly one Job input"
            )
    producer_id = scoped_plan.producer_executable_id
    producer_plan = build_fixed_hold_family_job_plan(
        definition=scoped_plan.definition,
        artifact_namespace=scoped_plan.artifact_namespace,
        mission_id=scoped_plan.mission_id,
        study_id=scoped_plan.study_id,
        executable_id=producer_id,
    )
    if (
        provenance.get("cache_output_name") != scoped_plan.cache_output_name
        or provenance.get("definition_identity")
        != scoped_plan.definition.identity
        or provenance.get("family_id") != scoped_plan.definition.family_id
        or provenance.get("mission_id") != scoped_plan.mission_id
        or provenance.get("study_id") != scoped_plan.study_id
        or provenance.get("protocol_id")
        != scoped_plan.definition.protocol_id
        or provenance.get("producer_executable_id") != producer_id
        or provenance.get("producer_trace_output_name")
        != producer_plan.output_names["trace"]
    ):
        raise ValueError("fixed-hold cache provenance is out of scope")
    trace_content = writer.evidence.read_verified(producer_trace_hash)
    trace = parse_canonical(trace_content)
    if not isinstance(trace, dict) or canonical_bytes(trace) != trace_content:
        raise ValueError("fixed-hold producer trace is not canonical")
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
    if trace.get("schema") == FIXED_HOLD_FAMILY_TRACE_SCHEMA:
        neutral = validate_fixed_hold_family_trace(
            trace,
            definition=scoped_plan.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )
        if producer_trace_hash != cache_hash:
            raise ValueError(
                "shared fixed-hold producer trace must be the exact cache"
            )
    else:
        # Historical Jobs emitted a subject-bound copy of the full family
        # trace.  Preserve that exact validation route for immutable evidence.
        neutral = extract_fixed_hold_family_trace_from_subject(
            trace,
            definition=scoped_plan.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )
        if (
            trace.get("mission_id") != scoped_plan.mission_id
            or trace.get("subject_executable_id") != producer_id
            or trace.get("job_id") != execution.job_id
            or trace.get("job_hash") != execution.job_hash
        ):
            raise ValueError("fixed-hold producer trace execution drifted")
    cache = fixed_hold_family_cache(
        scoped_plan=scoped_plan,
        neutral_trace=neutral,
        produced=False,
    )
    if cache.sha256 != cache_hash:
        raise ValueError("fixed-hold cache differs from its producer trace")
    writer.verify_reproducible_cache_producer(
        execution,
        cache_output_name=scoped_plan.cache_output_name,
        cache_hash=cache.sha256,
        expected_callable_identity=_ascii(
            "fixed-hold expected callable identity",
            expected_callable_identity,
        ),
        expected_evidence_subject={"kind": "Executable", "id": producer_id},
        expected_output_classes=producer_plan.expected_output_classes(),
        expected_study_id=scoped_plan.study_id,
        manifest_output_name=producer_plan.cache_provenance_output_name,
        manifest_hash=provenance_hash,
    )
    target = Path(repository_root).resolve() / scoped_plan.cache_output_name
    if target.exists() or materialize_missing:
        materialize_fixed_hold_cache(
            repository_root,
            scoped_plan=scoped_plan,
            content=cache.content,
        )
    return cache, provenance_hash, producer_trace_hash, provenance


def _hypothesis_statistics(
    statistical_manifest: Mapping[str, Any],
    hypothesis_id: str,
) -> Mapping[str, Any]:
    hypotheses = statistical_manifest.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("fixed-hold inference hypotheses are invalid")
    matches = [
        item
        for item in hypotheses
        if isinstance(item, Mapping)
        and item.get("hypothesis_id") == hypothesis_id
    ]
    if len(matches) != 1:
        raise ValueError("fixed-hold inference subject is ambiguous")
    return matches[0]


def build_fixed_hold_measurement(
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    job_id: str,
    job_hash: str,
    calculation: Mapping[str, Any],
    trace_sha256: str,
    calculation_sha256: str,
) -> dict[str, object]:
    metrics = calculation.get("metrics")
    statistics = calculation.get("statistics")
    if not isinstance(metrics, Mapping) or not isinstance(statistics, Mapping):
        raise ValueError("fixed-hold calculation metrics are invalid")
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
        raise ValueError("fixed-hold calculation belongs to another Job")
    requirements = parse_proof_requirements(
        scoped_plan.plan["proof_requirements"],
        evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    )
    registrations = fixed_hold_multiplicity_registrations(
        definition=scoped_plan.definition,
        subject_executable_id=scoped_plan.executable_id,
    )
    result_rows: list[dict[str, object]] = []
    for registration in registrations:
        criterion_id = str(registration["criterion_id"])
        if criterion_id == "D02-opposite-sign-uncertainty":
            manifest = statistics.get("paired_control_family")
            adjusted = metrics["registered_control_contrast"][
                "opposite_sign_pvalue_upper_ppm"
            ]
        else:
            manifest = statistics.get("selection_family")
            adjusted = metrics["selection_aware_signal_evidence"][
                "selection_aware_pvalue_ppm"
            ]
        if not isinstance(manifest, Mapping):
            raise ValueError("fixed-hold inference manifest is invalid")
        hypothesis = _hypothesis_statistics(
            manifest,
            str(registration["member_id"]),
        )
        raw = hypothesis.get("raw")
        familywise = hypothesis.get("familywise")
        if not isinstance(raw, Mapping) or not isinstance(familywise, Mapping):
            raise ValueError("fixed-hold inference p-values are invalid")
        synchronized = familywise.get("synchronized_max")
        if not isinstance(synchronized, Mapping):
            raise ValueError("fixed-hold synchronized inference is absent")
        raw_pvalue = raw.get("monte_carlo_upper_pvalue_ppm")
        adjusted_pvalue = synchronized.get(
            "monte_carlo_upper_pvalue_ppm"
        )
        if (
            type(raw_pvalue) is not int
            or type(adjusted_pvalue) is not int
            or adjusted_pvalue != adjusted
        ):
            raise ValueError("fixed-hold inference metric binding drifted")
        result_rows.append(
            {
                **registration,
                "adjusted_pvalue_ppm": adjusted_pvalue,
                "raw_pvalue_ppm": raw_pvalue,
            }
        )
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(FIXED_HOLD_REPLAY_EVIDENCE_MODES),
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("fixed-hold measurement Job hash", job_hash),
        "job_id": _ascii("fixed-hold measurement Job", job_id),
        "metrics": metrics,
        "mission_id": scoped_plan.mission_id,
        "multiplicity": result_rows,
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    scoped_plan.output_names["trace"]: _digest(
                        "fixed-hold trace hash",
                        trace_sha256,
                    ),
                    scoped_plan.output_names["calculation"]: _digest(
                        "fixed-hold calculation hash",
                        calculation_sha256,
                    ),
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_fixed_hold_result(
    *,
    scoped_plan: FixedHoldFamilyJobPlan,
    job_id: str,
    job_hash: str,
    measurement_sha256: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": scoped_plan.executable_id,
        "job_hash": _digest("fixed-hold result Job hash", job_hash),
        "job_id": _ascii("fixed-hold result Job", job_id),
        "mission_id": scoped_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": _digest(
                    "fixed-hold measurement hash",
                    measurement_sha256,
                ),
            }
            for claim_id in FIXED_HOLD_REPLAY_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


def validated_fixed_hold_recomputed_criterion_ids(
    facts: Mapping[str, object],
) -> tuple[str, ...]:
    """Prove exact fixed-hold criterion coverage without requiring a pass."""

    return validated_recomputed_criterion_ids(
        facts,
        expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        expected_criteria=FIXED_HOLD_REPLAY_CRITERIA,
        context="historical fixed-hold replay",
    )


def materialize_fixed_hold_evidence(
    *,
    writer: FixedHoldJobAuthority,
    scoped_plan: FixedHoldFamilyJobPlan,
    execution: RunningJobExecution,
    neutral_trace: Mapping[str, Any],
    shared_trace_sha256: str,
) -> tuple[dict[str, str], str]:
    trace = validate_fixed_hold_family_trace(
        neutral_trace,
        definition=scoped_plan.definition,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
    )
    names = scoped_plan.output_names
    trace_hash = writer.evidence.finalize(canonical_bytes(trace)).sha256
    if trace_hash != _digest(
        "shared fixed-hold cache trace hash",
        shared_trace_sha256,
    ):
        raise ValueError("shared fixed-hold trace differs from its family cache")
    calculation = build_fixed_hold_shared_trace_calculation(
        trace=trace,
        definition=scoped_plan.definition,
        mission_id=scoped_plan.mission_id,
        executable_id=scoped_plan.executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        trace_output_name=names["trace"],
        trace_hash=trace_hash,
    )
    calculation_hash = writer.evidence.finalize(
        canonical_bytes(calculation)
    ).sha256
    measurement = build_fixed_hold_measurement(
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
    result = build_fixed_hold_result(
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
class FixedHoldFamilyJobPacket:
    adjudication_state: str
    output_manifest: tuple[tuple[str, str], ...]

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


__all__ = [
    "EVIDENCE_DEPTH",
    "FIXED_HOLD_CACHE_PROVENANCE_SCHEMA",
    "FixedHoldFamilyCache",
    "FixedHoldFamilyJobPacket",
    "FixedHoldFamilyJobPlan",
    "build_fixed_hold_cache_provenance",
    "build_fixed_hold_family_job_plan",
    "build_fixed_hold_measurement",
    "build_fixed_hold_result",
    "build_fixed_hold_shared_trace_calculation",
    "build_fixed_hold_validation_plan",
    "fixed_hold_cache_output_name",
    "fixed_hold_cache_provenance_output_name",
    "fixed_hold_family_cache",
    "fixed_hold_family_job_implementation_sha256",
    "fixed_hold_multiplicity_registrations",
    "fixed_hold_output_names",
    "materialize_fixed_hold_cache",
    "materialize_fixed_hold_evidence",
    "validate_fixed_hold_cache_provenance",
    "validate_fixed_hold_shared_trace_calculation",
    "validated_fixed_hold_recomputed_criterion_ids",
    "verify_fixed_hold_cache_producer",
]
