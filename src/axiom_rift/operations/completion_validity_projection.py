"""Read-only projection of completion-scoped scientific invalidations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.historical_scientific_validity import (
    AUTHORITY_DELTA_ZERO,
    HistoricalScientificValidityError,
    HistoricalScientificValidityInvalidation,
    JobBindingKind,
    historical_scientific_validity_invalidation_from_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class CompletionValidityProjectionError(RuntimeError):
    """The current completion-validity head is malformed or misbound."""


@dataclass(frozen=True, slots=True)
class CompletionValidityHead:
    """Authenticated current invalidation with stable Journal provenance."""

    invalidation: HistoricalScientificValidityInvalidation
    invalidation_record_id: str
    validity_stream_sequence: int
    authority_event_id: str
    authority_sequence: int
    authority_offset: int

    @property
    def completion_record_id(self) -> str:
        return self.invalidation.completion_record_id

    @property
    def executable_id(self) -> str:
        return self.invalidation.executable_id

    @property
    def reason(self) -> str:
        return self.invalidation.reason.value

    @property
    def affected_criterion_ids(self) -> tuple[str, ...]:
        return self.invalidation.affected_criterion_ids


def completion_validity_stream(completion_record_id: str) -> str:
    """Return the one append-only validity stream for an exact completion."""

    if (
        type(completion_record_id) is not str
        or len(completion_record_id) != 64
        or any(char not in "0123456789abcdef" for char in completion_record_id)
    ):
        raise ValueError("completion record id must be a lowercase SHA-256 digest")
    return f"completion-scientific-validity:{completion_record_id}"


def completion_validity_invalidation_record(
    invalidation: HistoricalScientificValidityInvalidation,
    *,
    sequence: int,
) -> IndexRecord:
    """Build the exact durable projection member for Writer integration."""

    if not isinstance(invalidation, HistoricalScientificValidityInvalidation):
        raise TypeError("completion invalidation is not typed")
    if sequence != 1:
        raise ValueError("completion validity invalidation must be stream sequence one")
    return IndexRecord(
        kind="historical-scientific-validity-invalidation",
        record_id=invalidation.identity,
        subject=f"JobCompletion:{invalidation.completion_record_id}",
        status="invalidated",
        fingerprint=invalidation.identity.removeprefix(
            "historical-scientific-validity-invalidation:"
        ),
        payload=invalidation.to_identity_payload(),
        event_stream=completion_validity_stream(invalidation.completion_record_id),
        event_sequence=sequence,
    )


def _component_implementation_hashes(trial: IndexRecord) -> tuple[str, ...]:
    executable = trial.payload.get("executable")
    manifests = (
        None
        if not isinstance(executable, Mapping)
        else executable.get("component_manifests")
    )
    if not isinstance(manifests, list) or not manifests:
        raise CompletionValidityProjectionError(
            "completion validity trial lacks component manifests"
        )
    resolved: set[str] = set()
    for manifest in manifests:
        implementation = (
            None
            if not isinstance(manifest, Mapping)
            else manifest.get("implementation")
        )
        if (
            type(implementation) is not str
            or "@sha256:" not in implementation
            or not implementation.isascii()
        ):
            raise CompletionValidityProjectionError(
                "completion validity component implementation is malformed"
            )
        digest = implementation.rsplit("@sha256:", 1)[1]
        if len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise CompletionValidityProjectionError(
                "completion validity component digest is malformed"
            )
        resolved.add(digest)
    return tuple(sorted(resolved))


def _completion_claim_ids(scientific: Mapping[str, Any]) -> set[str]:
    direct = scientific.get("claims")
    claims: set[str] = set()
    if isinstance(direct, list):
        for item in direct:
            if type(item) is str:
                claims.add(item)
            elif isinstance(item, Mapping) and type(item.get("claim_id")) is str:
                claims.add(item["claim_id"])
            else:
                raise CompletionValidityProjectionError(
                    "completion scientific claims are malformed"
                )
    adjudication = scientific.get("adjudication")
    adjudicated = (
        None
        if not isinstance(adjudication, Mapping)
        else adjudication.get("claims")
    )
    if isinstance(adjudicated, list):
        for item in adjudicated:
            if not isinstance(item, Mapping) or type(item.get("claim_id")) is not str:
                raise CompletionValidityProjectionError(
                    "completion adjudication claims are malformed"
                )
            claims.add(item["claim_id"])
    if not claims:
        raise CompletionValidityProjectionError(
            "completion validity lacks exact scientific claims"
        )
    return claims


def _completion_criterion_ids(scientific: Mapping[str, Any]) -> set[str] | None:
    adjudication = scientific.get("adjudication")
    criteria = (
        None
        if not isinstance(adjudication, Mapping)
        else adjudication.get("criteria")
    )
    if criteria is None:
        return None
    if not isinstance(criteria, list) or not criteria:
        raise CompletionValidityProjectionError(
            "completion adjudication criteria are malformed"
        )
    resolved: set[str] = set()
    for item in criteria:
        criterion_id = (
            None if not isinstance(item, Mapping) else item.get("criterion_id")
        )
        if type(criterion_id) is not str or not criterion_id.isascii():
            raise CompletionValidityProjectionError(
                "completion adjudication criterion is malformed"
            )
        resolved.add(criterion_id)
    return resolved


def validate_completion_validity_invalidation_binding(
    index: LocalIndex | LocalIndexView,
    invalidation: HistoricalScientificValidityInvalidation,
) -> None:
    """Validate semantic bindings without requiring a committed stream head."""

    if not isinstance(index, (LocalIndex, LocalIndexView)) or not isinstance(
        invalidation,
        HistoricalScientificValidityInvalidation,
    ):
        raise CompletionValidityProjectionError(
            "completion validity binding request is untyped"
        )
    completion = index.get("job-completed", invalidation.completion_record_id)
    if completion is None or completion.record_id != invalidation.completion_record_id:
        raise CompletionValidityProjectionError(
            "completion validity lost its exact completion"
        )
    scientific = completion.payload.get("scientific")
    outputs = completion.payload.get("outputs")
    measurement_hashes = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("measurement_artifact_hashes")
    )
    if (
        not isinstance(scientific, Mapping)
        or scientific.get("executable_id") != invalidation.executable_id
        or scientific.get("validation_plan_hash")
        != invalidation.validation_plan_hash
        or scientific.get("result_manifest_hash") != invalidation.result_manifest_hash
        or not isinstance(measurement_hashes, list)
        or invalidation.measurement_artifact_hash not in measurement_hashes
        or not isinstance(outputs, Mapping)
        or not {
            invalidation.validation_plan_hash,
            invalidation.measurement_artifact_hash,
            invalidation.result_manifest_hash,
        }.issubset(set(outputs.values()))
    ):
        raise CompletionValidityProjectionError(
            "completion validity scientific artifact binding is not exact"
        )
    if completion.payload.get("job_id") != invalidation.job_id:
        raise CompletionValidityProjectionError(
            "completion validity targets another Job"
        )

    declaration = index.get("job-declared", invalidation.job_id)
    spec = None if declaration is None else declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    if (
        declaration is None
        or declaration.payload.get("study_id") != invalidation.study_id
        or not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or subject.get("id") != invalidation.executable_id
    ):
        raise CompletionValidityProjectionError(
            "completion validity Job declaration binding is not exact"
        )
    if invalidation.job_binding_kind is JobBindingKind.DECLARATION:
        if invalidation.job_binding_record_id != declaration.record_id:
            raise CompletionValidityProjectionError(
                "completion validity declaration reference is not exact"
            )
    else:
        start = index.get("job-started", invalidation.job_binding_record_id)
        if (
            start is None
            or completion.payload.get("start_record_id") != start.record_id
            or start.subject != f"Job:{invalidation.job_id}"
        ):
            raise CompletionValidityProjectionError(
                "completion validity Job start binding is not exact"
            )

    study = index.get("study-open", invalidation.study_id)
    close = index.get("study-close", invalidation.study_close_record_id)
    if (
        study is None
        or close is None
        or study.payload.get("mission_id") != declaration.payload.get("mission_id")
        or close.subject != f"Study:{invalidation.study_id}"
    ):
        raise CompletionValidityProjectionError(
            "completion validity Study or close binding is not exact"
        )

    trial = index.get("trial", invalidation.executable_id)
    executable = None if trial is None else trial.payload.get("executable")
    if (
        trial is None
        or trial.payload.get("mission_id") != declaration.payload.get("mission_id")
        or not isinstance(executable, Mapping)
        or executable.get("clock_contract") != invalidation.clock_contract
        or executable.get("cost_contract") != invalidation.cost_contract
        or _component_implementation_hashes(trial)
        != invalidation.component_implementation_hashes
    ):
        raise CompletionValidityProjectionError(
            "completion validity Executable implementation or clock-cost binding is not exact"
        )
    declared_implementations = declaration.payload.get(
        "component_implementation_hashes"
    )
    if declared_implementations is not None and (
        not isinstance(declared_implementations, list)
        or tuple(sorted(set(declared_implementations)))
        != invalidation.component_implementation_hashes
    ):
        raise CompletionValidityProjectionError(
            "completion validity disagrees with declared component implementations"
        )

    modes = scientific.get("executed_evidence_modes")
    if (
        not isinstance(modes, list)
        or not set(invalidation.affected_evidence_modes).issubset(set(modes))
        or not set(invalidation.affected_claim_ids).issubset(
            _completion_claim_ids(scientific)
        )
    ):
        raise CompletionValidityProjectionError(
            "completion validity affected claim or mode scope is not exact"
        )
    criteria = _completion_criterion_ids(scientific)
    if criteria is not None and not set(
        invalidation.affected_criterion_ids
    ).issubset(criteria):
        raise CompletionValidityProjectionError(
            "completion validity affected criterion scope is not exact"
        )


def _require_writer_authority(
    index: LocalIndex | LocalIndexView,
    *,
    record: IndexRecord,
    invalidation: HistoricalScientificValidityInvalidation,
) -> None:
    try:
        _event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {"historical_scientific_validity_invalidations_recorded"}
            ),
        )
    except RecordedTransitionAuthorityError as exc:
        raise CompletionValidityProjectionError(
            "completion validity lacks same-event Writer authority"
        ) from exc
    inventory = result.get("invalidations")
    authority_delta = result.get("authority_delta")
    if (
        set(result) != {"authority_delta", "invalidations"}
        or not isinstance(authority_delta, Mapping)
        or set(authority_delta) != set(AUTHORITY_DELTA_ZERO)
        or any(
            type(authority_delta[name]) is not int
            or authority_delta[name] != 0
            for name in authority_delta
        )
        or not isinstance(inventory, list)
        or not inventory
    ):
        raise CompletionValidityProjectionError(
            "completion validity Writer result is malformed"
        )
    normalized: list[tuple[str, str]] = []
    for item in inventory:
        if not isinstance(item, Mapping) or set(item) != {
            "completion_record_id",
            "invalidation_record_id",
        }:
            raise CompletionValidityProjectionError(
                "completion validity Writer inventory is malformed"
            )
        completion_id = item.get("completion_record_id")
        invalidation_id = item.get("invalidation_record_id")
        if type(completion_id) is not str or type(invalidation_id) is not str:
            raise CompletionValidityProjectionError(
                "completion validity Writer inventory is untyped"
            )
        normalized.append((completion_id, invalidation_id))
    if (
        normalized != sorted(normalized)
        or len(normalized) != len(set(normalized))
        or (
            invalidation.completion_record_id,
            invalidation.identity,
        )
        not in normalized
    ):
        raise CompletionValidityProjectionError(
            "completion validity Writer inventory lacks the exact head"
        )


def current_completion_validity_invalidation(
    index: LocalIndex | LocalIndexView,
    completion_record_id: str,
) -> CompletionValidityHead | None:
    """Return the valid current completion head, or fail closed on malformed state."""

    stream = completion_validity_stream(completion_record_id)
    head = index.event_head(stream)
    if head is None:
        return None
    record = index.get(head.record_kind, head.record_id)
    try:
        invalidation = historical_scientific_validity_invalidation_from_payload(
            {} if record is None else record.payload
        )
    except HistoricalScientificValidityError as exc:
        raise CompletionValidityProjectionError(
            "completion validity head payload is malformed"
        ) from exc
    if (
        record is None
        or head.sequence != 1
        or record.kind != "historical-scientific-validity-invalidation"
        or record.status != "invalidated"
        or record.record_id != invalidation.identity
        or record.fingerprint
        != invalidation.identity.removeprefix(
            "historical-scientific-validity-invalidation:"
        )
        or record.subject != f"JobCompletion:{completion_record_id}"
        or record.event_stream != stream
        or record.event_sequence != head.sequence
        or invalidation.completion_record_id != completion_record_id
        or type(record.authority_event_id) is not str
        or len(record.authority_event_id) != 64
        or any(
            char not in "0123456789abcdef" for char in record.authority_event_id
        )
        or type(record.authority_sequence) is not int
        or record.authority_sequence < 1
        or type(record.authority_offset) is not int
        or record.authority_offset < 0
    ):
        raise CompletionValidityProjectionError(
            "completion validity stream head is invalid"
        )
    _require_writer_authority(
        index,
        record=record,
        invalidation=invalidation,
    )
    validate_completion_validity_invalidation_binding(index, invalidation)
    return CompletionValidityHead(
        invalidation=invalidation,
        invalidation_record_id=invalidation.identity,
        validity_stream_sequence=head.sequence,
        authority_event_id=record.authority_event_id,
        authority_sequence=record.authority_sequence,
        authority_offset=record.authority_offset,
    )


# A short public alias is useful to replay and audit readers without creating a
# second semantic operation.
completion_validity_head = current_completion_validity_invalidation


__all__ = [
    "CompletionValidityHead",
    "CompletionValidityProjectionError",
    "completion_validity_head",
    "completion_validity_invalidation_record",
    "completion_validity_stream",
    "current_completion_validity_invalidation",
    "validate_completion_validity_invalidation_binding",
]
