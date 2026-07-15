from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from importlib import util
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.operations.external_observed_development_binding import (
    ExternalObservedDevelopmentJobBindingError,
    build_external_observed_development_job_spec,
    external_observed_development_job_binding,
    external_observed_development_job_input_hashes,
    require_current_external_observed_development_job_binding,
    verify_external_observed_development_job_prefixes,
)
from axiom_rift.research import external_observed_development as boundary
from axiom_rift.research.external_observed_development import (
    ExternalObservedDevelopment,
    ExternalObservedDevelopmentError,
    ExternalObservedDevelopmentMetadata,
    ExternalObservedDevelopmentSpec,
    load_external_observed_development,
    prospective_external_source_job_binding,
    publish_immutable_raw_snapshot,
)
from axiom_rift.research import cross_asset_downside_spillover_discovery
from axiom_rift.research import cross_asset_relative_strength_discovery
from axiom_rift.research import us30_downside_spillover_discovery
from axiom_rift.research import us30_sector_rotation_discovery
from axiom_rift.research import us500_market_coherence_discovery
from axiom_rift.research import usdjpy_carry_exit_discovery
from axiom_rift.research import us500_market_coherence_chassis
from axiom_rift.research import usdjpy_carry_exit_chassis
from axiom_rift.research import us30_source
from axiom_rift.research import us500_source
from axiom_rift.research import usdjpy_source


REPO_ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER_PATH = (
    REPO_ROOT / "scripts" / "materialize_external_observed_development.py"
)
HEADER = b"time,open,high,low,close,tick_volume,spread,real_volume\n"


def _load_materializer():
    spec = util.spec_from_file_location("external_prefix_materializer", MATERIALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("external materializer cannot be imported")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALIZER = _load_materializer()


def _fixture_bytes() -> tuple[bytes, bytes]:
    rows = (
        b"2026.04.30 23:45:00,100,102,99,101,10,1,0\n",
        b"2026.04.30 23:50:00,101,103,100,102,11,1,0\n",
        b"2026.04.30 23:55:00,102,104,101,103,12,1,0\n",
    )
    prefix = HEADER + b"".join(rows)
    raw = prefix + b"2026.05.01 00:00:00,999,999,999,999,99,9,9,TAIL_SENTINEL\n"
    return prefix, raw


def _fixture_spec(prefix: bytes, raw: bytes) -> ExternalObservedDevelopmentSpec:
    return ExternalObservedDevelopmentSpec(
        source_key="TEST",
        raw_relative_path="data/raw/mt5_bars/m5/TEST.csv",
        parent_raw_sha256=sha256(raw).hexdigest(),
        prefix_relative_path=(
            "data/processed/datasets/test_m5_observed_development.csv"
        ),
        prefix_sha256=sha256(prefix).hexdigest(),
        prefix_byte_count=len(prefix),
        row_count=3,
        first_time="2026.04.30 23:45:00",
        last_time="2026.04.30 23:55:00",
    )


def _write_fixture(root: Path, *, prefix_content: bytes | None = None):
    prefix, raw = _fixture_bytes()
    spec = _fixture_spec(prefix, raw)
    raw_path = root / spec.raw_relative_path
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)
    if prefix_content is not None:
        prefix_path = root / spec.prefix_relative_path
        prefix_path.parent.mkdir(parents=True)
        prefix_path.write_bytes(prefix_content)
    return spec, prefix, raw, raw_path


def _job_spec(executable_id: str, input_hashes: tuple[str, ...]) -> dict[str, object]:
    return {
        "evidence_subject": {"kind": "Executable", "id": executable_id},
        "input_hashes": list(sorted(input_hashes)),
    }


def _manifest_id(manifest: dict[str, object]) -> str:
    return "executable:" + canonical_digest(domain="executable", payload=manifest)


def _loader_source_dependencies() -> tuple[dict[str, str], ...]:
    return (
        {
            "path": "axiom_rift/research/external_observed_development.py",
            "sha256": (
                boundary.external_observed_development_loader_implementation_sha256()
            ),
        },
    )


def _unrelated_source_dependencies() -> tuple[dict[str, str], ...]:
    return (
        {
            "path": "axiom_rift/research/unrelated.py",
            "sha256": "a" * 64,
        },
    )


def _fixture_executable(spec: ExternalObservedDevelopmentSpec) -> ExecutableSpec:
    loader = boundary.external_observed_development_loader_implementation_sha256()
    component = ComponentSpec(
        display_name=f"{spec.source_key} exact external development fixture",
        protocol="external_source.test_m5.v1",
        implementation="test:external-prefix-consumer",
        spec={
            "development_loader_implementation_sha256": loader,
            "development_material_identity": spec.material_identity,
            "development_prefix_byte_count": spec.prefix_byte_count,
            "development_prefix_row_count": spec.row_count,
            "development_prefix_sha256": spec.prefix_sha256,
            "development_source_key": spec.source_key,
            "raw_sha256": spec.parent_raw_sha256,
            "raw_sha256_role": "acquisition_identity_only",
        },
    )
    return ExecutableSpec(
        display_name=f"{spec.source_key} external fixture",
        components=(component,),
        parameters={},
        data_contract="data:" + "a" * 64,
        split_contract="split:" + "b" * 64,
        clock_contract="clock:test",
        cost_contract="cost:test",
        engine_contract=(
            f"engine:test:external_development_material_{spec.material_identity}:"
            f"external_development_prefix_{spec.prefix_sha256}:"
            f"external_loader_{loader}"
        ),
    )


class ExternalObservedDevelopmentBoundaryTests(unittest.TestCase):
    def test_loader_never_opens_raw_parent(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, prefix, _, raw_path = _write_fixture(root, prefix_content=_fixture_bytes()[0])
            original_open = Path.open

            def guarded_open(path: Path, *args: object, **kwargs: object):
                if path.resolve() == raw_path.resolve():
                    raise AssertionError("routine loader opened the raw parent")
                return original_open(path, *args, **kwargs)

            with patch.dict(boundary._SPECS, {"TEST": spec}), patch.object(
                Path, "open", new=guarded_open
            ):
                loaded = load_external_observed_development(root, "TEST")

            self.assertEqual(len(loaded.frame), 3)
            self.assertEqual(loaded.metadata.development_prefix_sha256, sha256(prefix).hexdigest())
            self.assertEqual(tuple(loaded.frame.columns), ("time", "close"))

    def test_missing_and_mismatched_prefix_fail_before_raw(self) -> None:
        for case in ("missing", "mismatch"):
            with self.subTest(case=case), TemporaryDirectory() as temporary:
                root = Path(temporary)
                content = None if case == "missing" else b"mismatched-prefix\n"
                spec, _, _, raw_path = _write_fixture(root, prefix_content=content)
                original_open = Path.open
                raw_opened = False

                def guarded_open(path: Path, *args: object, **kwargs: object):
                    nonlocal raw_opened
                    if path.resolve() == raw_path.resolve():
                        raw_opened = True
                        raise AssertionError("failure path opened the raw parent")
                    return original_open(path, *args, **kwargs)

                with patch.dict(boundary._SPECS, {"TEST": spec}), patch.object(
                    Path, "open", new=guarded_open
                ):
                    with self.assertRaises(ExternalObservedDevelopmentError):
                        load_external_observed_development(root, "TEST")
                self.assertFalse(raw_opened)

    def test_prefix_path_rejects_symlink(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, prefix, _, _ = _write_fixture(root)
            outside = root / "outside.csv"
            outside.write_bytes(prefix)
            prefix_path = root / spec.prefix_relative_path
            prefix_path.parent.mkdir(parents=True)
            try:
                prefix_path.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")
            with patch.dict(boundary._SPECS, {"TEST": spec}):
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentError, "link-like"
                ):
                    load_external_observed_development(root, "TEST")
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentError, "link-like"
                ):
                    MATERIALIZER.materialize_external_observed_development(
                        root, "TEST"
                    )

    def test_identity_scan_rejects_same_size_same_mtime_path_inode_swap(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, prefix, _, _ = _write_fixture(root, prefix_content=_fixture_bytes()[0])
            prefix_path = root / spec.prefix_relative_path
            real = prefix_path.lstat()
            swapped = SimpleNamespace(
                st_dev=real.st_dev,
                st_ino=real.st_ino + 1,
                st_mode=real.st_mode,
                st_mtime_ns=real.st_mtime_ns,
                st_size=real.st_size,
            )
            with patch.dict(boundary._SPECS, {"TEST": spec}), patch.object(
                boundary,
                "_regular_lstat",
                side_effect=(real, swapped),
            ):
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentError, "path identity"
                ):
                    boundary.verify_external_observed_development_prefix_identity(
                        root, "TEST"
                    )
            self.assertEqual(prefix_path.read_bytes(), prefix)

    def test_prospective_job_requires_prefix_and_material_inputs(self) -> None:
        spec = boundary.US500_OBSERVED_DEVELOPMENT_SPEC
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentError, "omits its exact prefix"
        ):
            prospective_external_source_job_binding(
                "US500", input_hashes=(spec.parent_raw_sha256,)
            )
        binding = prospective_external_source_job_binding(
            "US500", input_hashes=spec.job_input_hashes()
        )
        payload = binding.to_payload()
        self.assertEqual(payload["development_prefix_sha256"], spec.prefix_sha256)
        self.assertEqual(payload["material_identity"], spec.material_identity)
        self.assertEqual(len(payload["loader_implementation_sha256"]), 64)

    def test_spec_rejects_bool_counts_noncanonical_keys_and_bad_times(self) -> None:
        prefix, raw = _fixture_bytes()
        base = {
            "source_key": "TEST",
            "raw_relative_path": "data/raw/mt5_bars/m5/TEST.csv",
            "parent_raw_sha256": sha256(raw).hexdigest(),
            "prefix_relative_path": (
                "data/processed/datasets/test_m5_observed_development.csv"
            ),
            "prefix_sha256": sha256(prefix).hexdigest(),
            "prefix_byte_count": len(prefix),
            "row_count": 3,
            "first_time": "2026.04.30 23:45:00",
            "last_time": "2026.04.30 23:55:00",
        }
        cases = (
            ("prefix_byte_count", True),
            ("row_count", False),
            ("source_key", "test"),
            ("source_key", "TEST/TAIL"),
            ("source_key", "T\u00c9ST"),
            ("first_time", "NaT"),
            ("first_time", "2026.04.30 23:45:00+09:00"),
            ("last_time", "2026.04.30 23:56:00"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                kwargs = dict(base)
                kwargs[field] = value
                with self.assertRaises(ValueError):
                    ExternalObservedDevelopmentSpec(**kwargs)

    def test_prospective_executables_bind_exact_prefix_and_loader_identity(self) -> None:
        us30 = boundary.US30_OBSERVED_DEVELOPMENT_SPEC
        us500 = boundary.US500_OBSERVED_DEVELOPMENT_SPEC
        usdjpy = boundary.USDJPY_OBSERVED_DEVELOPMENT_SPEC
        loader_hash = (
            boundary.external_observed_development_loader_implementation_sha256()
        )
        downside_configurations = (
            cross_asset_downside_spillover_discovery
            .cross_asset_downside_spillover_configurations()
        )
        downside_configuration = downside_configurations[0]
        strength_configuration = (
            cross_asset_relative_strength_discovery.cross_asset_relative_strength_configurations()[
                0
            ]
        )
        cases = (
            (
                cross_asset_downside_spillover_discovery.cross_asset_downside_spillover_executable(
                    downside_configuration,
                    us500.parent_raw_sha256,
                ),
                us500,
            ),
            (
                cross_asset_relative_strength_discovery.cross_asset_relative_strength_executable(
                    strength_configuration,
                    us500.parent_raw_sha256,
                ),
                us500,
            ),
            (
                us30_downside_spillover_discovery.us30_downside_spillover_executable(
                    us30_downside_spillover_discovery.us30_downside_spillover_configurations()[0],
                    us30.parent_raw_sha256,
                ),
                us30,
            ),
            (
                us30_sector_rotation_discovery.us30_sector_rotation_executable(
                    us30_sector_rotation_discovery.us30_sector_rotation_configurations()[0],
                    us30.parent_raw_sha256,
                ),
                us30,
            ),
            (
                us500_market_coherence_chassis.us500_market_coherence_executable(
                    us500_market_coherence_chassis.us500_market_coherence_configurations()[1]
                ),
                us500,
            ),
            (
                usdjpy_carry_exit_chassis.usdjpy_carry_exit_executable(
                    usdjpy_carry_exit_chassis.usdjpy_carry_exit_configurations()[1]
                ),
                usdjpy,
            ),
        )
        for executable, spec in cases:
            with self.subTest(source=spec.source_key, executable=executable.display_name):
                self.assertIn(spec.prefix_sha256, executable.engine_contract)
                self.assertIn(spec.material_identity, executable.engine_contract)
                self.assertIn(loader_hash, executable.engine_contract)

    def test_all_public_discovery_wrappers_delegate_to_central_loader(self) -> None:
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(["2026-04-30 23:55:00"]),
                "close": [100.0],
            }
        )
        cases = (
            (
                cross_asset_downside_spillover_discovery,
                "load_us500_observed_development",
                "US500",
            ),
            (
                cross_asset_relative_strength_discovery,
                "load_us500_observed_development",
                "US500",
            ),
            (
                us30_downside_spillover_discovery,
                "load_us30_observed_development",
                "US30",
            ),
            (
                us30_sector_rotation_discovery,
                "load_us30_observed_development",
                "US30",
            ),
            (
                us500_market_coherence_discovery,
                "load_us500_development",
                "US500",
            ),
            (
                usdjpy_carry_exit_discovery,
                "load_usdjpy_development",
                "USDJPY",
            ),
        )
        for module, function_name, source_key in cases:
            with self.subTest(module=module.__name__):
                source_spec = boundary.external_observed_development_spec(source_key)
                loaded = ExternalObservedDevelopment(
                    frame=frame,
                    metadata=ExternalObservedDevelopmentMetadata(
                        source_key=source_key,
                        parent_raw_sha256=source_spec.parent_raw_sha256,
                        development_prefix_sha256=source_spec.prefix_sha256,
                        material_identity=source_spec.material_identity,
                        prefix_byte_count=source_spec.prefix_byte_count,
                        development_row_count=source_spec.row_count,
                        first_time=pd.Timestamp(source_spec.first_time),
                        last_time=pd.Timestamp(source_spec.last_time),
                        source_path=Path(source_spec.prefix_relative_path),
                    ),
                )
                with patch.object(
                    module,
                    "load_external_observed_development",
                    return_value=loaded,
                ) as central:
                    result = getattr(module, function_name)(REPO_ROOT)
                central.assert_called_once_with(REPO_ROOT, source_key)
                observed_raw = (
                    result.raw_sha256
                    if hasattr(result, "raw_sha256")
                    else result.metadata.raw_sha256
                )
                self.assertEqual(observed_raw, source_spec.parent_raw_sha256)


class ExternalObservedDevelopmentJobBindingTests(unittest.TestCase):
    @staticmethod
    def _us30_executable() -> ExecutableSpec:
        spec = boundary.US30_OBSERVED_DEVELOPMENT_SPEC
        return us30_downside_spillover_discovery.us30_downside_spillover_executable(
            us30_downside_spillover_discovery.us30_downside_spillover_configurations()[0],
            spec.parent_raw_sha256,
        )

    @staticmethod
    def _us500_executable() -> ExecutableSpec:
        spec = boundary.US500_OBSERVED_DEVELOPMENT_SPEC
        configurations = (
            cross_asset_relative_strength_discovery.cross_asset_relative_strength_configurations()
        )
        return cross_asset_relative_strength_discovery.cross_asset_relative_strength_executable(
            configurations[0],
            spec.parent_raw_sha256,
        )

    def test_exact_production_manifest_builds_durable_binding(self) -> None:
        executable = self._us30_executable()
        source = boundary.US30_OBSERVED_DEVELOPMENT_SPEC
        binding = external_observed_development_job_binding(
            executable_id=executable.identity,
            executable_manifest=executable.to_identity_payload(),
            job_spec=_job_spec(executable.identity, source.job_input_hashes()),
            source_closure_dependencies=_loader_source_dependencies(),
        )
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(
            [item["source_key"] for item in binding.to_payload()["source_bindings"]],
            ["US30"],
        )
        self.assertEqual(
            binding.to_payload()["source_bindings"][0]["development_prefix_sha256"],
            source.prefix_sha256,
        )

    def test_public_job_input_builder_supports_each_production_source(self) -> None:
        cases = (
            (self._us30_executable(), boundary.US30_OBSERVED_DEVELOPMENT_SPEC),
            (self._us500_executable(), boundary.US500_OBSERVED_DEVELOPMENT_SPEC),
            (
                usdjpy_carry_exit_chassis.usdjpy_carry_exit_executable(
                    usdjpy_carry_exit_chassis.usdjpy_carry_exit_configurations()[1]
                ),
                boundary.USDJPY_OBSERVED_DEVELOPMENT_SPEC,
            ),
        )
        for executable, source in cases:
            with self.subTest(source=source.source_key):
                required = external_observed_development_job_input_hashes(
                    executable_manifest=executable.to_identity_payload(),
                    source_closure_dependencies=_loader_source_dependencies(),
                )
                self.assertEqual(required, source.job_input_hashes())
                job = build_external_observed_development_job_spec(
                    base_job_spec=_job_spec(
                        executable.identity,
                        ("a" * 64,),
                    ),
                    executable_manifest=executable.to_identity_payload(),
                    source_closure_dependencies=_loader_source_dependencies(),
                )
                self.assertEqual(
                    job["input_hashes"],
                    list(sorted({*required, "a" * 64})),
                )
                binding = external_observed_development_job_binding(
                    executable_id=executable.identity,
                    executable_manifest=executable.to_identity_payload(),
                    job_spec=job,
                    source_closure_dependencies=_loader_source_dependencies(),
                )
                self.assertIsNotNone(binding)

    def test_known_raw_consumer_with_missing_prefix_manifest_fails_closed(self) -> None:
        executable = self._us500_executable()
        manifest = deepcopy(executable.to_identity_payload())
        source_component = next(
            component
            for component in manifest["component_manifests"]
            if component["spec"].get("raw_sha256")
            == boundary.US500_OBSERVED_DEVELOPMENT_SPEC.parent_raw_sha256
        )
        for field in tuple(source_component["spec"]):
            if field.startswith("development_"):
                source_component["spec"].pop(field)
        mutated_id = _manifest_id(manifest)
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentJobBindingError,
            "omits exact observed-development fields",
        ):
            external_observed_development_job_binding(
                executable_id=mutated_id,
                executable_manifest=manifest,
                job_spec=_job_spec(mutated_id, ("a" * 64,)),
                source_closure_dependencies=_loader_source_dependencies(),
            )

    def test_unrelated_executable_and_non_executable_job_are_unchanged(self) -> None:
        executable = us500_market_coherence_chassis.frontier_executable()
        self.assertIsNone(
            external_observed_development_job_binding(
                executable_id=executable.identity,
                executable_manifest=executable.to_identity_payload(),
                job_spec=_job_spec(executable.identity, ("a" * 64,)),
                source_closure_dependencies=_unrelated_source_dependencies(),
            )
        )
        self.assertIsNone(
            external_observed_development_job_binding(
                executable_id=executable.identity,
                executable_manifest={},
                job_spec={
                    "evidence_subject": {"kind": "Study", "id": "study:unrelated"},
                    "input_hashes": ["a" * 64],
                },
                source_closure_dependencies=(),
            )
        )

    def test_manifest_and_source_closure_are_bidirectionally_bound(self) -> None:
        external = self._us30_executable()
        external_job = _job_spec(
            external.identity,
            boundary.US30_OBSERVED_DEVELOPMENT_SPEC.job_input_hashes(),
        )
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentJobBindingError,
            "manifest and implementation source closure disagree",
        ):
            external_observed_development_job_binding(
                executable_id=external.identity,
                executable_manifest=external.to_identity_payload(),
                job_spec=external_job,
                source_closure_dependencies=_unrelated_source_dependencies(),
            )

        unrelated = us500_market_coherence_chassis.frontier_executable()
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentJobBindingError,
            "manifest and implementation source closure disagree",
        ):
            external_observed_development_job_binding(
                executable_id=unrelated.identity,
                executable_manifest=unrelated.to_identity_payload(),
                job_spec=_job_spec(unrelated.identity, ("a" * 64,)),
                source_closure_dependencies=_loader_source_dependencies(),
            )

        wrong_loader = (
            {
                "path": "axiom_rift/research/external_observed_development.py",
                "sha256": "f" * 64,
            },
        )
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentJobBindingError,
            "loader hash differs",
        ):
            external_observed_development_job_binding(
                executable_id=external.identity,
                executable_manifest=external.to_identity_payload(),
                job_spec=external_job,
                source_closure_dependencies=wrong_loader,
            )

    def test_multi_source_binding_is_the_exact_sorted_set(self) -> None:
        us30 = self._us30_executable()
        us500 = self._us500_executable()
        components = (us30.components[0], us500.components[0])
        sources = tuple(
            sorted(
                {
                    dependency
                    for component in components
                    for dependency in component.semantic_dependencies
                    if dependency.startswith("source:")
                }
            )
        )
        executable = ExecutableSpec(
            display_name="US30 and US500 exact prefix fixture",
            components=components,
            parameters={},
            data_contract=us30.data_contract,
            split_contract=us30.split_contract,
            clock_contract=us30.clock_contract,
            cost_contract=us30.cost_contract,
            engine_contract=us30.engine_contract + ":" + us500.engine_contract,
            source_contracts=sources,
        )
        inputs = tuple(
            sorted(
                {
                    *boundary.US30_OBSERVED_DEVELOPMENT_SPEC.job_input_hashes(),
                    *boundary.US500_OBSERVED_DEVELOPMENT_SPEC.job_input_hashes(),
                }
            )
        )
        binding = external_observed_development_job_binding(
            executable_id=executable.identity,
            executable_manifest=executable.to_identity_payload(),
            job_spec=_job_spec(executable.identity, inputs),
            source_closure_dependencies=_loader_source_dependencies(),
        )
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(
            tuple(item.source_key for item in binding.source_bindings),
            ("US30", "US500"),
        )

    def test_duplicate_unknown_and_registry_drift_fail_closed(self) -> None:
        executable = self._us30_executable()
        original = executable.to_identity_payload()
        source_component_index = next(
            index
            for index, component in enumerate(original["component_manifests"])
            if component["spec"].get("development_source_key") == "US30"
        )
        cases = (
            ("development_source_key", "UNKNOWN", "unknown development source"),
            ("development_material_identity", "d" * 64, "differs from the current"),
            ("development_prefix_sha256", "e" * 64, "differs from the current"),
            (
                "development_loader_implementation_sha256",
                "f" * 64,
                "differs from the current",
            ),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                manifest = deepcopy(original)
                manifest["component_manifests"][source_component_index]["spec"][field] = value
                mutated_id = _manifest_id(manifest)
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentJobBindingError, message
                ):
                    external_observed_development_job_binding(
                        executable_id=mutated_id,
                        executable_manifest=manifest,
                        job_spec=_job_spec(
                            mutated_id,
                            boundary.US30_OBSERVED_DEVELOPMENT_SPEC.job_input_hashes(),
                        ),
                        source_closure_dependencies=_loader_source_dependencies(),
                    )

        manifest = deepcopy(original)
        manifest["component_manifests"].append(
            deepcopy(manifest["component_manifests"][source_component_index])
        )
        mutated_id = _manifest_id(manifest)
        with self.assertRaisesRegex(
            ExternalObservedDevelopmentJobBindingError, "duplicate external"
        ):
            external_observed_development_job_binding(
                executable_id=mutated_id,
                executable_manifest=manifest,
                job_spec=_job_spec(
                    mutated_id,
                    boundary.US30_OBSERVED_DEVELOPMENT_SPEC.job_input_hashes(),
                ),
                source_closure_dependencies=_loader_source_dependencies(),
            )

    def test_start_and_reuse_revalidate_durable_and_physical_prefix(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, prefix, _, _ = _write_fixture(root, prefix_content=_fixture_bytes()[0])
            with patch.dict(boundary._SPECS, {"TEST": spec}):
                executable = _fixture_executable(spec)
                job = _job_spec(executable.identity, spec.job_input_hashes())
                binding = external_observed_development_job_binding(
                    executable_id=executable.identity,
                    executable_manifest=executable.to_identity_payload(),
                    job_spec=job,
                    source_closure_dependencies=_loader_source_dependencies(),
                )
                self.assertIsNotNone(binding)
                assert binding is not None
                verify_external_observed_development_job_prefixes(
                    repository_root=root, binding=binding
                )
                current = require_current_external_observed_development_job_binding(
                    executable_id=executable.identity,
                    executable_manifest=executable.to_identity_payload(),
                    job_spec=job,
                    source_closure_dependencies=_loader_source_dependencies(),
                    durable_payload=binding.to_payload(),
                    repository_root=root,
                )
                self.assertEqual(current, binding)

                forged = deepcopy(binding.to_payload())
                forged["source_bindings"][0]["development_prefix_sha256"] = "f" * 64
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentJobBindingError, "durable.*differs"
                ):
                    require_current_external_observed_development_job_binding(
                        executable_id=executable.identity,
                        executable_manifest=executable.to_identity_payload(),
                        job_spec=job,
                        source_closure_dependencies=_loader_source_dependencies(),
                        durable_payload=forged,
                        repository_root=root,
                    )

                prefix_path = root / spec.prefix_relative_path
                prefix_path.write_bytes(prefix[:-1] + b"X")
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentJobBindingError,
                    "physically unavailable or invalid",
                ):
                    require_current_external_observed_development_job_binding(
                        executable_id=executable.identity,
                        executable_manifest=executable.to_identity_payload(),
                        job_spec=job,
                        source_closure_dependencies=_loader_source_dependencies(),
                        durable_payload=binding.to_payload(),
                        repository_root=root,
                    )

    def test_start_revalidation_rejects_missing_and_link_swapped_prefix(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, prefix, _, _ = _write_fixture(root, prefix_content=_fixture_bytes()[0])
            with patch.dict(boundary._SPECS, {"TEST": spec}):
                executable = _fixture_executable(spec)
                job = _job_spec(executable.identity, spec.job_input_hashes())
                binding = external_observed_development_job_binding(
                    executable_id=executable.identity,
                    executable_manifest=executable.to_identity_payload(),
                    job_spec=job,
                    source_closure_dependencies=_loader_source_dependencies(),
                )
                assert binding is not None
                prefix_path = root / spec.prefix_relative_path
                prefix_path.unlink()
                with self.assertRaises(ExternalObservedDevelopmentJobBindingError):
                    require_current_external_observed_development_job_binding(
                        executable_id=executable.identity,
                        executable_manifest=executable.to_identity_payload(),
                        job_spec=job,
                        source_closure_dependencies=_loader_source_dependencies(),
                        durable_payload=binding.to_payload(),
                        repository_root=root,
                    )
                outside = root / "outside.csv"
                outside.write_bytes(prefix)
                try:
                    prefix_path.symlink_to(outside)
                except OSError as exc:
                    self.skipTest(f"file symlinks unavailable: {exc}")
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentJobBindingError,
                    "physically unavailable or invalid",
                ):
                    require_current_external_observed_development_job_binding(
                        executable_id=executable.identity,
                        executable_manifest=executable.to_identity_payload(),
                        job_spec=job,
                        source_closure_dependencies=_loader_source_dependencies(),
                        durable_payload=binding.to_payload(),
                        repository_root=root,
                    )


class ExternalSourceSpreadPrefixCausalityTests(unittest.TestCase):
    def test_spread_only_prefix_perturbation_fails_all_four_discoveries(self) -> None:
        count = 240
        time = pd.date_range("2025-01-01", periods=count, freq="5min")
        target_close = 20_000.0 + np.cumsum(
            0.1 + 0.2 * np.sin(np.arange(count, dtype=float) / 11.0)
        )
        source_close = 5_000.0 + np.cumsum(
            0.03 + 0.1 * np.cos(np.arange(count, dtype=float) / 13.0)
        )
        target = pd.DataFrame(
            {
                "time": time,
                "open": target_close - 0.05,
                "high": target_close + 0.2,
                "low": target_close - 0.2,
                "close": target_close,
                "tick_volume": np.full(count, 100),
                "spread": 1 + (np.arange(count) % 3),
            }
        )
        source = pd.DataFrame({"time": time, "close": source_close})
        end = pd.Timestamp(time[179])
        prefix_target = target.loc[target["time"] <= end].reset_index(drop=True)
        prefix_source = source.loc[source["time"] <= end].reset_index(drop=True)
        cases = (
            (
                cross_asset_relative_strength_discovery,
                "relative_strength_12_joint",
            ),
            (
                cross_asset_downside_spillover_discovery,
                "source_downside_expansion",
            ),
            (us30_downside_spillover_discovery, "source_downside_expansion"),
            (us30_sector_rotation_discovery, "relative_strength_12_joint"),
        )
        for module, profile in cases:
            with self.subTest(module=module.__name__):
                full = module._context(target, source)
                prefix = module._context(prefix_target, prefix_source)
                self.assertEqual(
                    module._prefix_mismatch_count(
                        full, prefix, profile=profile, end=end
                    ),
                    0,
                )
                changed_spread = prefix.effective_spread.copy()
                changed_spread[-1] += 0.25
                perturbed = module._EvaluationContext(
                    target_frame=prefix.target_frame,
                    joined_frame=prefix.joined_frame,
                    features=prefix.features,
                    effective_spread=changed_spread,
                )
                self.assertGreater(
                    module._prefix_mismatch_count(
                        full, perturbed, profile=profile, end=end
                    ),
                    0,
                )


class ExternalDevelopmentMaterializerTests(unittest.TestCase):
    def test_copy_stops_at_matching_line_without_requesting_tail(self) -> None:
        prefix, raw = _fixture_bytes()
        spec = _fixture_spec(prefix, raw)

        class GuardedReader(BytesIO):
            def __init__(self, value: bytes) -> None:
                super().__init__(value)
                self.readline_calls = 0

            def readline(self, *args: object, **kwargs: object) -> bytes:
                self.readline_calls += 1
                if self.readline_calls > 4:
                    raise AssertionError("materializer requested a tail line")
                return super().readline(*args, **kwargs)

        source = GuardedReader(raw)
        target = BytesIO()
        MATERIALIZER._copy_exact_prefix(source, target, spec)
        self.assertEqual(source.readline_calls, 4)
        self.assertEqual(target.getvalue(), prefix)
        self.assertNotIn(b"TAIL_SENTINEL", target.getvalue())

    def test_existing_mismatch_and_destination_override_fail_before_raw(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _, _, raw_path = _write_fixture(
                root, prefix_content=b"existing mismatch\n"
            )
            original_open = Path.open

            def guarded_open(path: Path, *args: object, **kwargs: object):
                if path.resolve() == raw_path.resolve():
                    raise AssertionError("failure path opened raw parent")
                return original_open(path, *args, **kwargs)

            with patch.dict(boundary._SPECS, {"TEST": spec}), patch.object(
                Path, "open", new=guarded_open
            ):
                with self.assertRaises(ExternalObservedDevelopmentError):
                    MATERIALIZER.materialize_external_observed_development(
                        root, "TEST"
                    )
                with self.assertRaisesRegex(
                    MATERIALIZER.ExternalDevelopmentMaterializationError,
                    "destination differs",
                ):
                    MATERIALIZER.materialize_external_observed_development(
                        root,
                        "TEST",
                        destination_relative="data/processed/datasets/other.csv",
                    )

    def test_materializer_rejects_negative_real_volume_before_publication(self) -> None:
        prefix, raw = _fixture_bytes()
        invalid_prefix = prefix.replace(
            b"2026.04.30 23:50:00,101,103,100,102,11,1,0\n",
            b"2026.04.30 23:50:00,101,103,100,102,11,1,-1\n",
        )
        invalid_raw = invalid_prefix + raw[len(prefix) :]
        spec = _fixture_spec(invalid_prefix, invalid_raw)
        with TemporaryDirectory() as temporary, patch.dict(
            boundary._SPECS, {"TEST": spec}
        ):
            root = Path(temporary)
            raw_path = root / spec.raw_relative_path
            raw_path.parent.mkdir(parents=True)
            raw_path.write_bytes(invalid_raw)
            with self.assertRaisesRegex(
                ExternalObservedDevelopmentError,
                "volume invariants",
            ):
                MATERIALIZER.materialize_external_observed_development(
                    root, "TEST"
                )
            self.assertFalse((root / spec.prefix_relative_path).exists())

    def test_materializer_opens_raw_parent_unbuffered(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec, _, _, raw_path = _write_fixture(root)
            original_open = Path.open
            raw_buffering: list[object] = []

            def observed_open(path: Path, *args: object, **kwargs: object):
                if path.resolve() == raw_path.resolve():
                    raw_buffering.append(kwargs.get("buffering"))
                return original_open(path, *args, **kwargs)

            with patch.dict(boundary._SPECS, {"TEST": spec}), patch.object(
                Path, "open", new=observed_open
            ):
                report = MATERIALIZER.materialize_external_observed_development(
                    root, "TEST"
                )
            self.assertEqual(report["status"], "materialized")
            self.assertEqual(raw_buffering, [0])


class ImmutableRawPublicationTests(unittest.TestCase):
    def test_publish_is_atomic_idempotent_and_refuses_existing_mismatch(self) -> None:
        prefix, raw = _fixture_bytes()
        spec = _fixture_spec(prefix, raw)
        with patch.dict(boundary._SPECS, {"TEST": spec}):
            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.assertEqual(
                    publish_immutable_raw_snapshot(root, "TEST", raw),
                    "materialized",
                )
                destination = root / spec.raw_relative_path
                self.assertEqual(destination.read_bytes(), raw)
                self.assertEqual(
                    publish_immutable_raw_snapshot(root, "TEST", raw),
                    "existing_exact",
                )

            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                destination = root / spec.raw_relative_path
                destination.parent.mkdir(parents=True)
                original = b"existing immutable mismatch\n"
                destination.write_bytes(original)
                with self.assertRaisesRegex(
                    ExternalObservedDevelopmentError, "identity differs"
                ):
                    publish_immutable_raw_snapshot(root, "TEST", raw)
                self.assertEqual(destination.read_bytes(), original)

    def test_failed_atomic_publication_leaves_no_partial_destination(self) -> None:
        prefix, raw = _fixture_bytes()
        spec = _fixture_spec(prefix, raw)
        with TemporaryDirectory() as temporary, patch.dict(
            boundary._SPECS, {"TEST": spec}
        ), patch.object(boundary.os, "link", side_effect=OSError("blocked")):
            root = Path(temporary)
            with self.assertRaisesRegex(
                ExternalObservedDevelopmentError, "publication failed"
            ):
                publish_immutable_raw_snapshot(root, "TEST", raw)
            destination = root / spec.raw_relative_path
            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.glob(".*.tmp")), [])


class HistoricalSourceVolumeAuditTests(unittest.TestCase):
    def test_negative_tick_and_real_volume_fail_structure_audit(self) -> None:
        content = HEADER + (
            b"2018.05.07 01:00:00,100,102,99,101,10,1,0\n"
            b"2018.05.07 01:05:00,101,103,100,102,-1,1,-2\n"
        )
        cases = (
            us30_source.audit_us30_historical_bytes,
            us500_source.audit_us500_historical_bytes,
            usdjpy_source.audit_usdjpy_historical_bytes,
        )
        for audit in cases:
            with self.subTest(audit=audit.__name__):
                measurement = audit(
                    content, observed_at_utc="2026-07-15T00:00:00Z"
                )
                self.assertTrue(str(measurement["schema"]).endswith(".v3"))
                self.assertEqual(measurement["negative_tick_volume_rows"], 1)
                self.assertEqual(measurement["negative_real_volume_rows"], 1)
                self.assertFalse(measurement["facts"]["gaps_audited"])


if __name__ == "__main__":
    unittest.main()
