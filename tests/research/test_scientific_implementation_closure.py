from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys

import pytest

import axiom_rift.research.analog_state_replay_v2 as replay_v2_module
from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_identity_bytes
from axiom_rift.operations.validation import (
    EvidenceValidatorRegistry,
    EvidenceValidationError,
    validator_execution_dependency_paths,
    validator_identity,
    validator_implementation_sha256,
)
from axiom_rift.research.analog_fixed_hold_replay import (
    analog_fixed_hold_replay_protocol_definition,
    analog_fixed_hold_replay_producer_implementation_identities,
)
from axiom_rift.research.analog_fixed_hold_replay_job import RUNTIME_ADAPTER
from axiom_rift.research import analog_state_scoped_job as scoped_job
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.research.analog_state_replay_v2 import (
    analog_family_executable_scoped_v2,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_job_implementation_artifact,
    fixed_hold_replay_job_implementation_sha256,
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.implementation_closure import (
    COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA,
    ImplementationClosureError,
    require_current_job_source_closure,
    require_job_implementation_closure,
)
from axiom_rift.research.validation import (
    SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
    SCIENTIFIC_VALIDATION_DEPENDENCIES,
    SCIENTIFIC_VALIDATION_DOMAINS,
    SCIENTIFIC_VALIDATION_PROTOCOL,
    ScientificDiscoveryValidator,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
    SCIENTIFIC_VALIDATION_V2_DOMAINS,
    SCIENTIFIC_VALIDATION_V2_PROTOCOL,
    ScientificAdjudicationValidatorV2,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
FIXED_HOLD_CONTEXT = 622
WRITER_BOUND_STU0061_FAMILY = historical_family_from_manifest(
    STU0061_HISTORICAL_FAMILY.manifest()
)
FIXED_HOLD_REPLAY_CONTEXT = HistoricalFamilyReplayContext(
    family_authority_id="historical-family-authority:" + "1" * 64,
    replay_obligation_id="historical-replay-obligation:" + "2" * 64,
    family=WRITER_BOUND_STU0061_FAMILY,
    prior_global_exposure_count=FIXED_HOLD_CONTEXT,
    original_family_end_global_exposure_count=492,
)


@pytest.mark.parametrize(
    (
        "validator_type",
        "declared_dependencies",
        "expected_id",
        "protocol",
        "domains",
    ),
    (
        (
            ScientificDiscoveryValidator,
            SCIENTIFIC_VALIDATION_DEPENDENCIES,
            SCIENTIFIC_DISCOVERY_VALIDATOR_ID,
            SCIENTIFIC_VALIDATION_PROTOCOL,
            SCIENTIFIC_VALIDATION_DOMAINS,
        ),
        (
            ScientificAdjudicationValidatorV2,
            SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            SCIENTIFIC_VALIDATION_V2_PROTOCOL,
            SCIENTIFIC_VALIDATION_V2_DOMAINS,
        ),
    ),
)
def test_scientific_validator_separates_semantic_identity_from_execution_closure(
    validator_type: type,
    declared_dependencies: tuple[Path, ...],
    expected_id: str,
    protocol: str,
    domains: frozenset[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = validator_type()
    execution_dependencies = set(
        validator_execution_dependency_paths(
            validator.implementation_path,
            declared_dependencies,
        )
    )
    operational_target = (
        SOURCE_ROOT / "axiom_rift/operations/validation.py"
    ).resolve()
    assert operational_target in execution_dependencies
    assert operational_target not in set(declared_dependencies)
    assert validator.dependency_paths == declared_dependencies
    registry = EvidenceValidatorRegistry((validator,))

    original_read_bytes = Path.read_bytes

    def perturbed_read_bytes(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.resolve() == operational_target:
            return content + b"\n# operational execution perturbation"
        return content

    monkeypatch.setattr(Path, "read_bytes", perturbed_read_bytes)
    changed_id = validator_identity(
        protocol=protocol,
        domains=domains,
        implementation_sha256=validator_implementation_sha256(
            implementation_path=validator.implementation_path,
            dependency_paths=declared_dependencies,
        ),
    )
    assert changed_id == expected_id
    with pytest.raises(
        EvidenceValidationError,
        match="registration changed after registration",
    ):
        registry.require_registered(
            validator_id=validator.validator_id,
            domain="scientific",
        )


def _current_runtime_source_artifacts() -> tuple[dict[str, bytes], list[str]]:
    artifacts: dict[str, bytes] = {}
    for path in fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER):
        content = path.read_bytes()
        artifacts[sha256(content).hexdigest()] = content
    closure = fixed_hold_replay_job_implementation_artifact(RUNTIME_ADAPTER)
    artifacts[sha256(closure).hexdigest()] = closure
    return artifacts, sorted(artifacts)


def _source_closure_identity(artifacts: dict[str, bytes]) -> str:
    for identity, content in artifacts.items():
        try:
            payload = parse_canonical(content)
        except ValueError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("schema") == "job_implementation_source_closure.v1"
        ):
            return identity
    raise AssertionError("typed source closure is absent")


def test_current_job_source_closure_binds_real_paths_bytes_and_callable() -> None:
    artifacts, identities = _current_runtime_source_artifacts()
    authority = require_current_job_source_closure(
        callable_identity=RUNTIME_ADAPTER.callable_identity,
        job_artifact_hashes=identities,
        artifact_reader=artifacts.__getitem__,
        source_root=SOURCE_ROOT,
    )
    assert authority["schema"] == "job_implementation_source_authority.v1"
    assert authority["callable_module_path"] == (
        "axiom_rift/research/analog_fixed_hold_replay_job.py"
    )
    assert authority["dependency_count"] == len(
        fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER)
    )


def test_current_job_source_closure_rejects_path_swap_and_orphan_hash() -> None:
    artifacts, identities = _current_runtime_source_artifacts()
    closure_identity = _source_closure_identity(artifacts)
    closure = parse_canonical(artifacts[closure_identity])
    assert isinstance(closure, dict)
    dependencies = [dict(item) for item in closure["dependencies"]]
    left = next(
        ordinal
        for ordinal, item in enumerate(dependencies)
        if item["sha256"] != dependencies[0]["sha256"]
    )
    dependencies[0]["sha256"], dependencies[left]["sha256"] = (
        dependencies[left]["sha256"],
        dependencies[0]["sha256"],
    )
    swapped_closure = canonical_bytes(
        {**closure, "dependencies": dependencies}
    )
    swapped_hash = sha256(swapped_closure).hexdigest()
    swapped_artifacts = {
        identity: content
        for identity, content in artifacts.items()
        if identity != closure_identity
    }
    swapped_artifacts[swapped_hash] = swapped_closure
    with pytest.raises(
        ImplementationClosureError,
        match="current project source bytes",
    ):
        require_current_job_source_closure(
            callable_identity=RUNTIME_ADAPTER.callable_identity,
            job_artifact_hashes=sorted(swapped_artifacts),
            artifact_reader=swapped_artifacts.__getitem__,
            source_root=SOURCE_ROOT,
        )

    orphan = b"orphan implementation artifact"
    orphan_hash = sha256(orphan).hexdigest()
    orphan_artifacts = {**artifacts, orphan_hash: orphan}
    with pytest.raises(
        ImplementationClosureError,
        match="exact implementation artifact set",
    ):
        require_current_job_source_closure(
            callable_identity=RUNTIME_ADAPTER.callable_identity,
            job_artifact_hashes=sorted(orphan_artifacts),
            artifact_reader=orphan_artifacts.__getitem__,
            source_root=SOURCE_ROOT,
        )


def test_current_job_source_closure_rejects_relabelled_callable_module() -> None:
    artifacts, identities = _current_runtime_source_artifacts()
    closure_identity = _source_closure_identity(artifacts)
    closure = parse_canonical(artifacts[closure_identity])
    assert isinstance(closure, dict)
    callable_identity = "axiom_rift.research.absent.execute_absent.v1"
    relabelled = canonical_bytes(
        {**closure, "callable_identity": callable_identity}
    )
    relabelled_hash = sha256(relabelled).hexdigest()
    relabelled_artifacts = {
        identity: content
        for identity, content in artifacts.items()
        if identity != closure_identity
    }
    relabelled_artifacts[relabelled_hash] = relabelled
    with pytest.raises(
        ImplementationClosureError,
        match="callable module path",
    ):
        require_current_job_source_closure(
            callable_identity=callable_identity,
            job_artifact_hashes=sorted(relabelled_artifacts),
            artifact_reader=relabelled_artifacts.__getitem__,
            source_root=SOURCE_ROOT,
        )


def test_current_job_source_closure_rejects_link_traversal(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    real_package = tmp_path / "real_axiom_rift"
    real_package.mkdir()
    source = b"def execute():\n    return 1\n"
    (real_package / "demo.py").write_bytes(source)
    try:
        os.symlink(
            real_package,
            source_root / "axiom_rift",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("directory symlinks are unavailable in this environment")
    source_hash = sha256(source).hexdigest()
    closure = canonical_bytes(
        {
            "callable_identity": "axiom_rift.demo.execute.v1",
            "dependencies": [
                {"path": "axiom_rift/demo.py", "sha256": source_hash}
            ],
            "schema": "job_implementation_source_closure.v1",
        }
    )
    closure_hash = sha256(closure).hexdigest()
    artifacts = {source_hash: source, closure_hash: closure}
    with pytest.raises(
        ImplementationClosureError,
        match="links or junctions",
    ):
        require_current_job_source_closure(
            callable_identity="axiom_rift.demo.execute.v1",
            job_artifact_hashes=sorted(artifacts),
            artifact_reader=artifacts.__getitem__,
            source_root=source_root,
        )


def test_nested_component_closure_partitions_exactly_from_current_source(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    callable_path = source_root / "axiom_rift" / "demo.py"
    callable_path.parent.mkdir(parents=True)
    source = b"def execute_demo():\n    return 1\n"
    callable_path.write_bytes(source)
    source_hash = sha256(source).hexdigest()
    callable_identity = "axiom_rift.demo.execute_demo.v1"
    source_closure = canonical_bytes(
        {
            "callable_identity": callable_identity,
            "dependencies": [
                {"path": "axiom_rift/demo.py", "sha256": source_hash}
            ],
            "schema": "job_implementation_source_closure.v1",
        }
    )
    source_closure_hash = sha256(source_closure).hexdigest()

    leaf = b"nested exact Component source"
    leaf_hash = sha256(leaf).hexdigest()
    inner = canonical_identity_bytes(
        domain="scientific-closure-inner-bundle",
        payload={
            "dependency_artifact_hashes": [leaf_hash],
            "implementation_bundle_schema": (
                COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
            ),
        },
    )
    inner_hash = sha256(inner).hexdigest()
    outer = canonical_identity_bytes(
        domain="scientific-closure-outer-bundle",
        payload={
            "dependency_artifact_hashes": [inner_hash],
            "implementation_bundle_schema": (
                COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
            ),
        },
    )
    outer_hash = sha256(outer).hexdigest()
    artifacts = {
        source_hash: source,
        source_closure_hash: source_closure,
        leaf_hash: leaf,
        inner_hash: inner,
        outer_hash: outer,
    }
    executable_manifest = {
        "schema": "executable_spec.v1",
        "component_identities": [f"component:{'1' * 64}"],
        "component_manifests": [
            {
                "implementation": (
                    "axiom_rift.research.fixture.nested"
                    f"@sha256:{outer_hash}"
                )
            }
        ],
    }
    component_hashes = require_job_implementation_closure(
        executable_manifest=executable_manifest,
        job_artifact_hashes=tuple(sorted(artifacts)),
        artifact_reader=artifacts.__getitem__,
    )
    assert component_hashes == tuple(
        sorted((outer_hash, inner_hash, leaf_hash))
    )
    authority = require_current_job_source_closure(
        callable_identity=callable_identity,
        job_artifact_hashes=tuple(sorted(artifacts)),
        artifact_reader=artifacts.__getitem__,
        source_root=source_root,
        verified_non_source_artifact_hashes=component_hashes,
    )
    assert authority["dependency_count"] == 1


def test_historical_analog_scoped_job_is_reconstruction_only() -> None:
    manifest = parse_canonical(
        scoped_job.analog_scoped_job_implementation_artifact()
    )
    assert isinstance(manifest, dict)
    artifacts: dict[str, bytes] = {}
    for path in scoped_job.analog_scoped_job_dependency_paths():
        content = path.read_bytes()
        artifacts[sha256(content).hexdigest()] = content
    source_closure = scoped_job.analog_scoped_job_source_closure_artifact()
    artifacts[sha256(source_closure).hexdigest()] = source_closure
    assert set(artifacts) == set(manifest["artifact_hashes"])

    executable = analog_family_executable_scoped_v2(
        P1_STU0061_ANALOG_FAMILY.configurations()[0]
    )
    component_hashes = require_job_implementation_closure(
        executable_manifest=executable.to_identity_payload(),
        job_artifact_hashes=manifest["artifact_hashes"],
        artifact_reader=artifacts.__getitem__,
    )
    assert component_hashes
    with pytest.raises(
        ImplementationClosureError,
        match="reconstruction-only",
    ):
        require_current_job_source_closure(
            callable_identity=scoped_job.CALLABLE_IDENTITY,
            job_artifact_hashes=manifest["artifact_hashes"],
            artifact_reader=artifacts.__getitem__,
            source_root=SOURCE_ROOT,
            verified_non_source_artifact_hashes=component_hashes,
        )


def _subprocess_json(source: str) -> object:
    environment = dict(os.environ)
    prior = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(SOURCE_ROOT)
        if not prior
        else os.pathsep.join((str(SOURCE_ROOT), prior))
    )
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_validation_v2_import_does_not_eager_load_numerical_protocols() -> None:
    observed = _subprocess_json(
        """
import json
import sys
import axiom_rift.research.validation_v2
forbidden = (
    "numpy",
    "pandas",
    "scipy",
    "axiom_rift.research.analog_state_family",
    "axiom_rift.research.analog_state_fit_v2",
    "axiom_rift.research.analog_state_trace",
    "axiom_rift.research.discovery",
    "axiom_rift.research.selection_inference",
)
print(json.dumps({name: name in sys.modules for name in forbidden}))
"""
    )
    assert isinstance(observed, dict)
    assert not any(observed.values())


def test_research_package_preserves_public_lazy_imports() -> None:
    observed = _subprocess_json(
        """
import json
import sys
import axiom_rift.research as research
before = sorted(name for name in sys.modules if name.startswith("axiom_rift.research."))
resolved = {name: getattr(research, name) is not None for name in research.__all__}
from axiom_rift.research import analog_state_fit_v2
print(json.dumps({
    "before": before,
    "public_count": len(research.__all__),
    "public_unique": len(set(research.__all__)),
    "resolved": sorted(resolved),
    "submodule": analog_state_fit_v2.__name__,
}))
"""
    )
    assert observed["before"] == []
    assert observed["public_count"] == observed["public_unique"]
    assert observed["public_count"] == len(observed["resolved"])
    assert observed["submodule"] == "axiom_rift.research.analog_state_fit_v2"


def test_fixed_hold_job_declares_executed_modules_without_foreign_validator_code() -> None:
    observed = _subprocess_json(
        """
import json
import sys
from pathlib import Path
import axiom_rift.research.analog_fixed_hold_replay_job as job
from axiom_rift.research.fixed_hold_replay_runtime import fixed_hold_replay_runtime_dependency_paths
source_root = Path("src").resolve()
loaded = set()
for module in tuple(sys.modules.values()):
    path = getattr(module, "__file__", None)
    if not path:
        continue
    try:
        resolved = Path(path).resolve()
        resolved.relative_to(source_root)
    except (OSError, ValueError):
        continue
    loaded.add(resolved)
declared = set(fixed_hold_replay_runtime_dependency_paths(job.RUNTIME_ADAPTER))
incidental_imports = {
    source_root / "axiom_rift/research/audit_integrity_proof.py",
}
foreign_validator_only = {
    source_root / "axiom_rift/research/historical_family_stu0017.py",
    source_root / "axiom_rift/research/historical_family_stu0032.py",
}
p0_only = {
    source_root / "axiom_rift/research/p0_replay_inventory.py",
    source_root / "axiom_rift/research/p0_selection_inference.py",
}
print(json.dumps({
    "foreign_declared": sorted(path.relative_to(source_root).as_posix() for path in declared & foreign_validator_only),
    "missing": sorted(path.relative_to(source_root).as_posix() for path in loaded - declared - incidental_imports),
    "p0_declared": sorted(path.relative_to(source_root).as_posix() for path in declared & p0_only),
    "p0_loaded": sorted(path.relative_to(source_root).as_posix() for path in loaded & p0_only),
    "writer_loaded": "axiom_rift.operations.writer" in sys.modules,
}))
"""
    )
    assert observed == {
        "foreign_declared": [],
        "missing": [],
        "p0_declared": [],
        "p0_loaded": [],
        "writer_loaded": False,
    }


@pytest.mark.parametrize(
    "field",
    ("python", "numpy", "pandas", "scipy"),
)
def test_numerical_environment_remains_typed_and_definition_identity_bound(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = replay_v2_module.analog_replay_numerical_environment_manifest()
    assert manifest == {
        "numpy": replay_v2_module.np.__version__,
        "pandas": replay_v2_module.pd.__version__,
        "python": ".".join(
            str(value) for value in replay_v2_module.sys.version_info[:3]
        ),
        "schema": "analog_replay_numerical_environment.v1",
        "scipy": replay_v2_module.scipy.__version__,
    }
    baseline_environment_identity = (
        replay_v2_module.analog_replay_numerical_environment_identity()
    )
    baseline_definition = analog_fixed_hold_replay_protocol_definition(
        FIXED_HOLD_REPLAY_CONTEXT
    )
    assert analog_fixed_hold_replay_producer_implementation_identities()[
        "numerical_environment_sha256"
    ] == baseline_environment_identity

    if field == "python":
        monkeypatch.setattr(
            replay_v2_module.sys,
            "version_info",
            (99, 98, 97),
        )
    else:
        module = getattr(
            replay_v2_module,
            {"numpy": "np", "pandas": "pd", "scipy": "scipy"}[field],
        )
        monkeypatch.setattr(
            module,
            "__version__",
            str(getattr(module, "__version__")) + "+closure-test",
        )

    changed_manifest = (
        replay_v2_module.analog_replay_numerical_environment_manifest()
    )
    changed_definition = analog_fixed_hold_replay_protocol_definition(
        FIXED_HOLD_REPLAY_CONTEXT
    )
    assert changed_manifest[field] != manifest[field]
    assert (
        replay_v2_module.analog_replay_numerical_environment_identity()
        != baseline_environment_identity
    )
    assert changed_definition.identity != baseline_definition.identity
    assert (
        changed_definition.prospective_executable_ids
        != baseline_definition.prospective_executable_ids
    )


@pytest.mark.parametrize(
    ("relative_path", "semantic_identity_changes"),
    (
        ("axiom_rift/research/analog_fixed_hold_replay.py", False),
        ("axiom_rift/research/analog_state_replay_v2.py", True),
        ("axiom_rift/research/adjudication.py", True),
        ("axiom_rift/research/completed_period_atomic_trace.py", True),
        ("axiom_rift/research/fixed_hold_historical_projection.py", True),
        ("axiom_rift/research/historical_semantic_transition.py", True),
        ("axiom_rift/operations/validation.py", False),
        ("axiom_rift/storage/atomic_file.py", False),
        ("axiom_rift/research/__init__.py", False),
    ),
)
def test_validator_semantics_and_job_execution_bind_their_own_closures(
    relative_path: str,
    semantic_identity_changes: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = (SOURCE_ROOT / relative_path).resolve()
    validation_dependencies = set(SCIENTIFIC_VALIDATION_V2_DEPENDENCIES)
    job_dependencies = set(
        fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER)
    )
    assert (target in validation_dependencies) is semantic_identity_changes
    assert target in job_dependencies

    baseline_job_identity = fixed_hold_replay_job_implementation_sha256(
        RUNTIME_ADAPTER
    )
    original_read_bytes = Path.read_bytes

    def perturbed_read_bytes(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.resolve() == target:
            return content + b"\n# adversarial closure perturbation"
        return content

    monkeypatch.setattr(Path, "read_bytes", perturbed_read_bytes)
    validator = ScientificAdjudicationValidatorV2()
    changed_validator_id = validator_identity(
        protocol=SCIENTIFIC_VALIDATION_V2_PROTOCOL,
        domains=SCIENTIFIC_VALIDATION_V2_DOMAINS,
        implementation_sha256=validator_implementation_sha256(
            implementation_path=validator.implementation_path,
            dependency_paths=SCIENTIFIC_VALIDATION_V2_DEPENDENCIES,
        ),
    )
    changed_job_identity = fixed_hold_replay_job_implementation_sha256(
        RUNTIME_ADAPTER
    )
    assert (
        changed_validator_id != SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
    ) is semantic_identity_changes
    assert changed_job_identity != baseline_job_identity
