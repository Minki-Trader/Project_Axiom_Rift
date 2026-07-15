from __future__ import annotations

from copy import deepcopy
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest

from axiom_rift.operations.effective_axis_projection import (
    EffectiveAxisProjectionError,
    audit_effective_axis_projection,
    eligible_performance_source_ids,
    effective_axis_resolution,
    effective_axis_resolutions,
    effective_replay_axis_bindings,
    mission_effective_axis_blockers,
    selectable_axis_ids,
    source_authority_subject_ids,
)
from axiom_rift.operations.evidence_scope_projection import (
    evidence_scope_overlay_record,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.operations.replay_projection import (
    initial_obligation_record,
    prepare_deferral,
    prepare_execution_progress,
    replay_evidence_record_ids,
    satisfaction_record,
)
from axiom_rift.research.effective_axis import (
    EffectiveAxisStatus,
    EvidenceScopeAxisBinding,
    ReplayAxisBinding,
)
from axiom_rift.research.effective_evidence_scope import (
    HistoricalEvidenceScopeOverlay,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import (
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
)
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayObligationStatus,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResolutionScope,
    ReplaySatisfaction,
    derive_historical_replay_obligation,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceAuthorityReason,
    SourceAuthoritySurface,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-EFFECTIVE-REPLAY"


def _put_authenticated_satisfaction(
    index: LocalIndex,
    transition: IndexRecord,
    *,
    token: int,
    obligation_id: str,
    event_kind: str,
) -> None:
    authority_sequence = 20_000 + token
    operation_id = f"authenticated-replay-satisfaction-{token}-{event_kind}"
    event_id = canonical_digest(
        domain="effective-axis-fixture-journal-event",
        payload={
            "authority_sequence": authority_sequence,
            "operation_id": operation_id,
            "record_id": transition.record_id,
        },
    )
    offset = authority_sequence * 100
    authority = {
        "authority_sequence": authority_sequence,
        "authority_event_id": event_id,
        "authority_offset": offset,
    }
    result = {"satisfied_replay_obligation_ids": [obligation_id]}
    index.put_many(
        (
            IndexRecord(
                kind="journal-event",
                record_id=event_id,
                subject="Mission:active",
                status=event_kind,
                fingerprint=event_id,
                payload={
                    "occurred_at_utc": "2026-07-15T00:00:00Z",
                    "operation_id": operation_id,
                },
                event_stream="control",
                event_sequence=authority_sequence,
                **authority,
            ),
            IndexRecord(
                kind="operation",
                record_id=operation_id,
                subject="Mission:active",
                status="success",
                fingerprint=canonical_digest(
                    domain="effective-axis-fixture-operation",
                    payload={"event_kind": event_kind, "result": result},
                ),
                payload={"event_kind": event_kind, "result": result},
                **authority,
            ),
            replace(transition, **authority),
        )
    )


def _adjudication_payload(token: int) -> dict[str, object]:
    criterion_id = f"criterion-{token}"
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": f"claim-{token}"}],
            "criteria": [
                {
                    "claim_id": f"claim-{token}",
                    "criterion_id": criterion_id,
                    "decision_role": "primary",
                    "metric": "net_information",
                    "operator": ">=",
                    "threshold": 1,
                }
            ],
        },
        "audit_artifact_hash": f"{token + 10:064x}",
        "completion_record_id": f"{token + 20:064x}",
        "disposition": "replay_required",
        "executable_id": f"executable:{token + 30:064x}",
        "measurement_artifact_hash": f"{token + 40:064x}",
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": ReplayPriority.P1.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": f"{token + 50:064x}",
        "study_id": f"STU-HIST-{token:04d}",
        "validation_plan_hash": f"{token + 60:064x}",
    }


def _axis(token: str, *, status: str = "open") -> dict[str, str]:
    return {
        "axis_id": f"axis-{token}",
        "axis_identity": "axis:" + token * 64,
        "status": status,
    }


def _source_invalidation_record(
    source_id: str,
    *,
    token: int,
) -> IndexRecord:
    source_state_record_id = f"{token + 100:064x}"
    manifest = SourceAuthorityAuditManifest(
        report_artifact_hash=f"{token + 101:064x}",
        report_finding_id=f"SOURCE-AUTH-{token:03d}",
        source_contract_id=source_id,
        source_state_record_id=source_state_record_id,
        surface=SourceAuthoritySurface.AVAILABILITY,
        reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
        observed_defect="point-in-time authority was not proven",
        observed_at_utc="2026-07-14T00:00:00Z",
    )
    invalidation = SourceAuthorityInvalidation(
        source_contract_id=source_id,
        source_state_record_id=source_state_record_id,
        audit_artifact_hash=f"{token + 102:064x}",
        surface=manifest.surface,
        reason_code=manifest.reason_code,
        observed_defect=manifest.observed_defect,
        observed_at_utc=manifest.observed_at_utc,
    )
    latch = SourceAuthorityLatch.bind(
        invalidation=invalidation,
        manifest=manifest,
    )
    return IndexRecord(
        kind="source-authority-invalidation",
        record_id=invalidation.identity,
        subject=f"Source:{source_id}",
        status="confirmed_and_suspended",
        fingerprint=invalidation.identity.removeprefix(
            "source-authority-invalidation:"
        ),
        payload={
            "audit_manifest": manifest.to_identity_payload(),
            "eligible_source_state_record_id": source_state_record_id,
            "invalidated_state": "historical_audited",
            "invalidation": invalidation.to_identity_payload(),
            "latch": latch.to_identity_payload(),
            "preserved_receipt_id": f"{token + 103:064x}",
            "prior_active_source_state_record_id": source_state_record_id,
            "replacement_state_record_id": f"{token + 104:064x}",
            "scientific_trial_delta": 0,
        },
        event_stream=f"source-authority:{source_id}",
        event_sequence=1,
    )


def _seed_obligation(
    index: LocalIndex,
    *,
    token: int,
    axis: dict[str, str],
    source_contract_ids: tuple[str, ...] = (),
    study_axis_identity: str | None = None,
):
    payload = _adjudication_payload(token)
    obligation = derive_historical_replay_obligation(
        governing_mission_id=MISSION_ID,
        historical_adjudication_id=f"historical-adjudication:{token:064x}",
        adjudication_payload=payload,
    )
    historical_mission_id = f"MIS-HIST-{token:04d}"
    job_id = f"job:{token + 70:064x}"
    effective_study_axis = (
        axis["axis_identity"]
        if study_axis_identity is None
        else study_axis_identity
    )
    index.put_many(
        (
            IndexRecord(
                kind="study-open",
                record_id=obligation.original_study_id,
                subject=f"Study:{obligation.original_study_id}",
                status="open",
                fingerprint=f"{token + 80:064x}",
                payload={
                    "mission_id": historical_mission_id,
                    "portfolio_axis_id": axis["axis_id"],
                    "portfolio_axis_identity": effective_study_axis,
                },
            ),
            IndexRecord(
                kind="trial",
                record_id=obligation.original_executable_id,
                subject=f"Batch:BAT-HIST-{token:04d}",
                status="evaluated",
                fingerprint=obligation.original_executable_id.removeprefix(
                    "executable:"
                ),
                payload={
                    "executable": {
                        "schema": "effective_axis_original_fixture.v1",
                        "source_contracts": list(source_contract_ids),
                    },
                    "mission_id": historical_mission_id,
                    "portfolio_axis_id": axis["axis_id"],
                    "portfolio_axis_identity": axis["axis_identity"],
                    "study_id": obligation.original_study_id,
                },
            ),
            IndexRecord(
                kind="job-declared",
                record_id=job_id,
                subject=f"Job:{job_id}",
                status="declared",
                fingerprint=f"{token + 71:064x}",
                payload={
                    "mission_id": historical_mission_id,
                    "spec": {
                        "evidence_subject": {
                            "id": obligation.original_executable_id,
                            "kind": "Executable",
                        }
                    },
                    "study_id": obligation.original_study_id,
                },
            ),
            IndexRecord(
                kind="job-completed",
                record_id=obligation.original_completion_record_id,
                subject=f"Job:{job_id}",
                status="success",
                fingerprint=f"{token + 72:064x}",
                payload={
                    "job_id": job_id,
                    "scientific": {
                        "candidate_eligible": False,
                        "executed_evidence_modes": ["causal_contrast"],
                        "executable_id": obligation.original_executable_id,
                        "scientific_eligible": True,
                    },
                },
            ),
            IndexRecord(
                kind="study-close",
                record_id=obligation.original_study_close_record_id,
                subject=f"Study:{obligation.original_study_id}",
                status="failed",
                fingerprint=f"{token + 50:064x}",
                payload={"study_id": obligation.original_study_id},
            ),
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=obligation.historical_adjudication_id,
                subject=f"Study:{obligation.original_study_id}",
                status="replay_required",
                fingerprint=f"{token:064x}",
                payload=payload,
            ),
            initial_obligation_record(obligation),
        )
    )
    return obligation


def _seed_replay_execution(
    index: LocalIndex,
    *,
    obligation,
    token: int,
    replay_axis: dict[str, str],
):
    decision_id = f"decision:{token + 100:064x}"
    study_id = f"STU-REPLAY-{token:04d}"
    replay_executable_id = f"executable:{token + 110:064x}"
    executable = {
        "authority": "prospective_scientific_replay",
        "component_manifests": [
            {
                "spec": {
                    "parameter_fields": [
                        "historical_reference_executable_id"
                    ]
                }
            }
        ],
        "parameters": {
            "historical_reference_executable_id": (
                obligation.original_executable_id
            )
        },
        "schema": "effective_axis_replay_fixture.v1",
        "source_contracts": [],
    }
    decision = IndexRecord(
        kind="portfolio-decision",
        record_id=decision_id,
        subject=f"Mission:{MISSION_ID}",
        status="contrast",
        fingerprint=decision_id.removeprefix("decision:"),
        payload={
            "baseline_executable": executable,
            "replay_obligation_ids": [obligation.identity],
            "target_axis_identity": replay_axis["axis_identity"],
        },
    )
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=f"{token + 101:064x}",
        payload={
            "mission_id": MISSION_ID,
            "portfolio_axis_id": replay_axis["axis_id"],
            "portfolio_axis_identity": replay_axis["axis_identity"],
            "portfolio_decision_id": decision_id,
            "replay_obligation_ids": [obligation.identity],
        },
    )
    index.put_many((decision, study))
    matched, progress = prepare_execution_progress(
        index,
        study_record=study,
        executable_id=replay_executable_id,
        executable_payload=executable,
    )
    assert matched == (obligation.identity,)
    trial = IndexRecord(
        kind="trial",
        record_id=replay_executable_id,
        subject=f"Batch:BAT-REPLAY-{token:04d}",
        status="evaluated",
        fingerprint=replay_executable_id.removeprefix("executable:"),
        payload={
            "executable": executable,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": replay_axis["axis_id"],
            "portfolio_axis_identity": replay_axis["axis_identity"],
            "replay_obligation_ids": [obligation.identity],
            "study_id": study_id,
        },
    )
    index.put_many((*progress, trial))
    return decision, study, trial


def _satisfy_replay(
    index: LocalIndex,
    *,
    obligation,
    token: int,
    replay_axis: dict[str, str],
    scope: ReplayResolutionScope,
    validator_id: str = SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
):
    decision, study, trial = _seed_replay_execution(
        index,
        obligation=obligation,
        token=token,
        replay_axis=replay_axis,
    )
    executable = dict(trial.payload["executable"])
    if scope is ReplayResolutionScope.AUDIT_ONLY:
        executable["authority"] = "post_selection_descriptive_audit_only"
        # The progress record and trial must bind the exact same manifest.
        # Seed audit mode at construction time by rebuilding this fixture path.
        raise AssertionError("audit fixture must use _satisfy_audit_only_replay")
    completion_id = f"{token + 120:064x}"
    close_id = f"{token + 121:064x}"
    diagnosis_id = f"diagnosis:{token + 122:064x}"
    job_id = f"job:{token + 123:064x}"
    criterion = dict(_adjudication_payload(token)["adjudication"]["criteria"][0])
    observed_criterion = {
        **criterion,
        "comparison_state": "passed",
        "scientific_state": "supported",
        "value": 2,
    }
    declaration = IndexRecord(
        kind="job-declared",
        record_id=job_id,
        subject=f"Job:{job_id}",
        status="declared",
        fingerprint=f"{token + 124:064x}",
        payload={
            "mission_id": MISSION_ID,
            "study_id": study.record_id,
            "spec": {
                "evidence_subject": {
                    "id": trial.record_id,
                    "kind": "Executable",
                },
                "scientific_binding": {
                    "validation_plan_hash": obligation.validation_plan_hash,
                    "validator_id": validator_id,
                },
            },
        },
    )
    completion = IndexRecord(
        kind="job-completed",
        record_id=completion_id,
        subject=f"Job:{job_id}",
        status="success",
        fingerprint=f"{token + 120:064x}",
        payload={
            "job_id": job_id,
            "scientific": {
                "adjudication": {
                    "criteria": [observed_criterion],
                    "evaluable": True,
                    "invalid_metrics": [],
                    "schema": "scientific_adjudication.v1",
                },
                "candidate_eligible": False,
                "executed_evidence_modes": ["causal_contrast"],
                "executable_id": trial.record_id,
                "scientific_eligible": True,
                "validation_plan_hash": obligation.validation_plan_hash,
                "validation_trace": {
                    "declared_artifact_count": 1,
                    "opened_artifact_count": 1,
                    "validator_id": validator_id,
                },
                "validator_id": validator_id,
            },
        },
    )
    close_record = IndexRecord(
        kind="study-close",
        record_id=close_id,
        subject=f"Study:{study.record_id}",
        status="failed",
        fingerprint=f"{token + 121:064x}",
        payload={"study_id": study.record_id},
    )
    diagnosis = IndexRecord(
        kind="study-diagnosis",
        record_id=diagnosis_id,
        subject=f"Study:{study.record_id}",
        status="complete",
        fingerprint=f"{token + 122:064x}",
        payload={
            "evidence_basis": [
                {"kind": "job-completed", "record_id": completion_id}
            ],
            "study_close_record_id": close_id,
            "study_id": study.record_id,
        },
    )
    index.put_many((declaration, completion, close_record, diagnosis))
    satisfaction = ReplaySatisfaction(
        obligation_id=obligation.identity,
        resolution_scope=scope,
        portfolio_decision_id=decision.record_id,
        replay_study_id=study.record_id,
        replay_executable_id=trial.record_id,
        replay_study_close_record_id=close_record.record_id,
        study_diagnosis_id=diagnosis.record_id,
        satisfied_criterion_ids=obligation.criterion_ids,
        evidence_record_ids=replay_evidence_record_ids(
            diagnosis=diagnosis,
            close_record=close_record,
            trial=trial,
        ),
    )
    _put_authenticated_satisfaction(
        index,
        satisfaction_record(
            obligation=obligation,
            satisfaction=satisfaction,
            prior_status=ReplayObligationStatus.IN_PROGRESS,
            sequence=3,
        ),
        token=token,
        obligation_id=obligation.identity,
        event_kind="historical_replay_obligations_resolved",
    )
    return satisfaction


def _satisfy_audit_only_replay(
    index: LocalIndex,
    *,
    obligation,
    token: int,
    replay_axis: dict[str, str],
):
    decision_id = f"decision:{token + 200:064x}"
    study_id = f"STU-AUDIT-{token:04d}"
    executable_id = f"executable:{token + 210:064x}"
    executable = {
        "authority": "post_selection_descriptive_audit_only",
        "component_manifests": [],
        "exact_legacy_member": obligation.original_executable_id,
        "parameters": {},
        "schema": "effective_axis_audit_fixture.v1",
        "source_contracts": [],
    }
    completion_id = f"{token + 220:064x}"
    close_id = f"{token + 221:064x}"
    diagnosis_id = f"diagnosis:{token + 222:064x}"
    job_id = f"job:{token + 223:064x}"
    decision = IndexRecord(
        kind="portfolio-decision",
        record_id=decision_id,
        subject=f"Mission:{MISSION_ID}",
        status="synthesize",
        fingerprint=decision_id.removeprefix("decision:"),
        payload={
            "baseline_executable": executable,
            "replay_obligation_ids": [obligation.identity],
            "target_axis_identity": replay_axis["axis_identity"],
        },
    )
    study = IndexRecord(
        kind="study-open",
        record_id=study_id,
        subject=f"Study:{study_id}",
        status="open",
        fingerprint=f"{token + 201:064x}",
        payload={
            "mission_id": MISSION_ID,
            "portfolio_axis_id": replay_axis["axis_id"],
            "portfolio_axis_identity": replay_axis["axis_identity"],
            "portfolio_decision_id": decision_id,
            "replay_obligation_ids": [obligation.identity],
        },
    )
    trial = IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=f"Batch:BAT-AUDIT-{token:04d}",
        status="evaluated",
        fingerprint=executable_id.removeprefix("executable:"),
        payload={
            "executable": executable,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": replay_axis["axis_id"],
            "portfolio_axis_identity": replay_axis["axis_identity"],
            "replay_obligation_ids": [obligation.identity],
            "study_id": study_id,
        },
    )
    declaration = IndexRecord(
        kind="job-declared",
        record_id=job_id,
        subject=f"Job:{job_id}",
        status="declared",
        fingerprint=f"{token + 224:064x}",
        payload={
            "mission_id": MISSION_ID,
            "study_id": study_id,
            "spec": {
                "evidence_subject": {"id": executable_id, "kind": "Executable"}
            },
        },
    )
    completion = IndexRecord(
        kind="job-completed",
        record_id=completion_id,
        subject=f"Job:{job_id}",
        status="success",
        fingerprint=f"{token + 220:064x}",
        payload={
            "job_id": job_id,
            "scientific": {
                "candidate_eligible": False,
                "executed_evidence_modes": ["causal_contrast"],
                "executable_id": executable_id,
                "scientific_eligible": True,
            },
        },
    )
    close_record = IndexRecord(
        kind="study-close",
        record_id=close_id,
        subject=f"Study:{study_id}",
        status="failed",
        fingerprint=f"{token + 221:064x}",
        payload={"study_id": study_id},
    )
    diagnosis = IndexRecord(
        kind="study-diagnosis",
        record_id=diagnosis_id,
        subject=f"Study:{study_id}",
        status="complete",
        fingerprint=f"{token + 222:064x}",
        payload={
            "evidence_basis": [
                {"kind": "job-completed", "record_id": completion_id}
            ],
            "study_close_record_id": close_id,
            "study_id": study_id,
        },
    )
    index.put_many(
        (decision, study, trial, declaration, completion, close_record, diagnosis)
    )
    satisfaction = ReplaySatisfaction(
        obligation_id=obligation.identity,
        resolution_scope=ReplayResolutionScope.AUDIT_ONLY,
        portfolio_decision_id=decision_id,
        replay_study_id=study_id,
        replay_executable_id=executable_id,
        replay_study_close_record_id=close_id,
        study_diagnosis_id=diagnosis_id,
        satisfied_criterion_ids=obligation.criterion_ids,
        evidence_record_ids=replay_evidence_record_ids(
            diagnosis=diagnosis,
            close_record=close_record,
            trial=trial,
        ),
        remaining_scientific_condition="prospective_exact_replay_required",
    )
    resolution = satisfaction_record(
        obligation=obligation,
        satisfaction=satisfaction,
        prior_status=ReplayObligationStatus.PENDING,
        sequence=2,
    )
    overlay = HistoricalEvidenceScopeOverlay(
        completion_record_id=completion_id,
        governing_mission_id=MISSION_ID,
        replay_study_id=study_id,
        replay_obligation_ids=(obligation.identity,),
        replay_resolution_ids=(satisfaction.identity,),
    )
    _put_authenticated_satisfaction(
        index,
        resolution,
        token=token,
        obligation_id=obligation.identity,
        event_kind="historical_replay_correction_recorded",
    )
    index.put(evidence_scope_overlay_record(overlay))
    return satisfaction, overlay


class EffectiveAxisProjectionTests(unittest.TestCase):
    @staticmethod
    def _typed_source_executable(
        source_id: str,
        *,
        performance: bool,
        declared_source_id: str | None = None,
        performance_allowed: bool | None = None,
        omit_performance_allowed: bool = False,
    ) -> ExecutableSpec:
        specification: dict[str, object] = {
            "source_contract_id": (
                source_id if declared_source_id is None else declared_source_id
            ),
        }
        if not omit_performance_allowed:
            specification["performance_allowed"] = (
                performance
                if performance_allowed is None
                else performance_allowed
            )
        component = ComponentSpec(
            display_name="typed external source projection fixture",
            protocol="external_source.projection_fixture.v1",
            implementation="fixture.external_source@sha256:" + "f" * 64,
            spec=specification,
            semantic_dependencies=(source_id,) if performance else (),
        )
        return ExecutableSpec(
            display_name="typed external source projection fixture",
            components=(component,),
            parameters={"performance": performance},
            data_contract="data:projection-fixture",
            split_contract="split:projection-fixture",
            clock_contract="clock:projection-fixture",
            cost_contract="cost:projection-fixture",
            engine_contract="engine:projection-fixture",
            source_contracts=(source_id,) if performance else (),
        )

    def test_zero_trial_typed_source_axis_is_blocked_by_its_invalidated_authority(
        self,
    ) -> None:
        source_id = "source:" + "1" * 64
        axis = _axis("7")
        unrelated = _axis("8")
        eligibility_only = self._typed_source_executable(
            source_id,
            performance=False,
        )
        payload = eligibility_only.to_identity_payload()
        self.assertEqual(eligible_performance_source_ids(payload), ())
        self.assertEqual(source_authority_subject_ids(payload), (source_id,))

        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(
                    (
                        IndexRecord(
                            kind="portfolio-decision",
                            record_id="decision:" + "9" * 64,
                            subject=f"Mission:{MISSION_ID}",
                            status="accepted",
                            fingerprint="9" * 64,
                            payload={
                                "baseline_executable": payload,
                                "target_axis_identity": axis["axis_identity"],
                            },
                        ),
                        _source_invalidation_record(source_id, token=130),
                    )
                )
                self.assertEqual(index.records_by_kind("trial"), ())
                resolution = effective_axis_resolution(index, axis)
                self.assertEqual(resolution.source_contract_ids, (source_id,))
                self.assertIs(
                    resolution.effective_status,
                    EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
                )
                self.assertFalse(resolution.selectable)
                self.assertFalse(resolution.decision_option_eligible)
                self.assertFalse(resolution.terminal_eligible)
                self.assertEqual(
                    selectable_axis_ids(index, (axis, unrelated)),
                    (unrelated["axis_id"],),
                )

    def test_source_authority_subjects_preserve_performance_meaning_and_fail_closed(
        self,
    ) -> None:
        source_id = "source:" + "2" * 64
        other_source_id = "source:" + "3" * 64
        performance = self._typed_source_executable(
            source_id,
            performance=True,
        ).to_identity_payload()
        self.assertEqual(
            eligible_performance_source_ids(performance),
            (source_id,),
        )
        self.assertEqual(
            source_authority_subject_ids(performance),
            (source_id,),
        )

        legacy_feature = ComponentSpec(
            display_name="legacy source-consuming feature fixture",
            protocol="feature.source_projection_fixture.v1",
            implementation="fixture.feature@sha256:" + "e" * 64,
            spec={"availability": "completed_bar_only"},
            semantic_dependencies=(source_id,),
        )
        legacy_performance = ExecutableSpec(
            display_name="legacy performance source fixture",
            components=(legacy_feature,),
            parameters={},
            data_contract="data:projection-fixture",
            split_contract="split:projection-fixture",
            clock_contract="clock:projection-fixture",
            cost_contract="cost:projection-fixture",
            engine_contract="engine:projection-fixture",
            source_contracts=(source_id,),
        ).to_identity_payload()
        self.assertEqual(
            source_authority_subject_ids(legacy_performance),
            (source_id,),
        )

        non_contract_external_material = ExecutableSpec(
            display_name="non-SourceContract external material fixture",
            components=(
                ComponentSpec(
                    display_name="bounded external development material",
                    protocol="external_source.development_fixture.v1",
                    implementation="fixture.external_material@sha256:" + "d" * 64,
                    spec={"material_identity": "material:" + "a" * 64},
                ),
            ),
            parameters={},
            data_contract="data:projection-fixture",
            split_contract="split:projection-fixture",
            clock_contract="clock:projection-fixture",
            cost_contract="cost:projection-fixture",
            engine_contract="engine:projection-fixture",
        ).to_identity_payload()
        self.assertEqual(
            source_authority_subject_ids(non_contract_external_material),
            (),
        )

        for malformed_eligibility in (
            self._typed_source_executable(
                source_id,
                performance=False,
                omit_performance_allowed=True,
            ),
            self._typed_source_executable(
                source_id,
                performance=False,
                performance_allowed=True,
            ),
        ):
            with self.assertRaisesRegex(
                EffectiveAxisProjectionError,
                "requires explicit performance_allowed false",
            ):
                source_authority_subject_ids(
                    malformed_eligibility.to_identity_payload()
                )

        omitted_performance_marker = self._typed_source_executable(
            source_id,
            performance=True,
            omit_performance_allowed=True,
        ).to_identity_payload()
        self.assertEqual(
            source_authority_subject_ids(omitted_performance_marker),
            (source_id,),
        )
        explicit_false_performance = self._typed_source_executable(
            source_id,
            performance=True,
            performance_allowed=False,
        ).to_identity_payload()
        with self.assertRaisesRegex(
            EffectiveAxisProjectionError,
            "cannot declare performance_allowed false",
        ):
            source_authority_subject_ids(explicit_false_performance)

        mismatch = self._typed_source_executable(
            source_id,
            performance=True,
            declared_source_id=other_source_id,
        ).to_identity_payload()
        with self.assertRaisesRegex(
            EffectiveAxisProjectionError,
            "disagrees with its semantic source dependency",
        ):
            source_authority_subject_ids(mismatch)

    def test_read_only_batch_projection_is_pure_equal_and_bounded(self) -> None:
        class CountingView:
            def __init__(self, view: object) -> None:
                self.view = view
                self.calls: Counter[str] = Counter()

            def __getattr__(self, name: str):
                value = getattr(self.view, name)
                if not callable(value):
                    return value

                def call(*args: object, **kwargs: object):
                    self.calls[name] += 1
                    return value(*args, **kwargs)

                return call

        axes = tuple(
            {
                "axis_id": f"axis-{ordinal}",
                "axis_identity": f"axis:{ordinal:064x}",
                "status": "open",
            }
            for ordinal in range(1, 33)
        )
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite") as index:
                view = index.read_only()
                before_count = index.record_count()
                before_attributes = tuple(dir(view))
                direct = effective_axis_resolution(view, axes[0])
                batch = effective_axis_resolutions(view, axes)
                self.assertEqual(batch[0], direct)
                self.assertEqual(tuple(item.axis_id for item in batch), tuple(
                    axis["axis_id"] for axis in axes
                ))
                self.assertEqual(index.record_count(), before_count)
                self.assertEqual(tuple(dir(view)), before_attributes)
                self.assertFalse(
                    hasattr(view, "_axiom_axis_source_lineage_cache")
                )
                self.assertFalse(
                    hasattr(view, "_axiom_effective_axis_authority_cache")
                )

                one = CountingView(view)
                effective_axis_resolutions(one, axes[:1])
                many = CountingView(view)
                effective_axis_resolutions(many, axes)
                self.assertEqual(one.calls, many.calls)
                self.assertNotIn("record_count", many.calls)
                self.assertNotIn("records_by_kind", many.calls)
                self.assertGreater(
                    many.calls["records_by_payload_text_values"],
                    0,
                )

    def test_invalidated_lineage_stays_blocked_until_new_source_and_axis(self) -> None:
        invalid_source = "source:" + "1" * 64
        replacement_source = "source:" + "2" * 64
        old_axis = {
            "axis_id": "axis-invalidated-source",
            "axis_identity": "axis:" + "3" * 64,
            "status": "pruned",
        }
        new_axis = {
            "axis_id": "axis-replacement-source",
            "axis_identity": "axis:" + "4" * 64,
            "status": "open",
        }
        invalidation_record = _source_invalidation_record(
            invalid_source,
            token=5,
        )
        invalidation_id = invalidation_record.record_id
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(
                    (
                        IndexRecord(
                            kind="portfolio-decision",
                            record_id="decision:" + "6" * 64,
                            subject="Mission:MIS-EFFECTIVE-AXIS",
                            status="accepted",
                            fingerprint="6" * 64,
                            payload={
                                "baseline_executable": {
                                    "source_contracts": [invalid_source]
                                },
                                "target_axis_identity": old_axis["axis_identity"],
                            },
                        ),
                        invalidation_record,
                    )
                )
                old = effective_axis_resolution(index, old_axis)
                self.assertEqual(old.snapshot_status, "pruned")
                self.assertIs(
                    old.effective_status,
                    EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
                )
                self.assertFalse(old.terminal_eligible)
                old_with_replacement = effective_axis_resolution(
                    index,
                    old_axis,
                    prospective_source_ids=(replacement_source,),
                )
                self.assertIs(
                    old_with_replacement.effective_status,
                    EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
                )
                replacement = effective_axis_resolution(
                    index,
                    new_axis,
                    prospective_source_ids=(replacement_source,),
                )
                self.assertIs(
                    replacement.effective_status,
                    EffectiveAxisStatus.SELECTABLE,
                )

    def test_unresolved_replay_blocks_only_its_exact_axis_and_terminal(self) -> None:
        blocked_axis = _axis("a")
        unrelated_axis = _axis("b")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                pending = _seed_obligation(
                    index, token=1, axis=blocked_axis
                )
                in_progress = _seed_obligation(
                    index, token=2, axis=blocked_axis
                )
                _seed_replay_execution(
                    index,
                    obligation=in_progress,
                    token=2,
                    replay_axis=_axis("c"),
                )
                deferred = _seed_obligation(
                    index, token=3, axis=blocked_axis
                )
                basis_id = "diagnosis:" + "d" * 64
                index.put(
                    IndexRecord(
                        kind="study-diagnosis",
                        record_id=basis_id,
                        subject=f"Study:{deferred.original_study_id}",
                        status="complete",
                        fingerprint="d" * 64,
                        payload={
                            "evidence_basis": [
                                {
                                    "kind": "job-completed",
                                    "record_id": (
                                        deferred.original_completion_record_id
                                    ),
                                },
                                {
                                    "kind": "study-close",
                                    "record_id": (
                                        deferred.original_study_close_record_id
                                    ),
                                },
                            ],
                            "mission_id": MISSION_ID,
                            "study_close_record_id": (
                                deferred.original_study_close_record_id
                            ),
                            "study_id": deferred.original_study_id,
                        },
                    )
                )
                deferral = ReplayDeferral(
                    obligation_id=deferred.identity,
                    basis=ReplayDeferralBasis(
                        kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                        record_id=basis_id,
                        subject_id=deferred.original_study_id,
                    ),
                    reason_codes=("await_exact_input",),
                    resume_conditions=(
                        ReplayResumeCondition(
                            kind=(
                                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL
                            ),
                            protocol_id="effective-axis-replay-v1",
                            original_executable_ids=(
                                deferred.original_executable_id,
                            ),
                            criterion_ids=deferred.criterion_ids,
                        ),
                    ),
                )
                deferral_records, _constraints, _result = prepare_deferral(
                    index,
                    mission_id=MISSION_ID,
                    deferrals=(deferral,),
                )
                index.put_many(deferral_records)

                before = deepcopy(blocked_axis)
                resolution = effective_axis_resolution(index, blocked_axis)
                self.assertEqual(blocked_axis, before)
                self.assertIs(
                    resolution.status,
                    EffectiveAxisStatus.BLOCKED_BY_REPLAY_OBLIGATION,
                )
                self.assertFalse(resolution.selectable)
                self.assertFalse(resolution.terminal_eligible)
                self.assertEqual(
                    {item.status for item in resolution.replay_bindings},
                    {
                        ReplayObligationStatus.PENDING,
                        ReplayObligationStatus.IN_PROGRESS,
                        ReplayObligationStatus.DEFERRED,
                    },
                )
                self.assertEqual(
                    selectable_axis_ids(index, (blocked_axis, unrelated_axis)),
                    (unrelated_axis["axis_id"],),
                )
                blockers = mission_effective_axis_blockers(
                    index, mission_id=MISSION_ID
                )
                self.assertEqual(len(blockers), 3)
                self.assertTrue(
                    all(isinstance(item, ReplayAxisBinding) for item in blockers)
                )
                self.assertEqual(
                    {item.obligation_id for item in blockers},
                    {pending.identity, in_progress.identity, deferred.identity},
                )
                self.assertTrue(
                    effective_axis_resolution(index, unrelated_axis).selectable
                )

    def test_exact_scientific_satisfaction_clears_replay_block(self) -> None:
        original_axis = _axis("e")
        replay_axis = _axis("f")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                obligation = _seed_obligation(
                    index, token=10, axis=original_axis
                )
                _satisfy_replay(
                    index,
                    obligation=obligation,
                    token=10,
                    replay_axis=replay_axis,
                    scope=ReplayResolutionScope.SCIENTIFIC,
                )
                with patch(
                    "axiom_rift.operations.replay_projection."
                    "_require_scientific_satisfaction_evidence",
                    side_effect=AssertionError(
                        "stored satisfaction must not run current protocol"
                    ),
                ):
                    resolution = effective_axis_resolution(index, original_axis)
                self.assertTrue(resolution.selectable)
                self.assertTrue(resolution.terminal_eligible)
                self.assertEqual(resolution.blocking_replay_obligation_ids, ())
                self.assertEqual(
                    resolution.replay_bindings[0].resolution_scope,
                    ReplayResolutionScope.SCIENTIFIC,
                )
                self.assertEqual(
                    mission_effective_axis_blockers(
                        index, mission_id=MISSION_ID
                    ),
                    (),
                )

    def test_scientific_satisfaction_survives_validator_upgrade(self) -> None:
        original_axis = _axis("a")
        replay_axis = _axis("b")
        historical_validator_id = "validator:" + "f" * 64
        self.assertNotEqual(
            historical_validator_id,
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        )
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                obligation = _seed_obligation(
                    index,
                    token=14,
                    axis=original_axis,
                )
                _satisfy_replay(
                    index,
                    obligation=obligation,
                    token=14,
                    replay_axis=replay_axis,
                    scope=ReplayResolutionScope.SCIENTIFIC,
                    validator_id=historical_validator_id,
                )
                resolution = effective_axis_resolution(index, original_axis)
                self.assertTrue(resolution.selectable)
                self.assertTrue(resolution.terminal_eligible)
                self.assertEqual(resolution.blocking_replay_obligation_ids, ())

    def test_audit_only_scope_zero_credits_completion_without_blocking_axes(
        self,
    ) -> None:
        source_id = "source:" + "7" * 64
        original_axis = _axis("1", status="pruned")
        audit_axis = _axis("2")
        unrelated_axis = _axis("3")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                obligation = _seed_obligation(
                    index,
                    token=20,
                    axis=original_axis,
                    source_contract_ids=(source_id,),
                )
                _satisfaction, overlay = _satisfy_audit_only_replay(
                    index,
                    obligation=obligation,
                    token=20,
                    replay_axis=audit_axis,
                )
                original = effective_axis_resolution(index, original_axis)
                audit = effective_axis_resolution(index, audit_axis)
                self.assertIs(
                    original.effective_status,
                    EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
                )
                self.assertIs(
                    audit.effective_status,
                    EffectiveAxisStatus.SELECTABLE,
                )
                self.assertEqual(
                    original.replay_bindings[0].evidence_scope_overlay_id,
                    overlay.identity,
                )
                self.assertFalse(original.selectable)
                self.assertTrue(original.decision_option_eligible)
                self.assertTrue(original.requires_reopen)
                self.assertTrue(original.terminal_eligible)
                self.assertEqual(original.blocking_replay_obligation_ids, ())
                self.assertNotIn(
                    "terminal_excluded",
                    original.to_projection_payload(),
                )
                original_open = effective_axis_resolution(
                    index,
                    {**original_axis, "status": "open"},
                )
                self.assertIs(
                    original_open.effective_status,
                    EffectiveAxisStatus.SELECTABLE,
                )
                self.assertTrue(original_open.selectable)
                self.assertTrue(original_open.terminal_eligible)
                original_preserved = effective_axis_resolution(
                    index,
                    {**original_axis, "status": "preserved"},
                )
                self.assertIs(
                    original_preserved.effective_status,
                    EffectiveAxisStatus.SELECTABLE,
                )
                self.assertTrue(original_preserved.selectable)
                self.assertEqual(len(audit.evidence_scope_bindings), 1)
                self.assertIsInstance(
                    audit.evidence_scope_bindings[0], EvidenceScopeAxisBinding
                )
                self.assertEqual(
                    audit.evidence_scope_bindings[0].overlay_record_id,
                    overlay.identity,
                )
                self.assertTrue(audit.selectable)
                self.assertEqual(
                    selectable_axis_ids(
                        index,
                        (original_axis, audit_axis, unrelated_axis),
                    ),
                    tuple(
                        sorted(
                            (audit_axis["axis_id"], unrelated_axis["axis_id"])
                        )
                    ),
                )
                blockers = mission_effective_axis_blockers(
                    index, mission_id=MISSION_ID
                )
                self.assertEqual(blockers, ())

                invalidation_record = _source_invalidation_record(
                    source_id,
                    token=8,
                )
                index.put(invalidation_record)
                precedence = effective_axis_resolution(index, original_axis)
                self.assertIs(
                    precedence.effective_status,
                    EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
                )
                self.assertEqual(precedence.snapshot_status, "pruned")

                pending = _seed_obligation(
                    index,
                    token=21,
                    axis=original_axis,
                    source_contract_ids=(source_id,),
                )
                self.assertEqual(
                    tuple(
                        item.obligation_id
                        for item in mission_effective_axis_blockers(
                            index, mission_id=MISSION_ID
                        )
                    ),
                    (pending.identity,),
                )

    def test_writer_reopens_only_the_exact_audit_deferred_pruned_axis(
        self,
    ) -> None:
        def portfolio_axis(
            axis_id: str,
            *,
            layer: ResearchLayer,
            controlled: ResearchLayer,
            mechanism: str,
            status: str,
        ) -> PortfolioAxis:
            return PortfolioAxis(
                axis_id=axis_id,
                causal_question=(
                    f"Does {mechanism} retain information after audit correction?"
                ),
                mechanism_family=mechanism,
                primary_research_layer=layer,
                system_architecture_family=(
                    f"architecture-family:{mechanism}"
                ),
                changed_domains=(layer,),
                controlled_domains=(controlled,),
                why_now="the audit changed the exact historical completion scope",
                stop_or_reopen_condition=(
                    "reopen only through the exact audit-deferred authority"
                ),
                status=status,
            )

        target_pruned = portfolio_axis(
            "axis-audit-pruned",
            layer=ResearchLayer.FEATURE,
            controlled=ResearchLayer.MODEL,
            mechanism="audit-pruned-mechanism",
            status="pruned",
        )
        unrelated_open = portfolio_axis(
            "axis-unrelated-open",
            layer=ResearchLayer.MODEL,
            controlled=ResearchLayer.FEATURE,
            mechanism="unrelated-open-mechanism",
            status="open",
        )
        initial_snapshot = PortfolioSnapshot(
            mission_id=MISSION_ID,
            axes=(target_pruned, unrelated_open),
            opportunity_cost_basis=(
                "retain the unrelated branch while correcting exact audit scope"
            ),
        )

        def preserve_decision(tag: str) -> PortfolioDecision:
            return PortfolioDecision(
                decision_id=f"DEC-{tag}",
                chosen_option_id="preserve-audit-pruned",
                options=(
                    DecisionOption(
                        option_id="preserve-audit-pruned",
                        action=PortfolioAction.PRESERVE,
                        target_id=target_pruned.axis_id,
                        expected_information_value=(
                            "restore one branch whose old prune lost its evidence scope"
                        ),
                        opportunity_cost="one additive authority transition",
                    ),
                    DecisionOption(
                        option_id="contrast-unrelated",
                        action=PortfolioAction.CONTRAST,
                        target_id=unrelated_open.axis_id,
                        expected_information_value="continue unrelated valid research",
                        opportunity_cost="leave the audit-deferred branch unresolved",
                        omission_reason=(
                            "the exact historical prune must be corrected first"
                        ),
                    ),
                ),
                rationale=(
                    "preserve only the branch whose audit-only replay removed prune credit"
                ),
                commitment_batches=1,
            )

        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                Path(temporary) / "writer",
                clock=lambda: "2026-07-15T00:00:00Z",
                engineering_fixture=True,
                foundation_root=Path(__file__).resolve().parents[2],
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id=MISSION_ID,
                goal={
                    "objective": "exercise exact audit-deferred axis reopening",
                    "scope": ["isolated", "engineering_fixture"],
                    "terminal_contract": "no_scientific_terminal",
                },
                operation_id="axis-reopen-open-mission",
            )
            writer.open_initiative(
                initiative_id="INI-AXIS-REOPEN",
                objective={
                    "objective": "prove exact additive axis reopen authority",
                    "bounds": {"trial_delta": 0, "wall_seconds": 30},
                    "done_conditions": ["exact transition accepted"],
                },
                operation_id="axis-reopen-open-initiative",
            )
            writer.record_portfolio_snapshot(
                snapshot=initial_snapshot,
                operation_id="axis-reopen-initial-snapshot",
            )

            with self.assertRaisesRegex(
                TransitionError,
                "effectively blocked target axis",
            ):
                writer.record_portfolio_decision(
                    decision=preserve_decision("ARBITRARY-PRUNE"),
                    operation_id="reject-arbitrary-pruned-axis-reopen",
                )

            initial_target = next(
                axis
                for axis in initial_snapshot.to_identity_payload()["axes"]
                if axis["axis_id"] == target_pruned.axis_id
            )
            initial_unrelated = next(
                axis
                for axis in initial_snapshot.to_identity_payload()["axes"]
                if axis["axis_id"] == unrelated_open.axis_id
            )
            seed_kinds = (
                "historical-evidence-scope-overlay",
                "historical-replay-obligation",
                "historical-replay-obligation-resolution",
                "historical-scientific-adjudication",
                "job-completed",
                "job-declared",
                "portfolio-decision",
                "study-close",
                "study-diagnosis",
                "study-open",
                "trial",
            )
            with TemporaryDirectory() as seed_temporary:
                with LocalIndex(
                    Path(seed_temporary) / "seed.sqlite3"
                ) as seed_index:
                    obligation = _seed_obligation(
                        seed_index,
                        token=90,
                        axis=initial_target,
                    )
                    satisfaction, overlay = _satisfy_audit_only_replay(
                        seed_index,
                        obligation=obligation,
                        token=90,
                        replay_axis=initial_unrelated,
                    )
                    seeded_records = tuple(
                        record
                        for kind in seed_kinds
                        for record in seed_index.records_by_kind(kind)
                    )

            def seed_audit_authority(current, _index):
                assert current is not None
                return writer._body(current), list(seeded_records), {
                    "satisfied_replay_obligation_ids": [obligation.identity]
                }

            writer._commit(
                event_kind="historical_replay_correction_recorded",
                operation_id="seed-audit-only-replay-authority",
                subject=f"Mission:{MISSION_ID}",
                payload={"trial_delta": 0},
                prepare=seed_audit_authority,
            )
            with LocalIndex(writer.index_path) as index:
                deferred = effective_axis_resolution(index, initial_target)
            self.assertIs(
                deferred.effective_status,
                EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
            )

            accepted = preserve_decision("EXACT-AUDIT-REOPEN")
            writer.record_portfolio_decision(
                decision=accepted,
                operation_id="accept-exact-audit-reopen-decision",
            )
            control = writer.read_control()
            assert control is not None
            self.assertEqual(
                control["next_action"]["kind"],
                "record_axis_reopen_authority",
            )
            self.assertEqual(
                control["next_action"]["replay_resolution_record_ids"],
                [satisfaction.identity],
            )
            self.assertEqual(
                control["next_action"]["evidence_scope_overlay_ids"],
                [overlay.identity],
            )

            target_preserved = portfolio_axis(
                "axis-audit-pruned",
                layer=ResearchLayer.FEATURE,
                controlled=ResearchLayer.MODEL,
                mechanism="audit-pruned-mechanism",
                status="preserved",
            )
            preserved_snapshot = PortfolioSnapshot(
                mission_id=MISSION_ID,
                axes=(target_preserved, unrelated_open),
                opportunity_cost_basis=(
                    "retain the unrelated branch while correcting exact audit scope"
                ),
            )
            with self.assertRaisesRegex(
                TransitionError,
                "pending audit-deferred axis reopen authority",
            ):
                writer.record_portfolio_snapshot(
                    snapshot=preserved_snapshot,
                    operation_id="reject-snapshot-before-reopen-authority",
                )

            authority_result = writer.record_axis_reopen_authority(
                operation_id="record-exact-axis-reopen-authority"
            )
            authority_id = authority_result.result[
                "axis_reopen_authority_id"
            ]
            unrelated_preserved = portfolio_axis(
                "axis-unrelated-open",
                layer=ResearchLayer.MODEL,
                controlled=ResearchLayer.FEATURE,
                mechanism="unrelated-open-mechanism",
                status="preserved",
            )
            wrong_snapshot = PortfolioSnapshot(
                mission_id=MISSION_ID,
                axes=(target_preserved, unrelated_preserved),
                opportunity_cost_basis=(
                    "retain the unrelated branch while correcting exact audit scope"
                ),
            )
            with self.assertRaisesRegex(
                TransitionError,
                "differs from its structural Decision",
            ):
                writer.record_portfolio_snapshot(
                    snapshot=wrong_snapshot,
                    operation_id="reject-cross-axis-reopen-authority",
                )

            writer.record_portfolio_snapshot(
                snapshot=preserved_snapshot,
                operation_id="record-authorized-preserved-snapshot",
            )
            with LocalIndex(writer.index_path) as index:
                authority = index.get("axis-reopen-authority", authority_id)
                original = index.get(
                    "portfolio-snapshot", initial_snapshot.identity
                )
                current = index.get(
                    "portfolio-snapshot", preserved_snapshot.identity
                )
                current_target = next(
                    axis
                    for axis in current.payload["axes"]
                    if axis["axis_id"] == target_pruned.axis_id
                )
                reopened = effective_axis_resolution(index, current_target)
            assert authority is not None and original is not None
            self.assertEqual(
                next(
                    axis["status"]
                    for axis in original.payload["axes"]
                    if axis["axis_id"] == target_pruned.axis_id
                ),
                "pruned",
            )
            self.assertEqual(current_target["status"], "preserved")
            self.assertIs(
                reopened.effective_status,
                EffectiveAxisStatus.SELECTABLE,
            )
            self.assertEqual(
                authority.payload["authority"][
                    "replay_resolution_record_ids"
                ],
                [satisfaction.identity],
            )
            self.assertEqual(
                authority.payload["authority"][
                    "evidence_scope_overlay_ids"
                ],
                [overlay.identity],
            )
            self.assertEqual(authority.payload["scientific_credit"], 0)
            with self.assertRaisesRegex(
                TransitionError,
                "no exact audit-deferred axis reopen is pending",
            ):
                writer.record_axis_reopen_authority(
                    operation_id="reject-reusing-axis-reopen-authority"
                )

    def test_malformed_original_executable_axis_lineage_fails_closed(self) -> None:
        target = _axis("4")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                _seed_obligation(
                    index,
                    token=30,
                    axis=target,
                    study_axis_identity="axis:" + "5" * 64,
                )
                self.assertTrue(effective_axis_resolution(index, _axis("6")).selectable)
                with self.assertRaisesRegex(
                    EffectiveAxisProjectionError,
                    "trial-to-Study-to-axis lineage",
                ):
                    audit_effective_axis_projection(index)

    def test_snapshot_deferred_axis_requires_typed_reopen_but_stays_visible(self) -> None:
        deferred_axis = _axis("9", status="deferred")
        open_axis = _axis("a")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                resolution = effective_axis_resolution(index, deferred_axis)
                self.assertIs(
                    resolution.effective_status,
                    EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
                )
                self.assertFalse(resolution.selectable)
                self.assertTrue(resolution.decision_option_eligible)
                self.assertTrue(resolution.requires_reopen)
                self.assertTrue(resolution.terminal_eligible)
                self.assertEqual(
                    selectable_axis_ids(index, (deferred_axis, open_axis)),
                    (open_axis["axis_id"],),
                )


if __name__ == "__main__":
    unittest.main()
