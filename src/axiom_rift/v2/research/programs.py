"""Static, hash-verified program identities for the canonical V2 scout engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from axiom_rift.v2.identity import sha256_payload


DEFAULT_PROGRAM_REGISTRY_PATH = Path("configs/v2/program_registry.yaml")
CANONICAL_ENGINE = {
    "engine_key": "nested_causal_scout_v2",
    "feature_path": "src/axiom_rift/v2/features.py",
    "scout_path": "src/axiom_rift/v2/research/scout.py",
    "evaluation_path": "src/axiom_rift/v2/research/evaluation.py",
    "sensitivity_path": "src/axiom_rift/v2/research/sensitivity.py",
}
FIXTURE_ONLY = {"research_core_path": "src/axiom_rift/v2/research/core.py"}
PROGRAM_KINDS = ("feature", "label", "model", "calibration", "selector", "trade")
PROGRAM_ID_PATTERNS = {
    "feature": re.compile(r"^V2FP[0-9]{4}$"),
    "label": re.compile(r"^V2LP[0-9]{4}$"),
    "model": re.compile(r"^V2MP[0-9]{4}$"),
    "calibration": re.compile(r"^V2CP[0-9]{4}$"),
    "selector": re.compile(r"^V2SEL[0-9]{4}$"),
    "trade": re.compile(r"^V2TP[0-9]{4}$"),
}
IMPLEMENTATION_KEYS = {
    "feature": frozenset({"canonical_completed_bar_features_v1"}),
    "label": frozenset({"normalized_forward_open_return_v1"}),
    "model": frozenset({"train_scaled_ridge_v1"}),
    "calibration": frozenset({"validation_absolute_residual_quantile_v1"}),
    "selector": frozenset({"sequential_cost_abstention_v1"}),
    "trade": frozenset({"fixed_horizon_observed_spread_v1"}),
}


class ProgramRegistryError(ValueError):
    """Raised when a static program identity or its contract cannot be trusted."""


def _contract_sha256(path: Path) -> str:
    try:
        payload = yaml.safe_load(path.read_text(encoding="ascii"))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ProgramRegistryError(f"program contract is not valid ASCII YAML: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ProgramRegistryError(f"program contract must be a mapping: {path}")
    return sha256_payload(payload)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _relative_file(project_root: Path, raw_path: object, *, label: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ProgramRegistryError(f"{label} must be a non-empty repo-relative POSIX path")
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise ProgramRegistryError(f"{label} must stay inside the project root")
    resolved = (project_root / path).resolve()
    if project_root not in resolved.parents or not resolved.is_file():
        raise ProgramRegistryError(f"{label} is missing or outside the project root: {raw_path}")
    return path.as_posix(), resolved


@dataclass(frozen=True)
class ProgramDefinition:
    program_id: str
    kind: str
    version: int
    contract_path: str
    contract_sha256: str
    implementation_key: str
    parameters: dict[str, Any]
    program_sha256: str

    def identity_payload(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "kind": self.kind,
            "version": self.version,
            "contract_path": self.contract_path,
            "contract_sha256": self.contract_sha256,
            "implementation_key": self.implementation_key,
            "parameters": self.parameters,
        }

    def receipt_identity(self) -> dict[str, Any]:
        return {
            "id": self.program_id,
            "kind": self.kind,
            "version": self.version,
            "contract_path": self.contract_path,
            "contract_sha256": self.contract_sha256,
            "implementation_key": self.implementation_key,
            "program_sha256": self.program_sha256,
        }


@dataclass(frozen=True)
class ProgramRegistry:
    project_root: Path
    path: Path
    relative_path: str
    registry_sha256: str
    programs: dict[str, ProgramDefinition]

    def resolve(self, program_id: str, *, kind: str) -> ProgramDefinition:
        if kind not in PROGRAM_KINDS:
            raise ProgramRegistryError(f"unknown program kind: {kind}")
        definition = self.programs.get(program_id)
        if definition is None:
            raise ProgramRegistryError(f"program is not registered: {kind}={program_id}")
        if definition.kind != kind:
            raise ProgramRegistryError(
                f"program kind mismatch: {program_id} is {definition.kind}, expected {kind}"
            )
        return definition

    def resolve_section(self, kind: str, section: Mapping[str, Any]) -> ProgramDefinition:
        program_id = section.get("id")
        if not isinstance(program_id, str):
            raise ProgramRegistryError(f"missing program id for kind: {kind}")
        definition = self.resolve(program_id, kind=kind)
        expected = {"id": program_id, **definition.parameters}
        observed = dict(section)
        if observed != expected:
            raise ProgramRegistryError(
                f"program parameters differ from registered identity: {kind}={program_id}"
            )
        return definition


def _load_definition(
    project_root: Path,
    program_id: str,
    payload: Mapping[str, Any],
) -> ProgramDefinition:
    required = {
        "kind",
        "version",
        "contract_path",
        "contract_sha256",
        "implementation_key",
        "parameters",
        "program_sha256",
    }
    if set(payload) != required:
        raise ProgramRegistryError(f"program registry fields mismatch: {program_id}")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in PROGRAM_KINDS:
        raise ProgramRegistryError(f"invalid program kind: {program_id}")
    if PROGRAM_ID_PATTERNS[kind].fullmatch(program_id) is None:
        raise ProgramRegistryError(f"program id does not match kind: {program_id}")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ProgramRegistryError(f"invalid program version: {program_id}")
    implementation_key = payload.get("implementation_key")
    if implementation_key not in IMPLEMENTATION_KEYS[kind]:
        raise ProgramRegistryError(
            f"implementation key is not statically supported: {kind}={implementation_key}"
        )
    contract_path, resolved_contract = _relative_file(
        project_root, payload.get("contract_path"), label=f"{program_id}.contract_path"
    )
    contract_sha256 = payload.get("contract_sha256")
    if not _is_sha256(contract_sha256) or _contract_sha256(resolved_contract) != contract_sha256:
        raise ProgramRegistryError(f"program contract hash mismatch: {program_id}")
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ProgramRegistryError(f"program parameters must be a mapping: {program_id}")
    if "id" in parameters:
        raise ProgramRegistryError(f"program parameters may not override id: {program_id}")
    program_sha256 = payload.get("program_sha256")
    if not _is_sha256(program_sha256):
        raise ProgramRegistryError(f"invalid program hash: {program_id}")
    definition = ProgramDefinition(
        program_id=program_id,
        kind=kind,
        version=version,
        contract_path=contract_path,
        contract_sha256=contract_sha256,
        implementation_key=str(implementation_key),
        parameters=dict(parameters),
        program_sha256=program_sha256,
    )
    if sha256_payload(definition.identity_payload()) != program_sha256:
        raise ProgramRegistryError(f"program identity hash mismatch: {program_id}")
    return definition


def load_program_registry(
    project_root: Path,
    registry_path: Path | None = None,
) -> ProgramRegistry:
    """Load the static registry and verify every program contract and identity hash."""

    root = project_root.resolve()
    candidate = registry_path or DEFAULT_PROGRAM_REGISTRY_PATH
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if root not in path.parents or not path.is_file():
        raise ProgramRegistryError("program registry is missing or outside the project root")
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
        payload = yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ProgramRegistryError(f"program registry is not valid ASCII YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProgramRegistryError("program registry must be a mapping")
    expected_fields = {
        "schema",
        "status",
        "encoding",
        "hash_semantics",
        "canonical_engine",
        "fixture_only",
        "programs",
    }
    if set(payload) != expected_fields:
        raise ProgramRegistryError("program registry top-level fields mismatch")
    if payload.get("schema") != "axiom_rift_v2_program_registry_v1":
        raise ProgramRegistryError("program registry schema mismatch")
    if payload.get("status") != "active" or payload.get("encoding") != "ascii_only":
        raise ProgramRegistryError("program registry is not active ASCII truth")
    if payload.get("hash_semantics") != "compact_sorted_ascii_json_sha256":
        raise ProgramRegistryError("program registry hash semantics mismatch")
    if payload.get("canonical_engine") != CANONICAL_ENGINE:
        raise ProgramRegistryError("canonical research engine declaration mismatch")
    if payload.get("fixture_only") != FIXTURE_ONLY:
        raise ProgramRegistryError("fixture-only research declaration mismatch")
    for raw_path in (*CANONICAL_ENGINE.values(), *FIXTURE_ONLY.values()):
        if raw_path.endswith(".py"):
            _relative_file(root, raw_path, label="research implementation path")
    rows = payload.get("programs")
    if not isinstance(rows, Mapping) or not rows:
        raise ProgramRegistryError("program registry contains no programs")
    programs: dict[str, ProgramDefinition] = {}
    for raw_program_id, body in rows.items():
        if not isinstance(raw_program_id, str) or not isinstance(body, Mapping):
            raise ProgramRegistryError("program registry entries must be mappings keyed by id")
        programs[raw_program_id] = _load_definition(root, raw_program_id, body)
    if {definition.kind for definition in programs.values()} != set(PROGRAM_KINDS):
        raise ProgramRegistryError("program registry must cover every canonical scout program kind")
    return ProgramRegistry(
        project_root=root,
        path=path,
        relative_path=path.relative_to(root).as_posix(),
        registry_sha256=sha256_payload(payload),
        programs=programs,
    )
