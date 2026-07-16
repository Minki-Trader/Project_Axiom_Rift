"""Build the exact legacy-v1 spread-time adjudication supersession plan.

The input is the typed 34-completion invalidation inventory.  This module does
not accept completion, adjudication, memory, obligation, or satisfaction IDs
from a caller.  It rejoins every item to the authenticated index, excludes the
eight rich-v2 completions, and derives the 26 legacy-v1 requests from their
current stream heads.  The result is a read-only activation manifest; only the
StateWriter may record it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    current_completion_validity_invalidation,
    validate_completion_validity_invalidation_binding,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.historical_adjudication import (
    HistoricalAdjudicationRequest,
    HistoricalDisposition,
    HistoricalValidityOverride,
    HistoricalValidityReason,
    ReplayPriority,
    profile_manifest,
)
from axiom_rift.research.historical_scientific_validity import (
    NEGATIVE_MEMORY_ROLE,
    HistoricalScientificValidityInvalidation,
)
from axiom_rift.research.historical_spread_time_invalidation_builder import (
    AUDIT_FINDING_ID,
    EXPECTED_COMPLETION_COUNT,
    EXPECTED_STUDY_CONTEXTS,
    HistoricalSpreadTimeInvalidationInventory,
)
from axiom_rift.research.replay_obligation import (
    ReplayResolutionScope,
    ReplaySatisfaction,
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


REQUEST_MANIFEST_SCHEMA = (
    "historical_spread_time_adjudication_supersession_manifest.v1"
)
EXPECTED_LEGACY_COMPLETION_COUNT = 26
EXPECTED_RICH_V2_EXCLUDED_COUNT = 8
EXPECTED_NEGATIVE_MEMORY_COUNT = 26

P0_REPLAY_FAMILY_ID = "p0_revoked_satisfaction_replay"
P1_REPLAY_FAMILY_ID = "p1_timing_validity_replay"
NOT_EVALUABLE_FAMILY_ID = "not_evaluable_source_timing_union"

P0_REPLAY_COMPLETION_IDS = frozenset(
    {
        "9765f44d5c872bcba69cd3838b0758e7978720e3926cadd78e91d42e020eb1d8",
        "731e78ec1fa83c667d0370d600de6b4ced384cde60499fa47f07f04c81047d03",
    }
)
NOT_EVALUABLE_COMPLETION_ID = (
    "0e396a98308e99792591ad8dd1b80b8ce26c69825bb68e00606173dda7a6d3f8"
)

_P0_REPLAY_AUTHORITY = {
    "9765f44d5c872bcba69cd3838b0758e7978720e3926cadd78e91d42e020eb1d8": (
        "historical-replay-obligation:"
        "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e",
        "historical-replay-satisfaction:"
        "6a0d460befc957bad4cb250fdc1a0cb3a74fd7c00ed5643e93f7fc60a59790d4",
    ),
    "731e78ec1fa83c667d0370d600de6b4ced384cde60499fa47f07f04c81047d03": (
        "historical-replay-obligation:"
        "a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904",
        "historical-replay-satisfaction:"
        "6b59a863de2e5f4833ae7dd6786423c7b1642b4c741db1bc10e8357648fdda2f",
    ),
}

# These digests freeze the exact authenticated sequence-5385 semantic slice.
# They intentionally exclude the audit-document hash from the first three
# inventories: prose changes cannot substitute another completion or slice.
_EXPECTED_ALL_INVALIDATION_INVENTORY_DIGEST = (
    "a5f6885fc897359829a79f304719f2f57c48cec1806373dddad99a05fff12bf5"
)
_EXPECTED_LEGACY_INVALIDATION_INVENTORY_DIGEST = (
    "bf65400627185084ad843706964901119a981669dc125e20e5db966bb767517b"
)
_EXPECTED_RICH_V2_INVALIDATION_INVENTORY_DIGEST = (
    "37bdf4d4e336ef96ce2f55a28cbaea3712157735c1ac8423e25f13d564abb950"
)
_EXPECTED_PRIOR_HEAD_INVENTORY_DIGEST = (
    "fcf1e8ee150629518cd902f4cb7c52d59e682d47d97561a95c5ef90fee42cfd6"
)
_EXPECTED_NEGATIVE_MEMORY_INVENTORY_DIGEST = (
    "9687872d95bed1f4821f7bfd8b6d93b671201f3e35ac508fa8bcac4f76d153e0"
)

_P0_REASON_CODES = (
    "accepted_replay_satisfaction_revocation_pending",
    "decision_input_point_in_time_unproven",
    "diagnostic_negative_memory_retained",
)
_P1_REASON_CODES = (
    "decision_input_point_in_time_unproven",
    "diagnostic_negative_memory_retained",
    "prospective_exact_replay_required",
)
_NOT_EVALUABLE_REASON_CODES = (
    "decision_input_point_in_time_unproven",
    "diagnostic_negative_memory_retained",
    "source_and_timing_invalidity_union",
)


class HistoricalSpreadTimeAdjudicationBuilderError(RuntimeError):
    """The frozen 26-request correction plan cannot be derived exactly."""


def _error(message: str) -> HistoricalSpreadTimeAdjudicationBuilderError:
    return HistoricalSpreadTimeAdjudicationBuilderError(message)


def _semantic_inventory_digest(
    class_name: str,
    invalidations: tuple[HistoricalScientificValidityInvalidation, ...],
) -> str:
    entries = [
        {
            "audit_slice_digest": item.audit_slice_digest,
            "completion_record_id": item.completion_record_id,
            "executable_id": item.executable_id,
            "study_id": item.study_id,
        }
        for item in sorted(
            invalidations,
            key=lambda candidate: candidate.completion_record_id,
        )
    ]
    return canonical_digest(
        domain="historical-spread-time-readjudication-inventory",
        payload={"class": class_name, "entries": entries},
    )


def _head_inventory_digest(entries: list[dict[str, object]]) -> str:
    return canonical_digest(
        domain="historical-spread-time-readjudication-heads",
        payload={"entries": entries},
    )


def _negative_memory_inventory_digest(entries: list[dict[str, str]]) -> str:
    return canonical_digest(
        domain="historical-spread-time-readjudication-negative-memories",
        payload={"entries": entries},
    )


def _request_payload(request: HistoricalAdjudicationRequest) -> dict[str, Any]:
    return {
        "completion_record_id": request.completion_record_id,
        "disposition": request.disposition.value,
        "profile": profile_manifest(request.profile),
        "reason_codes": list(request.reason_codes),
        "replay_priority": request.replay_priority.value,
        "validity_overrides": [
            item.manifest() for item in request.validity_overrides
        ],
    }


@dataclass(frozen=True, slots=True)
class HistoricalSpreadTimeAdjudicationMember:
    """One request plus every current authority ID used to derive it."""

    study_id: str
    executable_id: str
    job_id: str
    completion_record_id: str
    invalidation_record_id: str
    prior_adjudication_record_id: str
    prior_adjudication_sequence: int
    prior_adjudication_status: str
    negative_memory_ids: tuple[str, ...]
    request: HistoricalAdjudicationRequest
    replay_obligation_id: str | None = None
    accepted_satisfaction_record_id: str | None = None
    prior_replay_obligation_priority: ReplayPriority | None = None

    def to_manifest_payload(self) -> dict[str, Any]:
        return {
            "accepted_satisfaction_record_id": (
                self.accepted_satisfaction_record_id
            ),
            "completion_record_id": self.completion_record_id,
            "executable_id": self.executable_id,
            "invalidation_record_id": self.invalidation_record_id,
            "job_declaration_record_id": self.job_id,
            "negative_memory_ids": list(self.negative_memory_ids),
            "negative_memory_role": NEGATIVE_MEMORY_ROLE,
            "prior_adjudication_record_id": self.prior_adjudication_record_id,
            "prior_adjudication_sequence": self.prior_adjudication_sequence,
            "prior_adjudication_status": self.prior_adjudication_status,
            "prior_replay_obligation_priority": (
                None
                if self.prior_replay_obligation_priority is None
                else self.prior_replay_obligation_priority.value
            ),
            "replay_obligation_id": self.replay_obligation_id,
            "request": _request_payload(self.request),
            "study_id": self.study_id,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSpreadTimeAdjudicationFamily:
    """A deterministic activation group with one exact policy."""

    family_id: str
    disposition: HistoricalDisposition
    replay_priority: ReplayPriority
    members: tuple[HistoricalSpreadTimeAdjudicationMember, ...]

    @property
    def requests(self) -> tuple[HistoricalAdjudicationRequest, ...]:
        return tuple(member.request for member in self.members)

    def to_manifest_payload(self) -> dict[str, Any]:
        priority_transitions = [
            {
                "from_priority": member.prior_replay_obligation_priority.value,
                "obligation_id": member.replay_obligation_id,
                "to_priority": member.request.replay_priority.value,
            }
            for member in self.members
            if member.prior_replay_obligation_priority is not None
            and member.prior_replay_obligation_priority
            is not member.request.replay_priority
        ]
        return {
            "disposition": self.disposition.value,
            "family_id": self.family_id,
            "member_count": len(self.members),
            "members": [member.to_manifest_payload() for member in self.members],
            "priority_transitions": priority_transitions,
            "replay_priority": self.replay_priority.value,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSpreadTimeAdjudicationPlan:
    """Canonical, read-only 26-request handoff for the activation script."""

    audit_artifact_hash: str
    typed_invalidation_inventory_digest: str
    prior_head_inventory_digest: str
    negative_memory_inventory_digest: str
    excluded_rich_v2_completion_ids: tuple[str, ...]
    families: tuple[HistoricalSpreadTimeAdjudicationFamily, ...]

    @property
    def members(self) -> tuple[HistoricalSpreadTimeAdjudicationMember, ...]:
        return tuple(
            sorted(
                (
                    member
                    for family in self.families
                    for member in family.members
                ),
                key=lambda member: member.completion_record_id,
            )
        )

    @property
    def requests(self) -> tuple[HistoricalAdjudicationRequest, ...]:
        return tuple(member.request for member in self.members)

    def family(
        self,
        family_id: str,
    ) -> HistoricalSpreadTimeAdjudicationFamily:
        matches = [family for family in self.families if family.family_id == family_id]
        if len(matches) != 1:
            raise KeyError(f"unknown readjudication family: {family_id}")
        return matches[0]

    def to_request_manifest_payload(self) -> dict[str, Any]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            "excluded_rich_v2_completion_count": len(
                self.excluded_rich_v2_completion_ids
            ),
            "excluded_rich_v2_completion_ids": list(
                self.excluded_rich_v2_completion_ids
            ),
            "families": [
                family.to_manifest_payload() for family in self.families
            ],
            "negative_memory_count": sum(
                len(member.negative_memory_ids) for member in self.members
            ),
            "negative_memory_inventory_digest": (
                self.negative_memory_inventory_digest
            ),
            "negative_memory_role": NEGATIVE_MEMORY_ROLE,
            "prior_head_inventory_digest": self.prior_head_inventory_digest,
            "request_count": len(self.requests),
            "requests": [_request_payload(request) for request in self.requests],
            "schema": REQUEST_MANIFEST_SCHEMA,
            "typed_invalidation_inventory_digest": (
                self.typed_invalidation_inventory_digest
            ),
        }

    @property
    def request_manifest_digest(self) -> str:
        return canonical_digest(
            domain="historical-spread-time-adjudication-supersession-manifest",
            payload=self.to_request_manifest_payload(),
        )


def _require_current_adjudication_head(
    index: LocalIndex | LocalIndexView,
    invalidation: HistoricalScientificValidityInvalidation,
) -> tuple[IndexRecord, int]:
    stream = f"historical-adjudication:{invalidation.completion_record_id}"
    head = index.event_head(stream)
    record = None if head is None else index.get(head.record_kind, head.record_id)
    payload = None if record is None else record.payload
    if (
        head is None
        or record is None
        or head.sequence != 1
        or record.kind != "historical-scientific-adjudication"
        or record.event_stream != stream
        or record.event_sequence != head.sequence
        or record.record_id != head.record_id
        or record.fingerprint
        != record.record_id.removeprefix("historical-adjudication:")
        or record.subject != f"Study:{invalidation.study_id}"
        or not isinstance(payload, Mapping)
        or payload.get("schema") != "historical_scientific_adjudication.v2"
        or payload.get("completion_record_id")
        != invalidation.completion_record_id
        or payload.get("executable_id") != invalidation.executable_id
        or payload.get("study_id") != invalidation.study_id
        or payload.get("study_close_record_id")
        != invalidation.study_close_record_id
        or payload.get("validation_plan_hash")
        != invalidation.validation_plan_hash
        or payload.get("measurement_artifact_hash")
        != invalidation.measurement_artifact_hash
        or payload.get("disposition") != record.status
        or payload.get("supersedes_record_id") is not None
        or payload.get("candidate_delta") != 0
        or payload.get("holdout_delta") != 0
        or payload.get("trial_delta") != 0
        or payload.get("claim_authority") != "additive_qualification_only"
        or not isinstance(payload.get("adjudication"), Mapping)
        or payload["adjudication"].get("candidate_eligible") is not False
    ):
        raise _error("legacy historical adjudication head is stale or malformed")
    try:
        _event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {"historical_scientific_adjudications_recorded"}
            ),
        )
    except RecordedTransitionAuthorityError as exc:
        raise _error(
            "legacy historical adjudication lacks same-event Writer authority"
        ) from exc
    ids = result.get("adjudication_record_ids")
    if (
        not isinstance(ids, list)
        or record.record_id not in ids
        or len(ids) != len(set(ids))
        or result.get("audit_artifact_hash") != payload.get("audit_artifact_hash")
        or result.get("candidate_delta") != 0
        or result.get("holdout_delta") != 0
        or result.get("trial_delta") != 0
    ):
        raise _error("legacy adjudication Writer result is not exact")
    return record, head.sequence


def _prior_overrides(record: IndexRecord) -> tuple[HistoricalValidityOverride, ...]:
    raw = record.payload.get("validity_overrides")
    if not isinstance(raw, list):
        raise _error("prior historical validity overrides are malformed")
    try:
        overrides = tuple(
            HistoricalValidityOverride(
                reason=HistoricalValidityReason(item["reason"]),
                subject_id=item["subject_id"],
                evidence_record_id=item["evidence_record_id"],
            )
            for item in raw
            if isinstance(item, Mapping)
            and set(item) == {"evidence_record_id", "reason", "subject_id"}
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _error("prior historical validity overrides are malformed") from exc
    if len(overrides) != len(raw) or len(
        {item.subject_id for item in overrides}
    ) != len(overrides):
        raise _error("prior historical validity overrides are malformed")
    return tuple(
        sorted(
            overrides,
            key=lambda item: (
                item.reason.value,
                item.subject_id,
                item.evidence_record_id,
            ),
        )
    )


def _validate_source_override(
    index: LocalIndex | LocalIndexView,
    *,
    override: HistoricalValidityOverride,
    source_contracts: tuple[str, ...],
) -> None:
    if (
        override.reason is not HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
        or override.subject_id not in source_contracts
    ):
        raise _error("prior source validity override is not trial-bound")
    correction = index.get(
        "source-authority-invalidation",
        override.evidence_record_id,
    )
    head = index.event_head(f"source-authority:{override.subject_id}")
    if (
        correction is None
        or head is None
        or head.record_kind != correction.kind
        or head.record_id != correction.record_id
        or head.sequence != correction.event_sequence
        or correction.subject != f"Source:{override.subject_id}"
        or correction.status != "confirmed_and_suspended"
        or correction.event_stream != f"source-authority:{override.subject_id}"
        or correction.record_id != override.evidence_record_id
    ):
        raise _error("prior source validity override lost its current latch")
    try:
        invalidation = SourceAuthorityInvalidation.from_identity_payload(
            correction.payload["invalidation"]
        )
        manifest = SourceAuthorityAuditManifest.from_mapping(
            correction.payload["audit_manifest"]
        )
        latch = SourceAuthorityLatch.from_mapping(correction.payload["latch"])
        expected_latch = SourceAuthorityLatch.bind(
            invalidation=invalidation,
            manifest=manifest,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _error("prior source validity latch is malformed") from exc
    if (
        invalidation.identity != override.evidence_record_id
        or invalidation.source_contract_id != override.subject_id
        or latch != expected_latch
        or latch.invalidation_id != override.evidence_record_id
        or latch.source_contract_id != override.subject_id
    ):
        raise _error("prior source validity latch changed identity")


def _derive_validity_overrides(
    index: LocalIndex | LocalIndexView,
    *,
    invalidation: HistoricalScientificValidityInvalidation,
    trial: IndexRecord,
    prior: IndexRecord,
) -> tuple[HistoricalValidityOverride, ...]:
    executable = trial.payload.get("executable")
    raw_sources = (
        None if not isinstance(executable, Mapping) else executable.get("source_contracts")
    )
    if (
        not isinstance(raw_sources, list)
        or any(type(item) is not str for item in raw_sources)
        or len(raw_sources) != len(set(raw_sources))
    ):
        raise _error("legacy Trial source-contract inventory is malformed")
    source_contracts = tuple(sorted(raw_sources))
    prior_overrides = _prior_overrides(prior)
    by_subject: dict[str, HistoricalValidityOverride] = {}
    for override in prior_overrides:
        if (
            override.reason
            is HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
        ):
            if (
                override.subject_id != invalidation.completion_record_id
                or override.evidence_record_id != invalidation.identity
            ):
                raise _error("prior timing override is not the typed invalidation")
        else:
            _validate_source_override(
                index,
                override=override,
                source_contracts=source_contracts,
            )
        previous = by_subject.setdefault(override.subject_id, override)
        if previous != override:
            raise _error("prior historical validity override conflicts")

    for source_id in source_contracts:
        source_head = index.event_head(f"source-authority:{source_id}")
        if source_head is None:
            continue
        if source_head.record_kind != "source-authority-invalidation":
            raise _error("current source-authority head is malformed")
        override = HistoricalValidityOverride(
            reason=HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
            subject_id=source_id,
            evidence_record_id=source_head.record_id,
        )
        _validate_source_override(
            index,
            override=override,
            source_contracts=source_contracts,
        )
        previous = by_subject.setdefault(source_id, override)
        if previous != override:
            raise _error("source validity override cannot be replaced")

    try:
        completion_head = current_completion_validity_invalidation(
            index,
            invalidation.completion_record_id,
        )
    except CompletionValidityProjectionError as exc:
        raise _error("current completion-validity head is malformed") from exc
    if any(
        item.reason
        is HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
        for item in prior_overrides
    ) and completion_head is None:
        raise _error("prior timing override lacks its committed current head")
    if completion_head is not None and (
        completion_head.invalidation_record_id != invalidation.identity
        or completion_head.invalidation != invalidation
    ):
        raise _error("typed completion invalidation differs from its current head")
    timing = HistoricalValidityOverride(
        reason=HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN,
        subject_id=invalidation.completion_record_id,
        evidence_record_id=invalidation.identity,
    )
    previous = by_subject.setdefault(invalidation.completion_record_id, timing)
    if previous != timing:
        raise _error("completion timing validity override cannot be replaced")
    return tuple(
        sorted(
            by_subject.values(),
            key=lambda item: (
                item.reason.value,
                item.subject_id,
                item.evidence_record_id,
            ),
        )
    )


def _negative_memories(
    index: LocalIndex | LocalIndexView,
    *,
    invalidation: HistoricalScientificValidityInvalidation,
    prior: IndexRecord,
) -> tuple[str, ...]:
    prior_ids = prior.payload.get("negative_memory_ids")
    if (
        not isinstance(prior_ids, list)
        or len(prior_ids) != 1
        or len(prior_ids) != len(set(prior_ids))
    ):
        raise _error("legacy adjudication negative-memory binding changed")
    actual = tuple(
        sorted(
            record.record_id
            for record in index.records_by_subject_status(
                f"Executable:{invalidation.executable_id}",
                "durable",
            )
            if record.kind == "negative-memory"
            and record.payload.get("study_id") == invalidation.study_id
        )
    )
    if tuple(sorted(prior_ids)) != actual or len(actual) != 1:
        raise _error("legacy adjudication lost its exact negative memory")
    memory = index.get("negative-memory", actual[0])
    references = None if memory is None else memory.payload.get("evidence_references")
    if (
        memory is None
        or memory.subject != f"Executable:{invalidation.executable_id}"
        or references != [invalidation.completion_record_id]
        or memory.payload.get("holdout_id") is not None
    ):
        raise _error("negative memory is not bound to the exact completion")
    return actual


def _require_p0_satisfied_replay(
    index: LocalIndex | LocalIndexView,
    *,
    invalidation: HistoricalScientificValidityInvalidation,
    prior: IndexRecord,
) -> tuple[str, str, ReplayPriority]:
    obligation_id, satisfaction_id = _P0_REPLAY_AUTHORITY[
        invalidation.completion_record_id
    ]
    obligation_record = index.get("historical-replay-obligation", obligation_id)
    obligation = (
        None
        if obligation_record is None
        else obligation_record.payload.get("obligation")
    )
    stream = f"historical-replay-obligation:{obligation_id}"
    head = index.event_head(stream)
    satisfaction = None if head is None else index.get(head.record_kind, head.record_id)
    resolution = (
        None
        if satisfaction is None
        else satisfaction.payload.get("resolution")
    )
    if (
        obligation_record is None
        or not isinstance(obligation, Mapping)
        or obligation_record.record_id != obligation_id
        or obligation_record.status != "pending"
        or obligation_record.event_stream != stream
        or obligation_record.event_sequence != 1
        or obligation.get("schema") != "historical_replay_obligation.v1"
        or obligation.get("historical_adjudication_id") != prior.record_id
        or obligation.get("original_completion_record_id")
        != invalidation.completion_record_id
        or obligation.get("original_executable_id") != invalidation.executable_id
        or obligation.get("original_study_id") != invalidation.study_id
        or obligation.get("original_study_close_record_id")
        != invalidation.study_close_record_id
        or obligation.get("replay_priority") != ReplayPriority.P1.value
        or head is None
        or head.sequence != 3
        or head.record_kind != "historical-replay-obligation-resolution"
        or head.record_id != satisfaction_id
        or satisfaction is None
        or satisfaction.status != "satisfied"
        or satisfaction.event_stream != stream
        or satisfaction.event_sequence != head.sequence
        or satisfaction.payload.get("obligation_id") != obligation_id
        or not isinstance(resolution, Mapping)
        or resolution.get("schema") != "historical_replay_satisfaction.v1"
        or resolution.get("obligation_id") != obligation_id
    ):
        raise _error("P0 replay does not bind its accepted satisfaction")
    _require_recorded_satisfaction_authority(
        index,
        obligation_payload=obligation,
        satisfaction=satisfaction,
    )
    return obligation_id, satisfaction_id, ReplayPriority.P1


def _require_recorded_satisfaction_authority(
    index: LocalIndex | LocalIndexView,
    *,
    obligation_payload: Mapping[str, object],
    satisfaction: IndexRecord,
) -> None:
    """Authenticate the stored satisfaction without rerunning old science."""

    from axiom_rift.operations.replay_projection import (
        ReplayProjectionError,
        require_recorded_satisfaction,
    )

    raw = satisfaction.payload.get("resolution")
    if not isinstance(raw, Mapping):
        raise _error("P0 replay satisfaction payload is malformed")
    try:
        obligation = historical_replay_obligation_from_identity_payload(
            obligation_payload
        )
        parsed = ReplaySatisfaction(
            obligation_id=raw["obligation_id"],  # type: ignore[arg-type]
            resolution_scope=ReplayResolutionScope(
                raw["resolution_scope"]  # type: ignore[arg-type]
            ),
            portfolio_decision_id=raw["portfolio_decision_id"],  # type: ignore[arg-type]
            replay_study_id=raw["replay_study_id"],  # type: ignore[arg-type]
            replay_executable_id=raw["replay_executable_id"],  # type: ignore[arg-type]
            replay_study_close_record_id=raw[
                "replay_study_close_record_id"
            ],  # type: ignore[arg-type]
            study_diagnosis_id=raw["study_diagnosis_id"],  # type: ignore[arg-type]
            satisfied_criterion_ids=tuple(
                raw["satisfied_criterion_ids"]  # type: ignore[arg-type]
            ),
            evidence_record_ids=tuple(
                raw["evidence_record_ids"]  # type: ignore[arg-type]
            ),
            remaining_scientific_condition=raw.get(
                "remaining_scientific_condition"
            ),  # type: ignore[arg-type]
        )
        require_recorded_satisfaction(
            index,
            obligation=obligation,
            satisfaction=parsed,
            allow_legacy_decision_binding=True,
            satisfaction_head=satisfaction,
            require_current_head=True,
        )
    except (KeyError, TypeError, ValueError, ReplayProjectionError) as exc:
        raise _error("P0 replay satisfaction lacks recorded authority") from exc


def _policy(
    invalidation: HistoricalScientificValidityInvalidation,
    overrides: tuple[HistoricalValidityOverride, ...],
) -> tuple[str, HistoricalAdjudicationRequest]:
    completion_id = invalidation.completion_record_id
    source_overrides = tuple(
        item
        for item in overrides
        if item.reason is HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED
    )
    timing_overrides = tuple(
        item
        for item in overrides
        if item.reason
        is HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
    )
    if len(timing_overrides) != 1:
        raise _error("request does not contain one exact timing override")
    if completion_id == NOT_EVALUABLE_COMPLETION_ID:
        if invalidation.study_id != "STU-0101" or len(source_overrides) != 1:
            raise _error("STU-0101 source-and-timing override union changed")
        return NOT_EVALUABLE_FAMILY_ID, HistoricalAdjudicationRequest(
            completion_record_id=completion_id,
            disposition=HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION,
            replay_priority=ReplayPriority.NONE,
            reason_codes=_NOT_EVALUABLE_REASON_CODES,
            validity_overrides=overrides,
        )
    if source_overrides:
        raise _error("unexpected legacy completion gained a source override")
    if completion_id in P0_REPLAY_COMPLETION_IDS:
        return P0_REPLAY_FAMILY_ID, HistoricalAdjudicationRequest(
            completion_record_id=completion_id,
            disposition=HistoricalDisposition.REPLAY_REQUIRED,
            replay_priority=ReplayPriority.P0,
            reason_codes=_P0_REASON_CODES,
            validity_overrides=overrides,
        )
    return P1_REPLAY_FAMILY_ID, HistoricalAdjudicationRequest(
        completion_record_id=completion_id,
        disposition=HistoricalDisposition.REPLAY_REQUIRED,
        replay_priority=ReplayPriority.P1,
        reason_codes=_P1_REASON_CODES,
        validity_overrides=overrides,
    )


def build_historical_spread_time_adjudication_plan(
    index: LocalIndex | LocalIndexView,
    inventory: HistoricalSpreadTimeInvalidationInventory,
) -> HistoricalSpreadTimeAdjudicationPlan:
    """Derive the exact 26 supersession requests without mutating authority."""

    if not isinstance(index, (LocalIndex, LocalIndexView)) or not isinstance(
        inventory,
        HistoricalSpreadTimeInvalidationInventory,
    ):
        raise _error("readjudication builder requires a typed index and inventory")
    if (
        inventory.study_contexts != EXPECTED_STUDY_CONTEXTS
        or len(inventory.invalidations) != EXPECTED_COMPLETION_COUNT
    ):
        raise _error("typed spread-time invalidation inventory changed shape")

    invalidations = tuple(
        sorted(
            inventory.invalidations,
            key=lambda item: item.completion_record_id,
        )
    )
    if (
        _semantic_inventory_digest("all_typed_invalidations", invalidations)
        != _EXPECTED_ALL_INVALIDATION_INVENTORY_DIGEST
    ):
        raise _error("typed spread-time invalidation inventory drifted")

    legacy: list[HistoricalScientificValidityInvalidation] = []
    rich_v2: list[HistoricalScientificValidityInvalidation] = []
    for invalidation in invalidations:
        try:
            validate_completion_validity_invalidation_binding(index, invalidation)
        except (CompletionValidityProjectionError, TypeError, ValueError) as exc:
            raise _error("typed invalidation lost its completion binding") from exc
        completion = index.get("job-completed", invalidation.completion_record_id)
        scientific = None if completion is None else completion.payload.get("scientific")
        declaration = (
            None
            if completion is None
            else index.get("job-declared", completion.payload.get("job_id", ""))
        )
        if (
            completion is None
            or not isinstance(scientific, Mapping)
            or scientific.get("scientific_eligible") is not True
            or scientific.get("executable_id") != invalidation.executable_id
            or declaration is None
            or declaration.record_id != invalidation.job_id
            or declaration.payload.get("study_id") != invalidation.study_id
        ):
            raise _error("typed invalidation completion or declaration drifted")
        if isinstance(scientific.get("adjudication"), Mapping):
            if index.event_head(
                f"historical-adjudication:{invalidation.completion_record_id}"
            ) is not None:
                raise _error("rich-v2 completion gained a legacy adjudication head")
            rich_v2.append(invalidation)
        else:
            legacy.append(invalidation)

    legacy_tuple = tuple(legacy)
    rich_tuple = tuple(rich_v2)
    if (
        len(legacy_tuple) != EXPECTED_LEGACY_COMPLETION_COUNT
        or _semantic_inventory_digest(
            "legacy_v1_supersession",
            legacy_tuple,
        )
        != _EXPECTED_LEGACY_INVALIDATION_INVENTORY_DIGEST
        or len(rich_tuple) != EXPECTED_RICH_V2_EXCLUDED_COUNT
        or {item.study_id for item in rich_tuple} != {"STU-0107", "STU-0108"}
        or _semantic_inventory_digest("rich_v2_excluded", rich_tuple)
        != _EXPECTED_RICH_V2_INVALIDATION_INVENTORY_DIGEST
    ):
        raise _error("legacy-v1 and rich-v2 invalidation partition drifted")

    affected_obligations: dict[str, list[str]] = {}
    legacy_ids = {item.completion_record_id for item in legacy_tuple}
    for record in index.records_by_kind("historical-replay-obligation"):
        obligation = record.payload.get("obligation")
        completion_id = (
            None
            if not isinstance(obligation, Mapping)
            else obligation.get("original_completion_record_id")
        )
        if completion_id in legacy_ids:
            if type(completion_id) is not str:
                raise _error("legacy replay obligation completion is malformed")
            affected_obligations.setdefault(completion_id, []).append(
                record.record_id
            )
    expected_obligations = {
        completion_id: [authority[0]]
        for completion_id, authority in _P0_REPLAY_AUTHORITY.items()
    }
    if {
        completion_id: sorted(record_ids)
        for completion_id, record_ids in affected_obligations.items()
    } != expected_obligations:
        raise _error("affected legacy replay-obligation inventory drifted")

    head_entries: list[dict[str, object]] = []
    memory_entries: list[dict[str, str]] = []
    grouped: dict[str, list[HistoricalSpreadTimeAdjudicationMember]] = {
        P0_REPLAY_FAMILY_ID: [],
        P1_REPLAY_FAMILY_ID: [],
        NOT_EVALUABLE_FAMILY_ID: [],
    }
    for invalidation in legacy_tuple:
        completion = index.get("job-completed", invalidation.completion_record_id)
        declaration = (
            None
            if completion is None
            else index.get("job-declared", completion.payload.get("job_id", ""))
        )
        trial = index.get("trial", invalidation.executable_id)
        if (
            completion is None
            or declaration is None
            or declaration.record_id != invalidation.job_id
            or trial is None
            or trial.record_id != invalidation.executable_id
        ):
            raise _error("legacy completion-declaration-Trial join drifted")
        prior, prior_sequence = _require_current_adjudication_head(
            index,
            invalidation,
        )
        memories = _negative_memories(
            index,
            invalidation=invalidation,
            prior=prior,
        )
        overrides = _derive_validity_overrides(
            index,
            invalidation=invalidation,
            trial=trial,
            prior=prior,
        )
        family_id, request = _policy(invalidation, overrides)

        obligation_id: str | None = None
        satisfaction_id: str | None = None
        prior_obligation_priority: ReplayPriority | None = None
        if invalidation.completion_record_id in P0_REPLAY_COMPLETION_IDS:
            if prior.status != HistoricalDisposition.REPLAY_REQUIRED.value:
                raise _error("P0 completion is not currently replay-required")
            (
                obligation_id,
                satisfaction_id,
                prior_obligation_priority,
            ) = _require_p0_satisfied_replay(
                index,
                invalidation=invalidation,
                prior=prior,
            )
        elif prior.status == HistoricalDisposition.REPLAY_REQUIRED.value:
            raise _error("unexpected legacy completion is already replay-required")

        head_entries.append(
            {
                "completion_record_id": invalidation.completion_record_id,
                "head_record_id": prior.record_id,
                "head_sequence": prior_sequence,
            }
        )
        memory_entries.extend(
            {
                "completion_record_id": invalidation.completion_record_id,
                "negative_memory_id": memory_id,
            }
            for memory_id in memories
        )
        grouped[family_id].append(
            HistoricalSpreadTimeAdjudicationMember(
                study_id=invalidation.study_id,
                executable_id=invalidation.executable_id,
                job_id=declaration.record_id,
                completion_record_id=invalidation.completion_record_id,
                invalidation_record_id=invalidation.identity,
                prior_adjudication_record_id=prior.record_id,
                prior_adjudication_sequence=prior_sequence,
                prior_adjudication_status=prior.status,
                negative_memory_ids=memories,
                request=request,
                replay_obligation_id=obligation_id,
                accepted_satisfaction_record_id=satisfaction_id,
                prior_replay_obligation_priority=prior_obligation_priority,
            )
        )

    prior_head_digest = _head_inventory_digest(head_entries)
    negative_memory_digest = _negative_memory_inventory_digest(memory_entries)
    if prior_head_digest != _EXPECTED_PRIOR_HEAD_INVENTORY_DIGEST:
        raise _error("current historical adjudication head inventory drifted")
    if (
        len(memory_entries) != EXPECTED_NEGATIVE_MEMORY_COUNT
        or negative_memory_digest != _EXPECTED_NEGATIVE_MEMORY_INVENTORY_DIGEST
    ):
        raise _error("affected negative-memory inventory drifted")

    families = (
        HistoricalSpreadTimeAdjudicationFamily(
            family_id=P0_REPLAY_FAMILY_ID,
            disposition=HistoricalDisposition.REPLAY_REQUIRED,
            replay_priority=ReplayPriority.P0,
            members=tuple(
                sorted(
                    grouped[P0_REPLAY_FAMILY_ID],
                    key=lambda member: member.completion_record_id,
                )
            ),
        ),
        HistoricalSpreadTimeAdjudicationFamily(
            family_id=P1_REPLAY_FAMILY_ID,
            disposition=HistoricalDisposition.REPLAY_REQUIRED,
            replay_priority=ReplayPriority.P1,
            members=tuple(
                sorted(
                    grouped[P1_REPLAY_FAMILY_ID],
                    key=lambda member: member.completion_record_id,
                )
            ),
        ),
        HistoricalSpreadTimeAdjudicationFamily(
            family_id=NOT_EVALUABLE_FAMILY_ID,
            disposition=HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION,
            replay_priority=ReplayPriority.NONE,
            members=tuple(grouped[NOT_EVALUABLE_FAMILY_ID]),
        ),
    )
    if tuple(len(family.members) for family in families) != (2, 23, 1):
        raise _error("readjudication policy family counts changed")
    return HistoricalSpreadTimeAdjudicationPlan(
        audit_artifact_hash=inventory.audit_artifact_hash,
        typed_invalidation_inventory_digest=(
            _EXPECTED_ALL_INVALIDATION_INVENTORY_DIGEST
        ),
        prior_head_inventory_digest=prior_head_digest,
        negative_memory_inventory_digest=negative_memory_digest,
        excluded_rich_v2_completion_ids=tuple(
            item.completion_record_id for item in rich_tuple
        ),
        families=families,
    )


def build_historical_spread_time_adjudication_requests(
    index: LocalIndex | LocalIndexView,
    inventory: HistoricalSpreadTimeInvalidationInventory,
) -> tuple[HistoricalAdjudicationRequest, ...]:
    """Return only the exact Writer request tuple from the canonical plan."""

    return build_historical_spread_time_adjudication_plan(
        index,
        inventory,
    ).requests


__all__ = [
    "EXPECTED_LEGACY_COMPLETION_COUNT",
    "EXPECTED_NEGATIVE_MEMORY_COUNT",
    "EXPECTED_RICH_V2_EXCLUDED_COUNT",
    "HistoricalSpreadTimeAdjudicationBuilderError",
    "HistoricalSpreadTimeAdjudicationFamily",
    "HistoricalSpreadTimeAdjudicationMember",
    "HistoricalSpreadTimeAdjudicationPlan",
    "NOT_EVALUABLE_COMPLETION_ID",
    "NOT_EVALUABLE_FAMILY_ID",
    "P0_REPLAY_COMPLETION_IDS",
    "P0_REPLAY_FAMILY_ID",
    "P1_REPLAY_FAMILY_ID",
    "REQUEST_MANIFEST_SCHEMA",
    "build_historical_spread_time_adjudication_plan",
    "build_historical_spread_time_adjudication_requests",
]
