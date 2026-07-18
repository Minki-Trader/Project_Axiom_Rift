from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.repair_protocol import (
    RepairProtocolError,
    parse_engineering_failure_disposition,
    parse_repair_attempt_proof,
)


def digest(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


class RepairProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job_id = f"job:{digest('job')}"
        self.repair_id = f"repair:{digest('repair')}"
        self.job_hash = digest("job-hash")
        self.cause_hash = digest("cause")
        self.reproduction = digest("reproduction")
        self.previous_basis = digest("previous-basis")
        self.new_basis = digest("new-basis")
        self.verification = digest("verification")
        self.verified: list[str] = []
        self.evidence: dict[str, bytes] = {}
        self.disposition_attempts: tuple[dict[str, object], ...] = ()

    def attempt(self, **changes: object) -> bytes:
        requested_new_basis = changes.get("new_basis_hash", self.new_basis)
        check_plan = canonical_bytes(
            {
                "new_basis_hash": requested_new_basis,
                "schema": "fixture_repair_check_plan.v1",
            }
        )
        check_plan_hash = sha256(check_plan).hexdigest()
        self.evidence[check_plan_hash] = check_plan
        receipt = canonical_bytes(
            {
                "cause_hash": self.cause_hash,
                "changed_dimension": "cause",
                "check_plan_hash": check_plan_hash,
                "job_hash": self.job_hash,
                "job_id": self.job_id,
                "new_basis_hash": requested_new_basis,
                "outcome": "repaired",
                "repair_id": self.repair_id,
                "result_artifact_hashes": [self.verification],
                "resume_action": "resume_exact_job",
                "schema": "repair_verification_receipt.v1",
                "scientific_semantics_changed": False,
                "verdict": "passed",
                "verification_method": "focused independent fixture check",
            }
        )
        receipt_hash = sha256(receipt).hexdigest()
        self.evidence[receipt_hash] = receipt
        value: dict[str, object] = {
            "cause_hash": self.cause_hash,
            "changed_dimension": "cause",
            "explanation": "changed the suspected engineering cause",
            "failure_observation": None,
            "implementation_proof_hash": None,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "new_basis_hash": self.new_basis,
            "new_evidence_hashes": [self.new_basis],
            "outcome": "repaired",
            "previous_basis_hash": self.previous_basis,
            "prior_attempt_record_id": None,
            "repair_id": self.repair_id,
            "reproduction_evidence_hashes": [self.reproduction],
            "resume_action": "resume_exact_job",
            "schema": "running_job_repair_attempt.v1",
            "scientific_semantics_changed": False,
            "verification_evidence_hashes": [receipt_hash],
        }
        value.update(changes)
        return canonical_bytes(value)

    def parse_attempt(self, document: bytes):
        return parse_repair_attempt_proof(
            document,
            expected_outcome="repaired",
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            cause_hash=self.cause_hash,
            resume_action="resume_exact_job",
            reproduction_evidence_hashes=(self.reproduction,),
            prior_attempt_record_id=None,
            previous_basis_hash=self.previous_basis,
            used_basis_hashes=(self.previous_basis,),
            read_evidence=self.evidence.__getitem__,
            verify_evidence=self.verified.append,
        )

    def test_repaired_attempt_binds_change_and_independent_verification(self) -> None:
        proof = self.parse_attempt(self.attempt())

        self.assertEqual(proof.new_basis_hash, self.new_basis)
        self.assertEqual(len(self.verified), 3)
        self.assertEqual(self.verified[0], self.new_basis)
        self.assertIn(self.verified[1], self.evidence)
        self.assertEqual(self.verified[2], self.verification)

    def test_attempt_rejects_scientific_change_and_evidence_overlap(self) -> None:
        with self.assertRaisesRegex(
            RepairProtocolError,
            "scientific semantic change",
        ):
            self.parse_attempt(
                self.attempt(scientific_semantics_changed=True)
            )
        with self.assertRaisesRegex(RepairProtocolError, "must be distinct"):
            self.parse_attempt(
                self.attempt(
                    verification_evidence_hashes=[self.new_basis]
                )
            )

    def test_attempt_allows_reassessment_but_rejects_unlinked_basis(self) -> None:
        reassessed = self.parse_attempt(
            self.attempt(
                new_basis_hash=self.previous_basis,
                new_evidence_hashes=[self.previous_basis],
            )
        )
        self.assertEqual(reassessed.new_basis_hash, self.previous_basis)
        with self.assertRaisesRegex(RepairProtocolError, "changed evidence"):
            self.parse_attempt(
                self.attempt(new_evidence_hashes=[digest("unrelated")])
            )

    def disposition(
        self,
        *,
        observation_changes: Mapping[str, object] | None = None,
        basis_changes: Mapping[str, object] | None = None,
        **changes: object,
    ) -> bytes:
        disposition = str(
            changes.get("disposition", "requires_scientific_change")
        )
        basis_values = {
            "repair_exhausted_changed_causes": (
                False,
                False,
                "not_applicable",
                [],
            ),
            "repair_infeasible": (
                False,
                False,
                "not_applicable",
                [],
            ),
            "repair_nonpositive_expected_value": (
                True,
                False,
                "nonpositive",
                ["bounded remaining cause"],
            ),
            "requires_scientific_change": (
                False,
                True,
                "not_applicable",
                [],
            ),
        }
        repairable, semantic_change, expected_value, remaining = (
            basis_values[disposition]
        )
        check_plan = canonical_bytes(
            {
                "disposition": disposition,
                "schema": "fixture_engineering_disposition_check.v1",
            }
        )
        check_plan_hash = sha256(check_plan).hexdigest()
        self.evidence[check_plan_hash] = check_plan
        verification_results = {
            "repair_exhausted_changed_causes": "changed_causes_exhausted",
            "repair_infeasible": "repair_infeasible",
            "repair_nonpositive_expected_value": "nonpositive_expected_value",
            "requires_scientific_change": "scientific_change_required",
        }
        observation_value: dict[str, object] = {
            "cause_hash": self.cause_hash,
            "check_plan_hash": check_plan_hash,
            "disposition": disposition,
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "minimum_reproduction_evidence_hashes": [self.reproduction],
            "repair_attempts": list(self.disposition_attempts),
            "repair_id": self.repair_id,
            "result_artifact_hashes": [self.verification],
            "schema": "engineering_failure_disposition_observation.v1",
            "scientific_semantics_changed": False,
            "verification_method": "independent bounded assessment",
            "verification_result": verification_results[disposition],
        }
        if observation_changes is not None:
            observation_value.update(observation_changes)
        observation = canonical_bytes(observation_value)
        observation_hash = sha256(observation).hexdigest()
        self.evidence[observation_hash] = observation
        basis_value: dict[str, object] = {
            "cause_hash": self.cause_hash,
            "disposition": disposition,
            "expected_value": expected_value,
            "job_id": self.job_id,
            "observation_manifest_hash": observation_hash,
            "remaining_changed_causes": remaining,
            "repair_id": self.repair_id,
            "repairable_without_scientific_change": repairable,
            "schema": "engineering_failure_disposition_basis.v1",
            "scientific_semantics_change_required": semantic_change,
        }
        if basis_changes is not None:
            basis_value.update(basis_changes)
        basis = canonical_bytes(basis_value)
        basis_hash = sha256(basis).hexdigest()
        self.evidence[basis_hash] = basis
        value: dict[str, object] = {
            "basis_manifest_hash": basis_hash,
            "cause_hash": self.cause_hash,
            "disposition": disposition,
            "job_id": self.job_id,
            "rationale": "repair would change the registered contrast",
            "repair_id": self.repair_id,
            "repair_attempt_record_ids": [],
            "resume_condition": "register a successor Study",
            "schema": "engineering_failure_disposition.v1",
            "successor_scope": "study",
        }
        value.update(changes)
        return canonical_bytes(value)

    def parse_disposition(self, document: bytes):
        return parse_engineering_failure_disposition(
            document,
            job_id=self.job_id,
            job_hash=self.job_hash,
            repair_id=self.repair_id,
            cause_hash=self.cause_hash,
            reproduction_evidence_hashes=(self.reproduction,),
            repair_attempts=self.disposition_attempts,
            read_evidence=self.evidence.__getitem__,
            verify_evidence=self.verified.append,
        )

    def test_scientific_change_disposition_requires_successor_scope(self) -> None:
        parsed = self.parse_disposition(self.disposition())
        self.assertEqual(parsed.successor_scope, "study")
        with self.assertRaisesRegex(RepairProtocolError, "requires Executable"):
            self.parse_disposition(
                self.disposition(successor_scope=None)
            )

    def test_exhaustion_disposition_requires_failed_attempt_identity(self) -> None:
        with self.assertRaisesRegex(RepairProtocolError, "requires failed"):
            self.parse_disposition(
                self.disposition(
                    disposition="repair_exhausted_changed_causes",
                    successor_scope=None,
                )
            )

    def test_disposition_rejects_untyped_existing_observation_artifact(self) -> None:
        self.evidence[self.verification] = b"existing but untyped observation"
        with self.assertRaisesRegex(RepairProtocolError, "canonical evidence"):
            self.parse_disposition(
                self.disposition(
                    basis_changes={
                        "observation_manifest_hash": self.verification,
                    }
                )
            )

    def test_disposition_observation_binds_job_cause_and_result(self) -> None:
        with self.assertRaisesRegex(RepairProtocolError, "exact context"):
            self.parse_disposition(
                self.disposition(
                    observation_changes={"job_hash": digest("other-job")}
                )
            )
        with self.assertRaisesRegex(RepairProtocolError, "exact context"):
            self.parse_disposition(
                self.disposition(
                    observation_changes={"cause_hash": digest("other-cause")}
                )
            )
        with self.assertRaisesRegex(RepairProtocolError, "exact context"):
            self.parse_disposition(
                self.disposition(
                    observation_changes={"verification_result": "passed"}
                )
            )

    def test_disposition_observation_binds_exact_failed_attempt_receipt(self) -> None:
        attempt_record_id = digest("failed-attempt-record")
        attempt_proof_hash = digest("failed-attempt-proof")
        check_plan_hash = digest("failed-attempt-plan")
        result_hash = digest("failed-attempt-result")
        receipt = canonical_bytes(
            {
                "cause_hash": self.cause_hash,
                "changed_dimension": "cause",
                "check_plan_hash": check_plan_hash,
                "job_hash": self.job_hash,
                "job_id": self.job_id,
                "new_basis_hash": self.new_basis,
                "outcome": "failed",
                "repair_id": self.repair_id,
                "result_artifact_hashes": [result_hash],
                "resume_action": "resume_exact_job",
                "schema": "repair_verification_receipt.v1",
                "scientific_semantics_changed": False,
                "verdict": "failure_reproduced",
                "verification_method": "focused independent fixture check",
            }
        )
        receipt_hash = sha256(receipt).hexdigest()
        self.evidence[receipt_hash] = receipt
        self.disposition_attempts = (
            {
                "attempt_proof_hash": attempt_proof_hash,
                "changed_dimension": "cause",
                "new_basis_hash": self.new_basis,
                "repair_attempt_record_id": attempt_record_id,
                "repair_axis_id": "axis:failed-attempt-cause",
                "verification_receipt_hashes": [receipt_hash],
            },
        )
        parsed = self.parse_disposition(
            self.disposition(
                repair_attempt_record_ids=[attempt_record_id],
            )
        )
        self.assertEqual(parsed.repair_attempt_record_ids, (attempt_record_id,))

        with self.assertRaisesRegex(RepairProtocolError, "changes the Repair attempts"):
            self.parse_disposition(
                self.disposition(
                    repair_attempt_record_ids=[attempt_record_id],
                    observation_changes={"repair_attempts": []},
                )
            )
        bad_receipt = dict(self.disposition_attempts[0])
        bad_receipt["verification_receipt_hashes"] = [digest("other-receipt")]
        with self.assertRaisesRegex(RepairProtocolError, "changes the Repair attempts"):
            self.parse_disposition(
                self.disposition(
                    repair_attempt_record_ids=[attempt_record_id],
                    observation_changes={"repair_attempts": [bad_receipt]},
                )
            )

        invalid_result = dict(
            parse_canonical(receipt)
        )
        invalid_result["verdict"] = "passed"
        invalid_receipt = canonical_bytes(invalid_result)
        invalid_receipt_hash = sha256(invalid_receipt).hexdigest()
        self.evidence[invalid_receipt_hash] = invalid_receipt
        invalid_attempt = dict(self.disposition_attempts[0])
        invalid_attempt["verification_receipt_hashes"] = [
            invalid_receipt_hash
        ]
        self.disposition_attempts = (invalid_attempt,)
        with self.assertRaisesRegex(
            RepairProtocolError,
            "verification differs from its failed attempt",
        ):
            self.parse_disposition(
                self.disposition(
                    repair_attempt_record_ids=[attempt_record_id],
                )
            )


if __name__ == "__main__":
    unittest.main()
