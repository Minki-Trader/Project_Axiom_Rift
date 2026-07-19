from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.prospective_engineering_reentry import (
    ProspectiveEngineeringReentryValidationError,
    require_prospective_engineering_reentry,
)
from axiom_rift.operations.repair_semantic_change_authority import (
    build_semantic_change_successor_artifact,
)
from axiom_rift.research.forest_replay import build_p0_composite_validation_plan
from axiom_rift.research.prospective_engineering_reentry import (
    ProspectiveEngineeringReentry,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext
from axiom_rift.research.semantic_question import (
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.storage.index import IndexRecord


class _MemoryIndex:
    def __init__(self, records: tuple[IndexRecord, ...]) -> None:
        self.records = {
            (record.kind, record.record_id): record for record in records
        }

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self.records.get((kind, record_id))

    def records_by_kind(self, kind: str) -> tuple[IndexRecord, ...]:
        return tuple(
            record
            for (record_kind, _), record in self.records.items()
            if record_kind == kind
        )


class ProspectiveEngineeringReentryValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mission_id = "MIS-PROSPECTIVE-REENTRY-VALIDATION"
        cls.snapshot_id = "portfolio:" + "4" * 64
        cls.axis_id = "axis-risk-reentry"
        cls.axis_identity = "axis:" + "5" * 64
        cls.predecessor_study_id = "STU-0122"
        cls.successor_study_id = "STU-0123"
        cls.diagnosis_id = "diagnosis:" + "3" * 64
        cls.close_id = "2" * 64
        cls.completion_id = "1" * 64
        cls.disposition_id = "6" * 64
        cls.disposition_hash = "7" * 64
        cls.job_id = "job:" + "a" * 64
        cls.question_core = SemanticQuestionCore(
            causal_question="Does the corrected intent calendar reduce loss skip risk?",
            changed_variables=("intent_calendar_policy",),
            controlled_variables=("data", "split"),
        )
        executable_plan = build_p0_composite_validation_plan(
            mission_id=cls.mission_id,
            historical_context=HistoricalSearchContext(
                context_id="history:prospective-reentry-validation",
                prior_global_exposure_count=470,
            ),
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=992,
        )
        cls.executable = executable_plan.baseline_executable
        cls.successor_artifact = build_semantic_change_successor_artifact(
            successor_scope="executable",
            job_spec={
                "evidence_subject": {
                    "id": cls.executable.identity,
                    "kind": "Executable",
                },
                "expected_outputs": [
                    "scientific/STU-0123/batch_result.json",
                ],
                "implementation_identity": "b" * 64,
            },
            executable_manifest=cls.executable.to_identity_payload(),
            implementation_protocol="prospective corrected protocol v1",
        )
        cls.successor_bytes = canonical_bytes(cls.successor_artifact)
        cls.successor_hash = sha256(cls.successor_bytes).hexdigest()

    def _lineage(
        self,
        *,
        include_diagnosis: bool = True,
    ) -> SemanticQuestionLineageProposal:
        basis = [
            "job-completed:" + self.completion_id,
            "study-close:" + self.close_id,
            "study-open:" + self.predecessor_study_id,
        ]
        if include_diagnosis:
            basis.append("study-diagnosis:" + self.diagnosis_id)
        return SemanticQuestionLineageProposal(
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            predecessor_core_id=self.question_core.identity,
            successor_core_id=self.question_core.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale="Retry the same question under the validated correction.",
            basis_record_ids=tuple(basis),
        )

    def _plan(
        self,
        *,
        include_diagnosis: bool = True,
    ) -> ProspectiveEngineeringReentry:
        return ProspectiveEngineeringReentry(
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot_id,
            target_axis_id=self.axis_id,
            target_axis_identity=self.axis_identity,
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            study_diagnosis_id=self.diagnosis_id,
            study_close_record_id=self.close_id,
            completion_record_id=self.completion_id,
            disposition_record_id=self.disposition_id,
            disposition_hash=self.disposition_hash,
            successor_artifact_hash=self.successor_hash,
            successor_baseline_executable_id=self.executable.identity,
            portfolio_action="deepen",
            semantic_question_lineage=self._lineage(
                include_diagnosis=include_diagnosis
            ),
        )

    def _records(self) -> tuple[IndexRecord, ...]:
        return (
            IndexRecord(
                kind="study-open",
                record_id=self.predecessor_study_id,
                subject="Study:" + self.predecessor_study_id,
                status="open",
                fingerprint="c" * 64,
                payload={
                    "mission_id": self.mission_id,
                    "question": self.question_core.to_identity_payload(),
                },
            ),
            IndexRecord(
                kind="study-close",
                record_id=self.close_id,
                subject="Study:" + self.predecessor_study_id,
                status="not_evaluable",
                fingerprint="d" * 64,
                payload={"mission_id": self.mission_id},
            ),
            IndexRecord(
                kind="job-completed",
                record_id=self.completion_id,
                subject="Job:" + self.job_id,
                status="completed",
                fingerprint="e" * 64,
                payload={
                    "engineering_disposition_record_id": self.disposition_id,
                    "failure": {"failure_kind": "engineering"},
                    "job_id": self.job_id,
                    "scientific": None,
                },
            ),
            IndexRecord(
                kind="repair-close",
                record_id=self.disposition_id,
                subject="Job:" + self.job_id,
                status="completed",
                fingerprint="f" * 64,
                payload={
                    "disposition": {
                        "disposition": "requires_scientific_change",
                        "job_id": self.job_id,
                    },
                    "disposition_hash": self.disposition_hash,
                    "disposition_validation": {
                        "semantic_change_validation": {
                            "schema": (
                                "engineering_semantic_change_necessity_"
                                "validation.v2"
                            ),
                            "validation": {
                                "facts": {
                                    "binding": {
                                        "context": {
                                            "proposed_successor_artifact_sha256": (
                                                self.successor_hash
                                            )
                                        }
                                    }
                                },
                                "result_artifact_hashes": [self.successor_hash],
                                "schema": (
                                    "engineering_repair_registered_validation.v2"
                                ),
                                "verdict": "passed",
                                "verification_kind": "semantic_change",
                            },
                        }
                    },
                },
            ),
            IndexRecord(
                kind="study-diagnosis",
                record_id=self.diagnosis_id,
                subject="Study:" + self.predecessor_study_id,
                status="engineering_gap",
                fingerprint="0" * 64,
                payload={
                    "evidence_basis": [
                        {
                            "kind": "job-completed",
                            "record_id": self.completion_id,
                        },
                        {
                            "kind": "study-close",
                            "record_id": self.close_id,
                        },
                    ],
                    "mission_id": self.mission_id,
                    "portfolio_axis_id": self.axis_id,
                    "portfolio_axis_identity": self.axis_identity,
                    "portfolio_snapshot_id": self.snapshot_id,
                    "study_close_record_id": self.close_id,
                },
            ),
        )

    def _validate(
        self,
        index: _MemoryIndex,
        plan: ProspectiveEngineeringReentry | None = None,
    ) -> dict[str, object]:
        return require_prospective_engineering_reentry(
            index,  # type: ignore[arg-type]
            artifact_reader=lambda digest: (
                self.successor_bytes
                if digest == self.successor_hash
                else b"unverified"
            ),
            plan=self._plan() if plan is None else plan,
            mission_id=self.mission_id,
            portfolio_snapshot_id=self.snapshot_id,
            portfolio_action="deepen",
            target_axis={
                "axis_id": self.axis_id,
                "axis_identity": self.axis_identity,
            },
            baseline_executable_id=self.executable.identity,
        )

    def test_exact_predecessor_and_successor_join_without_scientific_credit(
        self,
    ) -> None:
        result = self._validate(_MemoryIndex(self._records()))
        self.assertEqual(result["successor_artifact_hash"], self.successor_hash)
        self.assertEqual(result["scientific_trial_delta"], 0)
        self.assertEqual(result["scientific_claim_delta"], 0)
        self.assertEqual(result["scientific_failure_delta"], 0)

    def test_registered_reproducible_cache_output_is_allowed(self) -> None:
        artifact = deepcopy(self.successor_artifact)
        cache_path = "local/cache/prospective-successor.json"
        artifact["job_spec"]["expected_outputs"].append(cache_path)
        artifact["job_spec"]["output_classes"] = {
            cache_path: "reproducible_cache",
        }
        self.successor_bytes = canonical_bytes(artifact)
        self.successor_hash = sha256(self.successor_bytes).hexdigest()

        result = self._validate(_MemoryIndex(self._records()))

        self.assertEqual(result["successor_artifact_hash"], self.successor_hash)

    def test_unclassified_non_scientific_output_fails_closed(self) -> None:
        artifact = deepcopy(self.successor_artifact)
        artifact["job_spec"]["expected_outputs"].append(
            "local/cache/unclassified-successor.json"
        )
        self.successor_bytes = canonical_bytes(artifact)
        self.successor_hash = sha256(self.successor_bytes).hexdigest()

        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryValidationError,
            "distinct Study protocol",
        ):
            self._validate(_MemoryIndex(self._records()))

    def test_disposition_artifact_binding_tamper_fails_closed(self) -> None:
        records = list(self._records())
        original = records[3]
        payload = deepcopy(original.payload)
        payload["disposition_validation"]["semantic_change_validation"][
            "validation"
        ]["facts"]["binding"]["context"][
            "proposed_successor_artifact_sha256"
        ] = "9" * 64
        records[3] = IndexRecord(
            kind=original.kind,
            record_id=original.record_id,
            subject=original.subject,
            status=original.status,
            fingerprint=original.fingerprint,
            payload=payload,
        )
        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryValidationError,
            "validated successor artifact",
        ):
            self._validate(_MemoryIndex(tuple(records)))

    def test_missing_lineage_basis_and_predecessor_trial_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryValidationError,
            "exact predecessor",
        ):
            self._validate(
                _MemoryIndex(self._records()),
                self._plan(include_diagnosis=False),
            )

        trial = IndexRecord(
            kind="trial",
            record_id=self.executable.identity,
            subject="Executable:" + self.executable.identity,
            status="completed",
            fingerprint="8" * 64,
            payload={"study_id": self.predecessor_study_id},
        )
        with self.assertRaisesRegex(
            ProspectiveEngineeringReentryValidationError,
            "distinct Study protocol",
        ):
            self._validate(_MemoryIndex((*self._records(), trial)))


if __name__ == "__main__":
    unittest.main()
