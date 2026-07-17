from __future__ import annotations

import unittest

from axiom_rift.research.effective_axis import (
    EffectiveAxisStatus,
    SourceInvalidationBinding,
    resolve_effective_axis,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayObligationError,
    ReplayPriorityEscalation,
    ReplayResolutionScope,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    ReplaySatisfaction,
    derive_historical_replay_obligation,
    historical_replay_obligation_from_identity_payload,
    highest_pending_priority,
    replay_priority_escalation_from_identity_payload,
    replay_deferral_from_identity_payload,
    replay_resume_evidence_from_identity_payload,
)


def adjudication_payload(*, token: int, priority: ReplayPriority) -> dict[str, object]:
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": f"claim-{token}"}],
            "criteria": [{"criterion_id": f"criterion-{token}"}],
        },
        "audit_artifact_hash": f"{token + 10:064x}",
        "completion_record_id": f"{token + 20:064x}",
        "disposition": "replay_required",
        "executable_id": f"executable:{token + 30:064x}",
        "measurement_artifact_hash": f"{token + 40:064x}",
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": priority.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": f"{token + 50:064x}",
        "study_id": f"STU-{token:04d}",
        "validation_plan_hash": f"{token + 60:064x}",
    }


def obligation(*, token: int, priority: ReplayPriority):
    return derive_historical_replay_obligation(
        governing_mission_id="MIS-REPLAY",
        historical_adjudication_id=f"historical-adjudication:{token:064x}",
        adjudication_payload=adjudication_payload(token=token, priority=priority),
    )


class ReplayObligationTests(unittest.TestCase):
    def test_identity_payload_round_trips_exactly(self) -> None:
        expected = obligation(token=1, priority=ReplayPriority.P1)
        rebuilt = historical_replay_obligation_from_identity_payload(
            expected.to_identity_payload()
        )
        self.assertEqual(rebuilt, expected)
        self.assertEqual(rebuilt.identity, expected.identity)

    def test_priority_escalation_is_exact_one_way_additive_authority(self) -> None:
        target = obligation(token=1, priority=ReplayPriority.P1)
        escalation = ReplayPriorityEscalation(
            governing_mission_id=target.governing_mission_id,
            obligation_id=target.identity,
            superseding_historical_adjudication_id=(
                "historical-adjudication:" + "a" * 64
            ),
            completion_validity_invalidation_id=(
                "historical-scientific-validity-invalidation:" + "b" * 64
            ),
            accepted_satisfaction_record_id=(
                "historical-replay-satisfaction:" + "c" * 64
            ),
            audit_artifact_hash="d" * 64,
            reason_codes=(
                "accepted_replay_satisfaction_revocation_pending",
                "decision_input_point_in_time_unproven",
            ),
        )
        rebuilt = replay_priority_escalation_from_identity_payload(
            escalation.to_identity_payload()
        )
        self.assertEqual(rebuilt, escalation)
        self.assertIs(rebuilt.prior_priority, ReplayPriority.P1)
        self.assertIs(rebuilt.effective_priority, ReplayPriority.P0)
        forged = dict(escalation.to_identity_payload())
        forged["effective_priority"] = "p1"
        with self.assertRaisesRegex(ReplayObligationError, "malformed"):
            replay_priority_escalation_from_identity_payload(forged)

    def test_p0_is_the_only_schedulable_priority_while_present(self) -> None:
        pending = (
            obligation(token=1, priority=ReplayPriority.P1),
            obligation(token=2, priority=ReplayPriority.P0),
            obligation(token=3, priority=ReplayPriority.P1),
        )
        self.assertIs(highest_pending_priority(pending), ReplayPriority.P0)
        self.assertIs(
            highest_pending_priority(
                tuple(
                    item
                    for item in pending
                    if item.replay_priority is ReplayPriority.P1
                )
            ),
            ReplayPriority.P1,
        )

    def test_audit_only_satisfaction_retains_scientific_condition(self) -> None:
        target = obligation(token=1, priority=ReplayPriority.P0)
        satisfaction = ReplaySatisfaction(
            obligation_id=target.identity,
            resolution_scope=ReplayResolutionScope.AUDIT_ONLY,
            portfolio_decision_id="decision:" + "1" * 64,
            replay_study_id="STU-REPLAY",
            replay_executable_id="executable:" + "2" * 64,
            replay_study_close_record_id="3" * 64,
            study_diagnosis_id="diagnosis:" + "4" * 64,
            satisfied_criterion_ids=target.criterion_ids,
            evidence_record_ids=("5" * 64,),
            remaining_scientific_condition=(
                "prospective_paired_control_or_independent_family"
            ),
        )
        self.assertEqual(
            satisfaction.to_identity_payload()["remaining_scientific_condition"],
            "prospective_paired_control_or_independent_family",
        )
        with self.assertRaisesRegex(
            ReplayObligationError, "remaining scientific condition"
        ):
            ReplaySatisfaction(
                obligation_id=target.identity,
                resolution_scope=ReplayResolutionScope.AUDIT_ONLY,
                portfolio_decision_id="decision:" + "1" * 64,
                replay_study_id="STU-REPLAY",
                replay_executable_id="executable:" + "2" * 64,
                replay_study_close_record_id="3" * 64,
                study_diagnosis_id="diagnosis:" + "4" * 64,
                satisfied_criterion_ids=target.criterion_ids,
                evidence_record_ids=("5" * 64,),
            )

    def test_deferral_round_trips_finite_conditions_and_exact_execution(self) -> None:
        target = obligation(token=1, priority=ReplayPriority.P1)
        family = tuple(f"executable:{token:064x}" for token in range(31, 35))
        conditions = tuple(
            ReplayResumeCondition(
                kind=kind,
                protocol_id="python.source.analog_state_replay.v1",
                original_executable_ids=family,
                criterion_ids=target.criterion_ids,
            )
            for kind in (
                ReplayResumeConditionKind.REGISTERED_DEVELOPMENT_MATERIAL,
                ReplayResumeConditionKind.SAME_PROTOCOL_REPAIR,
            )
        )
        deferral = ReplayDeferral(
            obligation_id=target.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id="diagnosis:" + "1" * 64,
                subject_id="STU-REPLAY",
            ),
            reason_codes=("original_criterion_recomputation_incomplete",),
            resume_conditions=conditions,
            execution_binding=ReplayDeferralExecutionBinding(
                portfolio_decision_id="decision:" + "2" * 64,
                replay_study_id="STU-REPLAY",
                replay_executable_id="executable:" + "3" * 64,
                replay_study_close_record_id="4" * 64,
                study_diagnosis_id="diagnosis:" + "1" * 64,
            ),
        )
        rebuilt = replay_deferral_from_identity_payload(
            deferral.to_identity_payload()
        )
        self.assertEqual(rebuilt, deferral)
        evidence = ReplayResumeEvidence(
            obligation_id=target.identity,
            deferral_id=deferral.identity,
            resume_condition_id=conditions[0].identity,
            trigger_record_id="5" * 64,
        )
        self.assertEqual(
            evidence.to_identity_payload()["deferral_id"], deferral.identity
        )
        self.assertEqual(
            replay_resume_evidence_from_identity_payload(
                evidence.to_identity_payload()
            ),
            evidence,
        )
        for field, value in (
            ("schema", "historical_replay_resume_evidence.v2"),
            ("deferral_id", "historical-replay-deferral:malformed"),
            ("unexpected", True),
        ):
            forged = dict(evidence.to_identity_payload())
            forged[field] = value
            with self.assertRaises(ReplayObligationError):
                replay_resume_evidence_from_identity_payload(forged)

        with self.assertRaisesRegex(ReplayObligationError, "not typed"):
            ReplayResumeCondition(
                kind="new_mechanism",  # type: ignore[arg-type]
                protocol_id="python.source.materially_different.v1",
                original_executable_ids=family,
                criterion_ids=target.criterion_ids,
            )

    def test_source_invalidation_overrides_historical_prune_without_rewrite(self) -> None:
        source_id = "source:" + "a" * 64
        resolution = resolve_effective_axis(
            axis_id="axis-legacy",
            axis_identity="axis:" + "b" * 64,
            snapshot_status="pruned",
            source_contract_ids=(source_id,),
            invalidations=(
                SourceInvalidationBinding(
                    source_contract_id=source_id,
                    invalidation_record_id=(
                        "source-authority-invalidation:" + "c" * 64
                    ),
                ),
            ),
        )
        self.assertEqual(resolution.snapshot_status, "pruned")
        self.assertIs(
            resolution.effective_status,
            EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
        )
        self.assertFalse(resolution.selectable)


if __name__ == "__main__":
    unittest.main()
