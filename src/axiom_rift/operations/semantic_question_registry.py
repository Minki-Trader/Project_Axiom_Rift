"""Durable semantic-question projection and scientific-work lineage checks.

Question identity is deliberately narrower than evidence authority.  An exact
question core groups declared estimands, while Study, Batch, Job, and
Executable records remain the only authority for what was actually run and
what scientific verdict was earned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.semantic_question import (
    SEMANTIC_QUESTION_STUDY_BINDING_SCHEMA,
    SemanticQuestionCore,
    SemanticQuestionEquivalenceProposal,
    SemanticQuestionError,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
    semantic_question_study_binding_id,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID = "semantic-question-registry-v1"
SEMANTIC_QUESTION_REGISTRY_ACTIVATION_SCHEMA = (
    "semantic_question_registry_activation.v1"
)
SEMANTIC_QUESTION_EQUIVALENCE_RECORD_SCHEMA = (
    "semantic_question_equivalence_record.v1"
)
SEMANTIC_QUESTION_LINEAGE_RECORD_SCHEMA = (
    "semantic_question_lineage_record.v1"
)

_STUDY_OUTCOMES = (
    "supported",
    "not_supported",
    "not_evaluable",
    "evidence_gap",
    "pruned",
    "preserved",
)
_DIAGNOSIS_STATUSES = (
    "absent_information",
    "target_mismatch",
    "model_capacity",
    "calibration_selection",
    "entry_policy",
    "lifecycle_risk",
    "execution_cost",
    "stability_concentration",
    "supported_requires_confirmation",
    "not_identifiable",
    "engineering_gap",
)
_BATCH_OUTCOMES = (
    "completed",
    "budget_exhausted",
    "stopped_early",
    "not_evaluable",
    "engineering_failure",
)
_JOB_OUTCOMES = ("success", "failed", "not_evaluable")
_BASIS_KINDS = frozenset(
    {
        "batch-close",
        "batch-open",
        "job-completed",
        "job-declared",
        "study-close",
        "study-diagnosis",
        "study-open",
        "trial",
    }
)


class SemanticQuestionRegistryError(ValueError):
    """A proposed semantic-question transition is not admissible."""


class SemanticQuestionRegistryIntegrityError(RuntimeError):
    """Durable semantic-question projection differs from its source records."""


def _record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: Mapping[str, object],
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=dict(payload),
        event_stream=event_stream,
        event_sequence=event_sequence,
    )


def _record_reference(record: IndexRecord) -> str:
    return f"{record.kind}:{record.record_id}"


def _study_id_from_open(record: IndexRecord) -> str:
    study_id = record.record_id
    if (
        record.kind != "study-open"
        or record.status != "open"
        or record.subject != f"Study:{study_id}"
    ):
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question source is not an exact Study-open record"
        )
    return study_id


def _core_from_study_open(record: IndexRecord) -> SemanticQuestionCore:
    study_id = _study_id_from_open(record)
    question = record.payload.get("question")
    if not isinstance(question, Mapping):
        raise SemanticQuestionRegistryIntegrityError(
            f"Study {study_id} lacks its declared question"
        )
    try:
        core = SemanticQuestionCore.from_question_manifest(question)
    except SemanticQuestionError as exc:
        raise SemanticQuestionRegistryIntegrityError(str(exc)) from exc
    question_hash = canonical_digest(
        domain="study-question",
        payload=dict(question),
    )
    if record.payload.get("question_hash") != question_hash:
        raise SemanticQuestionRegistryIntegrityError(
            f"Study {study_id} question hash differs from its declaration"
        )
    return core


def semantic_question_core_record(core: SemanticQuestionCore) -> IndexRecord:
    payload = {
        "semantic_question_core_id": core.identity,
        **core.to_identity_payload(),
    }
    return _record(
        kind="semantic-question-core",
        record_id=core.identity,
        subject=f"SemanticQuestion:{core.identity}",
        status="registered",
        fingerprint=core.identity,
        payload=payload,
    )


def semantic_question_study_record(study_open: IndexRecord) -> IndexRecord:
    study_id = _study_id_from_open(study_open)
    core = _core_from_study_open(study_open)
    payload = {
        "question_hash": study_open.payload["question_hash"],
        "schema": SEMANTIC_QUESTION_STUDY_BINDING_SCHEMA,
        "semantic_question_core_id": core.identity,
        "study_id": study_id,
        "study_open_fingerprint": study_open.fingerprint,
        "study_open_record_id": study_open.record_id,
    }
    return _record(
        kind="semantic-question-study",
        record_id=semantic_question_study_binding_id(
            semantic_question_core_id=core.identity,
            study_id=study_id,
        ),
        subject=f"Study:{study_id}",
        status="bound",
        fingerprint=core.identity,
        payload=payload,
    )


def semantic_question_records_for_study(
    study_open: IndexRecord,
) -> tuple[IndexRecord, IndexRecord]:
    core = _core_from_study_open(study_open)
    return (
        semantic_question_core_record(core),
        semantic_question_study_record(study_open),
    )


def backfill_semantic_question_records(
    study_opens: Iterable[IndexRecord],
) -> tuple[IndexRecord, ...]:
    """Build the complete immutable projection from an explicit audit slice."""

    records: dict[tuple[str, str], IndexRecord] = {}
    for study_open in sorted(study_opens, key=lambda item: item.record_id):
        for record in semantic_question_records_for_study(study_open):
            key = (record.kind, record.record_id)
            existing = records.get(key)
            if existing is not None and existing != record:
                raise SemanticQuestionRegistryIntegrityError(
                    "semantic question backfill produced a record collision"
                )
            records[key] = record
    return tuple(records[key] for key in sorted(records))


def semantic_question_registry_activation_record(
    *,
    operation_id: str,
    study_count: int,
    core_count: int,
) -> IndexRecord:
    if (
        type(operation_id) is not str
        or not operation_id
        or not operation_id.isascii()
    ):
        raise SemanticQuestionRegistryError(
            "semantic question activation operation_id must be non-empty ASCII"
        )
    if (
        type(study_count) is not int
        or study_count <= 0
        or type(core_count) is not int
        or core_count <= 0
        or core_count > study_count
    ):
        raise SemanticQuestionRegistryError(
            "semantic question activation counts are invalid"
        )
    payload = {
        "activation_operation_id": operation_id,
        "core_count": core_count,
        "schema": SEMANTIC_QUESTION_REGISTRY_ACTIVATION_SCHEMA,
        "study_count": study_count,
    }
    fingerprint = canonical_digest(
        domain="semantic-question-registry-activation",
        payload=payload,
    )
    return _record(
        kind="semantic-question-registry-activation",
        record_id=SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="active",
        fingerprint=fingerprint,
        payload=payload,
    )


def require_semantic_question_registry_activation(
    index: LocalIndex | LocalIndexView,
) -> IndexRecord | None:
    activation = index.get(
        "semantic-question-registry-activation",
        SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID,
    )
    if activation is None:
        return None
    payload = activation.payload
    operation_id = payload.get("activation_operation_id")
    if (
        activation.kind != "semantic-question-registry-activation"
        or activation.record_id != SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID
        or activation.status != "active"
        or activation.subject != "ProjectGoal:OPERATING_DIRECTION.md"
        or set(payload)
        != {"activation_operation_id", "core_count", "schema", "study_count"}
        or type(operation_id) is not str
        or not operation_id
        or not operation_id.isascii()
        or payload.get("schema")
        != SEMANTIC_QUESTION_REGISTRY_ACTIVATION_SCHEMA
        or type(payload.get("study_count")) is not int
        or type(payload.get("core_count")) is not int
        or payload["study_count"] <= 0
        or payload["core_count"] <= 0
        or payload["core_count"] > payload["study_count"]
        or activation.fingerprint
        != canonical_digest(
            domain="semantic-question-registry-activation",
            payload=dict(payload),
        )
    ):
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question registry activation is malformed"
        )
    return activation


def require_semantic_question_projection(
    index: LocalIndex | LocalIndexView,
    record: IndexRecord,
) -> IndexRecord | None:
    existing = index.get(record.kind, record.record_id)
    if existing is None:
        return record
    if (
        existing.subject != record.subject
        or existing.status != record.status
        or existing.fingerprint != record.fingerprint
        or dict(existing.payload) != dict(record.payload)
        or existing.event_stream != record.event_stream
        or existing.event_sequence != record.event_sequence
    ):
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question immutable projection collision"
        )
    return None


def semantic_question_bindings_for_core(
    index: LocalIndex | LocalIndexView,
    core_id: str,
) -> tuple[IndexRecord, ...]:
    digest = core_id.removeprefix("semantic-question-core:")
    if (
        digest == core_id
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise SemanticQuestionRegistryError(
            "semantic question core id is invalid"
        )
    records = tuple(
        record
        for record in index.records_by_fingerprint(core_id)
        if record.kind == "semantic-question-study"
    )
    for record in records:
        study_id = record.payload.get("study_id")
        if (
            record.status != "bound"
            or record.subject != f"Study:{study_id}"
            or record.payload.get("schema")
            != SEMANTIC_QUESTION_STUDY_BINDING_SCHEMA
            or record.payload.get("semantic_question_core_id") != core_id
            or record.record_id
            != semantic_question_study_binding_id(
                semantic_question_core_id=core_id,
                study_id=study_id,  # type: ignore[arg-type]
            )
        ):
            raise SemanticQuestionRegistryIntegrityError(
                "semantic question Study binding is malformed"
            )
    return tuple(sorted(records, key=lambda item: item.record_id))


def require_semantic_question_study_binding(
    index: LocalIndex | LocalIndexView,
    *,
    study_id: str,
    core_id: str,
) -> IndexRecord:
    record_id = semantic_question_study_binding_id(
        semantic_question_core_id=core_id,
        study_id=study_id,
    )
    record = index.get("semantic-question-study", record_id)
    if record is None:
        raise SemanticQuestionRegistryIntegrityError(
            f"Study {study_id} lacks its semantic question binding"
        )
    if record not in semantic_question_bindings_for_core(index, core_id):
        raise SemanticQuestionRegistryIntegrityError(
            f"Study {study_id} semantic question binding is inconsistent"
        )
    return record


@dataclass(frozen=True, slots=True)
class StudySemanticEvidence:
    study_open: IndexRecord
    core: SemanticQuestionCore
    study_closes: tuple[IndexRecord, ...]
    diagnoses: tuple[IndexRecord, ...]
    batch_opens: tuple[IndexRecord, ...]
    batch_closes: tuple[IndexRecord, ...]
    job_declarations: tuple[IndexRecord, ...]
    job_completions: tuple[IndexRecord, ...]
    trials: tuple[IndexRecord, ...]

    @property
    def study_id(self) -> str:
        return self.study_open.record_id

    @property
    def record_references(self) -> tuple[str, ...]:
        records = (
            self.study_open,
            *self.study_closes,
            *self.diagnoses,
            *self.batch_opens,
            *self.batch_closes,
            *self.job_declarations,
            *self.job_completions,
            *self.trials,
        )
        return tuple(sorted({_record_reference(record) for record in records}))

    @property
    def registered_executable_ids(self) -> tuple[str, ...]:
        return tuple(sorted({record.record_id for record in self.trials}))

    @property
    def executed_executable_ids(self) -> tuple[str, ...]:
        values: set[str] = set()
        for declaration in self.job_declarations:
            spec = declaration.payload.get("spec")
            subject = None if not isinstance(spec, Mapping) else spec.get(
                "evidence_subject"
            )
            executable_id = (
                None if not isinstance(subject, Mapping) else subject.get("id")
            )
            if isinstance(executable_id, str) and executable_id.startswith(
                "executable:"
            ):
                values.add(executable_id)
        return tuple(sorted(values))

    @property
    def scientific_completion_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                record.record_id
                for record in self.job_completions
                if isinstance(record.payload.get("scientific"), Mapping)
                and record.payload["scientific"].get("scientific_eligible")
                is True
            )
        )

    @property
    def engineering_gap_completion_ids(self) -> tuple[str, ...]:
        values: list[str] = []
        for record in self.job_completions:
            failure = record.payload.get("failure")
            if (
                isinstance(failure, Mapping)
                and failure.get("failure_kind") in {"engineering", "not_evaluable"}
                and not isinstance(record.payload.get("scientific"), Mapping)
            ):
                values.append(record.record_id)
        return tuple(sorted(values))

    @property
    def has_non_scientific_reentry_gap(self) -> bool:
        close_gap = any(
            record.status in {"not_evaluable", "evidence_gap"}
            for record in self.study_closes
        )
        batch_gap = any(
            record.status in {"engineering_failure", "not_evaluable"}
            for record in self.batch_closes
        )
        diagnosis_gap = any(
            record.status in {"engineering_gap", "not_identifiable"}
            for record in self.diagnoses
        )
        return close_gap and (
            bool(self.engineering_gap_completion_ids)
            or batch_gap
            or diagnosis_gap
        )


def _records_by_subject_statuses(
    index: LocalIndex | LocalIndexView,
    *,
    subject: str,
    statuses: Iterable[str],
    kind: str,
) -> tuple[IndexRecord, ...]:
    records = {
        (record.kind, record.record_id): record
        for status in statuses
        for record in index.records_by_subject_status(subject, status)
        if record.kind == kind
    }
    return tuple(records[key] for key in sorted(records))


def study_semantic_evidence(
    index: LocalIndex | LocalIndexView,
    study_id: str,
) -> StudySemanticEvidence:
    study_open = index.get("study-open", study_id)
    if study_open is None:
        raise SemanticQuestionRegistryIntegrityError(
            f"Study {study_id} declaration is unavailable"
        )
    core = _core_from_study_open(study_open)
    study_closes = _records_by_subject_statuses(
        index,
        subject=f"Study:{study_id}",
        statuses=_STUDY_OUTCOMES,
        kind="study-close",
    )
    diagnoses = _records_by_subject_statuses(
        index,
        subject=f"Study:{study_id}",
        statuses=_DIAGNOSIS_STATUSES,
        kind="study-diagnosis",
    )
    batch_opens = _records_by_subject_statuses(
        index,
        subject=f"Study:{study_id}",
        statuses=("open",),
        kind="batch-open",
    )
    batch_closes: list[IndexRecord] = []
    declarations: list[IndexRecord] = []
    completions: list[IndexRecord] = []
    trials: list[IndexRecord] = []
    for batch in batch_opens:
        batch_closes.extend(
            _records_by_subject_statuses(
                index,
                subject=f"Batch:{batch.record_id}",
                statuses=_BATCH_OUTCOMES,
                kind="batch-close",
            )
        )
        batch_declarations = tuple(
            record
            for record in index.records_by_payload_text(
                "job-declared", "batch_id", batch.record_id
            )
            if record.payload.get("study_id") == study_id
        )
        declarations.extend(batch_declarations)
        trials.extend(
            _records_by_subject_statuses(
                index,
                subject=f"Batch:{batch.record_id}",
                statuses=("evaluated",),
                kind="trial",
            )
        )
        for declaration in batch_declarations:
            completions.extend(
                _records_by_subject_statuses(
                    index,
                    subject=f"Job:{declaration.record_id}",
                    statuses=_JOB_OUTCOMES,
                    kind="job-completed",
                )
            )
    return StudySemanticEvidence(
        study_open=study_open,
        core=core,
        study_closes=tuple(
            sorted(study_closes, key=lambda item: (item.kind, item.record_id))
        ),
        diagnoses=tuple(
            sorted(diagnoses, key=lambda item: (item.kind, item.record_id))
        ),
        batch_opens=tuple(
            sorted(batch_opens, key=lambda item: (item.kind, item.record_id))
        ),
        batch_closes=tuple(
            sorted(batch_closes, key=lambda item: (item.kind, item.record_id))
        ),
        job_declarations=tuple(
            sorted(declarations, key=lambda item: (item.kind, item.record_id))
        ),
        job_completions=tuple(
            sorted(completions, key=lambda item: (item.kind, item.record_id))
        ),
        trials=tuple(
            sorted(trials, key=lambda item: (item.kind, item.record_id))
        ),
    )


def _resolve_basis_records(
    index: LocalIndex | LocalIndexView,
    references: tuple[str, ...],
) -> tuple[IndexRecord, ...]:
    records: list[IndexRecord] = []
    for reference in references:
        kind, separator, record_id = reference.partition(":")
        if not separator or kind not in _BASIS_KINDS or not record_id:
            raise SemanticQuestionRegistryError(
                f"semantic question basis reference {reference!r} is invalid"
            )
        record = index.get(kind, record_id)
        if record is None:
            raise SemanticQuestionRegistryError(
                f"semantic question basis record {reference!r} is unavailable"
            )
        records.append(record)
    return tuple(records)


def _require_basis_scope(
    *,
    index: LocalIndex | LocalIndexView,
    references: tuple[str, ...],
    predecessor: StudySemanticEvidence,
    successor: StudySemanticEvidence,
    relation: SemanticQuestionRelation | None,
) -> tuple[IndexRecord, ...]:
    records = _resolve_basis_records(index, references)
    allowed = set(predecessor.record_references).union(
        successor.record_references
    )
    supplied = {_record_reference(record) for record in records}
    required = {
        _record_reference(predecessor.study_open),
        _record_reference(successor.study_open),
    }
    if not required.issubset(supplied):
        raise SemanticQuestionRegistryError(
            "semantic question basis must bind both exact Study declarations"
        )
    if not supplied.issubset(allowed):
        raise SemanticQuestionRegistryError(
            "semantic question basis escapes the two bound Studies"
        )
    if relation is not None:
        predecessor_closes = {
            _record_reference(record) for record in predecessor.study_closes
        }
        successor_closes = {
            _record_reference(record) for record in successor.study_closes
        }
        if predecessor_closes and not supplied.intersection(predecessor_closes):
            raise SemanticQuestionRegistryError(
                "historical lineage basis lacks the predecessor Study close"
            )
        if successor_closes and not supplied.intersection(successor_closes):
            raise SemanticQuestionRegistryError(
                "historical lineage basis lacks the successor Study close"
            )
    if relation is SemanticQuestionRelation.ENGINEERING_REENTRY:
        gap_refs = {
            _record_reference(record)
            for record in (
                *predecessor.study_closes,
                *predecessor.diagnoses,
                *predecessor.batch_closes,
                *predecessor.job_completions,
            )
            if (
                record.status
                in {
                    "engineering_failure",
                    "engineering_gap",
                    "evidence_gap",
                    "not_evaluable",
                    "not_identifiable",
                }
                or (
                    isinstance(record.payload.get("failure"), Mapping)
                    and record.payload["failure"].get("failure_kind")
                    in {"engineering", "not_evaluable"}
                )
            )
        }
        successor_science_refs = {
            _record_reference(record)
            for record in successor.job_completions
            if record.record_id in successor.scientific_completion_ids
        }
        if not supplied.intersection(gap_refs):
            raise SemanticQuestionRegistryError(
                "engineering reentry basis lacks the predecessor gap"
            )
        if successor.study_closes and not supplied.intersection(
            successor_science_refs
        ):
            raise SemanticQuestionRegistryError(
                "historical engineering reentry basis lacks successor science"
            )
    return records


def _require_bound_study_evidence(
    index: LocalIndex | LocalIndexView,
    study_id: str,
    expected_core_id: str,
) -> StudySemanticEvidence:
    evidence = study_semantic_evidence(index, study_id)
    if evidence.core.identity != expected_core_id:
        raise SemanticQuestionRegistryError(
            f"Study {study_id} differs from the proposed semantic core"
        )
    require_semantic_question_study_binding(
        index,
        study_id=study_id,
        core_id=expected_core_id,
    )
    return evidence


def semantic_question_equivalence_record(
    index: LocalIndex | LocalIndexView,
    proposal: SemanticQuestionEquivalenceProposal,
) -> IndexRecord:
    if not isinstance(proposal, SemanticQuestionEquivalenceProposal):
        raise SemanticQuestionRegistryError(
            "semantic question equivalence proposal is not typed"
        )
    canonical = _require_bound_study_evidence(
        index,
        proposal.canonical_study_id,
        proposal.canonical_core_id,
    )
    equivalent = _require_bound_study_evidence(
        index,
        proposal.equivalent_study_id,
        proposal.equivalent_core_id,
    )
    _require_basis_scope(
        index=index,
        references=proposal.basis_record_ids,
        predecessor=canonical,
        successor=equivalent,
        relation=None,
    )
    members = sorted(
        (
            {
                "semantic_question_core_id": proposal.canonical_core_id,
                "study_id": proposal.canonical_study_id,
            },
            {
                "semantic_question_core_id": proposal.equivalent_core_id,
                "study_id": proposal.equivalent_study_id,
            },
        ),
        key=lambda item: (item["study_id"], item["semantic_question_core_id"]),
    )
    record_id = "semantic-question-equivalence-pair:" + canonical_digest(
        domain="semantic-question-equivalence-pair",
        payload={"members": members},
    )
    payload = {
        "automatic_similarity_authority": "none",
        "members": members,
        "proposal": proposal.to_identity_payload(),
        "proposal_id": proposal.identity,
        "schema": SEMANTIC_QUESTION_EQUIVALENCE_RECORD_SCHEMA,
        "scope": "declared_question_core_only",
        "scientific_credit_delta": 0,
    }
    return _record(
        kind="semantic-question-equivalence",
        record_id=record_id,
        subject=f"SemanticQuestionPair:{record_id}",
        status="accepted",
        fingerprint=proposal.identity,
        payload=payload,
    )


def _require_prospective_basis_scope(
    *,
    index: LocalIndex | LocalIndexView,
    references: tuple[str, ...],
    predecessor: StudySemanticEvidence,
    relation: SemanticQuestionRelation | None,
) -> tuple[IndexRecord, ...]:
    records = _resolve_basis_records(index, references)
    supplied = {_record_reference(record) for record in records}
    if _record_reference(predecessor.study_open) not in supplied:
        raise SemanticQuestionRegistryError(
            "prospective semantic question basis lacks its predecessor Study"
        )
    if not supplied.issubset(set(predecessor.record_references)):
        raise SemanticQuestionRegistryError(
            "prospective semantic question basis escapes its predecessor Study"
        )
    predecessor_closes = {
        _record_reference(record) for record in predecessor.study_closes
    }
    if relation is not None and predecessor_closes and not supplied.intersection(
        predecessor_closes
    ):
        raise SemanticQuestionRegistryError(
            "prospective lineage basis lacks the predecessor Study close"
        )
    if relation is SemanticQuestionRelation.ENGINEERING_REENTRY:
        gap_refs = {
            _record_reference(record)
            for record in (
                *predecessor.study_closes,
                *predecessor.diagnoses,
                *predecessor.batch_closes,
                *predecessor.job_completions,
            )
            if (
                record.status
                in {
                    "engineering_failure",
                    "engineering_gap",
                    "evidence_gap",
                    "not_evaluable",
                    "not_identifiable",
                }
                or (
                    isinstance(record.payload.get("failure"), Mapping)
                    and record.payload["failure"].get("failure_kind")
                    in {"engineering", "not_evaluable"}
                )
            )
        }
        if not supplied.intersection(gap_refs):
            raise SemanticQuestionRegistryError(
                "prospective engineering reentry basis lacks the predecessor gap"
            )
    return records


def semantic_question_prospective_equivalence_record(
    index: LocalIndex | LocalIndexView,
    successor_study_open: IndexRecord,
    proposal: SemanticQuestionEquivalenceProposal,
) -> IndexRecord:
    """Accept explicit equivalence while the successor Study is being opened."""

    if not isinstance(proposal, SemanticQuestionEquivalenceProposal):
        raise SemanticQuestionRegistryError(
            "semantic question equivalence proposal is not typed"
        )
    successor_id = _study_id_from_open(successor_study_open)
    successor_core = _core_from_study_open(successor_study_open)
    members = {
        proposal.canonical_study_id: proposal.canonical_core_id,
        proposal.equivalent_study_id: proposal.equivalent_core_id,
    }
    if members.get(successor_id) != successor_core.identity:
        raise SemanticQuestionRegistryError(
            "prospective equivalence does not bind the opening Study"
        )
    predecessor_id = next(
        study_id for study_id in members if study_id != successor_id
    )
    predecessor = _require_bound_study_evidence(
        index,
        predecessor_id,
        members[predecessor_id],
    )
    _require_prospective_basis_scope(
        index=index,
        references=proposal.basis_record_ids,
        predecessor=predecessor,
        relation=None,
    )
    pair_members = sorted(
        (
            {
                "semantic_question_core_id": proposal.canonical_core_id,
                "study_id": proposal.canonical_study_id,
            },
            {
                "semantic_question_core_id": proposal.equivalent_core_id,
                "study_id": proposal.equivalent_study_id,
            },
        ),
        key=lambda item: (item["study_id"], item["semantic_question_core_id"]),
    )
    record_id = "semantic-question-equivalence-pair:" + canonical_digest(
        domain="semantic-question-equivalence-pair",
        payload={"members": pair_members},
    )
    payload = {
        "automatic_similarity_authority": "none",
        "members": pair_members,
        "proposal": proposal.to_identity_payload(),
        "proposal_id": proposal.identity,
        "schema": SEMANTIC_QUESTION_EQUIVALENCE_RECORD_SCHEMA,
        "scope": "declared_question_core_only",
        "scientific_credit_delta": 0,
    }
    return _record(
        kind="semantic-question-equivalence",
        record_id=record_id,
        subject=f"SemanticQuestionPair:{record_id}",
        status="accepted",
        fingerprint=proposal.identity,
        payload=payload,
    )


def _require_equivalence_record(
    *,
    proposal: SemanticQuestionLineageProposal,
    equivalence_record: IndexRecord | None,
) -> None:
    equivalence_id = proposal.equivalence_proposal_id
    if equivalence_id is None:
        if equivalence_record is not None:
            raise SemanticQuestionRegistryError(
                "same-core or revised lineage supplied unexpected equivalence"
            )
        return
    if (
        equivalence_record is None
        or equivalence_record.kind != "semantic-question-equivalence"
        or equivalence_record.status != "accepted"
        or equivalence_record.fingerprint != equivalence_id
        or equivalence_record.payload.get("proposal_id") != equivalence_id
    ):
        raise SemanticQuestionRegistryError(
            "lineage lacks its exact accepted equivalence"
        )
    members = equivalence_record.payload.get("members")
    expected = {
        (proposal.predecessor_study_id, proposal.predecessor_core_id),
        (proposal.successor_study_id, proposal.successor_core_id),
    }
    observed = (
        {
            (member.get("study_id"), member.get("semantic_question_core_id"))
            for member in members
        }
        if isinstance(members, list)
        and all(isinstance(member, Mapping) for member in members)
        else set()
    )
    if observed != expected:
        raise SemanticQuestionRegistryError(
            "accepted equivalence belongs to different Studies or cores"
        )


def semantic_question_lineage_record(
    index: LocalIndex | LocalIndexView,
    proposal: SemanticQuestionLineageProposal,
    *,
    equivalence_record: IndexRecord | None = None,
) -> IndexRecord:
    if not isinstance(proposal, SemanticQuestionLineageProposal):
        raise SemanticQuestionRegistryError(
            "semantic question lineage proposal is not typed"
        )
    predecessor = _require_bound_study_evidence(
        index,
        proposal.predecessor_study_id,
        proposal.predecessor_core_id,
    )
    successor = _require_bound_study_evidence(
        index,
        proposal.successor_study_id,
        proposal.successor_core_id,
    )
    if len(predecessor.study_closes) != 1 or len(successor.study_closes) != 1:
        raise SemanticQuestionRegistryError(
            "historical semantic lineage requires both exact Study closes"
        )
    predecessor_sequence = predecessor.study_open.authority_sequence
    successor_sequence = successor.study_open.authority_sequence
    if (
        type(predecessor_sequence) is int
        and type(successor_sequence) is int
        and predecessor_sequence >= successor_sequence
    ):
        raise SemanticQuestionRegistryError(
            "semantic question lineage must point forward in authority time"
        )
    _require_equivalence_record(
        proposal=proposal,
        equivalence_record=equivalence_record,
    )
    if proposal.relation is SemanticQuestionRelation.SEMANTIC_REVISION:
        pair_members = sorted(
            (
                {
                    "semantic_question_core_id": proposal.predecessor_core_id,
                    "study_id": proposal.predecessor_study_id,
                },
                {
                    "semantic_question_core_id": proposal.successor_core_id,
                    "study_id": proposal.successor_study_id,
                },
            ),
            key=lambda item: (
                item["study_id"],
                item["semantic_question_core_id"],
            ),
        )
        pair_id = "semantic-question-equivalence-pair:" + canonical_digest(
            domain="semantic-question-equivalence-pair",
            payload={"members": pair_members},
        )
        if index.get("semantic-question-equivalence", pair_id) is not None:
            raise SemanticQuestionRegistryError(
                "semantic revision conflicts with accepted core equivalence"
            )
    _require_basis_scope(
        index=index,
        references=proposal.basis_record_ids,
        predecessor=predecessor,
        successor=successor,
        relation=proposal.relation,
    )
    if proposal.relation is SemanticQuestionRelation.ENGINEERING_REENTRY:
        if not predecessor.has_non_scientific_reentry_gap:
            raise SemanticQuestionRegistryError(
                "engineering reentry predecessor lacks a non-scientific gap"
            )
        if not successor.scientific_completion_ids:
            raise SemanticQuestionRegistryError(
                "historical engineering reentry successor lacks scientific evidence"
            )
        if not any(
            record.status in {"supported", "not_supported"}
            for record in successor.study_closes
        ):
            raise SemanticQuestionRegistryError(
                "historical engineering reentry successor lacks a scientific Study verdict"
            )
    if proposal.relation is SemanticQuestionRelation.CONFIRMATION and not any(
        record.status == "supported" for record in predecessor.study_closes
    ):
        raise SemanticQuestionRegistryError(
            "confirmation predecessor is not supported"
        )
    predecessor_known = set(predecessor.registered_executable_ids).union(
        predecessor.executed_executable_ids
    )
    successor_known = set(successor.registered_executable_ids).union(
        successor.executed_executable_ids
    )
    overlap = tuple(sorted(predecessor_known.intersection(successor_known)))
    if proposal.relation in {
        SemanticQuestionRelation.INDEPENDENT_REPLICATION,
        SemanticQuestionRelation.CONFIRMATION,
    }:
        if (
            not predecessor.scientific_completion_ids
            or not successor.scientific_completion_ids
        ):
            raise SemanticQuestionRegistryError(
                "replication or confirmation requires scientific evidence on both Studies"
            )
        if overlap:
            raise SemanticQuestionRegistryError(
                "replication or confirmation cannot reuse an exact Executable"
            )
    if proposal.relation is SemanticQuestionRelation.SEMANTIC_REVISION:
        resolution = "historical_successor_result_distinct_estimand"
        predecessor_resolution_authority = "none_distinct_estimand"
    elif successor.scientific_completion_ids:
        resolution = "historical_related_scientific_result"
        predecessor_resolution_authority = (
            "successor_only"
            if proposal.relation
            is SemanticQuestionRelation.ENGINEERING_REENTRY
            else "none"
        )
    elif any(record.status == "preserved" for record in successor.study_closes):
        resolution = "historical_operational_result_without_scientific_credit"
        predecessor_resolution_authority = "none"
    else:
        resolution = "historical_related_without_scientific_result"
        predecessor_resolution_authority = "none"
    event_stream = f"semantic-question-lineage:{proposal.successor_study_id}"
    existing_lineage = index.get("semantic-question-lineage", proposal.identity)
    if existing_lineage is not None:
        if (
            existing_lineage.event_stream != event_stream
            or type(existing_lineage.event_sequence) is not int
            or existing_lineage.event_sequence <= 0
        ):
            raise SemanticQuestionRegistryIntegrityError(
                "semantic question lineage stream position is malformed"
            )
        event_sequence = existing_lineage.event_sequence
    else:
        head = index.event_head(event_stream)
        event_sequence = 1 if head is None else head.sequence + 1
    payload = {
        "automatic_equivalence_authority": "none",
        "claim_delta": "none",
        "evidence_transfer_authority": "none",
        "exact_executable_overlap_ids": list(overlap),
        "predecessor_engineering_gap_completion_ids": list(
            predecessor.engineering_gap_completion_ids
        ),
        "predecessor_registered_executable_ids": list(
            predecessor.registered_executable_ids
        ),
        "predecessor_resolution_authority": predecessor_resolution_authority,
        "predecessor_scientific_completion_ids": list(
            predecessor.scientific_completion_ids
        ),
        "proposal": proposal.to_identity_payload(),
        "proposal_id": proposal.identity,
        "relation": proposal.relation.value,
        "resolution_scope": resolution,
        "schema": SEMANTIC_QUESTION_LINEAGE_RECORD_SCHEMA,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "successor_registered_executable_ids": list(
            successor.registered_executable_ids
        ),
        "successor_scientific_completion_ids": list(
            successor.scientific_completion_ids
        ),
    }
    return _record(
        kind="semantic-question-lineage",
        record_id=proposal.identity,
        subject=f"Study:{proposal.successor_study_id}",
        status="accepted",
        fingerprint=proposal.identity,
        payload=payload,
        event_stream=event_stream,
        event_sequence=event_sequence,
    )


def semantic_question_prospective_lineage_record(
    index: LocalIndex | LocalIndexView,
    successor_study_open: IndexRecord,
    proposal: SemanticQuestionLineageProposal,
    *,
    equivalence_record: IndexRecord | None = None,
) -> IndexRecord:
    """Declare typed lineage in the same atomic event as a successor Study."""

    if not isinstance(proposal, SemanticQuestionLineageProposal):
        raise SemanticQuestionRegistryError(
            "semantic question lineage proposal is not typed"
        )
    successor_id = _study_id_from_open(successor_study_open)
    successor_core = _core_from_study_open(successor_study_open)
    if (
        proposal.successor_study_id != successor_id
        or proposal.successor_core_id != successor_core.identity
    ):
        raise SemanticQuestionRegistryError(
            "prospective lineage does not bind the opening Study"
        )
    predecessor = _require_bound_study_evidence(
        index,
        proposal.predecessor_study_id,
        proposal.predecessor_core_id,
    )
    _require_equivalence_record(
        proposal=proposal,
        equivalence_record=equivalence_record,
    )
    _require_prospective_basis_scope(
        index=index,
        references=proposal.basis_record_ids,
        predecessor=predecessor,
        relation=proposal.relation,
    )
    if (
        proposal.relation is SemanticQuestionRelation.ENGINEERING_REENTRY
        and not predecessor.has_non_scientific_reentry_gap
    ):
        raise SemanticQuestionRegistryError(
            "engineering reentry predecessor lacks a non-scientific gap"
        )
    if proposal.relation is SemanticQuestionRelation.CONFIRMATION and not any(
        record.status == "supported" for record in predecessor.study_closes
    ):
        raise SemanticQuestionRegistryError(
            "confirmation predecessor is not supported"
        )
    head = index.event_head(f"semantic-question-lineage:{successor_id}")
    payload = {
        "automatic_equivalence_authority": "none",
        "claim_delta": "none",
        "evidence_transfer_authority": "none",
        "exact_executable_overlap_ids": [],
        "predecessor_engineering_gap_completion_ids": list(
            predecessor.engineering_gap_completion_ids
        ),
        "predecessor_registered_executable_ids": list(
            predecessor.registered_executable_ids
        ),
        "predecessor_resolution_authority": "pending_successor_result",
        "predecessor_scientific_completion_ids": list(
            predecessor.scientific_completion_ids
        ),
        "proposal": proposal.to_identity_payload(),
        "proposal_id": proposal.identity,
        "relation": proposal.relation.value,
        "resolution_scope": "prospective_pending_successor_evidence",
        "schema": SEMANTIC_QUESTION_LINEAGE_RECORD_SCHEMA,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "successor_registered_executable_ids": [],
        "successor_scientific_completion_ids": [],
    }
    return _record(
        kind="semantic-question-lineage",
        record_id=proposal.identity,
        subject=f"Study:{successor_id}",
        status="declared",
        fingerprint=proposal.identity,
        payload=payload,
        event_stream=f"semantic-question-lineage:{successor_id}",
        event_sequence=1 if head is None else head.sequence + 1,
    )


def semantic_question_lineage_resolution_records(
    index: LocalIndex | LocalIndexView,
    study_close: IndexRecord,
) -> tuple[IndexRecord, ...]:
    """Resolve prospective lineage from successor evidence without back-credit."""

    study_id = study_close.subject.removeprefix("Study:")
    if (
        study_close.kind != "study-close"
        or study_close.subject != f"Study:{study_id}"
        or study_close.status not in _STUDY_OUTCOMES
        or study_close.payload.get("outcome") != study_close.status
    ):
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question lineage resolution received a malformed Study close"
        )
    study_open = index.get("study-open", study_id)
    if study_open is None:
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question lineage resolution lacks its Study declaration"
        )
    declared_id = study_open.payload.get("semantic_question_lineage_id")
    declared_records = tuple(
        record
        for record in index.records_by_subject_status(
            f"Study:{study_id}", "declared"
        )
        if record.kind == "semantic-question-lineage"
    )
    if declared_id is None:
        if declared_records:
            raise SemanticQuestionRegistryIntegrityError(
                "Study declaration omitted its durable semantic lineage"
            )
        return ()
    if type(declared_id) is not str:
        raise SemanticQuestionRegistryIntegrityError(
            "Study semantic lineage identity is malformed"
        )
    if len(declared_records) != 1 or declared_records[0].record_id != declared_id:
        raise SemanticQuestionRegistryIntegrityError(
            "Study semantic lineage declaration is unavailable or ambiguous"
        )
    declared = declared_records[0]
    proposal_payload = declared.payload.get("proposal")
    if not isinstance(proposal_payload, Mapping):
        raise SemanticQuestionRegistryIntegrityError(
            "Study semantic lineage proposal is unavailable"
        )
    try:
        proposal = SemanticQuestionLineageProposal.from_identity_payload(
            proposal_payload
        )
    except SemanticQuestionError as exc:
        raise SemanticQuestionRegistryIntegrityError(str(exc)) from exc
    if (
        proposal.identity != declared_id
        or proposal.successor_study_id != study_id
        or declared.fingerprint != proposal.identity
        or declared.payload.get("proposal_id") != proposal.identity
    ):
        raise SemanticQuestionRegistryIntegrityError(
            "Study semantic lineage differs from its typed proposal"
        )
    predecessor = _require_bound_study_evidence(
        index,
        proposal.predecessor_study_id,
        proposal.predecessor_core_id,
    )
    successor = study_semantic_evidence(index, study_id)
    if successor.core.identity != proposal.successor_core_id:
        raise SemanticQuestionRegistryIntegrityError(
            "successor Study differs from its declared semantic lineage"
        )
    predecessor_known = set(predecessor.registered_executable_ids).union(
        predecessor.executed_executable_ids
    )
    successor_known = set(successor.registered_executable_ids).union(
        successor.executed_executable_ids
    )
    overlap = tuple(sorted(predecessor_known.intersection(successor_known)))
    scientific_result = bool(successor.scientific_completion_ids) and (
        study_close.status
        in {"supported", "not_supported", "preserved", "pruned"}
    )
    resolution_status = (
        "scientific_result_recorded" if scientific_result else "unresolved"
    )
    payload = {
        "claim_delta": "none",
        "evidence_transfer_authority": "none",
        "exact_executable_overlap_ids": list(overlap),
        "lineage_record_id": declared.record_id,
        "predecessor_resolution_authority": (
            "none_distinct_estimand"
            if proposal.relation is SemanticQuestionRelation.SEMANTIC_REVISION
            else "successor_only"
            if scientific_result
            and proposal.relation
            is SemanticQuestionRelation.ENGINEERING_REENTRY
            else "none"
        ),
        "proposal_id": proposal.identity,
        "relation": proposal.relation.value,
        "resolution_status": resolution_status,
        "schema": "semantic_question_lineage_resolution.v1",
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
        "study_close_outcome": study_close.status,
        "study_close_record_id": study_close.record_id,
        "successor_executed_executable_ids": list(
            successor.executed_executable_ids
        ),
        "successor_registered_executable_ids": list(
            successor.registered_executable_ids
        ),
        "successor_scientific_completion_ids": list(
            successor.scientific_completion_ids
        ),
    }
    record_id = "semantic-question-lineage-resolution:" + canonical_digest(
        domain="semantic-question-lineage-resolution",
        payload=payload,
    )
    head = index.event_head(f"semantic-question-lineage:{study_id}")
    if head is None or head.record_id != declared.record_id:
        raise SemanticQuestionRegistryIntegrityError(
            "semantic question lineage stream lost its declaration head"
        )
    return (
        _record(
            kind="semantic-question-lineage-resolution",
            record_id=record_id,
            subject=f"Study:{study_id}",
            status=resolution_status,
            fingerprint=proposal.identity,
            payload=payload,
            event_stream=f"semantic-question-lineage:{study_id}",
            event_sequence=head.sequence + 1,
        ),
    )


def require_repeated_core_lineage(
    index: LocalIndex | LocalIndexView,
    *,
    successor_study_id: str,
    successor_core_id: str,
    proposal: SemanticQuestionLineageProposal | None,
) -> None:
    """Fail closed after activation when an exact question is silently reused."""

    if require_semantic_question_registry_activation(index) is None:
        return
    prior = tuple(
        record
        for record in semantic_question_bindings_for_core(index, successor_core_id)
        if record.payload.get("study_id") != successor_study_id
    )
    if not prior:
        return
    if proposal is None:
        raise SemanticQuestionRegistryError(
            "repeated exact semantic question requires typed Study lineage"
        )
    prior_ids = {record.payload.get("study_id") for record in prior}
    if (
        proposal.successor_study_id != successor_study_id
        or proposal.successor_core_id != successor_core_id
        or proposal.predecessor_study_id not in prior_ids
    ):
        raise SemanticQuestionRegistryError(
            "repeated exact semantic question lineage does not bind a prior Study"
        )


__all__ = [
    "SEMANTIC_QUESTION_EQUIVALENCE_RECORD_SCHEMA",
    "SEMANTIC_QUESTION_LINEAGE_RECORD_SCHEMA",
    "SEMANTIC_QUESTION_REGISTRY_ACTIVATION_ID",
    "SEMANTIC_QUESTION_REGISTRY_ACTIVATION_SCHEMA",
    "SemanticQuestionRegistryError",
    "SemanticQuestionRegistryIntegrityError",
    "StudySemanticEvidence",
    "backfill_semantic_question_records",
    "require_repeated_core_lineage",
    "require_semantic_question_projection",
    "require_semantic_question_registry_activation",
    "require_semantic_question_study_binding",
    "semantic_question_bindings_for_core",
    "semantic_question_core_record",
    "semantic_question_equivalence_record",
    "semantic_question_lineage_record",
    "semantic_question_lineage_resolution_records",
    "semantic_question_prospective_equivalence_record",
    "semantic_question_prospective_lineage_record",
    "semantic_question_records_for_study",
    "semantic_question_registry_activation_record",
    "semantic_question_study_record",
    "study_semantic_evidence",
]
