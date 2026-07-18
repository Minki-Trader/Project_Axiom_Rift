from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.implementation_closure import (
    HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256,
    HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS,
    ImplementationClosureError,
    require_current_job_source_closure,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _admit_source(
    tmp_path: Path,
    source: str | bytes,
    *,
    relative_path: str = "axiom_rift/research/capability_probe.py",
) -> dict[str, object]:
    source_root = tmp_path / "src"
    path = source_root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    content = source if isinstance(source, bytes) else source.encode("ascii")
    path.write_bytes(content)
    source_hash = sha256(content).hexdigest()
    module = relative_path.removesuffix(".py").replace("/", ".")
    callable_identity = f"{module}.run.v1"
    closure = canonical_bytes(
        {
            "callable_identity": callable_identity,
            "dependencies": [
                {"path": relative_path, "sha256": source_hash}
            ],
            "schema": "job_implementation_source_closure.v1",
        }
    )
    closure_hash = sha256(closure).hexdigest()
    artifacts = {source_hash: content, closure_hash: closure}
    return require_current_job_source_closure(
        callable_identity=callable_identity,
        job_artifact_hashes=tuple(sorted(artifacts)),
        artifact_reader=artifacts.__getitem__,
        source_root=source_root,
    )


def test_source_admission_accepts_only_the_narrow_evidence_facade(
    tmp_path: Path,
) -> None:
    authority = _admit_source(
        tmp_path,
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext

def run():
    context = RunningJobExecutionContext('.')
    return context.evidence.read_verified('0' * 64)
""",
    )
    assert authority["schema"] == "job_implementation_source_authority.v1"


def test_source_admission_accepts_the_validated_multiplicity_scalar(
    tmp_path: Path,
) -> None:
    authority = _admit_source(
        tmp_path,
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext

def run():
    context = RunningJobExecutionContext('.')
    return context.prior_global_multiplicity_floor
""",
    )
    assert authority["schema"] == "job_implementation_source_authority.v1"


@pytest.mark.parametrize(
    "source",
    (
        """from axiom_rift.operations.running_job import RunningJobAuthority
def run():
    authority = RunningJobAuthority('.')
    return authority.open_stable_index()
""",
        """import axiom_rift.operations.running_job as running_job
def run():
    authority = running_job.RunningJobAuthority('.')
    return authority.open_stable_index()
""",
        """from axiom_rift.operations.running_job_context import running_job_execution_context_dependency_paths
def run():
    source = running_job_execution_context_dependency_paths()[0]
    return (source.parents[3] / 'state' / 'control.json').read_bytes()
""",
        """from axiom_rift.operations.running_job_context import running_job_scientific_projection_dependency_paths
def run():
    source = running_job_scientific_projection_dependency_paths()[0]
    return (source.parents[3] / 'state' / 'control.json').read_bytes()
""",
        """from axiom_rift.operations.running_job_context import running_job_operational_identity_boundary_paths
def run():
    source = running_job_operational_identity_boundary_paths()[0]
    return (source.parents[3] / 'state' / 'control.json').read_bytes()
""",
        """from axiom_rift.research.fixed_hold_replay_runtime import fixed_hold_replay_runtime_dependency_paths
def run(adapter):
    source = fixed_hold_replay_runtime_dependency_paths(adapter)[0]
    return source.read_bytes()
""",
        """import builtins
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    raw = builtins.__dict__['object'].__getattribute__
    authority = raw(context, '_RunningJobExecutionContext__authority')
    return authority.foundation_root
""",
        """import builtins
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    raw = builtins.__dict__['object'].__getattribute__
    facade = context.evidence
    return raw(facade, '_RunningJobEvidenceFacade__store')
""",
        """import builtins
def run():
    load = builtins.__dict__['__' + 'import__']
    module = load(
        'axiom_rift.operations.' + 'writer',
        fromlist=['State' + 'Writer'],
    )
    return getattr(module, 'State' + 'Writer')
""",
        """def run():
    load = __import__
    return load('axiom_rift.operations.' + 'writer')
""",
        """def run():
    load = globals()['__' + 'import__']
    return load('axiom_rift.operations.' + 'writer')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    raw = type.__getattribute__(object, '__get' + 'attribute__')
    return raw(context, '_RunningJobExecutionContext__authority')
""",
    ),
)
def test_source_admission_rejects_raw_running_authority_and_builtins_escape(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(ImplementationClosureError, match="prospective Job source"):
        _admit_source(tmp_path, source)


@pytest.mark.parametrize(
    "source",
    (
        """from axiom_rift.storage.evidence import EvidenceStore
def run():
    return EvidenceStore('local/evidence')
""",
        """from axiom_rift.storage.evidence import EvidenceStore as Store
def run():
    return Store('local/evidence')
""",
        """import axiom_rift.storage.evidence as evidence_module
def run():
    return evidence_module.EvidenceStore('local/evidence')
""",
        """from axiom_rift.storage import evidence as evidence_module
def run():
    return evidence_module.EvidenceStore('local/evidence')
""",
        """from axiom_rift.operations.running_job_context import _EvidenceStore
def run():
    return _EvidenceStore('local/evidence')
""",
        """import axiom_rift.operations.running_job_context as context_module
def run():
    return context_module._EvidenceStore('local/evidence')
""",
        """import importlib
def run():
    module = importlib.import_module('axiom_rift.storage.evidence')
    return module.EvidenceStore('local/evidence')
""",
        """def run():
    module = __import__('axiom_rift.storage.evidence', fromlist=['EvidenceStore'])
    return module.EvidenceStore('local/evidence')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return context._authority
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return context.foundation_root
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return context.open_stable_index()
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return (context.index_path, context.root, context.read_control())
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext as Context
def run():
    context = Context('.')
    return getattr(context, 'foundation_root')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext as Context
def run():
    context = Context('.')
    return object.__getattribute__(context, '_authority')
""",
        """from axiom_rift.operations import running_job_context as context_module
def run():
    return context_module.RunningJobExecutionContext('.').foundation_root
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    object.__setattr__(context, 'prior_global_multiplicity_floor', 0)
    return context
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    alias = context
    return alias.foundation_root
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext as Context
def run(context: 'Context'):
    alias = context
    return getattr(alias, 'index_path')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    alias = context
    return object.__getattribute__(alias, '_authority')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    alias = context
    return alias.verify_running_job_execution.__self__
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    bound = context.verify_running_job_execution
    return bound.__self__
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    probe = getattr
    return probe(context, 'foundation_root')
""",
        """from builtins import getattr as probe
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    return probe(context, 'foundation_root')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run(context: RunningJobExecutionContext):
    probe = object.__getattribute__
    return probe(context, '_authority')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
Context = RunningJobExecutionContext
def run():
    context = Context('.')
    return context.foundation_root
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext as RunningJobContext
def run(context: 'RunningJobContext'):
    alias = context
    return alias.index_path
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    return RunningJobExecutionContext.verify_running_job_execution.__globals__
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext as Context
def run(context: Context | None):
    alias = context
    return alias.read_control()
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return context.evidence.verify('0' * 64)
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    capability = context.evidence
    return getattr(capability, '_root')
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    capability = context.evidence
    return object.__getattribute__(
        capability,
        '_RunningJobEvidenceFacade__store',
    )
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    return context.evidence.finalize.__self__
""",
        """from axiom_rift.operations.running_job_context import RunningJobExecutionContext
def run():
    context = RunningJobExecutionContext('.')
    bound = context.evidence.finalize
    return bound.__self__
""",
    ),
)
def test_source_admission_rejects_raw_store_and_reflection_escape(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(ImplementationClosureError, match="prospective Job source"):
        _admit_source(tmp_path, source)


def test_entire_frozen_historical_registry_is_reconstruction_only(
    tmp_path: Path,
) -> None:
    expected = {
        f"axiom_rift/research/{name}": identity
        for name, identity in HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.items()
    }
    assert dict(HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256) == expected
    gap_path = "axiom_rift/research/gap_recovery_diagnostic.py"
    assert gap_path in expected
    with pytest.raises(TypeError):
        HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256[gap_path] = "0" * 64
    for relative_path, identity in sorted(expected.items()):
        content = (REPOSITORY_ROOT / "src" / relative_path).read_bytes()
        assert sha256(content).hexdigest() == identity
        with pytest.raises(
            ImplementationClosureError,
            match="frozen historical source is reconstruction-only",
        ):
            _admit_source(
                tmp_path,
                content,
                relative_path=relative_path,
            )


def test_frozen_historical_path_with_changed_bytes_fails_closed(
    tmp_path: Path,
) -> None:
    relative_path = next(
        iter(sorted(HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256))
    )
    with pytest.raises(
        ImplementationClosureError,
        match="registry identity drifted",
    ):
        _admit_source(
            tmp_path,
            "def run():\n    return None\n",
            relative_path=relative_path,
        )


@pytest.mark.parametrize(
    "source",
    (
        """from axiom_rift.operations.writer import StateWriter
def run():
    return StateWriter('.')
""",
        """import axiom_rift.operations.writer as writer_module
def run():
    return writer_module.StateWriter('.')
""",
        """from axiom_rift.operations import writer as writer_module
def run():
    return writer_module.StateWriter('.')
""",
        """import importlib
def run():
    return importlib.import_module('axiom_rift.operations.writer')
""",
        """def run():
    loader = __import__
    return loader('axiom_rift.operations.writer')
""",
        """from importlib import import_module as loader
def run():
    return loader('axiom_rift.operations.writer')
""",
        """MISSION_ID = 'MIS-0004'
STUDY_ID = 'STU-0044'
def run():
    return MISSION_ID, STUDY_ID
""",
    ),
)
def test_source_admission_rejects_writer_and_embedded_control_authority(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(ImplementationClosureError, match="prospective Job source"):
        _admit_source(tmp_path, source)


@pytest.mark.parametrize(
    "relative_path",
    sorted(HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS),
)
def test_historical_raw_store_surfaces_are_reconstruction_only(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(
        ImplementationClosureError,
        match="reconstruction-only",
    ):
        source = (
            (REPOSITORY_ROOT / "src" / relative_path).read_bytes()
            if relative_path
            in HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256
            else "def run():\n    return None\n"
        )
        _admit_source(
            tmp_path,
            source,
            relative_path=relative_path,
        )


@pytest.mark.parametrize(
    "source",
    (
        """from axiom_rift.operations.writer import StateWriter
class RunningJobExecutionContext:
    pass
def run():
    return StateWriter('.')
""",
        """class RunningJobExecutionContext:
    @property
    def foundation_root(self):
        return '.'
def run():
    return RunningJobExecutionContext().foundation_root
""",
        """class RunningJobExecutionContext:
    __slots__ = ('foundation' + '_root',)
def run():
    return RunningJobExecutionContext()
""",
    ),
)
def test_trusted_running_job_context_owner_fails_closed_on_authority_drift(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(ImplementationClosureError, match="prospective Job"):
        _admit_source(
            tmp_path,
            source,
            relative_path="axiom_rift/operations/running_job_context.py",
        )
