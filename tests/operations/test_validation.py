from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.validation import (
    ENGINEERING_RUNTIME_PLAN_HASH,
    EngineeringEvidenceValidationRequest,
    EngineeringFixtureValidator,
    EngineeringRetryFixtureValidator,
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidatedEvidence,
    ValidationArtifact,
    validator_identity,
    validator_implementation_sha256,
)


IMPLEMENTATION_PATH = Path(__file__).resolve()
IMPLEMENTATION_HASH = validator_implementation_sha256(
    implementation_path=IMPLEMENTATION_PATH
)


class ImmutableRequestValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "immutable_request_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def preflight_binding(self, *, domain: str, binding: object) -> None:
        if domain != "scientific":
            raise AssertionError("unexpected preflight domain")
        try:
            binding["forged"] = True  # type: ignore[index]
        except TypeError:
            return
        raise AssertionError("preflight binding was mutable")

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        try:
            request.binding["forged"] = True  # type: ignore[index]
        except TypeError:
            pass
        else:
            raise AssertionError("validation request binding was mutable")
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


FALSE_IMPLEMENTATION_PATH = (
    IMPLEMENTATION_PATH.parents[2]
    / "src"
    / "axiom_rift"
    / "operations"
    / "validation.py"
)


class FalseImplementationPathValidator:
    domains = frozenset({"scientific"})
    implementation_path = FALSE_IMPLEMENTATION_PATH
    protocol = "false_implementation_path_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=validator_implementation_sha256(
            implementation_path=implementation_path
        ),
    )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        return ValidatedEvidence(verdict="passed")


class MutableConfigValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    dependency_paths: tuple[Path, ...] = ()
    protocol = "mutable_config_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def __init__(self) -> None:
        self.policy = {"mode": "strict"}

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        for artifact in request.artifacts:
            artifact.read_bytes()
        return ValidatedEvidence(verdict="passed")


class SelfMutatingValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "self_mutating_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def __init__(self) -> None:
        self.policy = "strict"

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        self.policy = "forged"
        for artifact in request.artifacts:
            artifact.read_bytes()
        return ValidatedEvidence(verdict="passed")


class SelfMutatingPreflightValidator:
    domains = frozenset({"scientific"})
    implementation_path = IMPLEMENTATION_PATH
    protocol = "self_mutating_preflight_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=IMPLEMENTATION_HASH,
    )

    def __init__(self) -> None:
        self.policy = "strict"

    def preflight_binding(self, *, domain: str, binding: object) -> None:
        self.policy = "forged"

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        for artifact in request.artifacts:
            artifact.read_bytes()
        return ValidatedEvidence(verdict="passed")


def replacement_validate(
    self: object,
    request: EvidenceValidationRequest,
) -> ValidatedEvidence:
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
    def test_engineering_retry_fixture_validator_rejects_nonfixture_dispatch(
        self,
    ) -> None:
        with TemporaryDirectory() as root:
            directory = Path(root)
            plan_path = directory / "plan.json"
            plan_path.write_bytes(
                canonical_bytes(
                    {
                        "operation": "canonical_required_transition",
                        "schema": "engineering_retry_fixture_plan.v1",
                    }
                )
            )
            binding = {
                "schema": "engineering_retry_validation_binding.v1"
            }
            measurement_path = directory / "measurement.json"
            measurement_path.write_bytes(
                canonical_bytes(
                    {
                        "binding_sha256": sha256(
                            canonical_bytes(binding)
                        ).hexdigest(),
                        "current_measurement": "passed",
                        "prior_measurement": "failed",
                        "required_measurement": "passed",
                        "schema": (
                            "engineering_retry_fixture_measurement.v1"
                        ),
                    }
                )
            )
            plan = ValidationArtifact(
                output_name="validation_plan",
                sha256=sha256(plan_path.read_bytes()).hexdigest(),
                _source=plan_path,
            )
            measurement = ValidationArtifact(
                output_name="validation_result:0000",
                sha256=sha256(measurement_path.read_bytes()).hexdigest(),
                _source=measurement_path,
            )
            validator = EngineeringRetryFixtureValidator()
            request = EngineeringEvidenceValidationRequest(
                validator_id=validator.validator_id,
                validation_plan_hash=plan.sha256,
                mission_id="MIS-ENGINEERING-RETRY",
                retry_family_fingerprint="1" * 64,
                prior_completion_record_id="2" * 64,
                prior_job_id="job:" + "3" * 64,
                prior_job_hash="4" * 64,
                prior_work_fingerprint="5" * 64,
                new_work_fingerprint="5" * 64,
                changed_dimension="cause",
                new_basis_hash="6" * 64,
                evidence_subject={
                    "kind": "Mission",
                    "id": "MIS-ENGINEERING-RETRY",
                },
                binding=binding,
                result_manifest={"claimed_verdict": "passed"},
                artifacts=(plan, measurement),
                engineering_fixture=False,
            )
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "fixture-only",
            ):
                EvidenceValidatorRegistry((validator,)).validate(request)

    def test_engineering_validator_derives_exact_source_lifecycle_coverage(
        self,
    ) -> None:
        coverage_id = "source-lifecycle-coverage:" + "d" * 64
        with TemporaryDirectory() as root:
            source = Path(root) / "measurement.json"
            source.write_bytes(
                canonical_bytes(
                    {
                        "claims": ["source_interruption"],
                        "schema": "engineering_runtime_measurement.v1",
                    }
                )
            )
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(source.read_bytes()).hexdigest(),
                _source=source,
            )
            validator = EngineeringFixtureValidator()
            request = EvidenceValidationRequest(
                domain="runtime",
                validator_id=validator.validator_id,
                validation_plan_hash=ENGINEERING_RUNTIME_PLAN_HASH,
                job_id="job:fixture",
                job_hash="c" * 64,
                mission_id="MIS-VALIDATION",
                evidence_subject={"kind": "Executable", "id": "executable:fixture"},
                binding={"artifact_roles": {}},
                result_manifest={
                    "observations": [
                        {
                            "claim_id": "source_interruption",
                            "measurement_artifact_hash": artifact.sha256,
                            "source_lifecycle_coverage_id": coverage_id,
                            "status": "passed",
                        }
                    ]
                },
                artifacts=(artifact,),
                engineering_fixture=True,
            )

            validated, _trace = EvidenceValidatorRegistry((validator,)).validate(
                request
            )

        self.assertEqual(
            validated.facts["source_lifecycle_coverage_ids"],
            [coverage_id],
        )

    def test_binding_preflight_is_dispatched_with_an_immutable_copy(self) -> None:
        validator = ImmutableRequestValidator()
        registry = EvidenceValidatorRegistry((validator,))
        binding = {"planned_claims": ["claim-a"]}

        registry.preflight_binding(
            validator_id=validator.validator_id,
            domain="scientific",
            binding=binding,
        )

        self.assertEqual(binding, {"planned_claims": ["claim-a"]})

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
            request = request_for(
                validator_id=validator.validator_id,
                artifact=artifact,
            )
            registry.validate(request)
            self.assertNotIn("forged", request.binding)

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

    def test_declared_implementation_must_match_actual_class_and_callable_source(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "class/module source differs",
        ):
            EvidenceValidatorRegistry((FalseImplementationPathValidator(),))

    def test_instance_method_shadow_fails_before_and_after_registration(self) -> None:
        before = UnreadArtifactValidator()
        before.validate = replacement_validate  # type: ignore[method-assign]
        with self.assertRaises(EvidenceValidationError):
            EvidenceValidatorRegistry((before,))

        after = UnreadArtifactValidator()
        registry = EvidenceValidatorRegistry((after,))
        after.validate = replacement_validate  # type: ignore[method-assign]
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "registration changed after registration",
        ):
            registry.require_registered(
                validator_id=after.validator_id,
                domain="scientific",
            )

    def test_registered_protocol_is_an_exact_capability(self) -> None:
        validator = UnreadArtifactValidator()
        registry = EvidenceValidatorRegistry((validator,))
        registry.require_registered_protocol(
            validator_id=validator.validator_id,
            domain="scientific",
            protocol=validator.protocol,
        )
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "protocol differs",
        ):
            registry.require_registered_protocol(
                validator_id=validator.validator_id,
                domain="scientific",
                protocol="unrelated_protocol.v1",
            )
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "protocol requirement is invalid",
        ):
            registry.require_registered_protocol(
                validator_id=validator.validator_id,
                domain="scientific",
                protocol="",
            )

    def test_class_method_replacement_and_in_place_code_patch_fail_closed(
        self,
    ) -> None:
        validator = UnreadArtifactValidator()
        registry = EvidenceValidatorRegistry((validator,))
        original = UnreadArtifactValidator.validate
        try:
            UnreadArtifactValidator.validate = replacement_validate  # type: ignore[method-assign]
            with self.assertRaises(EvidenceValidationError):
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
        finally:
            UnreadArtifactValidator.validate = original  # type: ignore[method-assign]

        validator = UnreadArtifactValidator()
        registry = EvidenceValidatorRegistry((validator,))
        original_code = UnreadArtifactValidator.validate.__code__
        try:
            UnreadArtifactValidator.validate.__code__ = replacement_validate.__code__
            with self.assertRaises(EvidenceValidationError):
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
        finally:
            UnreadArtifactValidator.validate.__code__ = original_code

    def test_metadata_and_dependency_mutation_fail_closed(self) -> None:
        cases = (
            ("validator_id", "validator:" + "e" * 64),
            ("protocol", "changed_protocol.v1"),
            ("domains", frozenset({"runtime"})),
            ("implementation_path", FALSE_IMPLEMENTATION_PATH),
            ("dependency_paths", (FALSE_IMPLEMENTATION_PATH,)),
        )
        for name, changed in cases:
            with self.subTest(name=name):
                validator = MutableConfigValidator()
                validator_id = validator.validator_id
                registry = EvidenceValidatorRegistry((validator,))
                original = vars(MutableConfigValidator)[name]
                try:
                    setattr(MutableConfigValidator, name, changed)
                    with self.assertRaises(EvidenceValidationError):
                        registry.require_registered(
                            validator_id=validator_id,
                            domain="scientific",
                        )
                finally:
                    setattr(MutableConfigValidator, name, original)

    def test_mutable_instance_config_is_sealed(self) -> None:
        validator = MutableConfigValidator()
        registry = EvidenceValidatorRegistry((validator,))
        validator.policy["mode"] = "forged"

        with self.assertRaisesRegex(
            EvidenceValidationError,
            "registration changed after registration",
        ):
            registry.require_registered(
                validator_id=validator.validator_id,
                domain="scientific",
            )

    def test_validator_self_mutation_fails_after_validate_and_preflight(self) -> None:
        with TemporaryDirectory() as root:
            source = Path(root) / "artifact.bin"
            source.write_bytes(b"self mutation artifact")
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(source.read_bytes()).hexdigest(),
                _source=source,
            )
            validator = SelfMutatingValidator()
            registry = EvidenceValidatorRegistry((validator,))
            with self.assertRaisesRegex(
                EvidenceValidationError,
                "registration changed after registration",
            ):
                registry.validate(
                    request_for(
                        validator_id=validator.validator_id,
                        artifact=artifact,
                    )
                )

        validator = SelfMutatingPreflightValidator()
        registry = EvidenceValidatorRegistry((validator,))
        with self.assertRaisesRegex(
            EvidenceValidationError,
            "registration changed after registration",
        ):
            registry.preflight_binding(
                validator_id=validator.validator_id,
                domain="scientific",
                binding={"planned_claims": ["claim-a"]},
            )


if __name__ == "__main__":
    unittest.main()
