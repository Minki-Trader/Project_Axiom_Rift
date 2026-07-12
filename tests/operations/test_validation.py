from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidatedEvidence,
    ValidationArtifact,
    validator_identity,
)


IMPLEMENTATION_PATH = Path(__file__).resolve()
IMPLEMENTATION_HASH = sha256(IMPLEMENTATION_PATH.read_bytes()).hexdigest()


class ImmutableRequestValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "immutable_request_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def __init__(self) -> None:
        self.mutation_rejected = False
        self.preflight_mutation_rejected = False

    def preflight_binding(self, *, domain: str, binding: object) -> None:
        self.asserted_domain = domain
        try:
            binding["forged"] = True  # type: ignore[index]
        except TypeError:
            self.preflight_mutation_rejected = True

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        try:
            request.binding["forged"] = True  # type: ignore[index]
        except TypeError:
            self.mutation_rejected = True
        for artifact in request.artifacts:
            artifact.read_bytes()
        return ValidatedEvidence(verdict="passed")


class ArtifactMutationValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "artifact_mutation_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        artifact = request.artifacts[0]
        artifact.read_bytes()
        artifact._source.write_bytes(b"mutated after validator read")  # noqa: SLF001
        return ValidatedEvidence(verdict="passed")


class UnreadArtifactValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "unread_artifact_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        return ValidatedEvidence(verdict="passed")


class WrongIdentityValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "wrong_identity_fixture.v1"
    validator_id = "validator:" + "f" * 64

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        return ValidatedEvidence(verdict="passed")


def request_for(
    *, validator_id: str, artifact: ValidationArtifact
) -> EvidenceValidationRequest:
    return EvidenceValidationRequest(
        domain="scientific",
        validator_id=validator_id,
        validation_plan_hash="b" * 64,
        job_id="job:fixture",
        job_hash="c" * 64,
        mission_id="MIS-VALIDATION",
        evidence_subject={"kind": "Executable", "id": "executable:fixture"},
        binding={"planned_claims": ["claim-a"]},
        result_manifest={"claims": ["claim-a"]},
        artifacts=(artifact,),
    )


class ValidatorBoundaryTests(unittest.TestCase):
    def test_binding_preflight_is_dispatched_with_an_immutable_copy(self) -> None:
        validator = ImmutableRequestValidator()
        registry = EvidenceValidatorRegistry((validator,))

        registry.preflight_binding(
            validator_id=validator.validator_id,
            domain="scientific",
            binding={"planned_claims": ["claim-a"]},
        )

        self.assertEqual(validator.asserted_domain, "scientific")
        self.assertTrue(validator.preflight_mutation_rejected)

    def test_request_is_deeply_immutable_to_registered_validator(self) -> None:
        with TemporaryDirectory() as root:
            source = Path(root) / "artifact.bin"
            source.write_bytes(b"immutable validator artifact")
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(source.read_bytes()).hexdigest(),
                _source=source,
            )
            validator = ImmutableRequestValidator()
            registry = EvidenceValidatorRegistry((validator,))
            registry.validate(
                request_for(validator_id=validator.validator_id, artifact=artifact)
            )
            self.assertTrue(validator.mutation_rejected)

    def test_validator_cannot_mutate_durable_artifact_after_read(self) -> None:
        with TemporaryDirectory() as root:
            source = Path(root) / "artifact.bin"
            source.write_bytes(b"durable validator artifact")
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(source.read_bytes()).hexdigest(),
                _source=source,
            )
            validator = ArtifactMutationValidator()
            registry = EvidenceValidatorRegistry((validator,))
            with self.assertRaises(EvidenceValidationError):
                registry.validate(
                    request_for(validator_id=validator.validator_id, artifact=artifact)
                )

    def test_unread_artifact_and_wrong_implementation_identity_fail_closed(self) -> None:
        with self.assertRaises(EvidenceValidationError):
            EvidenceValidatorRegistry((WrongIdentityValidator(),))
        with TemporaryDirectory() as root:
            source = Path(root) / "artifact.bin"
            source.write_bytes(b"unread validator artifact")
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(source.read_bytes()).hexdigest(),
                _source=source,
            )
            validator = UnreadArtifactValidator()
            registry = EvidenceValidatorRegistry((validator,))
            with self.assertRaises(EvidenceValidationError):
                registry.validate(
                    request_for(validator_id=validator.validator_id, artifact=artifact)
                )


if __name__ == "__main__":
    unittest.main()
