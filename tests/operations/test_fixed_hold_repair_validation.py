from __future__ import annotations

from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.operations.fixed_hold_repair_equivalence as equivalence_module
from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.fixed_hold_repair_equivalence import (
    fixed_hold_authority_correction_verification_claim_manifest,
)
from axiom_rift.operations.fixed_hold_repair_validation import (
    FIXED_HOLD_REPAIR_ATTEMPT_PROTOCOL,
    FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID,
    FixedHoldRepairAttemptValidator,
)
from axiom_rift.operations.repair_validation import (
    build_repair_candidate_validation_context,
    build_repair_validation_plan,
    repair_validation_binding,
)
from axiom_rift.operations.validation import (
    EngineeringRepairValidationRequest,
    EvidenceValidationError,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.storage.evidence import EvidenceStore


class FixedHoldRepairValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence = EvidenceStore(self.temporary.name)
        self.job_hash = "1" * 64
        self.job_id = "job:" + self.job_hash
        self.repair_id = "repair:" + "2" * 64
        self.previous_basis_hash = "5" * 64
        self.reproduction = self.evidence.finalize(
            b"fixed-hold failure reproduction"
        )
        source_artifact = self.evidence.finalize(
            b"fixed-hold corrected implementation source"
        )
        new_manifest = self.evidence.finalize(
            canonical_bytes(
                {
                    "artifact_hashes": [source_artifact.sha256],
                    "callable_identity": "fixture.fixed_hold.execute.v1",
                    "protocol": "python.source.fixed_hold.fixture.v1",
                    "schema": "job_implementation_evidence.v1",
                }
            )
        )
        self.new_basis_hash = new_manifest.sha256
        profile = {
            "allowed_changed_symbols": {},
            "old_implementation_identity": self.previous_basis_hash,
            "required_changed_paths": (
                "axiom_rift/operations/running_job_context.py",
            ),
            "source_paths": (
                "axiom_rift/operations/running_job_context.py",
            ),
        }
        profile_patch = patch.dict(
            equivalence_module._CORRECTION_PROFILES,
            {self.new_basis_hash: profile},
        )
        profile_patch.start()
        self.addCleanup(profile_patch.stop)
        semantic_plan = self.evidence.finalize(b"semantic plan")
        semantic_result = self.evidence.finalize(b"semantic result")
        semantic_measurement = self.evidence.finalize(b"semantic measurement")
        inner_new_evidence = sorted(
            {
                self.new_basis_hash,
                source_artifact.sha256,
                semantic_plan.sha256,
                semantic_result.sha256,
                semantic_measurement.sha256,
            }
        )
        self.inner_proof_payload = {
            "changed_dimension": "implementation",
            "explanation": "resolve the exact fixed-hold authority defect",
            "job_hash": self.job_hash,
            "job_id": self.job_id,
            "new_evidence_hashes": inner_new_evidence,
            "new_implementation_identity": self.new_basis_hash,
            "previous_implementation_identity": self.previous_basis_hash,
            "repair_id": self.repair_id,
            "reproduction_evidence_hashes": [self.reproduction.sha256],
            "schema": "running_job_implementation_repair.v2",
            "semantic_equivalence_measurement_artifact_hashes": [
                semantic_measurement.sha256
            ],
            "semantic_equivalence_result_manifest_hash": semantic_result.sha256,
            "semantic_equivalence_validation_plan_hash": semantic_plan.sha256,
            "semantic_equivalence_validator_id": "validator:" + "a" * 64,
        }
        inner_proof = self.evidence.finalize(
            canonical_bytes(self.inner_proof_payload)
        )
        self.implementation_proof_hash = inner_proof.sha256
        result = fixed_hold_authority_correction_verification_claim_manifest(
            new_implementation_identity=self.new_basis_hash
        )
        self.result = self.evidence.finalize(canonical_bytes(result))
        self.context = build_repair_candidate_validation_context(
            bound_validation_observations=(),
            cause_hash="6" * 64,
            changed_dimension="implementation",
            explanation=self.inner_proof_payload["explanation"],
            implementation_proof_hash=self.implementation_proof_hash,
            job_hash=self.job_hash,
            job_id=self.job_id,
            new_basis_hash=self.new_basis_hash,
            new_evidence_hashes=tuple(
                sorted(
                    {
                        self.implementation_proof_hash,
                        *inner_new_evidence,
                    }
                )
            ),
            previous_basis_hash=self.previous_basis_hash,
            prior_attempt_record_id=None,
            prior_validation_observation_head=None,
            repair_axis_id="implementation-source-closure",
            repair_id=self.repair_id,
            reproduction_evidence_hashes=(self.reproduction.sha256,),
            resume_action="continue_batch",
        )

    def _request(
        self,
        *,
        context: dict[str, object] | None = None,
    ) -> EngineeringRepairValidationRequest:
        selected_context = self.context if context is None else context
        implementation_proof_hash = str(
            selected_context["implementation_proof_hash"]
        )
        role_hashes = {
            "implementation_proof": implementation_proof_hash,
            "new_implementation_manifest": self.new_basis_hash,
            "reproduction:0000": self.reproduction.sha256,
            "validation_result": self.result.sha256,
        }
        artifact_roles = tuple(sorted(role_hashes.items()))
        binding = repair_validation_binding(
            verification_kind="candidate",
            mission_id="MIS-FIXED-HOLD-REPAIR",
            protocol=FIXED_HOLD_REPAIR_ATTEMPT_PROTOCOL,
            context=selected_context,
            artifact_roles=artifact_roles,
        )
        plan = self.evidence.finalize(
            canonical_bytes(
                build_repair_validation_plan(
                    validator_id=FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID,
                    binding=binding,
                )
            )
        )
        return EngineeringRepairValidationRequest(
            validator_id=FIXED_HOLD_REPAIR_ATTEMPT_VALIDATOR_ID,
            validation_plan_hash=plan.sha256,
            mission_id="MIS-FIXED-HOLD-REPAIR",
            job_id=self.job_id,
            job_hash=self.job_hash,
            repair_id=self.repair_id,
            verification_kind="candidate",
            evidence_subject={"kind": "Repair", "id": self.repair_id},
            binding=binding,
            result_manifest={
                "protocol": FIXED_HOLD_REPAIR_ATTEMPT_PROTOCOL,
                "result_artifact_hashes": sorted(role_hashes.values()),
                "schema": "engineering_repair_validation_dispatch.v1",
                "verification_kind": "candidate",
            },
            artifacts=(
                ValidationArtifact(
                    output_name="validation_plan",
                    sha256=plan.sha256,
                    _source=self.evidence.verified_path(plan.sha256),
                ),
                *(
                    ValidationArtifact(
                        output_name=name,
                        sha256=identity,
                        _source=self.evidence.verified_path(identity),
                    )
                    for name, identity in artifact_roles
                ),
            ),
            engineering_fixture=False,
        )

    def test_registered_validator_recomputes_exact_fixed_hold_result(self) -> None:
        request = self._request()
        validated, trace = EvidenceValidatorRegistry(
            (FixedHoldRepairAttemptValidator(),)
        ).validate(request)
        self.assertEqual(validated.verdict, "passed")
        self.assertEqual(
            validated.measurement_artifact_hashes,
            tuple(sorted(request.result_manifest["result_artifact_hashes"])),
        )
        self.assertTrue(validated.facts["cause_resolved"])
        self.assertTrue(validated.facts["material_change"])
        self.assertFalse(validated.facts["failure_reproduced"])
        self.assertEqual(trace.declared_artifact_count, 5)
        self.assertEqual(trace.opened_artifact_count, 5)

    def test_validator_rejects_context_that_does_not_match_job(self) -> None:
        context = {**self.context, "job_hash": "7" * 64}
        request = self._request(context=context)
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "does not prove material correction",
        ):
            EvidenceValidatorRegistry(
                (FixedHoldRepairAttemptValidator(),)
            ).validate(request)

    def test_validator_rejects_inner_proof_that_diverges_from_context(self) -> None:
        tampered = self.evidence.finalize(
            canonical_bytes({**self.inner_proof_payload, "job_hash": "7" * 64})
        )
        context = {
            **self.context,
            "implementation_proof_hash": tampered.sha256,
            "new_evidence_hashes": sorted(
                {
                    *self.context["new_evidence_hashes"],
                    tampered.sha256,
                }
                - {self.implementation_proof_hash}
            ),
        }
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "inner proof or implementation is invalid",
        ):
            EvidenceValidatorRegistry(
                (FixedHoldRepairAttemptValidator(),)
            ).validate(self._request(context=context))

    def test_validator_rejects_missing_reproduction_artifact(self) -> None:
        request = self._request()
        request = replace(
            request,
            artifacts=tuple(
                artifact
                for artifact in request.artifacts
                if artifact.output_name != "reproduction:0000"
            ),
        )
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "artifacts are incomplete or ambiguous",
        ):
            EvidenceValidatorRegistry(
                (FixedHoldRepairAttemptValidator(),)
            ).validate(request)

    def test_unregistered_validator_cannot_authorize_repair(self) -> None:
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "no registered validator",
        ):
            EvidenceValidatorRegistry().validate(self._request())


if __name__ == "__main__":
    unittest.main()
