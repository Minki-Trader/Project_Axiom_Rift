"""Narrow evidence context for a read-only running-Job authority reader."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import axiom_rift.operations.recorded_transition_authority as recorded_transition_authority_module
import axiom_rift.operations.scientific_history as scientific_history_module
import axiom_rift.operations.historical_family_authority_admission as historical_family_authority_admission_module
from axiom_rift.operations import completion_validity_projection
import axiom_rift.research.historical_family_binding as historical_family_binding_module
import axiom_rift.research.replay_exposure as replay_exposure_module
import axiom_rift.research.replay_member_assignment as replay_member_assignment_module
import axiom_rift.research.replay_obligation as replay_obligation_module
import axiom_rift.research.replay_satisfaction_invalidation as replay_satisfaction_invalidation_module
import axiom_rift.research.semantic_question as semantic_question_module
import axiom_rift.research.trials as trials_module
import axiom_rift.storage.evidence as evidence_module
from axiom_rift.research import historical_scientific_validity
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job import (
    RunningJobAuthority,
    RunningJobAuthorityError,
    RunningJobExecution,
    running_job_authority_dependency_paths,
)
from axiom_rift.operations.scientific_history import (
    ScientificHistoryProjectionError,
    project_frozen_family_exposure_context,
    project_historical_family_end_global_exposure_count,
    project_registered_replay_member_bindings,
    project_running_batch_job_prefix,
)
from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    authority_key,
    require_recorded_transition_authority,
    require_same_event_operation_result,
)
from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    current_completion_validity_invalidation,
)
from axiom_rift.operations.historical_family_authority_admission import (
    HistoricalFamilyAuthorityAdmissionError,
    require_recorded_historical_family_authority,
)
from axiom_rift.research.replay_exposure import FrozenFamilyExposureContext
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilySpec,
    historical_family_core_identity,
)
from axiom_rift.research.replay_obligation import (
    ReplayExecutionBinding,
    ReplayObligationError,
    ReplayResolutionScope,
    ReplaySatisfaction,
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.research.replay_member_assignment import (
    ReplayMemberAssignmentError,
    ReplayMemberAssignmentSet,
    assignment_set_from_semantic_proposal,
)
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplayCompletionValidityDefect,
    ReplaySatisfactionInvalidationAuditManifest,
    ReplaySatisfactionInvalidationAuditManifestV2,
    ReplaySatisfactionInvalidationManifest,
    replay_satisfaction_invalidation_manifest_from_mapping,
)
from axiom_rift.research.semantic_question import (
    SemanticQuestionCore,
    SemanticQuestionEquivalenceProposal,
    SemanticQuestionError,
    SemanticQuestionLineageProposal,
)
from axiom_rift.research.trials import TrialAccountant
from axiom_rift.storage.evidence import (
    EvidenceArtifact,
    EvidenceStore as _EvidenceStore,
)


_THIS_FILE = Path(__file__).resolve()


class RunningJobEvidence(Protocol):
    """The complete evidence capability available to a running Job."""

    def finalize(self, content: bytes) -> EvidenceArtifact: ...

    def read_verified(self, identity: str) -> bytes: ...


class _RunningJobEvidenceFacade:
    """Expose content bytes, never storage paths or the underlying store."""

    __slots__ = ("__store",)

    def __init__(self, root: Path) -> None:
        object.__setattr__(
            self,
            "_RunningJobEvidenceFacade__store",
            _EvidenceStore(root),
        )

    def __getattribute__(self, name: str) -> object:
        if name == "_RunningJobEvidenceFacade__store":
            raise AttributeError("the running Job evidence store is not exposed")
        return object.__getattribute__(self, name)

    def finalize(self, content: bytes) -> EvidenceArtifact:
        store = object.__getattribute__(
            self,
            "_RunningJobEvidenceFacade__store",
        )
        return store.finalize(content)

    def read_verified(self, identity: str) -> bytes:
        store = object.__getattribute__(
            self,
            "_RunningJobEvidenceFacade__store",
        )
        return store.read_verified(identity)


@dataclass(frozen=True, slots=True)
class RunningJobSourceState:
    """Detached state of the one source contract bound to a running Job."""

    record_id: str
    status: str
    _payload_bytes: bytes

    def payload(self) -> dict[str, Any]:
        value = parse_canonical(self._payload_bytes)
        if not isinstance(value, dict):
            raise RunningJobAuthorityError(
                "bound source state payload is not an object"
            )
        return value


@dataclass(frozen=True, slots=True)
class RunningJobFixedHoldReplayContext:
    """Detached replay authority bound to one exact active Executable Job."""

    family_authority_id: str
    replay_obligation_id: str
    family: HistoricalFamilySpec
    original_family_end_global_exposure_count: int
    exposure: FrozenFamilyExposureContext
    batch_family_executable_ids: tuple[str, ...]
    registered_member_bindings: tuple[tuple[str, str], ...]
    execution_prefix_executable_ids: tuple[str, ...]
    completed_member_executable_ids: tuple[str, ...]
    target_prospective_executable_id: str


def _require_same_event_family_authority(
    *,
    family_record: Any,
    invalidation_authority: tuple[int, str, int],
    family_authority_id: object,
) -> None:
    """Require one family record created by the invalidation event itself."""

    try:
        same_event = invalidation_authority == authority_key(family_record)
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(str(exc)) from exc
    if not same_event or family_authority_id != family_record.record_id:
        raise RunningJobAuthorityError(
            "fixed-hold correction lacks same-event Writer authority"
        )


def _require_prior_family_authority(
    index: Any,
    *,
    obligation: Any,
    family_record: Any,
    invalidation_authority: tuple[int, str, int],
) -> None:
    """Authenticate one previously accepted family without recreating it."""

    try:
        family_authority = authority_key(family_record)
        _event_kind, family_result = require_same_event_operation_result(
            index,
            record=family_record,
            expected_event_kinds=frozenset(
                {"historical_replay_satisfaction_invalidated"}
            ),
        )
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(
            "fixed-hold prior family authority lacks Writer authentication"
        ) from exc
    pending_ids = family_result.get("pending_replay_obligation_ids")
    if (
        family_authority[0] >= invalidation_authority[0]
        or family_result.get("historical_family_authority_id")
        != family_record.record_id
        or family_result.get("replay_obligation_id") != obligation.identity
        or not isinstance(pending_ids, list)
        or any(type(item) is not str for item in pending_ids)
        or pending_ids != sorted(set(pending_ids))
        or obligation.identity not in pending_ids
        or any(
            family_result.get(field) != 0
            for field in (
                "candidate_delta",
                "holdout_reveal_delta",
                "scientific_claim_delta",
                "scientific_satisfaction_delta",
                "scientific_trial_delta",
            )
        )
    ):
        raise RunningJobAuthorityError(
            "fixed-hold prior family authority does not predate the v2 correction"
        )


def _require_v2_scientific_satisfaction(
    index: Any,
    *,
    obligation: Any,
    predecessor: Any,
    manifest: ReplaySatisfactionInvalidationAuditManifestV2,
    invalidation_authority: tuple[int, str, int],
) -> ReplaySatisfaction:
    """Rebuild and authenticate the scientific satisfaction named by v2."""

    raw = predecessor.payload.get("resolution")
    try:
        if not isinstance(raw, Mapping):
            raise ReplayObligationError("replay satisfaction payload is absent")
        satisfaction = ReplaySatisfaction(
            obligation_id=raw["obligation_id"],
            resolution_scope=ReplayResolutionScope(raw["resolution_scope"]),
            portfolio_decision_id=raw["portfolio_decision_id"],
            replay_study_id=raw["replay_study_id"],
            replay_executable_id=raw["replay_executable_id"],
            replay_study_close_record_id=raw[
                "replay_study_close_record_id"
            ],
            study_diagnosis_id=raw["study_diagnosis_id"],
            satisfied_criterion_ids=tuple(raw["satisfied_criterion_ids"]),
            evidence_record_ids=tuple(raw["evidence_record_ids"]),
            remaining_scientific_condition=raw.get(
                "remaining_scientific_condition"
            ),
        )
    except (KeyError, TypeError, ValueError, ReplayObligationError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold v2 correction satisfaction is malformed"
        ) from exc
    completion_ids = {
        evidence_id
        for evidence_id in satisfaction.evidence_record_ids
        if index.get("job-completed", evidence_id) is not None
    }
    try:
        satisfaction_authority = authority_key(predecessor)
        _event_kind, result = require_same_event_operation_result(
            index,
            record=predecessor,
            expected_event_kinds=frozenset(
                {
                    "historical_replay_correction_recorded",
                    "historical_replay_obligations_disposed",
                    "historical_replay_obligations_resolved",
                    "historical_replay_sibling_evidence_recertified",
                }
            ),
        )
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(
            "fixed-hold v2 correction satisfaction lacks Writer authentication"
        ) from exc
    satisfied_ids = result.get("satisfied_replay_obligation_ids")
    if (
        satisfaction.resolution_scope is not ReplayResolutionScope.SCIENTIFIC
        or satisfaction_authority[0] >= invalidation_authority[0]
        or not isinstance(satisfied_ids, list)
        or any(type(item) is not str for item in satisfied_ids)
        or satisfied_ids != sorted(set(satisfied_ids))
        or obligation.identity not in satisfied_ids
        or predecessor.payload
        != {
            "obligation_id": obligation.identity,
            "prior_status": predecessor.payload.get("prior_status"),
            "resolution": satisfaction.to_identity_payload(),
        }
        or predecessor.payload.get("prior_status") not in {"pending", "in_progress"}
        or satisfaction.identity != manifest.satisfaction_record_id
        or satisfaction.obligation_id != obligation.identity
        or satisfaction.portfolio_decision_id != manifest.portfolio_decision_id
        or satisfaction.replay_study_id != manifest.replay_study_id
        or satisfaction.replay_executable_id != manifest.replay_executable_id
        or satisfaction.replay_study_close_record_id
        != manifest.replay_study_close_record_id
        or satisfaction.study_diagnosis_id != manifest.study_diagnosis_id
        or completion_ids != set(manifest.completion_record_ids)
    ):
        raise RunningJobAuthorityError(
            "fixed-hold v2 correction lost its exact scientific satisfaction"
        )
    return satisfaction


def _require_v2_completion_validity_heads(
    index: Any,
    *,
    manifest: ReplaySatisfactionInvalidationAuditManifestV2,
    defect: ReplayCompletionValidityDefect,
    satisfaction: ReplaySatisfaction,
    invalidation_authority: tuple[int, str, int],
) -> None:
    """Rejoin every v2 observation to its exact current validity head."""

    observations = {
        observation.completion_record_id: observation
        for observation in defect.observations
    }
    current_heads: dict[str, Any] = {}
    for completion_id in manifest.completion_record_ids:
        try:
            current = current_completion_validity_invalidation(
                index,
                completion_id,
            )
        except CompletionValidityProjectionError as exc:
            raise RunningJobAuthorityError(
                "fixed-hold completion-validity head is malformed"
            ) from exc
        if current is not None:
            current_heads[completion_id] = current
    if set(current_heads) != set(observations):
        raise RunningJobAuthorityError(
            "fixed-hold completion-validity observations are not current and exact"
        )
    for completion_id, observation in observations.items():
        current = current_heads[completion_id]
        if (
            current.completion_record_id != observation.completion_record_id
            or current.executable_id != observation.executable_id
            or current.invalidation_record_id
            != observation.invalidation_record_id
            or current.reason != observation.reason
            or current.affected_criterion_ids
            != observation.affected_criterion_ids
            or current.validity_stream_sequence
            != observation.validity_stream_sequence
            or current.authority_event_id != observation.authority_event_id
            or current.authority_sequence != observation.authority_sequence
            or current.authority_offset != observation.authority_offset
            or current.authority_sequence >= invalidation_authority[0]
            or not set(observation.affected_criterion_ids).intersection(
                satisfaction.satisfied_criterion_ids
            )
        ):
            raise RunningJobAuthorityError(
                "fixed-hold completion-validity observation is stale or unrelated"
            )


def _require_correction_pending_invalidation(
    index: Any,
    *,
    obligation: Any,
    record: Any,
    family_record: Any,
    require_current_head: bool,
) -> ReplaySatisfactionInvalidationManifest:
    """Authenticate the correction and its exact family-authority route."""

    raw_manifest = record.payload.get("audit_manifest")
    audit_hash = record.payload.get("audit_manifest_hash")
    try:
        manifest = replay_satisfaction_invalidation_manifest_from_mapping(
            raw_manifest
        )
    except (TypeError, ValueError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold correction invalidation manifest is malformed"
        ) from exc
    expected_payload = {
        "audit_manifest": manifest.to_identity_payload(),
        "audit_manifest_hash": audit_hash,
        "candidate_delta": 0,
        "holdout_reveal_delta": 0,
        "obligation_id": obligation.identity,
        "prior_satisfaction_record_id": manifest.satisfaction_record_id,
        "prior_status": "satisfied",
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
        "terminal_credit_delta": 0,
    }
    stream = f"historical-replay-obligation:{obligation.identity}"
    predecessor = (
        None
        if type(record.event_sequence) is not int
        else index.event_record(stream, record.event_sequence - 1)
    )
    if (
        type(audit_hash) is not str
        or sha256(canonical_bytes(manifest.to_identity_payload())).hexdigest()
        != audit_hash
        or record.kind != "historical-replay-satisfaction-invalidation"
        or record.record_id != manifest.identity
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.status != "pending"
        or record.fingerprint
        != manifest.identity.removeprefix(
            "historical-replay-satisfaction-invalidation:"
        )
        or record.payload != expected_payload
        or record.event_stream != stream
        or record.event_sequence != manifest.satisfaction_event_sequence + 1
        or manifest.governing_mission_id != obligation.governing_mission_id
        or manifest.obligation_id != obligation.identity
        or predecessor is None
        or predecessor.record_id != manifest.satisfaction_record_id
        or predecessor.event_sequence != manifest.satisfaction_event_sequence
    ):
        raise RunningJobAuthorityError(
            "fixed-hold correction invalidation is not exact"
        )
    try:
        _event_kind, result = require_recorded_transition_authority(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {"historical_replay_satisfaction_invalidated"}
            ),
            require_current_head=require_current_head,
        )
        invalidation_authority = authority_key(record)
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(str(exc)) from exc
    pending_ids = result.get("pending_replay_obligation_ids")
    expected_result_fields = {
        "audit_manifest_hash",
        "candidate_delta",
        "holdout_reveal_delta",
        "invalidated_satisfaction_record_id",
        "pending_replay_obligation_ids",
        "replay_obligation_id",
        "scientific_claim_delta",
        "scientific_satisfaction_delta",
        "scientific_trial_delta",
    }
    if "historical_family_authority_id" in result:
        expected_result_fields.add("historical_family_authority_id")
    if (
        set(result) != expected_result_fields
        or result.get("audit_manifest_hash") != audit_hash
        or result.get("invalidated_satisfaction_record_id")
        != manifest.satisfaction_record_id
        or result.get("replay_obligation_id") != obligation.identity
        or not isinstance(pending_ids, list)
        or any(type(item) is not str for item in pending_ids)
        or pending_ids != sorted(set(pending_ids))
        or obligation.identity not in pending_ids
        or any(
            result.get(field) != 0
            for field in (
                "candidate_delta",
                "holdout_reveal_delta",
                "scientific_claim_delta",
                "scientific_satisfaction_delta",
                "scientific_trial_delta",
            )
        )
    ):
        raise RunningJobAuthorityError(
            "fixed-hold correction lacks exact zero-delta Writer authority"
        )
    if isinstance(manifest, ReplaySatisfactionInvalidationAuditManifest):
        _require_same_event_family_authority(
            family_record=family_record,
            invalidation_authority=invalidation_authority,
            family_authority_id=result.get("historical_family_authority_id"),
        )
        return manifest

    if not isinstance(manifest, ReplaySatisfactionInvalidationAuditManifestV2):
        raise RunningJobAuthorityError(
            "fixed-hold correction invalidation schema is unsupported"
        )
    completion_defects = tuple(
        defect
        for defect in manifest.defects
        if isinstance(defect, ReplayCompletionValidityDefect)
    )
    if len(completion_defects) != 1:
        raise RunningJobAuthorityError(
            "fixed-hold v2 correction lacks one completion-validity defect"
        )
    if "historical_family_authority_id" in result:
        _require_same_event_family_authority(
            family_record=family_record,
            invalidation_authority=invalidation_authority,
            family_authority_id=result["historical_family_authority_id"],
        )
    else:
        _require_prior_family_authority(
            index,
            obligation=obligation,
            family_record=family_record,
            invalidation_authority=invalidation_authority,
        )

    satisfaction = _require_v2_scientific_satisfaction(
        index,
        obligation=obligation,
        predecessor=predecessor,
        manifest=manifest,
        invalidation_authority=invalidation_authority,
    )

    _require_v2_completion_validity_heads(
        index,
        manifest=manifest,
        defect=completion_defects[0],
        satisfaction=satisfaction,
        invalidation_authority=invalidation_authority,
    )
    return manifest


def _require_replay_progress_transition(
    index: Any,
    *,
    obligation: Any,
    record: Any,
    require_current_head: bool,
) -> ReplayExecutionBinding:
    """Authenticate one exact pending-to-in-progress replay transition."""

    raw_binding = record.payload.get("binding")
    try:
        if not isinstance(raw_binding, Mapping):
            raise ReplayObligationError("replay progress binding is absent")
        binding = ReplayExecutionBinding(
            obligation_ids=tuple(raw_binding["obligation_ids"]),
            portfolio_decision_id=raw_binding["portfolio_decision_id"],
            replay_study_id=raw_binding["replay_study_id"],
            replay_executable_id=raw_binding["replay_executable_id"],
        )
    except (KeyError, TypeError, ValueError, ReplayObligationError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold replay progress binding is malformed"
        ) from exc
    expected_payload = {
        "binding": binding.to_identity_payload(),
        "obligation_id": obligation.identity,
        "prior_status": "pending",
    }
    stream = f"historical-replay-obligation:{obligation.identity}"
    if (
        binding.obligation_ids != (obligation.identity,)
        or record.kind != "historical-replay-obligation-progress"
        or record.record_id
        != "historical-replay-progress:"
        + canonical_digest(
            domain="historical-replay-obligation-progress",
            payload=expected_payload,
        )
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.status != "in_progress"
        or record.fingerprint != binding.identity
        or record.payload != expected_payload
        or record.event_stream != stream
        or type(record.event_sequence) is not int
        or record.event_sequence < 2
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay progress transition is not exact"
        )
    try:
        require_recorded_transition_authority(
            index,
            record=record,
            expected_event_kinds=frozenset({"trial_registered"}),
            require_current_head=require_current_head,
        )
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(str(exc)) from exc
    return binding


def _require_replay_deferral_transition(
    index: Any,
    *,
    obligation: Any,
    record: Any,
) -> Any:
    """Authenticate one exact replay deferral inside a correction route."""

    raw_deferral = record.payload.get("resolution")
    try:
        if not isinstance(raw_deferral, Mapping):
            raise ReplayObligationError("replay deferral payload is absent")
        deferral = replay_obligation_module.replay_deferral_from_identity_payload(
            raw_deferral
        )
    except (TypeError, ValueError, ReplayObligationError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold replay deferral is malformed"
        ) from exc
    prior_status = record.payload.get("prior_status")
    expected_payload = {
        "obligation_id": obligation.identity,
        "prior_status": prior_status,
        "resolution": deferral.to_identity_payload(),
    }
    stream = f"historical-replay-obligation:{obligation.identity}"
    if (
        prior_status not in {"pending", "in_progress"}
        or deferral.obligation_id != obligation.identity
        or record.kind != "historical-replay-obligation-resolution"
        or record.record_id != deferral.identity
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.status != "deferred"
        or record.fingerprint
        != deferral.identity.removeprefix("historical-replay-deferral:")
        or record.payload != expected_payload
        or record.event_stream != stream
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay deferral transition is not exact"
        )
    try:
        _event_kind, result = require_recorded_transition_authority(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {
                    "historical_replay_obligations_deferred",
                    "historical_replay_obligations_disposed",
                }
            ),
            require_current_head=False,
        )
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(str(exc)) from exc
    deferred_ids = result.get("deferred_replay_obligation_ids")
    expected_result_fields = (
        {
            "deferred_replay_obligation_ids",
            "effective_scope_overlay_ids",
            "satisfied_replay_obligation_ids",
        }
        if _event_kind == "historical_replay_obligations_disposed"
        else {"deferred_replay_obligation_ids"}
    )
    if (
        set(result) != expected_result_fields
        or not isinstance(deferred_ids, list)
        or any(type(item) is not str for item in deferred_ids)
        or deferred_ids != sorted(set(deferred_ids))
        or obligation.identity not in deferred_ids
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay deferral lacks exact Writer authority"
        )
    return deferral


def _require_replay_resume_transition(
    index: Any,
    *,
    obligation: Any,
    record: Any,
    deferral: Any,
) -> None:
    """Authenticate one exact deferred-to-pending replay transition."""

    raw_evidence = record.payload.get("resume_evidence")
    try:
        if not isinstance(raw_evidence, Mapping):
            raise ReplayObligationError("replay resume evidence is absent")
        evidence = (
            replay_obligation_module
            .replay_resume_evidence_from_identity_payload(raw_evidence)
        )
    except (TypeError, ValueError, ReplayObligationError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold replay resume evidence is malformed"
        ) from exc
    expected_payload = {
        "obligation_id": obligation.identity,
        "prior_status": "deferred",
        "resume_evidence": evidence.to_identity_payload(),
        "scientific_claim_delta": 0,
        "scientific_satisfaction_delta": 0,
        "scientific_trial_delta": 0,
    }
    stream = f"historical-replay-obligation:{obligation.identity}"
    if (
        evidence.obligation_id != obligation.identity
        or evidence.deferral_id != deferral.identity
        or evidence.resume_condition_id
        not in {item.identity for item in deferral.resume_conditions}
        or record.kind != "historical-replay-obligation-resume"
        or record.record_id != evidence.identity
        or record.subject != f"Mission:{obligation.governing_mission_id}"
        or record.status != "pending"
        or record.fingerprint
        != evidence.identity.removeprefix(
            "historical-replay-resume-evidence:"
        )
        or record.payload != expected_payload
        or record.event_stream != stream
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay resume transition is not exact"
        )
    try:
        _event_kind, result = require_recorded_transition_authority(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {"historical_replay_obligations_resumed"}
            ),
            require_current_head=False,
        )
    except RecordedTransitionAuthorityError as exc:
        raise RunningJobAuthorityError(str(exc)) from exc
    expected_result_fields = {
        "resume_condition_ids",
        "resume_trigger_record_ids",
        "resumed_replay_obligation_ids",
        "scientific_claim_delta",
        "scientific_satisfaction_delta",
        "scientific_trial_delta",
    }
    inventories = (
        ("resume_condition_ids", evidence.resume_condition_id),
        ("resume_trigger_record_ids", evidence.trigger_record_id),
        ("resumed_replay_obligation_ids", obligation.identity),
    )
    if set(result) != expected_result_fields or any(
        not isinstance(values := result.get(field), list)
        or any(type(item) is not str for item in values)
        or values != sorted(set(values))
        or expected not in values
        for field, expected in inventories
    ) or any(
        result.get(field) != 0
        for field in (
            "scientific_claim_delta",
            "scientific_satisfaction_delta",
            "scientific_trial_delta",
        )
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay resume lacks exact zero-delta Writer authority"
        )


def _require_correction_invalidation_route(
    index: Any,
    *,
    obligation: Any,
    current_progress: Any,
) -> Any:
    """Walk the exact correction, deferral, and resume ancestry."""

    stream = f"historical-replay-obligation:{obligation.identity}"
    sequence = current_progress.event_sequence
    cursor = (
        None
        if type(sequence) is not int or sequence < 2
        else index.event_record(stream, sequence - 1)
    )
    while cursor is not None:
        if cursor.kind == "historical-replay-satisfaction-invalidation":
            return cursor
        if (
            cursor.kind != "historical-replay-obligation-resume"
            or cursor.status != "pending"
            or type(cursor.event_sequence) is not int
            or cursor.event_sequence < 3
        ):
            break
        deferral_record = index.event_record(
            stream,
            cursor.event_sequence - 1,
        )
        if deferral_record is None:
            break
        deferral = _require_replay_deferral_transition(
            index,
            obligation=obligation,
            record=deferral_record,
        )
        _require_replay_resume_transition(
            index,
            obligation=obligation,
            record=cursor,
            deferral=deferral,
        )
        prior = index.event_record(
            stream,
            deferral_record.event_sequence - 1,
        )
        if prior is None:
            break
        if prior.status == "in_progress":
            _require_replay_progress_transition(
                index,
                obligation=obligation,
                record=prior,
                require_current_head=False,
            )
            cursor = index.event_record(stream, prior.event_sequence - 1)
        elif prior.status == "pending":
            cursor = prior
        else:
            break
    raise RunningJobAuthorityError(
        "fixed-hold replay execution lost its correction invalidation route"
    )


@dataclass(frozen=True, slots=True)
class _BoundRunningJob:
    execution: RunningJobExecution
    mission_id: str | None
    study_id: str | None
    batch_id: str | None
    subject_kind: str | None
    subject_id: str | None
    source_contract_id: str | None


def _require_bound_active_job(
    control: Mapping[str, Any],
    bound: _BoundRunningJob,
) -> None:
    science = control.get("scientific")
    active_job = (
        None
        if not isinstance(science, Mapping)
        else science.get("active_job")
    )
    execution = bound.execution
    if (
        not isinstance(active_job, Mapping)
        or active_job.get("status") != "running"
        or active_job.get("id") != execution.job_id
        or active_job.get("hash") != execution.job_hash
        or active_job.get("start_record_id") != execution.start_record_id
    ):
        raise RunningJobAuthorityError(
            "verified running Job authority changed"
        )


def _fixed_hold_replay_study_input_payload(
    *,
    study_id: str,
    study_payload: Mapping[str, Any],
    question: Mapping[str, Any],
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild the exact Writer-bound Study identity at the Job boundary."""

    equivalence_payload = study_payload.get("semantic_question_equivalence")
    lineage_payload = study_payload.get("semantic_question_lineage")
    try:
        equivalence = (
            None
            if equivalence_payload is None
            else SemanticQuestionEquivalenceProposal.from_identity_payload(
                equivalence_payload
            )
        )
        lineage = (
            None
            if lineage_payload is None
            else SemanticQuestionLineageProposal.from_identity_payload(
                lineage_payload
            )
        )
        semantic_core = (
            None
            if study_payload.get("semantic_question_core_id") is None
            and lineage is None
            else SemanticQuestionCore.from_question_manifest(question)
        )
    except (SemanticQuestionError, TypeError) as exc:
        raise RunningJobAuthorityError(
            "fixed-hold replay Study semantic authority is malformed"
        ) from exc
    equivalence_id = study_payload.get("semantic_question_equivalence_id")
    lineage_id = study_payload.get("semantic_question_lineage_id")
    semantic_core_id = study_payload.get("semantic_question_core_id")
    if (
        (equivalence is None and equivalence_id is not None)
        or (equivalence is not None and equivalence.identity != equivalence_id)
        or (lineage is None and lineage_id is not None)
        or (lineage is not None and lineage.identity != lineage_id)
        or (
            lineage is not None
            and (
                lineage.successor_study_id != study_id
                or semantic_core is None
                or lineage.successor_core_id != semantic_core.identity
                or lineage.equivalence_proposal_id
                != (None if equivalence is None else equivalence.identity)
            )
        )
        or (
            semantic_core is not None
            and semantic_core.identity != semantic_core_id
        )
    ):
        raise RunningJobAuthorityError(
            "fixed-hold replay Study semantic authority is malformed"
        )
    identity_payload: dict[str, Any] = {
        "controlled_chassis": study_payload.get("controlled_chassis"),
        "question_hash": study_payload.get("question_hash"),
        "material_identity": study_payload.get("material_identity"),
        "portfolio_axis_id": study_payload.get("portfolio_axis_id"),
        "portfolio_axis_identity": study_payload.get(
            "portfolio_axis_identity"
        ),
        "portfolio_decision_id": study_payload.get("portfolio_decision_id"),
        "semantic_proposal": dict(proposal),
    }
    if equivalence is not None:
        identity_payload["semantic_question_equivalence"] = (
            equivalence.to_identity_payload()
        )
    if lineage is not None:
        identity_payload["semantic_question_lineage"] = (
            lineage.to_identity_payload()
        )
    return identity_payload


class RunningJobExecutionContext:
    """Expose only projections bound to one verified running Job."""

    __slots__ = (
        "__authority",
        "__bound_job",
        "__evidence",
        "__prior_global_multiplicity_floor",
    )

    def __init__(self, root: str | Path) -> None:
        resolved = Path(root).resolve()
        authority = RunningJobAuthority(resolved)
        prior_floor = TrialAccountant.from_foundation(
            authority.foundation_root
        ).prior_global_multiplicity_floor
        if type(prior_floor) is not int or prior_floor < 0:
            raise RunningJobAuthorityError(
                "Foundation prior global multiplicity floor is invalid"
            )
        object.__setattr__(
            self,
            "_RunningJobExecutionContext__authority",
            authority,
        )
        object.__setattr__(
            self,
            "_RunningJobExecutionContext__bound_job",
            None,
        )
        object.__setattr__(
            self,
            "_RunningJobExecutionContext__evidence",
            _RunningJobEvidenceFacade(resolved / "local" / "evidence"),
        )
        object.__setattr__(
            self,
            "_RunningJobExecutionContext__prior_global_multiplicity_floor",
            prior_floor,
        )

    def __getattribute__(self, name: str) -> object:
        if name in {
            "_RunningJobExecutionContext__authority",
            "_RunningJobExecutionContext__bound_job",
            "_RunningJobExecutionContext__evidence",
            "_RunningJobExecutionContext__prior_global_multiplicity_floor",
        }:
            raise AttributeError(
                "running Job context internals are not exposed"
            )
        return object.__getattribute__(self, name)

    @property
    def evidence(self) -> RunningJobEvidence:
        return object.__getattribute__(
            self,
            "_RunningJobExecutionContext__evidence",
        )

    @property
    def prior_global_multiplicity_floor(self) -> int:
        return object.__getattribute__(
            self,
            "_RunningJobExecutionContext__prior_global_multiplicity_floor",
        )

    def _bound(self) -> _BoundRunningJob:
        bound = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__bound_job",
        )
        if not isinstance(bound, _BoundRunningJob):
            raise RunningJobAuthorityError(
                "running Job execution has not been verified"
            )
        return bound

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        **kwargs: Any,
    ) -> dict[str, Any]:
        authority = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__authority",
        )
        binding = authority.verify_running_job_execution(
            execution,
            **kwargs,
        )
        spec = binding.get("spec")
        subject = (
            None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
        )
        source_binding = (
            None if not isinstance(spec, Mapping) else spec.get("source_binding")
        )
        candidate = _BoundRunningJob(
            execution=execution,
            mission_id=(
                binding.get("mission_id")
                if type(binding.get("mission_id")) is str
                else None
            ),
            study_id=(
                binding.get("study_id")
                if type(binding.get("study_id")) is str
                else None
            ),
            batch_id=(
                binding.get("batch_id")
                if type(binding.get("batch_id")) is str
                else None
            ),
            subject_kind=(
                subject.get("kind")
                if isinstance(subject, Mapping)
                and type(subject.get("kind")) is str
                else None
            ),
            subject_id=(
                subject.get("id")
                if isinstance(subject, Mapping)
                and type(subject.get("id")) is str
                else None
            ),
            source_contract_id=(
                source_binding.get("source_contract_id")
                if isinstance(source_binding, Mapping)
                and type(source_binding.get("source_contract_id")) is str
                else None
            ),
        )
        prior = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__bound_job",
        )
        if prior is not None and prior != candidate:
            raise RunningJobAuthorityError(
                "running Job context cannot be rebound to another execution"
            )
        object.__setattr__(
            self,
            "_RunningJobExecutionContext__bound_job",
            candidate,
        )
        return binding

    def project_bound_fixed_hold_family_exposure(
        self,
        *,
        study_id: str,
        batch_id: str,
        subject_executable_id: str,
        expected_family_size: int,
        parameter_name: str | None,
    ) -> FrozenFamilyExposureContext:
        """Return only the family projection of the verified Job subject."""

        bound = self._bound()
        if (
            bound.subject_kind != "Executable"
            or bound.study_id != study_id
            or bound.batch_id != batch_id
            or bound.subject_id != subject_executable_id
        ):
            raise RunningJobAuthorityError(
                "fixed-hold family request differs from the verified Job"
            )
        authority = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__authority",
        )
        with authority.open_stable_index() as (control, index):
            _require_bound_active_job(control, bound)
            return project_frozen_family_exposure_context(
                index,
                prior_global_exposure_floor=(
                    self.prior_global_multiplicity_floor
                ),
                study_id=study_id,
                batch_id=batch_id,
                expected_family_size=expected_family_size,
                parameter_name=parameter_name,
                allow_unregistered=False,
            )

    def project_bound_fixed_hold_replay_context(
        self,
        *,
        study_id: str,
        batch_id: str,
        subject_executable_id: str,
        expected_family_size: int,
        parameter_name: str | None,
    ) -> RunningJobFixedHoldReplayContext:
        """Return only Writer-authenticated family data and frozen exposure."""

        bound = self._bound()
        if (
            bound.mission_id is None
            or bound.subject_kind != "Executable"
            or bound.study_id != study_id
            or bound.batch_id != batch_id
            or bound.subject_id != subject_executable_id
        ):
            raise RunningJobAuthorityError(
                "fixed-hold replay request differs from the verified Job"
            )
        authority = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__authority",
        )
        with authority.open_stable_index() as (control, index):
            _require_bound_active_job(control, bound)
            science = control.get("scientific")
            if (
                not isinstance(science, Mapping)
                or science.get("active_mission") != bound.mission_id
                or science.get("active_study") != study_id
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay active Mission or Study drifted"
                )
            study = index.get("study-open", study_id)
            study_payload = None if study is None else study.payload
            proposal = (
                None
                if not isinstance(study_payload, Mapping)
                else study_payload.get("semantic_proposal")
            )
            question = (
                None
                if not isinstance(study_payload, Mapping)
                else study_payload.get("question")
            )
            try:
                assignment_set = (
                    None
                    if not isinstance(proposal, Mapping)
                    else assignment_set_from_semantic_proposal(proposal)
                )
            except ReplayMemberAssignmentError as exc:
                raise RunningJobAuthorityError(
                    "fixed-hold replay member assignments are malformed"
                ) from exc
            base_proposal_fields = {
                "candidate_eligible",
                "concurrent_family",
                "historical_family_authority_id",
                "historical_family_identity",
                "historical_obligation_id",
                "mechanism",
                "original_study_id",
            }
            assignment_proposal_fields = {
                "replay_member_assignment_set_id",
                "replay_member_assignments",
                "replay_obligation_ids",
            }
            if (
                study is None
                or study.kind != "study-open"
                or study.record_id != study_id
                or study.subject != f"Study:{study_id}"
                or study.status != "open"
                or not isinstance(study_payload, Mapping)
                or not isinstance(proposal, Mapping)
                or not isinstance(question, Mapping)
                or set(proposal)
                != (
                    base_proposal_fields
                    if assignment_set is None
                    else base_proposal_fields | assignment_proposal_fields
                )
                or canonical_digest(
                    domain="study-question",
                    payload=dict(question),
                )
                != study_payload.get("question_hash")
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay Study authority is malformed"
                )
            study_input_payload = _fixed_hold_replay_study_input_payload(
                study_id=study_id,
                study_payload=study_payload,
                question=question,
                proposal=proposal,
            )
            if canonical_digest(
                domain="study-input",
                payload=study_input_payload,
            ) != study.fingerprint:
                raise RunningJobAuthorityError(
                    "fixed-hold replay Study authority is malformed"
                )
            obligation_ids = study_payload.get("replay_obligation_ids")
            family_authority_id = proposal.get(
                "historical_family_authority_id"
            )
            replay_obligation_id = proposal.get("historical_obligation_id")
            if (
                type(obligation_ids) is not list
                or obligation_ids
                != (
                    [replay_obligation_id]
                    if assignment_set is None
                    else list(assignment_set.obligation_ids)
                )
                or type(replay_obligation_id) is not str
                or type(family_authority_id) is not str
                or proposal.get("candidate_eligible") is not False
                or (
                    assignment_set is not None
                    and (
                        assignment_set.mission_id != bound.mission_id
                        or assignment_set.primary_obligation_id
                        != replay_obligation_id
                        or proposal.get("replay_member_assignment_set_id")
                        != assignment_set.identity
                        or proposal.get("replay_obligation_ids")
                        != list(assignment_set.obligation_ids)
                        or assignment_set.primary.historical_family_authority_id
                        != family_authority_id
                    )
                )
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay Study binding is incomplete"
                )
            obligation_record = index.get(
                "historical-replay-obligation",
                replay_obligation_id,
            )
            obligation_payload = (
                None
                if obligation_record is None
                else obligation_record.payload.get("obligation")
            )
            try:
                if not isinstance(obligation_payload, Mapping):
                    raise ReplayObligationError(
                        "historical replay obligation payload is absent"
                    )
                obligation = historical_replay_obligation_from_identity_payload(
                    obligation_payload
                )
            except ReplayObligationError as exc:
                raise RunningJobAuthorityError(
                    "fixed-hold replay obligation is malformed"
                ) from exc
            if (
                obligation_record is None
                or obligation_record.kind
                != "historical-replay-obligation"
                or obligation_record.record_id != replay_obligation_id
                or obligation_record.subject != f"Mission:{bound.mission_id}"
                or obligation_record.status != "pending"
                or obligation_record.fingerprint
                != replay_obligation_id.removeprefix(
                    "historical-replay-obligation:"
                )
                or obligation.identity != replay_obligation_id
                or obligation.governing_mission_id != bound.mission_id
                or obligation_record.event_stream
                != f"historical-replay-obligation:{replay_obligation_id}"
                or obligation_record.event_sequence != 1
                or obligation_record.payload
                != {"obligation": obligation.to_identity_payload()}
                or index.event_record(
                    f"historical-replay-obligation:{replay_obligation_id}",
                    1,
                )
                != obligation_record
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay obligation differs from the active Mission"
                )
            family_record = index.get(
                "historical-family-authority",
                family_authority_id,
            )
            try:
                if family_record is None:
                    raise HistoricalFamilyAuthorityAdmissionError(
                        "historical family authority is absent"
                    )
                family_authority = require_recorded_historical_family_authority(
                    index,
                    family_record,
                )
            except HistoricalFamilyAuthorityAdmissionError as exc:
                raise RunningJobAuthorityError(
                    "fixed-hold historical family authority is malformed: "
                    f"{exc}"
                ) from exc
            family = family_authority.family
            if (
                family_record.kind != "historical-family-authority"
                or family_record.record_id != family_authority_id
                or family_record.subject
                != f"ReplayObligation:{replay_obligation_id}"
                or family_record.status != "accepted"
                or family_record.fingerprint
                != family_authority_id.removeprefix(
                    "historical-family-authority:"
                )
                or family_authority.identity != family_authority_id
                or family_authority.replay_obligation_id
                != replay_obligation_id
                or family.original_study_id
                != obligation.original_study_id
                or family.target_historical_executable_id
                != obligation.original_executable_id
                or family.family_size != expected_family_size
                or proposal.get("historical_family_identity")
                != family.identity
                or proposal.get("original_study_id")
                != family.original_study_id
                or proposal.get("concurrent_family") != family.manifest()
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold historical family differs from its obligation"
                )
            selected_assignment_bindings: list[tuple[Any, Any, Any]] = []
            if assignment_set is not None:
                primary_family_core = historical_family_core_identity(family)
                for assignment in assignment_set.assignments:
                    selected_obligation_record = index.get(
                        "historical-replay-obligation",
                        assignment.obligation_id,
                    )
                    selected_obligation_payload = (
                        None
                        if selected_obligation_record is None
                        else selected_obligation_record.payload.get(
                            "obligation"
                        )
                    )
                    selected_family_record = index.get(
                        "historical-family-authority",
                        assignment.historical_family_authority_id,
                    )
                    try:
                        if not isinstance(
                            selected_obligation_payload,
                            Mapping,
                        ) or selected_family_record is None:
                            raise ReplayObligationError(
                                "selected replay authority is absent"
                            )
                        selected_obligation = (
                            historical_replay_obligation_from_identity_payload(
                                selected_obligation_payload
                            )
                        )
                        selected_family_authority = (
                            require_recorded_historical_family_authority(
                                index,
                                selected_family_record,
                            )
                        )
                    except (
                        HistoricalFamilyAuthorityAdmissionError,
                        ReplayObligationError,
                    ) as exc:
                        raise RunningJobAuthorityError(
                            f"selected replay authority is malformed: {exc}"
                        ) from exc
                    selected_family = selected_family_authority.family
                    selected_family_core = historical_family_core_identity(
                        selected_family
                    )
                    if (
                        selected_obligation_record.record_id
                        != assignment.obligation_id
                        or selected_obligation_record.subject
                        != f"Mission:{bound.mission_id}"
                        or selected_obligation_record.status != "pending"
                        or selected_obligation.identity
                        != assignment.obligation_id
                        or selected_obligation.governing_mission_id
                        != bound.mission_id
                        or selected_obligation.original_executable_id
                        != assignment.original_executable_id
                        or selected_obligation.criterion_ids
                        != assignment.criterion_ids
                        or selected_family_record.record_id
                        != assignment.historical_family_authority_id
                        or selected_family_record.subject
                        != f"ReplayObligation:{assignment.obligation_id}"
                        or selected_family_record.status != "accepted"
                        or selected_family_authority.identity
                        != assignment.historical_family_authority_id
                        or selected_family_authority.replay_obligation_id
                        != assignment.obligation_id
                        or selected_family.target_historical_executable_id
                        != assignment.original_executable_id
                        or selected_family_core != primary_family_core
                        or selected_family_authority.reconstruction_source_path
                        != family_authority.reconstruction_source_path
                        or selected_family_authority.reconstruction_source_sha256
                        != family_authority.reconstruction_source_sha256
                        or selected_family_authority.reconstruction_only_parameter_names
                        != family_authority.reconstruction_only_parameter_names
                    ):
                        raise RunningJobAuthorityError(
                            "selected replay authority differs from its assignment"
                        )
                    selected_assignment_bindings.append(
                        (
                            assignment,
                            selected_obligation,
                            selected_family_record,
                        )
                    )
            try:
                original_family_end_global_exposure_count = (
                    project_historical_family_end_global_exposure_count(
                        index,
                        prior_global_exposure_floor=(
                            self.prior_global_multiplicity_floor
                        ),
                        family=family,
                    )
                )
            except ScientificHistoryProjectionError as exc:
                raise RunningJobAuthorityError(str(exc)) from exc
            batch = index.get("batch-open", batch_id)
            batch_payload = None if batch is None else batch.payload
            batch_spec = (
                None
                if not isinstance(batch_payload, Mapping)
                else batch_payload.get("spec")
            )
            acceptance = (
                None
                if not isinstance(batch_spec, Mapping)
                else batch_spec.get("acceptance_profile")
            )
            batch_digest = (
                None
                if not isinstance(batch_spec, Mapping)
                else canonical_digest(
                    domain="batch-spec",
                    payload=dict(batch_spec),
                )
            )
            concurrent_family = (
                None
                if not isinstance(acceptance, Mapping)
                else acceptance.get("concurrent_family")
            )
            expected_acceptance_fields = {
                "candidate_authority",
                "concurrent_family",
                "exact_original_criteria",
                "historical_family_authority_id",
                "historical_family_identity",
                "replay_obligation_id",
            }
            if assignment_set is not None:
                expected_acceptance_fields.add(
                    "replay_member_assignment_set_id"
                )
            active_batch = science.get("active_batch")
            if (
                batch is None
                or batch.kind != "batch-open"
                or batch.record_id != batch_id
                or batch.subject != f"Study:{study_id}"
                or batch.status != "open"
                or not isinstance(batch_payload, Mapping)
                or not isinstance(batch_spec, Mapping)
                or not isinstance(acceptance, Mapping)
                or batch_digest is None
                or batch_id != f"batch:{batch_digest}"
                or batch.fingerprint != batch_digest
                or batch_payload.get("batch_hash") != batch_digest
                or batch_spec.get("study_hash") != study.fingerprint
                or batch_spec.get("max_trials") != expected_family_size
                or acceptance.get("replay_obligation_id")
                != replay_obligation_id
                or acceptance.get("historical_family_authority_id")
                != family_authority_id
                or acceptance.get("historical_family_identity")
                != family.identity
                or acceptance.get("candidate_authority") != "none"
                or acceptance.get("exact_original_criteria")
                != list(obligation.criterion_ids)
                or set(acceptance) != expected_acceptance_fields
                or (
                    assignment_set is not None
                    and acceptance.get(
                        "replay_member_assignment_set_id"
                    )
                    != assignment_set.identity
                )
                or not isinstance(concurrent_family, Mapping)
                or concurrent_family.get("schema")
                != "concurrent_family_manifest.v1"
                or concurrent_family.get("family_size")
                != expected_family_size
                or not isinstance(active_batch, Mapping)
                or active_batch.get("id") != batch_id
                or active_batch.get("hash") != batch_digest
                or active_batch.get("status") != "open"
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay Batch authority is malformed"
                )
            exposure = project_frozen_family_exposure_context(
                index,
                prior_global_exposure_floor=(
                    self.prior_global_multiplicity_floor
                ),
                study_id=study_id,
                batch_id=batch_id,
                expected_family_size=expected_family_size,
                parameter_name=parameter_name,
                allow_unregistered=False,
            )
            if (
                exposure.prior_global_exposure_count
                < original_family_end_global_exposure_count
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay predates its original family end"
                )
            concurrent_ids = concurrent_family.get("executable_ids")
            registered_bindings = project_registered_replay_member_bindings(
                index,
                study_id=study_id,
                batch_id=batch_id,
            )
            registered_ids = tuple(item[0] for item in registered_bindings)
            registered_historical_ids = tuple(
                item[1] for item in registered_bindings
            )
            historical_family_ids = tuple(
                member.historical_reference_executable_id
                for member in family.members
            )
            if (
                type(concurrent_ids) is not list
                or len(concurrent_ids) != expected_family_size
                or len(set(concurrent_ids)) != len(concurrent_ids)
                or any(type(item) is not str for item in concurrent_ids)
                or not exposure.family_executable_ids
                or any(
                    item not in concurrent_ids
                    for item in exposure.family_executable_ids
                )
                or registered_ids != exposure.family_executable_ids
                or len(registered_ids) != expected_family_size
                or registered_historical_ids != historical_family_ids
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold prospective family differs from its Batch"
                )
            registered_by_historical_executable = {
                historical_id: executable_id
                for executable_id, historical_id in registered_bindings
            }
            if assignment_set is not None and any(
                registered_by_historical_executable.get(
                    assignment.original_executable_id
                )
                != assignment.replay_executable_id
                for assignment in assignment_set.assignments
            ):
                raise RunningJobAuthorityError(
                    "selected replay assignments differ from registered members"
                )
            try:
                (
                    execution_prefix_executable_ids,
                    completed_member_executable_ids,
                ) = project_running_batch_job_prefix(
                    index,
                    mission_id=bound.mission_id,
                    study_id=study_id,
                    batch_id=batch_id,
                    expected_executable_ids=registered_ids,
                    active_job_id=bound.execution.job_id,
                    subject_executable_id=subject_executable_id,
                )
            except ScientificHistoryProjectionError as exc:
                raise RunningJobAuthorityError(str(exc)) from exc
            obligation_stream = (
                f"historical-replay-obligation:{replay_obligation_id}"
            )
            obligation_head = index.event_head(obligation_stream)
            current_obligation = (
                None
                if obligation_head is None
                else index.get(
                    obligation_head.record_kind,
                    obligation_head.record_id,
                )
            )
            target_ordinal = (
                historical_family_ids.index(
                    family.target_historical_executable_id
                )
                + 1
            )
            target_prospective_executable_id = registered_ids[
                target_ordinal - 1
            ]
            if (
                assignment_set is not None
                and assignment_set.primary.replay_executable_id
                != target_prospective_executable_id
            ):
                raise RunningJobAuthorityError(
                    "primary replay assignment differs from its family target"
                )
            if (
                current_obligation is None
                or current_obligation.subject != f"Mission:{bound.mission_id}"
                or current_obligation.event_stream != obligation_stream
                or current_obligation.event_sequence != obligation_head.sequence
                or current_obligation.status not in {"pending", "in_progress"}
                or (
                    current_obligation.record_id != replay_obligation_id
                    and current_obligation.payload.get("obligation_id")
                    != replay_obligation_id
                )
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay obligation current head is not executable"
                )
            if current_obligation.status != "in_progress":
                raise RunningJobAuthorityError(
                    "fixed-hold fully registered family lacks progress authority"
                )
            binding = _require_replay_progress_transition(
                index,
                obligation=obligation,
                record=current_obligation,
                require_current_head=True,
            )
            if (
                binding.portfolio_decision_id
                != study_payload.get("portfolio_decision_id")
                or binding.replay_study_id != study_id
                or binding.replay_executable_id
                != target_prospective_executable_id
            ):
                raise RunningJobAuthorityError(
                    "fixed-hold replay execution binding differs from its Study"
                )
            invalidation = _require_correction_invalidation_route(
                index,
                obligation=obligation,
                current_progress=current_obligation,
            )
            _require_correction_pending_invalidation(
                index,
                obligation=obligation,
                record=invalidation,
                family_record=family_record,
                require_current_head=False,
            )
            for (
                assignment,
                selected_obligation,
                selected_family_record,
            ) in selected_assignment_bindings:
                if assignment.obligation_id == replay_obligation_id:
                    continue
                selected_stream = (
                    "historical-replay-obligation:"
                    + assignment.obligation_id
                )
                selected_head = index.event_head(selected_stream)
                selected_current = (
                    None
                    if selected_head is None
                    else index.get(
                        selected_head.record_kind,
                        selected_head.record_id,
                    )
                )
                if (
                    selected_current is None
                    or selected_current.subject
                    != f"Mission:{bound.mission_id}"
                    or selected_current.event_stream != selected_stream
                    or selected_current.event_sequence
                    != selected_head.sequence
                    or selected_current.status != "in_progress"
                    or (
                        selected_current.record_id
                        != assignment.obligation_id
                        and selected_current.payload.get("obligation_id")
                        != assignment.obligation_id
                    )
                ):
                    raise RunningJobAuthorityError(
                        "selected replay obligation is not in progress"
                    )
                selected_progress = _require_replay_progress_transition(
                    index,
                    obligation=selected_obligation,
                    record=selected_current,
                    require_current_head=True,
                )
                if (
                    selected_progress.portfolio_decision_id
                    != study_payload.get("portfolio_decision_id")
                    or selected_progress.replay_study_id != study_id
                    or selected_progress.replay_executable_id
                    != assignment.replay_executable_id
                ):
                    raise RunningJobAuthorityError(
                        "selected replay progress differs from its assignment"
                    )
                selected_invalidation = (
                    _require_correction_invalidation_route(
                        index,
                        obligation=selected_obligation,
                        current_progress=selected_current,
                    )
                )
                _require_correction_pending_invalidation(
                    index,
                    obligation=selected_obligation,
                    record=selected_invalidation,
                    family_record=selected_family_record,
                    require_current_head=False,
                )
        return RunningJobFixedHoldReplayContext(
            family_authority_id=family_authority_id,
            replay_obligation_id=replay_obligation_id,
            family=family,
            original_family_end_global_exposure_count=(
                original_family_end_global_exposure_count
            ),
            exposure=exposure,
            batch_family_executable_ids=tuple(sorted(concurrent_ids)),
            registered_member_bindings=registered_bindings,
            execution_prefix_executable_ids=(
                execution_prefix_executable_ids
            ),
            completed_member_executable_ids=(
                completed_member_executable_ids
            ),
            target_prospective_executable_id=(
                target_prospective_executable_id
            ),
        )

    def project_bound_source_state(
        self,
        *,
        source_contract_id: str,
    ) -> RunningJobSourceState:
        """Return the current state of the verified Job's exact source."""

        bound = self._bound()
        if (
            bound.subject_kind != "Study"
            or bound.subject_id != bound.study_id
            or bound.source_contract_id != source_contract_id
        ):
            raise RunningJobAuthorityError(
                "source-state request differs from the verified Job"
            )
        authority = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__authority",
        )
        with authority.open_stable_index() as (control, index):
            _require_bound_active_job(control, bound)
            head = index.event_head(f"source:{source_contract_id}")
            state = (
                None
                if head is None
                else index.get(head.record_kind, head.record_id)
            )
        if state is None:
            raise RunningJobAuthorityError(
                "verified running Job source state is absent"
            )
        return RunningJobSourceState(
            record_id=state.record_id,
            status=state.status,
            _payload_bytes=canonical_bytes(state.payload),
        )

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None:
        authority = object.__getattribute__(
            self,
            "_RunningJobExecutionContext__authority",
        )
        authority.verify_reproducible_cache_producer(
            producer,
            **kwargs,
        )


def running_job_execution_context_dependency_paths() -> tuple[Path, ...]:
    """Return the complete project-local source closure of this context."""

    return tuple(
        sorted(
            {
                _THIS_FILE,
                Path(completion_validity_projection.__file__).resolve(),
                Path(evidence_module.__file__).resolve(),
                Path(
                    historical_family_authority_admission_module.__file__
                ).resolve(),
                Path(historical_family_binding_module.__file__).resolve(),
                Path(historical_scientific_validity.__file__).resolve(),
                Path(replay_exposure_module.__file__).resolve(),
                Path(replay_member_assignment_module.__file__).resolve(),
                Path(replay_obligation_module.__file__).resolve(),
                Path(replay_satisfaction_invalidation_module.__file__).resolve(),
                Path(semantic_question_module.__file__).resolve(),
                Path(recorded_transition_authority_module.__file__).resolve(),
                Path(scientific_history_module.__file__).resolve(),
                Path(trials_module.__file__).resolve(),
                *running_job_authority_dependency_paths(),
            },
            key=lambda path: path.as_posix(),
        )
    )


def running_job_execution_context_dependency_manifest() -> dict[str, Any]:
    """Describe the exact project-local source closure with canonical paths."""

    source_root = _THIS_FILE.parents[2]
    dependencies: list[dict[str, str]] = []
    for path in running_job_execution_context_dependency_paths():
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(source_root).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                "running Job context dependency escapes the project source root"
            ) from exc
        dependencies.append(
            {
                "path": relative,
                "sha256": sha256(resolved.read_bytes()).hexdigest(),
            }
        )
    value: dict[str, Any] = {
        "dependencies": dependencies,
        "schema": "running_job_execution_context_dependency_closure.v1",
    }
    return value


@lru_cache(maxsize=1)
def running_job_execution_context_implementation_sha256() -> str:
    """Return one process-stable identity for the loaded context closure.

    A new interpreter recomputes every bound byte.  Process-local caching both
    avoids repeated filesystem validation in every runner and prevents a hot
    edit on disk from relabeling code that this interpreter already loaded.
    """

    return canonical_digest(
        domain="running-job-execution-context-dependency-closure",
        payload=running_job_execution_context_dependency_manifest(),
    )


__all__ = [
    "RunningJobEvidence",
    "RunningJobExecutionContext",
    "RunningJobFixedHoldReplayContext",
    "RunningJobSourceState",
    "running_job_execution_context_dependency_manifest",
    "running_job_execution_context_dependency_paths",
    "running_job_execution_context_implementation_sha256",
]
