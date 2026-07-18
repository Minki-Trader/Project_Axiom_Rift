"""Stable project-local semantic dependency discovery for validator identity.

The authored ``dependency_paths`` of a validator are semantic roots.  This
module follows only imports reached from those roots; imports reached only from
the validator implementation remain part of the operational registry closure.
Dynamic project imports must be reducible to a literal target or an immutable
module-level routing table, otherwise identity construction fails closed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import stat
from threading import RLock
from typing import Mapping


class SemanticDependencyError(RuntimeError):
    """An authored semantic dependency graph cannot be sealed exactly."""


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_SOURCE_ROOT = _PROJECT_ROOT / "src"


@dataclass(frozen=True, slots=True)
class SemanticDependency:
    path: Path
    project_path: str | None
    sha256: str


@dataclass(frozen=True, slots=True)
class _ImportAnalysis:
    static_modules: tuple[str, ...]
    dynamic_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ModuleResolution:
    target: Path
    dependency_paths: tuple[Path, ...]


_IMPORT_ANALYSIS_CACHE: dict[tuple[Path, str], _ImportAnalysis] = {}
_SEMANTIC_CLOSURE_CACHE: dict[
    tuple[tuple[Path, ...], frozenset[Path], str],
    tuple[SemanticDependency, ...],
] = {}
_CACHE_LOCK = RLock()


def _project_relative(path: Path) -> str | None:
    try:
        return path.relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def _project_python_inventory_fingerprint() -> str:
    """Hash importable project Python path presence and file kinds."""

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
                    raise SemanticDependencyError(
                        "project Python path inventory cannot be sealed"
                    ) from exc
                relative = child.relative_to(root).as_posix()
                if stat.S_ISLNK(mode):
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
                    raise SemanticDependencyError(
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


def _module_context(path: Path) -> tuple[str, str, bool] | None:
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
        if not parts or any(not part.isidentifier() for part in parts):
            return None
        module = ".".join(parts)
        package = module if is_package else module.rpartition(".")[0]
        return module, package, is_package
    return None


def _regular_file(path: Path, *, label: str) -> Path:
    try:
        if path.is_symlink():
            raise SemanticDependencyError(f"{label} must not be a symlink")
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SemanticDependencyError(f"{label} is invalid or absent") from exc
    if not resolved.is_file():
        raise SemanticDependencyError(f"{label} must be a regular file")
    return resolved


def _module_resolution(module_name: str) -> _ModuleResolution | None:
    if not module_name or any(
        not part.isidentifier() for part in module_name.split(".")
    ):
        return None
    relative = Path(*module_name.split("."))
    resolutions: list[_ModuleResolution] = []
    for root in (_PROJECT_SOURCE_ROOT, _PROJECT_ROOT):
        package = root / relative / "__init__.py"
        source = (root / relative).with_suffix(".py")
        existing = [path for path in (package, source) if path.is_file()]
        if len(existing) > 1:
            raise SemanticDependencyError(
                "project semantic module has ambiguous package and source targets"
            )
        if not existing:
            continue
        raw_target = existing[0]
        target = _regular_file(
            raw_target,
            label="project semantic dependency",
        )
        try:
            target.relative_to(_PROJECT_ROOT)
        except ValueError as exc:
            raise SemanticDependencyError(
                "project semantic dependency resolves outside the project"
            ) from exc
        dependencies = {target}
        parent = raw_target.parent
        while parent != root:
            if parent.is_symlink():
                raise SemanticDependencyError(
                    "project semantic dependency path must not contain a symlink"
                )
            initializer = parent / "__init__.py"
            if initializer.is_file():
                dependencies.add(
                    _regular_file(
                        initializer,
                        label="project package initializer",
                    )
                )
            parent = parent.parent
        resolutions.append(
            _ModuleResolution(
                target=target,
                dependency_paths=tuple(
                    sorted(dependencies, key=lambda item: item.as_posix())
                ),
            )
        )
    unique = tuple(
        {
            resolution.target: resolution
            for resolution in resolutions
        }.values()
    )
    if len(unique) > 1:
        raise SemanticDependencyError(
            "project semantic module is shadowed by another project root"
        )
    return None if not unique else unique[0]


def _module_target(module_name: str) -> Path | None:
    resolution = _module_resolution(module_name)
    return None if resolution is None else resolution.target


def _absolute_import_name(
    *,
    module: str | None,
    level: int,
    package: str,
) -> str:
    if level == 0:
        return "" if module is None else module
    parts = package.split(".") if package else []
    retained = len(parts) - level + 1
    if retained < 0:
        return ""
    prefix = parts[:retained]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def _without_type_checking(tree: ast.Module) -> tuple[ast.AST, ...]:
    nodes: list[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            test = node.test
            is_type_checking = (
                isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
            ) or (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "typing"
                and test.attr == "TYPE_CHECKING"
            )
            nodes.append(node)
            if is_type_checking:
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def generic_visit(self, node: ast.AST) -> None:
            if node is not tree:
                nodes.append(node)
            super().generic_visit(node)

    visitor = _Visitor()
    for statement in tree.body:
        visitor.visit(statement)
    return tuple(nodes)


def _literal_mapping_values(tree: ast.Module) -> dict[str, object]:
    values: dict[str, object] = {}
    assignments: dict[str, int] = {}
    for statement in tree.body:
        name: str | None = None
        value: ast.AST | None = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            name = statement.target.id
            value = statement.value
        if name is None or value is None:
            continue
        assignments[name] = assignments.get(name, 0) + 1
        try:
            literal = ast.literal_eval(value)
        except (TypeError, ValueError):
            continue
        if isinstance(literal, Mapping):
            values[name] = literal
    candidates = {
        name: value
        for name, value in values.items()
        if assignments.get(name) == 1
    }
    store_counts = {
        name: sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, (ast.Store, ast.Del))
        )
        for name in candidates
    }
    mutated: set[str] = set()
    mutating_methods = {
        "__delitem__",
        "__ior__",
        "__setitem__",
        "clear",
        "pop",
        "popitem",
        "setdefault",
        "update",
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in candidates
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            mutated.add(node.value.id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in candidates
            and node.func.attr in mutating_methods
        ):
            mutated.add(node.func.value.id)
    return {
        name: value
        for name, value in candidates.items()
        if store_counts.get(name) == 1 and name not in mutated
    }


def _mapping_strings(value: object) -> tuple[str, ...]:
    strings: list[str] = []

    def collect(item: object) -> None:
        if type(item) is str:
            strings.append(item)
        elif isinstance(item, Mapping):
            for child in item.values():
                collect(child)
        elif type(item) in {tuple, list, set, frozenset}:
            for child in item:
                collect(child)

    collect(value)
    return tuple(strings)


def _scope_nodes(scope: ast.AST) -> tuple[ast.AST, ...]:
    nodes: list[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def generic_visit(self, node: ast.AST) -> None:
            nodes.append(node)
            super().generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is scope:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is scope:
                self.generic_visit(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            if node is scope:
                self.generic_visit(node)

    if isinstance(scope, ast.Module):
        for statement in scope.body:
            if not isinstance(
                statement,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
            ):
                _Visitor().visit(statement)
    else:
        _Visitor().visit(scope)
    return tuple(nodes)


def _assigned_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(
            name
            for child in target.elts
            for name in _assigned_names(child)
        )
    return ()


def _expression_sources(
    expression: ast.AST,
    *,
    mapping_names: frozenset[str],
) -> tuple[frozenset[str], frozenset[str]]:
    maps: set[str] = set()
    names: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript) -> None:
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in mapping_names
            ):
                maps.add(node.value.id)
                return
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id in mapping_names
                and function.attr in {"get", "__getitem__"}
            ):
                maps.add(function.value.id)
                return
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if (
                isinstance(node.ctx, ast.Load)
                and node.id not in {"__name__", "__package__"}
            ):
                names.add(node.id)

    _Visitor().visit(expression)
    return frozenset(maps), frozenset(names)


def _dynamic_target_mapping_names(
    expression: ast.AST,
    *,
    call: ast.Call,
    tree: ast.Module,
    parents: Mapping[ast.AST, ast.AST],
    mapping_names: frozenset[str],
) -> frozenset[str]:
    current: ast.AST | None = call
    while current is not None and not isinstance(
        current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    ):
        current = parents.get(current)
    scope = tree if current is None else current
    assignments: dict[str, list[ast.AST]] = {}
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Assign):
            targets = tuple(
                name
                for target in node.targets
                for name in _assigned_names(target)
            )
            for name in targets:
                assignments.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for name in _assigned_names(node.target):
                assignments.setdefault(name, []).append(node.value)
        elif isinstance(node, ast.NamedExpr):
            for name in _assigned_names(node.target):
                assignments.setdefault(name, []).append(node.value)

    sealed_maps: set[str] = set()
    direct_maps, frontier = _expression_sources(
        expression,
        mapping_names=mapping_names,
    )
    sealed_maps.update(direct_maps)
    pending = list(frontier)
    visited: set[str] = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        values = assignments.get(name, [])
        if len(values) != 1:
            return frozenset()
        direct_maps, source_names = _expression_sources(
            values[0],
            mapping_names=mapping_names,
        )
        sealed_maps.update(direct_maps)
        pending.extend(source_names - visited)
    return frozenset(sealed_maps)


def _static_string(
    expression: ast.AST,
    *,
    module_name: str,
    package_name: str,
) -> str | None:
    if isinstance(expression, ast.Constant) and type(expression.value) is str:
        return expression.value
    if isinstance(expression, ast.Name):
        if expression.id == "__name__":
            return module_name
        if expression.id == "__package__":
            return package_name
        return None
    if not isinstance(expression, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in expression.values:
        if isinstance(value, ast.Constant) and type(value.value) is str:
            parts.append(value.value)
        elif (
            isinstance(value, ast.FormattedValue)
            and isinstance(value.value, ast.Name)
            and value.value.id in {"__name__", "__package__"}
            and value.conversion == -1
            and value.format_spec is None
        ):
            parts.append(
                module_name
                if value.value.id == "__name__"
                else package_name
            )
        else:
            return None
    return "".join(parts)


def _relative_dynamic_target(
    target: str,
    *,
    call: ast.Call,
    module_name: str,
    package_name: str,
    import_module_names: frozenset[str],
    importlib_names: frozenset[str],
) -> str:
    function = call.func
    is_import_module = (
        isinstance(function, ast.Name)
        and function.id in import_module_names
    ) or (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id in importlib_names
        and function.attr == "import_module"
    )
    if not is_import_module:
        raise SemanticDependencyError(
            "semantic dependency relative dynamic import is not sealed"
        )
    package_expression: ast.AST | None = (
        call.args[1] if len(call.args) >= 2 else None
    )
    for keyword in call.keywords:
        if keyword.arg == "package":
            if package_expression is not None:
                raise SemanticDependencyError(
                    "semantic dependency dynamic import package is ambiguous"
                )
            package_expression = keyword.value
    if package_expression is None:
        raise SemanticDependencyError(
            "semantic dependency relative dynamic import package is absent"
        )
    sealed_package = _static_string(
        package_expression,
        module_name=module_name,
        package_name=package_name,
    )
    if sealed_package is None:
        raise SemanticDependencyError(
            "semantic dependency relative dynamic import package is not sealed"
        )
    level = len(target) - len(target.lstrip("."))
    absolute = _absolute_import_name(
        module=target[level:] or None,
        level=level,
        package=sealed_package,
    )
    if not absolute:
        raise SemanticDependencyError(
            "semantic dependency relative dynamic import escapes its package"
        )
    return absolute


def _uses_current_module_prefix(expression: ast.AST) -> bool:
    return isinstance(expression, ast.JoinedStr) and any(
        isinstance(value, ast.FormattedValue)
        and isinstance(value.value, ast.Name)
        and value.value.id == "__name__"
        for value in expression.values
    )


def _dynamic_call_kind(
    call: ast.Call,
    *,
    import_module_names: frozenset[str],
    importlib_names: frozenset[str],
    runpy_names: frozenset[str],
    runpy_function_names: frozenset[str],
) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        if function.id in import_module_names or function.id == "__import__":
            return "module"
        if function.id in {"exec", "eval"} or function.id in runpy_function_names:
            return "code"
    if isinstance(function, ast.Attribute) and isinstance(
        function.value, ast.Name
    ):
        if function.value.id in importlib_names and function.attr == "import_module":
            return "module"
        if function.value.id in runpy_names and function.attr in {
            "run_module",
            "run_path",
        }:
            return "code"
    return None


def _reject_dynamic_indirection(
    *,
    nodes: tuple[ast.AST, ...],
    parents: Mapping[ast.AST, ast.AST],
    import_module_names: frozenset[str],
    importlib_names: frozenset[str],
    runpy_names: frozenset[str],
    runpy_function_names: frozenset[str],
) -> None:
    direct_names = import_module_names.union(
        runpy_function_names,
        {"__import__", "exec", "eval"},
    )
    for node in nodes:
        parent = parents.get(node)
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in direct_names
            and not (isinstance(parent, ast.Call) and parent.func is node)
        ):
            raise SemanticDependencyError(
                "semantic dependency uses unsealed dynamic import indirection"
            )
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and (
                (
                    node.value.id in importlib_names
                    and node.attr == "import_module"
                )
                or (
                    node.value.id in runpy_names
                    and node.attr in {"run_module", "run_path"}
                )
            )
            and not (isinstance(parent, ast.Call) and parent.func is node)
        ):
            raise SemanticDependencyError(
                "semantic dependency uses unsealed dynamic import indirection"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and isinstance(node.args[1], ast.Constant)
            and type(node.args[1].value) is str
            and (
                (
                    node.args[0].id in importlib_names
                    and node.args[1].value == "import_module"
                )
                or (
                    node.args[0].id in runpy_names
                    and node.args[1].value in {"run_module", "run_path"}
                )
            )
        ):
            raise SemanticDependencyError(
                "semantic dependency uses unsealed dynamic import indirection"
            )


def _analyze_imports(
    *,
    path: Path,
    content: bytes,
    digest: str,
) -> _ImportAnalysis:
    with _CACHE_LOCK:
        cached = _IMPORT_ANALYSIS_CACHE.get((path, digest))
    if cached is not None:
        return cached
    context = _module_context(path)
    if context is None:
        raise SemanticDependencyError(
            "project semantic dependency has no importable module identity"
        )
    module_name, package, _is_package = context
    try:
        tree = ast.parse(content, filename=str(path))
    except (SyntaxError, TypeError, ValueError) as exc:
        raise SemanticDependencyError(
            "project semantic dependency source cannot be parsed"
        ) from exc
    nodes = _without_type_checking(tree)
    static_modules: set[str] = set()
    import_module_names: set[str] = set()
    importlib_names: set[str] = set()
    runpy_names: set[str] = set()
    runpy_function_names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                static_modules.add(alias.name)
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
                elif alias.name == "runpy":
                    runpy_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_import_name(
                module=node.module,
                level=node.level,
                package=package,
            )
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_names.add(alias.asname or alias.name)
            elif node.module == "runpy":
                for alias in node.names:
                    if alias.name in {"run_module", "run_path"}:
                        runpy_function_names.add(alias.asname or alias.name)
            if not base and node.level:
                raise SemanticDependencyError(
                    "semantic dependency relative import escapes its package"
                )
            if not base:
                continue
            static_modules.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}"
                if _module_target(candidate) is not None:
                    static_modules.add(candidate)

    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    _reject_dynamic_indirection(
        nodes=nodes,
        parents=parents,
        import_module_names=frozenset(import_module_names),
        importlib_names=frozenset(importlib_names),
        runpy_names=frozenset(runpy_names),
        runpy_function_names=frozenset(runpy_function_names),
    )
    literal_mappings = _literal_mapping_values(tree)
    mapping_names = frozenset(literal_mappings)
    dynamic_modules: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        kind = _dynamic_call_kind(
            node,
            import_module_names=frozenset(import_module_names),
            importlib_names=frozenset(importlib_names),
            runpy_names=frozenset(runpy_names),
            runpy_function_names=frozenset(runpy_function_names),
        )
        if kind is None:
            continue
        if kind == "code":
            raise SemanticDependencyError(
                "semantic dependency uses unsealed dynamic code execution"
            )
        if not node.args:
            raise SemanticDependencyError(
                "semantic dependency dynamic import target is absent"
            )
        raw_target = _static_string(
            node.args[0],
            module_name=module_name,
            package_name=package,
        )
        if raw_target is not None:
            relative_target = raw_target.startswith(".")
            target = raw_target
            if relative_target:
                target = _relative_dynamic_target(
                    target,
                    call=node,
                    module_name=module_name,
                    package_name=package,
                    import_module_names=frozenset(import_module_names),
                    importlib_names=frozenset(importlib_names),
                )
            resolved_target = _module_target(target)
            if resolved_target is not None:
                dynamic_modules.add(target)
            elif relative_target:
                raise SemanticDependencyError(
                    "semantic dependency names an absent relative dynamic import"
                )
            elif target == "axiom_rift" or target.startswith("axiom_rift."):
                raise SemanticDependencyError(
                    "semantic dependency names an absent project dynamic import"
                )
            continue
        referenced_mappings = _dynamic_target_mapping_names(
            node.args[0],
            call=node,
            tree=tree,
            parents=parents,
            mapping_names=mapping_names,
        )
        candidates: set[str] = set()
        current_module_prefix = _uses_current_module_prefix(node.args[0])
        for name in referenced_mappings:
            for value in _mapping_strings(literal_mappings[name]):
                absolute_target = _module_target(value)
                if absolute_target is not None:
                    candidates.add(value)
                elif value == "axiom_rift" or value.startswith("axiom_rift."):
                    raise SemanticDependencyError(
                        "semantic dependency routing table names an absent "
                        "project module"
                    )
                if current_module_prefix:
                    relative = f"{module_name}.{value}"
                    relative_target = _module_target(relative)
                    if relative_target is not None:
                        candidates.add(relative)
                    else:
                        raise SemanticDependencyError(
                            "semantic dependency routing table has an unsealed "
                            "relative module"
                        )
        if not candidates:
            raise SemanticDependencyError(
                "semantic dependency dynamic import target is not statically "
                "classified"
            )
        dynamic_modules.update(candidates)

    analysis = _ImportAnalysis(
        static_modules=tuple(sorted(static_modules)),
        dynamic_modules=tuple(sorted(dynamic_modules)),
    )
    with _CACHE_LOCK:
        stale = tuple(
            key
            for key in _IMPORT_ANALYSIS_CACHE
            if key[0] == path and key != (path, digest)
        )
        for key in stale:
            _IMPORT_ANALYSIS_CACHE.pop(key, None)
        _IMPORT_ANALYSIS_CACHE[(path, digest)] = analysis
    return analysis


def _discover_once(
    roots: tuple[Path, ...],
    *,
    boundary_paths: frozenset[Path],
) -> tuple[SemanticDependency, ...]:
    pending = list(roots)
    for root in roots:
        context = _module_context(root)
        if context is None:
            continue
        resolution = _module_resolution(context[0])
        if resolution is None or resolution.target != root:
            raise SemanticDependencyError(
                "project semantic root has no unique module resolution"
            )
        pending.extend(
            dependency
            for dependency in resolution.dependency_paths
            if dependency not in boundary_paths
        )
    observed: dict[Path, SemanticDependency] = {}
    while pending:
        path = pending.pop()
        if path in observed or path in boundary_paths:
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise SemanticDependencyError(
                "semantic dependency file is absent"
            ) from exc
        digest = sha256(content).hexdigest()
        project_path = _project_relative(path)
        observed[path] = SemanticDependency(
            path=path,
            project_path=project_path,
            sha256=digest,
        )
        if project_path is None or path.suffix != ".py":
            continue
        analysis = _analyze_imports(path=path, content=content, digest=digest)
        for module in (*analysis.static_modules, *analysis.dynamic_modules):
            resolution = _module_resolution(module)
            if resolution is None and (
                module == "axiom_rift" or module.startswith("axiom_rift.")
            ):
                raise SemanticDependencyError(
                    "semantic dependency names an absent project import"
                )
            if resolution is not None:
                for dependency in resolution.dependency_paths:
                    if (
                        dependency not in observed
                        and dependency not in boundary_paths
                    ):
                        pending.append(dependency)
    return tuple(
        sorted(
            observed.values(),
            key=lambda item: (
                item.project_path is None,
                "" if item.project_path is None else item.project_path,
                item.path.as_posix(),
            ),
        )
    )


def semantic_dependency_binding(
    dependency_paths: tuple[str | Path, ...],
    *,
    boundary_paths: tuple[str | Path, ...] = (),
) -> tuple[SemanticDependency, ...]:
    """Return a stable authored semantic closure or fail closed."""

    roots = tuple(
        _regular_file(Path(value), label="validator semantic dependency")
        for value in dependency_paths
    )
    if len(set(roots)) != len(roots):
        raise SemanticDependencyError(
            "validator semantic dependency paths must be unique"
        )
    boundaries = frozenset(
        _regular_file(Path(value), label="semantic dependency boundary")
        for value in boundary_paths
    )
    if boundaries.intersection(roots):
        raise SemanticDependencyError(
            "semantic dependency roots and boundaries must be disjoint"
        )
    if not roots:
        return ()
    for _attempt in range(2):
        inventory_digest = _project_python_inventory_fingerprint()
        cache_key = (roots, boundaries, inventory_digest)
        with _CACHE_LOCK:
            cached = _SEMANTIC_CLOSURE_CACHE.get(cache_key)
        if cached is not None:
            try:
                current = tuple(
                    SemanticDependency(
                        path=item.path,
                        project_path=_project_relative(item.path),
                        sha256=sha256(item.path.read_bytes()).hexdigest(),
                    )
                    for item in cached
                )
            except OSError:
                current = ()
            if current == cached:
                return cached
            with _CACHE_LOCK:
                if _SEMANTIC_CLOSURE_CACHE.get(cache_key) is cached:
                    _SEMANTIC_CLOSURE_CACHE.pop(cache_key, None)
        first = _discover_once(roots, boundary_paths=boundaries)
        second = _discover_once(roots, boundary_paths=boundaries)
        if first != second:
            continue
        if _project_python_inventory_fingerprint() != inventory_digest:
            continue
        with _CACHE_LOCK:
            stale = tuple(
                key
                for key in _SEMANTIC_CLOSURE_CACHE
                if key[:2] == cache_key[:2] and key != cache_key
            )
            for key in stale:
                _SEMANTIC_CLOSURE_CACHE.pop(key, None)
            _SEMANTIC_CLOSURE_CACHE[cache_key] = second
        return second
    raise SemanticDependencyError(
        "semantic dependency graph changed during identity construction"
    )


__all__ = [
    "SemanticDependency",
    "SemanticDependencyError",
    "semantic_dependency_binding",
]
