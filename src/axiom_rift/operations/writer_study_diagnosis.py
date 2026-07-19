"""Study diagnosis, additive correction, and architecture-review transitions.

The StateWriter facade remains the sole atomic commit owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.writer_support import (
    RecoveryRequired,
    TransitionError,
    TransitionResult,
    _record,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class StudyDiagnosisWriterMixin:
    """Own diagnosis and architecture review; the facade commits atomically."""

    def record_study_diagnosis(
        self,
        *,
        diagnosis: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.governance import (
            EvidenceState,
            ResearchLayer,
            StudyDiagnosis,
            diagnosis_branch,
        )

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures do not create Study diagnosis")
        if not isinstance(diagnosis, StudyDiagnosis):
            raise TransitionError("diagnosis must be a StudyDiagnosis")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("Study diagnosis requires an active Mission")
            science = current["scientific"]
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("Study diagnosis cannot bypass active work")
            next_action = current["next_action"]
            if next_action != {
                "kind": "diagnose_study",
                "study_id": diagnosis.study_id,
                "study_close_record_id": diagnosis.study_close_record_id,
                "portfolio_snapshot_id": next_action.get("portfolio_snapshot_id"),
            }:
                raise TransitionError("Study diagnosis is not the exact next action")
            close_record = index.get(
                "study-close", diagnosis.study_close_record_id
            )
            study = index.get("study-open", diagnosis.study_id)
            if (
                close_record is None
                or close_record.subject != f"Study:{diagnosis.study_id}"
                or study is None
                or study.payload.get("mission_id") != science["active_mission"]
                or close_record.payload.get("portfolio_axis_identity")
                != study.payload.get("portfolio_axis_identity")
            ):
                raise TransitionError("Study diagnosis subject is unavailable or stale")
            outcome = close_record.status
            claim_scoped = self._study_claim_scoped_diagnosis(
                index,
                study_id=diagnosis.study_id,
            )
            supported_states = {EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION}
            unavailable_states = {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.NOT_IDENTIFIABLE,
            }
            negative_states = set(EvidenceState) - supported_states - {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.NOT_IDENTIFIABLE,
            }
            allowed_states = (
                (
                    {claim_scoped.evidence_state}
                    if claim_scoped is not None
                    else supported_states
                )
                if outcome in {"supported", "preserved"}
                else unavailable_states
                if outcome in {"evidence_gap", "not_evaluable"}
                else negative_states
                if outcome == "not_supported"
                else negative_states | {EvidenceState.NOT_IDENTIFIABLE}
                if outcome == "pruned"
                else set()
            )
            if diagnosis.evidence_state not in allowed_states:
                raise TransitionError(
                    "Study diagnosis evidence state conflicts with its typed outcome"
                )
            if (
                claim_scoped is not None
                and diagnosis.evidence_state is not claim_scoped.evidence_state
            ):
                raise TransitionError(
                    "Study diagnosis permits unrelated-claim compensation"
                )
            if claim_scoped is not None and (
                diagnosis.diagnosis_reason_code != claim_scoped.reason_code
                or diagnosis.supported_claim_ids
                != claim_scoped.supported_claim_ids
                or diagnosis.contradicted_claim_ids
                != claim_scoped.contradicted_claim_ids
                or diagnosis.unresolved_claim_ids
                != claim_scoped.unresolved_claim_ids
                or diagnosis.diagnostic_criterion_ids
                != claim_scoped.diagnostic_criterion_ids
            ):
                raise TransitionError(
                    "Study diagnosis claim inventory differs from durable evidence"
                )
            from axiom_rift.operations.study_diagnosis_admission import (
                StudyDiagnosisAdmissionError,
                require_primary_control_consistency,
            )

            try:
                require_primary_control_consistency(
                    diagnosis,
                    claim_scoped=claim_scoped,
                )
            except StudyDiagnosisAdmissionError as exc:
                raise TransitionError(str(exc)) from exc
            kpi = index.get("study-kpi", diagnosis.study_id)
            unavailable_reason = (
                None if kpi is None else kpi.payload.get("unavailable_reason")
            )
            engineering_basis = (
                unavailable_reason
                in {
                    "engineering_failure",
                    "started_batch_implementation_authority_invalid_"
                    "without_final_validator_completion",
                    "unstarted_batch_implementation_authority_invalid_"
                    "without_final_validator_completion",
                }
            )
            if (
                diagnosis.evidence_state == EvidenceState.ENGINEERING_GAP
            ) != engineering_basis:
                raise TransitionError(
                    "engineering diagnosis must match the writer-derived Batch basis"
                )
            try:
                primary_layer = ResearchLayer(
                    study.payload["primary_research_layer"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise TransitionError(
                    "Study diagnosis lacks a typed primary research layer"
                ) from exc
            raw_changed_layers = study.payload.get("changed_domains", [])
            try:
                changed_layers = tuple(
                    ResearchLayer(value) for value in raw_changed_layers
                )
            except (TypeError, ValueError) as exc:
                raise TransitionError(
                    "Study diagnosis lacks typed changed research layers"
                ) from exc
            architecture = self._study_resolved_architecture_family(
                index=index,
                study=study,
            )
            allowed_actions, allowed_layers = diagnosis_branch(
                diagnosis.evidence_state,
                primary_layer=primary_layer,
                changed_layers=changed_layers,
                reason_code=diagnosis.diagnosis_reason_code,
            )
            evidence_basis = self._study_diagnosis_evidence_basis(
                index,
                study_id=diagnosis.study_id,
                close_record=close_record,
            )
            payload = {
                **diagnosis.to_identity_payload(),
                "allowed_actions": list(allowed_actions),
                "allowed_research_layers": list(allowed_layers),
                "claim_scoped_diagnosis": (
                    None if claim_scoped is None else claim_scoped.to_payload()
                ),
                "evidence_basis": evidence_basis,
                "mission_id": science["active_mission"],
                "portfolio_axis_id": study.payload.get("portfolio_axis_id"),
                "portfolio_axis_identity": study.payload.get(
                    "portfolio_axis_identity"
                ),
                "portfolio_snapshot_id": study.payload.get(
                    "portfolio_snapshot_id"
                ),
                "primary_research_layer": primary_layer.value,
                "study_outcome": outcome,
                "system_architecture_family": architecture,
            }
            current_is_reviewable = diagnosis.evidence_state not in {
                EvidenceState.ENGINEERING_GAP,
                EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION,
            }
            diagnosis_sequence_head = index.event_head(
                f"study-diagnosis:{science['active_mission']}"
            )
            diagnosis_sequence = (
                1
                if diagnosis_sequence_head is None
                else diagnosis_sequence_head.sequence + 1
            )
            diagnosis_record = _record(
                kind="study-diagnosis",
                record_id=diagnosis.identity,
                subject=f"Study:{diagnosis.study_id}",
                status=diagnosis.evidence_state.value,
                fingerprint=diagnosis.identity.removeprefix("diagnosis:"),
                payload=payload,
                event_stream=f"study-diagnosis:{science['active_mission']}",
                event_sequence=diagnosis_sequence,
            )
            snapshot_id = study.payload.get("portfolio_snapshot_id")
            trigger_record: IndexRecord | None = None
            if current_is_reviewable:
                trigger_record = self._pending_architecture_review_trigger(
                    index=index,
                    mission_id=science["active_mission"],
                    portfolio_snapshot_id=snapshot_id,
                    architecture_family=architecture,
                    pending_diagnoses=(diagnosis_record,),
                )
            body = self._body(current)
            if trigger_record is None:
                body["next_action"] = {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot_id,
                    "study_diagnosis_id": diagnosis.identity,
                }
                records = [diagnosis_record]
            else:
                body["next_action"] = {
                    "kind": "review_architecture",
                    "trigger_record_id": trigger_record.record_id,
                }
                records = [diagnosis_record, trigger_record]
            from axiom_rift.operations.replay_projection import (
                ReplayProjectionError,
                ReplayTransitionError,
                require_diagnosed_replay,
            )

            try:
                replay_obligation_ids = require_diagnosed_replay(
                    index,
                    mission_id=science["active_mission"],
                    study=study,
                    diagnosis_id=diagnosis.identity,
                    diagnosis_record=diagnosis_record,
                )
            except ReplayProjectionError as exc:
                raise RecoveryRequired(str(exc)) from exc
            except ReplayTransitionError as exc:
                raise TransitionError(str(exc)) from exc
            if replay_obligation_ids:
                body["next_action"] = {
                    "kind": "resolve_historical_replay_obligations",
                    "replay_obligation_ids": list(replay_obligation_ids),
                    "resume_next_action": body["next_action"],
                    "study_diagnosis_id": diagnosis.identity,
                    "study_id": diagnosis.study_id,
                }
            return body, records, {
                "architecture_review_trigger_id": (
                    None if trigger_record is None else trigger_record.record_id
                ),
                "study_diagnosis_id": diagnosis.identity,
            }

        return self._commit(
            event_kind="study_diagnosis_recorded",
            operation_id=operation_id,
            subject=f"Study:{diagnosis.study_id}",
            payload={"study_diagnosis_id": diagnosis.identity},
            prepare=prepare,
        )

    def record_study_diagnosis_corrections(
        self,
        *,
        audit: Any,
        operation_id: str,
    ) -> TransitionResult:
        """Additively correct every evidence-derived diagnosis mismatch.

        Original diagnosis, Study close, Job evidence, replay satisfaction,
        trials, and Decisions remain immutable.  The correction only removes
        invalid axis-level confirmation credit and supplies the effective
        claim-scoped Portfolio branch.
        """

        from axiom_rift.operations.effective_study_diagnosis import (
            EffectiveStudyDiagnosisError,
        )
        from axiom_rift.research.governance import (
            EvidenceState,
            ResearchLayer,
            diagnosis_branch,
        )
        from axiom_rift.research.portfolio import PortfolioAction
        from axiom_rift.research.replay_obligation import (
            ReplayObligationStatus,
        )
        from axiom_rift.research.study_diagnosis_correction import (
            StudyDiagnosisCorrectionAudit,
        )

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError(
                "engineering fixtures do not correct scientific history"
            )
        if not isinstance(audit, StudyDiagnosisCorrectionAudit):
            raise TransitionError(
                "diagnosis correction requires a typed audit inventory"
            )

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None:
                raise TransitionError("diagnosis correction requires control")
            science = current["scientific"]
            if science.get("active_mission") != audit.mission_id or any(
                science.get(name) is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_holdout_evaluation",
                    "active_job",
                    "active_lineage",
                    "active_release",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError(
                    "diagnosis correction requires one idle active Mission"
                )
            next_action = current.get("next_action", {})
            if next_action.get("kind") != "portfolio_decision":
                raise TransitionError(
                    "diagnosis correction requires a stable Portfolio boundary"
                )
            journal_head = current.get("heads", {}).get("journal", {})
            if (
                audit.prior_journal_sequence != journal_head.get("sequence")
                or audit.prior_journal_event_id != journal_head.get("event_id")
            ):
                raise TransitionError(
                    "diagnosis correction audit is stale for the Journal head"
                )

            from axiom_rift.operations.effective_study_diagnosis import (
                effective_study_diagnoses_for_mission,
            )

            try:
                effective_mission_diagnoses = (
                    effective_study_diagnoses_for_mission(
                        index,
                        mission_id=audit.mission_id,
                    )
                )
            except EffectiveStudyDiagnosisError as exc:
                raise RecoveryRequired(str(exc)) from exc
            mismatches: list[tuple[Any, Any]] = []
            for effective in effective_mission_diagnoses:
                original = effective.original
                study_id = original.payload.get("study_id")
                if not isinstance(study_id, str):
                    raise RecoveryRequired(
                        "Study diagnosis correction lost its Study identity"
                    )
                try:
                    pattern = self._study_claim_scoped_diagnosis(
                        index,
                        study_id=study_id,
                    )
                except TransitionError:
                    if effective.status == EvidenceState.ENGINEERING_GAP.value:
                        continue
                    raise
                if (
                    pattern is not None
                    and pattern.evidence_state.value != effective.status
                ):
                    mismatches.append((effective, pattern))
            mismatch_ids = tuple(
                sorted(
                    effective.record_id
                    for effective, _pattern in mismatches
                )
            )
            if mismatch_ids != audit.original_diagnosis_ids:
                raise TransitionError(
                    "diagnosis correction audit inventory is incomplete or stale"
                )
            prior_correction_ids = tuple(
                sorted(
                    effective.correction.record_id
                    for effective, _pattern in mismatches
                    if effective.correction is not None
                )
            )
            if prior_correction_ids != audit.prior_correction_ids:
                raise TransitionError(
                    "diagnosis correction audit prior authority is incomplete or stale"
                )

            audit_payload = audit.to_identity_payload()
            audit_digest = audit.identity.removeprefix(
                "diagnosis-correction-audit:"
            )
            audit_record = _record(
                kind="study-diagnosis-correction-audit",
                record_id=audit.identity,
                subject=f"Mission:{audit.mission_id}",
                status="complete_mismatch_inventory",
                fingerprint=audit_digest,
                payload=audit_payload,
            )

            correction_records: list[IndexRecord] = []
            corrections_by_original: dict[str, IndexRecord] = {}
            state_overrides: dict[str, str] = {}
            architecture_families: set[str] = set()
            decisions_by_diagnosis: dict[str, list[IndexRecord]] = {}
            mission_subject = f"Mission:{audit.mission_id}"
            for decision in (
                record
                for action in PortfolioAction
                for record in index.records_by_subject_status(
                    mission_subject,
                    action.value,
                )
                if record.kind == "portfolio-decision"
            ):
                diagnosis_id = decision.payload.get("study_diagnosis_id")
                if isinstance(diagnosis_id, str):
                    decisions_by_diagnosis.setdefault(
                        diagnosis_id,
                        [],
                    ).append(decision)
            satisfactions_by_diagnosis: dict[str, list[str]] = {}
            for resolution in (
                record
                for status in (
                    ReplayObligationStatus.DEFERRED,
                    ReplayObligationStatus.SATISFIED,
                )
                for record in index.records_by_subject_status(
                    mission_subject,
                    status.value,
                )
                if record.kind
                == "historical-replay-obligation-resolution"
            ):
                resolution_payload = resolution.payload.get("resolution")
                diagnosis_id = (
                    None
                    if not isinstance(resolution_payload, Mapping)
                    else resolution_payload.get("study_diagnosis_id")
                )
                if isinstance(diagnosis_id, str):
                    satisfactions_by_diagnosis.setdefault(
                        diagnosis_id,
                        [],
                    ).append(resolution.record_id)
            reviewed_diagnosis_ids: set[str] = set()
            for review in index.records_by_payload_text(
                "architecture-review",
                "mission_id",
                audit.mission_id,
            ):
                reviewed_diagnosis_ids.update(
                    value
                    for value in review.payload.get("covered_diagnosis_ids", [])
                    if isinstance(value, str)
                )
            for effective, pattern in sorted(
                mismatches,
                key=lambda item: item[0].record_id,
            ):
                original = effective.original
                stream = f"study-diagnosis-correction:{original.record_id}"
                stream_head = index.event_head(stream)
                prior_correction = effective.correction
                if (
                    (stream_head is None) != (prior_correction is None)
                    or (
                        stream_head is not None
                        and prior_correction is not None
                        and (
                            stream_head.record_kind != prior_correction.kind
                            or stream_head.record_id
                            != prior_correction.record_id
                            or stream_head.sequence
                            != prior_correction.event_sequence
                        )
                    )
                ):
                    raise RecoveryRequired(
                        "Study diagnosis correction head conflicts with effective authority"
                    )
                correction_sequence = (
                    1 if stream_head is None else stream_head.sequence + 1
                )
                study_id = original.payload["study_id"]
                study = index.get("study-open", study_id)
                if study is None:
                    raise RecoveryRequired(
                        "diagnosis correction lost its Study record"
                    )
                try:
                    primary_layer = ResearchLayer(
                        study.payload["primary_research_layer"]
                    )
                    changed_layers = tuple(
                        ResearchLayer(value)
                        for value in study.payload.get("changed_domains", [])
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RecoveryRequired(
                        "diagnosis correction Study layers are malformed"
                    ) from exc
                allowed_actions, allowed_layers = diagnosis_branch(
                    pattern.evidence_state,
                    primary_layer=primary_layer,
                    changed_layers=changed_layers,
                    reason_code=pattern.reason_code,
                )
                completions = self._study_primary_scientific_completions(
                    index,
                    study_id=study_id,
                )
                completion_basis: list[dict[str, str]] = []
                effective_scope_basis: list[dict[str, Any]] = []
                from axiom_rift.operations.evidence_scope_projection import (
                    EvidenceScopeProjectionError,
                    effective_completion_evidence_scope,
                )
                for completion in completions:
                    scientific = completion.payload.get("scientific")
                    adjudication = (
                        None
                        if not isinstance(scientific, Mapping)
                        else scientific.get("adjudication")
                    )
                    executable_id = (
                        None
                        if not isinstance(scientific, Mapping)
                        else scientific.get("executable_id")
                    )
                    if (
                        not isinstance(adjudication, Mapping)
                        or not isinstance(executable_id, str)
                    ):
                        raise RecoveryRequired(
                            "diagnosis correction completion basis is malformed"
                        )
                    completion_basis.append(
                        {
                            "adjudication_digest": canonical_digest(
                                domain="scientific-adjudication",
                                payload=dict(adjudication),
                            ),
                            "completion_record_id": completion.record_id,
                            "executable_id": executable_id,
                        }
                    )
                    try:
                        scope = effective_completion_evidence_scope(
                            index,
                            completion,
                        )
                    except EvidenceScopeProjectionError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    effective_scope_basis.append(
                        {
                            "candidate_credit": scope.candidate_credit,
                            "completion_record_id": completion.record_id,
                            "cost_semantics_latch_id": (
                                scope.cost_semantics_latch_id
                            ),
                            "economic_credit": scope.economic_credit,
                            "evidence_modes": list(scope.evidence_modes),
                            "invalidation_record_id": (
                                scope.invalidation_record_id
                            ),
                            "overlay_record_id": scope.overlay_record_id,
                            "scientific_credit": scope.scientific_credit,
                            "scientific_eligible": (
                                scope.scientific_eligible
                            ),
                            "terminal_credit": scope.terminal_credit,
                        }
                    )
                satisfaction_ids = tuple(
                    sorted(
                        satisfactions_by_diagnosis.get(original.record_id, [])
                    )
                )
                decision_qualifications: list[dict[str, str]] = []
                for decision in decisions_by_diagnosis.get(
                    original.record_id,
                    [],
                ):
                    active = self._active_portfolio_decision(
                        index,
                        decision.record_id,
                    )
                    action = decision.status
                    qualification = (
                        "withdrawn_no_effect"
                        if active is None
                        else "historical_only_no_confirmation_credit"
                        if action == "preserve"
                        else "independent_protocol_authority_preserved"
                        if action == "revise_protocol"
                        else "direction_compatible_no_inherited_positive_credit"
                        if action in allowed_actions
                        else "historical_only_requires_reassessment"
                    )
                    decision_qualifications.append(
                        {
                            "action": action,
                            "decision_id": decision.record_id,
                            "qualification": qualification,
                        }
                    )
                architecture = self._study_resolved_architecture_family(
                    index=index,
                    study=study,
                )
                architecture_families.add(architecture)
                correction_payload = {
                    "affected_completion_record_ids": sorted(
                        reference.get("record_id")
                        for reference in original.payload.get(
                            "evidence_basis", []
                        )
                        if isinstance(reference, Mapping)
                        and reference.get("kind") == "job-completed"
                        and isinstance(reference.get("record_id"), str)
                    ),
                    "allowed_actions": list(allowed_actions),
                    "allowed_research_layers": list(allowed_layers),
                    "audit_id": audit.identity,
                    "audit_protocol_id": audit.protocol_id,
                    "candidate_authority_delta": 0,
                    "claim_scoped_diagnosis": pattern.to_payload(),
                    "completion_basis": completion_basis,
                    "confirmation_credit_delta": (
                        -1
                        if effective.status
                        == EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION.value
                        and pattern.evidence_state
                        is not EvidenceState.SUPPORTED_REQUIRES_CONFIRMATION
                        else 0
                    ),
                    "decision_qualifications": decision_qualifications,
                    "effective_confidence": pattern.confidence.value,
                    "effective_completion_scope_basis": (
                        effective_scope_basis
                    ),
                    "effective_evidence_state": pattern.evidence_state.value,
                    "effective_reason_code": pattern.reason_code,
                    "evidence_basis_digest": canonical_digest(
                        domain="study-diagnosis-evidence-basis",
                        payload=original.payload.get("evidence_basis", []),
                    ),
                    "holdout_reveal_delta": 0,
                    "mission_id": audit.mission_id,
                    "original_confidence": original.payload.get("confidence"),
                    "original_diagnosis_id": original.record_id,
                    "original_diagnosis_payload_digest": canonical_digest(
                        domain="study-diagnosis-payload",
                        payload=dict(original.payload),
                    ),
                    "original_evidence_state": original.payload.get(
                        "evidence_state"
                    ),
                    "portfolio_axis_id": original.payload.get(
                        "portfolio_axis_id"
                    ),
                    "portfolio_axis_identity": original.payload.get(
                        "portfolio_axis_identity"
                    ),
                    "portfolio_snapshot_id": original.payload.get(
                        "portfolio_snapshot_id"
                    ),
                    "projection_scope": (
                        "study_primary_question_over_all_completion_references"
                    ),
                    "prior_effective_authority_record_id": (
                        effective.authority_record_id
                    ),
                    "prior_effective_evidence_state": effective.status,
                    "replay_satisfaction_delta": 0,
                    "replay_satisfaction_record_ids": list(satisfaction_ids),
                    "schema": "study_diagnosis_correction.v2",
                    "scientific_trial_delta": 0,
                    "study_close_record_id": original.payload.get(
                        "study_close_record_id"
                    ),
                    "study_id": study_id,
                    "system_architecture_family": architecture,
                    "supersedes_audit_id": (
                        None
                        if prior_correction is None
                        else prior_correction.payload.get("audit_id")
                    ),
                    "supersedes_correction_id": (
                        None
                        if prior_correction is None
                        else prior_correction.record_id
                    ),
                }
                digest = canonical_digest(
                    domain="study-diagnosis-correction",
                    payload=correction_payload,
                )
                correction = _record(
                    kind="study-diagnosis-correction",
                    record_id="diagnosis-correction:" + digest,
                    subject=original.subject,
                    status=pattern.evidence_state.value,
                    fingerprint=digest,
                    payload=correction_payload,
                    event_stream=stream,
                    event_sequence=correction_sequence,
                )
                correction_records.append(correction)
                corrections_by_original[original.record_id] = correction
                state_overrides[original.record_id] = pattern.evidence_state.value

            snapshot_id = next_action.get("portfolio_snapshot_id")
            if not isinstance(snapshot_id, str):
                raise TransitionError(
                    "diagnosis correction lost its Portfolio snapshot"
                )
            triggers = {
                trigger.record_id: trigger
                for architecture in sorted(architecture_families)
                for trigger in (
                    self._pending_architecture_review_trigger(
                        index=index,
                        mission_id=audit.mission_id,
                        portfolio_snapshot_id=snapshot_id,
                        architecture_family=architecture,
                        effective_state_overrides=state_overrides,
                        effective_authority_overrides={
                            original_id: (
                                "study-diagnosis-correction",
                                correction.record_id,
                            )
                            for original_id, correction
                            in corrections_by_original.items()
                        },
                        effective_diagnoses=effective_mission_diagnoses,
                        reviewed_diagnosis_ids=frozenset(
                            reviewed_diagnosis_ids
                        ),
                    ),
                )
                if trigger is not None
            }
            if len(triggers) > 1:
                raise TransitionError(
                    "diagnosis correction requires a typed architecture review queue"
                )
            body = self._body(current)
            if triggers:
                trigger = next(iter(triggers.values()))
                body["next_action"] = {
                    "kind": "review_architecture",
                    "trigger_record_id": trigger.record_id,
                }
                records = [audit_record, *correction_records, trigger]
            else:
                current_diagnosis_id = next_action.get("study_diagnosis_id")
                current_correction = corrections_by_original.get(
                    current_diagnosis_id
                )
                body["next_action"] = dict(next_action)
                if current_correction is not None:
                    body["next_action"].update(
                        {
                            "diagnosis_correction_audit_id": audit.identity,
                            "study_diagnosis_correction_id": (
                                current_correction.record_id
                            ),
                        }
                    )
                records = [audit_record, *correction_records]
            return body, records, {
                "audit_id": audit.identity,
                "candidate_authority_delta": 0,
                "corrected_diagnosis_count": len(correction_records),
                "holdout_reveal_delta": 0,
                "replay_satisfaction_delta": 0,
                "scientific_trial_delta": 0,
                "study_diagnosis_correction_ids": sorted(
                    record.record_id for record in correction_records
                ),
            }

        return self._commit(
            event_kind="study_diagnoses_corrected",
            operation_id=operation_id,
            subject=f"Mission:{audit.mission_id}",
            payload={"audit_id": audit.identity},
            prepare=prepare,
        )

    def record_architecture_review(
        self,
        *,
        review: Any,
        operation_id: str,
    ) -> TransitionResult:
        from axiom_rift.research.governance import (
            ArchitectureReview,
            ArchitectureReviewConclusion,
        )
        from axiom_rift.operations.architecture_review_direction import (
            ArchitectureReviewDirectionError,
            constraint_from_direction,
            require_existing_axis_binding,
            require_review_binding,
        )

        self._require_study_close_delivery_guard()
        if self.engineering_fixture:
            raise TransitionError("engineering fixtures do not create architecture review")
        if not isinstance(review, ArchitectureReview):
            raise TransitionError("review must be an ArchitectureReview")

        def prepare(current: dict[str, Any] | None, index: LocalIndex):
            if current is None or current["scientific"]["active_mission"] is None:
                raise TransitionError("architecture review requires an active Mission")
            science = current["scientific"]
            if science["active_mission"] != review.mission_id:
                raise TransitionError("architecture review belongs to another Mission")
            if any(
                science[name] is not None
                for name in (
                    "active_batch",
                    "active_executable",
                    "active_job",
                    "active_repair",
                    "active_study",
                )
            ):
                raise TransitionError("architecture review cannot bypass active work")
            next_action = current["next_action"]
            trigger_id = next_action.get("trigger_record_id")
            trigger = (
                None
                if not isinstance(trigger_id, str)
                else index.get("architecture-review-trigger", trigger_id)
            )
            if (
                next_action.get("kind") != "review_architecture"
                or trigger_id != review.trigger_record_id
                or trigger is None
                or trigger.status != "required"
                or trigger.payload.get("mission_id") != review.mission_id
                or trigger.payload.get("system_architecture_family")
                != review.system_architecture_family
            ):
                raise TransitionError("architecture review trigger is absent or stale")
            post_holdout_development_id = next_action.get(
                "post_holdout_development_id"
            )
            if post_holdout_development_id is not None:
                required_holdout_id = science.get(
                    "required_future_holdout_id"
                )
                if (
                    science.get("holdout_reveals", 0) < 1
                    or not isinstance(required_holdout_id, str)
                    or not isinstance(post_holdout_development_id, str)
                ):
                    raise TransitionError(
                        "architecture review post-holdout authority is malformed"
                    )
                self._require_post_holdout_development_authority(
                    index,
                    mission_id=review.mission_id,
                    record_id=post_holdout_development_id,
                    required_holdout_id=required_holdout_id,
                )
            payload = {
                **review.to_identity_payload(),
                "covered_diagnosis_ids": trigger.payload["diagnosis_ids"],
                "portfolio_axis_ids": trigger.payload["portfolio_axis_ids"],
                "portfolio_snapshot_id": trigger.payload["portfolio_snapshot_id"],
                "primary_research_layers": trigger.payload[
                    "primary_research_layers"
                ],
            }
            if isinstance(post_holdout_development_id, str):
                payload["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            trigger_schema = trigger.payload.get("schema")
            if trigger_schema == "architecture_review_trigger.v2":
                authorities = trigger.payload.get("diagnosis_authorities")
                if not isinstance(authorities, list):
                    raise RecoveryRequired(
                        "architecture review trigger authority is malformed"
                    )
                from axiom_rift.operations.effective_study_diagnosis import (
                    EffectiveStudyDiagnosisError,
                    effective_study_diagnosis,
                )

                for authority in authorities:
                    if not isinstance(authority, Mapping):
                        raise RecoveryRequired(
                            "architecture review trigger authority is malformed"
                        )
                    original_id = authority.get("original_diagnosis_id")
                    if not isinstance(original_id, str):
                        raise RecoveryRequired(
                            "architecture review trigger authority is malformed"
                        )
                    try:
                        effective = effective_study_diagnosis(
                            index,
                            original_id,
                        )
                    except EffectiveStudyDiagnosisError as exc:
                        raise RecoveryRequired(str(exc)) from exc
                    expected_kind = (
                        "study-diagnosis"
                        if effective.correction is None
                        else "study-diagnosis-correction"
                    )
                    if (
                        authority.get("effective_authority_kind")
                        != expected_kind
                        or authority.get("effective_authority_record_id")
                        != effective.authority_record_id
                    ):
                        raise TransitionError(
                            "architecture review diagnosis authority drifted"
                        )
                payload["diagnosis_authorities"] = [
                    dict(authority) for authority in authorities
                ]
            elif trigger_schema != "architecture_review_trigger.v1":
                raise RecoveryRequired(
                    "architecture review trigger schema is unsupported"
                )
            continuation = None
            if (
                review.conclusion
                is ArchitectureReviewConclusion.BOUNDED_SAME_ARCHITECTURE
            ):
                assert review.continuation_direction is not None
                continuation = constraint_from_direction(
                    architecture_review_id=review.identity,
                    direction=review.continuation_direction,
                )
                try:
                    require_review_binding(
                        continuation,
                        review_record_id=review.identity,
                        review_payload=payload,
                        trigger_payload=trigger.payload,
                    )
                except ArchitectureReviewDirectionError as exc:
                    raise TransitionError(str(exc)) from exc
                snapshot = index.get(
                    "portfolio-snapshot",
                    trigger.payload["portfolio_snapshot_id"],
                )
                if snapshot is None:
                    raise RecoveryRequired(
                        "architecture review lost its Portfolio snapshot"
                    )
                axis_values = tuple(snapshot.payload.get("axes", []))
                axes_by_id = {
                    axis["axis_id"]: axis
                    for axis in axis_values
                    if isinstance(axis, Mapping)
                    and isinstance(axis.get("axis_id"), str)
                }
                resolutions = self._effective_axis_resolutions(index, axis_values)
                selectable_axis_ids = frozenset(
                    axis["axis_id"]
                    for axis, resolution in zip(
                        axis_values,
                        resolutions,
                        strict=True,
                    )
                    if resolution.decision_option_eligible
                )
                resolved_families = {
                    axis_id: self._axis_resolved_architecture_family(
                        index=index,
                        axis=axis,
                    )
                    for axis_id, axis in axes_by_id.items()
                }
                try:
                    require_existing_axis_binding(
                        continuation,
                        axes_by_id=axes_by_id,
                        selectable_axis_ids=selectable_axis_ids,
                        resolved_architecture_families=resolved_families,
                    )
                except ArchitectureReviewDirectionError as exc:
                    raise TransitionError(str(exc)) from exc
            body = self._body(current)
            body["next_action"] = {
                "kind": "portfolio_decision",
                "architecture_review_id": review.identity,
                "constraint_source_id": review.identity,
                "portfolio_snapshot_id": trigger.payload["portfolio_snapshot_id"],
            }
            if isinstance(post_holdout_development_id, str):
                body["next_action"]["post_holdout_development_id"] = (
                    post_holdout_development_id
                )
            if continuation is not None:
                body["next_action"].update(continuation.to_action_fields())
            elif (
                review.conclusion
                == ArchitectureReviewConclusion.ROTATE_ARCHITECTURE
            ):
                body["next_action"]["excluded_architecture_family"] = (
                    review.system_architecture_family
                )
            else:
                body["next_action"]["excluded_research_layers"] = trigger.payload[
                    "primary_research_layers"
                ]
            record = _record(
                kind="architecture-review",
                record_id=review.identity,
                subject=f"Mission:{review.mission_id}",
                status=review.conclusion.value,
                fingerprint=review.identity.removeprefix("architecture-review:"),
                payload=payload,
            )
            return body, [record], {"architecture_review_id": review.identity}

        return self._commit(
            event_kind="architecture_review_recorded",
            operation_id=operation_id,
            subject=f"Mission:{review.mission_id}",
            payload={"architecture_review_id": review.identity},
            prepare=prepare,
        )
