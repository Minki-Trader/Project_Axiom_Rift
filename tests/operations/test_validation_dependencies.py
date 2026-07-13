from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidatorRegistry,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)


class _DependencyBoundValidator:
    domains = frozenset({"scientific"})
    protocol = "dependency_bound_fixture.v1"

    def __init__(self, implementation: Path, dependency: Path) -> None:
        self.implementation_path = implementation
        self.dependency_paths = (dependency,)
        self.validator_id = validator_identity(
            protocol=self.protocol,
            domains=self.domains,
            implementation_sha256=validator_implementation_sha256(
                implementation_path=implementation,
                dependency_paths=self.dependency_paths,
            ),
        )

    def validate(self, request: object) -> ValidatedEvidence:
        raise AssertionError("identity tests do not dispatch validation")


class ValidatorDependencyIdentityTests(unittest.TestCase):
    def test_dependency_free_digest_is_legacy_file_sha256(self) -> None:
        with TemporaryDirectory() as root:
            implementation = Path(root) / "validator.py"
            implementation.write_bytes(b"legacy validator bytes")

            self.assertEqual(
                validator_implementation_sha256(
                    implementation_path=implementation
                ),
                sha256(implementation.read_bytes()).hexdigest(),
            )

    def test_dependency_drift_fails_before_and_after_registration(self) -> None:
        with TemporaryDirectory() as root:
            implementation = Path(root) / "validator.py"
            dependency = Path(root) / "decision.py"
            implementation.write_bytes(b"validator implementation")
            dependency.write_bytes(b"decision dependency v1")
            validator = _DependencyBoundValidator(implementation, dependency)
            registry = EvidenceValidatorRegistry((validator,))

            dependency.write_bytes(b"decision dependency v2")

            with self.assertRaises(EvidenceValidationError):
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
            with self.assertRaises(EvidenceValidationError):
                EvidenceValidatorRegistry((validator,))

    def test_missing_or_duplicate_dependency_fails_closed(self) -> None:
        with TemporaryDirectory() as root:
            implementation = Path(root) / "validator.py"
            dependency = Path(root) / "decision.py"
            implementation.write_bytes(b"validator implementation")
            dependency.write_bytes(b"decision dependency")
            validator = _DependencyBoundValidator(implementation, dependency)
            registry = EvidenceValidatorRegistry((validator,))
            dependency.unlink()

            with self.assertRaises(EvidenceValidationError):
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
            with self.assertRaises(EvidenceValidationError):
                EvidenceValidatorRegistry((validator,))
            with self.assertRaises(EvidenceValidationError):
                validator_implementation_sha256(
                    implementation_path=implementation,
                    dependency_paths=(implementation,),
                )

    def test_dependency_declaration_order_is_identity_bearing(self) -> None:
        with TemporaryDirectory() as root:
            implementation = Path(root) / "validator.py"
            dependency_a = Path(root) / "a.py"
            dependency_b = Path(root) / "b.py"
            implementation.write_bytes(b"validator implementation")
            dependency_a.write_bytes(b"dependency a")
            dependency_b.write_bytes(b"dependency b")

            forward = validator_implementation_sha256(
                implementation_path=implementation,
                dependency_paths=(dependency_a, dependency_b),
            )
            reverse = validator_implementation_sha256(
                implementation_path=implementation,
                dependency_paths=(dependency_b, dependency_a),
            )

            self.assertNotEqual(forward, reverse)


if __name__ == "__main__":
    unittest.main()
