from __future__ import annotations

from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.repair_candidate import (
    ACCEPTED_REPAIR_ATTEMPT_MODES,
    REPAIR_EVALUATION_MODES,
    ZERO_CREDIT_REPAIR_OBSERVATION_MODES,
    RepairCandidateError,
    build_repair_candidate,
    build_repair_evaluation,
    build_repair_new_failure_manifest,
    is_accepted_repair_attempt_mode,
    is_zero_credit_repair_observation_mode,
    parse_repair_candidate,
    parse_repair_evaluation,
    parse_repair_new_failure_manifest,
    repair_evaluation_authority_class,
)


def digest(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


class RepairCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repair_id = f"repair:{digest('repair')}"
        self.job_id = f"job:{digest('job')}"
        self.job_hash = digest("job-hash")
        self.cause_hash = digest("cause")
        self.previous_basis_hash = digest("previous-basis")
        self.new_basis_hash = digest("new-basis")
        self.prior_attempt_record_id = digest("prior-attempt")
        self.reproduction = digest("original-reproduction")
        self.implementation_proof = digest("implementation-proof")
        self.changed_artifact = digest("changed-artifact")
        self.verification_receipt = digest("verification-receipt")
        self.validator_id = f"validator:{digest('validator')}"
        self.validation_plan_hash = digest("validation-plan")
        self.registry_trace_hash = digest("registry-trace")
        self.verified: list[str] = []
        self.evidence: dict[str, bytes] = {}

    def candidate(self, **changes: object) -> dict[str, object]:
        values: dict[str, object] = {
            "repair_id": self.repair_id,
            "job_id": self.job_id,
            "job_hash": self.job_hash,
            "cause_hash": self.cause_hash,
            "repair_axis_id": "implementation-source-closure",
            "changed_dimension": "implementation",
            "previous_basis_hash": self.previous_basis_hash,
            "new_basis_hash": self.new_basis_hash,
            "prior_attempt_record_id": self.prior_attempt_record_id,
            "prior_validation_observation_head": None,
            "bound_validation_observations": (),
            "reproduction_evidence_hashes": (self.reproduction,),
            "new_evidence_hashes": tuple(
                sorted(
                    {
                        self.new_basis_hash,
                        self.implementation_proof,
                        self.changed_artifact,
                    }
                )
            ),
            "verification_evidence_hashes": (self.verification_receipt,),
            "implementation_proof_hash": self.implementation_proof,
            "explanation": "evaluate one bounded implementation correction",
            "resume_action": "resume_exact_job",
        }
        values.update(changes)
        return build_repair_candidate(**values)  # type: ignore[arg-type]

    def parse_candidate(self, payload: dict[str, object]):
        return parse_repair_candidate(
            canonical_bytes(payload),
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            cause_hash=self.cause_hash,
            previous_basis_hash=self.previous_basis_hash,
            prior_attempt_record_id=self.prior_attempt_record_id,
            reproduction_evidence_hashes=(self.reproduction,),
            resume_action="resume_exact_job",
            verify_evidence=self.verified.append,
        )

    def evaluation(self, mode: str, **changes: object) -> dict[str, object]:
        facts = {
            "repaired": (True, False, True),
            "failure_reproduced": (False, True, True),
            "new_failure": (None, None, True),
            "invalid_change": (None, None, False),
            "not_evaluable": (None, None, None),
            "validation_unavailable": (None, None, None),
        }
        cause_resolved, failure_reproduced, material_change = facts[mode]
        values: dict[str, object] = {
            "candidate_hash": sha256(
                canonical_bytes(self.candidate())
            ).hexdigest(),
            "validator_id": self.validator_id,
            "validation_plan_hash": self.validation_plan_hash,
            "registry_trace_hash": (
                None
                if mode == "validation_unavailable"
                else self.registry_trace_hash
            ),
            "mode": mode,
            "cause_resolved": cause_resolved,
            "failure_reproduced": failure_reproduced,
            "material_change": material_change,
            "new_failure_manifest_hash": None,
            "reason_code": (
                "measurement_is_ambiguous"
                if mode == "not_evaluable"
                else "candidate_change_is_not_material"
                if mode == "invalid_change"
                else "validator_absent_or_unregistered"
                if mode == "validation_unavailable"
                else None
            ),
        }
        values.update(changes)
        return build_repair_evaluation(
            **values,  # type: ignore[arg-type]
            read_evidence=self.evidence.__getitem__,
        )

    def parse_evaluation(self, payload: dict[str, object]):
        return parse_repair_evaluation(
            canonical_bytes(payload),
            candidate_hash=str(payload["candidate_hash"]),
            validator_id=self.validator_id,
            validation_plan_hash=self.validation_plan_hash,
            registry_trace_hash=payload[  # type: ignore[arg-type]
                "registry_trace_hash"
            ],
            read_evidence=self.evidence.__getitem__,
        )

    def new_failure_manifest(self, *, candidate_hash: str) -> str:
        payload = build_repair_new_failure_manifest(
            candidate_hash=candidate_hash,
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            interrupted_action="fixture.execute.v1",
            root_cause="the changed implementation raised a distinct exception",
            minimum_reproduction_evidence_hashes=(digest("new-reproduction"),),
        )
        content = canonical_bytes(payload)
        identity = sha256(content).hexdigest()
        self.evidence[identity] = content
        return identity

    def test_candidate_round_trip_binds_exact_active_context(self) -> None:
        payload = self.candidate()

        candidate = self.parse_candidate(payload)

        self.assertEqual(candidate.payload(), payload)
        self.assertEqual(
            candidate.sha256,
            sha256(canonical_bytes(payload)).hexdigest(),
        )
        self.assertEqual(
            self.verified,
            [
                self.reproduction,
                *payload["new_evidence_hashes"],  # type: ignore[misc]
                self.verification_receipt,
            ],
        )
        self.assertNotIn("outcome", payload)
        self.assertNotIn("failure_observation", payload)

    def test_candidate_rejects_caller_outcome_and_scientific_change(self) -> None:
        with_outcome = {**self.candidate(), "outcome": "repaired"}
        with self.assertRaisesRegex(RepairCandidateError, "schema"):
            self.parse_candidate(with_outcome)

        scientific_change = {
            **self.candidate(),
            "scientific_semantics_changed": True,
        }
        with self.assertRaisesRegex(RepairCandidateError, "scientific semantic"):
            self.parse_candidate(scientific_change)

    def test_candidate_rejects_context_spoof_and_noncanonical_document(self) -> None:
        another_cause = {**self.candidate(), "cause_hash": digest("another-cause")}
        with self.assertRaisesRegex(RepairCandidateError, "active Repair context"):
            self.parse_candidate(another_cause)

        with self.assertRaisesRegex(RepairCandidateError, "not canonical"):
            parse_repair_candidate(
                canonical_bytes(self.candidate()) + b"\n",
                repair_id=self.repair_id,
                job_id=self.job_id,
                job_hash=self.job_hash,
                cause_hash=self.cause_hash,
                previous_basis_hash=self.previous_basis_hash,
                prior_attempt_record_id=self.prior_attempt_record_id,
                reproduction_evidence_hashes=(self.reproduction,),
                resume_action="resume_exact_job",
            )

    def test_candidate_enforces_digest_lists_and_distinct_surfaces(self) -> None:
        with self.assertRaisesRegex(RepairCandidateError, "sorted unique"):
            self.candidate(
                new_evidence_hashes=(self.new_basis_hash, self.new_basis_hash)
            )
        with self.assertRaisesRegex(RepairCandidateError, "must be distinct"):
            self.candidate(
                verification_evidence_hashes=(self.new_basis_hash,)
            )
        with self.assertRaisesRegex(RepairCandidateError, "new basis is absent"):
            self.candidate(
                new_evidence_hashes=tuple(
                    sorted({self.implementation_proof, self.changed_artifact})
                )
            )

    def test_candidate_enforces_implementation_proof_role(self) -> None:
        with self.assertRaisesRegex(RepairCandidateError, "implementation proof"):
            self.candidate(implementation_proof_hash=None)

        cause_basis = digest("cause-basis")
        cause_candidate = self.candidate(
            changed_dimension="cause",
            new_basis_hash=cause_basis,
            new_evidence_hashes=(cause_basis,),
            implementation_proof_hash=None,
        )
        parsed = self.parse_candidate(cause_candidate)
        self.assertEqual(parsed.changed_dimension, "cause")
        with self.assertRaisesRegex(RepairCandidateError, "non-implementation"):
            self.candidate(
                changed_dimension="cause",
                new_basis_hash=cause_basis,
                new_evidence_hashes=tuple(
                    sorted({cause_basis, self.implementation_proof})
                ),
            )

    def test_complete_mode_matrix_round_trips(self) -> None:
        for mode in (
            "repaired",
            "failure_reproduced",
            "invalid_change",
            "not_evaluable",
            "validation_unavailable",
        ):
            with self.subTest(mode=mode):
                payload = self.evaluation(mode)
                parsed = self.parse_evaluation(payload)
                self.assertEqual(parsed.mode, mode)
                self.assertEqual(parsed.payload(), payload)

        candidate_hash = sha256(canonical_bytes(self.candidate())).hexdigest()
        manifest_hash = self.new_failure_manifest(candidate_hash=candidate_hash)
        payload = self.evaluation(
            "new_failure",
            candidate_hash=candidate_hash,
            new_failure_manifest_hash=manifest_hash,
        )
        parsed = self.parse_evaluation(payload)
        self.assertEqual(parsed.mode, "new_failure")
        self.assertTrue(parsed.zero_credit_observation)

    def test_mode_matrix_rejects_spoofed_facts_and_nullability(self) -> None:
        with self.assertRaisesRegex(RepairCandidateError, "mode matrix"):
            self.evaluation("repaired", cause_resolved=False)
        with self.assertRaisesRegex(RepairCandidateError, "nullable bool"):
            self.evaluation("repaired", material_change=1)
        with self.assertRaisesRegex(RepairCandidateError, "registered trace"):
            self.evaluation("failure_reproduced", registry_trace_hash=None)
        with self.assertRaisesRegex(RepairCandidateError, "cannot carry a reason"):
            self.evaluation("repaired", reason_code="caller_says_passed")

    def test_partial_is_not_a_mode_and_is_typed_as_unavailable_reason(self) -> None:
        values = {
            "candidate_hash": sha256(
                canonical_bytes(self.candidate())
            ).hexdigest(),
            "validator_id": self.validator_id,
            "validation_plan_hash": self.validation_plan_hash,
            "registry_trace_hash": None,
            "mode": "partial",
            "cause_resolved": None,
            "failure_reproduced": None,
            "material_change": None,
            "new_failure_manifest_hash": None,
            "reason_code": "partial_validator_result",
        }
        with self.assertRaisesRegex(RepairCandidateError, "mode is invalid"):
            build_repair_evaluation(**values)  # type: ignore[arg-type]

        payload = self.evaluation(
            "validation_unavailable",
            reason_code="partial_validator_result",
        )
        self.assertEqual(
            self.parse_evaluation(payload).reason_code,
            "partial_validator_result",
        )

    def test_unavailable_forbids_trace_and_requires_typed_reason(self) -> None:
        with self.assertRaisesRegex(RepairCandidateError, "typed reason"):
            self.evaluation(
                "validation_unavailable",
                reason_code="arbitrary_caller_reason",
            )
        with self.assertRaisesRegex(RepairCandidateError, "no registry trace"):
            self.evaluation(
                "validation_unavailable",
                registry_trace_hash=self.registry_trace_hash,
            )

    def test_new_failure_requires_exact_typed_manifest_and_no_other_mode_may_use_it(
        self,
    ) -> None:
        candidate_hash = sha256(canonical_bytes(self.candidate())).hexdigest()
        with self.assertRaisesRegex(RepairCandidateError, "typed failure manifest"):
            self.evaluation("new_failure", candidate_hash=candidate_hash)

        unrelated_manifest_hash = self.new_failure_manifest(
            candidate_hash=digest("another-candidate")
        )
        with self.assertRaisesRegex(RepairCandidateError, "another candidate"):
            self.evaluation(
                "new_failure",
                candidate_hash=candidate_hash,
                new_failure_manifest_hash=unrelated_manifest_hash,
            )

        manifest_hash = self.new_failure_manifest(candidate_hash=candidate_hash)
        with self.assertRaisesRegex(RepairCandidateError, "only new_failure"):
            self.evaluation(
                "repaired",
                candidate_hash=candidate_hash,
                new_failure_manifest_hash=manifest_hash,
            )

    def test_new_failure_manifest_binds_hash_context_and_distinct_reproduction(
        self,
    ) -> None:
        candidate_hash = sha256(canonical_bytes(self.candidate())).hexdigest()
        payload = build_repair_new_failure_manifest(
            candidate_hash=candidate_hash,
            repair_id=self.repair_id,
            job_id=self.job_id,
            job_hash=self.job_hash,
            interrupted_action="fixture.execute.v1",
            root_cause="a distinct parser exception",
            minimum_reproduction_evidence_hashes=(digest("new-reproduction"),),
        )
        parsed = parse_repair_new_failure_manifest(
            canonical_bytes(payload),
            candidate_hash=candidate_hash,
            verify_evidence=self.verified.append,
        )
        self.assertEqual(parsed.payload(), payload)
        self.assertEqual(self.verified, [digest("new-reproduction")])

        overlapping = {
            **payload,
            "minimum_reproduction_evidence_hashes": [candidate_hash],
        }
        with self.assertRaisesRegex(RepairCandidateError, "must be distinct"):
            parse_repair_new_failure_manifest(
                canonical_bytes(overlapping),
                candidate_hash=candidate_hash,
                forbidden_evidence_hashes=(candidate_hash,),
            )

    def test_evaluation_rejects_dispatch_spoof_and_surface_overlap(self) -> None:
        payload = self.evaluation("repaired")
        with self.assertRaisesRegex(RepairCandidateError, "authoritative dispatch"):
            parse_repair_evaluation(
                canonical_bytes(payload),
                candidate_hash=str(payload["candidate_hash"]),
                validator_id=f"validator:{digest('another-validator')}",
                validation_plan_hash=self.validation_plan_hash,
                registry_trace_hash=self.registry_trace_hash,
            )
        with self.assertRaisesRegex(RepairCandidateError, "must be distinct"):
            self.evaluation(
                "repaired",
                validation_plan_hash=str(payload["candidate_hash"]),
            )

    def test_mode_helpers_partition_every_evaluation_mode(self) -> None:
        self.assertEqual(
            ACCEPTED_REPAIR_ATTEMPT_MODES,
            frozenset({"repaired", "failure_reproduced"}),
        )
        self.assertEqual(
            ZERO_CREDIT_REPAIR_OBSERVATION_MODES,
            frozenset(
                {
                    "new_failure",
                    "invalid_change",
                    "not_evaluable",
                    "validation_unavailable",
                }
            ),
        )
        self.assertEqual(
            REPAIR_EVALUATION_MODES,
            ACCEPTED_REPAIR_ATTEMPT_MODES
            | ZERO_CREDIT_REPAIR_OBSERVATION_MODES,
        )
        for mode in REPAIR_EVALUATION_MODES:
            accepted = is_accepted_repair_attempt_mode(mode)
            observed = is_zero_credit_repair_observation_mode(mode)
            self.assertNotEqual(accepted, observed)
            self.assertEqual(
                repair_evaluation_authority_class(mode),
                "accepted_attempt" if accepted else "zero_credit_observation",
            )
        self.assertFalse(is_accepted_repair_attempt_mode("partial"))
        self.assertFalse(is_zero_credit_repair_observation_mode("partial"))
        with self.assertRaisesRegex(RepairCandidateError, "mode is invalid"):
            repair_evaluation_authority_class("partial")


if __name__ == "__main__":
    unittest.main()
