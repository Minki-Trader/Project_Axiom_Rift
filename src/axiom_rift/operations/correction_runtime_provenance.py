"""Seal the interpreter and PyYAML bytes used by a correction runner."""

from __future__ import annotations

import base64
import importlib.metadata
from pathlib import Path
import platform
import sys
from typing import Any

from hashlib import sha256


class CorrectionRuntimeProvenanceError(RuntimeError):
    """The current correction interpreter boundary is not reproducible."""


def capture_correction_runtime_provenance(
    *,
    safe_startup: bool,
    private_bytecode_cache_root: str | Path | None,
) -> dict[str, Any]:
    """Bind Python plus every executable PyYAML RECORD member and import."""

    try:
        executable = Path(sys.executable).resolve(strict=True)
        executable_bytes = executable.read_bytes()
        distribution = importlib.metadata.distribution("PyYAML")
        distribution_root = Path(distribution.locate_file("")).resolve(strict=True)
        files = tuple(distribution.files or ())
        record_entries = tuple(
            item
            for item in files
            if item.as_posix().casefold().endswith(".dist-info/record")
        )
        if len(record_entries) != 1:
            raise ValueError("PyYAML RECORD inventory is ambiguous")
        record_path = Path(
            distribution.locate_file(record_entries[0])
        ).resolve(strict=True)
        record_bytes = record_path.read_bytes()
        executable_suffixes = {".dll", ".py", ".pyd", ".so"}
        execution_inventory: list[dict[str, str]] = []
        for entry in sorted(files, key=lambda item: item.as_posix()):
            relative = entry.as_posix()
            if (
                Path(relative).suffix.casefold() not in executable_suffixes
                or not (
                    relative.startswith("yaml/")
                    or relative.startswith("_yaml/")
                    or Path(relative).name.casefold().startswith("_yaml")
                )
            ):
                continue
            if entry.hash is None or entry.hash.mode != "sha256":
                raise ValueError("PyYAML executable lacks a RECORD SHA-256")
            source = Path(distribution.locate_file(entry))
            resolved = source.resolve(strict=True)
            resolved.relative_to(distribution_root)
            if source.is_symlink() or not resolved.is_file():
                raise ValueError("PyYAML executable is link-like or unavailable")
            content_hash = sha256(resolved.read_bytes()).hexdigest()
            record_hash = base64.urlsafe_b64decode(
                entry.hash.value + "=" * (-len(entry.hash.value) % 4)
            ).hex()
            if content_hash != record_hash:
                raise ValueError("PyYAML executable differs from RECORD")
            execution_inventory.append(
                {"path": relative, "sha256": content_hash}
            )
        if not execution_inventory:
            raise ValueError("PyYAML executable inventory is empty")
        execution_by_path = {
            item["path"]: item["sha256"] for item in execution_inventory
        }
        loaded_inventory: list[dict[str, str]] = []
        for module_name, module in sorted(sys.modules.items()):
            if not (
                module_name == "yaml"
                or module_name.startswith("yaml.")
                or module_name == "_yaml"
                or module_name.startswith("_yaml.")
            ):
                continue
            module_file = getattr(module, "__file__", None)
            if type(module_file) is not str:
                continue
            resolved = Path(module_file).resolve(strict=True)
            relative = resolved.relative_to(distribution_root).as_posix()
            expected = execution_by_path.get(relative)
            if expected is None or sha256(resolved.read_bytes()).hexdigest() != expected:
                raise ValueError("loaded PyYAML module is outside sealed RECORD")
            loaded_inventory.append({"path": relative, "sha256": expected})
        loaded_inventory = [
            {"path": path, "sha256": digest}
            for path, digest in sorted(
                {(item["path"], item["sha256"]) for item in loaded_inventory}
            )
        ]
        if not loaded_inventory:
            raise ValueError("loaded PyYAML module inventory is empty")
        private_root = (
            None
            if private_bytecode_cache_root is None
            else Path(private_bytecode_cache_root).resolve(strict=True)
        )
        current_prefix = (
            None
            if sys.pycache_prefix is None
            else Path(sys.pycache_prefix).resolve(strict=True)
        )
        private_policy = (
            safe_startup
            and private_root is not None
            and current_prefix is not None
            and current_prefix.is_relative_to(private_root)
            and sys.dont_write_bytecode
        )
        if safe_startup and not private_policy:
            raise ValueError("isolated correction bytecode policy drifted")
        if safe_startup and any(
            name in sys.modules for name in ("sitecustomize", "usercustomize")
        ):
            raise ValueError("automatic startup module was loaded")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise CorrectionRuntimeProvenanceError(
            "current Python and PyYAML provenance cannot be sealed"
        ) from exc
    return {
        "python": {
            "bytecode_cache_policy": (
                "private_external_prefix"
                if private_policy
                else "ambient_read_only_planning"
            ),
            "dont_write_bytecode": sys.dont_write_bytecode,
            "executable": executable.as_posix(),
            "executable_sha256": sha256(executable_bytes).hexdigest(),
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "pyyaml": {
            "distribution": distribution.metadata["Name"],
            "execution_files": execution_inventory,
            "loaded_execution_files": loaded_inventory,
            "record_path": record_path.relative_to(distribution_root).as_posix(),
            "record_sha256": sha256(record_bytes).hexdigest(),
            "version": distribution.version,
        },
        "schema": "correction_runtime_provenance.v1",
    }


__all__ = [
    "CorrectionRuntimeProvenanceError",
    "capture_correction_runtime_provenance",
]
