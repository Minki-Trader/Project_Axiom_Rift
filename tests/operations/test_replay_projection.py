from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import PermitAuthority
from axiom_rift.operations.effective_axis_projection import (
    effective_replay_axis_bindings,
)
from axiom_rift.operations.replay_projection import (
    ReplayAuthorityError,
    ReplayProjectionError,
    ReplayTransitionError,
    build_correction_plan,
    build_satisfaction_invalidation_plan,
    constraints_for_pending,
    initial_obligation_record,
    is_exact_replay_protocol_revision_selection,
    obligation_heads,
    prepare_disposition,
    prepare_execution_progress,
    prepare_scientific_change_return,
    prepare_satisfaction_invalidation,
    prepare_sibling_evidence_recertification,
    replay_evidence_record_ids,
    require_recorded_satisfaction,
    require_scientific_change_return_record,
    require_satisfaction,
    require_satisfaction_invalidation_record,
    require_study_execution_complete,
    satisfaction_record,
    validate_decision_selection,
    validate_replay_review_basis,
    validate_snapshot_scheduler_projection,
    with_scheduler_constraints,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayObligationStatus,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplaySatisfaction,
    derive_historical_replay_obligation,
)
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplaySatisfactionInvalidationAuditManifest,
    ReplaySatisfactionInvalidationAuditManifestV2,
)
from axiom_rift.research.validation_v2 import (
    multiplicity_family_registration_hash,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-MULTI-REPLAY"
DECISION_ID = "decision:" + "d" * 64
REPO_ROOT = Path(__file__).resolve().parents[2]


def _authenticated_transition_records(
    transition: IndexRecord,
    *,
    authority_sequence: int,
    event_kind: str,
    operation_id: str,
    result: dict[str, object],
) -> tuple[IndexRecord, IndexRecord, IndexRecord]:
    event_id = canonical_digest(
        domain="fixture-journal-event",
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
    journal_event = IndexRecord(
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
    )
    operation = IndexRecord(
        kind="operation",
        record_id=operation_id,
        subject="Mission:active",
        status="success",
        fingerprint=canonical_digest(
            domain="fixture-operation",
            payload={"event_kind": event_kind, "result": result},
        ),
        payload={"event_kind": event_kind, "result": result},
        **authority,
    )
    return journal_event, operation, replace(transition, **authority)


def _historical_executable_payload(token: int) -> dict[str, object]:
    return {
        "schema": "historical_fixture.v1",
        "source_contracts": [],
        "token": token,
    }


def _adjudication_payload(
    token: int,
    priority: ReplayPriority = ReplayPriority.P1,
) -> dict[str, object]:
    executable = _historical_executable_payload(token)
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": f"claim-{token}"}],
            "criteria": [{"criterion_id": f"criterion-{token}"}],
        },
        "audit_artifact_hash": f"{token + 10:064x}",
        "completion_record_id": f"{token + 20:064x}",
        "disposition": "replay_required",
        "executable_id": "executable:"
        + canonical_digest(domain="executable", payload=executable),
        "measurement_artifact_hash": f"{token + 40:064x}",
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": priority.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": f"{token + 50:064x}",
        "study_id": f"STU-{token:04d}",
        "validation_plan_hash": f"{token + 60:064x}",
    }


class MultiExecutableReplayProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = LocalIndex(Path(self.temporary.name) / "index.sqlite3")
        self.addCleanup(self.index.close)
        self.obligations = tuple(
            derive_historical_replay_obligation(
                governing_mission_id=MISSION_ID,
                historical_adjudication_id=(
                    f"historical-adjudication:{token:064x}"
                ),
                adjudication_payload=_adjudication_payload(token),
            )
            for token in range(1, 5)
        )
        self.affected_axis_id = "axis-historical-replay"
        self.affected_axis_identity = "axis:" + "a" * 64
        self.unrelated_axis_id = "axis-unrelated"
        self.unrelated_axis_identity = "axis:" + "b" * 64
        records: list[IndexRecord] = []
        for token, obligation in enumerate(self.obligations, start=1):
            historical_mission_id = f"MIS-HIST-{token:04d}"
            job_id = f"job:{token + 70:064x}"
            registration_study_id = (
                "STU-HIST-REGISTRATION-0001"
                if token == 1
                else obligation.original_study_id
            )
            registration_axis_id = (
                "axis-historical-registration"
                if token == 1
                else self.affected_axis_id
            )
            registration_axis_identity = (
                "axis:" + "d" * 64
                if token == 1
                else self.affected_axis_identity
            )
            registration_study_records = (
                (
                    IndexRecord(
                        kind="study-open",
                        record_id=registration_study_id,
                        subject=f"Study:{registration_study_id}",
                        status="closed",
                        fingerprint=f"{token + 81:064x}",
                        payload={
                            "mission_id": historical_mission_id,
                            "portfolio_axis_id": registration_axis_id,
                            "portfolio_axis_identity": (
                                registration_axis_identity
                            ),
                        },
                    ),
                )
                if token == 1
                else ()
            )
            records.extend(
                (
                    IndexRecord(
                        kind="study-open",
                        record_id=obligation.original_study_id,
                        subject=f"Study:{obligation.original_study_id}",
                        status="closed",
                        fingerprint=f"{token + 80:064x}",
                        payload={
                            "mission_id": historical_mission_id,
                            "portfolio_axis_id": self.affected_axis_id,
                            "portfolio_axis_identity": (
                                self.affected_axis_identity
                            ),
                        },
                    ),
                    *registration_study_records,
                    IndexRecord(
                        kind="trial",
                        record_id=obligation.original_executable_id,
                        subject=f"Batch:BAT-HIST-{token:04d}",
                        status="evaluated",
                        fingerprint=(
                            obligation.original_executable_id.removeprefix(
                                "executable:"
                            )
                        ),
                        payload={
                            "executable": _historical_executable_payload(token),
                            "mission_id": historical_mission_id,
                            "portfolio_axis_id": registration_axis_id,
                            "portfolio_axis_identity": (
                                registration_axis_identity
                            ),
                            "study_id": registration_study_id,
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
                            "study_id": obligation.original_study_id,
                            "spec": {
                                "evidence_subject": {
                                    "id": obligation.original_executable_id,
                                    "kind": "Executable",
                                }
                            },
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
                                "executable_id": (
                                    obligation.original_executable_id
                                )
                            },
                        },
                    ),
                    IndexRecord(
                        kind="study-close",
                        record_id=(
                            obligation.original_study_close_record_id
                        ),
                        subject=f"Study:{obligation.original_study_id}",
                        status="failed",
                        fingerprint=f"{token + 50:064x}",
                        payload=(
                            {}
                            if token == 1
                            else {"study_id": obligation.original_study_id}
                        ),
                    ),
                    IndexRecord(
                        kind="historical-scientific-adjudication",
                        record_id=obligation.historical_adjudication_id,
                        subject=f"Study:{obligation.original_study_id}",
                        status="replay_required",
                        fingerprint=f"{token:064x}",
                        payload=_adjudication_payload(token),
                    ),
                    initial_obligation_record(obligation),
                )
            )
        self.index.put_many(records)
        self.study = IndexRecord(
            kind="study-open",
            record_id="STU-MULTI-REPLAY",
            subject=f"Mission:{MISSION_ID}",
            status="open",
            fingerprint="a" * 64,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": sorted(
                    item.identity for item in self.obligations
                ),
            },
        )
        self.index.put(self.study)

    def _put_scheduler_snapshot(self, snapshot_id: str) -> None:
        self.index.put(
            IndexRecord(
                kind="portfolio-snapshot",
                record_id=snapshot_id,
                subject=f"Mission:{MISSION_ID}",
                status="current",
                fingerprint="c" * 64,
                payload={
                    "axes": [
                        {
                            "axis_id": self.affected_axis_id,
                            "axis_identity": self.affected_axis_identity,
                        },
                        {
                            "axis_id": self.unrelated_axis_id,
                            "axis_identity": self.unrelated_axis_identity,
                        },
                        {
                            "axis_id": "axis-completed-replay",
                            "axis_identity": "axis:" + "c" * 64,
                        },
                    ],
                    "mission_id": MISSION_ID,
                },
            )
        )

    def test_legacy_correction_plan_name_delegates_to_explicit_audit(self) -> None:
        expected = {"schema": "historical_replay_correction_plan.fixture"}
        with patch(
            "axiom_rift.operations.replay_projection."
            "build_explicit_historical_replay_correction_audit_plan",
            return_value=expected,
        ) as explicit_audit:
            actual = build_correction_plan(
                self.index,
                mission_id=MISSION_ID,
                adjudication_record_ids=("historical-adjudication:" + "a" * 64,),
                replay_study_id=self.study.record_id,
            )
        self.assertIs(actual, expected)
        explicit_audit.assert_called_once_with(
            self.index,
            mission_id=MISSION_ID,
            adjudication_record_ids=("historical-adjudication:" + "a" * 64,),
            replay_study_id=self.study.record_id,
        )

    @staticmethod
    def _executable_payload(
        reference: str | None = None,
        *,
        duplicate_declaration: bool = False,
    ) -> dict[str, object]:
        if reference is None:
            return {"schema": "ordinary_control_trial.v1"}
        declaration = {
            "spec": {
                "parameter_fields": ["historical_reference_executable_id"]
            }
        }
        manifests = [declaration]
        if duplicate_declaration:
            manifests.append(declaration)
        return {
            "component_manifests": manifests,
            "parameters": {"historical_reference_executable_id": reference},
            "schema": "multi_replay_trial_fixture.v1",
        }

    @staticmethod
    def _trial_record(
        *,
        study_id: str,
        executable_id: str,
        executable_payload: dict[str, object],
        obligation_ids: tuple[str, ...],
    ) -> IndexRecord:
        return IndexRecord(
            kind="trial",
            record_id=executable_id,
            subject="Batch:BAT-MULTI-REPLAY",
            status="evaluated",
            fingerprint=executable_id.removeprefix("executable:"),
            payload={
                "executable": executable_payload,
                "replay_obligation_ids": list(obligation_ids),
                "study_id": study_id,
            },
        )

    def _register_matching_trial(self, ordinal: int) -> str:
        obligation = self.obligations[ordinal - 1]
        executable_id = f"executable:{ordinal + 100:064x}"
        executable_payload = self._executable_payload(
            obligation.original_executable_id
        )
        matched, progress = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id=executable_id,
            executable_payload=executable_payload,
        )
        self.assertEqual(matched, (obligation.identity,))
        self.index.put_many(
            (
                *progress,
                self._trial_record(
                    study_id=self.study.record_id,
                    executable_id=executable_id,
                    executable_payload=executable_payload,
                    obligation_ids=matched,
                ),
            )
        )
        return executable_id

    def test_four_trial_family_advances_one_obligation_per_exact_manifest(self) -> None:
        unmatched, records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id="executable:" + "9" * 64,
            executable_payload=self._executable_payload(),
        )
        self.assertEqual(unmatched, ())
        self.assertEqual(records, [])

        with self.assertRaisesRegex(
            ReplayTransitionError, "not one typed component field"
        ):
            prepare_execution_progress(
                self.index,
                study_record=self.study,
                executable_id="executable:" + "8" * 64,
                executable_payload=self._executable_payload(
                    self.obligations[0].original_executable_id,
                    duplicate_declaration=True,
                ),
            )

        first_executable_id = self._register_matching_trial(1)
        duplicate, duplicate_records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id=first_executable_id,
            executable_payload=self._executable_payload(
                self.obligations[0].original_executable_id
            ),
        )
        self.assertEqual(duplicate, ())
        self.assertEqual(duplicate_records, [])

        for ordinal in (2, 3):
            self._register_matching_trial(ordinal)
        with self.assertRaisesRegex(
            ReplayTransitionError, "one exact trial per obligation"
        ):
            require_study_execution_complete(
                self.index,
                mission_id=MISSION_ID,
                study=self.study,
            )

        self._register_matching_trial(4)
        self.assertEqual(
            require_study_execution_complete(
                self.index,
                mission_id=MISSION_ID,
                study=self.study,
            ),
            tuple(self.study.payload["replay_obligation_ids"]),
        )
        post_family, post_family_records = prepare_execution_progress(
            self.index,
            study_record=self.study,
            executable_id="executable:" + "7" * 64,
            executable_payload={"schema": "post_family_control_trial.v1"},
        )
        self.assertEqual(post_family, ())
        self.assertEqual(post_family_records, [])

    def test_study_scientific_change_returns_whole_family_without_credit(
        self,
    ) -> None:
        study_id = "STU-SCIENTIFIC-CHANGE"
        batch_id = "batch:" + "b" * 64
        selected_ids = tuple(sorted(item.identity for item in self.obligations))

        def authoritative(record: IndexRecord, sequence: int) -> IndexRecord:
            return replace(
                record,
                authority_sequence=sequence,
                authority_event_id=f"{sequence:064x}",
                authority_offset=sequence * 100,
            )

        study = authoritative(
            IndexRecord(
                kind="study-open",
                record_id=study_id,
                subject=f"Study:{study_id}",
                status="open",
                fingerprint="9" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_decision_id": DECISION_ID,
                    "replay_obligation_ids": list(selected_ids),
                },
            ),
            10,
        )
        batch = authoritative(
            IndexRecord(
                kind="batch-open",
                record_id=batch_id,
                subject=f"Study:{study_id}",
                status="open",
                fingerprint="8" * 64,
                payload={},
            ),
            20,
        )
        self.index.put_many((study, batch))
        executable_ids: list[str] = []
        for ordinal, obligation in enumerate(self.obligations, start=1):
            executable_id = f"executable:{ordinal + 200:064x}"
            executable_ids.append(executable_id)
            executable = self._executable_payload(
                obligation.original_executable_id
            )
            matched, progress = prepare_execution_progress(
                self.index,
                study_record=study,
                executable_id=executable_id,
                executable_payload=executable,
            )
            sequence = 20 + ordinal
            self.index.put_many(
                (
                    authoritative(progress[0], sequence),
                    authoritative(
                        IndexRecord(
                            kind="trial",
                            record_id=executable_id,
                            subject=f"Batch:{batch_id}",
                            status="evaluated",
                            fingerprint=executable_id.removeprefix(
                                "executable:"
                            ),
                            payload={
                                "executable": executable,
                                "replay_obligation_ids": list(matched),
                                "study_id": study_id,
                            },
                        ),
                        sequence,
                    ),
                )
            )
        job_id = "job:" + "7" * 64
        disposition_hash = "6" * 64
        disposition_id = "5" * 64
        completion_id = "4" * 64
        batch_close_id = "3" * 64
        close_id = "2" * 64
        diagnosis_id = "diagnosis:" + "1" * 64
        resume_condition = (
            "admit a new Study with feasible registered semantics and "
            "distinct Executable identities"
        )
        engineering_disposition = {
            "basis_manifest_hash": "a" * 64,
            "cause_hash": "b" * 64,
            "disposition": "requires_scientific_change",
            "job_id": job_id,
            "rationale": "the registered scientific component must change",
            "repair_attempt_record_ids": [],
            "repair_id": None,
            "resume_condition": resume_condition,
            "schema": "engineering_failure_disposition.v1",
            "successor_scope": "study",
        }
        declaration = authoritative(
            IndexRecord(
                kind="job-declared",
                record_id=job_id,
                subject=f"Job:{job_id}",
                status="declared",
                fingerprint="d" * 64,
                payload={
                    "batch_id": batch_id,
                    "mission_id": MISSION_ID,
                    "spec": {
                        "evidence_subject": {
                            "id": executable_ids[-1],
                            "kind": "Executable",
                        }
                    },
                    "study_id": study_id,
                },
            ),
            30,
        )
        disposition = authoritative(
            IndexRecord(
                kind="engineering-failure-disposition",
                record_id=disposition_id,
                subject=f"Job:{job_id}",
                status="requires_scientific_change",
                fingerprint=disposition_hash,
                payload={
                    "disposition": engineering_disposition,
                    "disposition_hash": disposition_hash,
                    "job_id": job_id,
                    "repair_id": None,
                },
            ),
            31,
        )
        completion = authoritative(
            IndexRecord(
                kind="job-completed",
                record_id=completion_id,
                subject=f"Job:{job_id}",
                status="failed",
                fingerprint="c" * 64,
                payload={
                    "engineering_disposition": engineering_disposition,
                    "failure": {
                        "failure_kind": "engineering",
                        "repair_disposition_hash": disposition_hash,
                    },
                    "job_id": job_id,
                    "scientific": None,
                },
            ),
            32,
        )
        batch_close = authoritative(
            IndexRecord(
                kind="batch-close",
                record_id=batch_close_id,
                subject=f"Batch:{batch_id}",
                status="engineering_failure",
                fingerprint="b" * 64,
                payload={"outcome": "engineering_failure"},
            ),
            33,
        )
        close = authoritative(
            IndexRecord(
                kind="study-close",
                record_id=close_id,
                subject=f"Study:{study_id}",
                status="not_evaluable",
                fingerprint="a" * 64,
                payload={},
            ),
            34,
        )
        kpi = authoritative(
            IndexRecord(
                kind="study-kpi",
                record_id=study_id,
                subject=f"Study:{study_id}",
                status="not_evaluable",
                fingerprint="9" * 64,
                payload={
                    "completion_record_id": completion_id,
                    "outcome": "not_evaluable",
                    "source": "typed_engineering_failure_completion",
                    "study_id": study_id,
                    "unavailable_reason": "engineering_failure",
                },
            ),
            34,
        )
        diagnosis = authoritative(
            IndexRecord(
                kind="study-diagnosis",
                record_id=diagnosis_id,
                subject=f"Study:{study_id}",
                status="engineering_gap",
                fingerprint="8" * 64,
                payload={
                    "evidence_basis": [
                        {"kind": "batch-close", "record_id": batch_close_id},
                        {"kind": "batch-open", "record_id": batch_id},
                        {"kind": "job-completed", "record_id": completion_id},
                        {"kind": "study-close", "record_id": close_id},
                        {"kind": "study-kpi", "record_id": study_id},
                    ],
                    "evidence_state": "engineering_gap",
                    "mission_id": MISSION_ID,
                    "reopen_condition": resume_condition,
                    "schema": "study_diagnosis.v1",
                    "study_close_record_id": close_id,
                    "study_id": study_id,
                    "study_outcome": "not_evaluable",
                },
            ),
            35,
        )
        self.index.put_many(
            (
                declaration,
                disposition,
                completion,
                batch_close,
                close,
                kpi,
                diagnosis,
            )
        )
        next_action = {
            "kind": "resolve_historical_replay_obligations",
            "replay_obligation_ids": list(selected_ids),
            "resume_next_action": {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": "portfolio:" + "e" * 64,
                "study_diagnosis_id": diagnosis_id,
            },
            "study_diagnosis_id": diagnosis_id,
            "study_id": study_id,
        }

        records, constraints, result = prepare_scientific_change_return(
            self.index,
            mission_id=MISSION_ID,
            next_action=next_action,
            obligation_ids=selected_ids,
        )

        self.assertEqual(len(records), 4)
        self.assertTrue(all(record.status == "pending" for record in records))
        self.assertTrue(all(record.event_sequence == 3 for record in records))
        self.assertEqual(
            result["returned_replay_obligation_ids"],
            list(selected_ids),
        )
        for name in (
            "candidate_delta",
            "holdout_reveal_delta",
            "scientific_claim_delta",
            "scientific_failure_delta",
            "scientific_satisfaction_delta",
            "scientific_trial_delta",
            "terminal_credit_delta",
        ):
            self.assertEqual(result[name], 0)
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            list(selected_ids),
        )

        event_kind = (
            "historical_replay_obligations_"
            "returned_for_scientific_change"
        )
        journal, operation, first = _authenticated_transition_records(
            records[0],
            authority_sequence=36,
            event_kind=event_kind,
            operation_id="return-scientific-change",
            result=result,
        )
        authority = {
            "authority_sequence": first.authority_sequence,
            "authority_event_id": first.authority_event_id,
            "authority_offset": first.authority_offset,
        }
        committed = (first,) + tuple(
            replace(record, **authority) for record in records[1:]
        )
        self.index.put_many((journal, operation, *committed))
        first_obligation = next(
            item
            for item in self.obligations
            if item.identity == committed[0].payload["obligation_id"]
        )
        payload = require_scientific_change_return_record(
            self.index,
            obligation=first_obligation,
            record=committed[0],
        )
        self.assertEqual(payload["successor_scope"], "study")

    def test_mixed_disposition_is_one_exact_atomic_selected_transition(
        self,
    ) -> None:
        first_executable_id = self._register_matching_trial(1)
        second_executable_id = self._register_matching_trial(2)
        first, second = self.obligations[:2]
        diagnosis_id = "diagnosis:" + "a" * 64
        close_record_id = "b" * 64
        satisfaction = ReplaySatisfaction(
            obligation_id=first.identity,
            resolution_scope=ReplayResolutionScope.SCIENTIFIC,
            portfolio_decision_id=DECISION_ID,
            replay_study_id=self.study.record_id,
            replay_executable_id=first_executable_id,
            replay_study_close_record_id=close_record_id,
            study_diagnosis_id=diagnosis_id,
            satisfied_criterion_ids=first.criterion_ids,
            evidence_record_ids=("evidence-a",),
        )
        deferral = ReplayDeferral(
            obligation_id=second.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=diagnosis_id,
                subject_id=self.study.record_id,
            ),
            reason_codes=("selected_member_recomputation_partial",),
            resume_conditions=(
                ReplayResumeCondition(
                    kind=(
                        ReplayResumeConditionKind
                        .REGISTERED_DEVELOPMENT_MATERIAL
                    ),
                    protocol_id="python.source.fixture.v1",
                    original_executable_ids=(
                        first.original_executable_id,
                        second.original_executable_id,
                    ),
                    criterion_ids=second.criterion_ids,
                ),
            ),
            execution_binding=ReplayDeferralExecutionBinding(
                portfolio_decision_id=DECISION_ID,
                replay_study_id=self.study.record_id,
                replay_executable_id=second_executable_id,
                replay_study_close_record_id=close_record_id,
                study_diagnosis_id=diagnosis_id,
            ),
        )
        selected_ids = sorted((first.identity, second.identity))
        next_action = {
            "kind": "resolve_historical_replay_obligations",
            "replay_obligation_ids": selected_ids,
            "resume_next_action": {
                "kind": "portfolio_decision",
                "portfolio_snapshot_id": "portfolio:" + "c" * 64,
            },
            "study_diagnosis_id": diagnosis_id,
            "study_id": self.study.record_id,
        }
        patches = (
            patch(
                "axiom_rift.operations.replay_projection.require_satisfaction"
            ),
            patch(
                "axiom_rift.operations.replay_projection."
                "_require_resume_condition_surface"
            ),
            patch(
                "axiom_rift.operations.replay_projection."
                "_require_in_progress_deferral_basis"
            ),
        )
        with patches[0], patches[1], patches[2]:
            records, constraints, result = prepare_disposition(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                satisfactions=(satisfaction,),
                deferrals=(deferral,),
            )

        self.assertEqual(
            {
                record.payload["obligation_id"]: (
                    record.status,
                    record.payload["prior_status"],
                )
                for record in records
            },
            {
                first.identity: ("satisfied", "in_progress"),
                second.identity: ("deferred", "in_progress"),
            },
        )
        self.assertEqual(
            result,
            {
                "deferred_replay_obligation_ids": [second.identity],
                "effective_scope_overlay_ids": [],
                "satisfied_replay_obligation_ids": [first.identity],
            },
        )
        assert constraints is not None
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            sorted(item.identity for item in self.obligations[2:]),
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "exact next action",
        ):
            prepare_disposition(
                self.index,
                mission_id=MISSION_ID,
                next_action={**next_action, "replay_obligation_ids": [first.identity]},
                satisfactions=(satisfaction,),
                deferrals=(deferral,),
            )

    def test_selected_p0_family_admits_only_exact_frozen_p1_controls(self) -> None:
        payloads: list[dict[str, object]] = []
        obligations = []
        for token in range(11, 15):
            payload = deepcopy(
                _adjudication_payload(
                    token,
                    (
                        ReplayPriority.P0
                        if token == 14
                        else ReplayPriority.P1
                    ),
                )
            )
            payload["study_id"] = (
                "STU-9001" if token == 14 else "STU-9000"
            )
            payload["adjudication"]["claims"] = [  # type: ignore[index]
                {"claim_id": "family-claim"}
            ]
            payload["adjudication"]["criteria"] = [  # type: ignore[index]
                {"criterion_id": "family-criterion"}
            ]
            payloads.append(payload)
            obligations.append(
                derive_historical_replay_obligation(
                    governing_mission_id=MISSION_ID,
                    historical_adjudication_id=(
                        f"historical-adjudication:{token:064x}"
                    ),
                    adjudication_payload=payload,
                )
            )
        family_obligations = tuple(obligations)
        references = tuple(
            obligation.original_executable_id
            for obligation in family_obligations
        )
        family = HistoricalFamilySpec(
            original_study_id="STU-9000",
            original_batch_id="batch:" + "b" * 64,
            target_historical_executable_id=references[3],
            members=tuple(
                HistoricalMemberSpec(
                    ordinal=ordinal,
                    configuration_id=f"family-member-{ordinal}",
                    historical_reference_executable_id=reference,
                    parameters={"variant": ordinal},
                )
                for ordinal, reference in enumerate(references, start=1)
            ),
            controls=(
                ControlBinding(
                    subject_historical_executable_id=references[0],
                    opposite_historical_executable_id=references[1],
                    feature_historical_executable_ids=(references[2],),
                ),
                ControlBinding(
                    subject_historical_executable_id=references[1],
                    opposite_historical_executable_id=references[0],
                    feature_historical_executable_ids=(references[3],),
                ),
                ControlBinding(
                    subject_historical_executable_id=references[2],
                    opposite_historical_executable_id=references[3],
                    feature_historical_executable_ids=(references[0],),
                ),
                ControlBinding(
                    subject_historical_executable_id=references[3],
                    opposite_historical_executable_id=references[2],
                    feature_historical_executable_ids=(references[1],),
                ),
            ),
        )
        selected = family_obligations[3]
        authority = HistoricalFamilyAuthority(
            replay_obligation_id=selected.identity,
            family=family,
            reconstruction_source_path="records/family-fixture.json",
            reconstruction_source_sha256="f" * 64,
        )
        for obligation, payload in zip(
            family_obligations,
            payloads,
            strict=True,
        ):
            self.index.put_many(
                (
                    IndexRecord(
                        kind="historical-scientific-adjudication",
                        record_id=obligation.historical_adjudication_id,
                        subject=f"Study:{payload['study_id']}",
                        status="replay_required",
                        fingerprint=obligation.identity.removeprefix(
                            "historical-replay-obligation:"
                        ),
                        payload=payload,
                    ),
                    initial_obligation_record(obligation),
                )
            )
        self.index.put(
            IndexRecord(
                kind="historical-family-authority",
                record_id=authority.identity,
                subject=f"ReplayObligation:{selected.identity}",
                status="accepted",
                fingerprint=authority.identity.removeprefix(
                    "historical-family-authority:"
                ),
                payload=authority.to_identity_payload(),
            )
        )
        prospective_ids = tuple(
            f"executable:{token:064x}" for token in range(201, 205)
        )
        study = IndexRecord(
            kind="study-open",
            record_id="STU-9002",
            subject=f"Mission:{MISSION_ID}",
            status="open",
            fingerprint="e" * 64,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": [selected.identity],
                "semantic_proposal": {
                    "candidate_eligible": False,
                    "concurrent_family": family.manifest(),
                    "historical_family_authority_id": authority.identity,
                    "historical_family_identity": family.identity,
                    "historical_obligation_id": selected.identity,
                    "original_study_id": selected.original_study_id,
                },
            },
        )
        batch = IndexRecord(
            kind="batch-open",
            record_id="batch:" + "c" * 64,
            subject=f"Study:{study.record_id}",
            status="open",
            fingerprint="c" * 64,
            payload={
                "spec": {
                    "acceptance_profile": {
                        "concurrent_family": {
                            "evaluation_mode": "vectorized",
                            "executable_ids": list(prospective_ids),
                            "family_size": len(prospective_ids),
                            "schema": "concurrent_family_manifest.v1",
                        },
                        "historical_family_authority_id": authority.identity,
                        "historical_family_identity": family.identity,
                    }
                }
            },
        )

        control_ids, control_records = prepare_execution_progress(
            self.index,
            study_record=study,
            batch_record=batch,
            executable_id=prospective_ids[0],
            executable_payload=self._executable_payload(references[0]),
        )
        self.assertEqual(control_ids, ())
        self.assertEqual(control_records, [])

        with self.assertRaisesRegex(
            ReplayTransitionError,
            "unselected Mission replay obligation",
        ):
            prepare_execution_progress(
                self.index,
                study_record=study,
                batch_record=None,
                executable_id=prospective_ids[0],
                executable_payload=self._executable_payload(references[0]),
            )

        selected_ids, selected_records = prepare_execution_progress(
            self.index,
            study_record=study,
            batch_record=batch,
            executable_id=prospective_ids[3],
            executable_payload=self._executable_payload(references[3]),
        )
        self.assertEqual(selected_ids, (selected.identity,))
        self.assertEqual(len(selected_records), 1)

    def test_obligation_heads_are_mission_scoped_and_preserve_exact_heads(
        self,
    ) -> None:
        expected_heads: dict[str, IndexRecord] = {
            self.obligations[-1].identity: initial_obligation_record(
                self.obligations[-1]
            )
        }
        for ordinal, (obligation, status) in enumerate(
            zip(
                self.obligations[:3],
                (
                    ReplayObligationStatus.IN_PROGRESS,
                    ReplayObligationStatus.SATISFIED,
                    ReplayObligationStatus.DEFERRED,
                ),
                strict=True,
            ),
            start=1,
        ):
            head = IndexRecord(
                kind=(
                    "historical-replay-obligation-progress"
                    if status is ReplayObligationStatus.IN_PROGRESS
                    else "historical-replay-obligation-resolution"
                ),
                record_id=f"mission-scoped-head-{ordinal}",
                subject=f"Mission:{MISSION_ID}",
                status=status.value,
                fingerprint=f"{ordinal + 500:064x}",
                payload={"obligation_id": obligation.identity},
                event_stream=(
                    "historical-replay-obligation:" + obligation.identity
                ),
                event_sequence=2,
                authority_sequence=ordinal + 100,
                authority_event_id=f"{ordinal + 100:064x}",
                authority_offset=ordinal * 1_000,
            )
            self.index.put(head)
            expected_heads[obligation.identity] = head

        unrelated = IndexRecord(
            kind="historical-replay-obligation",
            record_id="historical-replay-obligation:" + "f" * 64,
            subject="Mission:MIS-UNRELATED",
            status=ReplayObligationStatus.PENDING.value,
            fingerprint="f" * 64,
            payload={"malformed": "must not enter another Mission projection"},
        )
        self.index.put(unrelated)

        class MissionScopedProbe:
            def __init__(self, index: LocalIndex) -> None:
                self.index = index
                self.subject_status_calls: list[tuple[str, str]] = []

            def records_by_subject_status(
                self,
                subject: str,
                status: str,
            ) -> tuple[IndexRecord, ...]:
                self.subject_status_calls.append((subject, status))
                return self.index.records_by_subject_status(subject, status)

            def records_by_kind(self, _kind: str) -> tuple[IndexRecord, ...]:
                raise AssertionError("obligation heads must not scan a global kind")

            def get(self, kind: str, record_id: str) -> IndexRecord | None:
                return self.index.get(kind, record_id)

            def event_head(self, stream: str):
                return self.index.event_head(stream)

        probe = MissionScopedProbe(self.index)
        heads = obligation_heads(probe, mission_id=MISSION_ID)  # type: ignore[arg-type]

        self.assertEqual(
            probe.subject_status_calls,
            [
                (
                    f"Mission:{MISSION_ID}",
                    ReplayObligationStatus.PENDING.value,
                )
            ],
        )
        self.assertEqual(
            [obligation.identity for obligation, _head in heads],
            sorted(item.identity for item in self.obligations),
        )
        self.assertEqual(
            {obligation.identity: head for obligation, head in heads},
            expected_heads,
        )
        self.assertEqual(
            {
                head.status
                for _obligation, head in heads
            },
            {
                ReplayObligationStatus.PENDING.value,
                ReplayObligationStatus.IN_PROGRESS.value,
                ReplayObligationStatus.SATISFIED.value,
                ReplayObligationStatus.DEFERRED.value,
            },
        )

    def test_obligation_heads_keep_current_head_fail_closed(self) -> None:
        obligation = self.obligations[0]
        self.index.put(
            IndexRecord(
                kind="historical-replay-obligation-resolution",
                record_id="malformed-current-replay-head",
                subject=f"Mission:{MISSION_ID}",
                status="invalid-status",
                fingerprint="f" * 64,
                payload={"obligation_id": obligation.identity},
                event_stream=(
                    "historical-replay-obligation:" + obligation.identity
                ),
                event_sequence=2,
            )
        )
        with self.assertRaisesRegex(
            ReplayProjectionError,
            "stream head is malformed",
        ):
            obligation_heads(self.index, mission_id=MISSION_ID)

    def test_matching_obligation_cannot_move_to_another_study(self) -> None:
        self._register_matching_trial(1)
        other_study = IndexRecord(
            kind="study-open",
            record_id="STU-OTHER-REPLAY",
            subject=f"Mission:{MISSION_ID}",
            status="open",
            fingerprint="b" * 64,
            payload={
                "mission_id": MISSION_ID,
                "portfolio_decision_id": DECISION_ID,
                "replay_obligation_ids": [self.obligations[0].identity],
            },
        )
        with self.assertRaisesRegex(
            ReplayTransitionError, "already bound to another trial or Study"
        ):
            prepare_execution_progress(
                self.index,
                study_record=other_study,
                executable_id="executable:" + "6" * 64,
                executable_payload=self._executable_payload(
                    self.obligations[0].original_executable_id
                ),
            )

    def test_scheduler_exposes_only_p0_while_any_p0_is_pending(self) -> None:
        p1 = self.obligations[0]
        p0 = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=(
                "historical-adjudication:" + "f" * 64
            ),
            adjudication_payload=_adjudication_payload(
                99,
                ReplayPriority.P0,
            ),
        )
        constraints = constraints_for_pending((p1, p0))
        assert constraints is not None
        self.assertEqual(constraints["required_replay_priority"], "p0")
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            [p0.identity],
        )

    def test_p0_pending_keeps_unbound_scientific_work_blocked(self) -> None:
        payload = _adjudication_payload(1, ReplayPriority.P0)
        p0 = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=(
                "historical-adjudication:" + "f" * 64
            ),
            adjudication_payload=payload,
        )
        self.index.put_many(
            (
                IndexRecord(
                    kind="historical-scientific-adjudication",
                    record_id=p0.historical_adjudication_id,
                    subject=f"Study:{p0.original_study_id}",
                    status="replay_required",
                    fingerprint="f" * 64,
                    payload=payload,
                ),
                initial_obligation_record(p0),
            )
        )
        snapshot_id = "portfolio:" + "d" * 64
        self._put_scheduler_snapshot(snapshot_id)
        constraints = constraints_for_pending((*self.obligations, p0))
        assert constraints is not None
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "cannot bypass the highest-priority replay queue",
        ):
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action={
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": snapshot_id,
                    **constraints,
                },
                replay_obligation_ids=(),
                action="deepen",
                target_axis_id=self.unrelated_axis_id,
                work_actions=frozenset(
                    {
                        "complementary_sleeve",
                        "contrast",
                        "deepen",
                        "recombine",
                        "rotate",
                        "synthesize",
                    }
                ),
            )

    def test_p1_pending_allows_unrelated_forest_work_without_selection(
        self,
    ) -> None:
        snapshot_id = "portfolio:" + "e" * 64
        self._put_scheduler_snapshot(snapshot_id)
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        next_action = {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": snapshot_id,
            **constraints,
        }
        work_actions = frozenset(
            {
                "complementary_sleeve",
                "contrast",
                "deepen",
                "recombine",
                "rotate",
                "synthesize",
            }
        )
        for action in (
            *sorted(work_actions),
            "new_mechanism",
            "preserve",
            "prune",
        ):
            with self.subTest(action=action):
                self.assertEqual(
                    validate_decision_selection(
                        self.index,
                        mission_id=MISSION_ID,
                        next_action=next_action,
                        replay_obligation_ids=(),
                        action=action,
                        target_axis_id=self.unrelated_axis_id,
                        work_actions=work_actions,
                    ),
                    constraints,
                )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "only exact bound work or unrelated bounded forest work",
        ):
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(),
                action="caller_boolean_bypass",
                target_axis_id=self.unrelated_axis_id,
                work_actions=work_actions,
            )

    def test_selected_p1_requires_exact_pending_obligation_binding(self) -> None:
        snapshot_id = "portfolio:" + "1" * 64
        self._put_scheduler_snapshot(snapshot_id)
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        next_action = {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": snapshot_id,
            **constraints,
        }
        work_actions = frozenset({"deepen"})
        selected = self.obligations[0].identity
        self.assertEqual(
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(selected,),
                action="deepen",
                target_axis_id=self.unrelated_axis_id,
                work_actions=work_actions,
            ),
            constraints,
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "non-pending replay obligation",
        ):
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(
                    "historical-replay-obligation:" + "0" * 64,
                ),
                action="deepen",
                target_axis_id=self.unrelated_axis_id,
                work_actions=work_actions,
            )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "not sorted and unique",
        ):
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(selected, selected),
                action="deepen",
                target_axis_id=self.unrelated_axis_id,
                work_actions=work_actions,
            )

    def test_exact_protocol_revision_can_structurally_exit_prior_diagnosis(
        self,
    ) -> None:
        obligation_id = self.obligations[0].identity
        constraints = {
            "pending_replay_obligation_ids": [obligation_id],
            "required_replay_priority": "p0",
        }
        self.assertTrue(
            is_exact_replay_protocol_revision_selection(
                constraints=constraints,
                selected_obligation_ids=(obligation_id,),
                action="revise_protocol",
                protocol_revision_obligation_id=obligation_id,
            )
        )
        invalid_cases = (
            {
                "selected_obligation_ids": (),
            },
            {
                "action": "deepen",
            },
            {
                "protocol_revision_obligation_id": (
                    "historical-replay-obligation:" + "0" * 64
                ),
            },
            {
                "constraints": {
                    "pending_replay_obligation_ids": [obligation_id],
                    "required_replay_priority": "caller_priority",
                },
            },
        )
        defaults = {
            "constraints": constraints,
            "selected_obligation_ids": (obligation_id,),
            "action": "revise_protocol",
            "protocol_revision_obligation_id": obligation_id,
        }
        for override in invalid_cases:
            with self.subTest(override=override):
                self.assertFalse(
                    is_exact_replay_protocol_revision_selection(
                        **{**defaults, **override}
                    )
                )

    def test_quant_team_review_considers_p1_without_forcing_allocation(self) -> None:
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        first = self.obligations[0].identity
        second = self.obligations[1].identity

        validate_replay_review_basis(
            constraints=constraints,
            selected_obligation_ids=(),
            review_basis={
                ("portfolio-snapshot", "portfolio:" + "1" * 64),
                ("historical-replay-obligation", first),
            },
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "omits the highest-priority replay opportunity",
        ):
            validate_replay_review_basis(
                constraints=constraints,
                selected_obligation_ids=(),
                review_basis={
                    ("portfolio-snapshot", "portfolio:" + "1" * 64),
                },
            )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "omits its selected replay-obligation basis",
        ):
            validate_replay_review_basis(
                constraints=constraints,
                selected_obligation_ids=(first, second),
                review_basis={
                    ("historical-replay-obligation", first),
                },
            )
        validate_replay_review_basis(
            constraints=constraints,
            selected_obligation_ids=(first, second),
            review_basis={
                ("historical-replay-obligation", first),
                ("historical-replay-obligation", second),
            },
        )

    def test_p1_pending_blocks_unbound_work_on_exact_affected_axis(self) -> None:
        snapshot_id = "portfolio:" + "2" * 64
        self._put_scheduler_snapshot(snapshot_id)
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        next_action = {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": snapshot_id,
            **constraints,
        }
        work_actions = frozenset(
            {
                "complementary_sleeve",
                "contrast",
                "deepen",
                "recombine",
                "rotate",
                "synthesize",
            }
        )
        for action in (
            *sorted(work_actions),
            "new_mechanism",
            "preserve",
            "prune",
        ):
            with self.subTest(action=action):
                with self.assertRaisesRegex(
                    ReplayTransitionError,
                    "blocks unbound work on its affected axis",
                ):
                    validate_decision_selection(
                        self.index,
                        mission_id=MISSION_ID,
                        next_action=next_action,
                        replay_obligation_ids=(),
                        action=action,
                        target_axis_id=self.affected_axis_id,
                        work_actions=work_actions,
                    )

    def test_p1_unrelated_work_fails_closed_on_forged_original_lineage(
        self,
    ) -> None:
        obligation = self.obligations[0]
        completion = self.index.get(
            "job-completed", obligation.original_completion_record_id
        )
        assert completion is not None
        declaration = self.index.get(
            "job-declared", completion.payload["job_id"]
        )
        assert declaration is not None
        original_get = self.index.get

        def forged_get(kind: str, record_id: str) -> IndexRecord | None:
            record = original_get(kind, record_id)
            if kind == "job-declared" and record_id == declaration.record_id:
                assert record is not None
                return replace(
                    record,
                    subject="Job:swapped-lineage-authority",
                )
            return record

        snapshot_id = "portfolio:" + "3" * 64
        self._put_scheduler_snapshot(snapshot_id)
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        with patch.object(self.index, "get", side_effect=forged_get):
            with self.assertRaisesRegex(
                ReplayProjectionError,
                "affected-axis lineage is malformed or ambiguous",
            ):
                validate_decision_selection(
                    self.index,
                    mission_id=MISSION_ID,
                    next_action={
                        "kind": "portfolio_decision",
                        "portfolio_snapshot_id": snapshot_id,
                        **constraints,
                    },
                    replay_obligation_ids=(),
                    action="deepen",
                    target_axis_id=self.unrelated_axis_id,
                    work_actions=frozenset({"deepen"}),
                )

    def test_diagnosis_cleanup_may_dispose_exact_axis_with_pending_replays(
        self,
    ) -> None:
        axis_id = self.affected_axis_id
        snapshot_id = "portfolio:" + "7" * 64
        diagnosis_id = "diagnosis:" + "8" * 64
        self.index.put(
            IndexRecord(
                kind="study-diagnosis",
                record_id=diagnosis_id,
                subject="Study:STU-COMPLETED-REPLAY",
                status="supported_requires_confirmation",
                fingerprint="8" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_axis_id": axis_id,
                    "portfolio_snapshot_id": snapshot_id,
                },
            )
        )
        constraints = constraints_for_pending(self.obligations)
        assert constraints is not None
        self._put_scheduler_snapshot(snapshot_id)
        next_action = {
            "kind": "portfolio_decision",
            **constraints,
            "portfolio_snapshot_id": snapshot_id,
            "study_diagnosis_id": diagnosis_id,
        }
        work_actions = frozenset(
            {"contrast", "deepen", "recombine", "rotate", "synthesize"}
        )

        self.assertEqual(
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(),
                action="preserve",
                target_axis_id=axis_id,
                work_actions=work_actions,
            ),
            constraints,
        )
        snapshot_action = with_scheduler_constraints(
            {
                "action": "preserve",
                "decision_id": "decision:" + "9" * 64,
                "kind": "record_portfolio_snapshot",
            },
            constraints,
        )
        self.assertEqual(
            {
                name: snapshot_action[name]
                for name in (
                    "pending_replay_obligation_ids",
                    "required_replay_priority",
                )
            },
            constraints,
        )
        self.assertTrue(
            validate_snapshot_scheduler_projection(
                next_action={
                    "action": "preserve",
                    "decision_id": "decision:" + "9" * 64,
                    "kind": "record_portfolio_snapshot",
                },
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        )
        self.assertFalse(
            validate_snapshot_scheduler_projection(
                next_action=snapshot_action,
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "Portfolio mutation replay scheduler authority is stale",
        ):
            validate_snapshot_scheduler_projection(
                next_action={
                    "action": "new_mechanism",
                    "decision_id": "decision:" + "9" * 64,
                    "kind": "record_portfolio_snapshot",
                },
                decision_payload={
                    "scheduler_constraints": constraints,
                    "study_diagnosis_id": diagnosis_id,
                },
                constraints=constraints,
            )
        self.assertEqual(
            validate_decision_selection(
                self.index,
                mission_id=MISSION_ID,
                next_action=next_action,
                replay_obligation_ids=(),
                action="prune",
                target_axis_id="axis-unrelated",
                work_actions=work_actions,
            ),
            constraints,
        )


class MultiplicityReplaySatisfactionTests(unittest.TestCase):
    FAMILY_ID = "family:exact-four-member-replay"
    BATCH_ID = "batch:" + "b" * 64
    STUDY_ID = "STU-MULTIPLICITY-REPLAY"
    VALIDATOR_ID = "validator:" + "f" * 64

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = LocalIndex(Path(self.temporary.name) / "index.sqlite3")
        self.addCleanup(self.index.close)
        self.authority_sequence = 10_000

    def _seed(
        self,
        *,
        recorded_family_size: int = 4,
        recorded_adjusted_pvalue_ppm: int = 20_000,
        recorded_alpha_ppm: int = 100_000,
        paired_family_size: int = 2,
        mismatch_member_family_id: int | None = None,
        target_batch_id: str | None = None,
        omit_member_completion: int | None = None,
        wrong_registration_member: int | None = None,
        forged_registration_hash_member: int | None = None,
        unrelated_registration_member: int | None = None,
        omit_registration_member: int | None = None,
        reverse_registration_order: bool = False,
        project_registration: bool = True,
        project_durable_batch_binding: bool = False,
        durable_batch_binding_mutation: str | None = None,
        historical_reference_by_member: dict[int, str] | None = None,
        project_batch_stream: bool = False,
    ):
        historical_payload = {
            "adjudication": {
                "candidate_eligible": False,
                "claims": [{"claim_id": "selection-aware-evidence"}],
                "criteria": [
                    {
                        "claim_id": "selection-aware-evidence",
                        "criterion_id": "D02-opposite-sign-uncertainty",
                        "decision_role": "multiplicity",
                        "metric": "opposite_sign_pvalue_upper_ppm",
                        "operator": "le",
                        "threshold": 100_000,
                    },
                    {
                        "claim_id": "selection-aware-evidence",
                        "criterion_id": "E01-familywise-selection",
                        "decision_role": "multiplicity",
                        "metric": "selection_aware_pvalue_ppm",
                        "operator": "le",
                        "threshold": 100_000,
                    }
                ],
            },
            "audit_artifact_hash": "1" * 64,
            "completion_record_id": "2" * 64,
            "disposition": "replay_required",
            "executable_id": "executable:"
            + canonical_digest(
                domain="executable",
                payload={"schema": "historical_fixture.v1"},
            ),
            "measurement_artifact_hash": "4" * 64,
            "reason_codes": ["missing_exact_uncertainty"],
            "replay_priority": ReplayPriority.P1.value,
            "schema": "historical_scientific_adjudication.v2",
            "study_close_record_id": "5" * 64,
            "study_id": "STU-HIST-MULTIPLICITY",
            "validation_plan_hash": "6" * 64,
        }
        obligation = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id="historical-adjudication:" + "7" * 64,
            adjudication_payload=historical_payload,
        )
        decision_id = "decision:" + "8" * 64
        family_ids = tuple(
            f"executable:{ordinal:064x}" for ordinal in range(101, 105)
        )
        concurrent_family = {
            "evaluation_mode": "sequential",
            "executable_ids": list(family_ids),
            "family_size": 4,
            "schema": "concurrent_family_manifest.v1",
        }
        target_id = family_ids[0]
        observed_criteria = [
            {
                **criterion,
                "comparison_state": "passed",
                "scientific_state": "supported",
                "value": 12_000 if ordinal == 0 else 20_000,
            }
            for ordinal, criterion in enumerate(
                historical_payload["adjudication"]["criteria"]
            )
        ]
        records: list[IndexRecord] = [
            IndexRecord(
                kind="historical-scientific-adjudication",
                record_id=obligation.historical_adjudication_id,
                subject="Study:STU-HIST-MULTIPLICITY",
                status="replay_required",
                fingerprint="7" * 64,
                payload=historical_payload,
            ),
            IndexRecord(
                kind="portfolio-decision",
                record_id=decision_id,
                subject=f"Mission:{MISSION_ID}",
                status="synthesize",
                fingerprint="8" * 64,
                payload={"replay_obligation_ids": [obligation.identity]},
            ),
            IndexRecord(
                kind="study-open",
                record_id=self.STUDY_ID,
                subject=f"Mission:{MISSION_ID}",
                status="open",
                fingerprint="a" * 64,
                payload={
                    "mission_id": MISSION_ID,
                    "portfolio_decision_id": decision_id,
                    "replay_obligation_ids": [obligation.identity],
                },
            ),
            IndexRecord(
                kind="batch-open",
                record_id=self.BATCH_ID,
                subject=f"Study:{self.STUDY_ID}",
                status="open",
                fingerprint="b" * 64,
                payload={
                    "spec": {
                        "acceptance_profile": {
                            "concurrent_family": concurrent_family
                        }
                    }
                },
                **(
                    {
                        "event_stream": f"study-batches:{self.STUDY_ID}",
                        "event_sequence": 1,
                    }
                    if project_batch_stream
                    else {}
                ),
            ),
        ]
        completion_ids: list[str] = []
        evidence = EvidenceStore(self.index.path.parent / "evidence")
        for ordinal, executable_id in enumerate(family_ids, start=1):
            job_id = f"job:{ordinal + 200:064x}"
            completion_id = f"{ordinal + 300:064x}"
            registered_members = tuple(sorted(family_ids))
            if reverse_registration_order:
                registered_members = tuple(reversed(registered_members))
            if recorded_family_size != len(registered_members):
                registered_members = tuple(
                    sorted(
                        (
                            executable_id,
                            *(
                                f"executable:{value:064x}"
                                for value in range(
                                    701,
                                    700 + recorded_family_size,
                                )
                            ),
                        )
                    )
                )
            if wrong_registration_member == ordinal:
                registered_members = tuple(
                    sorted(
                        (
                            executable_id,
                            *(f"executable:{value:064x}" for value in range(501, 504)),
                        )
                    )
                )
            selection_family_id = (
                "family:mismatched-selection"
                if mismatch_member_family_id == ordinal
                else self.FAMILY_ID
            )
            registration_member_id = executable_id
            if unrelated_registration_member == ordinal:
                registration_member_id = next(
                    item for item in registered_members if item != executable_id
                )
            registration_hash = multiplicity_family_registration_hash(
                family_id=selection_family_id,
                alpha_ppm=100_000,
                method="synchronized_max_moving_block_familywise.v1",
                ordered_member_ids=registered_members,
            )
            if forged_registration_hash_member == ordinal:
                registration_hash = "0" * 64
            registration = {
                "alpha_ppm": 100_000,
                "criterion_id": "E01-familywise-selection",
                "family_id": selection_family_id,
                "family_registration_hash": registration_hash,
                "family_size": len(registered_members),
                "member_id": registration_member_id,
                "method": "synchronized_max_moving_block_familywise.v1",
                "ordered_member_ids": list(registered_members),
            }
            registrations = (
                [] if omit_registration_member == ordinal else [registration]
            )
            durable_batch_binding = None
            if project_durable_batch_binding:
                binding_payload = {
                    "batch_id": self.BATCH_ID,
                    "concurrent_family_identity": "concurrent-family:"
                    + canonical_digest(
                        domain="concurrent-family-manifest",
                        payload=concurrent_family,
                    ),
                    "criterion_id": "E01-familywise-selection",
                    "executable_id": executable_id,
                    "family_id": registration["family_id"],
                    "family_registration_hash": registration[
                        "family_registration_hash"
                    ],
                    "family_size": len(family_ids),
                    "ordered_member_ids": list(family_ids),
                    "schema": "scientific_multiplicity_batch_binding.v1",
                }
                if ordinal == 1:
                    if durable_batch_binding_mutation == "missing":
                        binding_payload = None
                    elif durable_batch_binding_mutation == "wrong_batch":
                        binding_payload["batch_id"] = "batch:" + "0" * 64
                    elif durable_batch_binding_mutation == "reordered":
                        binding_payload["ordered_member_ids"] = list(
                            reversed(family_ids)
                        )
                    elif durable_batch_binding_mutation == "extra":
                        binding_payload["ordered_member_ids"] = [
                            *family_ids,
                            "executable:" + "9" * 64,
                        ]
                        binding_payload["family_size"] = 5
                    elif durable_batch_binding_mutation == "missing_member":
                        binding_payload["ordered_member_ids"] = list(
                            family_ids[:-1]
                        )
                        binding_payload["family_size"] = 3
                    elif durable_batch_binding_mutation == "wrong_subject":
                        binding_payload["executable_id"] = family_ids[1]
                if binding_payload is not None:
                    durable_batch_binding = {
                        **binding_payload,
                        "binding_hash": canonical_digest(
                            domain="scientific-multiplicity-batch-binding",
                            payload=binding_payload,
                        ),
                    }
            plan = evidence.finalize(
                canonical_bytes(
                    {
                        "adjudication_profile": {
                            "multiplicity": registrations,
                            "schema": "scientific_adjudication_profile.v1",
                        },
                        "executable_id": executable_id,
                        "schema": "scientific_validation_plan.v2",
                    }
                )
            )
            plan_hash = plan.sha256
            executable = {
                "component_manifests": [],
                "parameters": {},
                "schema": "multiplicity_replay_fixture.v1",
            }
            historical_reference = (
                obligation.original_executable_id
                if executable_id == target_id
                else (historical_reference_by_member or {}).get(ordinal)
            )
            if historical_reference is not None:
                executable["component_manifests"] = [
                    {
                        "spec": {
                            "parameter_fields": [
                                "historical_reference_executable_id"
                            ]
                        }
                    }
                ]
                executable["parameters"][
                    "historical_reference_executable_id"
                ] = historical_reference
            records.extend(
                (
                    IndexRecord(
                        kind="trial",
                        record_id=executable_id,
                        subject="Batch:BAT-MULTIPLICITY-REPLAY",
                        status="evaluated",
                        fingerprint=executable_id.removeprefix("executable:"),
                        payload={
                            "executable": executable,
                            "replay_obligation_ids": [obligation.identity],
                            "study_id": self.STUDY_ID,
                        },
                        **(
                            {
                                "event_stream": (
                                    f"batch-trials:{self.BATCH_ID}"
                                ),
                                "event_sequence": ordinal,
                            }
                            if project_batch_stream
                            else {}
                        ),
                    ),
                    IndexRecord(
                        kind="job-declared",
                        record_id=job_id,
                        subject=f"Job:{job_id}",
                        status="declared",
                        fingerprint=f"{ordinal + 200:064x}",
                        payload={
                            "batch_id": (
                                target_batch_id
                                if executable_id == target_id
                                and target_batch_id is not None
                                else self.BATCH_ID
                            ),
                            "mission_id": MISSION_ID,
                            "study_id": self.STUDY_ID,
                            **(
                                {
                                    "source_closure_authority": {
                                        "schema": "fixture_source_authority.v1"
                                    }
                                }
                                if project_durable_batch_binding
                                else {}
                            ),
                            "spec": {
                                "evidence_subject": {
                                    "id": executable_id,
                                    "kind": "Executable",
                                },
                                "scientific_binding": {
                                    "validation_plan_hash": plan_hash,
                                    "validator_id": self.VALIDATOR_ID,
                                },
                            },
                        },
                    ),
                    IndexRecord(
                        kind="job-completed",
                        record_id=completion_id,
                        subject=f"Job:{job_id}",
                        status="success",
                        fingerprint=f"{ordinal + 300:064x}",
                        payload={
                            "job_id": job_id,
                            "output_classes": {
                                "validation-plan.json": "durable_evidence"
                            },
                            "outputs": {"validation-plan.json": plan_hash},
                            "scientific": {
                                "adjudication": {
                                    "criteria": [
                                        dict(item) for item in observed_criteria
                                    ],
                                    "evaluable": True,
                                    "invalid_metrics": [],
                                    "multiplicity": [
                                        {
                                            "adjusted_pvalue_ppm": 12_000,
                                            "alpha_ppm": recorded_alpha_ppm,
                                            "criterion_id": (
                                                "D02-opposite-sign-uncertainty"
                                            ),
                                            "family_id": (
                                                f"family:paired-controls-{ordinal}"
                                            ),
                                            "family_size": paired_family_size,
                                            "method": (
                                                "synchronized_max_moving_block_"
                                                "familywise.v1"
                                            ),
                                            "raw_pvalue_ppm": 6_000,
                                        },
                                        {
                                            "adjusted_pvalue_ppm": (
                                                recorded_adjusted_pvalue_ppm
                                            ),
                                            "alpha_ppm": 100_000,
                                            "criterion_id": (
                                                "E01-familywise-selection"
                                            ),
                                            "family_id": (
                                                "family:mismatched-selection"
                                                if mismatch_member_family_id
                                                == ordinal
                                                else self.FAMILY_ID
                                            ),
                                            "family_size": recorded_family_size,
                                            "method": (
                                                "synchronized_max_moving_block_"
                                                "familywise.v1"
                                            ),
                                            "raw_pvalue_ppm": 10_000,
                                        },
                                    ],
                                    "schema": "scientific_adjudication.v1",
                                },
                                "candidate_eligible": False,
                                "executable_id": executable_id,
                                **(
                                    {
                                        "multiplicity_registrations": (
                                            registrations
                                        )
                                    }
                                    if project_registration
                                    else {}
                                ),
                                **(
                                    {
                                        "multiplicity_batch_binding": (
                                            durable_batch_binding
                                        )
                                    }
                                    if durable_batch_binding is not None
                                    else {}
                                ),
                                "scientific_eligible": True,
                                "validation_plan_hash": plan_hash,
                                "validation_trace": {
                                    "declared_artifact_count": 2,
                                    "opened_artifact_count": 2,
                                    "validator_id": self.VALIDATOR_ID,
                                },
                                "validator_id": self.VALIDATOR_ID,
                            },
                        },
                    ),
                )
            )
            if omit_member_completion != ordinal:
                completion_ids.append(completion_id)
        batch_close_id = "c" * 64
        study_close_id = "d" * 64
        diagnosis_id = "diagnosis:" + "e" * 64
        records.extend(
            (
                IndexRecord(
                    kind="batch-close",
                    record_id=batch_close_id,
                    subject=f"Batch:{self.BATCH_ID}",
                    status="completed",
                    fingerprint="c" * 64,
                    payload={"outcome": "completed"},
                ),
                IndexRecord(
                    kind="study-close",
                    record_id=study_close_id,
                    subject=f"Study:{self.STUDY_ID}",
                    status="preserved",
                    fingerprint="d" * 64,
                    payload={"outcome": "preserved"},
                ),
                IndexRecord(
                    kind="study-diagnosis",
                    record_id=diagnosis_id,
                    subject=f"Study:{self.STUDY_ID}",
                    status="supported_requires_confirmation",
                    fingerprint="e" * 64,
                    payload={
                        "evidence_basis": [
                            {"kind": "batch-open", "record_id": self.BATCH_ID},
                            {
                                "kind": "batch-close",
                                "record_id": batch_close_id,
                            },
                            *(
                                {
                                    "kind": "job-completed",
                                    "record_id": completion_id,
                                }
                                for completion_id in completion_ids
                            ),
                            {
                                "kind": "study-close",
                                "record_id": study_close_id,
                            },
                        ],
                        "study_close_record_id": study_close_id,
                        "study_id": self.STUDY_ID,
                    },
                ),
            )
        )
        self.index.put_many(records)
        diagnosis = self.index.get("study-diagnosis", diagnosis_id)
        close = self.index.get("study-close", study_close_id)
        trial = self.index.get("trial", target_id)
        assert diagnosis is not None and close is not None and trial is not None
        satisfaction = ReplaySatisfaction(
            obligation_id=obligation.identity,
            resolution_scope=ReplayResolutionScope.SCIENTIFIC,
            portfolio_decision_id=decision_id,
            replay_study_id=self.STUDY_ID,
            replay_executable_id=target_id,
            replay_study_close_record_id=study_close_id,
            study_diagnosis_id=diagnosis_id,
            satisfied_criterion_ids=obligation.criterion_ids,
            evidence_record_ids=replay_evidence_record_ids(
                diagnosis=diagnosis,
                close_record=close,
                trial=trial,
            ),
        )
        return obligation, satisfaction

    def _require(self, obligation, satisfaction) -> None:
        require_satisfaction(
            self.index,
            obligation=obligation,
            satisfaction=satisfaction,
            allow_legacy_decision_binding=False,
        )

    def _seed_satisfied(self, **kwargs):
        obligation, satisfaction = self._seed(**kwargs)
        self.index.put(initial_obligation_record(obligation))
        self.authority_sequence = getattr(self, "authority_sequence", 10_000) + 1
        resolution = satisfaction_record(
            obligation=obligation,
            satisfaction=satisfaction,
            prior_status=ReplayObligationStatus.PENDING,
            sequence=2,
        )
        self.index.put_many(
            _authenticated_transition_records(
                resolution,
                authority_sequence=self.authority_sequence,
                event_kind="historical_replay_correction_recorded",
                operation_id=f"accept-replay-satisfaction-{self.authority_sequence}",
                result={
                    "satisfied_replay_obligation_ids": [obligation.identity]
                },
            )
        )
        return obligation, satisfaction

    def _require_recorded(self, obligation, satisfaction) -> None:
        head = self.index.get(
            "historical-replay-obligation-resolution",
            satisfaction.identity,
        )
        self.assertIsNotNone(head)
        require_recorded_satisfaction(
            self.index,
            obligation=obligation,
            satisfaction=satisfaction,
            allow_legacy_decision_binding=False,
            satisfaction_head=head,
        )

    def _add_pending_sibling_obligation(
        self,
        *,
        source_obligation,
        original_executable_id: str,
        original_study_id: str | None = None,
    ):
        source_adjudication = self.index.get(
            "historical-scientific-adjudication",
            source_obligation.historical_adjudication_id,
        )
        self.assertIsNotNone(source_adjudication)
        assert source_adjudication is not None
        payload = deepcopy(source_adjudication.payload)
        payload.update(
            {
                "audit_artifact_hash": "9" * 64,
                "completion_record_id": "a" * 64,
                "executable_id": original_executable_id,
                "measurement_artifact_hash": "b" * 64,
                "study_close_record_id": "c" * 64,
                "study_id": (
                    source_obligation.original_study_id
                    if original_study_id is None
                    else original_study_id
                ),
                "validation_plan_hash": "d" * 64,
            }
        )
        adjudication_id = "historical-adjudication:" + "9" * 64
        sibling = derive_historical_replay_obligation(
            governing_mission_id=MISSION_ID,
            historical_adjudication_id=adjudication_id,
            adjudication_payload=payload,
        )
        self.index.put_many(
            (
                IndexRecord(
                    kind="historical-scientific-adjudication",
                    record_id=adjudication_id,
                    subject=f"Study:{sibling.original_study_id}",
                    status="replay_required",
                    fingerprint="9" * 64,
                    payload=payload,
                ),
                initial_obligation_record(sibling),
            )
        )
        return sibling

    def test_exact_omitted_sibling_recertifies_without_new_authority_delta(
        self,
    ) -> None:
        sibling_reference = "executable:" + "a" * 64
        source_obligation, source_satisfaction = self._seed_satisfied(
            historical_reference_by_member={2: sibling_reference},
            project_batch_stream=True,
        )
        sibling = self._add_pending_sibling_obligation(
            source_obligation=source_obligation,
            original_executable_id=sibling_reference,
        )

        derived, records, constraints, result = (
            prepare_sibling_evidence_recertification(
                self.index,
                mission_id=MISSION_ID,
                source_satisfaction_ids=(source_satisfaction.identity,),
                obligation_ids=(sibling.identity,),
            )
        )

        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0].obligation_id, sibling.identity)
        self.assertNotEqual(
            derived[0].replay_executable_id,
            source_satisfaction.replay_executable_id,
        )
        self.assertEqual(
            [record.kind for record in records],
            ["historical-replay-obligation-resolution"],
        )
        self.assertIsNone(constraints)
        self.assertEqual(
            result,
            {
                "candidate_delta": 0,
                "holdout_reveal_delta": 0,
                "satisfied_replay_obligation_ids": [sibling.identity],
                "source_satisfaction_ids": [source_satisfaction.identity],
                "trial_delta": 0,
            },
        )

    def test_ambiguous_omitted_sibling_family_fails_closed(self) -> None:
        sibling_reference = "executable:" + "a" * 64
        source_obligation, source_satisfaction = self._seed_satisfied(
            historical_reference_by_member={
                2: sibling_reference,
                3: sibling_reference,
            },
            project_batch_stream=True,
        )
        sibling = self._add_pending_sibling_obligation(
            source_obligation=source_obligation,
            original_executable_id=sibling_reference,
        )

        with self.assertRaisesRegex(
            ReplayTransitionError,
            "one exact closed family member",
        ):
            prepare_sibling_evidence_recertification(
                self.index,
                mission_id=MISSION_ID,
                source_satisfaction_ids=(source_satisfaction.identity,),
                obligation_ids=(sibling.identity,),
            )

    def test_mismatched_omitted_sibling_family_fails_closed(self) -> None:
        sibling_reference = "executable:" + "a" * 64
        source_obligation, source_satisfaction = self._seed_satisfied(
            historical_reference_by_member={2: sibling_reference},
            project_batch_stream=True,
        )
        sibling = self._add_pending_sibling_obligation(
            source_obligation=source_obligation,
            original_executable_id=sibling_reference,
            original_study_id="STU-HIST-OTHER",
        )

        with self.assertRaisesRegex(
            ReplayTransitionError,
            "one exact closed family member",
        ):
            prepare_sibling_evidence_recertification(
                self.index,
                mission_id=MISSION_ID,
                source_satisfaction_ids=(source_satisfaction.identity,),
                obligation_ids=(sibling.identity,),
            )

    def test_recorded_satisfaction_ignores_future_protocol_implementation(
        self,
    ) -> None:
        obligation, satisfaction = self._seed_satisfied()
        with patch(
            "axiom_rift.operations.replay_projection."
            "_require_scientific_satisfaction_evidence",
            side_effect=AssertionError("current protocol must not run"),
        ):
            self._require_recorded(obligation, satisfaction)

    def test_recorded_satisfaction_requires_same_event_writer_operation(
        self,
    ) -> None:
        obligation, satisfaction = self._seed()
        self.index.put(initial_obligation_record(obligation))
        self.authority_sequence += 1
        resolution = satisfaction_record(
            obligation=obligation,
            satisfaction=satisfaction,
            prior_status=ReplayObligationStatus.PENDING,
            sequence=2,
        )
        journal_event, operation, stored = _authenticated_transition_records(
            resolution,
            authority_sequence=self.authority_sequence,
            event_kind="historical_replay_correction_recorded",
            operation_id="cross-event-replay-satisfaction",
            result={
                "satisfied_replay_obligation_ids": [obligation.identity]
            },
        )
        operation = replace(operation, authority_event_id="f" * 64)
        self.index.put_many((journal_event, operation, stored))
        with self.assertRaisesRegex(
            ReplayAuthorityError,
            "cross-event",
        ):
            require_recorded_satisfaction(
                self.index,
                obligation=obligation,
                satisfaction=satisfaction,
                allow_legacy_decision_binding=False,
                satisfaction_head=stored,
            )

    def test_recorded_satisfaction_rejects_missing_writer_operation(self) -> None:
        obligation, satisfaction = self._seed()
        self.index.put(initial_obligation_record(obligation))
        self.authority_sequence += 1
        resolution = satisfaction_record(
            obligation=obligation,
            satisfaction=satisfaction,
            prior_status=ReplayObligationStatus.PENDING,
            sequence=2,
        )
        journal_event, _operation, stored = _authenticated_transition_records(
            resolution,
            authority_sequence=self.authority_sequence,
            event_kind="historical_replay_correction_recorded",
            operation_id="missing-operation-replay-satisfaction",
            result={
                "satisfied_replay_obligation_ids": [obligation.identity]
            },
        )
        self.index.put_many((journal_event, stored))
        with self.assertRaisesRegex(
            ReplayAuthorityError,
            "one same-authority Writer operation",
        ):
            require_recorded_satisfaction(
                self.index,
                obligation=obligation,
                satisfaction=satisfaction,
                allow_legacy_decision_binding=False,
                satisfaction_head=stored,
            )

    def test_recorded_satisfaction_checks_actual_predecessor_status(self) -> None:
        obligation, satisfaction = self._seed()
        self.index.put(initial_obligation_record(obligation))
        self.authority_sequence += 1
        resolution = satisfaction_record(
            obligation=obligation,
            satisfaction=satisfaction,
            prior_status=ReplayObligationStatus.IN_PROGRESS,
            sequence=2,
        )
        self.index.put_many(
            _authenticated_transition_records(
                resolution,
                authority_sequence=self.authority_sequence,
                event_kind="historical_replay_obligations_resolved",
                operation_id="broken-predecessor-replay-satisfaction",
                result={
                    "satisfied_replay_obligation_ids": [obligation.identity]
                },
            )
        )
        with self.assertRaisesRegex(
            ReplayAuthorityError,
            "actual predecessor",
        ):
            self._require_recorded(obligation, satisfaction)

    def test_scientific_satisfaction_accepts_batch_family_without_trial_tag(
        self,
    ) -> None:
        obligation, satisfaction = self._seed()
        self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rebuilds_exact_durable_batch_binding(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(
            project_durable_batch_binding=True
        )
        self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_durable_batch_binding_drift(
        self,
    ) -> None:
        for mutation in (
            "missing",
            "wrong_batch",
            "reordered",
            "extra",
            "missing_member",
            "wrong_subject",
        ):
            with self.subTest(mutation=mutation):
                original_index = self.index
                with TemporaryDirectory() as temporary:
                    with LocalIndex(Path(temporary) / "index.sqlite3") as isolated:
                        self.index = isolated
                        obligation, satisfaction = self._seed(
                            project_durable_batch_binding=True,
                            durable_batch_binding_mutation=mutation,
                        )
                        with self.assertRaisesRegex(
                            ReplayTransitionError,
                            "durable Batch binding",
                        ):
                            self._require(obligation, satisfaction)
                self.index = original_index

    def test_scientific_satisfaction_accepts_legacy_plan_registration(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(project_registration=False)
        self._require(obligation, satisfaction)

    def test_scientific_satisfaction_accepts_member_specific_paired_families(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(paired_family_size=3)
        self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_collapsed_family_size(self) -> None:
        obligation, satisfaction = self._seed(recorded_family_size=1)
        with self.assertRaisesRegex(ReplayTransitionError, "exact Batch family"):
            self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_adjustment_mismatch(self) -> None:
        obligation, satisfaction = self._seed(
            recorded_adjusted_pvalue_ppm=30_000
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "multiplicity adjustment",
        ):
            self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_alpha_mismatch(self) -> None:
        obligation, satisfaction = self._seed(recorded_alpha_ppm=50_000)
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "multiplicity adjustment",
        ):
            self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_family_identity_mismatch(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(
            mismatch_member_family_id=4
        )
        with self.assertRaisesRegex(ReplayTransitionError, "selection family"):
            self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_same_size_different_members(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(wrong_registration_member=4)
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "exact Batch family",
        ):
            self._require(obligation, satisfaction)

    def test_prospective_satisfaction_rejects_same_set_reordered_family(
        self,
    ) -> None:
        obligation, satisfaction = self._seed(
            reverse_registration_order=True
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "order differs from the exact prospective Batch order",
        ):
            self._require(obligation, satisfaction)

    def test_same_set_reordered_history_is_not_invalidation_authority(
        self,
    ) -> None:
        obligation, _satisfaction = self._seed_satisfied(
            reverse_registration_order=True
        )
        with self.assertRaisesRegex(
            ReplayTransitionError,
            "order differs from the exact prospective Batch order",
        ):
            build_satisfaction_invalidation_plan(
                self.index,
                mission_id=MISSION_ID,
                obligation_id=obligation.identity,
            )

    def test_reordered_history_does_not_mask_independent_validity_defect(
        self,
    ) -> None:
        obligation, satisfaction = self._seed_satisfied(
            reverse_registration_order=True
        )
        completion_ids = tuple(
            sorted(
                identity
                for identity in satisfaction.evidence_record_ids
                if self.index.get("job-completed", identity) is not None
            )
        )
        invalid_completion_id = completion_ids[0]
        completion = self.index.get("job-completed", invalid_completion_id)
        self.assertIsNotNone(completion)
        scientific = completion.payload["scientific"]
        validity = SimpleNamespace(
            affected_criterion_ids=tuple(obligation.criterion_ids),
            authority_event_id="f" * 64,
            authority_offset=1234,
            authority_sequence=9999,
            completion_record_id=invalid_completion_id,
            executable_id=scientific["executable_id"],
            invalidation_record_id=(
                "historical-scientific-validity-invalidation:" + "e" * 64
            ),
            reason="decision_input_point_in_time_unproven",
            validity_stream_sequence=1,
        )
        with patch(
            "axiom_rift.operations.replay_projection."
            "current_completion_validity_invalidation",
            side_effect=lambda _index, completion_id: (
                validity if completion_id == invalid_completion_id else None
            ),
        ):
            plan = build_satisfaction_invalidation_plan(
                self.index,
                mission_id=MISSION_ID,
                obligation_id=obligation.identity,
            )
        manifest = ReplaySatisfactionInvalidationAuditManifestV2.from_mapping(
            plan["audit_manifest"]
        )
        self.assertEqual(len(manifest.defects), 1)
        self.assertEqual(
            manifest.defects[0].code.value,
            "evidence_completion_validity_invalid",
        )
        self.assertEqual(
            manifest.completion_record_ids,
            completion_ids,
        )

    def test_forged_or_unrelated_registration_is_not_typed_invalidation(
        self,
    ) -> None:
        for kwargs, message in (
            (
                {
                    "forged_registration_hash_member": 4,
                    "recorded_family_size": 1,
                },
                "registration is malformed",
            ),
            (
                {"unrelated_registration_member": 4},
                "registration is unrelated",
            ),
            (
                {"omit_registration_member": 4},
                "registration is not exact",
            ),
        ):
            with self.subTest(kwargs=kwargs):
                original_index = self.index
                with TemporaryDirectory() as temporary:
                    with LocalIndex(Path(temporary) / "index.sqlite3") as isolated:
                        self.index = isolated
                        obligation, _ = self._seed_satisfied(**kwargs)
                        with self.assertRaisesRegex(
                            ReplayTransitionError,
                            message,
                        ):
                            build_satisfaction_invalidation_plan(
                                self.index,
                                mission_id=MISSION_ID,
                                obligation_id=obligation.identity,
                            )
                self.index = original_index

    def test_scientific_satisfaction_rejects_job_batch_mismatch(self) -> None:
        obligation, satisfaction = self._seed(
            target_batch_id="batch:" + "f" * 64
        )
        with self.assertRaisesRegex(ReplayTransitionError, "Batch"):
            self._require(obligation, satisfaction)

    def test_scientific_satisfaction_rejects_incomplete_family(self) -> None:
        obligation, satisfaction = self._seed(omit_member_completion=4)
        with self.assertRaisesRegex(ReplayTransitionError, "Batch"):
            self._require(obligation, satisfaction)

    def test_exact_e01_size_defect_can_requeue_satisfied_head(self) -> None:
        obligation, satisfaction = self._seed_satisfied(recorded_family_size=1)
        plan = build_satisfaction_invalidation_plan(
            self.index,
            mission_id=MISSION_ID,
            obligation_id=obligation.identity,
        )
        manifest = ReplaySatisfactionInvalidationAuditManifest.from_mapping(
            plan["audit_manifest"]
        )
        self.assertEqual(
            manifest.satisfaction_record_id,
            satisfaction.identity,
        )
        self.assertEqual(
            manifest.defect.code.value,
            "selection_family_size_mismatch",
        )
        self.assertEqual(manifest.defect.expected_family_size, 4)
        self.assertEqual(
            {item.family_size for item in manifest.defect.observations},
            {1},
        )

        records, constraints, result = prepare_satisfaction_invalidation(
            self.index,
            mission_id=MISSION_ID,
            obligation_id=obligation.identity,
            manifest=manifest,
            audit_manifest_hash=plan["audit_manifest_sha256"],
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "pending")
        self.assertEqual(records[0].event_sequence, 3)
        self.assertEqual(result["scientific_claim_delta"], 0)
        self.assertEqual(result["scientific_trial_delta"], 0)
        self.assertEqual(result["holdout_reveal_delta"], 0)
        self.assertEqual(result["candidate_delta"], 0)
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            [obligation.identity],
        )
        self.authority_sequence += 1
        self.index.put_many(
            _authenticated_transition_records(
                records[0],
                authority_sequence=self.authority_sequence,
                event_kind="historical_replay_satisfaction_invalidated",
                operation_id=f"invalidate-replay-{self.authority_sequence}",
                result=result,
            )
        )
        heads = obligation_heads(self.index, mission_id=MISSION_ID)
        self.assertEqual(heads[0][1].record_id, manifest.identity)
        self.assertEqual(heads[0][1].status, "pending")
        with patch(
            "axiom_rift.operations.replay_projection."
            "derive_satisfaction_invalidation_manifest",
            side_effect=AssertionError("stored invalidation must not rederive"),
        ):
            self.assertEqual(
                require_satisfaction_invalidation_record(
                    self.index,
                    obligation=obligation,
                    record=heads[0][1],
                ),
                manifest,
            )

    def test_exact_e01_membership_defect_round_trips_and_requeues(self) -> None:
        obligation, satisfaction = self._seed_satisfied(
            wrong_registration_member=4
        )
        plan = build_satisfaction_invalidation_plan(
            self.index,
            mission_id=MISSION_ID,
            obligation_id=obligation.identity,
        )
        manifest = ReplaySatisfactionInvalidationAuditManifest.from_mapping(
            plan["audit_manifest"]
        )
        self.assertEqual(
            manifest,
            ReplaySatisfactionInvalidationAuditManifest.from_bytes(
                canonical_bytes(manifest.to_identity_payload())
            ),
        )
        self.assertEqual(
            manifest.defect.code.value,
            "selection_family_membership_mismatch",
        )
        self.assertEqual(
            manifest.satisfaction_record_id,
            satisfaction.identity,
        )
        expected_members = tuple(sorted(manifest.defect.expected_executable_ids))
        mismatches = tuple(
            item
            for item in manifest.defect.observations
            if item.ordered_member_ids != expected_members
        )
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(
            mismatches[0].family_registration_hash,
            multiplicity_family_registration_hash(
                family_id=mismatches[0].family_id,
                alpha_ppm=mismatches[0].alpha_ppm,
                method=mismatches[0].method,
                ordered_member_ids=mismatches[0].ordered_member_ids,
            ),
        )

        records, constraints, result = prepare_satisfaction_invalidation(
            self.index,
            mission_id=MISSION_ID,
            obligation_id=obligation.identity,
            manifest=manifest,
            audit_manifest_hash=plan["audit_manifest_sha256"],
        )
        self.assertEqual(records[0].status, "pending")
        self.assertEqual(
            constraints["pending_replay_obligation_ids"],
            [obligation.identity],
        )
        self.assertEqual(result["scientific_claim_delta"], 0)

    def test_exact_e01_family_disagreement_is_typed(self) -> None:
        obligation, _ = self._seed_satisfied(mismatch_member_family_id=4)
        plan = build_satisfaction_invalidation_plan(
            self.index,
            mission_id=MISSION_ID,
            obligation_id=obligation.identity,
        )
        self.assertEqual(
            plan["audit_manifest"]["defect"]["code"],
            "selection_family_disagreement",
        )

    def test_only_typed_e01_family_defect_can_build_invalidation(self) -> None:
        valid, _ = self._seed_satisfied()
        with self.assertRaisesRegex(ReplayTransitionError, "remains valid"):
            build_satisfaction_invalidation_plan(
                self.index,
                mission_id=MISSION_ID,
                obligation_id=valid.identity,
            )

        original_index = self.index
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as isolated:
                self.index = isolated
                obligation, _ = self._seed_satisfied(
                    recorded_adjusted_pvalue_ppm=30_000
                )
                with self.assertRaisesRegex(
                    ReplayTransitionError,
                    "multiplicity adjustment",
                ):
                    build_satisfaction_invalidation_plan(
                        self.index,
                        mission_id=MISSION_ID,
                        obligation_id=obligation.identity,
                    )
        self.index = original_index

    def test_invalidation_fails_closed_for_wrong_head_obligation_and_artifact(
        self,
    ) -> None:
        pending, _ = self._seed()
        self.index.put(initial_obligation_record(pending))
        with self.assertRaisesRegex(ReplayTransitionError, "satisfied head"):
            build_satisfaction_invalidation_plan(
                self.index,
                mission_id=MISSION_ID,
                obligation_id=pending.identity,
            )
        with self.assertRaisesRegex(ReplayTransitionError, "unknown obligation"):
            build_satisfaction_invalidation_plan(
                self.index,
                mission_id=MISSION_ID,
                obligation_id="historical-replay-obligation:" + "f" * 64,
            )

        original_index = self.index
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as isolated:
                self.index = isolated
                obligation, _ = self._seed_satisfied(recorded_family_size=1)
                plan = build_satisfaction_invalidation_plan(
                    self.index,
                    mission_id=MISSION_ID,
                    obligation_id=obligation.identity,
                )
                manifest = (
                    ReplaySatisfactionInvalidationAuditManifest.from_mapping(
                        plan["audit_manifest"]
                    )
                )
                with self.assertRaisesRegex(
                    ReplayTransitionError,
                    "artifact differs",
                ):
                    prepare_satisfaction_invalidation(
                        self.index,
                        mission_id=MISSION_ID,
                        obligation_id=obligation.identity,
                        manifest=manifest,
                        audit_manifest_hash="0" * 64,
                    )
        self.index = original_index

    def test_writer_commits_exact_manifest_and_restores_scheduler(self) -> None:
        obligation, satisfaction = self._seed_satisfied(
            wrong_registration_member=4
        )
        original_axis_id = "axis-original-multiplicity"
        original_axis_identity = "axis:" + "4" * 64
        original_mission_id = "MIS-HIST-MULTIPLICITY"
        original_job_id = "job:" + "5" * 64
        self.index.put_many(
            (
                IndexRecord(
                    kind="study-open",
                    record_id=obligation.original_study_id,
                    subject=f"Study:{obligation.original_study_id}",
                    status="closed",
                    fingerprint="6" * 64,
                    payload={
                        "mission_id": original_mission_id,
                        "portfolio_axis_id": original_axis_id,
                        "portfolio_axis_identity": original_axis_identity,
                    },
                ),
                IndexRecord(
                    kind="trial",
                    record_id=obligation.original_executable_id,
                    subject="Batch:BAT-HIST-MULTIPLICITY",
                    status="evaluated",
                    fingerprint=obligation.original_executable_id.removeprefix(
                        "executable:"
                    ),
                    payload={
                        "executable": {"schema": "historical_fixture.v1"},
                        "mission_id": original_mission_id,
                        "portfolio_axis_id": original_axis_id,
                        "portfolio_axis_identity": original_axis_identity,
                        "study_id": obligation.original_study_id,
                    },
                ),
                IndexRecord(
                    kind="job-declared",
                    record_id=original_job_id,
                    subject=f"Job:{original_job_id}",
                    status="declared",
                    fingerprint="5" * 64,
                    payload={
                        "mission_id": original_mission_id,
                        "study_id": obligation.original_study_id,
                        "spec": {
                            "evidence_subject": {
                                "id": obligation.original_executable_id,
                                "kind": "Executable",
                            }
                        },
                    },
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id=obligation.original_completion_record_id,
                    subject=f"Job:{original_job_id}",
                    status="success",
                    fingerprint="2" * 64,
                    payload={
                        "job_id": original_job_id,
                        "scientific": {
                            "executable_id": obligation.original_executable_id
                        },
                    },
                ),
                IndexRecord(
                    kind="study-close",
                    record_id=obligation.original_study_close_record_id,
                    subject=f"Study:{obligation.original_study_id}",
                    status="failed",
                    fingerprint="5" * 64,
                    payload={"study_id": obligation.original_study_id},
                ),
            )
        )
        kinds = (
            "batch-close",
            "batch-open",
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
        records = tuple(
            record
            for kind in kinds
            for record in self.index.records_by_kind(kind)
        )
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                Path(temporary),
                permit_authority=PermitAuthority(b"p" * 32),
                clock=lambda: "2026-07-15T00:00:00Z",
                engineering_fixture=True,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id=MISSION_ID,
                goal={
                    "objective": "exercise exact replay satisfaction invalidation",
                    "scope": ["isolated", "engineering_fixture"],
                    "terminal_contract": "no_scientific_terminal",
                },
                operation_id="open-replay-invalidation-mission",
            )

            def seed(current, _index):
                body = writer._body(current)
                body["next_action"] = {
                    "kind": "choose_next_initiative_or_terminal",
                    "mission_id": MISSION_ID,
                }
                return body, records, {
                    "satisfied_replay_obligation_ids": [obligation.identity]
                }

            writer._commit(
                event_kind="historical_replay_correction_recorded",
                operation_id="seed-replay-satisfaction-invalidation",
                subject=f"Mission:{MISSION_ID}",
                payload={"obligation_id": obligation.identity},
                prepare=seed,
            )
            plan = writer.plan_historical_replay_satisfaction_invalidation(
                obligation_id=obligation.identity,
            )
            self.assertEqual(
                plan["audit_manifest"]["defect"]["code"],
                "selection_family_membership_mismatch",
            )
            artifact = writer.evidence.finalize(
                canonical_bytes(plan["audit_manifest"])
            )
            self.assertEqual(artifact.sha256, plan["audit_manifest_sha256"])
            malformed = writer.evidence.finalize(canonical_bytes({}))
            with self.assertRaisesRegex(TransitionError, "exact canonical manifest"):
                writer.invalidate_historical_replay_satisfaction(
                    obligation_id=obligation.identity,
                    audit_manifest_hash=malformed.sha256,
                    operation_id="reject-malformed-replay-invalidation",
                )
            tampered_payload = deepcopy(plan["audit_manifest"])
            tampered_observation = next(
                item
                for item in tampered_payload["defect"]["observations"]
                if item["ordered_member_ids"]
                != tampered_payload["defect"]["expected_executable_ids"]
            )
            tampered_members = tuple(
                sorted(
                    (
                        tampered_observation["executable_id"],
                        *(f"executable:{value:064x}" for value in range(601, 604)),
                    )
                )
            )
            tampered_observation["ordered_member_ids"] = list(tampered_members)
            tampered_observation["family_registration_hash"] = (
                multiplicity_family_registration_hash(
                    family_id=tampered_observation["family_id"],
                    alpha_ppm=tampered_observation["alpha_ppm"],
                    method=tampered_observation["method"],
                    ordered_member_ids=tampered_members,
                )
            )
            ReplaySatisfactionInvalidationAuditManifest.from_mapping(
                tampered_payload
            )
            tampered = writer.evidence.finalize(
                canonical_bytes(tampered_payload)
            )
            with self.assertRaisesRegex(TransitionError, "artifact differs"):
                writer.invalidate_historical_replay_satisfaction(
                    obligation_id=obligation.identity,
                    audit_manifest_hash=tampered.sha256,
                    operation_id="reject-tampered-replay-invalidation",
                )
            with self.assertRaisesRegex(TransitionError, "another obligation"):
                writer.invalidate_historical_replay_satisfaction(
                    obligation_id="historical-replay-obligation:" + "f" * 64,
                    audit_manifest_hash=artifact.sha256,
                    operation_id="reject-wrong-replay-obligation",
                )
            result = writer.invalidate_historical_replay_satisfaction(
                obligation_id=obligation.identity,
                audit_manifest_hash=artifact.sha256,
                operation_id="invalidate-replay-satisfaction",
            )
            self.assertEqual(
                result.result["invalidated_satisfaction_record_id"],
                satisfaction.identity,
            )
            control = writer.read_control()
            assert control is not None
            self.assertEqual(
                control["next_action"]["pending_replay_obligation_ids"],
                [obligation.identity],
            )
            self.assertEqual(
                control["next_action"]["required_replay_priority"],
                ReplayPriority.P1.value,
            )
            with self.assertRaisesRegex(TransitionError, "satisfied head"):
                writer.plan_historical_replay_satisfaction_invalidation(
                    obligation_id=obligation.identity,
                )
            with writer._open_authoritative_index() as index:
                bindings = effective_replay_axis_bindings(
                    index,
                    mission_id=MISSION_ID,
                )
            self.assertEqual(len(bindings), 1)
            self.assertIs(bindings[0].status, ReplayObligationStatus.PENDING)
            self.assertTrue(
                bindings[0].state_record_id.startswith(
                    "historical-replay-satisfaction-invalidation:"
                )
            )
            self.assertTrue(bindings[0].blocks_terminal)


if __name__ == "__main__":
    unittest.main()
