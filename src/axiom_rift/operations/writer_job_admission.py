"""Job identity, replay preflight, retry admission, and declaration transitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.external_dependency import (
    ExternalDependencyContractError,
    ExternalRecoveryPlan,
    external_plan_from_binding,
)
from axiom_rift.operations.external_observed_development_binding import (
    ExternalObservedDevelopmentJobBindingError,
    external_observed_development_job_binding,
    verify_external_observed_development_job_prefixes,
)
from axiom_rift.operations.historical_replay_implementation_authority import (
    HistoricalReplayImplementationAuthorityError,
    authenticated_historical_implementation_sources,
)
from axiom_rift.operations.job_admission_authority import (
    JobAdmissionAuthorityError,
    require_job_admission,
)
from axiom_rift.operations.job_cache_authority import (
    JobCacheAuthorityError,
    require_cached_success_binding,
    require_reusable_success_outputs,
)
from axiom_rift.operations.job_contract import (
    JobContractError,
    build_job_identity_plan,
    normalize_job_spec,
    validate_job_spec,
)
from axiom_rift.operations.job_implementation_authority import (
    JobImplementationAuthorityError,
    implementation_source_closure_hashes,
    require_job_implementation_evidence,
    requires_current_source_authority,
)
from axiom_rift.operations.job_retry_admission import (
    JobRetryAdmissionIntegrityError,
    JobRetryAdmissionRejected,
    JobRetryAdmissionSpecificationError,
    build_retry_family_declaration_record,
    prepare_job_retry_admission,
)
from axiom_rift.operations.job_retry_family import (
    JobRetryFamilyError,
    JobRetryValidationAuthority,
    JobRetryValidationDispatchRequired,
    validate_engineering_retry_evidence,
)
from axiom_rift.operations.observed_development_binding import (
    ObservedDevelopmentBindingError,
    scientific_observed_development_job_binding,
    verify_observed_development_prefix_artifact,
)
from axiom_rift.operations.permits import SubjectKind
from axiom_rift.operations.runtime_completion import (
    RuntimeSuccessAuthorityError,
    candidate_job_execution_context,
    current_runtime_source_snapshot,
)
from axiom_rift.operations.scientific_multiplicity_authority import (
    ScientificMultiplicityAuthorityError,
    ScientificMultiplicityIntegrityError,
    require_concurrent_family_registration,
)
from axiom_rift.operations.validation import (
    EvidenceValidationError,
)
from axiom_rift.operations.writer_lifecycle import (
    _concurrent_family_executable_ids,
)
from axiom_rift.operations.writer_support import (
    IdenticalFailedRetryError,
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _copy,
    _digest,
    _record,
    _require_ascii,
    _require_digest,
    _require_study_evidence_modes,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


_JOB_RETRY_VALIDATION_CAPABILITY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _JobRetryValidationCapability:
    """One or more retry validators executed outside one stable Writer head."""

    token: object
    control_hash: str
    authorities: Mapping[str, JobRetryValidationAuthority]


class _JobRetryValidationOutsideLock(RuntimeError):
    """Internal unwind from a dry Writer pass to a lock-free validator."""

    def __init__(
        self,
        *,
        control_hash: str,
        requirement: JobRetryValidationDispatchRequired,
    ) -> None:
        super().__init__(str(requirement))
        self.control_hash = control_hash
        self.requirement = requirement


_job_implementation_source_closure_hashes = implementation_source_closure_hashes


def _job_requires_current_source_authority(
    *, engineering_fixture: bool, evidence_subject_kind: object
) -> bool:
    """Apply one explicit source-authority policy to every Job subject."""

    try:
        return requires_current_source_authority(
            engineering_fixture=engineering_fixture,
            evidence_subject_kind=evidence_subject_kind,
        )
    except JobImplementationAuthorityError as exc:
        raise TransitionError(str(exc)) from exc


def _require_concurrent_family_registration(
    index: LocalIndex,
    *,
    batch_record: IndexRecord,
    evidence_subject: Mapping[str, Any],
) -> None:
    try:
        require_concurrent_family_registration(
            index,
            batch_record=batch_record,
            evidence_subject=evidence_subject,
        )
    except ScientificMultiplicityIntegrityError as exc:
        raise RecoveryRequired(str(exc)) from exc
    except ScientificMultiplicityAuthorityError as exc:
        raise TransitionError(str(exc)) from exc


class JobAdmissionWriterMixin:
    """Own immutable Job admission and declaration; the facade commits atomically."""

    @staticmethod
    def _normalize_job_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
        return normalize_job_spec(spec)

    @staticmethod
    def _validate_job_spec(spec: Mapping[str, Any]) -> None:
        try:
            validate_job_spec(
                spec,
                evidence_modes_validator=_require_study_evidence_modes,
            )
        except JobContractError as exc:
            raise TransitionError(str(exc)) from exc

    def _require_job_implementation_evidence(
        self,
        spec: Mapping[str, Any],
        *,
        _index: LocalIndex | LocalIndexView | None = None,
    ) -> Mapping[str, Any]:
        def require(
            index: LocalIndex | LocalIndexView,
        ) -> Mapping[str, Any]:
            try:
                historical_sources = (
                    authenticated_historical_implementation_sources(
                        spec,
                        index=index,
                        artifact_reader=self.evidence.read_verified,
                    )
                )
                return require_job_implementation_evidence(
                    spec,
                    artifact_reader=self.evidence.read_verified,
                    historical_source_authorities=historical_sources,
                )
            except (
                HistoricalReplayImplementationAuthorityError,
                JobImplementationAuthorityError,
            ) as exc:
                raise TransitionError(str(exc)) from exc

        if _index is not None:
            return require(_index)
        with self.open_stable_index() as (_control, index):
            return require(index)

    def _require_reusable_success_outputs(
        self, *, completion: IndexRecord, spec: Mapping[str, Any]
    ) -> None:
        try:
            require_reusable_success_outputs(
                completion_payload=completion.payload,
                spec=spec,
                repository_root=self.root,
                durable_verifier=self.evidence.verify,
            )
        except JobCacheAuthorityError as exc:
            raise RecoveryRequired(str(exc)) from exc

    def _preflight_scientific_binding(self, spec: Mapping[str, Any]) -> None:
        binding = spec.get("scientific_binding")
        if not isinstance(binding, Mapping):
            return
        try:
            self.validation_registry.preflight_binding(
                validator_id=binding["validator_id"],
                domain="scientific",
                binding=binding,
            )
        except EvidenceValidationError as exc:
            raise TransitionError(
                f"scientific validation preflight failed: {exc}"
            ) from exc

    def _authority_requires_scientific_adjudication_v2(
        self,
        current: Mapping[str, Any],
    ) -> bool:
        authority = current.get("authority")
        if not isinstance(authority, Mapping):
            raise RecoveryRequired("scientific protocol authority is unavailable")
        contracts = authority.get("contracts")
        if not isinstance(contracts, list):
            raise RecoveryRequired("scientific protocol contract manifest is invalid")
        root = self.foundation_root.resolve()
        for relative in contracts:
            _require_ascii("authority contract path", relative)
            path = (root / relative).resolve()
            if root != path and root not in path.parents:
                raise RecoveryRequired("scientific protocol contract escapes Foundation")
            if not path.is_file():
                raise RecoveryRequired("scientific protocol contract is unavailable")
            if any(
                line.strip() == b"scientific_adjudication_v2:"
                for line in path.read_bytes().splitlines()
            ):
                return True
        return False

    def record_replay_job_implementation_preflight(
        self,
        *,
        request: Any,
        operation_id: str,
        repair_close_record_id: str | None = None,
    ) -> TransitionResult:
        """Check one replay family before it spends trial or Job budget.

        The Writer derives scope from the current Mission and Batch, invokes
        the byte inspector inside the stable-index lock, and writes the result
        itself.  Callers cannot submit an ``accepted`` result.  Rejection is
        operational evidence only and routes the Batch to an unavailable
        disposition without manufacturing a failed Job.  An exact successful
        running-Job implementation Repair may use the same evaluator to append
        a successor family admission after that Job is completed and judged;
        the completed prefix and predecessor admission are re-derived here.
        """

        from axiom_rift.operations.replay_job_implementation_preflight import (
            PREFLIGHT_SCHEMA,
            ReplayJobImplementationPreflightError,
            ReplayJobImplementationPreflightRequest,
            derive_replay_job_scientific_surface,
            evaluate_replay_job_implementation_preflight,
            replay_job_scientific_surface_hash,
            require_active_replay_job_replacement_binding,
            require_durable_replay_job_implementation_preflight,
            require_replacement_replay_job_scientific_surface,
        )
        from axiom_rift.operations.replay_projection import (
            ReplayProjectionError,
            ReplayTransitionError,
            obligation_heads,
            require_current_replacement_preflight_basis,
        )
        from axiom_rift.research.replay_obligation import ReplayObligationStatus

        self._require_study_close_delivery_guard()
        if not isinstance(request, ReplayJobImplementationPreflightRequest):
            raise TransitionError(
                "replay Job implementation preflight request is not typed"
            )
        if repair_close_record_id is not None:
            _require_digest(
                "replay implementation Repair close",
                repair_close_record_id,
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError(
                    "replay Job implementation preflight requires control"
                )
            science = current["scientific"]
            mission_id = science.get("active_mission")
            if mission_id != request.mission_id:
                raise TransitionError(
                    "replay implementation preflight belongs to another Mission"
                )
            if science.get("active_job") is not None or science.get(
                "active_repair"
            ) is not None:
                raise TransitionError(
                    "replay implementation preflight cannot bypass active work"
                )
            heads = {
                obligation.identity: (obligation, head)
                for obligation, head in obligation_heads(
                    index,
                    mission_id=mission_id,
                )
            }
            selected = tuple(
                heads.get(obligation_id)
                for obligation_id in request.replay_obligation_ids
            )
            if any(item is None for item in selected):
                raise TransitionError(
                    "replay implementation preflight lacks its exact obligation"
                )
            active_batch = science.get("active_batch")
            active_study_id = science.get("active_study")
            batch_id: str | None = None
            study_id: str | None = None
            surface_batch: IndexRecord | None = None
            surface_study: IndexRecord | None = None
            current_admission: IndexRecord | None = None
            required_replacement_preflight: IndexRecord | None = None
            registration_inspection: Any | None = None
            repair_boundary: Any | None = None
            protocol_failure: str | None = None
            protocol_activation: IndexRecord | None = None
            replacement = request.replacement_for_preflight_id
            replaced_record = (
                None
                if replacement is None
                else index.get("job-implementation-preflight", replacement)
            )
            if isinstance(active_batch, Mapping):
                if replacement is not None:
                    raise TransitionError(
                        "active replay preflight cannot replace another preflight"
                    )
                batch_id = active_batch.get("id")
                study_id = active_study_id
                batch = (
                    None
                    if not isinstance(batch_id, str)
                    else index.get("batch-open", batch_id)
                )
                study = (
                    None
                    if not isinstance(study_id, str)
                    else index.get("study-open", study_id)
                )
                surface_batch = batch
                surface_study = study
                resolved_family_ids = (
                    None
                    if batch is None
                    else _concurrent_family_executable_ids(batch)
                )
                family_ids = (
                    None
                    if resolved_family_ids is None
                    else list(resolved_family_ids)
                )
                action = current.get("next_action")
                if study is not None and batch is not None:
                    from axiom_rift.operations.replay_study_admission import (
                        ReplayStudyAdmissionError,
                        inspect_replay_study_registration,
                    )

                    try:
                        registration_inspection = (
                            inspect_replay_study_registration(
                                index,
                                study_record=study,
                                batch_record=batch,
                            ).require_usable()
                        )
                    except ReplayStudyAdmissionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                budget_head = (
                    None
                    if not isinstance(batch_id, str)
                    else index.event_head(f"batch-budget:{batch_id}")
                )
                declarations = (
                    ()
                    if not isinstance(batch_id, str)
                    else tuple(
                        index.records_by_payload_text(
                            "job-declared",
                            "batch_id",
                            batch_id,
                        )
                    )
                )
                existing_preflight_head = (
                    None
                    if not isinstance(batch_id, str)
                    else index.event_head(
                        "replay-job-implementation-preflight-batch:"
                        + batch_id
                    )
                )
                current_admission = (
                    None
                    if not isinstance(study_id, str)
                    else self._study_replay_implementation_admission(
                        index,
                        study_id=study_id,
                        authority_manifest_digest=current.get(
                            "authority", {}
                        ).get("manifest_digest"),
                    )
                )
                if (
                    batch is None
                    or study is None
                    or study.payload.get("mission_id") != mission_id
                    or study.payload.get("replay_obligation_ids")
                    != list(request.replay_obligation_ids)
                    or not isinstance(family_ids, list)
                    or len(family_ids) != len(request.executable_ids)
                    or set(family_ids) != set(request.executable_ids)
                    or not isinstance(action, Mapping)
                    or action.get("kind") != "declare_job"
                    or action.get("batch_id") != batch_id
                    or registration_inspection is None
                    or registration_inspection.expected_executable_ids
                    != request.executable_ids
                    or (
                        repair_close_record_id is None
                        and (
                            current_admission is not None
                            or budget_head is not None
                            or declarations
                            or existing_preflight_head is not None
                        )
                    )
                    or (
                        repair_close_record_id is not None
                        and current_admission is None
                    )
                ):
                    raise TransitionError(
                        "replay implementation preflight differs from the active family"
                    )
                if repair_close_record_id is not None:
                    assert current_admission is not None
                    assert study is not None
                    assert batch is not None
                    from axiom_rift.operations import (
                        replay_implementation_repair_admission
                        as repair_module,
                    )

                    boundary_inspector = (
                        repair_module.inspect_replay_implementation_repair_boundary
                    )
                    boundary_error = (
                        repair_module.ReplayImplementationRepairAdmissionError
                    )

                    try:
                        repair_boundary = boundary_inspector(
                            index,
                            predecessor_admission=current_admission,
                            study_record=study,
                            batch_record=batch,
                            request=request.to_identity_payload(),
                            registration_inspection=registration_inspection,
                            trigger_repair_close_record_id=(
                                repair_close_record_id
                            ),
                        )
                    except boundary_error as exc:
                        raise TransitionError(str(exc)) from exc
                if any(
                    item is None
                    or item[1].status
                    not in {
                        ReplayObligationStatus.PENDING.value,
                        ReplayObligationStatus.IN_PROGRESS.value,
                    }
                    for item in selected
                ):
                    raise TransitionError(
                        "active replay preflight obligation is not schedulable"
                    )
                protocol_failure = self._replay_scientific_protocol_failure(
                    current,
                    index,
                    request=request,
                )
                if protocol_failure is not None:
                    raise TransitionError(
                        "replay implementation preflight requires an exact "
                        "prospective protocol rebind before recertification: "
                        + protocol_failure
                    )
                from axiom_rift.operations.research_protocol_projection import (
                    ResearchProtocolProjectionError,
                    require_current_research_protocol_activation,
                )

                try:
                    protocol_activation = (
                        require_current_research_protocol_activation(
                            index,
                            authority_manifest_digest=current.get(
                                "authority", {}
                            ).get("manifest_digest"),
                        )
                    )
                except ResearchProtocolProjectionError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                if repair_boundary is not None:
                    assert current_admission is not None
                    accepted_id = current_admission.payload.get(
                        "accepted_replacement_preflight_id"
                    )
                    required_replacement_preflight = (
                        None
                        if accepted_id is None
                        else index.get(
                            "job-implementation-preflight",
                            str(accepted_id),
                        )
                    )
                    if accepted_id is not None and (
                        required_replacement_preflight is None
                    ):
                        raise RecoveryRequired(
                            "post-Repair replay admission lost its "
                            "replacement authority"
                        )
                else:
                    if (
                        type(study.authority_sequence) is not int
                        or type(protocol_activation.authority_sequence) is not int
                        or study.authority_sequence
                        >= protocol_activation.authority_sequence
                    ):
                        raise RecoveryRequired(
                            "missing replay admission is not inside the legacy "
                            "pre-activation recertification boundary"
                        )
                    replacement_triggers: list[IndexRecord] = []
                    for _obligation, head_record in selected:
                        prior = (
                            None
                            if not isinstance(head_record.event_stream, str)
                            or type(head_record.event_sequence) is not int
                            or head_record.event_sequence < 2
                            else index.event_record(
                                head_record.event_stream,
                                head_record.event_sequence - 1,
                            )
                        )
                        resume_evidence = (
                            None
                            if prior is None
                            or prior.kind
                            != "historical-replay-obligation-resume"
                            else prior.payload.get("resume_evidence")
                        )
                        trigger_id = (
                            None
                            if not isinstance(resume_evidence, Mapping)
                            else resume_evidence.get("trigger_record_id")
                        )
                        trigger = (
                            None
                            if not isinstance(trigger_id, str)
                            else index.get(
                                "job-implementation-preflight",
                                trigger_id,
                            )
                        )
                        if trigger is not None and trigger.payload.get(
                            "replacement_for_preflight_id"
                        ) is not None:
                            replacement_triggers.append(trigger)
                    if replacement_triggers:
                        trigger_ids = {
                            record.record_id for record in replacement_triggers
                        }
                        if (
                            len(replacement_triggers) != len(selected)
                            or len(trigger_ids) != 1
                        ):
                            raise TransitionError(
                                "active replay family mixes replacement authorities"
                            )
                        required_replacement_preflight = replacement_triggers[0]
            else:
                replaced_batch_id = (
                    None
                    if replaced_record is None
                    else replaced_record.payload.get("batch_id")
                )
                replaced_study_id = (
                    None
                    if replaced_record is None
                    else replaced_record.payload.get("study_id")
                )
                surface_batch = (
                    None
                    if not isinstance(replaced_batch_id, str)
                    else index.get("batch-open", replaced_batch_id)
                )
                surface_study = (
                    None
                    if not isinstance(replaced_study_id, str)
                    else index.get("study-open", replaced_study_id)
                )
                if (
                    science.get("active_study") is not None
                    or science.get("active_executable") is not None
                    or replaced_record is None
                    or replaced_record.status != "rejected"
                    or replaced_record.payload.get("schema") != PREFLIGHT_SCHEMA
                    or replaced_record.payload.get("mission_id") != mission_id
                    or replaced_record.payload.get("replay_obligation_ids")
                    != list(request.replay_obligation_ids)
                    or surface_batch is None
                    or surface_study is None
                    or any(
                        item is None
                        or item[1].status
                        != ReplayObligationStatus.DEFERRED.value
                        for item in selected
                    )
                    or index.event_head(
                        "replay-job-implementation-preflight-replacement:"
                        + str(replacement)
                    )
                    is not None
                ):
                    raise TransitionError(
                        "replacement replay preflight lacks its current deferral"
                    )
                for selected_item in selected:
                    assert selected_item is not None
                    obligation, deferral_head = selected_item
                    try:
                        current_rejection = (
                            require_current_replacement_preflight_basis(
                                index,
                                obligation=obligation,
                                deferral_head=deferral_head,
                                rejected_preflight_id=replacement,
                            )
                        )
                    except ReplayProjectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    except ReplayTransitionError as exc:
                        raise TransitionError(str(exc)) from exc
                    if current_rejection.record_id != replaced_record.record_id:
                        raise TransitionError(
                            "replacement replay preflight names another rejection"
                        )
            if surface_batch is None or surface_study is None:
                raise TransitionError(
                    "replay implementation preflight lacks its scientific surface"
                )
            try:
                for binding in request.scientific_binding_values():
                    self._preflight_scientific_binding(
                        {"scientific_binding": binding}
                    )
                scientific_surface = derive_replay_job_scientific_surface(
                    request,
                    study_payload=surface_study.payload,
                    batch_payload=surface_batch.payload,
                    artifact_reader=self.evidence.read_verified,
                    registered_batch_executable_ids=(
                        None
                        if replaced_record is None
                        else tuple(
                            replaced_record.payload.get(
                                "executable_ids",
                                (),
                            )
                        )
                    ),
                )
                scientific_surface_hash = (
                    replay_job_scientific_surface_hash(scientific_surface)
                )
            except ReplayJobImplementationPreflightError as exc:
                raise TransitionError(str(exc)) from exc
            if repair_boundary is not None and (
                current_admission is None
                or current_admission.payload.get("scientific_surface")
                != scientific_surface
                or current_admission.payload.get("scientific_surface_hash")
                != scientific_surface_hash
            ):
                raise TransitionError(
                    "post-Repair recertification changed the admitted "
                    "scientific surface"
                )
            scientific_candidate = {
                "callable_identity": request.callable_identity,
                "executable_ids": list(request.executable_ids),
                "executable_manifests": [
                    executable.to_identity_payload()
                    for executable in request.executables
                ],
                "implementation_identity": request.implementation_identity,
                "mission_id": request.mission_id,
                "protocol_id": request.protocol_id,
                "replacement_for_preflight_id": replacement,
                "replay_obligation_ids": list(
                    request.replay_obligation_ids
                ),
                "schema": PREFLIGHT_SCHEMA,
                "scientific_surface": scientific_surface,
                "scientific_surface_hash": scientific_surface_hash,
            }
            if replaced_record is not None:
                try:
                    require_replacement_replay_job_scientific_surface(
                        prior_preflight_id=replaced_record.record_id,
                        prior_payload=replaced_record.payload,
                        replacement_payload=scientific_candidate,
                    )
                except ReplayJobImplementationPreflightError as exc:
                    raise TransitionError(str(exc)) from exc
            if required_replacement_preflight is not None:
                trigger_head = (
                    None
                    if not isinstance(
                        required_replacement_preflight.event_stream,
                        str,
                    )
                    else index.event_head(
                        required_replacement_preflight.event_stream
                    )
                )
                if repair_boundary is None:
                    try:
                        require_active_replay_job_replacement_binding(
                            accepted_payload=(
                                required_replacement_preflight.payload
                            ),
                            active_payload=scientific_candidate,
                        )
                    except ReplayJobImplementationPreflightError as exc:
                        raise TransitionError(str(exc)) from exc
                if (
                    required_replacement_preflight.status != "accepted"
                    or trigger_head is None
                    or trigger_head.record_id
                    != required_replacement_preflight.record_id
                ):
                    raise TransitionError(
                        "active replay family lacks its current accepted replacement"
                    )
            result = evaluate_replay_job_implementation_preflight(
                request,
                index=index,
                artifact_reader=self.evidence.read_verified,
                source_root=(self.foundation_root / "src").absolute(),
            )
            try:
                require_durable_replay_job_implementation_preflight(result)
            except ReplayJobImplementationPreflightError as exc:
                raise TransitionError(
                    "replay implementation needs same-identity source repair "
                    "before any durable rejection or scientific transition: "
                    f"{result.reason_code}: {result.failure_detail}"
                ) from exc
            if repair_boundary is not None and not result.accepted:
                raise TransitionError(
                    "post-Repair family recertification failed its independent "
                    f"implementation preflight: {result.reason_code}: "
                    f"{result.failure_detail}"
                )
            payload = {
                **result.to_record_payload(),
                "batch_id": batch_id,
                "scientific_surface": scientific_surface,
                "scientific_surface_hash": scientific_surface_hash,
                "study_id": study_id,
                **(
                    {}
                    if repair_boundary is None
                    else {
                        "repair_close_record_id": (
                            repair_boundary.trigger_repair_close_record_id
                        )
                    }
                ),
            }
            fingerprint = _digest(
                payload,
                domain="replay-job-implementation-preflight",
            )
            preflight_id = f"job-implementation-preflight:{fingerprint}"
            if repair_boundary is not None:
                stream = repair_module.repair_preflight_stream(
                    repair_boundary.trigger_repair_close_record_id
                )
            else:
                stream = (
                    f"replay-job-implementation-preflight-replacement:{replacement}"
                    if replacement is not None
                    else f"replay-job-implementation-preflight-batch:{batch_id}"
                )
            head = index.event_head(stream)
            if repair_boundary is not None and head is not None:
                raise RecoveryRequired(
                    "post-Repair implementation preflight stream is not atomic"
                )
            record = _record(
                kind="job-implementation-preflight",
                record_id=preflight_id,
                subject=(
                    f"Batch:{batch_id}"
                    if isinstance(batch_id, str)
                    else f"Mission:{mission_id}"
                ),
                status=result.status,
                fingerprint=fingerprint,
                payload=payload,
                event_stream=stream,
                event_sequence=1 if head is None else head.sequence + 1,
            )
            admission_record: IndexRecord | None = None
            if result.accepted and registration_inspection is not None:
                if (
                    not isinstance(batch_id, str)
                    or not isinstance(study_id, str)
                    or protocol_activation is None
                ):
                    raise RecoveryRequired(
                        "legacy replay recertification lost its Study, Batch, or protocol"
                    )
                admission_payload = {
                    "accepted_replacement_preflight_id": (
                        None
                        if required_replacement_preflight is None
                        else required_replacement_preflight.record_id
                    ),
                    "authority_manifest_digest": current.get(
                        "authority", {}
                    ).get("manifest_digest"),
                    "batch_id": batch_id,
                    "recertification_preflight_id": preflight_id,
                    "registered_prefix_executable_ids": list(
                        registration_inspection.registered_executable_ids
                    ),
                    "research_protocol_activation_id": (
                        protocol_activation.record_id
                    ),
                    "request": request.to_identity_payload(),
                    "schema": "replay_implementation_admission.v2",
                    "scientific_surface": scientific_surface,
                    "scientific_surface_hash": scientific_surface_hash,
                    "source_closure_authority": dict(
                        result.source_closure_authority or {}
                    ),
                    "study_id": study_id,
                }
                admission_stream = (
                    "replay-implementation-admission-study:" + study_id
                )
                admission_sequence = 1
                if repair_boundary is not None:
                    repair_schema = (
                        repair_module.REPAIR_RECERTIFICATION_ADMISSION_SCHEMA
                    )
                    admission_payload.update(
                        {
                            "predecessor_admission_id": (
                                repair_boundary.predecessor_admission_id
                            ),
                            "repair_close_record_ids": list(
                                repair_boundary.repair_close_record_ids
                            ),
                            "repair_executable_id": (
                                repair_boundary.repair_executable_id
                            ),
                            "repair_job_id": repair_boundary.repair_job_id,
                            "schema": repair_schema,
                            "trigger_repair_close_record_id": (
                                repair_boundary.trigger_repair_close_record_id
                            ),
                        }
                    )
                    admission_stream = (
                        repair_module.repair_admission_stream(study_id)
                    )
                    admission_sequence = (
                        repair_boundary.admission_event_sequence
                    )
                admission_fingerprint = _digest(
                    admission_payload,
                    domain="replay-implementation-admission",
                )
                admission_record = _record(
                    kind="replay-implementation-admission",
                    record_id=(
                        "replay-implementation-admission:"
                        + admission_fingerprint
                    ),
                    subject=f"Study:{study_id}",
                    status="active",
                    fingerprint=admission_fingerprint,
                    payload=admission_payload,
                    event_stream=admission_stream,
                    event_sequence=admission_sequence,
                )
            body = self._body(current)
            if (
                repair_boundary is None
                and not result.accepted
                and isinstance(batch_id, str)
            ):
                body["next_action"] = {
                    "basis_record_id": preflight_id,
                    "kind": "dispose_batch",
                    "batch_id": batch_id,
                }
            return body, [
                record,
                *([] if admission_record is None else [admission_record]),
            ], {
                "admission_id": (
                    None
                    if admission_record is None
                    else admission_record.record_id
                ),
                "preflight_id": preflight_id,
                "reason_code": result.reason_code,
                "status": result.status,
            }

        return self._commit(
            event_kind=(
                "replay_implementation_repair_recertified"
                if repair_close_record_id is not None
                else "replay_job_implementation_preflight_recorded"
            ),
            operation_id=operation_id,
            subject=f"Mission:{request.mission_id}",
            payload={
                "request_identity": request.identity,
                **(
                    {}
                    if repair_close_record_id is None
                    else {"repair_close_record_id": repair_close_record_id}
                ),
            },
            prepare=prepare,
        )

    def declare_job(
        self, *, spec: Mapping[str, Any], operation_id: str
    ) -> TransitionResult:
        self._require_study_close_delivery_guard()
        spec = self._normalize_job_spec(spec)
        self._validate_job_spec(spec)
        external_binding = spec.get("external_dependency_binding")
        if isinstance(external_binding, dict):
            try:
                self.evidence.verify(external_binding["validation_plan_hash"])
            except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
                raise TransitionError(
                    "external validation plan evidence is absent or corrupt"
                ) from exc
        self._preflight_scientific_binding(spec)
        work_basis = {
            "callable_identity": spec["callable_identity"],
            "component_parity_binding": spec.get("component_parity_binding"),
            "evidence_subject": spec["evidence_subject"],
            "external_dependency_binding": spec.get(
                "external_dependency_binding"
            ),
            "input_hashes": spec["input_hashes"],
            "holdout_binding": spec.get("holdout_binding"),
            "runtime_binding": spec.get("runtime_binding"),
            "scientific_binding": spec.get("scientific_binding"),
            "source_binding": spec.get("source_binding"),
        }
        retry_validation_capability: _JobRetryValidationCapability | None = (
            None
        )

        def prepare(current: dict[str, Any] | None, _index: LocalIndex):
            if current is None:
                raise TransitionError("control is absent")
            prevalidated_retry_authorities: (
                Mapping[str, JobRetryValidationAuthority] | None
            ) = None
            if retry_validation_capability is not None:
                if (
                    retry_validation_capability.token
                    is not _JOB_RETRY_VALIDATION_CAPABILITY_TOKEN
                    or retry_validation_capability.control_hash
                    != current.get("control_hash")
                ):
                    raise TransitionError(
                        "Job retry validation capability is stale"
                    )
                prevalidated_retry_authorities = (
                    retry_validation_capability.authorities
                )
            body = self._body(current)
            science = body["scientific"]
            return_next_action = _copy(body["next_action"])
            if science["active_mission"] is None:
                raise TransitionError("Job requires an active Mission")
            if science["active_job"] is not None:
                raise TransitionError("another parent Job is active")
            active_batch = science.get("active_batch")
            if isinstance(active_batch, dict):
                batch_record = _index.get("batch-open", active_batch["id"])
                if batch_record is None:
                    raise RecoveryRequired(
                        "active Batch declaration is unavailable at Job declaration"
                    )
                _require_concurrent_family_registration(
                    _index,
                    batch_record=batch_record,
                    evidence_subject=spec["evidence_subject"],
                )
            external_binding = spec.get("external_dependency_binding")
            external_plan: ExternalRecoveryPlan | None = None
            external_plan_records: list[IndexRecord] = []
            if isinstance(external_binding, dict):
                try:
                    external_plan = external_plan_from_binding(external_binding)
                except ExternalDependencyContractError as exc:
                    raise TransitionError(str(exc)) from exc
            scientific_binding = spec.get("scientific_binding")
            protocol_head = _index.event_head("research-protocol:scientific")
            if (
                isinstance(scientific_binding, dict)
                and protocol_head is None
                and self._authority_requires_scientific_adjudication_v2(current)
            ):
                raise TransitionError(
                    "authority requires an active v2 scientific protocol"
                )
            if isinstance(scientific_binding, dict) and protocol_head is not None:
                protocol = _index.get(
                    protocol_head.record_kind, protocol_head.record_id
                )
                if (
                    protocol is None
                    or protocol.kind != "research-protocol-activation"
                    or protocol.status != "active"
                    or protocol.event_sequence != protocol_head.sequence
                    or protocol.payload.get("protocol")
                    != "scientific_adjudication_v2"
                    or protocol.payload.get("authority_manifest_digest")
                    != current.get("authority", {}).get("manifest_digest")
                ):
                    raise RecoveryRequired(
                        "active scientific protocol projection is invalid"
                    )
                if (
                    scientific_binding.get("validator_id")
                    != protocol.payload.get("validator_id")
                ):
                    raise TransitionError(
                        "prospective scientific Job must use the active v2 protocol"
                    )
            try:
                external_plan_records.extend(
                    require_job_admission(
                        engineering_fixture=self.engineering_fixture,
                        current=current,
                        science=science,
                        spec=spec,
                        external_binding=external_binding,
                        external_plan=external_plan,
                        index=_index,
                        record_builder=_record,
                        active_decision_loader=self._active_portfolio_decision,
                    )
                )
            except JobAdmissionAuthorityError as exc:
                raise TransitionError(str(exc)) from exc
            mission_id = science["active_mission"]
            scientific_lineage_material_identity: str | None = None
            lineage_study_id: str | None = None
            lineage_study: IndexRecord | None = None
            if (
                isinstance(scientific_binding, dict)
                and not self.engineering_fixture
            ):
                lineage_study_id = science["active_study"]
                if not isinstance(lineage_study_id, str):
                    evidence_subject = spec["evidence_subject"]
                    trial = (
                        _index.get("trial", evidence_subject["id"])
                        if evidence_subject["kind"] == "Executable"
                        else None
                    )
                    lineage_study_id = (
                        None if trial is None else trial.payload.get("study_id")
                    )
                lineage_study = (
                    None
                    if not isinstance(lineage_study_id, str)
                    else _index.get("study-open", lineage_study_id)
                )
                declared_modes = set(scientific_binding["evidence_modes"])
                if (
                    lineage_study is None
                    or lineage_study.payload.get("mission_id") != mission_id
                    or not declared_modes.issubset(
                        _require_study_evidence_modes(
                            lineage_study.payload.get("question", {})
                        )
                    )
                ):
                    raise TransitionError(
                        "scientific Job evidence modes exceed its Study preregistration"
                    )
                scientific_lineage_material_identity = _require_digest(
                    "scientific Job lineage material",
                    lineage_study.payload.get("material_identity"),
                )
            implementation_manifest = self._require_job_implementation_evidence(
                spec,
                _index=_index,
            )
            replay_admission = (
                None
                if not isinstance(lineage_study_id, str)
                else self._study_replay_implementation_admission(
                    _index,
                    study_id=lineage_study_id,
                    authority_manifest_digest=current.get(
                        "authority", {}
                    ).get("manifest_digest"),
                )
            )
            if (
                lineage_study is not None
                and lineage_study.payload.get("replay_obligation_ids")
                and replay_admission is None
            ):
                raise RecoveryRequired(
                    "replay Job declaration requires a current implementation admission"
                )
            if replay_admission is not None:
                admitted_request = replay_admission.payload.get("request")
                manifests = (
                    None
                    if not isinstance(admitted_request, Mapping)
                    else admitted_request.get("executable_manifests")
                )
                bindings = (
                    None
                    if not isinstance(admitted_request, Mapping)
                    else admitted_request.get("scientific_bindings")
                )
                subject_id = spec["evidence_subject"]["id"]
                subject_trial = _index.get("trial", subject_id)
                subject_manifest = (
                    None
                    if subject_trial is None
                    else subject_trial.payload.get("executable")
                )
                try:
                    member_index = (
                        manifests.index(subject_manifest)
                        if isinstance(manifests, list)
                        else -1
                    )
                except ValueError:
                    member_index = -1
                admitted_binding = (
                    bindings[member_index]
                    if isinstance(bindings, list)
                    and 0 <= member_index < len(bindings)
                    else None
                )
                if (
                    not isinstance(admitted_request, Mapping)
                    or member_index < 0
                    or spec["callable_identity"]
                    != admitted_request.get("callable_identity")
                    or spec["implementation_identity"]
                    != admitted_request.get("implementation_identity")
                    or scientific_binding != admitted_binding
                    or implementation_manifest.get("protocol")
                    != admitted_request.get("protocol_id")
                ):
                    raise TransitionError(
                        "Job differs from the replay implementation admission"
                    )
            component_implementation_hashes: tuple[str, ...] = ()
            source_closure_authority: dict[str, Any] | None = None
            external_observed_development_binding_payload: (
                dict[str, Any] | None
            ) = None
            if _job_requires_current_source_authority(
                engineering_fixture=self.engineering_fixture,
                evidence_subject_kind=spec["evidence_subject"]["kind"],
            ):
                from axiom_rift.research.implementation_closure import (
                    ImplementationClosureError,
                    require_current_job_source_closure,
                    require_job_implementation_closure,
                )

                executable_manifest: dict[str, Any] | None = None
                try:
                    if spec["evidence_subject"]["kind"] == "Executable":
                        subject_trial = _index.get(
                            "trial", spec["evidence_subject"]["id"]
                        )
                        executable_manifest = (
                            None
                            if subject_trial is None
                            else subject_trial.payload.get("executable")
                        )
                        if not isinstance(executable_manifest, dict):
                            raise TransitionError(
                                "Executable Job subject lacks its exact trial manifest"
                            )
                        component_implementation_hashes = (
                            require_job_implementation_closure(
                                executable_manifest=executable_manifest,
                                job_artifact_hashes=implementation_manifest[
                                    "artifact_hashes"
                                ],
                                artifact_reader=self.evidence.read_verified,
                            )
                        )
                    source_closure_hashes = (
                        _job_implementation_source_closure_hashes(
                            implementation_manifest=implementation_manifest,
                            artifact_reader=self.evidence.read_verified,
                        )
                    )
                    if source_closure_hashes:
                        source_closure_authority = (
                            require_current_job_source_closure(
                                callable_identity=spec["callable_identity"],
                                job_artifact_hashes=implementation_manifest[
                                    "artifact_hashes"
                                ],
                                artifact_reader=self.evidence.read_verified,
                                source_root=self.foundation_root / "src",
                                verified_non_source_artifact_hashes=(
                                    component_implementation_hashes
                                ),
                            )
                        )
                        if executable_manifest is not None:
                            closure_payload = parse_canonical(
                                self.evidence.read_verified(
                                    source_closure_hashes[0]
                                )
                            )
                            if not isinstance(closure_payload, Mapping):
                                raise ImplementationClosureError(
                                    "Job source closure payload is malformed"
                                )
                            external_binding_value = (
                                external_observed_development_job_binding(
                                    executable_id=spec["evidence_subject"][
                                        "id"
                                    ],
                                    executable_manifest=executable_manifest,
                                    job_spec=spec,
                                    source_closure_dependencies=(
                                        closure_payload["dependencies"]
                                    ),
                                )
                            )
                            if external_binding_value is not None:
                                verify_external_observed_development_job_prefixes(
                                    repository_root=self.foundation_root,
                                    binding=external_binding_value,
                                )
                                external_observed_development_binding_payload = (
                                    external_binding_value.to_payload()
                                )
                    else:
                        raise TransitionError(
                            "prospective production Job requires one exact "
                            "current source closure; historical implementation "
                            "exemptions are read-only evidence, not execution authority"
                        )
                except (
                    ExternalObservedDevelopmentJobBindingError,
                    ImplementationClosureError,
                ) as exc:
                    raise TransitionError(str(exc)) from exc
            candidate_execution_context: dict[str, Any] | None = None
            active_executable = science.get("active_executable")
            if (
                isinstance(active_executable, str)
                and spec["evidence_subject"]
                == {"kind": "Executable", "id": active_executable}
            ):
                candidate_head = _index.event_head(
                    f"candidate:{active_executable}"
                )
                candidate = (
                    None
                    if candidate_head is None
                    else _index.get(
                        candidate_head.record_kind,
                        candidate_head.record_id,
                    )
                )
                expected_candidate = (
                    ("engineering-executable-fixture", "bound_fixture")
                    if self.engineering_fixture
                    else ("candidate", "frozen")
                )
                if candidate is None or (
                    candidate.kind,
                    candidate.status,
                ) != expected_candidate:
                    raise TransitionError(
                        "candidate Job lacks its current frozen activation"
                    )
                executable_payload = candidate.payload.get("executable")
                candidate_source_bindings = candidate.payload.get(
                    "source_bindings"
                )
                candidate_source_ids = (
                    None
                    if not isinstance(executable_payload, Mapping)
                    else executable_payload.get("source_contracts")
                )
                if (
                    not isinstance(candidate_source_ids, list)
                    or any(type(source_id) is not str for source_id in candidate_source_ids)
                    or candidate_source_ids != sorted(set(candidate_source_ids))
                    or not isinstance(candidate_source_bindings, list)
                    or any(
                        not isinstance(binding, Mapping)
                        or binding.get("source_contract_id") not in candidate_source_ids
                        for binding in candidate_source_bindings
                    )
                    or sorted(
                        binding["source_contract_id"]
                        for binding in candidate_source_bindings
                    )
                    != candidate_source_ids
                ):
                    raise RecoveryRequired(
                        "candidate source bindings are malformed"
                    )
                candidate_source_job = spec.get("source_binding")
                if isinstance(candidate_source_job, Mapping):
                    target_source_id = candidate_source_job.get(
                        "source_contract_id"
                    )
                    if target_source_id not in candidate_source_ids:
                        raise TransitionError(
                            "candidate source Job must target one of its frozen SourceContracts"
                        )
                    if _index.event_head(
                        f"source-authority:{target_source_id}"
                    ) is not None:
                        raise TransitionError(
                            "audit-invalidated candidate source requires a new SourceContract identity"
                        )
                    source_state_record_ids: list[str] = []
                    for source_id in candidate_source_ids:
                        source_head = _index.event_head(f"source:{source_id}")
                        source_state = (
                            None
                            if source_head is None
                            else _index.get(
                                source_head.record_kind,
                                source_head.record_id,
                            )
                        )
                        if (
                            source_state is None
                            or source_state.kind != "source-state"
                            or source_state.subject != f"Source:{source_id}"
                            or source_state.event_sequence
                            != source_head.sequence
                        ):
                            raise RecoveryRequired(
                                "candidate source Job lacks its exact current source state"
                            )
                        source_state_record_ids.append(
                            source_state.record_id
                        )
                    candidate_execution_context = {
                        "candidate_activation_id": candidate.record_id,
                        "executable_id": active_executable,
                        "schema": "candidate_source_job_execution_context.v1",
                        "source_state_record_ids": sorted(
                            source_state_record_ids
                        ),
                        "target_source_contract_id": target_source_id,
                    }
                else:
                    try:
                        source_snapshot = current_runtime_source_snapshot(
                            index=_index,
                            source_contract_ids=tuple(candidate_source_ids),
                            require_runtime_source=self._require_runtime_source,
                        )
                        candidate_execution_context = (
                            candidate_job_execution_context(
                                index=_index,
                                candidate=candidate,
                                current=source_snapshot,
                                runtime_binding=(
                                    spec.get("runtime_binding")
                                    if isinstance(
                                        spec.get("runtime_binding"), Mapping
                                    )
                                    else None
                                ),
                            )
                        )
                    except RuntimeSuccessAuthorityError as exc:
                        raise TransitionError(str(exc)) from exc
            try:
                observed_binding_value = scientific_observed_development_job_binding(
                    foundation_root=self.foundation_root,
                    input_hashes=spec["input_hashes"],
                    lineage_material_identity=(
                        scientific_lineage_material_identity
                    ),
                )
            except ObservedDevelopmentBindingError as exc:
                raise TransitionError(str(exc)) from exc
            observed_development_binding = (
                None
                if observed_binding_value is None
                else observed_binding_value.to_payload()
            )
            implementation_source_authority = (
                None
                if source_closure_authority is None
                else {
                    "authority": source_closure_authority,
                    "schema": "job_implementation_source_binding.v1",
                }
            )
            identity_plan = build_job_identity_plan(
                spec=spec,
                work_basis=work_basis,
                mission_id=mission_id,
                candidate_execution_context=candidate_execution_context,
                observed_development_binding=observed_development_binding,
                implementation_source_authority=implementation_source_authority,
                external_observed_development_binding=(
                    external_observed_development_binding_payload
                ),
            )
            bound_work_basis = dict(identity_plan.bound_work_basis)
            job_hash = identity_plan.job_hash
            job_id = identity_plan.job_id
            work_fingerprint = identity_plan.work_fingerprint
            success_fingerprint = identity_plan.success_fingerprint
            cached_success = _index.get("job-success-cache", success_fingerprint)
            if cached_success is not None:
                completion_id = cached_success.payload.get("completion_record_id")
                completion = (
                    None
                    if not isinstance(completion_id, str)
                    else _index.get("job-completed", completion_id)
                )
                if completion is None:
                    raise RecoveryRequired("successful Job cache is inconsistent")
                try:
                    require_cached_success_binding(
                        cached_payload=cached_success.payload,
                        completion_status=completion.status,
                        completion_payload=completion.payload,
                        spec=spec,
                        mission_id=mission_id,
                        candidate_execution_context=candidate_execution_context,
                        observed_development_binding=observed_development_binding,
                        implementation_source_authority=(
                            implementation_source_authority
                        ),
                        external_observed_development_binding=(
                            external_observed_development_binding_payload
                        ),
                    )
                except JobCacheAuthorityError as exc:
                    raise RecoveryRequired(str(exc)) from exc
                if observed_binding_value is not None:
                    try:
                        verify_observed_development_prefix_artifact(
                            foundation_root=self.foundation_root,
                            binding=observed_binding_value,
                        )
                    except ObservedDevelopmentBindingError as exc:
                        raise RecoveryRequired(
                            "observed development cache source bytes are unavailable "
                            "or inconsistent"
                        ) from exc
                self._require_reusable_success_outputs(
                    completion=completion, spec=spec
                )
                return body, [], {
                    "disposition": "reuse_success",
                    "completion_record_id": completion.record_id,
                    "job_id": completion.payload["job_id"],
                }
            try:
                retry_admission = prepare_job_retry_admission(
                    index=_index,
                    mission_id=mission_id,
                    initiative_id=science.get("active_initiative"),
                    study_id=science.get("active_study"),
                    batch_id=(
                        active_batch.get("id")
                        if isinstance(active_batch, Mapping)
                        else None
                    ),
                    spec=spec,
                    candidate_execution_context=candidate_execution_context,
                    implementation_manifest=implementation_manifest,
                    current_job_id=job_id,
                    current_job_hash=job_hash,
                    work_fingerprint=work_fingerprint,
                    read_evidence=self.evidence.read_verified,
                    verify_evidence=self.evidence.verify,
                    evidence_path=self.evidence.verified_path,
                    validation_registry=self.validation_registry,
                    engineering_fixture=self.engineering_fixture,
                    prevalidated_authorities=(
                        prevalidated_retry_authorities
                    ),
                    defer_validation=True,
                )
            except JobRetryValidationDispatchRequired as exc:
                raise _JobRetryValidationOutsideLock(
                    control_hash=str(current["control_hash"]),
                    requirement=exc,
                ) from exc
            except JobRetryAdmissionSpecificationError as exc:
                raise TransitionError(str(exc)) from exc
            except JobRetryAdmissionIntegrityError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except JobRetryAdmissionRejected as exc:
                raise IdenticalFailedRetryError(str(exc)) from exc
            retry_family = retry_admission.family
            retry_basis_records = list(retry_admission.basis_records)
            attempt_head = _index.event_head(
                f"job-attempt:{work_fingerprint}"
            )
            evidence_subject = spec["evidence_subject"]
            active_by_kind = {
                "Mission": science["active_mission"],
                "Initiative": science["active_initiative"],
                "Study": science["active_study"],
                "Executable": science["active_executable"],
            }
            if evidence_subject["kind"] == "Executable":
                subject_exists = (
                    _index.get("trial", evidence_subject["id"]) is not None
                    or _index.get("engineering-evaluation-fixture", evidence_subject["id"])
                    is not None
                    or active_by_kind["Executable"] == evidence_subject["id"]
                )
            elif evidence_subject["kind"] == "Release":
                subject_exists = (
                    _index.get("release-declared", evidence_subject["id"]) is not None
                )
            else:
                subject_exists = active_by_kind[evidence_subject["kind"]] == evidence_subject["id"]
            if not subject_exists:
                raise TransitionError("Job evidence subject is not active or registered")
            reservation_records: list[IndexRecord] = []
            batch = science["active_batch"]
            if isinstance(batch, dict):
                batch_record = _index.get("batch-open", batch["id"])
                if batch_record is None:
                    raise TransitionError("active Batch declaration is unavailable")
                budget_head = _index.event_head(f"batch-budget:{batch['id']}")
                previous_budget = (
                    {"compute_seconds": 0, "wall_seconds": 0}
                    if budget_head is None
                    else _index.get(budget_head.record_kind, budget_head.record_id).payload
                )
                next_compute = previous_budget["compute_seconds"] + spec["budget"]["compute_seconds"]
                next_wall = previous_budget["wall_seconds"] + spec["budget"]["wall_seconds"]
                frozen_spec = batch_record.payload["spec"]
                if (
                    next_compute > frozen_spec["max_compute_seconds"]
                    or next_wall > frozen_spec["max_wall_seconds"]
                ):
                    raise TransitionError("Job exceeds the frozen Batch compute or wall budget")
                reservation_id = canonical_digest(
                    domain="batch-budget-reservation",
                    payload={"batch_id": batch["id"], "job_id": job_id},
                )
                reservation_records.append(
                    _record(
                        kind="batch-budget-reservation",
                        record_id=reservation_id,
                        subject=f"Batch:{batch['id']}",
                        status="reserved",
                        fingerprint=job_hash,
                        payload={
                            "compute_seconds": next_compute,
                            "wall_seconds": next_wall,
                            "job_id": job_id,
                        },
                        event_stream=f"batch-budget:{batch['id']}",
                        event_sequence=1 if budget_head is None else budget_head.sequence + 1,
                    )
                )
            try:
                retry_family_record = build_retry_family_declaration_record(
                    admission=retry_admission,
                    job_id=job_id,
                    job_hash=job_hash,
                    work_fingerprint=work_fingerprint,
                )
            except JobRetryAdmissionSpecificationError as exc:
                raise TransitionError(str(exc)) from exc
            science["active_job"] = {
                "id": job_id,
                "hash": job_hash,
                "return_next_action": return_next_action,
                "status": "declared",
                "resume_action": spec["resume_action"],
            }
            body["next_action"] = {"kind": "issue_job_permit", "job_id": job_id}
            authorization = self._authorization(
                kind=SubjectKind.JOB, subject_id=job_id, semantic_hash=job_hash
            )
            self._bind_authorization(body, authorization)
            record = _record(
                kind="job-declared",
                record_id=job_id,
                subject=f"Job:{job_id}",
                status="declared",
                fingerprint=job_hash,
                payload={
                    "spec": dict(spec),
                    "mission_id": science["active_mission"],
                    "initiative_id": science["active_initiative"],
                    "study_id": science["active_study"],
                    "batch_id": None if not isinstance(batch, dict) else batch["id"],
                    "candidate_execution_context": (
                        candidate_execution_context
                    ),
                    **(
                        {
                            "observed_development_binding": (
                                observed_development_binding
                            )
                        }
                        if observed_development_binding is not None
                        else {}
                    ),
                    **(
                        {
                            "external_observed_development_binding": (
                                external_observed_development_binding_payload
                            )
                        }
                        if external_observed_development_binding_payload
                        is not None
                        else {}
                    ),
                    "return_next_action": return_next_action,
                    "retry_family": retry_family.payload(),
                    "retry_family_fingerprint": retry_family.fingerprint,
                    "retry_basis_record_ids": sorted(
                        record.record_id for record in retry_basis_records
                    ),
                    "success_fingerprint": success_fingerprint,
                    "work_fingerprint": work_fingerprint,
                    **(
                        {
                            "component_implementation_hashes": list(
                                component_implementation_hashes
                            )
                        }
                        if component_implementation_hashes
                        else {}
                    ),
                    **(
                        {
                            "source_closure_authority": (
                                source_closure_authority
                            )
                        }
                        if source_closure_authority is not None
                        else {}
                    ),
                },
                event_stream=f"job-attempt:{work_fingerprint}",
                event_sequence=(
                    1 if attempt_head is None else attempt_head.sequence + 1
                ),
            )
            return body, [
                *external_plan_records,
                *retry_basis_records,
                *reservation_records,
                record,
                retry_family_record,
            ], {
                "job_id": job_id,
                "job_hash": job_hash,
            }

        while True:
            try:
                return self._commit(
                    event_kind="job_declared",
                    operation_id=operation_id,
                    subject=(
                        f"{spec['evidence_subject']['kind']}:"
                        f"{spec['evidence_subject']['id']}"
                    ),
                    payload={
                        "job_spec_hash": _digest(
                            dict(spec), domain="job-spec"
                        )
                    },
                    prepare=prepare,
                    read_only_when_unchanged=True,
                )
            except _JobRetryValidationOutsideLock as dispatch:
                if (
                    retry_validation_capability is not None
                    and retry_validation_capability.control_hash
                    != dispatch.control_hash
                ):
                    raise TransitionError(
                        "Job retry head changed between validation dispatches"
                    ) from dispatch
                arguments = dict(dispatch.requirement.arguments)
                receipt_hash = arguments.get("receipt_hash")
                result_hashes = arguments.get("result_artifact_hashes")
                if type(receipt_hash) is not str or not isinstance(
                    result_hashes, list
                ):
                    raise TransitionError(
                        "Job retry validation dispatch is malformed"
                    ) from dispatch
                arguments["result_artifact_hashes"] = tuple(result_hashes)
                try:
                    authority = validate_engineering_retry_evidence(
                        **arguments,
                        validation_registry=self.validation_registry,
                        evidence_path=self.evidence.verified_path,
                    )
                except JobRetryFamilyError as exc:
                    raise IdenticalFailedRetryError(str(exc)) from exc
                authorities = (
                    {}
                    if retry_validation_capability is None
                    else dict(retry_validation_capability.authorities)
                )
                if receipt_hash in authorities:
                    raise TransitionError(
                        "Job retry validator requested a duplicate dispatch"
                    )
                authorities[receipt_hash] = authority
                retry_validation_capability = _JobRetryValidationCapability(
                    token=_JOB_RETRY_VALIDATION_CAPABILITY_TOKEN,
                    control_hash=dispatch.control_hash,
                    authorities=authorities,
                )
