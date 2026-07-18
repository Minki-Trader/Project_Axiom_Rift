"""Implementation-integrity sealing for evidence validator registrations."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import inspect
import os
from pathlib import Path
import stat
import sys
from types import CodeType, FunctionType, MethodType, ModuleType
from typing import Any, Callable, Mapping

from axiom_rift.operations.validation import (
    EvidenceValidationError,
    validator_identity,
    validator_implementation_sha256,
)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise EvidenceValidationError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise EvidenceValidationError(
            f"{name} must be a lowercase SHA-256 digest"
        )
    return text


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_SOURCE_ROOT = _PROJECT_ROOT / "src"
_INTEGRITY_IMPLEMENTATION = Path(__file__).resolve()


def _regular_file(
    value: str | Path,
    *,
    label: str,
    python_source: bool = False,
) -> Path:
    try:
        raw = Path(value)
        if raw.is_symlink():
            raise EvidenceValidationError(f"{label} must not be a symlink")
        path = raw.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        raise EvidenceValidationError(f"{label} is invalid or absent") from exc
    if not path.is_file() or (python_source and path.suffix != ".py"):
        suffix = " Python" if python_source else ""
        raise EvidenceValidationError(
            f"{label} must be a regular{suffix} file"
        )
    return path


def _project_relative(path: Path) -> bool:
    try:
        path.relative_to(_PROJECT_ROOT)
    except ValueError:
        return False
    return True


def _module_name_for_path(path: Path) -> tuple[str, str] | None:
    for root in (_PROJECT_SOURCE_ROOT, _PROJECT_ROOT):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if path.suffix != ".py":
            return None
        parts = list(relative.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        if not parts:
            return None
        module = ".".join(parts)
        package = module if is_package else module.rpartition(".")[0]
        return module, package
    return None


def _project_module_paths(module_name: str) -> tuple[Path, ...]:
    if not module_name or any(not part for part in module_name.split(".")):
        return ()
    relative = Path(*module_name.split("."))
    for root in (_PROJECT_SOURCE_ROOT, _PROJECT_ROOT):
        package = root / relative / "__init__.py"
        source = (root / relative).with_suffix(".py")
        target = package if package.is_file() else source if source.is_file() else None
        if target is None:
            continue
        if target.is_symlink():
            raise EvidenceValidationError(
                "project validator dependency must not be a symlink"
            )
        try:
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise EvidenceValidationError(
                "project validator dependency is invalid or absent"
            ) from exc
        if not _project_relative(resolved):
            raise EvidenceValidationError(
                "project validator dependency resolves outside the project"
            )
        paths: set[Path] = {resolved}
        parent = target.parent
        while parent != root:
            if parent.is_symlink():
                raise EvidenceValidationError(
                    "project validator dependency path must not contain a symlink"
                )
            initializer = parent / "__init__.py"
            if initializer.is_file():
                paths.add(
                    _regular_file(
                        initializer,
                        label="project package initializer",
                        python_source=True,
                    )
                )
            parent = parent.parent
        return tuple(sorted(paths, key=lambda item: item.as_posix()))
    return ()


def _absolute_import_name(
    *,
    module: str | None,
    level: int,
    package: str,
) -> str:
    if level == 0:
        return "" if module is None else module
    package_parts = package.split(".") if package else []
    retained = len(package_parts) - level + 1
    if retained < 0:
        return ""
    prefix = package_parts[:retained]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _project_python_import_dependency_paths(
    root_paths: tuple[Path, ...],
    *,
    include_deferred_imports: bool,
    observed_source_digests: dict[Path, str] | None = None,
    inventory_digest: str | None = None,
) -> tuple[Path, ...]:
    """Return one recursive import closure for all project Python roots."""

    if inventory_digest is None:
        inventory_digest = _project_python_inventory_fingerprint()
    project_roots = tuple(
        path
        for path in root_paths
        if path.suffix == ".py" and _project_relative(path)
    )
    pending = list(project_roots)
    visited: set[Path] = set()
    closure: set[Path] = set(project_roots)
    for root in project_roots:
        context = _module_name_for_path(root)
        if context is None:
            raise EvidenceValidationError(
                "project validator dependency has no importable module identity"
            )
        closure.update(_project_module_paths(context[0]))
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        module_context = _module_name_for_path(path)
        if module_context is None:
            raise EvidenceValidationError(
                "project validator dependency has no importable module identity"
            )
        _module_name, package = module_context
        try:
            source = path.read_bytes()
            source_digest = sha256(source).hexdigest()
            if observed_source_digests is not None:
                observed_source_digests[path] = source_digest
        except OSError as exc:
            raise EvidenceValidationError(
                "project validator dependency source cannot be read"
            ) from exc
        cache_key = (
            path,
            source_digest,
            include_deferred_imports,
            inventory_digest,
        )
        dependencies = _PROJECT_IMPORT_DEPENDENCY_CACHE.get(cache_key)
        if dependencies is None:
            try:
                tree = ast.parse(source, filename=str(path))
            except (SyntaxError, ValueError) as exc:
                raise EvidenceValidationError(
                    "project validator dependency source cannot be parsed"
                ) from exc
            import_nodes = (
                ast.walk(tree)
                if include_deferred_imports
                else _module_execution_nodes(tree)
            )
            discovered_names: set[str] = set()
            for node in import_nodes:
                if isinstance(node, ast.Import):
                    discovered_names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    base = _absolute_import_name(
                        module=node.module,
                        level=node.level,
                        package=package,
                    )
                    if base:
                        discovered_names.add(base)
                        for alias in node.names:
                            if alias.name != "*":
                                discovered_names.add(f"{base}.{alias.name}")
            dependencies = tuple(
                sorted(
                    {
                        dependency
                        for name in discovered_names
                        for dependency in _project_module_paths(name)
                    },
                    key=lambda item: item.as_posix(),
                )
            )
            stale = tuple(
                key
                for key in _PROJECT_IMPORT_DEPENDENCY_CACHE
                if key[0] == path
                and key[2] == include_deferred_imports
                and key != cache_key
            )
            for key in stale:
                del _PROJECT_IMPORT_DEPENDENCY_CACHE[key]
            _PROJECT_IMPORT_DEPENDENCY_CACHE[cache_key] = dependencies
        for dependency in dependencies:
            closure.add(dependency)
            if dependency not in visited:
                pending.append(dependency)
    return tuple(sorted(closure, key=lambda item: item.as_posix()))


def _module_execution_nodes(tree: ast.AST) -> tuple[ast.AST, ...]:
    """Return nodes evaluated at import time, excluding deferred bodies."""

    nodes: list[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def generic_visit(self, node: ast.AST) -> None:
            nodes.append(node)
            super().generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            nodes.append(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            nodes.append(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.generic_visit(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            nodes.append(node)

    _Visitor().visit(tree)
    return tuple(nodes)


def validator_project_dependency_paths(
    implementation_path: str | Path,
) -> tuple[Path, ...]:
    """Return project imports for compatibility with the original API.

    New execution-identity callers should use
    :func:`validator_execution_dependency_paths`, which also includes the
    implementation and authored semantic dependency roots.
    """

    implementation = _regular_file(
        implementation_path,
        label="validator implementation",
        python_source=True,
    )
    return tuple(
        path
        for path in _project_python_import_dependency_paths(
            (implementation,),
            include_deferred_imports=True,
        )
        if path != implementation
    )


def _infer_execution_dependency_paths(
    roots: tuple[Path, ...],
    *,
    include_deferred_imports: bool,
    observed_source_digests: dict[Path, str] | None = None,
    inventory_digest: str | None = None,
) -> tuple[Path, ...]:
    closure = set(roots)
    closure.update(
        _project_python_import_dependency_paths(
            roots,
            include_deferred_imports=include_deferred_imports,
            observed_source_digests=observed_source_digests,
            inventory_digest=inventory_digest,
        )
    )
    return tuple(sorted(closure, key=lambda item: item.as_posix()))


def validator_execution_dependency_paths(
    implementation_path: str | Path,
    dependency_paths: tuple[str | Path, ...] = (),
    *,
    include_deferred_imports: bool = False,
) -> tuple[Path, ...]:
    """Infer the complete source closure executed by one validator.

    ``dependency_paths`` are authored execution roots: registry sealing passes
    all semantic identity roots, while a Job passes only the protocol roots it
    can execute.  This function adds the implementation, every root byte, and
    every recursively imported project Python source (including package
    initializers).  Deferred function-body imports are optional so a Job does
    not inherit unrelated protocol branches.  The result is operational and
    deliberately separate from scientific validator identity.
    """

    implementation = _regular_file(
        implementation_path,
        label="validator implementation",
        python_source=True,
    )
    roots = {
        implementation,
        _INTEGRITY_IMPLEMENTATION,
        *(
            _regular_file(
                path,
                label="validator execution dependency",
                python_source=False,
            )
            for path in dependency_paths
        ),
    }
    if type(include_deferred_imports) is not bool:
        raise EvidenceValidationError(
            "validator execution closure mode must be bool"
        )
    ordered_roots = tuple(sorted(roots, key=lambda item: item.as_posix()))
    for _attempt in range(2):
        inventory_digest = _project_python_inventory_fingerprint()
        cache_key = (
            ordered_roots,
            include_deferred_imports,
            inventory_digest,
        )
        cached = _EXECUTION_DEPENDENCY_CACHE.get(cache_key)
        if cached is not None:
            try:
                current = tuple(
                    (path, sha256(path.read_bytes()).hexdigest())
                    for path, _digest_value in cached
                )
            except OSError:
                current = ()
            if current == cached:
                if (
                    _project_python_inventory_fingerprint()
                    == inventory_digest
                ):
                    return tuple(path for path, _digest_value in cached)
                continue
            del _EXECUTION_DEPENDENCY_CACHE[cache_key]
        parsed_source_digests: dict[Path, str] = {}
        paths = _infer_execution_dependency_paths(
            ordered_roots,
            include_deferred_imports=include_deferred_imports,
            observed_source_digests=parsed_source_digests,
            inventory_digest=inventory_digest,
        )
        try:
            binding = tuple(
                (path, sha256(path.read_bytes()).hexdigest()) for path in paths
            )
        except OSError as exc:
            raise EvidenceValidationError(
                "validator execution dependency file is absent"
            ) from exc
        final_digests = dict(binding)
        if any(
            final_digests.get(path) != digest
            for path, digest in parsed_source_digests.items()
        ):
            continue
        if _project_python_inventory_fingerprint() != inventory_digest:
            continue
        stale_keys = tuple(
            key
            for key in _EXECUTION_DEPENDENCY_CACHE
            if key[:2] == cache_key[:2] and key != cache_key
        )
        for key in stale_keys:
            del _EXECUTION_DEPENDENCY_CACHE[key]
        _EXECUTION_DEPENDENCY_CACHE[cache_key] = binding
        return paths
    raise EvidenceValidationError(
        "project Python path inventory changed during execution closure"
    )


def _project_python_inventory_fingerprint() -> str:
    """Hash project Python path presence and file kinds without reading bytes."""

    entries: list[str] = []
    seen: set[Path] = set()
    for root_label, root in (
        ("src", _PROJECT_SOURCE_ROOT),
        ("project", _PROJECT_ROOT),
    ):
        if not root.is_dir():
            continue
        for directory, directory_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            directory_path = Path(directory)
            kept_directories: list[str] = []
            for name in sorted(directory_names):
                if name == "__pycache__" or not name.isidentifier():
                    continue
                child = directory_path / name
                try:
                    mode = child.lstat().st_mode
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise EvidenceValidationError(
                        "project Python path inventory cannot be sealed"
                    ) from exc
                if stat.S_ISLNK(mode):
                    relative = child.relative_to(root).as_posix()
                    entries.append(f"{root_label}:dir-symlink:{relative}")
                    continue
                if root == _PROJECT_ROOT and child == _PROJECT_SOURCE_ROOT:
                    continue
                kept_directories.append(name)
            directory_names[:] = kept_directories
            for name in sorted(file_names):
                if not name.endswith(".py") or not Path(name).stem.isidentifier():
                    continue
                path = directory_path / name
                if path in seen:
                    continue
                seen.add(path)
                try:
                    mode = path.lstat().st_mode
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise EvidenceValidationError(
                        "project Python path inventory cannot be sealed"
                    ) from exc
                if stat.S_ISREG(mode):
                    kind = "file"
                elif stat.S_ISLNK(mode):
                    kind = "symlink"
                else:
                    kind = "other"
                relative = path.relative_to(root).as_posix()
                entries.append(f"{root_label}:{kind}:{relative}")
    return sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()


_PROJECT_CLOSURE_CACHE: dict[
    tuple[object, ...], tuple[tuple[Path, str], ...]
] = {}
_EXECUTION_DEPENDENCY_CACHE: dict[
    tuple[object, ...], tuple[tuple[Path, str], ...]
] = {}
_PROJECT_IMPORT_DEPENDENCY_CACHE: dict[
    tuple[Path, str, bool, str], tuple[Path, ...]
] = {}


def _project_closure_binding(
    implementation_path: Path,
    *,
    dependency_paths: tuple[Path, ...] = (),
    require_stable_inventory: bool = False,
) -> tuple[tuple[Path, str], ...]:
    try:
        implementation_digest = sha256(
            implementation_path.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise EvidenceValidationError(
            "validator implementation file is absent"
        ) from exc
    try:
        semantic_binding = tuple(
            (
                path,
                sha256(path.read_bytes()).hexdigest(),
            )
            for path in dependency_paths
        )
    except OSError as exc:
        raise EvidenceValidationError(
            "validator semantic dependency file is absent"
        ) from exc
    for _attempt in range(2):
        inventory_digest = _project_python_inventory_fingerprint()
        cache_key = (
            implementation_path,
            implementation_digest,
            semantic_binding,
            inventory_digest,
        )
        cached = _PROJECT_CLOSURE_CACHE.get(cache_key)
        if cached is not None:
            try:
                current = tuple(
                    (path, sha256(path.read_bytes()).hexdigest())
                    for path, _digest_value in cached
                )
            except OSError:
                current = ()
            if current == cached:
                if (
                    not require_stable_inventory
                    or _project_python_inventory_fingerprint()
                    == inventory_digest
                ):
                    return cached
                continue
        binding: list[tuple[Path, str]] = []
        parsed_source_digests: dict[Path, str] = {}
        roots = tuple(
            sorted(
                {
                    implementation_path,
                    _INTEGRITY_IMPLEMENTATION,
                    *dependency_paths,
                },
                key=lambda path: path.as_posix(),
            )
        )
        for path in _infer_execution_dependency_paths(
            roots,
            include_deferred_imports=True,
            observed_source_digests=parsed_source_digests,
            inventory_digest=inventory_digest,
        ):
            try:
                digest = sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise EvidenceValidationError(
                    "validator project dependency file is absent"
                ) from exc
            binding.append((path, digest))
        frozen = tuple(binding)
        final_digests = dict(frozen)
        if any(
            final_digests.get(path) != digest
            for path, digest in parsed_source_digests.items()
        ):
            continue
        if _project_python_inventory_fingerprint() != inventory_digest:
            continue
        stale_keys = tuple(
            key
            for key in _PROJECT_CLOSURE_CACHE
            if key[0] == implementation_path and key != cache_key
        )
        for key in stale_keys:
            del _PROJECT_CLOSURE_CACHE[key]
        _PROJECT_CLOSURE_CACHE[cache_key] = frozen
        return frozen
    raise EvidenceValidationError(
        "project Python path inventory changed during validator sealing"
    )


def _code_constant_snapshot(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", value.real.hex(), value.imag.hex())
    if type(value) is bytes:
        return ("bytes", value.hex())
    if value is Ellipsis:
        return ("ellipsis",)
    if isinstance(value, CodeType):
        return ("code", _code_payload(value))
    if type(value) in {tuple, frozenset}:
        items = tuple(_code_constant_snapshot(item) for item in value)
        if type(value) is frozenset:
            items = tuple(sorted(items, key=repr))
        return (type(value).__name__, items)
    return (
        "unsupported",
        type(value).__module__,
        type(value).__qualname__,
        repr(value),
    )


def _code_payload(code: CodeType) -> tuple[object, ...]:
    return (
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code.hex(),
        tuple(_code_constant_snapshot(item) for item in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_name,
        code.co_qualname,
        code.co_firstlineno,
        getattr(code, "co_exceptiontable", b"").hex(),
    )


def _code_digest(code: CodeType) -> str:
    return sha256(repr(_code_payload(code)).encode("utf-8")).hexdigest()


def _compiled_code_digests(path: Path) -> dict[str, frozenset[str]]:
    try:
        module_code = compile(
            path.read_bytes(),
            str(path),
            "exec",
            flags=0,
            dont_inherit=True,
            optimize=sys.flags.optimize,
        )
    except (OSError, SyntaxError, ValueError) as exc:
        raise EvidenceValidationError(
            "validator implementation cannot be compiled"
        ) from exc
    by_qualname: dict[str, set[str]] = {}
    pending = [module_code]
    while pending:
        code = pending.pop()
        by_qualname.setdefault(code.co_qualname, set()).add(_code_digest(code))
        pending.extend(
            item for item in code.co_consts if isinstance(item, CodeType)
        )
    return {
        qualname: frozenset(digests)
        for qualname, digests in by_qualname.items()
    }


def _snapshot_value(
    value: object,
    *,
    active: dict[int, int] | None = None,
) -> object:
    if active is None:
        active = {}
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        return ("float", value.hex())
    if type(value) is complex:
        return ("complex", value.real.hex(), value.imag.hex())
    if type(value) is bytes:
        return ("bytes", sha256(value).hexdigest(), len(value))
    if isinstance(value, Path):
        return ("path", str(value.resolve()))
    if isinstance(value, Enum):
        return (
            "enum",
            type(value).__module__,
            type(value).__qualname__,
            value.name,
            _snapshot_value(value.value, active=active),
        )
    marker = id(value)
    if marker in active:
        return ("cycle", active[marker])
    active[marker] = len(active)
    try:
        if type(value) in {tuple, list}:
            return (
                type(value).__name__,
                tuple(_snapshot_value(item, active=active) for item in value),
            )
        if type(value) in {set, frozenset}:
            items = tuple(
                _snapshot_value(item, active=active) for item in value
            )
            return (type(value).__name__, tuple(sorted(items, key=repr)))
        if isinstance(value, Mapping):
            items = [
                (
                    _snapshot_value(key, active=active),
                    _snapshot_value(item, active=active),
                )
                for key, item in value.items()
            ]
            return ("mapping", tuple(sorted(items, key=repr)))
        if isinstance(value, FunctionType):
            closure = ()
            if value.__closure__ is not None:
                closure = tuple(
                    _snapshot_value(cell.cell_contents, active=active)
                    for cell in value.__closure__
                )
            return (
                "function",
                value.__module__,
                value.__qualname__,
                _code_digest(value.__code__),
                _snapshot_value(value.__defaults__, active=active),
                _snapshot_value(value.__kwdefaults__, active=active),
                _snapshot_value(value.__annotations__, active=active),
                _snapshot_value(value.__dict__, active=active),
                closure,
            )
        if isinstance(value, staticmethod):
            return (
                "staticmethod",
                _snapshot_value(value.__func__, active=active),
            )
        if isinstance(value, classmethod):
            return (
                "classmethod",
                _snapshot_value(value.__func__, active=active),
            )
        if isinstance(value, property):
            return (
                "property",
                _snapshot_value(value.fget, active=active),
                _snapshot_value(value.fset, active=active),
                _snapshot_value(value.fdel, active=active),
            )
        if isinstance(value, MethodType):
            return (
                "method",
                _snapshot_value(value.__func__, active=active),
                id(value.__self__),
            )
        if isinstance(value, ModuleType):
            module_file = getattr(value, "__file__", None)
            return (
                "module",
                value.__name__,
                None
                if module_file is None
                else str(Path(module_file).resolve()),
            )
        if isinstance(value, type):
            executable_items = tuple(
                sorted(
                    (
                        name,
                        id(item),
                        _snapshot_value(item, active=active),
                    )
                    for name, item in vars(value).items()
                    if isinstance(
                        item,
                        (FunctionType, staticmethod, classmethod, property),
                    )
                )
            )
            return (
                "type",
                value.__module__,
                value.__qualname__,
                executable_items,
            )
        if (
            inspect.isbuiltin(value)
            or inspect.ismethoddescriptor(value)
            or inspect.isgetsetdescriptor(value)
            or inspect.ismemberdescriptor(value)
        ):
            return (
                "descriptor",
                type(value).__module__,
                type(value).__qualname__,
                getattr(value, "__module__", None),
                getattr(value, "__qualname__", None),
                getattr(value, "__name__", None),
            )
        try:
            state = vars(value)
        except TypeError:
            state = None
        if state is not None:
            return (
                "object",
                type(value).__module__,
                type(value).__qualname__,
                _snapshot_value(state, active=active),
            )
        return (
            "opaque",
            type(value).__module__,
            type(value).__qualname__,
            repr(value),
        )
    finally:
        del active[marker]


def _class_state_snapshot(validator_type: type[object]) -> tuple[object, ...]:
    return tuple(
        (
            name,
            id(value),
            _snapshot_value(value),
        )
        for name, value in sorted(vars(validator_type).items())
    )


def _instance_state(validator: object) -> dict[str, object]:
    try:
        values = dict(vars(validator))
    except TypeError:
        values = {}
    for name, descriptor in vars(type(validator)).items():
        if not inspect.ismemberdescriptor(descriptor):
            continue
        try:
            values[f"slot:{name}"] = object.__getattribute__(validator, name)
        except AttributeError:
            values[f"slot:{name}"] = ("unbound-slot",)
    return values


def _instance_state_snapshot(
    values: Mapping[str, object],
) -> tuple[object, ...]:
    return tuple(
        (name, id(value), _snapshot_value(value))
        for name, value in sorted(values.items())
    )


def _metadata_value(
    *,
    validator_type: type[object],
    instance_values: Mapping[str, object],
    name: str,
) -> object:
    if name in instance_values:
        return instance_values[name]
    slot_name = f"slot:{name}"
    if slot_name in instance_values:
        return instance_values[slot_name]
    if name not in vars(validator_type):
        raise EvidenceValidationError(
            f"validator {name} must be declared on its concrete class or instance"
        )
    value = vars(validator_type)[name]
    if hasattr(value, "__get__"):
        raise EvidenceValidationError(
            f"validator {name} must be plain immutable data"
        )
    return value


@dataclass(frozen=True, slots=True)
class _ValidatorMethodBinding:
    function: FunctionType
    bound: Callable[..., Any]
    descriptor_id: int


def _validator_method_binding(
    *,
    validator: object,
    validator_type: type[object],
    implementation_path: Path,
    compiled: Mapping[str, frozenset[str]] | None,
    name: str,
    required: bool,
) -> _ValidatorMethodBinding | None:
    raw = vars(validator_type).get(name)
    if raw is None:
        if required:
            raise EvidenceValidationError(
                f"validator {name} must be defined on its concrete class"
            )
        return None
    if type(raw) is not FunctionType:
        raise EvidenceValidationError(
            f"validator {name} must be a plain instance method"
        )
    function = raw
    expected_qualname = f"{validator_type.__qualname__}.{name}"
    if (
        function.__module__ != validator_type.__module__
        or function.__qualname__ != expected_qualname
        or function.__closure__ is not None
        or function.__defaults__ is not None
        or function.__kwdefaults__ is not None
    ):
        raise EvidenceValidationError(
            f"validator {name} is not the source-defined concrete method"
        )
    try:
        method_path_value = inspect.getsourcefile(function)
    except (OSError, TypeError) as exc:
        raise EvidenceValidationError(
            f"validator {name} has no source file"
        ) from exc
    method_path = _regular_file(
        method_path_value,
        label=f"validator {name} source",
        python_source=True,
    )
    if method_path != implementation_path:
        raise EvidenceValidationError(
            f"validator {name} source differs from implementation_path"
        )
    if compiled is not None and _code_digest(
        function.__code__
    ) not in compiled.get(function.__qualname__, frozenset()):
        raise EvidenceValidationError(
            f"validator {name} callable differs from implementation source"
        )
    return _ValidatorMethodBinding(
        function=function,
        bound=MethodType(function, validator),
        descriptor_id=id(raw),
    )


def _code_global_names(code: CodeType) -> set[str]:
    names = set(code.co_names)
    for item in code.co_consts:
        if isinstance(item, CodeType):
            names.update(_code_global_names(item))
    return names


def _project_function(function: FunctionType) -> bool:
    try:
        source = inspect.getsourcefile(function)
        if source is None:
            return False
        return _project_relative(Path(source).resolve())
    except (OSError, TypeError, ValueError):
        return False


def _referenced_globals_snapshot(
    functions: tuple[FunctionType, ...],
) -> tuple[object, ...]:
    pending = list(functions)
    seen: set[int] = set()
    snapshot: list[object] = []
    while pending:
        function = pending.pop()
        if id(function) in seen:
            continue
        seen.add(id(function))
        for name in sorted(_code_global_names(function.__code__)):
            if name not in function.__globals__:
                continue
            value = function.__globals__[name]
            snapshot.append(
                (
                    function.__module__,
                    function.__qualname__,
                    name,
                    id(value),
                    _snapshot_value(value),
                )
            )
            if isinstance(value, FunctionType) and _project_function(value):
                pending.append(value)
    return tuple(sorted(snapshot, key=lambda item: repr(item[:3])))


@dataclass(frozen=True, slots=True)
class _ValidatorIntegritySnapshot:
    validator_type_id: int
    validator_module: str
    validator_qualname: str
    validator_id: str
    domains: frozenset[str]
    protocol: str
    authority_scope: str
    implementation_path: Path
    dependency_paths: tuple[Path, ...]
    semantic_boundary_paths: tuple[Path, ...]
    class_state: tuple[object, ...]
    instance_state: tuple[object, ...]
    validate_descriptor_id: int
    validate_state: object
    preflight_descriptor_id: int | None
    preflight_state: object | None
    referenced_globals: tuple[object, ...]


def _capture_validator_integrity(
    validator: object,
    *,
    verify_compiled_source: bool,
) -> tuple[
    _ValidatorIntegritySnapshot,
    Callable[..., Any],
    Callable[..., Any] | None,
]:
    validator_type = type(validator)
    if (
        type(validator_type) is not type
        or validator_type.__bases__ != (object,)
        or "<locals>" in validator_type.__qualname__
        or "__getattr__" in vars(validator_type)
        or "__getattribute__" in vars(validator_type)
    ):
        raise EvidenceValidationError(
            "validator must be a plain module-level concrete class"
        )
    instance_values = _instance_state(validator)
    if "validate" in instance_values or "preflight_binding" in instance_values:
        raise EvidenceValidationError(
            "validator methods must not be shadowed on the instance"
        )
    validator_id = _ascii(
        "validator_id",
        _metadata_value(
            validator_type=validator_type,
            instance_values=instance_values,
            name="validator_id",
        ),
    )
    _digest("validator identity", validator_id.removeprefix("validator:"))
    domains_value = _metadata_value(
        validator_type=validator_type,
        instance_values=instance_values,
        name="domains",
    )
    if (
        type(domains_value) is not frozenset
        or not domains_value
        or not domains_value.issubset(
            {"engineering", "scientific", "source", "runtime", "external"}
        )
    ):
        raise EvidenceValidationError("validator domains are invalid")
    domains = domains_value
    protocol = _ascii(
        "validator protocol",
        _metadata_value(
            validator_type=validator_type,
            instance_values=instance_values,
            name="protocol",
        ),
    )
    raw_authority_scope = instance_values.get(
        "authority_scope",
        vars(validator_type).get("authority_scope", "production"),
    )
    if raw_authority_scope not in {"fixture_only", "production"}:
        raise EvidenceValidationError(
            "validator authority_scope must be fixture_only or production"
        )
    authority_scope = str(raw_authority_scope)
    implementation_path = _regular_file(
        _metadata_value(
            validator_type=validator_type,
            instance_values=instance_values,
            name="implementation_path",
        ),
        label="validator implementation",
        python_source=True,
    )
    if not _project_relative(implementation_path):
        raise EvidenceValidationError(
            "validator implementation must be project-local source"
        )
    raw_dependencies = instance_values.get(
        "dependency_paths",
        vars(validator_type).get("dependency_paths", ()),
    )
    if type(raw_dependencies) is not tuple:
        raise EvidenceValidationError(
            "validator dependency paths must be a declared tuple"
        )
    dependency_paths = tuple(
        _regular_file(item, label="validator dependency")
        for item in raw_dependencies
    )
    if (
        len(set(dependency_paths)) != len(dependency_paths)
        or implementation_path in dependency_paths
    ):
        raise EvidenceValidationError(
            "validator dependency paths must be unique"
        )
    raw_semantic_boundaries = instance_values.get(
        "semantic_boundary_paths",
        vars(validator_type).get("semantic_boundary_paths", ()),
    )
    if type(raw_semantic_boundaries) is not tuple:
        raise EvidenceValidationError(
            "validator semantic boundary paths must be a declared tuple"
        )
    semantic_boundary_paths = tuple(
        _regular_file(
            item,
            label="validator semantic boundary",
            python_source=True,
        )
        for item in raw_semantic_boundaries
    )
    if (
        len(set(semantic_boundary_paths)) != len(semantic_boundary_paths)
        or implementation_path in semantic_boundary_paths
        or set(dependency_paths).intersection(semantic_boundary_paths)
        or any(not _project_relative(path) for path in semantic_boundary_paths)
    ):
        raise EvidenceValidationError(
            "validator semantic boundary paths must be unique, disjoint, and project-local"
        )
    module = sys.modules.get(validator_type.__module__)
    if module is None:
        raise EvidenceValidationError("validator module is not loaded")
    module_path = _regular_file(
        getattr(module, "__file__", None),
        label="validator module source",
        python_source=True,
    )
    try:
        class_source_value = inspect.getsourcefile(validator_type)
    except (OSError, TypeError) as exc:
        raise EvidenceValidationError(
            "validator class has no source file"
        ) from exc
    class_source = _regular_file(
        class_source_value,
        label="validator class source",
        python_source=True,
    )
    if module_path != implementation_path or class_source != implementation_path:
        raise EvidenceValidationError(
            "validator class/module source differs from implementation_path"
        )
    compiled = (
        _compiled_code_digests(implementation_path)
        if verify_compiled_source
        else None
    )
    if compiled is not None and validator_type.__qualname__ not in compiled:
        raise EvidenceValidationError(
            "validator class is absent from implementation source"
        )
    validate = _validator_method_binding(
        validator=validator,
        validator_type=validator_type,
        implementation_path=implementation_path,
        compiled=compiled,
        name="validate",
        required=True,
    )
    assert validate is not None
    preflight = _validator_method_binding(
        validator=validator,
        validator_type=validator_type,
        implementation_path=implementation_path,
        compiled=compiled,
        name="preflight_binding",
        required=False,
    )
    functions = (validate.function,) + (
        () if preflight is None else (preflight.function,)
    )
    snapshot = _ValidatorIntegritySnapshot(
        validator_type_id=id(validator_type),
        validator_module=validator_type.__module__,
        validator_qualname=validator_type.__qualname__,
        validator_id=validator_id,
        domains=domains,
        protocol=protocol,
        authority_scope=authority_scope,
        implementation_path=implementation_path,
        dependency_paths=dependency_paths,
        semantic_boundary_paths=semantic_boundary_paths,
        class_state=_class_state_snapshot(validator_type),
        instance_state=_instance_state_snapshot(instance_values),
        validate_descriptor_id=validate.descriptor_id,
        validate_state=_snapshot_value(validate.function),
        preflight_descriptor_id=(
            None if preflight is None else preflight.descriptor_id
        ),
        preflight_state=(
            None if preflight is None else _snapshot_value(preflight.function)
        ),
        referenced_globals=_referenced_globals_snapshot(functions),
    )
    return (
        snapshot,
        validate.bound,
        None if preflight is None else preflight.bound,
    )


@dataclass(frozen=True, slots=True)
class _ValidatorRegistration:
    validator: object
    integrity: _ValidatorIntegritySnapshot
    implementation_hash: str
    project_closure: tuple[tuple[Path, str], ...]
    validate: Callable[..., Any]
    preflight: Callable[..., Any] | None


def _build_validator_registration(validator: object) -> _ValidatorRegistration:
    integrity, validate, preflight = _capture_validator_integrity(
        validator,
        verify_compiled_source=True,
    )
    project_closure = _project_closure_binding(
        integrity.implementation_path,
        dependency_paths=(
            *integrity.dependency_paths,
            *integrity.semantic_boundary_paths,
        ),
        require_stable_inventory=True,
    )
    implementation_hash = validator_implementation_sha256(
        implementation_path=integrity.implementation_path,
        dependency_paths=integrity.dependency_paths,
        semantic_boundary_paths=integrity.semantic_boundary_paths,
    )
    expected_id = validator_identity(
        protocol=integrity.protocol,
        domains=integrity.domains,
        implementation_sha256=implementation_hash,
    )
    if integrity.validator_id != expected_id:
        raise EvidenceValidationError(
            "validator identity does not bind its implementation bundle"
        )
    return _ValidatorRegistration(
        validator=validator,
        integrity=integrity,
        implementation_hash=implementation_hash,
        project_closure=project_closure,
        validate=validate,
        preflight=preflight,
    )


def _require_validator_registration_unchanged(
    registration: _ValidatorRegistration,
) -> None:
    try:
        current, _validate, _preflight = _capture_validator_integrity(
            registration.validator,
            verify_compiled_source=False,
        )
        actual_hash = validator_implementation_sha256(
            implementation_path=registration.integrity.implementation_path,
            dependency_paths=registration.integrity.dependency_paths,
            semantic_boundary_paths=(
                registration.integrity.semantic_boundary_paths
            ),
        )
        actual_closure = _project_closure_binding(
            registration.integrity.implementation_path,
            dependency_paths=(
                *registration.integrity.dependency_paths,
                *registration.integrity.semantic_boundary_paths,
            ),
        )
    except (EvidenceValidationError, OSError) as exc:
        raise EvidenceValidationError(
            "validator registration changed after registration"
        ) from exc
    if (
        current != registration.integrity
        or actual_hash != registration.implementation_hash
        or actual_closure != registration.project_closure
    ):
        raise EvidenceValidationError(
            "validator registration changed after registration"
        )


__all__ = [
    "EvidenceValidationError",
    "validator_identity",
    "validator_implementation_sha256",
    "validator_execution_dependency_paths",
    "validator_project_dependency_paths",
]
