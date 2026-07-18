"""Prospective Component-to-Job implementation evidence closure."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.core.identity import (
    CANONICAL_IDENTITY_PREFIX,
    canonical_digest,
    parse_canonical_identity_bytes,
)
from axiom_rift.research.historical_study_registry import (
    HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256,
)


_IMPLEMENTATION_REFERENCE = re.compile(
    r"^[A-Za-z0-9_./:-]+@sha256:([0-9a-f]{64})$"
)
COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA = "component_implementation_bundle.v1"
JOB_IMPLEMENTATION_SOURCE_CLOSURE_SCHEMA = (
    "job_implementation_source_closure.v1"
)
JOB_IMPLEMENTATION_SOURCE_AUTHORITY_SCHEMA = (
    "job_implementation_source_authority.v1"
)
HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS = frozenset(
    {
        "axiom_rift/research/distribution_asymmetry_replay_parity.py",
        "axiom_rift/research/drawdown_state_replay.py",
        "axiom_rift/research/historical_spread_time_invalidation_builder.py",
        "axiom_rift/research/routed_sleeve_replay_parity.py",
        "axiom_rift/research/volatility_duration_replay.py",
        "axiom_rift/research/volatility_duration_replay_parity.py",
    }
)
HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256 = MappingProxyType(
    {
        f"axiom_rift/research/{name}": identity
        for name, identity in sorted(
            HISTORICAL_HARDCODED_CONTROL_MODULE_SHA256.items()
        )
    }
)
_BUNDLE_SCHEMA_FIELD = "implementation_bundle_schema"
_BUNDLE_DEPENDENCIES_FIELD = "dependency_artifact_hashes"
_EVIDENCE_MODULE = "axiom_rift.storage.evidence"
_WRITER_MODULE = "axiom_rift.operations.writer"
_RUNNING_JOB_MODULE = "axiom_rift.operations.running_job"
_RUNNING_JOB_CONTEXT_MODULE = (
    "axiom_rift.operations.running_job_context"
)
_RUNNING_JOB_CONTEXT_PUBLIC_ATTRIBUTES = frozenset(
    {
        "evidence",
        "prior_global_multiplicity_floor",
        "project_bound_fixed_hold_family_exposure",
        "project_bound_fixed_hold_replay_context",
        "project_bound_source_state",
        "verify_reproducible_cache_producer",
        "verify_running_job_execution",
    }
)
_RUNNING_JOB_CONTEXT_METHOD_ATTRIBUTES = frozenset(
    {
        "project_bound_fixed_hold_family_exposure",
        "project_bound_fixed_hold_replay_context",
        "project_bound_source_state",
        "verify_reproducible_cache_producer",
        "verify_running_job_execution",
    }
)
_RUNNING_JOB_EVIDENCE_PUBLIC_ATTRIBUTES = frozenset(
    {"finalize", "read_verified"}
)
_RUNNING_JOB_CONTEXT_TYPE_EXPORTS = frozenset(
    {"RunningJobContext", "RunningJobExecutionContext"}
)
_RUNNING_JOB_CONTEXT_PATH_EXPORTS = frozenset(
    {
        "running_job_execution_context_dependency_paths",
        "running_job_operational_identity_boundary_paths",
        "running_job_scientific_projection_dependency_paths",
    }
)
_RUNNING_JOB_CONTEXT_PATH_BUILDERS = MappingProxyType(
    {
        "axiom_rift/research/cost_aware_execution_pair_runtime.py": frozenset(
            {"cost_aware_execution_pair_runtime_dependency_paths"}
        ),
        "axiom_rift/research/analog_state_scoped_job.py": frozenset(
            {"analog_scoped_job_dependency_paths"}
        ),
        "axiom_rift/research/fixed_hold_replay_runtime.py": frozenset(
            {"fixed_hold_replay_runtime_dependency_paths"}
        ),
    }
)
_RUNNING_JOB_CONTEXT_PATH_FORWARDERS = MappingProxyType(
    {
        "axiom_rift.research.cost_aware_execution_pair_runtime": frozenset(
            {"cost_aware_execution_pair_runtime_dependency_paths"}
        ),
        "axiom_rift.research.analog_state_scoped_job": frozenset(
            {"analog_scoped_job_dependency_paths"}
        ),
        "axiom_rift.research.fixed_hold_replay_runtime": frozenset(
            {"fixed_hold_replay_runtime_dependency_paths"}
        ),
    }
)
_RUNNING_JOB_CONTEXT_OWNER_PATH = (
    "axiom_rift/operations/running_job_context.py"
)
_EVIDENCE_CAPABILITY_OWNER_PATH = "axiom_rift/storage/evidence.py"
_RUNNING_JOB_CONTEXT_OWNER_ALLOWED_MEMBERS = frozenset(
    {
        "evidence",
        "prior_global_multiplicity_floor",
        "project_bound_fixed_hold_family_exposure",
        "project_bound_fixed_hold_replay_context",
        "project_bound_source_state",
        "verify_reproducible_cache_producer",
        "verify_running_job_execution",
    }
)
_RUNNING_JOB_CONTEXT_OWNER_FORBIDDEN_SURFACE = frozenset(
    {
        "StateWriter",
        "foundation_root",
        "index_path",
        "open_stable_index",
        "read_control",
        "root",
        "state_writer",
        "writer",
    }
)
_CAPABILITY_INTROSPECTION_ATTRIBUTES = frozenset(
    {
        "__closure__",
        "__code__",
        "__dict__",
        "__func__",
        "__globals__",
        "__self__",
    }
)
_SENSITIVE_REFLECTION_NAMES = frozenset(
    {
        "EvidenceStore",
        "_EvidenceStore",
        "_RunningJobExecutionContext__authority",
        "_RunningJobExecutionContext__bound_job",
        "_RunningJobExecutionContext__evidence",
        "_RunningJobExecutionContext__prior_global_multiplicity_floor",
        "_RunningJobEvidenceFacade__store",
        "_authority",
        "_root",
        "_target",
        "__closure__",
        "__code__",
        "__dict__",
        "__func__",
        "__getattribute__",
        "__globals__",
        "__import__",
        "__self__",
        "__setattr__",
        "evidence",
        "verified_path",
        "verify",
        "verify_manifest",
    }
)
_HISTORICAL_CONTROL_ID = re.compile(r"^(?:MIS|STU)-[0-9]{4}$")


class ImplementationClosureError(ValueError):
    """Raised when prospective code identity is not closed by durable bytes."""

    def __init__(
        self,
        message: str,
        *,
        same_identity_repairable: bool = False,
    ) -> None:
        super().__init__(message)
        self.same_identity_repairable = same_identity_repairable


def semantic_dependency_closure(
    *,
    roots: tuple[Path, ...],
    dependency_graph: Mapping[Path, tuple[Path, ...]],
    source_root: Path,
) -> tuple[Path, ...]:
    """Return one deterministic, explicit project-source dependency closure.

    The graph is deliberately authored from executed semantic calls rather
    than inferred from every Python import.  Package initializers,
    ``TYPE_CHECKING`` imports, and unused compatibility imports therefore do
    not make unrelated edits reidentify a Component.  Every reachable node is
    still explicit, regular, local Python source and cycles fail closed.
    """

    if type(roots) is not tuple or not roots:
        raise ImplementationClosureError(
            "semantic dependency roots must be a non-empty tuple"
        )
    if not isinstance(dependency_graph, Mapping) or not dependency_graph:
        raise ImplementationClosureError(
            "semantic dependency graph must be a non-empty mapping"
        )
    if not isinstance(source_root, Path):
        raise ImplementationClosureError("semantic source root must be a Path")
    try:
        normalized_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ImplementationClosureError(
            "semantic source root is unavailable"
        ) from exc
    if not normalized_root.is_dir():
        raise ImplementationClosureError(
            "semantic source root must be a directory"
        )

    def normalize(value: object) -> Path:
        if not isinstance(value, Path):
            raise ImplementationClosureError(
                "semantic dependency nodes must be Paths"
            )
        if value.is_symlink():
            raise ImplementationClosureError(
                "semantic dependency source must not be a symlink"
            )
        try:
            resolved = value.resolve(strict=True)
        except OSError as exc:
            raise ImplementationClosureError(
                "semantic dependency source is unavailable"
            ) from exc
        if not resolved.is_file() or resolved.suffix != ".py":
            raise ImplementationClosureError(
                "semantic dependency source must be a regular Python file"
            )
        try:
            resolved.relative_to(normalized_root)
        except ValueError as exc:
            raise ImplementationClosureError(
                "semantic dependency source escapes the project source root"
            ) from exc
        return resolved

    normalized_graph: dict[Path, tuple[Path, ...]] = {}
    for raw_node, raw_dependencies in dependency_graph.items():
        node = normalize(raw_node)
        if node in normalized_graph:
            raise ImplementationClosureError(
                "semantic dependency graph contains duplicate source nodes"
            )
        if type(raw_dependencies) is not tuple:
            raise ImplementationClosureError(
                "semantic dependency edges must be tuples"
            )
        dependencies = tuple(normalize(value) for value in raw_dependencies)
        if len(set(dependencies)) != len(dependencies):
            raise ImplementationClosureError(
                "semantic dependency edges contain duplicates"
            )
        normalized_graph[node] = tuple(
            sorted(
                dependencies,
                key=lambda path: path.relative_to(
                    normalized_root
                ).as_posix(),
            )
        )

    normalized_roots = tuple(normalize(value) for value in roots)
    if len(set(normalized_roots)) != len(normalized_roots):
        raise ImplementationClosureError(
            "semantic dependency roots contain duplicates"
        )
    declared_nodes = set(normalized_graph)
    referenced_nodes = set(normalized_roots) | {
        dependency
        for dependencies in normalized_graph.values()
        for dependency in dependencies
    }
    missing_nodes = referenced_nodes.difference(declared_nodes)
    if missing_nodes:
        raise ImplementationClosureError(
            "semantic dependency graph omits explicit source nodes: "
            + ",".join(
                path.relative_to(normalized_root).as_posix()
                for path in sorted(
                    missing_nodes,
                    key=lambda item: item.relative_to(
                        normalized_root
                    ).as_posix(),
                )
            )
        )

    ordered: list[Path] = []
    visiting: set[Path] = set()
    visited: set[Path] = set()

    def visit(node: Path) -> None:
        if node in visiting:
            raise ImplementationClosureError(
                "semantic dependency graph contains a cycle"
            )
        if node in visited:
            return
        visiting.add(node)
        ordered.append(node)
        for dependency in normalized_graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for root in sorted(
        normalized_roots,
        key=lambda path: path.relative_to(normalized_root).as_posix(),
    ):
        visit(root)
    unreachable = declared_nodes.difference(visited)
    if unreachable:
        raise ImplementationClosureError(
            "semantic dependency graph contains unreachable source nodes: "
            + ",".join(
                path.relative_to(normalized_root).as_posix()
                for path in sorted(
                    unreachable,
                    key=lambda item: item.relative_to(
                        normalized_root
                    ).as_posix(),
                )
            )
        )
    return tuple(ordered)


def component_implementation_sha256(reference: object) -> str:
    """Return the direct artifact digest from one typed Component reference."""

    if type(reference) is not str or not reference.isascii():
        raise ImplementationClosureError(
            "component implementation reference must be ASCII text"
        )
    matched = _IMPLEMENTATION_REFERENCE.fullmatch(reference)
    if matched is None:
        raise ImplementationClosureError(
            "component implementation reference must end in @sha256:<digest>"
        )
    return matched.group(1)


def executable_implementation_hashes(
    executable_manifest: Mapping[str, Any],
) -> tuple[str, ...]:
    """Resolve the direct implementation artifacts declared by an Executable."""

    manifests = executable_manifest.get("component_manifests")
    identities = executable_manifest.get("component_identities")
    if (
        executable_manifest.get("schema") != "executable_spec.v1"
        or not isinstance(manifests, list)
        or not manifests
        or not isinstance(identities, list)
        or len(identities) != len(manifests)
    ):
        raise ImplementationClosureError("Executable component closure is malformed")
    hashes: set[str] = set()
    for manifest in manifests:
        if not isinstance(manifest, Mapping):
            raise ImplementationClosureError("Component manifest is malformed")
        hashes.add(component_implementation_sha256(manifest.get("implementation")))
    return tuple(sorted(hashes))


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bundle_dependencies(content: bytes) -> tuple[str, ...] | None:
    if not content.startswith(CANONICAL_IDENTITY_PREFIX):
        return None
    try:
        _, payload = parse_canonical_identity_bytes(content)
    except (TypeError, ValueError) as exc:
        raise ImplementationClosureError(
            "Component implementation identity frame is invalid"
        ) from exc
    if not isinstance(payload, Mapping):
        return None
    has_schema = _BUNDLE_SCHEMA_FIELD in payload
    has_dependencies = _BUNDLE_DEPENDENCIES_FIELD in payload
    if not has_schema and not has_dependencies:
        return None
    dependencies = payload.get(_BUNDLE_DEPENDENCIES_FIELD)
    if (
        not has_schema
        or not has_dependencies
        or payload.get(_BUNDLE_SCHEMA_FIELD)
        != COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA
        or not isinstance(dependencies, list)
        or not dependencies
        or any(not _is_digest(value) for value in dependencies)
        or dependencies != sorted(set(dependencies))
    ):
        raise ImplementationClosureError(
            "Component implementation bundle payload is invalid"
        )
    return tuple(dependencies)


def require_job_implementation_closure(
    *,
    executable_manifest: Mapping[str, Any],
    job_artifact_hashes: Sequence[str],
    artifact_reader: Callable[[str], bytes],
) -> tuple[str, ...]:
    """Verify and return the complete Component implementation closure.

    The return value is the sorted set of direct Component roots plus every
    recursively reached typed-bundle dependency.  Returning only the direct
    roots would make a later exact source/non-source partition misclassify
    valid nested bundle artifacts as unexplained Job evidence.
    """

    artifacts = tuple(job_artifact_hashes)
    if (
        not artifacts
        or any(not _is_digest(value) for value in artifacts)
        or len(set(artifacts)) != len(artifacts)
    ):
        raise ImplementationClosureError("Job implementation artifacts are malformed")
    if not callable(artifact_reader):
        raise ImplementationClosureError("artifact_reader must be callable")
    required = executable_implementation_hashes(executable_manifest)
    artifact_set = set(artifacts)
    missing = tuple(sorted(set(required).difference(artifact_set)))
    if missing:
        raise ImplementationClosureError(
            "Job implementation evidence omits Component source bytes: "
            + ",".join(missing)
        )

    verified: set[str] = set()
    active: set[str] = set()

    def verify_artifact(identity: str) -> None:
        if identity in active:
            raise ImplementationClosureError(
                "Component implementation bundle dependency cycle is invalid"
            )
        if identity in verified:
            return
        try:
            content = artifact_reader(identity)
        except Exception as exc:
            raise ImplementationClosureError(
                f"Component implementation artifact is unavailable: {identity}"
            ) from exc
        if type(content) is not bytes:
            raise ImplementationClosureError(
                "Component implementation artifact reader must return bytes"
            )
        if sha256(content).hexdigest() != identity:
            raise ImplementationClosureError(
                f"Component implementation artifact hash mismatch: {identity}"
            )
        active.add(identity)
        try:
            dependencies = _bundle_dependencies(content)
            if dependencies is not None:
                missing_dependencies = tuple(
                    sorted(set(dependencies).difference(artifact_set))
                )
                if missing_dependencies:
                    raise ImplementationClosureError(
                        "Job implementation evidence omits Component bundle "
                        "dependencies: " + ",".join(missing_dependencies)
                    )
                for dependency in dependencies:
                    verify_artifact(dependency)
        finally:
            active.remove(identity)
        verified.add(identity)

    for identity in required:
        verify_artifact(identity)
    return tuple(sorted(verified))


def _source_relative_path(value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ImplementationClosureError(
            "Job source closure path must be non-empty ASCII"
        )
    if "\\" in value:
        raise ImplementationClosureError(
            "Job source closure path must use POSIX separators"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ImplementationClosureError(
            "Job source closure path must be normalized and relative"
        )
    return value


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _path_traverses_link_like(path: Path) -> bool:
    """Return whether any existing component is a symlink or junction."""

    if not path.is_absolute():
        return True
    candidate = Path(path.anchor)
    for part in path.parts[1:]:
        candidate = candidate / part
        if candidate.exists() and _link_like(candidate):
            return True
    return False


def _callable_source_location(callable_identity: object) -> tuple[str, str]:
    if (
        type(callable_identity) is not str
        or not callable_identity
        or not callable_identity.isascii()
    ):
        raise ImplementationClosureError(
            "Job callable identity must be non-empty ASCII"
        )
    parts = callable_identity.split(".")
    if (
        len(parts) < 4
        or re.fullmatch(r"v[1-9][0-9]*", parts[-1]) is None
        or not parts[-2].isidentifier()
        or any(not part.isidentifier() for part in parts[:-2])
        or parts[0] != "axiom_rift"
    ):
        raise ImplementationClosureError(
            "prospective Job callable identity must name one versioned "
            "axiom_rift module function"
        )
    return "/".join(parts[:-2]) + ".py", parts[-2]


def _attribute_chain(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        prefix = _attribute_chain(node.value)
        if prefix is not None:
            return (*prefix, node.attr)
    return None


def _static_string(node: ast.AST | None) -> str | None:
    """Resolve only syntax-proven strings without executing prospective code."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        values = tuple(_static_string(value) for value in node.values)
        if all(value is not None for value in values):
            return "".join(value for value in values if value is not None)
    return None


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _assigned_names(item)
        }
    return set()


def _reject_running_job_context_owner_drift(
    *,
    relative_path: str,
    tree: ast.Module,
) -> None:
    """Keep the trusted context owner narrower than the authority it wraps."""

    for node in ast.walk(tree):
        static_value = _static_string(node)
        if static_value == _WRITER_MODULE or static_value in (
            _RUNNING_JOB_CONTEXT_OWNER_FORBIDDEN_SURFACE
        ):
            raise ImplementationClosureError(
                "prospective Job running context owner names a forbidden "
                f"authority surface: {relative_path}"
            )
        if isinstance(node, ast.Import):
            if any(alias.name == _WRITER_MODULE for alias in node.names):
                raise ImplementationClosureError(
                    "prospective Job source cannot add StateWriter to the "
                    f"running Job context owner: {relative_path}"
                )
        elif isinstance(node, ast.ImportFrom):
            imported = {alias.name for alias in node.names}
            if node.module == _WRITER_MODULE or (
                node.module == "axiom_rift.operations"
                and imported.intersection({"*", "writer", "StateWriter"})
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot add StateWriter to the "
                    f"running Job context owner: {relative_path}"
                )
        if isinstance(node, ast.Name) and node.id == "StateWriter":
            raise ImplementationClosureError(
                "prospective Job source cannot expose StateWriter through the "
                f"running Job context owner: {relative_path}"
            )
        if isinstance(node, ast.Attribute) and node.attr == "StateWriter":
            raise ImplementationClosureError(
                "prospective Job source cannot expose StateWriter through the "
                f"running Job context owner: {relative_path}"
            )

    context_classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RunningJobExecutionContext"
    ]
    if len(context_classes) != 1:
        raise ImplementationClosureError(
            "prospective Job running context owner must define exactly one "
            f"RunningJobExecutionContext: {relative_path}"
        )
    context_class = context_classes[0]
    for member in context_class.body:
        names: set[str] = set()
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(member.name)
        elif isinstance(member, ast.Assign):
            names.update(
                name
                for target in member.targets
                for name in _assigned_names(target)
            )
        elif isinstance(member, ast.AnnAssign):
            names.update(_assigned_names(member.target))
        for name in names:
            if name in _RUNNING_JOB_CONTEXT_OWNER_FORBIDDEN_SURFACE:
                raise ImplementationClosureError(
                    "prospective Job running context owner exposes raw "
                    f"authority: {relative_path}"
                )
            if (
                not name.startswith("_")
                and name not in _RUNNING_JOB_CONTEXT_OWNER_ALLOWED_MEMBERS
            ):
                raise ImplementationClosureError(
                    "prospective Job running context owner added an "
                    f"unapproved public member: {relative_path}"
                )
    for node in ast.walk(context_class):
        value = _static_string(node)
        if value in _RUNNING_JOB_CONTEXT_OWNER_FORBIDDEN_SURFACE:
            raise ImplementationClosureError(
                "prospective Job running context owner exposes raw authority "
                f"by name: {relative_path}"
            )

    for member in tree.body:
        names: set[str] = set()
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(member.name)
        elif isinstance(member, ast.Assign):
            names.update(
                name
                for target in member.targets
                for name in _assigned_names(target)
            )
        elif isinstance(member, ast.AnnAssign):
            names.update(_assigned_names(member.target))
        if names.intersection(_RUNNING_JOB_CONTEXT_OWNER_FORBIDDEN_SURFACE):
            raise ImplementationClosureError(
                "prospective Job running context owner exports raw authority: "
                f"{relative_path}"
            )


def _reject_unscoped_context_path_export(
    *,
    relative_path: str,
    tree: ast.Module,
    local_names: set[str],
) -> None:
    """Confine absolute dependency paths to the two closure builders."""

    allowed_functions = _RUNNING_JOB_CONTEXT_PATH_BUILDERS.get(relative_path)
    if allowed_functions is None:
        raise ImplementationClosureError(
            "prospective Job source cannot import running context dependency "
            f"paths: {relative_path}"
        )
    for member in tree.body:
        if isinstance(member, ast.ImportFrom):
            continue
        if (
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name in allowed_functions
        ):
            continue
        if any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in local_names
            for node in ast.walk(member)
        ):
            raise ImplementationClosureError(
                "prospective Job source uses running context dependency paths "
                f"outside its closure builder: {relative_path}"
            )


@lru_cache(maxsize=512)
def _reject_prospective_evidence_capability_escape(
    *,
    relative_path: str,
    content: bytes,
) -> None:
    """Reject raw/path evidence authority from prospective source closures."""

    historical_identity = HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256.get(
        relative_path
    )
    if historical_identity is not None:
        if sha256(content).hexdigest() != historical_identity:
            raise ImplementationClosureError(
                "frozen historical source registry identity drifted: "
                f"{relative_path}"
            )
        raise ImplementationClosureError(
            "frozen historical source is reconstruction-only and cannot "
            f"enter prospective Job authority: {relative_path}"
        )
    if relative_path in HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS:
        raise ImplementationClosureError(
            "historical raw EvidenceStore compatibility source is "
            "reconstruction-only and cannot enter prospective Job authority: "
            f"{relative_path}"
        )
    if not relative_path.endswith(".py"):
        return
    try:
        tree = ast.parse(content, filename=relative_path, mode="exec")
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ImplementationClosureError(
            "prospective Job Python source is not parseable: "
            f"{relative_path}"
        ) from exc
    if relative_path == _EVIDENCE_CAPABILITY_OWNER_PATH:
        return
    if relative_path == _RUNNING_JOB_CONTEXT_OWNER_PATH:
        _reject_running_job_context_owner_drift(
            relative_path=relative_path,
            tree=tree,
        )
        return

    context_type_names: set[str] = set()
    reflective_import_names: set[str] = set()
    inspection_import_names: set[str] = set()
    dynamic_import_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "builtins":
                    raise ImplementationClosureError(
                        "prospective Job source cannot import the builtins "
                        f"reflection namespace: {relative_path}"
                    )
                if alias.name == _WRITER_MODULE:
                    raise ImplementationClosureError(
                        "prospective Job source cannot import StateWriter "
                        f"authority: {relative_path}"
                    )
                if alias.name == _RUNNING_JOB_MODULE:
                    raise ImplementationClosureError(
                        "prospective Job source cannot import raw running Job "
                        f"authority: {relative_path}"
                    )
                if alias.name in _RUNNING_JOB_CONTEXT_PATH_FORWARDERS:
                    raise ImplementationClosureError(
                        "prospective Job source cannot import a public "
                        f"dependency-path forwarder: {relative_path}"
                    )
                if alias.name in {_EVIDENCE_MODULE, _RUNNING_JOB_CONTEXT_MODULE}:
                    raise ImplementationClosureError(
                        "prospective Job source cannot import a raw evidence "
                        f"capability module: {relative_path}"
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            imported = {alias.name for alias in node.names}
            if module == "builtins":
                raise ImplementationClosureError(
                    "prospective Job source cannot import the builtins "
                    f"reflection namespace: {relative_path}"
                )
            elif module == "importlib":
                dynamic_import_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
            if module == _WRITER_MODULE or (
                module == "axiom_rift.operations"
                and imported.intersection({"*", "writer", "StateWriter"})
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import StateWriter "
                    f"authority: {relative_path}"
                )
            if (
                module == _RUNNING_JOB_MODULE
                and imported.intersection({"*", "RunningJobAuthority"})
            ) or (
                module == "axiom_rift.operations"
                and imported.intersection({"*", "running_job"})
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import raw running Job "
                    f"authority: {relative_path}"
                )
            forwarded_paths = _RUNNING_JOB_CONTEXT_PATH_FORWARDERS.get(module)
            if forwarded_paths is not None and imported.intersection(
                {"*", *forwarded_paths}
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import a public "
                    f"dependency-path forwarder: {relative_path}"
                )
            if (
                module == "axiom_rift.research"
                and imported.intersection(
                    {
                        "analog_state_scoped_job",
                        "cost_aware_execution_pair_runtime",
                        "fixed_hold_replay_runtime",
                    }
                )
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import a public "
                    f"dependency-path module alias: {relative_path}"
                )
            if (
                module == _EVIDENCE_MODULE
                and imported.intersection({"*", "EvidenceStore"})
            ) or (
                module == "axiom_rift.storage"
                and imported.intersection({"*", "evidence", "EvidenceStore"})
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import raw EvidenceStore "
                    f"authority: {relative_path}"
                )
            if module == _RUNNING_JOB_CONTEXT_MODULE:
                path_exports = {
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name in _RUNNING_JOB_CONTEXT_PATH_EXPORTS
                }
                if path_exports:
                    _reject_unscoped_context_path_export(
                        relative_path=relative_path,
                        tree=tree,
                        local_names=path_exports,
                    )
                for alias in node.names:
                    if alias.name == "*" or alias.name.startswith("_"):
                        raise ImplementationClosureError(
                            "prospective Job source cannot import a private "
                            f"evidence capability: {relative_path}"
                        )
                    if alias.name in _RUNNING_JOB_CONTEXT_TYPE_EXPORTS:
                        context_type_names.add(alias.asname or alias.name)
            if (
                module == "axiom_rift.operations"
                and imported.intersection({"*", "running_job_context"})
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot import a running Job "
                    f"context module alias: {relative_path}"
                )

    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
    ]
    for node in assignments:
        if isinstance(node, ast.Assign):
            targets = {
                name
                for target in node.targets
                for name in _assigned_names(target)
            }
            value = node.value
        else:
            targets = _assigned_names(node.target)
            value = node.value
        if (
            targets.intersection({"MISSION_ID", "STUDY_ID"})
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and _HISTORICAL_CONTROL_ID.fullmatch(value.value) is not None
        ):
            raise ImplementationClosureError(
                "prospective Job source embeds historical Mission or Study "
                f"control authority: {relative_path}"
            )

    # Resolve aliases of the privileged constructor before annotations and
    # constructor calls are classified.  A local alias must not erase the
    # capability taint.
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            if isinstance(assignment, ast.Assign):
                targets = {
                    name
                    for target in assignment.targets
                    for name in _assigned_names(target)
                }
                value = assignment.value
            else:
                targets = _assigned_names(assignment.target)
                value = assignment.value
            if (
                isinstance(value, ast.Name)
                and value.id in context_type_names
                and not targets.issubset(context_type_names)
            ):
                context_type_names.update(targets)
                changed = True

    def annotation_is_context(annotation: ast.AST | None) -> bool:
        if annotation is None:
            return False
        for item in ast.walk(annotation):
            if isinstance(item, ast.Name) and item.id in context_type_names:
                return True
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                identifiers = set(re.findall(r"[A-Za-z_]\w*", item.value))
                if identifiers.intersection(context_type_names):
                    return True
        return False

    context_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                if annotation_is_context(argument.annotation):
                    context_names.add(argument.arg)
            if (
                node.args.vararg is not None
                and annotation_is_context(node.args.vararg.annotation)
            ):
                context_names.add(node.args.vararg.arg)
            if (
                node.args.kwarg is not None
                and annotation_is_context(node.args.kwarg.annotation)
            ):
                context_names.add(node.args.kwarg.arg)
        elif (
            isinstance(node, ast.AnnAssign)
            and annotation_is_context(node.annotation)
        ):
            context_names.update(_assigned_names(node.target))
    evidence_names: set[str] = set()
    reflective_callable_names = {
        "getattr",
        "setattr",
        *reflective_import_names,
    }
    inspection_callable_names = {
        "dir",
        "type",
        "vars",
        *inspection_import_names,
    }
    dynamic_import_callable_names = {
        "__import__",
        "import_module",
        *dynamic_import_names,
    }
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            if isinstance(assignment, ast.Assign):
                targets = {
                    name
                    for target in assignment.targets
                    for name in _assigned_names(target)
                }
                value = assignment.value
            else:
                targets = _assigned_names(assignment.target)
                value = assignment.value
            if value is None:
                continue
            chain = _attribute_chain(value)
            is_context = (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in context_type_names
            ) or (
                isinstance(value, ast.Name) and value.id in context_names
            ) or (
                isinstance(value, ast.Attribute)
                and chain is not None
                and len(chain) > 1
                and chain[0] in context_names | context_type_names
                and chain[1] in _RUNNING_JOB_CONTEXT_METHOD_ATTRIBUTES
            )
            is_evidence = (
                chain is not None
                and (
                    "evidence" in chain
                    or chain[0] in evidence_names
                )
            ) or (
                isinstance(value, ast.Name) and value.id in evidence_names
            )
            if is_context and not targets.issubset(context_names):
                context_names.update(targets)
                changed = True
            if is_evidence and not targets.issubset(evidence_names):
                evidence_names.update(targets)
                changed = True
            if isinstance(value, ast.Name):
                for alias_set in (
                    reflective_callable_names,
                    inspection_callable_names,
                    dynamic_import_callable_names,
                ):
                    if (
                        value.id in alias_set
                        and not targets.issubset(alias_set)
                    ):
                        alias_set.update(targets)
                        changed = True
            elif chain is not None:
                if (
                    chain[-1] in {"getattr", "setattr"}
                    or chain[-1]
                    in {"__getattribute__", "__setattr__"}
                ) and not targets.issubset(reflective_callable_names):
                    reflective_callable_names.update(targets)
                    changed = True
                if (
                    chain[-1] in {"dir", "type", "vars"}
                    and not targets.issubset(inspection_callable_names)
                ):
                    inspection_callable_names.update(targets)
                    changed = True
                if (
                    chain[-1] == "import_module"
                    and not targets.issubset(dynamic_import_callable_names)
                ):
                    dynamic_import_callable_names.update(targets)
                    changed = True

    def expression_is_context(value: ast.AST) -> bool:
        chain = _attribute_chain(value)
        return (
            chain is not None and chain[0] in context_names
        ) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in context_type_names
        )

    def expression_is_evidence(value: ast.AST) -> bool:
        chain = _attribute_chain(value)
        return (
            chain is not None
            and (chain[0] in evidence_names or "evidence" in chain)
        ) or (
            isinstance(value, ast.Attribute)
            and value.attr == "evidence"
            and expression_is_context(value.value)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            raise ImplementationClosureError(
                "prospective Job source cannot access the builtins reflection "
                f"namespace: {relative_path}"
            )
        if isinstance(node, ast.Name) and node.id == "StateWriter":
            raise ImplementationClosureError(
                "prospective Job source references StateWriter authority: "
                f"{relative_path}"
            )
        if isinstance(node, ast.Name) and node.id in {
            "EvidenceStore",
            "_EvidenceStore",
        }:
            raise ImplementationClosureError(
                "prospective Job source references raw EvidenceStore authority: "
                f"{relative_path}"
            )
        if isinstance(node, ast.Attribute):
            chain = _attribute_chain(node)
            if (
                node.attr == "__dict__"
                and chain is not None
                and chain[0] in {"builtins", "object"}
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot inspect the builtins "
                    f"reflection namespace: {relative_path}"
                )
            if node.attr in {
                "EvidenceStore",
                "StateWriter",
                "_EvidenceStore",
                "_RunningJobEvidenceFacade__store",
            }:
                raise ImplementationClosureError(
                    "prospective Job source uses evidence capability "
                    f"reflection: {relative_path}"
                )
            if (
                node.attr in _CAPABILITY_INTROSPECTION_ATTRIBUTES
                and chain is not None
                and (
                    chain[0] in context_type_names
                    or chain[0] in context_names
                    or chain[0] in evidence_names
                    or "evidence" in chain[:-1]
                )
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot introspect an evidence "
                    f"capability: {relative_path}"
                )
            value_is_evidence = expression_is_evidence(node.value)
            if (
                expression_is_context(node.value)
                and not value_is_evidence
                and node.attr not in _RUNNING_JOB_CONTEXT_PUBLIC_ATTRIBUTES
            ):
                raise ImplementationClosureError(
                    "prospective Job source escapes the running Job context: "
                    f"{relative_path}"
                )
            if (
                value_is_evidence
                and node.attr not in _RUNNING_JOB_EVIDENCE_PUBLIC_ATTRIBUTES
            ):
                raise ImplementationClosureError(
                    "prospective Job source exceeds the running Job evidence "
                    f"facade: {relative_path}"
                )
            if chain is None:
                continue
            if (
                chain[0] in context_names
                and len(chain) > 1
                and chain[1] not in _RUNNING_JOB_CONTEXT_PUBLIC_ATTRIBUTES
            ):
                raise ImplementationClosureError(
                    "prospective Job source escapes the running Job context: "
                    f"{relative_path}"
                )
            if (
                (
                    chain[0] in evidence_names
                    or "evidence" in chain[:-1]
                )
                and chain[-1]
                not in _RUNNING_JOB_EVIDENCE_PUBLIC_ATTRIBUTES
            ):
                raise ImplementationClosureError(
                    "prospective Job source exceeds the running Job evidence "
                    f"facade: {relative_path}"
                )
        if isinstance(node, ast.Subscript):
            key = _static_string(node.slice)
            if (
                key
                in {
                    "RunningJobAuthority",
                    "StateWriter",
                    "__getattribute__",
                    "__import__",
                    "__setattr__",
                    "object",
                    _EVIDENCE_MODULE,
                    _RUNNING_JOB_CONTEXT_MODULE,
                    _RUNNING_JOB_MODULE,
                    _WRITER_MODULE,
                }
            ):
                raise ImplementationClosureError(
                    "prospective Job source cannot recover a privileged "
                    f"builtin by reflection: {relative_path}"
                )
        if not isinstance(node, ast.Call):
            continue
        first_argument = node.args[0] if node.args else None
        function_chain = _attribute_chain(node.func)
        is_reflective_builtin = (
            isinstance(node.func, ast.Name)
            and node.func.id in reflective_callable_names
        ) or (
            function_chain is not None
            and function_chain[-1] in {"getattr", "setattr"}
        )
        is_raw_attribute_accessor = (
            function_chain is not None
            and function_chain[-1]
            in {"__getattribute__", "__setattr__"}
        )
        if is_reflective_builtin or is_raw_attribute_accessor:
            reflected_name = (
                _static_string(node.args[1])
                if len(node.args) > 1
                else None
            )
            if (
                first_argument is not None
                and (
                    expression_is_context(first_argument)
                    or expression_is_evidence(first_argument)
                )
            ) or reflected_name in _SENSITIVE_REFLECTION_NAMES:
                raise ImplementationClosureError(
                    "prospective Job source cannot reflect over evidence "
                    f"capabilities: {relative_path}"
                )
        if (
            first_argument is not None
            and isinstance(node.func, ast.Name)
            and node.func.id in inspection_callable_names
            and (
                expression_is_context(first_argument)
                or expression_is_evidence(first_argument)
            )
        ):
            raise ImplementationClosureError(
                "prospective Job source cannot inspect evidence capabilities: "
                f"{relative_path}"
            )
        imported_module = _static_string(node.args[0]) if node.args else None
        if (
            imported_module
            in {
                _EVIDENCE_MODULE,
                _RUNNING_JOB_CONTEXT_MODULE,
                _RUNNING_JOB_MODULE,
                _WRITER_MODULE,
            }
            and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id in dynamic_import_callable_names
                )
                or (
                    function_chain is not None
                    and function_chain[-1] == "import_module"
                )
            )
        ):
            raise ImplementationClosureError(
                "prospective Job source cannot dynamically import a privileged "
                f"capability module: {relative_path}"
            )


def require_current_job_source_closure(
    *,
    callable_identity: str,
    job_artifact_hashes: Sequence[str],
    artifact_reader: Callable[[str], bytes],
    source_root: Path,
    verified_non_source_artifact_hashes: Sequence[str] = (),
) -> dict[str, Any]:
    """Bind a prospective Job closure to exact current project source paths.

    Durable hashes alone do not authorize execution: the one typed closure
    must explain the entire implementation artifact set, preserve path roles,
    and map every declared path to the same regular, link-free file and bytes
    under the current repository ``src`` root.  The versioned callable must be
    defined in its identity-derived module path.
    """

    artifacts = tuple(job_artifact_hashes)
    if (
        not artifacts
        or any(not _is_digest(value) for value in artifacts)
        or tuple(sorted(set(artifacts))) != artifacts
    ):
        raise ImplementationClosureError(
            "Job source closure artifacts must be sorted unique SHA-256 digests"
        )
    if not callable(artifact_reader):
        raise ImplementationClosureError("artifact_reader must be callable")
    non_source_artifacts = tuple(verified_non_source_artifact_hashes)
    if (
        any(not _is_digest(value) for value in non_source_artifacts)
        or tuple(sorted(set(non_source_artifacts))) != non_source_artifacts
        or not set(non_source_artifacts).issubset(artifacts)
    ):
        raise ImplementationClosureError(
            "verified non-source implementation artifacts are malformed"
        )
    if (
        not isinstance(source_root, Path)
        or _path_traverses_link_like(source_root)
    ):
        raise ImplementationClosureError(
            "Job source root and its traversal must be link-free",
            same_identity_repairable=True,
        )
    try:
        normalized_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ImplementationClosureError(
            "Job source root is unavailable",
            same_identity_repairable=True,
        ) from exc
    if not normalized_root.is_dir():
        raise ImplementationClosureError(
            "Job source root must be a directory",
            same_identity_repairable=True,
        )

    opened: dict[str, bytes] = {}
    closures: list[tuple[str, Mapping[str, Any]]] = []
    for identity in artifacts:
        try:
            content = artifact_reader(identity)
        except Exception as exc:
            raise ImplementationClosureError(
                f"Job source artifact is unavailable: {identity}",
                same_identity_repairable=True,
            ) from exc
        if type(content) is not bytes or sha256(content).hexdigest() != identity:
            raise ImplementationClosureError(
                f"Job source artifact hash mismatch: {identity}",
                same_identity_repairable=True,
            )
        opened[identity] = content
        try:
            payload = parse_canonical(content)
        except ValueError:
            continue
        if (
            isinstance(payload, Mapping)
            and payload.get("schema")
            == JOB_IMPLEMENTATION_SOURCE_CLOSURE_SCHEMA
        ):
            closures.append((identity, payload))
    if len(closures) != 1:
        raise ImplementationClosureError(
            "Job implementation must contain exactly one typed source closure"
        )
    closure_hash, closure = closures[0]
    dependencies = closure.get("dependencies")
    if (
        set(closure) != {"callable_identity", "dependencies", "schema"}
        or closure.get("callable_identity") != callable_identity
        or not isinstance(dependencies, list)
        or not dependencies
    ):
        raise ImplementationClosureError(
            "Job implementation source closure is malformed"
        )

    normalized_dependencies: list[dict[str, str]] = []
    for dependency in dependencies:
        if (
            not isinstance(dependency, Mapping)
            or set(dependency) != {"path", "sha256"}
            or not _is_digest(dependency.get("sha256"))
        ):
            raise ImplementationClosureError(
                "Job source closure dependency is malformed"
            )
        normalized_dependencies.append(
            {
                "path": _source_relative_path(dependency.get("path")),
                "sha256": str(dependency["sha256"]),
            }
        )
    paths = [item["path"] for item in normalized_dependencies]
    if (
        normalized_dependencies
        != sorted(normalized_dependencies, key=lambda item: item["path"])
        or len(set(paths)) != len(paths)
    ):
        raise ImplementationClosureError(
            "Job source closure paths must be sorted and unique"
        )
    expected_artifacts = {
        closure_hash,
        *(item["sha256"] for item in normalized_dependencies),
        *non_source_artifacts,
    }
    if set(artifacts) != expected_artifacts:
        raise ImplementationClosureError(
            "Job source closure must explain the exact implementation artifact set"
        )

    callable_path, callable_name = _callable_source_location(
        callable_identity
    )
    if callable_path not in set(paths):
        raise ImplementationClosureError(
            "Job source closure omits its identity-derived callable module path"
        )
    validation_order = sorted(
        normalized_dependencies,
        key=lambda item: (
            item["path"] != callable_path,
            item["path"],
        ),
    )
    for dependency in validation_order:
        relative_path = PurePosixPath(dependency["path"])
        if relative_path.parts[0] != "axiom_rift":
            raise ImplementationClosureError(
                "prospective Job source must remain inside the axiom_rift package"
            )
        candidate = normalized_root
        for part in relative_path.parts:
            candidate = candidate / part
            if _link_like(candidate):
                raise ImplementationClosureError(
                    "Job source closure paths must not traverse links or junctions",
                    same_identity_repairable=True,
                )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(normalized_root)
        except (OSError, ValueError) as exc:
            raise ImplementationClosureError(
                "Job source closure path escapes or is unavailable",
                same_identity_repairable=True,
            ) from exc
        if not resolved.is_file():
            raise ImplementationClosureError(
                "Job source closure path must resolve to a regular file",
                same_identity_repairable=True,
            )
        current_bytes = resolved.read_bytes()
        identity = dependency["sha256"]
        if (
            sha256(current_bytes).hexdigest() != identity
            or opened.get(identity) != current_bytes
        ):
            raise ImplementationClosureError(
                "Job source closure does not match current project source bytes",
                same_identity_repairable=True,
            )
        _reject_prospective_evidence_capability_escape(
            relative_path=dependency["path"],
            content=current_bytes,
        )

    callable_bytes = (
        normalized_root.joinpath(*PurePosixPath(callable_path).parts).read_bytes()
    )
    try:
        callable_tree = ast.parse(callable_bytes, mode="exec")
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ImplementationClosureError(
            "Job callable module is not parseable Python",
            same_identity_repairable=True,
        ) from exc
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == callable_name
        for node in callable_tree.body
    ):
        raise ImplementationClosureError(
            "Job callable function is not defined in its identity-derived module",
            same_identity_repairable=True,
        )

    return {
        "callable_module_path": callable_path,
        "dependency_count": len(normalized_dependencies),
        "path_inventory_hash": canonical_digest(
            domain="job-implementation-source-path-inventory",
            payload={"dependencies": normalized_dependencies},
        ),
        "schema": JOB_IMPLEMENTATION_SOURCE_AUTHORITY_SCHEMA,
        "source_closure_hash": closure_hash,
    }


__all__ = [
    "ImplementationClosureError",
    "COMPONENT_IMPLEMENTATION_BUNDLE_SCHEMA",
    "HISTORICAL_RECONSTRUCTION_ONLY_SOURCE_SHA256",
    "HISTORICAL_RAW_EVIDENCESTORE_COMPATIBILITY_PATHS",
    "JOB_IMPLEMENTATION_SOURCE_AUTHORITY_SCHEMA",
    "JOB_IMPLEMENTATION_SOURCE_CLOSURE_SCHEMA",
    "component_implementation_sha256",
    "executable_implementation_hashes",
    "require_current_job_source_closure",
    "require_job_implementation_closure",
    "semantic_dependency_closure",
]
