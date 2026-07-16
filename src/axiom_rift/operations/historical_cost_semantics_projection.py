"""Full-history audit and activation for historical spread-cost semantics.

Routine consumers use ``historical_cost_semantics_reader`` and never depend on
this inventory-scanning audit surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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
    adjudication_claims_and_criteria as _adjudication_claims_and_criteria,
    at_or_before as _at_or_before,
    class_for_study as _class_for_study,
    completion_claims as _claims,
    completion_join as _completion_join,
    is_spread_cost_contract as _is_spread_cost_contract,
    normalized_criterion as _normalized_bound_criterion,
    preserved_independent_scopes as _preserved_independent_scopes,
    record_cursor as _record_cursor,
)
from axiom_rift.operations.historical_cost_semantics_reader import (
    HistoricalCompletionCostAuthority,
    HistoricalNegativeMemoryCostAuthority,
    _current_latch_head,
    current_historical_cost_semantics_activation,
    effective_historical_completion_cost_authority,
    effective_historical_negative_memory_cost_authority,
    qualify_historical_cost_claim,
    qualify_historical_cost_criterion,
)
from axiom_rift.research.historical_cost_semantics import (
    CAUSAL_INVALID_COMPLETION_IDS,
    CAUSAL_INVALID_STUDY_CONTEXT_IDS,
    EXCEPTIONAL_STUDY_CLASSES,
    GOLDEN_CLASS_COMPLETION_SEALS,
    GOLDEN_INVENTORY_SEALS,
    HistoricalAuthorityCursor,
    HistoricalCostInterpretation,
    HistoricalCostQualificationState,
    HistoricalCostSemanticCriterion,
    HistoricalCostSemanticsLatch,
    HistoricalInventorySeal,
    HistoricalSpreadSemanticClass,
    HistoricalSpreadSemanticsAuditManifest,
    PRODUCTION_UPPER_CURSOR,
    historical_inventory_digest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


@dataclass(frozen=True, slots=True, order=True)
class HistoricalSpreadCompletionMember:
    """One exact completion reached through declaration-subject authority."""

    completion_record_id: str
    job_id: str
    job_declaration_record_id: str
    executable_id: str
    trial_record_id: str
    completion_study_id: str
    registration_study_id: str
    cost_contract: str
    semantic_class: HistoricalSpreadSemanticClass
    scientific: bool
    claim_ids: tuple[str, ...]
    criterion_bindings: tuple[HistoricalCriterionBinding, ...]
    adjudication_record_ids: tuple[str, ...]
    negative_memory_ids: tuple[str, ...]
    authority_sequence: int
    authority_event_id: str
    authority_offset: int


@dataclass(frozen=True, slots=True)
class HistoricalCompletionCostQualification:
    completion_record_id: str
    semantic_class: HistoricalSpreadSemanticClass
    scientific: bool
    permitted_interpretation: HistoricalCostInterpretation
    forbidden_interpretation: HistoricalCostInterpretation
    preserved_independent_scopes: tuple[str, ...]
    preserved_proxy_criteria: tuple[HistoricalCostSemanticCriterion, ...]
    unresolved_criteria: tuple[HistoricalCostSemanticCriterion, ...]
    diagnostic_criteria: tuple[HistoricalCostSemanticCriterion, ...]


@dataclass(frozen=True, slots=True)
class HistoricalSpreadAuditSlice:
    """Unsealed audit derivation; it is not authority until golden-checked."""

    upper_authority_cursor: HistoricalAuthorityCursor
    audited_cost_contracts: tuple[str, ...]
    members: tuple[HistoricalSpreadCompletionMember, ...]
    study_operation_record_ids: tuple[str, ...]
    adjudication_record_ids: tuple[str, ...]
    negative_memory_ids: tuple[str, ...]
    inventory_seals: tuple[HistoricalInventorySeal, ...]
    class_completion_seals: tuple[HistoricalInventorySeal, ...]


@dataclass(frozen=True, slots=True)
class HistoricalSpreadSemanticsProjection:
    """Golden frozen inventory plus reader-facing qualification operations."""

    audit_manifest: HistoricalSpreadSemanticsAuditManifest
    latch: HistoricalCostSemanticsLatch
    members: tuple[HistoricalSpreadCompletionMember, ...]
    study_operation_record_ids: tuple[str, ...]
    adjudication_record_ids: tuple[str, ...]
    negative_memory_ids: tuple[str, ...]

    def member(
        self,
        completion_record_id: str,
    ) -> HistoricalSpreadCompletionMember | None:
        for item in self.members:
            if item.completion_record_id == completion_record_id:
                return item
        return None

    def require_member(
        self,
        completion_record_id: str,
    ) -> HistoricalSpreadCompletionMember:
        item = self.member(completion_record_id)
        if item is None:
            raise HistoricalCostSemanticsProjectionError(
                "completion is not a member of the frozen spread-cost audit"
            )
        return item

    def completion_qualification(
        self,
        completion_record_id: str,
    ) -> HistoricalCompletionCostQualification:
        member = self.require_member(completion_record_id)
        if not member.scientific:
            return HistoricalCompletionCostQualification(
                completion_record_id=completion_record_id,
                semantic_class=member.semantic_class,
                scientific=False,
                permitted_interpretation=(
                    HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY
                ),
                forbidden_interpretation=(
                    HistoricalCostInterpretation.ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
                ),
                preserved_independent_scopes=(),
                preserved_proxy_criteria=(),
                unresolved_criteria=(),
                diagnostic_criteria=(),
            )
        independent = _preserved_independent_scopes(member.semantic_class)
        return HistoricalCompletionCostQualification(
            completion_record_id=completion_record_id,
            semantic_class=member.semantic_class,
            scientific=True,
            permitted_interpretation=(
                HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY
            ),
            forbidden_interpretation=(
                HistoricalCostInterpretation.ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
            ),
            preserved_independent_scopes=independent,
            preserved_proxy_criteria=(
                HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
                HistoricalCostSemanticCriterion.C02_STRESS_RESILIENCE,
                HistoricalCostSemanticCriterion.C05_FIXED_LOT_PROFIT_FACTOR,
            ),
            unresolved_criteria=(
                HistoricalCostSemanticCriterion.C03_DECISION_TIME_CAUSALITY,
            ),
            diagnostic_criteria=(
                HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION,
            ),
        )

    def qualify_criterion(
        self,
        completion_record_id: str,
        criterion: HistoricalCostSemanticCriterion | str,
        *,
        interpretation: HistoricalCostInterpretation,
    ) -> HistoricalCostQualification:
        member = self.require_member(completion_record_id)
        if not isinstance(interpretation, HistoricalCostInterpretation):
            raise HistoricalCostSemanticsProjectionError(
                "cost interpretation must be typed"
            )
        if not member.scientific:
            return _qualification(
                member,
                interpretation,
                HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE,
                "engineering_completion_has_no_scientific_cost_claim",
            )
        normalized = _normalized_criterion(member, criterion)
        if normalized is HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION:
            return _qualification(
                member,
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
                member,
                interpretation,
                HistoricalCostQualificationState.PRESERVED_EXACT_PROXY_ONLY,
                "original_comparison_state_is_exact_only_for_completed_period_proxy",
                proxy_only=True,
            )
        return _qualification(
            member,
            interpretation,
            HistoricalCostQualificationState.UNRESOLVED,
            "point_in_time_native_cost_meaning_requires_timestamped_quote_or_execution",
        )

    def qualify_claim(
        self,
        completion_record_id: str,
        claim_id: str,
        *,
        interpretation: HistoricalCostInterpretation,
    ) -> HistoricalCostQualification:
        member = self.require_member(completion_record_id)
        if type(claim_id) is not str or not claim_id or not claim_id.isascii():
            raise HistoricalCostSemanticsProjectionError(
                "claim id must be non-empty ASCII"
            )
        if not isinstance(interpretation, HistoricalCostInterpretation):
            raise HistoricalCostSemanticsProjectionError(
                "cost interpretation must be typed"
            )
        if not member.scientific:
            return _qualification(
                member,
                interpretation,
                HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE,
                "engineering_completion_has_no_scientific_cost_claim",
            )
        independent = self.completion_qualification(
            completion_record_id
        ).preserved_independent_scopes
        if claim_id in independent:
            return _qualification(
                member,
                interpretation,
                HistoricalCostQualificationState.PRESERVED_INDEPENDENT,
                "claim_scope_is_independent_of_completed_period_cost_meaning",
            )
        if claim_id not in member.claim_ids:
            raise HistoricalCostSemanticsProjectionError(
                "claim is not bound to the frozen completion"
            )
        return _qualification(
            member,
            interpretation,
            HistoricalCostQualificationState.UNRESOLVED,
            "historical_claim_depends_on_actual_or_native_cost_meaning",
        )


def _qualification(
    member: HistoricalSpreadCompletionMember,
    interpretation: HistoricalCostInterpretation,
    state: HistoricalCostQualificationState,
    reason: str,
    *,
    proxy_only: bool = False,
) -> HistoricalCostQualification:
    return HistoricalCostQualification(
        completion_record_id=member.completion_record_id,
        semantic_class=member.semantic_class,
        interpretation=interpretation,
        state=state,
        reason=reason,
        proxy_only=proxy_only,
    )


def _normalized_criterion(
    member: HistoricalSpreadCompletionMember,
    criterion: HistoricalCostSemanticCriterion | str,
) -> HistoricalCostSemanticCriterion | None:
    return _normalized_bound_criterion(criterion, member.criterion_bindings)


def _require_boundary(
    index: LocalIndex | LocalIndexView,
    upper: HistoricalAuthorityCursor,
) -> None:
    boundary = index.get("journal-event", upper.event_id)
    if (
        boundary is None
        or boundary.record_id != upper.event_id
        or boundary.event_stream != "control"
        or boundary.event_sequence != upper.sequence
        or _record_cursor(boundary) != upper
    ):
        raise HistoricalCostSemanticsProjectionError(
            "spread audit upper authority cursor is not authenticated"
        )
    head = index.event_head("control")
    if head is None or head.sequence < upper.sequence:
        raise HistoricalCostSemanticsProjectionError(
            "local projection trails the spread audit boundary"
        )
    if head.sequence == upper.sequence and (
        head.record_id != upper.event_id or head.record_kind != "journal-event"
    ):
        raise HistoricalCostSemanticsProjectionError(
            "local projection has another record at the spread audit boundary"
        )


def _seal(inventory_class: str, record_ids: tuple[str, ...]) -> HistoricalInventorySeal:
    resolved = tuple(sorted(record_ids))
    if len(resolved) != len(set(resolved)):
        raise HistoricalCostSemanticsProjectionError(
            f"{inventory_class} inventory contains duplicates"
        )
    return HistoricalInventorySeal(
        inventory_class=inventory_class,
        record_count=len(resolved),
        record_ids_digest=historical_inventory_digest(inventory_class, resolved),
    )


def _study_operation_ids(
    index: LocalIndex | LocalIndexView,
    study_ids: tuple[str, ...],
    upper: HistoricalAuthorityCursor,
) -> tuple[str, ...]:
    """Return exact Study-open records after verifying their Writer operations."""

    study_open_ids: list[str] = []
    for study_id in study_ids:
        study = index.get("study-open", study_id)
        if study is None or not _at_or_before(study, upper):
            raise HistoricalCostSemanticsProjectionError(
                "B-only Study operation lost its exact Study open"
            )
        operations = index.records_by_kind_at_authority_sequence(
            "operation",
            study.authority_sequence,  # type: ignore[arg-type]
        )
        matches = [
            item
            for item in operations
            if item.authority_event_id == study.authority_event_id
            and item.payload.get("event_kind") == "study_opened"
            and isinstance(item.payload.get("result"), Mapping)
            and item.payload["result"].get("study_id") == study_id
        ]
        if len(matches) != 1:
            raise HistoricalCostSemanticsProjectionError(
                "B-only Study open lacks one exact Writer operation"
            )
        study_open_ids.append(study.record_id)
    return tuple(sorted(study_open_ids))


def derive_historical_spread_semantics_audit_slice(
    index: LocalIndex | LocalIndexView,
    *,
    upper_authority_cursor: HistoricalAuthorityCursor = PRODUCTION_UPPER_CURSOR,
    causal_invalid_completion_ids: tuple[str, ...] = CAUSAL_INVALID_COMPLETION_IDS,
    causal_invalid_study_context_ids: tuple[str, ...] = (
        CAUSAL_INVALID_STUDY_CONTEXT_IDS
    ),
    exceptional_study_classes: Mapping[
        HistoricalSpreadSemanticClass, tuple[str, ...]
    ] = EXCEPTIONAL_STUDY_CLASSES,
) -> HistoricalSpreadAuditSlice:
    """Rederive the frozen audit from index records without creating authority."""

    if not isinstance(index, (LocalIndex, LocalIndexView)):
        raise HistoricalCostSemanticsProjectionError(
            "spread audit requires a LocalIndex read capability"
        )
    if not isinstance(upper_authority_cursor, HistoricalAuthorityCursor):
        raise HistoricalCostSemanticsProjectionError(
            "spread audit upper cursor is not typed"
        )
    excluded = tuple(sorted(causal_invalid_completion_ids))
    if len(excluded) != len(set(excluded)):
        raise HistoricalCostSemanticsProjectionError(
            "causal invalid completion exclusions are not unique"
        )
    excluded_studies = tuple(sorted(causal_invalid_study_context_ids))
    if len(excluded_studies) != len(set(excluded_studies)):
        raise HistoricalCostSemanticsProjectionError(
            "causal invalid Study context exclusions are not unique"
        )
    _require_boundary(index, upper_authority_cursor)
    raw: list[
        tuple[IndexRecord, IndexRecord, IndexRecord, str, str, bool]
    ] = []
    observed_contracts: set[str] = set()
    spread_completion_ids: set[str] = set()
    spread_study_ids: set[str] = set()
    for trial in index.records_by_kind("trial"):
        if not _at_or_before(trial, upper_authority_cursor):
            continue
        executable = trial.payload.get("executable")
        cost_contract = (
            executable.get("cost_contract")
            if isinstance(executable, Mapping)
            else None
        )
        study_id = trial.payload.get("study_id")
        if (
            type(cost_contract) is str
            and type(study_id) is str
            and _is_spread_cost_contract(cost_contract)
        ):
            observed_contracts.add(cost_contract)
            spread_study_ids.add(study_id)
    for completion in index.records_by_kind("job-completed"):
        if not _at_or_before(completion, upper_authority_cursor):
            continue
        job_id = completion.payload.get("job_id")
        declaration = (
            index.get("job-declared", job_id) if type(job_id) is str else None
        )
        spec = None if declaration is None else declaration.payload.get("spec")
        subject = (
            None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
        )
        if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
            continue
        declaration, trial, executable_id, _executable, cost_contract = (
            _completion_join(index, completion, upper_authority_cursor)
        )
        if not _is_spread_cost_contract(cost_contract):
            continue
        observed_contracts.add(cost_contract)
        spread_completion_ids.add(completion.record_id)
        completion_study_id = declaration.payload.get("study_id")
        if type(completion_study_id) is not str:
            raise HistoricalCostSemanticsProjectionError(
                "spread completion declaration lacks its Study context"
            )
        spread_study_ids.add(completion_study_id)
        if completion.record_id in excluded:
            continue
        raw.append(
            (
                completion,
                declaration,
                trial,
                executable_id,
                cost_contract,
                isinstance(completion.payload.get("scientific"), Mapping),
            )
        )
    if set(excluded) - spread_completion_ids:
        raise HistoricalCostSemanticsProjectionError(
            "causal invalid exclusion is absent from the frozen spread inventory"
        )
    if set(excluded_studies) - spread_study_ids:
        raise HistoricalCostSemanticsProjectionError(
            "causal invalid Study context is absent from the spread inventory"
        )

    scientific_completion_ids = {
        completion.record_id
        for completion, _declaration, _trial, _eid, _cost, scientific in raw
        if scientific
    }
    adjudications_by_completion: dict[str, list[IndexRecord]] = {}
    adjudication_ids: list[str] = []
    for adjudication in index.records_by_kind("historical-scientific-adjudication"):
        if not _at_or_before(adjudication, upper_authority_cursor):
            continue
        completion_id = adjudication.payload.get("completion_record_id")
        if completion_id in scientific_completion_ids:
            adjudications_by_completion.setdefault(completion_id, []).append(
                adjudication
            )
            adjudication_ids.append(adjudication.record_id)

    memories_by_completion: dict[str, list[str]] = {}
    negative_memory_ids: list[str] = []
    for memory in index.records_by_kind("negative-memory"):
        if not _at_or_before(memory, upper_authority_cursor):
            continue
        references = memory.payload.get("evidence_references")
        if not isinstance(references, list):
            continue
        if any(type(item) is not str for item in references):
            raise HistoricalCostSemanticsProjectionError(
                "negative memory evidence references are malformed"
            )
        matches = sorted(set(references) & scientific_completion_ids)
        if len(matches) > 1:
            raise HistoricalCostSemanticsProjectionError(
                "negative memory spans multiple B-only completions"
            )
        if matches:
            memories_by_completion.setdefault(matches[0], []).append(memory.record_id)
            negative_memory_ids.append(memory.record_id)

    rules = dict(exceptional_study_classes)
    members: list[HistoricalSpreadCompletionMember] = []
    for completion, declaration, trial, executable_id, cost_contract, scientific in raw:
        completion_study = declaration.payload["study_id"]
        registration_study = trial.payload["study_id"]
        claim_ids: tuple[str, ...] = ()
        criterion_bindings: tuple[HistoricalCriterionBinding, ...] = ()
        related_adjudications = tuple(
            sorted(adjudications_by_completion.get(completion.record_id, ()))
        )
        adjudication_record_ids_for_completion = tuple(
            item.record_id for item in related_adjudications
        )
        if scientific:
            scientific_payload = completion.payload["scientific"]
            assert isinstance(scientific_payload, Mapping)
            claim_ids = _claims(scientific_payload, declaration)
            direct_claims, direct_criteria = _adjudication_claims_and_criteria(
                scientific_payload.get("adjudication")
            )
            historical_claims: set[str] = set()
            historical_criteria: tuple[HistoricalCriterionBinding, ...] = ()
            for item in related_adjudications:
                parsed_claims, parsed_criteria = _adjudication_claims_and_criteria(
                    item.payload.get("adjudication")
                )
                historical_claims.update(parsed_claims)
                if historical_criteria and parsed_criteria != historical_criteria:
                    raise HistoricalCostSemanticsProjectionError(
                        "historical cost adjudication criteria disagree within "
                        "a completion"
                    )
                historical_criteria = parsed_criteria
            claim_ids = tuple(
                sorted(set(claim_ids) | set(direct_claims) | historical_claims)
            )
            if direct_criteria and historical_criteria and direct_criteria != (
                historical_criteria
            ):
                raise HistoricalCostSemanticsProjectionError(
                    "direct and historical cost criteria disagree"
                )
            criterion_bindings = direct_criteria or historical_criteria
        cursor = _record_cursor(completion)
        members.append(
            HistoricalSpreadCompletionMember(
                completion_record_id=completion.record_id,
                job_id=completion.payload["job_id"],
                job_declaration_record_id=declaration.record_id,
                executable_id=executable_id,
                trial_record_id=trial.record_id,
                completion_study_id=completion_study,
                registration_study_id=registration_study,
                cost_contract=cost_contract,
                semantic_class=_class_for_study(
                    completion_study,
                    scientific=scientific,
                    rules=rules,
                ),
                scientific=scientific,
                claim_ids=claim_ids,
                criterion_bindings=criterion_bindings,
                adjudication_record_ids=adjudication_record_ids_for_completion,
                negative_memory_ids=tuple(
                    sorted(memories_by_completion.get(completion.record_id, ()))
                ),
                authority_sequence=cursor.sequence,
                authority_event_id=cursor.event_id,
                authority_offset=cursor.offset,
            )
        )
    members_tuple = tuple(sorted(members))
    completion_ids = tuple(item.completion_record_id for item in members_tuple)
    scientific_members = tuple(item for item in members_tuple if item.scientific)
    scientific_ids = tuple(item.completion_record_id for item in scientific_members)
    executable_ids = tuple(sorted({item.executable_id for item in scientific_members}))
    study_ids = tuple(sorted(spread_study_ids - set(excluded_studies)))
    study_operations = _study_operation_ids(
        index,
        study_ids,
        upper_authority_cursor,
    )
    aggregate_seals = tuple(
        sorted(
            (
                _seal("adjudication", tuple(sorted(adjudication_ids))),
                _seal("b_only_study_operations", study_operations),
                _seal("completion", completion_ids),
                _seal("negative_memory", tuple(sorted(negative_memory_ids))),
                _seal("scientific_completion", scientific_ids),
                _seal("scientific_executable", executable_ids),
            )
        )
    )
    class_seals = tuple(
        sorted(
            _seal(
                semantic_class.value,
                tuple(
                    item.completion_record_id
                    for item in members_tuple
                    if item.semantic_class is semantic_class
                ),
            )
            for semantic_class in HistoricalSpreadSemanticClass
        )
    )
    return HistoricalSpreadAuditSlice(
        upper_authority_cursor=upper_authority_cursor,
        audited_cost_contracts=tuple(sorted(observed_contracts)),
        members=members_tuple,
        study_operation_record_ids=study_operations,
        adjudication_record_ids=tuple(sorted(adjudication_ids)),
        negative_memory_ids=tuple(sorted(negative_memory_ids)),
        inventory_seals=aggregate_seals,
        class_completion_seals=class_seals,
    )


def build_historical_spread_semantics_audit_manifest(
    index: LocalIndex | LocalIndexView,
    *,
    audit_artifact_hash: str,
) -> HistoricalSpreadSemanticsAuditManifest:
    """Build the one production manifest only after exact golden rederivation."""

    audit_slice = derive_historical_spread_semantics_audit_slice(index)
    if audit_slice.inventory_seals != GOLDEN_INVENTORY_SEALS:
        raise HistoricalCostSemanticsProjectionError(
            "historical spread aggregate inventory differs from golden authority"
        )
    if audit_slice.class_completion_seals != GOLDEN_CLASS_COMPLETION_SEALS:
        raise HistoricalCostSemanticsProjectionError(
            "historical spread semantic classes differ from golden authority"
        )
    return HistoricalSpreadSemanticsAuditManifest(
        audit_artifact_hash=audit_artifact_hash,
        upper_authority_cursor=audit_slice.upper_authority_cursor,
        causal_invalid_completion_ids=CAUSAL_INVALID_COMPLETION_IDS,
        causal_invalid_study_context_ids=CAUSAL_INVALID_STUDY_CONTEXT_IDS,
        audited_cost_contracts=audit_slice.audited_cost_contracts,
        exceptional_study_classes=tuple(
            sorted(EXCEPTIONAL_STUDY_CLASSES.items(), key=lambda item: item[0].value)
        ),
        inventory_seals=audit_slice.inventory_seals,
        class_completion_seals=audit_slice.class_completion_seals,
    )


def validate_historical_cost_semantics_latch_binding(
    index: LocalIndex | LocalIndexView,
    latch: HistoricalCostSemanticsLatch,
    manifest: HistoricalSpreadSemanticsAuditManifest,
) -> HistoricalSpreadAuditSlice:
    """Recompute every frozen inventory and bind the latch to the manifest."""

    if (
        not isinstance(latch, HistoricalCostSemanticsLatch)
        or not isinstance(manifest, HistoricalSpreadSemanticsAuditManifest)
        or latch.audit_manifest_hash != manifest.artifact_hash
        or latch.audit_manifest_identity != manifest.identity
        or latch.upper_authority_cursor != manifest.upper_authority_cursor
        or latch.inventory_seals != manifest.inventory_seals
        or latch.class_completion_seals != manifest.class_completion_seals
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch does not bind the exact audit manifest"
        )
    audit_slice = derive_historical_spread_semantics_audit_slice(
        index,
        upper_authority_cursor=manifest.upper_authority_cursor,
        causal_invalid_completion_ids=manifest.causal_invalid_completion_ids,
        causal_invalid_study_context_ids=(
            manifest.causal_invalid_study_context_ids
        ),
        exceptional_study_classes=dict(manifest.exceptional_study_classes),
    )
    if (
        audit_slice.audited_cost_contracts != manifest.audited_cost_contracts
        or audit_slice.inventory_seals != manifest.inventory_seals
        or audit_slice.class_completion_seals != manifest.class_completion_seals
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost latch rederivation differs from its frozen manifest"
        )
    return audit_slice


def historical_cost_semantics_latch_record(
    latch: HistoricalCostSemanticsLatch,
    *,
    sequence: int = 1,
) -> IndexRecord:
    if not isinstance(latch, HistoricalCostSemanticsLatch):
        raise TypeError("historical cost semantics latch is not typed")
    if sequence != 1:
        raise ValueError("historical cost semantics latch must be stream sequence one")
    return IndexRecord(
        kind=LATCH_RECORD_KIND,
        record_id=latch.identity,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="latched",
        fingerprint=latch.identity.removeprefix(
            "historical-cost-semantics-latch:"
        ),
        payload=latch.to_payload(),
        event_stream=LATCH_STREAM,
        event_sequence=sequence,
    )


def _completion_scope_payload(
    latch: HistoricalCostSemanticsLatch,
    member: HistoricalSpreadCompletionMember,
) -> dict[str, Any]:
    return {
        "completion_record_id": member.completion_record_id,
        "executable_id": member.executable_id,
        "latch_record_id": latch.identity,
        "negative_memory_ids": list(member.negative_memory_ids),
        "schema": COMPLETION_SCOPE_SCHEMA,
        "scientific": member.scientific,
        "semantic_class": member.semantic_class.value,
        "study_id": member.completion_study_id,
    }


def historical_cost_semantics_completion_record(
    latch: HistoricalCostSemanticsLatch,
    member: HistoricalSpreadCompletionMember,
) -> IndexRecord:
    """Materialize one keyed completion member in the latch Writer event."""

    if not isinstance(latch, HistoricalCostSemanticsLatch) or not isinstance(
        member, HistoricalSpreadCompletionMember
    ):
        raise TypeError("historical cost completion projection is not typed")
    payload = _completion_scope_payload(latch, member)
    fingerprint = canonical_digest(
        domain="historical-cost-semantics-completion",
        payload=payload,
    )
    return IndexRecord(
        kind=COMPLETION_SCOPE_RECORD_KIND,
        record_id=member.completion_record_id,
        subject=f"JobCompletion:{member.completion_record_id}",
        status=("qualified" if member.scientific else "engineering"),
        fingerprint=fingerprint,
        payload=payload,
    )


def historical_cost_semantics_activation_records(
    latch: HistoricalCostSemanticsLatch,
    audit_slice: HistoricalSpreadAuditSlice,
) -> tuple[IndexRecord, ...]:
    """Return the latch plus its complete keyed completion projection.

    Full-history classification happens once before the Writer event.  Routine
    consumers subsequently use one event-head lookup and direct record keys.
    """

    if not isinstance(latch, HistoricalCostSemanticsLatch) or not isinstance(
        audit_slice, HistoricalSpreadAuditSlice
    ):
        raise TypeError("historical cost activation inputs are not typed")
    completion_ids = tuple(
        member.completion_record_id for member in audit_slice.members
    )
    completion_seal = next(
        (
            item
            for item in latch.inventory_seals
            if item.inventory_class == "completion"
        ),
        None,
    )
    if (
        completion_ids != tuple(sorted(set(completion_ids)))
        or completion_seal is None
        or completion_seal.record_count != len(completion_ids)
        or completion_seal.record_ids_digest
        != historical_inventory_digest("completion", completion_ids)
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost keyed completion inventory differs from its latch"
        )
    records = tuple(
        historical_cost_semantics_completion_record(latch, member)
        for member in audit_slice.members
    )
    if len({(record.kind, record.record_id) for record in records}) != len(records):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost keyed completion inventory is ambiguous"
        )
    return (historical_cost_semantics_latch_record(latch), *records)


def current_historical_cost_semantics_latch(
    index: LocalIndex | LocalIndexView,
    manifest: HistoricalSpreadSemanticsAuditManifest,
) -> HistoricalCostSemanticsLatch | None:
    """Explicitly audit the latch against its complete frozen manifest."""

    resolved = _current_latch_head(index)
    if resolved is None:
        return None
    latch, latch_record = resolved
    audit_slice = validate_historical_cost_semantics_latch_binding(
        index,
        latch,
        manifest,
    )
    expected_records = historical_cost_semantics_activation_records(
        latch,
        audit_slice,
    )[1:]
    actual_records = index.records_by_kind(COMPLETION_SCOPE_RECORD_KIND)
    expected_by_id = {record.record_id: record for record in expected_records}
    actual_by_id = {record.record_id: record for record in actual_records}
    if (
        len(expected_by_id) != len(expected_records)
        or len(actual_by_id) != len(actual_records)
        or set(actual_by_id) != set(expected_by_id)
    ):
        raise HistoricalCostSemanticsProjectionError(
            "historical cost keyed completion inventory is incomplete or extra"
        )
    latch_cursor = _record_cursor(latch_record)
    for completion_id, expected in expected_by_id.items():
        actual = actual_by_id[completion_id]
        if (
            actual.kind != expected.kind
            or actual.record_id != expected.record_id
            or actual.subject != expected.subject
            or actual.status != expected.status
            or actual.fingerprint != expected.fingerprint
            or dict(actual.payload) != dict(expected.payload)
            or actual.event_stream is not None
            or actual.event_sequence is not None
            or _record_cursor(actual) != latch_cursor
        ):
            raise HistoricalCostSemanticsProjectionError(
                "historical cost keyed completion member is not same-event canonical"
            )
    return latch


def historical_spread_semantics_projection(
    index: LocalIndex | LocalIndexView,
    manifest: HistoricalSpreadSemanticsAuditManifest,
    *,
    latch: HistoricalCostSemanticsLatch | None = None,
    require_recorded_latch: bool = True,
) -> HistoricalSpreadSemanticsProjection:
    """Return the reader projection only from a valid typed latch."""

    if require_recorded_latch:
        recorded = current_historical_cost_semantics_latch(index, manifest)
        if recorded is None:
            raise HistoricalCostSemanticsProjectionError(
                "historical cost semantics latch is not recorded"
            )
        if latch is not None and latch != recorded:
            raise HistoricalCostSemanticsProjectionError(
                "caller latch differs from the authenticated current head"
            )
        latch = recorded
    if latch is None:
        raise HistoricalCostSemanticsProjectionError(
            "historical cost semantics projection requires a typed latch"
        )
    audit_slice = validate_historical_cost_semantics_latch_binding(
        index,
        latch,
        manifest,
    )
    return HistoricalSpreadSemanticsProjection(
        audit_manifest=manifest,
        latch=latch,
        members=audit_slice.members,
        study_operation_record_ids=audit_slice.study_operation_record_ids,
        adjudication_record_ids=audit_slice.adjudication_record_ids,
        negative_memory_ids=audit_slice.negative_memory_ids,
    )


__all__ = [
    "COMPLETION_SCOPE_RECORD_KIND",
    "COMPLETION_SCOPE_SCHEMA",
    "HistoricalCompletionCostQualification",
    "HistoricalCompletionCostAuthority",
    "HistoricalCostQualification",
    "HistoricalCostSemanticsProjectionError",
    "HistoricalCriterionBinding",
    "HistoricalNegativeMemoryCostAuthority",
    "HistoricalSpreadAuditSlice",
    "HistoricalSpreadCompletionMember",
    "HistoricalSpreadSemanticsProjection",
    "LATCH_EVENT_KIND",
    "LATCH_RECORD_KIND",
    "LATCH_STREAM",
    "build_historical_spread_semantics_audit_manifest",
    "current_historical_cost_semantics_activation",
    "current_historical_cost_semantics_latch",
    "derive_historical_spread_semantics_audit_slice",
    "effective_historical_completion_cost_authority",
    "effective_historical_negative_memory_cost_authority",
    "historical_cost_semantics_activation_records",
    "historical_cost_semantics_completion_record",
    "historical_cost_semantics_latch_record",
    "historical_spread_semantics_projection",
    "qualify_historical_cost_claim",
    "qualify_historical_cost_criterion",
    "validate_historical_cost_semantics_latch_binding",
]
