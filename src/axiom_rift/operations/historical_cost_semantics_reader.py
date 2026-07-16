"""Authenticated keyed hot-path reader for historical cost semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.historical_cost_semantics_common import (
    COMPLETION_SCOPE_RECORD_KIND,
    COMPLETION_SCOPE_SCHEMA,
    HistoricalCostQualification,
    HistoricalCostSemanticsProjectionError,
    HistoricalCriterionBinding,
    LATCH_EVENT_KIND,
    LATCH_RECORD_KIND,
    LATCH_STREAM,
    adjudication_claims_and_criteria,
    at_or_before,
    class_for_study,
    completion_claims,
    completion_join,
    is_spread_cost_contract,
    normalized_criterion,
    preserved_independent_scopes,
    record_cursor,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.historical_cost_semantics import (
    AUTHORITY_DELTA_ZERO,
    CAUSAL_INVALID_COMPLETION_IDS,
    EXCEPTIONAL_STUDY_CLASSES,
    HistoricalCostInterpretation,
    HistoricalCostQualificationState,
    HistoricalCostSemanticCriterion,
    HistoricalCostSemanticsError,
    HistoricalCostSemanticsLatch,
    HistoricalSpreadSemanticClass,
    PRODUCTION_UPPER_CURSOR,
    historical_cost_semantics_latch_from_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


@dataclass(frozen=True, slots=True)
class HistoricalCompletionCostAuthority:
    """Completion-scoped authority from one authenticated activation member."""

    completion_record_id: str
    executable_id: str
    study_id: str
    latch_record_id: str
    semantic_class: HistoricalSpreadSemanticClass
    scientific: bool
    negative_memory_ids: tuple[str, ...]
    preserved_independent_scopes: tuple[str, ...]

    @property
    def proxy_only(self) -> bool:
        return True

    @property
    def actual_native_cost_state(self) -> HistoricalCostQualificationState:
        return (
            HistoricalCostQualificationState.UNRESOLVED
            if self.scientific
            else HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE
        )

    @property
    def economic_credit(self) -> int:
        return 0

    @property
    def candidate_credit(self) -> int:
        return 0

    @property
    def negative_memory_authoritative(self) -> bool:
        return False

    @property
    def requires_axis_reopen(self) -> bool:
        return self.scientific and bool(self.negative_memory_ids)


@dataclass(frozen=True, slots=True)
class HistoricalNegativeMemoryCostAuthority:
    """Cost qualification for one exact durable negative-memory record."""

    negative_memory_id: str
    latch_record_id: str
    affected_completion_ids: tuple[str, ...]
    preserved_independent_scopes: tuple[str, ...]
    preserved_proxy_scope: bool = True
    state: str = "diagnostic_only"

    @property
    def prune_credit(self) -> int:
        return 0

    @property
    def exhaustion_credit(self) -> int:
        return 0

    @property
    def terminal_credit(self) -> int:
        return 0


def _require_latch_writer_authority(
    index: LocalIndex | LocalIndexView,
    record: IndexRecord,
    latch: HistoricalCostSemanticsLatch,
) -> None:
    try:
        _event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset({LATCH_EVENT_KIND}),
        )
    except RecordedTransitionAuthorityError as exc:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch lacks same-event Writer authority"
        ) from exc
    expected = {
        "audit_manifest_hash": latch.audit_manifest_hash,
        "authority_delta": dict(AUTHORITY_DELTA_ZERO),
        "latch_record_id": latch.identity,
    }
    if result != expected:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch Writer result is not exact"
        )


def _current_latch_head(
    index: LocalIndex | LocalIndexView,
) -> tuple[HistoricalCostSemanticsLatch, IndexRecord] | None:
    """Read only the authenticated activation head; never rescan inventory."""

    head = index.event_head(LATCH_STREAM)
    if head is None:
        return None
    record = index.get(head.record_kind, head.record_id)
    try:
        latch = historical_cost_semantics_latch_from_payload(
            {} if record is None else record.payload
        )
    except HistoricalCostSemanticsError as exc:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch head payload is malformed"
        ) from exc
    if (
        record is None
        or head.sequence != 1
        or record.kind != LATCH_RECORD_KIND
        or record.status != "latched"
        or record.record_id != latch.identity
        or record.subject != "ProjectGoal:OPERATING_DIRECTION.md"
        or record.event_stream != LATCH_STREAM
        or record.event_sequence != 1
        or record.fingerprint
        != latch.identity.removeprefix("historical-cost-semantics-latch:")
        or record_cursor(record).sequence < PRODUCTION_UPPER_CURSOR.sequence
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch stream head is invalid"
        )
    _require_latch_writer_authority(index, record, latch)
    return latch, record


def current_historical_cost_semantics_activation(
    index: LocalIndex | LocalIndexView,
) -> HistoricalCostSemanticsLatch | None:
    """Return the routine authenticated latch without complete rederivation."""

    head = _current_latch_head(index)
    return None if head is None else head[0]


def _direct_completion_cost_authority(
    index: LocalIndex | LocalIndexView,
    completion_record_id: str,
) -> HistoricalCompletionCostAuthority | None:
    if (
        type(completion_record_id) is not str
        or len(completion_record_id) != 64
        or any(char not in "0123456789abcdef" for char in completion_record_id)
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost completion id must be a SHA-256 digest"
        )
    activation = _current_latch_head(index)
    projected = index.get(COMPLETION_SCOPE_RECORD_KIND, completion_record_id)
    if activation is None:
        if projected is not None:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost completion projection exists before activation"
            )
        return None
    latch, latch_record = activation
    completion = index.get("job-completed", completion_record_id)
    if completion is None:
        if projected is not None:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost completion projection lost its completion"
            )
        return None
    before_boundary = at_or_before(completion, latch.upper_authority_cursor)
    declaration, _trial, executable_id, _executable, cost_contract = (
        completion_join(index, completion, latch.upper_authority_cursor)
        if before_boundary
        else (None, None, None, None, None)
    )
    is_member = bool(
        before_boundary
        and isinstance(cost_contract, str)
        and is_spread_cost_contract(cost_contract)
        and completion_record_id not in CAUSAL_INVALID_COMPLETION_IDS
    )
    if not is_member:
        if projected is not None:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost completion projection contains a nonmember"
            )
        return None
    assert declaration is not None and isinstance(executable_id, str)
    if projected is None:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch lacks a required keyed completion member"
        )
    payload = projected.payload
    negative_ids = payload.get("negative_memory_ids")
    try:
        semantic_class = HistoricalSpreadSemanticClass(
            payload.get("semantic_class")
        )
    except (TypeError, ValueError) as exc:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost completion semantic class is malformed"
        ) from exc
    scientific = isinstance(completion.payload.get("scientific"), Mapping)
    study_id = declaration.payload.get("study_id")
    if (
        not isinstance(negative_ids, list)
        or negative_ids != sorted(set(negative_ids))
        or any(
            type(value) is not str
            or not value.startswith("negative-memory:")
            for value in negative_ids
        )
        or type(study_id) is not str
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost completion payload is malformed"
        )
    expected_class = class_for_study(
        study_id,
        scientific=scientific,
        rules=EXCEPTIONAL_STUDY_CLASSES,
    )
    expected_payload = {
        "completion_record_id": completion_record_id,
        "executable_id": executable_id,
        "latch_record_id": latch.identity,
        "negative_memory_ids": negative_ids,
        "schema": COMPLETION_SCOPE_SCHEMA,
        "scientific": scientific,
        "semantic_class": expected_class.value,
        "study_id": study_id,
    }
    expected_fingerprint = canonical_digest(
        domain="historical-cost-semantics-completion",
        payload=expected_payload,
    )
    if (
        semantic_class is not expected_class
        or dict(payload) != expected_payload
        or projected.kind != COMPLETION_SCOPE_RECORD_KIND
        or projected.record_id != completion_record_id
        or projected.subject != f"JobCompletion:{completion_record_id}"
        or projected.status != ("qualified" if scientific else "engineering")
        or projected.fingerprint != expected_fingerprint
        or projected.event_stream is not None
        or projected.event_sequence is not None
        or record_cursor(projected) != record_cursor(latch_record)
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost completion projection is not same-event canonical"
        )
    for memory_id in negative_ids:
        memory = index.get("negative-memory", memory_id)
        references = None if memory is None else memory.payload.get(
            "evidence_references"
        )
        if (
            memory is None
            or memory.status != "durable"
            or not at_or_before(memory, latch.upper_authority_cursor)
            or not isinstance(references, list)
            or completion_record_id not in references
        ):
            raise HistoricalCostSemanticsProjectionError(
                "historical cost completion lost its negative-memory binding"
            )
    return HistoricalCompletionCostAuthority(
        completion_record_id=completion_record_id,
        executable_id=executable_id,
        study_id=study_id,
        latch_record_id=latch.identity,
        semantic_class=semantic_class,
        scientific=scientific,
        negative_memory_ids=tuple(negative_ids),
        preserved_independent_scopes=preserved_independent_scopes(
            semantic_class
        ),
    )


def effective_historical_completion_cost_authority(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord | str,
) -> HistoricalCompletionCostAuthority | None:
    """Resolve one completion through direct keys, never the 501-row audit."""

    completion_id = (
        completion.record_id if isinstance(completion, IndexRecord) else completion
    )
    authority = _direct_completion_cost_authority(index, completion_id)
    if (
        isinstance(completion, IndexRecord)
        and (stored := index.get("job-completed", completion_id)) != completion
    ):
        raise HistoricalCostSemanticsProjectionError(
            "caller completion differs from its authenticated projection"
        )
    return authority


def _current_completion_claims_and_criteria(
    index: LocalIndex | LocalIndexView,
    completion_id: str,
) -> tuple[tuple[str, ...], tuple[HistoricalCriterionBinding, ...]]:
    completion = index.get("job-completed", completion_id)
    if completion is None:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost claim lost its completion"
        )
    job_id = completion.payload.get("job_id")
    declaration = index.get("job-declared", job_id) if type(job_id) is str else None
    scientific = completion.payload.get("scientific")
    if declaration is None or not isinstance(scientific, Mapping):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost claim lacks scientific completion authority"
        )
    claim_ids = set(completion_claims(scientific, declaration))
    direct_claims, direct_criteria = adjudication_claims_and_criteria(
        scientific.get("adjudication")
    )
    claim_ids.update(direct_claims)
    criteria = direct_criteria
    head = index.event_head(f"historical-adjudication:{completion_id}")
    if head is not None:
        record = index.get(head.record_kind, head.record_id)
        if (
            record is None
            or record.kind != "historical-scientific-adjudication"
            or record.event_stream != f"historical-adjudication:{completion_id}"
            or record.event_sequence != head.sequence
            or record.payload.get("completion_record_id") != completion_id
        ):
            raise HistoricalCostSemanticsProjectionError(
                "historical cost claim adjudication head is malformed"
            )
        try:
            _event_kind, result = require_same_event_operation_result(
                index,
                record=record,
                expected_event_kinds=frozenset(
                    {"historical_scientific_adjudications_recorded"}
                ),
            )
        except RecordedTransitionAuthorityError as exc:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost claim adjudication lacks Writer authority"
            ) from exc
        adjudication_ids = result.get("adjudication_record_ids")
        if (
            not isinstance(adjudication_ids, list)
            or record.record_id not in adjudication_ids
        ):
            raise HistoricalCostSemanticsProjectionError(
                "historical cost claim adjudication is absent from Writer result"
            )
        historical_claims, historical_criteria = (
            adjudication_claims_and_criteria(
                record.payload.get("adjudication")
            )
        )
        claim_ids.update(historical_claims)
        if criteria and historical_criteria and criteria != historical_criteria:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost claim criteria disagree"
            )
        criteria = historical_criteria or criteria
    return tuple(sorted(claim_ids)), criteria


def _qualification(
    authority: HistoricalCompletionCostAuthority,
    interpretation: HistoricalCostInterpretation,
    state: HistoricalCostQualificationState,
    reason: str,
    *,
    proxy_only: bool = False,
) -> HistoricalCostQualification:
    return HistoricalCostQualification(
        completion_record_id=authority.completion_record_id,
        semantic_class=authority.semantic_class,
        interpretation=interpretation,
        state=state,
        reason=reason,
        proxy_only=proxy_only,
    )


def qualify_historical_cost_claim(
    index: LocalIndex | LocalIndexView,
    *,
    completion_record_id: str,
    claim_id: str,
    interpretation: HistoricalCostInterpretation,
) -> HistoricalCostQualification | None:
    authority = _direct_completion_cost_authority(index, completion_record_id)
    if authority is None:
        return None
    if type(claim_id) is not str or not claim_id or not claim_id.isascii():
        raise HistoricalCostSemanticsProjectionError(
            "historical cost claim id must be non-empty ASCII"
        )
    if not isinstance(interpretation, HistoricalCostInterpretation):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost claim interpretation is not typed"
        )
    if not authority.scientific:
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE,
            "engineering_completion_has_no_scientific_cost_claim",
        )
    if claim_id in authority.preserved_independent_scopes:
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.PRESERVED_INDEPENDENT,
            "claim_scope_is_independent_of_completed_period_cost_meaning",
        )
    claims, _criteria = _current_completion_claims_and_criteria(
        index,
        completion_record_id,
    )
    if claim_id not in claims:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost claim is not bound to its completion"
        )
    if interpretation is HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY:
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.PRESERVED_EXACT_PROXY_ONLY,
            "claim_is_preserved_only_under_completed_period_proxy_semantics",
            proxy_only=True,
        )
    return _qualification(
        authority,
        interpretation,
        HistoricalCostQualificationState.UNRESOLVED,
        "actual_or_native_cost_claim_requires_timestamped_quote_or_execution",
    )


def qualify_historical_cost_criterion(
    index: LocalIndex | LocalIndexView,
    *,
    completion_record_id: str,
    criterion: HistoricalCostSemanticCriterion | str,
    interpretation: HistoricalCostInterpretation,
) -> HistoricalCostQualification | None:
    authority = _direct_completion_cost_authority(index, completion_record_id)
    if authority is None:
        return None
    if not isinstance(interpretation, HistoricalCostInterpretation):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost criterion interpretation is not typed"
        )
    if not authority.scientific:
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE,
            "engineering_completion_has_no_scientific_cost_claim",
        )
    if isinstance(criterion, HistoricalCostSemanticCriterion):
        normalized = criterion
    else:
        _claims_for_completion, bindings = (
            _current_completion_claims_and_criteria(
                index,
                completion_record_id,
            )
        )
        normalized = normalized_criterion(criterion, bindings)
    if normalized is None:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost criterion is not a recognized cost criterion"
        )
    if normalized is HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION:
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.DIAGNOSTIC_ONLY,
            "completed_bar_zero_repair_does_not_prove_actual_cost_known",
        )
    if (
        interpretation is HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY
        and normalized
        in {
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
            HistoricalCostSemanticCriterion.C02_STRESS_RESILIENCE,
            HistoricalCostSemanticCriterion.C05_FIXED_LOT_PROFIT_FACTOR,
        }
    ):
        return _qualification(
            authority,
            interpretation,
            HistoricalCostQualificationState.PRESERVED_EXACT_PROXY_ONLY,
            "criterion_is_exact_only_for_completed_period_proxy",
            proxy_only=True,
        )
    return _qualification(
        authority,
        interpretation,
        HistoricalCostQualificationState.UNRESOLVED,
        "point_in_time_native_cost_meaning_requires_timestamped_quote_or_execution",
    )


def effective_historical_negative_memory_cost_authority(
    index: LocalIndex | LocalIndexView,
    negative_memory_id: str,
) -> HistoricalNegativeMemoryCostAuthority | None:
    """Resolve one negative memory and only its exact evidence references."""

    if type(negative_memory_id) is not str or not negative_memory_id.startswith(
        "negative-memory:"
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost negative-memory id is malformed"
        )
    memory = index.get("negative-memory", negative_memory_id)
    if memory is None:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost negative memory is unavailable"
        )
    references = memory.payload.get("evidence_references")
    if (
        memory.status != "durable"
        or not isinstance(references, list)
        or not references
        or references != sorted(set(references))
        or any(type(value) is not str for value in references)
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost negative-memory evidence is malformed"
        )
    authorities = tuple(
        value
        for completion_id in references
        if (
            value := _direct_completion_cost_authority(index, completion_id)
        )
        is not None
    )
    if not authorities:
        return None
    if any(
        negative_memory_id not in authority.negative_memory_ids
        for authority in authorities
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost negative memory is absent from its frozen member"
        )
    latch_ids = {authority.latch_record_id for authority in authorities}
    if len(latch_ids) != 1:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost negative memory spans different latch authority"
        )
    return HistoricalNegativeMemoryCostAuthority(
        negative_memory_id=negative_memory_id,
        latch_record_id=next(iter(latch_ids)),
        affected_completion_ids=tuple(
            sorted(authority.completion_record_id for authority in authorities)
        ),
        preserved_independent_scopes=tuple(
            sorted(
                {
                    scope
                    for authority in authorities
                    for scope in authority.preserved_independent_scopes
                }
            )
        ),
    )


__all__ = [
    "HistoricalCompletionCostAuthority",
    "HistoricalCostQualification",
    "HistoricalCostSemanticsProjectionError",
    "HistoricalNegativeMemoryCostAuthority",
    "current_historical_cost_semantics_activation",
    "effective_historical_completion_cost_authority",
    "effective_historical_negative_memory_cost_authority",
    "qualify_historical_cost_claim",
    "qualify_historical_cost_criterion",
]
