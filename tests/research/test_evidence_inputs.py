from __future__ import annotations

import ast
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.evidence_inputs import (
    read_bound_evidence_inputs,
    read_exact_evidence_inputs,
    read_surface_manifest_evidence_inputs,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)
from axiom_rift.research.implementation_closure import (
    HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS,
)
from axiom_rift.storage.evidence import EvidenceStore


ACTIVE_RESEARCH_EVIDENCE_CONSUMERS = (
    "analog_state_study.py",
    "cost_aware_execution_study.py",
    "dense_short_synthesis_study.py",
    "equity_premium_trade_study.py",
    "event_direction_meta_study.py",
    "fold_interaction_model_study.py",
    "fold_train_target_role_study.py",
    "high_vol_dense_regime_study.py",
    "high_vol_target_reversal_study.py",
    "independent_sleeve_portfolio_study.py",
    "low_vol_abstention_study.py",
    "monthly_loss_lock_risk_study.py",
    "path_occupancy_label_study.py",
    "positive_direction_sleeve_study.py",
    "regime_direction_router_study.py",
    "residual_quote_deferral_study.py",
    "session_dense_positive_sleeve_study.py",
    "shadow_slot_lifecycle_study.py",
    "three_way_regime_router_study.py",
    "trend_regime_study.py",
    "us30_downside_spillover_study.py",
    "us30_sector_rotation_study.py",
    "volatility_clock_label_study.py",
    "volatility_stop_risk_study.py",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_AXIOM_SOURCE_PATHS = frozenset(
    {
        REPOSITORY_ROOT / "src" / "axiom_rift" / "research" / name
        for name in (
            "tlt_source.py",
            "tlt_source_chassis.py",
            "tlt_source_eligibility_validation.py",
            "tlt_source_study.py",
        )
    }
)
EXPECTED_SURFACE_IMPLEMENTATION_SHA256 = "1" * 64


def _tracked_axiom_python_paths() -> tuple[Path, ...]:
    """Return only Git-indexed Python paths outside protected source."""

    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            ":(glob)src/axiom_rift/**/*.py",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    paths = tuple(
        REPOSITORY_ROOT / raw.decode("ascii")
        for raw in completed.stdout.split(b"\0")
        if raw
    )
    return tuple(
        path for path in paths if path not in PROTECTED_AXIOM_SOURCE_PATHS
    )


class ResearchEvidenceInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "evidence"
        self.store = EvidenceStore(self.root)

    def _canonical(self, value: object) -> str:
        return self.store.finalize(canonical_bytes(value)).sha256

    def test_identity_bound_inputs_allow_one_schema_for_many_artifacts(self) -> None:
        first = self._canonical(
            {"schema": "historical_member.v1", "subject": "first"}
        )
        second = self._canonical(
            {"schema": "historical_member.v1", "subject": "second"}
        )
        identities = tuple(sorted((first, second)))

        with patch.object(
            self.store,
            "read_verified",
            wraps=self.store.read_verified,
        ) as read_verified:
            inputs = read_bound_evidence_inputs(
                self.store,
                identities,
                expected_bindings=(
                    (first, "historical_member.v1"),
                    (second, "historical_member.v1"),
                ),
            )

        self.assertEqual(
            inputs.require_identity(first).value["subject"],
            "first",
        )
        self.assertEqual(
            inputs.require_identity(second).value["subject"],
            "second",
        )
        self.assertEqual(
            [call.args[0] for call in read_verified.call_args_list],
            list(identities),
        )

    def test_identity_bound_inventory_fails_before_any_evidence_read(self) -> None:
        first = self._canonical(
            {"schema": "historical_member.v1", "subject": "first"}
        )
        second = self._canonical(
            {"schema": "historical_member.v1", "subject": "second"}
        )

        with (
            patch.object(
                self.store,
                "read_verified",
                wraps=self.store.read_verified,
            ) as read_verified,
            self.assertRaisesRegex(ValueError, "differ from expected"),
        ):
            read_bound_evidence_inputs(
                self.store,
                (first,),
                expected_bindings=(
                    (first, "historical_member.v1"),
                    (second, "historical_member.v1"),
                ),
            )
        read_verified.assert_not_called()

    def test_surface_and_manifest_are_read_once_and_bound_exactly(self) -> None:
        surface_hash = self._canonical(
            {"rows": [], "schema": "test_surface.v1"}
        )
        manifest_hash = self._canonical(
            {
                "schema": "test_surface_manifest.v1",
                "surface_artifact_hash": surface_hash,
                "surface_implementation_sha256": (
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            }
        )

        with patch.object(
            self.store,
            "read_verified",
            wraps=self.store.read_verified,
        ) as read_verified:
            binding = read_surface_manifest_evidence_inputs(
                self.store,
                (surface_hash, manifest_hash),
                surface_schema="test_surface.v1",
                manifest_schema="test_surface_manifest.v1",
                expected_surface_implementation_sha256=(
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            )

        self.assertEqual(binding.surface.artifact_sha256, surface_hash)
        self.assertEqual(binding.manifest.artifact_sha256, manifest_hash)
        self.assertEqual(
            [call.args[0] for call in read_verified.call_args_list],
            [surface_hash, manifest_hash],
        )

    def test_missing_and_hash_integrity_errors_propagate(self) -> None:
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            read_exact_evidence_inputs(
                self.store,
                ("not-an-evidence-identity",),
                required_schemas=("test_surface.v1",),
            )

        missing = sha256(b"missing evidence").hexdigest()
        (self.root / "sha256" / missing[:2]).mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            read_exact_evidence_inputs(
                self.store,
                (missing,),
                required_schemas=("test_surface.v1",),
            )

        corrupt_identity = sha256(b"expected bytes").hexdigest()
        corrupt_path = (
            self.root / "sha256" / corrupt_identity[:2] / corrupt_identity
        )
        corrupt_path.parent.mkdir(parents=True)
        corrupt_path.write_bytes(b"wrong bytes")
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            read_exact_evidence_inputs(
                self.store,
                (corrupt_identity,),
                required_schemas=("test_surface.v1",),
            )

    def test_duplicate_input_identity_is_rejected_before_read(self) -> None:
        surface_hash = self._canonical({"schema": "test_surface.v1"})
        with (
            patch.object(
                self.store,
                "read_verified",
                wraps=self.store.read_verified,
            ) as read_verified,
            self.assertRaisesRegex(ValueError, "identities must be unique"),
        ):
            read_exact_evidence_inputs(
                self.store,
                (surface_hash, surface_hash),
                required_schemas=("test_surface.v1",),
            )
        read_verified.assert_not_called()

    def test_duplicate_requested_schema_role_is_rejected(self) -> None:
        first = self._canonical({"schema": "test_surface.v1", "value": 1})
        second = self._canonical({"schema": "test_surface.v1", "value": 2})

        with self.assertRaisesRegex(ValueError, "observed 2"):
            read_exact_evidence_inputs(
                self.store,
                (first, second),
                required_schemas=("test_surface.v1",),
            )

    def test_verified_unrelated_and_noncanonical_inputs_are_skipped(self) -> None:
        unrelated = self._canonical({"schema": "unrelated.v1"})
        noncanonical = self.store.finalize(b'{"schema": "not-canonical.v1"}').sha256
        surface = self._canonical({"schema": "test_surface.v1"})
        manifest = self._canonical(
            {
                "schema": "test_surface_manifest.v1",
                "surface_artifact_hash": surface,
                "surface_implementation_sha256": (
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            }
        )
        identities = (unrelated, noncanonical, surface, manifest)

        with patch.object(
            self.store,
            "read_verified",
            wraps=self.store.read_verified,
        ) as read_verified:
            result = read_surface_manifest_evidence_inputs(
                self.store,
                identities,
                surface_schema="test_surface.v1",
                manifest_schema="test_surface_manifest.v1",
                expected_surface_implementation_sha256=(
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            )

        self.assertEqual(result.surface.artifact_sha256, surface)
        self.assertEqual(read_verified.call_count, len(identities))
        self.assertEqual(
            [call.args[0] for call in read_verified.call_args_list],
            list(identities),
        )

    def test_wrong_surface_manifest_binding_is_rejected(self) -> None:
        surface = self._canonical({"schema": "test_surface.v1"})
        manifest = self._canonical(
            {
                "schema": "test_surface_manifest.v1",
                "surface_artifact_hash": "0" * 64,
                "surface_implementation_sha256": (
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            }
        )

        with self.assertRaisesRegex(ValueError, "another artifact"):
            read_surface_manifest_evidence_inputs(
                self.store,
                (surface, manifest),
                surface_schema="test_surface.v1",
                manifest_schema="test_surface_manifest.v1",
                expected_surface_implementation_sha256=(
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            )

    def test_surface_manifest_requires_exact_implementation_digest(self) -> None:
        surface = self._canonical({"schema": "test_surface.v1"})
        cases = (
            ("missing", None, "lowercase SHA-256"),
            ("wrong", "2" * 64, "differs from expectation"),
            ("non-digest", "NOT-A-DIGEST", "lowercase SHA-256"),
        )
        for name, implementation, error in cases:
            manifest_value = {
                "schema": "test_surface_manifest.v1",
                "surface_artifact_hash": surface,
            }
            if implementation is not None:
                manifest_value["surface_implementation_sha256"] = implementation
            manifest = self._canonical(manifest_value)
            with self.subTest(name=name):
                with patch.object(
                    self.store,
                    "read_verified",
                    wraps=self.store.read_verified,
                ) as read_verified:
                    with self.assertRaisesRegex(ValueError, error):
                        read_surface_manifest_evidence_inputs(
                            self.store,
                            (surface, manifest),
                            surface_schema="test_surface.v1",
                            manifest_schema="test_surface_manifest.v1",
                            expected_surface_implementation_sha256=(
                                EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                            ),
                        )
                self.assertEqual(
                    [call.args[0] for call in read_verified.call_args_list],
                    [surface, manifest],
                )

    def test_expected_surface_implementation_must_be_a_digest(self) -> None:
        surface = self._canonical({"schema": "test_surface.v1"})
        manifest = self._canonical(
            {
                "schema": "test_surface_manifest.v1",
                "surface_artifact_hash": surface,
                "surface_implementation_sha256": (
                    EXPECTED_SURFACE_IMPLEMENTATION_SHA256
                ),
            }
        )
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            read_surface_manifest_evidence_inputs(
                self.store,
                (surface, manifest),
                surface_schema="test_surface.v1",
                manifest_schema="test_surface_manifest.v1",
                expected_surface_implementation_sha256="A" * 64,
            )

    def test_all_active_study_input_wrappers_resolve_their_exact_roles(self) -> None:
        surface_consumers = (
            ("analog_state_study", "_load_surface", "analog_state_surface.v2", "analog_state_surface_manifest.v2"),
            ("cost_aware_execution_study", "_load_surface", "cost_aware_execution_surface.v1", "cost_aware_execution_surface_manifest.v1"),
            ("dense_short_synthesis_study", "_load_surface", "dense_short_synthesis_surface.v1", "dense_short_synthesis_surface_manifest.v1"),
            ("equity_premium_trade_study", "_load_surface", "equity_premium_trade_surface.v1", "equity_premium_trade_surface_manifest.v1"),
            ("event_direction_meta_study", "_load", "event_direction_meta_surface.v1", "event_direction_meta_surface_manifest.v1"),
            ("fold_interaction_model_study", "_load_surface", "fold_interaction_model_surface.v1", "fold_interaction_model_surface_manifest.v1"),
            ("fold_train_target_role_study", "_load", "fold_train_target_role_surface.v1", "fold_train_target_role_surface_manifest.v1"),
            ("high_vol_dense_regime_study", "_load_surface", "high_vol_dense_regime_surface.v1", "high_vol_dense_regime_surface_manifest.v1"),
            ("high_vol_target_reversal_study", "_load", "high_vol_target_reversal_surface.v1", "high_vol_target_reversal_surface_manifest.v1"),
            ("independent_sleeve_portfolio_study", "_load_surface", "independent_sleeve_portfolio_surface.v1", "independent_sleeve_portfolio_surface_manifest.v1"),
            ("low_vol_abstention_study", "_load", "low_vol_abstention_surface.v1", "low_vol_abstention_surface_manifest.v1"),
            ("monthly_loss_lock_risk_study", "_load_surface", "monthly_loss_lock_risk_surface.v1", "monthly_loss_lock_risk_surface_manifest.v1"),
            ("path_occupancy_label_study", "_load_surface", "path_occupancy_label_surface.v1", "path_occupancy_label_surface_manifest.v1"),
            ("positive_direction_sleeve_study", "_load", "positive_direction_sleeve_surface.v1", "positive_direction_sleeve_surface_manifest.v1"),
            ("regime_direction_router_study", "_load_surface", "regime_direction_router_surface.v1", "regime_direction_router_surface_manifest.v1"),
            ("residual_quote_deferral_study", "_load_surface", "residual_quote_deferral_surface.v1", "residual_quote_deferral_surface_manifest.v1"),
            ("session_dense_positive_sleeve_study", "_load", "session_dense_positive_sleeve_surface.v1", "session_dense_positive_sleeve_surface_manifest.v1"),
            ("shadow_slot_lifecycle_study", "_load_surface", "shadow_slot_lifecycle_surface.v1", "shadow_slot_lifecycle_surface_manifest.v1"),
            ("three_way_regime_router_study", "_load_surface", "three_way_regime_router_surface.v1", "three_way_regime_router_surface_manifest.v1"),
            ("trend_regime_study", "_load_surface", "trend_regime_evaluation_surface.v1", "trend_regime_surface_manifest.v1"),
            ("volatility_clock_label_study", "_load_surface", "volatility_clock_label_surface.v1", "volatility_clock_label_surface_manifest.v1"),
            ("volatility_stop_risk_study", "_load_surface", "volatility_stop_risk_surface.v1", "volatility_stop_risk_surface_manifest.v1"),
        )
        implementation_functions = {
            "analog_state_study": "analog_implementation_sha256",
            "cost_aware_execution_study": (
                "cost_aware_execution_implementation_sha256"
            ),
            "dense_short_synthesis_study": (
                "dense_short_synthesis_discovery_implementation_sha256"
            ),
            "equity_premium_trade_study": (
                "equity_premium_trade_discovery_implementation_sha256"
            ),
            "event_direction_meta_study": (
                "event_direction_meta_discovery_implementation_sha256"
            ),
            "fold_interaction_model_study": (
                "fold_interaction_model_discovery_implementation_sha256"
            ),
            "fold_train_target_role_study": (
                "fold_train_target_role_discovery_implementation_sha256"
            ),
            "high_vol_dense_regime_study": (
                "high_vol_dense_regime_discovery_implementation_sha256"
            ),
            "high_vol_target_reversal_study": (
                "high_vol_target_reversal_discovery_implementation_sha256"
            ),
            "independent_sleeve_portfolio_study": (
                "independent_sleeve_portfolio_discovery_implementation_sha256"
            ),
            "low_vol_abstention_study": (
                "low_vol_abstention_discovery_implementation_sha256"
            ),
            "monthly_loss_lock_risk_study": (
                "monthly_loss_lock_risk_discovery_implementation_sha256"
            ),
            "path_occupancy_label_study": (
                "path_occupancy_label_implementation_sha256"
            ),
            "positive_direction_sleeve_study": (
                "positive_direction_sleeve_discovery_implementation_sha256"
            ),
            "regime_direction_router_study": (
                "regime_direction_router_discovery_implementation_sha256"
            ),
            "residual_quote_deferral_study": (
                "residual_quote_deferral_discovery_implementation_sha256"
            ),
            "session_dense_positive_sleeve_study": (
                "session_dense_positive_sleeve_discovery_implementation_sha256"
            ),
            "shadow_slot_lifecycle_study": (
                "shadow_slot_lifecycle_discovery_implementation_sha256"
            ),
            "three_way_regime_router_study": (
                "three_way_regime_router_discovery_implementation_sha256"
            ),
            "trend_regime_study": (
                "trend_regime_discovery_implementation_sha256"
            ),
            "volatility_clock_label_study": (
                "volatility_clock_label_discovery_implementation_sha256"
            ),
            "volatility_stop_risk_study": (
                "volatility_stop_risk_discovery_implementation_sha256"
            ),
        }
        context = SimpleNamespace(evidence=self.store)
        observed: list[str] = []
        for module_name, loader_name, surface_schema, manifest_schema in surface_consumers:
            module = import_module(f"axiom_rift.research.{module_name}")
            implementation_sha256 = getattr(
                module,
                implementation_functions[module_name],
            )()
            surface_hash = self._canonical({"schema": surface_schema})
            manifest_hash = self._canonical(
                {
                    "schema": manifest_schema,
                    "surface_artifact_hash": surface_hash,
                    "surface_implementation_sha256": implementation_sha256,
                }
            )
            value, observed_surface, observed_manifest = getattr(
                module, loader_name
            )(context, (surface_hash, manifest_hash))
            self.assertEqual(value["schema"], surface_schema)
            self.assertEqual(observed_surface, surface_hash)
            self.assertEqual(observed_manifest, manifest_hash)
            observed.append(f"{module_name}.py")

        cache_consumers = (
            (
                "us30_downside_spillover_study",
                "us30_downside_spillover_surface_cache_manifest.v1",
            ),
            (
                "us30_sector_rotation_study",
                "us30_sector_rotation_surface_cache_manifest.v1",
            ),
        )
        for module_name, manifest_schema in cache_consumers:
            manifest_hash = self._canonical({"schema": manifest_schema})
            module = import_module(f"axiom_rift.research.{module_name}")
            validated = {"schema": manifest_schema, "validated": True}
            with patch.object(
                module,
                "_validate_surface_manifest",
                return_value=validated,
            ):
                observed_manifest, value = module._load_surface_manifest(
                    context,
                    repository_root=Path(self.temporary.name),
                    input_hashes=(manifest_hash,),
                    cache_hash="a" * 64,
                    environment_hash="b" * 64,
                )
            self.assertEqual(observed_manifest, manifest_hash)
            self.assertEqual(value, validated)
            observed.append(f"{module_name}.py")

        self.assertEqual(tuple(sorted(observed)), tuple(sorted(ACTIVE_RESEARCH_EVIDENCE_CONSUMERS)))


class EvidenceStoreRoleBoundaryTests(unittest.TestCase):
    def test_all_active_study_consumers_use_the_common_snapshot_helper(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        research_root = repository_root / "src" / "axiom_rift" / "research"
        observed: list[str] = []
        implementation_bound: list[str] = []

        for name in ACTIVE_RESEARCH_EVIDENCE_CONSUMERS:
            path = research_root / name
            tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
            helper_call_nodes = tuple(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                in {
                    "read_exact_evidence_inputs",
                    "read_surface_manifest_evidence_inputs",
                }
            )
            helper_calls = {node.func.id for node in helper_call_nodes}
            if helper_calls:
                observed.append(name)
            surface_calls = tuple(
                node
                for node in helper_call_nodes
                if node.func.id == "read_surface_manifest_evidence_inputs"
            )
            if surface_calls and all(
                any(
                    keyword.arg == "expected_surface_implementation_sha256"
                    for keyword in node.keywords
                )
                for node in surface_calls
            ):
                implementation_bound.append(name)

        self.assertEqual(tuple(observed), ACTIVE_RESEARCH_EVIDENCE_CONSUMERS)
        self.assertEqual(
            tuple(implementation_bound),
            tuple(
                name
                for name in ACTIVE_RESEARCH_EVIDENCE_CONSUMERS
                if name
                not in {
                    "us30_downside_spillover_study.py",
                    "us30_sector_rotation_study.py",
                }
            ),
        )

    def test_active_production_never_reads_the_private_evidence_root(self) -> None:
        repository_root = REPOSITORY_ROOT
        source_root = repository_root / "src" / "axiom_rift"
        frozen = {
            source_root / "research" / name
            for name in HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256
        }
        allowed_private_root_owners = frozen | {
            source_root / "research" / "data.py",
            source_root / "storage" / "evidence.py",
        }
        violations: list[str] = []

        for path in _tracked_axiom_python_paths():
            if path in allowed_private_root_owners:
                continue
            tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "_root":
                    violations.append(
                        f"{path.relative_to(repository_root).as_posix()}:{node.lineno}"
                    )

        self.assertEqual(violations, [])

    def test_untracked_decoy_cannot_change_the_audited_source_closure(self) -> None:
        research_root = REPOSITORY_ROOT / "src" / "axiom_rift" / "research"
        baseline = _tracked_axiom_python_paths()
        with TemporaryDirectory(
            dir=research_root,
            prefix=".axiom-untracked-evidence-decoy-",
        ) as temporary:
            decoy = Path(temporary) / "raw_store_escape.py"
            decoy.write_text(
                "from axiom_rift.storage.evidence import EvidenceStore\n",
                encoding="ascii",
            )
            observed = _tracked_axiom_python_paths()
            self.assertNotIn(decoy, observed)
            self.assertEqual(observed, baseline)
        self.assertTrue(
            PROTECTED_AXIOM_SOURCE_PATHS.isdisjoint(baseline)
        )

    def test_raw_store_compatibility_paths_are_exact_and_reconstruction_only(
        self,
    ) -> None:
        observed: set[str] = set()
        for path in _tracked_axiom_python_paths():
            try:
                relative = path.relative_to(
                    REPOSITORY_ROOT / "src"
                ).as_posix()
            except ValueError:
                continue
            if not relative.startswith("axiom_rift/research/"):
                continue
            tree = ast.parse(path.read_text(encoding="ascii"), filename=str(path))
            if any(
                isinstance(node, ast.ImportFrom)
                and node.module == "axiom_rift.storage.evidence"
                and any(alias.name == "EvidenceStore" for alias in node.names)
                for node in ast.walk(tree)
            ):
                observed.add(relative)

        self.assertEqual(
            observed,
            set(HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS),
        )


if __name__ == "__main__":
    unittest.main()
