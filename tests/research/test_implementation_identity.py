from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.identity import canonical_identity_bytes
from axiom_rift.research import (
    analog_state_study,
    fold_train_target_role_discovery,
    high_vol_target_reversal_discovery,
    independent_sleeve_portfolio_chassis,
    low_vol_abstention_discovery,
    session_dense_positive_sleeve_chassis,
    session_dense_positive_sleeve_discovery,
)
from axiom_rift.research.implementation_closure import (
    COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA,
    ImplementationClosureError,
    component_implementation_sha256,
    executable_implementation_hashes,
    require_job_implementation_closure,
    semantic_dependency_closure,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.operations.writer import _hardcoded_control_ids


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ImplementationIdentityTests(unittest.TestCase):
    @staticmethod
    def _executable_manifest(*digests: str) -> dict[str, object]:
        return {
            "schema": "executable_spec.v1",
            "component_identities": [f"component:{index:064x}" for index, _ in enumerate(digests)],
            "component_manifests": [
                {
                    "implementation": (
                        f"axiom_rift.research.fixture.component_{index}"
                        f"@sha256:{digest}"
                    )
                }
                for index, digest in enumerate(digests)
            ],
        }

    def test_component_reference_requires_exact_sha256_suffix(self) -> None:
        digest = "a" * 64
        self.assertEqual(
            component_implementation_sha256(
                f"axiom_rift.research.fixture.run@sha256:{digest}"
            ),
            digest,
        )
        for malformed in (
            "axiom_rift.research.fixture.run",
            "axiom_rift.research.fixture.run@sha256:abc",
            f"axiom_rift.research.fixture.run@sha256:{'A' * 64}",
        ):
            with self.subTest(reference=malformed):
                with self.assertRaises(ImplementationClosureError):
                    component_implementation_sha256(malformed)

    def test_semantic_dependency_closure_is_recursive_and_fail_closed(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            root = source_root / "root.py"
            alpha = source_root / "alpha.py"
            zeta = source_root / "zeta.py"
            for path in (root, alpha, zeta):
                path.write_text("pass\n", encoding="ascii")

            self.assertEqual(
                semantic_dependency_closure(
                    roots=(root,),
                    dependency_graph={
                        root: (zeta, alpha),
                        alpha: (),
                        zeta: (),
                    },
                    source_root=source_root,
                ),
                (root.resolve(), alpha.resolve(), zeta.resolve()),
            )
            invalid_graphs = (
                (
                    {root: (alpha,), alpha: (root,)},
                    "cycle",
                ),
                (
                    {root: (), alpha: ()},
                    "unreachable",
                ),
                (
                    {root: (alpha,)},
                    "omits explicit source nodes",
                ),
            )
            for graph, message in invalid_graphs:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(
                        ImplementationClosureError,
                        message,
                    ):
                        semantic_dependency_closure(
                            roots=(root,),
                            dependency_graph=graph,
                            source_root=source_root,
                        )

    def test_job_evidence_closes_every_distinct_component_hash(self) -> None:
        first_bytes = b"first exact Component implementation"
        second_bytes = b"second exact Component implementation"
        extra_bytes = b"unrelated Job implementation artifact"
        first = sha256(first_bytes).hexdigest()
        second = sha256(second_bytes).hexdigest()
        extra = sha256(extra_bytes).hexdigest()
        artifacts = {
            first: first_bytes,
            second: second_bytes,
            extra: extra_bytes,
        }
        executable = self._executable_manifest(first, second, first)
        self.assertEqual(
            executable_implementation_hashes(executable),
            tuple(sorted((first, second))),
        )
        self.assertEqual(
            require_job_implementation_closure(
                executable_manifest=executable,
                job_artifact_hashes=(second, extra, first),
                artifact_reader=artifacts.__getitem__,
            ),
            tuple(sorted((first, second))),
        )
        with self.assertRaisesRegex(
            ImplementationClosureError, "omits Component source bytes"
        ):
            require_job_implementation_closure(
                executable_manifest=executable,
                job_artifact_hashes=(first,),
                artifact_reader=artifacts.__getitem__,
            )
        tampered = dict(artifacts)
        tampered[first] = b"different bytes under the declared direct hash"
        with self.assertRaisesRegex(
            ImplementationClosureError, "artifact hash mismatch"
        ):
            require_job_implementation_closure(
                executable_manifest=executable,
                job_artifact_hashes=(first, second, extra),
                artifact_reader=tampered.__getitem__,
            )

    def test_typed_bundle_requires_every_exact_dependency_artifact(self) -> None:
        dependency_bytes = b"exact forest dependency source bytes"
        dependency_hash = sha256(dependency_bytes).hexdigest()
        bundle_bytes = canonical_identity_bytes(
            domain="fixture-component-implementation-bundle",
            payload={
                "dependency_artifact_hashes": [dependency_hash],
                "implementation_bundle_schema": (
                    COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
                ),
                "schema": "fixture_component_implementation_bundle.v1",
            },
        )
        bundle_hash = sha256(bundle_bytes).hexdigest()
        artifacts = {
            bundle_hash: bundle_bytes,
            dependency_hash: dependency_bytes,
        }
        executable = self._executable_manifest(bundle_hash)

        with self.assertRaisesRegex(
            ImplementationClosureError, "omits Component bundle dependencies"
        ):
            require_job_implementation_closure(
                executable_manifest=executable,
                job_artifact_hashes=(bundle_hash,),
                artifact_reader=artifacts.__getitem__,
            )
        self.assertEqual(
            require_job_implementation_closure(
                executable_manifest=executable,
                job_artifact_hashes=(bundle_hash, dependency_hash),
                artifact_reader=artifacts.__getitem__,
            ),
            (bundle_hash,),
        )

    def test_typed_bundle_rejects_duplicate_and_noncanonical_payloads(self) -> None:
        dependency_bytes = b"typed bundle dependency"
        dependency_hash = sha256(dependency_bytes).hexdigest()
        duplicate_bundle = canonical_identity_bytes(
            domain="duplicate-fixture-bundle",
            payload={
                "dependency_artifact_hashes": [
                    dependency_hash,
                    dependency_hash,
                ],
                "implementation_bundle_schema": (
                    COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
                ),
            },
        )
        noncanonical_bundle = canonical_identity_bytes(
            domain="noncanonical-fixture-bundle",
            payload={
                "dependency_artifact_hashes": [dependency_hash],
                "implementation_bundle_schema": (
                    COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
                ),
            },
        ).replace(b'{"dependency', b'{ "dependency', 1)
        for label, bundle_bytes, message in (
            ("duplicate", duplicate_bundle, "bundle payload is invalid"),
            ("noncanonical", noncanonical_bundle, "identity frame is invalid"),
        ):
            with self.subTest(label=label):
                bundle_hash = sha256(bundle_bytes).hexdigest()
                artifacts = {
                    bundle_hash: bundle_bytes,
                    dependency_hash: dependency_bytes,
                }
                with self.assertRaisesRegex(ImplementationClosureError, message):
                    require_job_implementation_closure(
                        executable_manifest=self._executable_manifest(bundle_hash),
                        job_artifact_hashes=(bundle_hash, dependency_hash),
                        artifact_reader=artifacts.__getitem__,
                    )

    def test_repaired_prospective_implementations_bind_current_bytes(self) -> None:
        cases = (
            (
                fold_train_target_role_discovery,
                fold_train_target_role_discovery.fold_train_target_role_discovery_implementation_sha256,
            ),
            (
                high_vol_target_reversal_discovery,
                high_vol_target_reversal_discovery.high_vol_target_reversal_discovery_implementation_sha256,
            ),
            (
                low_vol_abstention_discovery,
                low_vol_abstention_discovery.low_vol_abstention_discovery_implementation_sha256,
            ),
            (
                session_dense_positive_sleeve_discovery,
                session_dense_positive_sleeve_discovery.session_dense_positive_sleeve_discovery_implementation_sha256,
            ),
            (
                independent_sleeve_portfolio_chassis,
                independent_sleeve_portfolio_chassis.independent_sleeve_portfolio_chassis_implementation_sha256,
            ),
            (
                session_dense_positive_sleeve_chassis,
                session_dense_positive_sleeve_chassis.session_dense_positive_sleeve_chassis_implementation_sha256,
            ),
        )
        for module, identity in cases:
            with self.subTest(module=module.__name__):
                path = Path(module.__file__).resolve()
                self.assertEqual(identity(), sha256(path.read_bytes()).hexdigest())

    def test_tracked_research_code_has_no_unmarked_fixed_implementation_digest(self) -> None:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "src/axiom_rift/research/*.py",
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
        )
        paths = tuple(
            REPOSITORY_ROOT / value.decode("ascii")
            for value in completed.stdout.split(b"\0")
            if value
        )
        self.assertTrue(paths)
        violations: list[str] = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else (node.target,)
                )
                value = node.value
                if not (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and len(value.value) == 64
                    and all(character in "0123456789abcdef" for character in value.value)
                ):
                    continue
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id
                    if (
                        "IMPLEMENTATION_SHA256" in name
                        and not name.lstrip("_").startswith("HISTORICAL_")
                    ):
                        violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{name}")
        self.assertEqual(violations, [])

    def test_hardcoded_control_modules_are_frozen_historical_only(self) -> None:
        research_root = REPOSITORY_ROOT / "src" / "axiom_rift" / "research"
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "src/axiom_rift/research/*.py",
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
        )
        observed: dict[str, str] = {}
        for raw_path in completed.stdout.split(b"\0"):
            if not raw_path:
                continue
            path = REPOSITORY_ROOT / raw_path.decode("ascii")
            content = path.read_bytes()
            if _hardcoded_control_ids(content):
                observed[path.name] = sha256(content).hexdigest()
        self.assertEqual(
            observed,
            HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
        )
        self.assertNotIn(
            "analog_state_study.py",
            HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
        )
        self.assertEqual(
            research_root / "analog_state_study.py",
            Path(analog_state_study.__file__).resolve(),
        )


if __name__ == "__main__":
    unittest.main()
