from __future__ import annotations

from hashlib import sha256
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.operations.validation as validation_module
import axiom_rift.operations.validation_integrity as integrity_module
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidatedEvidence,
    ValidationArtifact,
    validator_execution_dependency_paths,
    validator_identity,
    validator_implementation_sha256,
    validator_project_dependency_paths,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _DependencyBoundValidator:
    domains = frozenset({"scientific"})
    implementation_path = Path(__file__).resolve()
    protocol = "dependency_bound_fixture.v1"

    def __init__(self, dependency: Path) -> None:
        self.dependency_paths = (dependency,)
        self.validator_id = validator_identity(
            protocol=self.protocol,
            domains=self.domains,
            implementation_sha256=validator_implementation_sha256(
                implementation_path=self.implementation_path,
                dependency_paths=self.dependency_paths,
            ),
        )

    def validate(self, request: EvidenceValidationRequest) -> ValidatedEvidence:
        for artifact in request.artifacts:
            artifact.read_bytes()
        return ValidatedEvidence(verdict="passed")


class ValidatorDependencyIdentityTests(unittest.TestCase):
    def test_integrity_public_api_is_reexported_from_validation(self) -> None:
        for name in (
            "EvidenceValidationError",
            "validator_identity",
            "validator_implementation_sha256",
            "validator_execution_dependency_paths",
            "validator_project_dependency_paths",
        ):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(validation_module, name),
                    getattr(integrity_module, name),
                )

    def test_execution_closure_includes_semantic_roots_and_transitive_imports(
        self,
    ) -> None:
        implementation = Path(validation_module.__file__).resolve()
        semantic_root = Path(integrity_module.__file__).resolve()
        closure = validator_execution_dependency_paths(
            implementation,
            (semantic_root,),
        )
        self.assertIn(implementation, closure)
        self.assertIn(semantic_root, closure)
        self.assertIn(
            (REPOSITORY_ROOT / "src/axiom_rift/core/canonical.py").resolve(),
            closure,
        )

    def test_execution_closure_cache_reuses_unchanged_ast_graph(self) -> None:
        implementation = Path(validation_module.__file__).resolve()
        semantic_root = Path(integrity_module.__file__).resolve()
        integrity_module._EXECUTION_DEPENDENCY_CACHE.clear()
        self.addCleanup(integrity_module._EXECUTION_DEPENDENCY_CACHE.clear)

        with patch.object(
            integrity_module,
            "_project_python_import_dependency_paths",
            wraps=integrity_module._project_python_import_dependency_paths,
        ) as discovery:
            first = validator_execution_dependency_paths(
                implementation,
                (semantic_root,),
            )
            second = validator_execution_dependency_paths(
                implementation,
                (semantic_root,),
            )

        self.assertEqual(first, second)
        self.assertEqual(discovery.call_count, 1)

    def test_execution_closure_retries_importer_drift_after_ast_parse(
        self,
    ) -> None:
        integrity_module._EXECUTION_DEPENDENCY_CACHE.clear()
        self.addCleanup(integrity_module._EXECUTION_DEPENDENCY_CACHE.clear)
        with TemporaryDirectory(
            dir=REPOSITORY_ROOT,
            prefix="_validation_execution_race_fixture_",
        ) as root:
            package = Path(root)
            (package / "__init__.py").write_text("", encoding="ascii")
            implementation = package / "validator.py"
            late_dependency = package / "late_dependency.py"
            initial_source = b"VALUE = 1\n"
            changed_source = b"from . import late_dependency\nVALUE = 1\n"
            implementation.write_bytes(changed_source)
            late_dependency.write_text("VALUE = 2\n", encoding="ascii")
            original_read_bytes = Path.read_bytes
            implementation_reads = 0

            def racing_read_bytes(path: Path) -> bytes:
                nonlocal implementation_reads
                if path.resolve() == implementation.resolve():
                    implementation_reads += 1
                    if implementation_reads == 1:
                        return initial_source
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", racing_read_bytes):
                closure = validator_execution_dependency_paths(implementation)

            self.assertGreaterEqual(implementation_reads, 4)
            self.assertIn(late_dependency.resolve(), closure)

    def test_project_closure_cache_reuses_unchanged_inventory(self) -> None:
        with TemporaryDirectory() as root:
            dependency = Path(root) / "decision.py"
            dependency.write_bytes(b"decision dependency")
            validator = _DependencyBoundValidator(dependency)
            integrity_module._PROJECT_CLOSURE_CACHE.clear()
            self.addCleanup(integrity_module._PROJECT_CLOSURE_CACHE.clear)

            with patch.object(
                integrity_module,
                "_project_python_import_dependency_paths",
                wraps=integrity_module._project_python_import_dependency_paths,
            ) as discovery:
                registry = EvidenceValidatorRegistry((validator,))
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )

            self.assertEqual(discovery.call_count, 1)

    def test_validation_uses_one_inventory_scan_at_each_boundary(self) -> None:
        with TemporaryDirectory() as root:
            directory = Path(root)
            dependency = directory / "decision.py"
            dependency.write_bytes(b"decision dependency")
            artifact_path = directory / "measurement.bin"
            artifact_path.write_bytes(b"measurement")
            artifact = ValidationArtifact(
                output_name="measurement",
                sha256=sha256(artifact_path.read_bytes()).hexdigest(),
                _source=artifact_path,
            )
            validator = _DependencyBoundValidator(dependency)
            integrity_module._PROJECT_CLOSURE_CACHE.clear()
            self.addCleanup(integrity_module._PROJECT_CLOSURE_CACHE.clear)
            registry = EvidenceValidatorRegistry((validator,))
            request = EvidenceValidationRequest(
                domain="scientific",
                validator_id=validator.validator_id,
                validation_plan_hash="a" * 64,
                job_id="job:inventory-scan",
                job_hash="b" * 64,
                mission_id="MIS-VALIDATION",
                evidence_subject={
                    "kind": "Executable",
                    "id": "executable:inventory-scan",
                },
                binding={},
                result_manifest={},
                artifacts=(artifact,),
            )

            with patch.object(
                integrity_module,
                "_project_python_inventory_fingerprint",
                wraps=integrity_module._project_python_inventory_fingerprint,
            ) as inventory:
                registry.validate(request)

            self.assertEqual(inventory.call_count, 2)

    def test_new_project_import_target_invalidates_cached_closure(self) -> None:
        integrity_module._PROJECT_CLOSURE_CACHE.clear()
        self.addCleanup(integrity_module._PROJECT_CLOSURE_CACHE.clear)
        with TemporaryDirectory(
            prefix="_validation_cache_fixture_",
            dir=REPOSITORY_ROOT,
        ) as root:
            package = Path(root)
            package_name = package.name
            implementation = package / "validator.py"
            late_dependency = package / "late_dependency.py"
            (package / "__init__.py").write_text("", encoding="ascii")
            implementation.write_text(
                """from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from axiom_rift.operations.validation import (
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)

if TYPE_CHECKING:
    from . import late_dependency


class InventoryValidator:
    domains = frozenset({"scientific"})
    implementation_path = Path(__file__).resolve()
    protocol = "inventory_cache_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=validator_implementation_sha256(
            implementation_path=implementation_path
        ),
    )

    def validate(self, request: object) -> ValidatedEvidence:
        raise AssertionError("cache fixture does not dispatch validation")
""",
                encoding="ascii",
            )
            initial_closure = validator_project_dependency_paths(implementation)
            self.assertNotIn(late_dependency.resolve(), initial_closure)

            sys.path.insert(0, str(REPOSITORY_ROOT))
            module_name = f"{package_name}.validator"
            try:
                importlib.invalidate_caches()
                module = importlib.import_module(module_name)
                validator = module.InventoryValidator()
                registry = EvidenceValidatorRegistry((validator,))
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )

                late_dependency.write_text("VALUE = 1\n", encoding="ascii")
                changed_closure = validator_project_dependency_paths(
                    implementation
                )
                self.assertIn(late_dependency.resolve(), changed_closure)
                self.assertNotEqual(initial_closure, changed_closure)
                with self.assertRaisesRegex(
                    EvidenceValidationError,
                    "registration changed after registration",
                ):
                    registry.require_registered(
                        validator_id=validator.validator_id,
                        domain="scientific",
                    )
            finally:
                sys.modules.pop(module_name, None)
                sys.modules.pop(package_name, None)
                sys.path.remove(str(REPOSITORY_ROOT))

    def test_mid_validation_import_target_creation_fails_at_post_boundary(
        self,
    ) -> None:
        integrity_module._PROJECT_CLOSURE_CACHE.clear()
        self.addCleanup(integrity_module._PROJECT_CLOSURE_CACHE.clear)
        with TemporaryDirectory(
            prefix="_validation_mid_tamper_fixture_",
            dir=REPOSITORY_ROOT,
        ) as root:
            package = Path(root)
            package_name = package.name
            implementation = package / "validator.py"
            late_dependency = package / "late_dependency.py"
            artifact_path = package / "measurement.bin"
            (package / "__init__.py").write_text("", encoding="ascii")
            artifact_path.write_bytes(b"measurement")
            implementation.write_text(
                '''from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from axiom_rift.operations.validation import (
    EvidenceValidationRequest,
    ValidatedEvidence,
    validator_identity,
    validator_implementation_sha256,
)

if TYPE_CHECKING:
    from . import late_dependency


class MidTamperValidator:
    domains = frozenset({"scientific"})
    implementation_path = Path(__file__).resolve()
    protocol = "mid_tamper_fixture.v1"
    validator_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=validator_implementation_sha256(
            implementation_path=implementation_path
        ),
    )

    def validate(
        self, request: EvidenceValidationRequest
    ) -> ValidatedEvidence:
        for artifact in request.artifacts:
            artifact.read_bytes()
        Path(__file__).with_name("late_dependency.py").write_text(
            "VALUE = 1\\n", encoding="ascii"
        )
        return ValidatedEvidence(verdict="passed")
''',
                encoding="ascii",
            )

            sys.path.insert(0, str(REPOSITORY_ROOT))
            module_name = f"{package_name}.validator"
            try:
                importlib.invalidate_caches()
                module = importlib.import_module(module_name)
                validator = module.MidTamperValidator()
                registry = EvidenceValidatorRegistry((validator,))
                artifact = ValidationArtifact(
                    output_name="measurement",
                    sha256=sha256(artifact_path.read_bytes()).hexdigest(),
                    _source=artifact_path,
                )
                request = EvidenceValidationRequest(
                    domain="scientific",
                    validator_id=validator.validator_id,
                    validation_plan_hash="a" * 64,
                    job_id="job:mid-tamper",
                    job_hash="b" * 64,
                    mission_id="MIS-VALIDATION",
                    evidence_subject={
                        "kind": "Executable",
                        "id": "executable:mid-tamper",
                    },
                    binding={},
                    result_manifest={},
                    artifacts=(artifact,),
                )

                with self.assertRaisesRegex(
                    EvidenceValidationError,
                    "registration changed after registration",
                ):
                    registry.validate(request)
                self.assertTrue(late_dependency.is_file())
            finally:
                sys.modules.pop(module_name, None)
                sys.modules.pop(package_name, None)
                sys.path.remove(str(REPOSITORY_ROOT))

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
            dependency = Path(root) / "decision.py"
            dependency.write_bytes(b"decision dependency v1")
            validator = _DependencyBoundValidator(dependency)
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
            dependency = Path(root) / "decision.py"
            dependency.write_bytes(b"decision dependency")
            validator = _DependencyBoundValidator(dependency)
            registry = EvidenceValidatorRegistry((validator,))
            dependency.unlink()

            with self.assertRaises(EvidenceValidationError):
                registry.require_registered(
                    validator_id=validator.validator_id,
                    domain="scientific",
                )
            with self.assertRaises(EvidenceValidationError):
                EvidenceValidatorRegistry((validator,))
            implementation = _DependencyBoundValidator.implementation_path
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
