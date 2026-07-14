from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.portfolio import (
    BatchSpec,
    BatchSpecError,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.index import LocalIndex
from tests.operations import test_writer as fixtures


class ConcurrentFamilyRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = StateWriter(
            self.root,
            permit_authority=PermitAuthority(b"f" * 32),
            clock=lambda: fixtures.FIXED_NOW,
            engineering_fixture=True,
            foundation_root=fixtures.REPO_ROOT,
        )
        self.writer.initialize_ready()
        self.writer.open_mission(
            mission_id="MIS-FAMILY",
            goal=fixtures.mission_goal("concurrent family registration"),
            operation_id="family-open-mission",
        )
        self.writer.open_initiative(
            initiative_id="INI-FAMILY",
            objective=fixtures.initiative_objective(
                "concurrent family registration"
            ),
            operation_id="family-open-initiative",
        )
        question = fixtures.study_question("concurrent family registration")
        proposal = {"mechanism": "typed concurrent family fixture"}
        study_hash = self.writer.study_input_hash(
            question=question,
            material_identity=fixtures.OBSERVED_MATERIAL_ID,
            semantic_proposal=proposal,
        )
        study_permit = self.writer.issue_permit(
            kind=PermitKind.STUDY,
            subject_kind=SubjectKind.INITIATIVE,
            subject_id="INI-FAMILY",
            input_hash=study_hash,
            actions=("open_study",),
            scope=("study",),
            expires_at_utc=fixtures.FIXED_EXPIRY,
            one_shot=True,
            operation_id="family-study-permit",
        )
        opened = self.writer.open_study(
            study_id="STU-FAMILY",
            question=question,
            material_identity=fixtures.OBSERVED_MATERIAL_ID,
            material_display_name="fixture material",
            semantic_proposal=proposal,
            permit=study_permit,
            operation_id="family-open-study",
        )
        self.members = (
            fixtures.executable_spec("family-a"),
            fixtures.executable_spec("family-b"),
        )
        self.manifest = ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(member.identity for member in self.members),
        )
        self.batch = BatchSpec(
            batch_id="BAT-FAMILY",
            study_id="STU-FAMILY",
            study_hash=opened.result["study_hash"],
            display_name="typed concurrent family fixture",
            max_trials=2,
            max_compute_seconds=60,
            max_wall_seconds=90,
            stop_rule="stop after the exact two-member family",
            concurrent_family=self.manifest,
            acceptance_profile={"causality": "required"},
            adaptive_basis={
                "uncertainty": "fixture",
                "causal_complexity": "two exact members",
                "surface_curvature": "fixed family",
                "compute_cost": "bounded",
                "expected_information_value": "positive",
                "portfolio_opportunity_cost": "declared",
            },
        )
        batch_permit = self.writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id="STU-FAMILY",
            input_hash=self.batch.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=fixtures.FIXED_EXPIRY,
            one_shot=True,
            operation_id="family-batch-permit",
        )
        self.writer.open_batch(
            batch_spec=self.batch,
            permit=batch_permit,
            operation_id="family-open-batch",
        )

    def _declare_and_permit(self, *, subject: dict[str, str], tag: str):
        declared = self.writer.declare_job(
            spec=fixtures.job_spec(self.writer, subject),
            operation_id=f"{tag}-declare",
        )
        permit = self.writer.issue_permit(
            kind=PermitKind.JOB,
            subject_kind=SubjectKind.JOB,
            subject_id=declared.result["job_id"],
            input_hash=declared.result["job_hash"],
            actions=("start_job",),
            scope=("job",),
            expires_at_utc=fixtures.FIXED_EXPIRY,
            one_shot=True,
            operation_id=f"{tag}-permit",
        )
        return permit

    def test_typed_manifest_is_exact_and_untyped_size_is_not_authority(self) -> None:
        acceptance = self.batch.acceptance()
        self.assertEqual(
            acceptance["concurrent_family"],
            self.manifest.to_identity_payload(),
        )
        with LocalIndex(self.writer.index_path) as index:
            record = index.get("batch-open", self.batch.identity)
        assert record is not None
        self.assertEqual(
            record.payload["spec"]["acceptance_profile"]["concurrent_family"],
            self.manifest.to_identity_payload(),
        )
        with self.assertRaisesRegex(BatchSpecError, "typed concurrent family"):
            BatchSpec(
                batch_id="BAT-UNTYPED",
                study_id="STU-FAMILY",
                study_hash="a" * 64,
                display_name="untyped family fixture",
                max_trials=2,
                max_compute_seconds=60,
                max_wall_seconds=90,
                stop_rule="stop at the claimed family",
                acceptance_profile={"concurrent_family_size": 2},
                adaptive_basis={
                    "uncertainty": "fixture",
                    "causal_complexity": "fixture",
                    "surface_curvature": "fixture",
                    "compute_cost": "bounded",
                    "expected_information_value": "positive",
                    "portfolio_opportunity_cost": "declared",
                },
            )

    def test_job_declaration_and_start_wait_for_every_exact_family_trial(self) -> None:
        self.writer.register_trial(
            executable=self.members[0],
            operation_id="family-register-first",
        )
        before = self.writer.read_control()
        with self.assertRaisesRegex(TransitionError, "1 missing"):
            self.writer.declare_job(
                spec=fixtures.job_spec(
                    self.writer,
                    {"kind": "Executable", "id": self.members[0].identity},
                ),
                operation_id="family-declare-before-registration",
            )
        self.assertEqual(self.writer.read_control(), before)

        self.writer.register_trial(
            executable=self.members[1],
            operation_id="family-register-second",
        )
        permit = self._declare_and_permit(
            subject={"kind": "Executable", "id": self.members[0].identity},
            tag="family-first-job",
        )
        started = self.writer.start_job(
            permit=permit,
            operation_id="family-start-after-registration",
        )
        self.assertEqual(started.result["job_id"], permit.subject.subject_id)
        with LocalIndex(self.writer.index_path) as index:
            head = index.event_head(f"permit:{permit.permit_id}")
        assert head is not None
        self.assertEqual(head.sequence, 2)

    def test_family_batch_rejects_a_non_member_job_before_start(self) -> None:
        for ordinal, member in enumerate(self.members, start=1):
            self.writer.register_trial(
                executable=member,
                operation_id=f"family-register-{ordinal}",
            )
        before = self.writer.read_control()
        with self.assertRaisesRegex(TransitionError, "outside the exact"):
            self.writer.declare_job(
                spec=fixtures.job_spec(
                    self.writer,
                    {"kind": "Study", "id": "STU-FAMILY"},
                ),
                operation_id="family-reject-non-member-declare",
            )
        self.assertEqual(self.writer.read_control(), before)


if __name__ == "__main__":
    unittest.main()
