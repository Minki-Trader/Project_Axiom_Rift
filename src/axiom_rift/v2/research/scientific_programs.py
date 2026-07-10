"""Read-only scientific program identities for the active V2 epoch.

The loader in this module only verifies repo-local declarations.  It neither
imports adapters nor mutates operational state, and bundle construction is a
pure resolution of already verified program identities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

import yaml

from axiom_rift.v2.identity import IdentityError, sha256_payload
from axiom_rift.v2.research.dispatch import PROGRAM_ID_PATTERNS, PROGRAM_KINDS


DEFAULT_SCIENTIFIC_PROGRAM_REGISTRY_PATH = Path(
    "configs/v2/scientific/program_registry.yaml"
)
SCIENTIFIC_REGISTRY_SCHEMA = "axiom_rift_v2_scientific_program_registry_v1"
SCIENTIFIC_ORIGIN = "v2_current"
REUSE_DECISIONS = frozenset(
    {
        "new_scientific_component",
        "engine_primitive_reuse_without_evidence",
    }
)
SCIENTIFIC_BUNDLE_ROLES = (
    "continuation_low",
    "continuation_base",
    "continuation_high",
    "failed_break_reversal",
    "compression_ablation",
)
SCIENTIFIC_RUNTIME_PATHS = (
    "src/axiom_rift/v2/research/compression_release.py",
    "src/axiom_rift/v2/research/scientific_scout.py",
)
SCIENTIFIC_RUNTIME_SCHEMA = "axiom_rift_v2_scientific_runtime_manifest_v1"

_IMPLEMENTATION_KEYS = {
    "feature": frozenset({"compression_release_features_v1"}),
    "label": frozenset({"forward_open_return_6bar_v1"}),
    "model": frozenset({"deterministic_event_score_v1"}),
    "calibration": frozenset({"identity_event_calibration_v1"}),
    "selector": frozenset(
        {
            "chronological_compression_selector_v1",
            "chronological_compression_cost_gated_selector_v1",
        }
    ),
    "trade": frozenset(
        {
            "fixed_6bar_observed_spread_v1",
            "fixed_6bar_causal_spread_floor_v1",
        }
    ),
    "sizing": frozenset({"fixed_lot_v1"}),
    "portfolio_risk": frozenset({"one_position_safety_v1"}),
}
if set(_IMPLEMENTATION_KEYS) != set(PROGRAM_KINDS):  # pragma: no cover - import guard
    raise RuntimeError("scientific implementation allowlist does not cover dispatch kinds")
SCIENTIFIC_IMPLEMENTATION_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    _IMPLEMENTATION_KEYS
)
# Explicit aliases make the security boundary easy to discover without
# duplicating or widening it.
SAFE_IMPLEMENTATION_KEYS = SCIENTIFIC_IMPLEMENTATION_KEYS
IMPLEMENTATION_KEY_ALLOWLIST = SCIENTIFIC_IMPLEMENTATION_KEYS
BUNDLE_ROLE_NAMES = SCIENTIFIC_BUNDLE_ROLES


class ScientificProgramRegistryError(ValueError):
    """Raised when a scientific registry, program, or bundle is untrusted."""


ScientificProgramError = ScientificProgramRegistryError


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical_sha256(payload: Any, *, label: str) -> str:
    try:
        return sha256_payload(payload)
    except IdentityError as exc:
        raise ScientificProgramRegistryError(
            f"{label} is not canonical JSON-compatible data"
        ) from exc


def _read_ascii_yaml_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        text = path.read_bytes().decode("ascii")
        payload = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ScientificProgramRegistryError(
            f"{label} is not valid ASCII YAML: {path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ScientificProgramRegistryError(f"{label} must be a mapping: {path}")
    return payload


def _repo_file(project_root: Path, raw_path: object, *, label: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ScientificProgramRegistryError(
            f"{label} must be a non-empty repo-relative POSIX path"
        )
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ScientificProgramRegistryError(f"{label} must stay inside the project root")
    resolved = (project_root / candidate).resolve()
    if project_root not in resolved.parents or not resolved.is_file():
        raise ScientificProgramRegistryError(
            f"{label} is missing or outside the project root: {raw_path}"
        )
    return candidate.as_posix(), resolved


def _registry_file(project_root: Path, registry_path: Path) -> tuple[str, Path]:
    resolved = (
        registry_path.resolve()
        if registry_path.is_absolute()
        else (project_root / registry_path).resolve()
    )
    if project_root not in resolved.parents or not resolved.is_file():
        raise ScientificProgramRegistryError(
            "scientific program registry is missing or outside the project root"
        )
    return resolved.relative_to(project_root).as_posix(), resolved


@dataclass(frozen=True)
class ScientificProgramDefinition:
    """One hash-bound executable declaration from the scientific registry."""

    program_id: str
    kind: str
    version: int
    contract_path: str
    contract_sha256: str
    implementation_key: str
    runtime_sha256: str
    parameters: Mapping[str, Any]
    fixture_only: bool
    reuse_decision: str
    program_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "kind": self.kind,
            "version": self.version,
            "contract_path": self.contract_path,
            "contract_sha256": self.contract_sha256,
            "implementation_key": self.implementation_key,
            "runtime_sha256": self.runtime_sha256,
            "parameters": dict(self.parameters),
            "fixture_only": self.fixture_only,
            "reuse_decision": self.reuse_decision,
        }

    def executable_payload(self) -> dict[str, Any]:
        """Return executable identity without its renameable registry id."""

        payload = self.identity_payload()
        payload.pop("program_id")
        return payload

    @property
    def executable_sha256(self) -> str:
        return sha256_payload(self.executable_payload())

    def receipt_identity(self) -> dict[str, Any]:
        return {
            "id": self.program_id,
            "kind": self.kind,
            "version": self.version,
            "contract_path": self.contract_path,
            "contract_sha256": self.contract_sha256,
            "implementation_key": self.implementation_key,
            "runtime_sha256": self.runtime_sha256,
            "fixture_only": self.fixture_only,
            "reuse_decision": self.reuse_decision,
            "program_sha256": self.program_sha256,
        }


# The short alias mirrors the older fixture registry while keeping imports from
# this module unambiguous.
ProgramDefinition = ScientificProgramDefinition


@dataclass(frozen=True)
class ScientificProgramBundle:
    """A complete eight-program scientific executable identity."""

    programs: Mapping[str, ScientificProgramDefinition]
    external_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if set(self.programs) != set(PROGRAM_KINDS):
            raise ScientificProgramRegistryError(
                "scientific bundle must contain all eight program kinds"
            )
        normalized: dict[str, ScientificProgramDefinition] = {}
        for kind in PROGRAM_KINDS:
            definition = self.programs[kind]
            if (
                not isinstance(definition, ScientificProgramDefinition)
                or definition.kind != kind
            ):
                raise ScientificProgramRegistryError(
                    f"scientific bundle kind mismatch: {kind}"
                )
            if definition.fixture_only:
                raise ScientificProgramRegistryError(
                    "fixture-only programs cannot enter a scientific bundle"
                )
            normalized[kind] = definition
        sources = tuple(self.external_source_ids)
        if sources:
            raise ScientificProgramRegistryError(
                "scientific program bundles may not declare external sources"
            )
        object.__setattr__(self, "programs", MappingProxyType(normalized))
        object.__setattr__(self, "external_source_ids", ())

    @property
    def program_ids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {kind: self.programs[kind].program_id for kind in PROGRAM_KINDS}
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scientific_program_bundle_v1",
            "scientific_origin": SCIENTIFIC_ORIGIN,
            "programs": {
                kind: {
                    "program_id": self.programs[kind].program_id,
                    "program_sha256": self.programs[kind].program_sha256,
                }
                for kind in PROGRAM_KINDS
            },
            "external_source_ids": [],
        }

    def to_payload(self) -> dict[str, Any]:
        return self.identity_payload()

    @property
    def bundle_sha256(self) -> str:
        return sha256_payload(self.identity_payload())


@dataclass(frozen=True)
class ScientificBundleBatch:
    """Three to five named, materially distinct scientific bundles."""

    bundles: Mapping[str, ScientificProgramBundle]
    external_source_ids: tuple[str, ...] = ()
    bundle_role_hashes: Mapping[str, str] = field(init=False)

    def __post_init__(self) -> None:
        roles = dict(self.bundles)
        if not 3 <= len(roles) <= 5:
            raise ScientificProgramRegistryError(
                "scientific bundle batch requires three to five roles"
            )
        unknown = set(roles) - set(SCIENTIFIC_BUNDLE_ROLES)
        if unknown:
            raise ScientificProgramRegistryError(
                f"scientific bundle batch has unknown roles: {sorted(unknown)}"
            )
        normalized: dict[str, ScientificProgramBundle] = {}
        for role in SCIENTIFIC_BUNDLE_ROLES:
            if role not in roles:
                continue
            bundle = roles[role]
            if not isinstance(bundle, ScientificProgramBundle):
                raise ScientificProgramRegistryError(
                    f"scientific bundle role is invalid: {role}"
                )
            if bundle.external_source_ids:
                raise ScientificProgramRegistryError(
                    "scientific bundle batch may not declare external sources"
                )
            normalized[role] = bundle
        role_hashes = {
            role: normalized[role].bundle_sha256 for role in normalized
        }
        if len(set(role_hashes.values())) != len(role_hashes):
            raise ScientificProgramRegistryError(
                "scientific bundle roles must be materially distinct"
            )
        if tuple(self.external_source_ids):
            raise ScientificProgramRegistryError(
                "scientific bundle batch may not declare external sources"
            )
        object.__setattr__(self, "bundles", MappingProxyType(normalized))
        object.__setattr__(self, "external_source_ids", ())
        object.__setattr__(self, "bundle_role_hashes", MappingProxyType(role_hashes))

    @property
    def bundle_roles(self) -> Mapping[str, str]:
        """Hashes ready for ``HypothesisBatch.bundle_roles``."""

        return self.bundle_role_hashes

    @property
    def bundle_sha256_by_role(self) -> Mapping[str, str]:
        return self.bundle_role_hashes

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_scientific_bundle_batch_v1",
            "scientific_origin": SCIENTIFIC_ORIGIN,
            "bundle_roles": dict(self.bundle_role_hashes),
            "external_source_ids": [],
        }

    def to_payload(self) -> dict[str, Any]:
        return self.identity_payload()

    @property
    def batch_sha256(self) -> str:
        return sha256_payload(self.identity_payload())

    @classmethod
    def from_payload(
        cls,
        registry: "ScientificProgramRegistry",
        payload: Mapping[str, Any],
    ) -> "ScientificBundleBatch":
        return build_scientific_bundle_batch(registry, payload)


@dataclass(frozen=True)
class ScientificProgramRegistry:
    """Verified in-memory view of a repo-local scientific registry."""

    project_root: Path
    path: Path
    relative_path: str
    registry_sha256: str
    runtime_sha256: str
    runtime_files: tuple[Mapping[str, str], ...]
    programs: Mapping[str, ScientificProgramDefinition]
    status: str = "active"
    scientific_origin: str = SCIENTIFIC_ORIGIN
    arbitrary_import_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "programs", MappingProxyType(dict(self.programs)))
        object.__setattr__(
            self,
            "runtime_files",
            tuple(MappingProxyType(dict(row)) for row in self.runtime_files),
        )

    def resolve(self, program_id: str, *, kind: str) -> ScientificProgramDefinition:
        if kind not in PROGRAM_KINDS:
            raise ScientificProgramRegistryError(f"unknown program kind: {kind}")
        definition = self.programs.get(program_id)
        if definition is None:
            raise ScientificProgramRegistryError(
                f"scientific program is not registered: {kind}={program_id}"
            )
        if definition.kind != kind:
            raise ScientificProgramRegistryError(
                f"scientific program kind mismatch: {program_id} is "
                f"{definition.kind}, expected {kind}"
            )
        return definition

    def make_bundle(
        self,
        program_ids: Mapping[str, Any],
        *,
        external_source_ids: tuple[str, ...] = (),
    ) -> ScientificProgramBundle:
        return build_scientific_program_bundle(
            self,
            program_ids,
            external_source_ids=external_source_ids,
        )

    def make_bundle_batch(
        self, payload: Mapping[str, Any]
    ) -> ScientificBundleBatch:
        return build_scientific_bundle_batch(self, payload)


def _load_definition(
    project_root: Path,
    program_id: str,
    payload: Mapping[str, Any],
    runtime_sha256: str,
) -> ScientificProgramDefinition:
    required = {
        "kind",
        "version",
        "contract_path",
        "contract_sha256",
        "implementation_key",
        "runtime_sha256",
        "parameters",
        "fixture_only",
        "reuse_decision",
        "program_sha256",
    }
    if set(payload) != required:
        raise ScientificProgramRegistryError(
            f"scientific program registry fields mismatch: {program_id}"
        )
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in PROGRAM_KINDS:
        raise ScientificProgramRegistryError(f"invalid scientific program kind: {program_id}")
    if PROGRAM_ID_PATTERNS[kind].fullmatch(program_id) is None:
        raise ScientificProgramRegistryError(
            f"scientific program id does not match kind: {program_id}"
        )
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ScientificProgramRegistryError(
            f"invalid scientific program version: {program_id}"
        )
    implementation_key = payload.get("implementation_key")
    if implementation_key not in SCIENTIFIC_IMPLEMENTATION_KEYS[kind]:
        raise ScientificProgramRegistryError(
            "implementation key is not in the scientific allowlist: "
            f"{kind}={implementation_key}"
        )
    if payload.get("runtime_sha256") != runtime_sha256:
        raise ScientificProgramRegistryError(
            f"scientific program runtime binding mismatch: {program_id}"
        )
    fixture_only = payload.get("fixture_only")
    if fixture_only is not False:
        raise ScientificProgramRegistryError(
            f"scientific program must set fixture_only=false: {program_id}"
        )
    reuse_decision = payload.get("reuse_decision")
    if reuse_decision not in REUSE_DECISIONS:
        raise ScientificProgramRegistryError(
            f"invalid scientific reuse decision: {program_id}"
        )
    contract_path, resolved_contract = _repo_file(
        project_root,
        payload.get("contract_path"),
        label=f"{program_id}.contract_path",
    )
    contract_payload = _read_ascii_yaml_mapping(
        resolved_contract, label="scientific program contract"
    )
    observed_contract_sha256 = _canonical_sha256(
        contract_payload, label="scientific program contract"
    )
    contract_sha256 = payload.get("contract_sha256")
    if (
        not _is_sha256(contract_sha256)
        or contract_sha256 != observed_contract_sha256
    ):
        raise ScientificProgramRegistryError(
            f"scientific program contract hash mismatch: {program_id}"
        )
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping) or not all(
        isinstance(key, str) for key in parameters
    ):
        raise ScientificProgramRegistryError(
            f"scientific program parameters must be a string-keyed mapping: {program_id}"
        )
    normalized_parameters = dict(parameters)
    _canonical_sha256(
        normalized_parameters,
        label=f"scientific program parameters for {program_id}",
    )
    program_sha256 = payload.get("program_sha256")
    if not _is_sha256(program_sha256):
        raise ScientificProgramRegistryError(
            f"invalid scientific program hash: {program_id}"
        )
    definition = ScientificProgramDefinition(
        program_id=program_id,
        kind=kind,
        version=version,
        contract_path=contract_path,
        contract_sha256=contract_sha256,
        implementation_key=implementation_key,
        runtime_sha256=runtime_sha256,
        parameters=normalized_parameters,
        fixture_only=False,
        reuse_decision=reuse_decision,
        program_sha256=program_sha256,
    )
    if sha256_payload(definition.identity_payload()) != program_sha256:
        raise ScientificProgramRegistryError(
            f"scientific program identity hash mismatch: {program_id}"
        )
    return definition


def _load_runtime_manifest(
    project_root: Path,
    payload: object,
) -> tuple[str, tuple[dict[str, str], ...]]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema",
        "files",
        "runtime_sha256",
    }:
        raise ScientificProgramRegistryError(
            "scientific runtime manifest fields mismatch"
        )
    if payload.get("schema") != SCIENTIFIC_RUNTIME_SCHEMA:
        raise ScientificProgramRegistryError("scientific runtime manifest schema mismatch")
    rows = payload.get("files")
    if not isinstance(rows, list) or len(rows) != len(SCIENTIFIC_RUNTIME_PATHS):
        raise ScientificProgramRegistryError("scientific runtime file set is incomplete")
    normalized: list[dict[str, str]] = []
    for expected_path, row in zip(SCIENTIFIC_RUNTIME_PATHS, rows, strict=True):
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256"}:
            raise ScientificProgramRegistryError("scientific runtime file descriptor is invalid")
        relative_path, resolved = _repo_file(
            project_root,
            row.get("path"),
            label="scientific runtime file",
        )
        expected_sha256 = row.get("sha256")
        observed_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if relative_path != expected_path or expected_sha256 != observed_sha256:
            raise ScientificProgramRegistryError(
                f"scientific runtime file hash mismatch: {expected_path}"
            )
        normalized.append({"path": relative_path, "sha256": observed_sha256})
    identity = {"schema": SCIENTIFIC_RUNTIME_SCHEMA, "files": normalized}
    runtime_sha256 = _canonical_sha256(identity, label="scientific runtime manifest")
    if payload.get("runtime_sha256") != runtime_sha256:
        raise ScientificProgramRegistryError("scientific runtime manifest hash mismatch")
    return runtime_sha256, tuple(normalized)


def load_scientific_program_registry(
    project_root: Path,
    registry_path: Path | None = None,
) -> ScientificProgramRegistry:
    """Load and verify a scientific registry without imports or writes."""

    root = project_root.resolve()
    if not root.is_dir():
        raise ScientificProgramRegistryError("project root is missing")
    relative_path, path = _registry_file(
        root, registry_path or DEFAULT_SCIENTIFIC_PROGRAM_REGISTRY_PATH
    )
    payload = _read_ascii_yaml_mapping(path, label="scientific program registry")
    required_fields = {
        "schema",
        "status",
        "scientific_origin",
        "arbitrary_import_allowed",
        "runtime",
        "programs",
    }
    optional_fields = {"encoding", "hash_semantics"}
    if not required_fields.issubset(payload) or set(payload) - (
        required_fields | optional_fields
    ):
        raise ScientificProgramRegistryError(
            "scientific program registry top-level fields mismatch"
        )
    if payload.get("schema") != SCIENTIFIC_REGISTRY_SCHEMA:
        raise ScientificProgramRegistryError("scientific program registry schema mismatch")
    if payload.get("status") != "active":
        raise ScientificProgramRegistryError("scientific program registry is not active")
    if payload.get("scientific_origin") != SCIENTIFIC_ORIGIN:
        raise ScientificProgramRegistryError(
            "scientific program registry origin must be v2_current"
        )
    if payload.get("arbitrary_import_allowed") is not False:
        raise ScientificProgramRegistryError(
            "scientific program registry may not allow arbitrary imports"
        )
    if "encoding" in payload and payload.get("encoding") != "ascii_only":
        raise ScientificProgramRegistryError(
            "scientific program registry encoding declaration mismatch"
        )
    if (
        "hash_semantics" in payload
        and payload.get("hash_semantics") != "compact_sorted_ascii_json_sha256"
    ):
        raise ScientificProgramRegistryError(
            "scientific program registry hash semantics mismatch"
        )
    rows = payload.get("programs")
    if not isinstance(rows, Mapping) or not rows:
        raise ScientificProgramRegistryError(
            "scientific program registry contains no programs"
        )
    runtime_sha256, runtime_files = _load_runtime_manifest(
        root, payload.get("runtime")
    )
    programs: dict[str, ScientificProgramDefinition] = {}
    executable_ids: dict[str, str] = {}
    for raw_program_id, body in rows.items():
        if not isinstance(raw_program_id, str) or not isinstance(body, Mapping):
            raise ScientificProgramRegistryError(
                "scientific program entries must be mappings keyed by id"
            )
        definition = _load_definition(
            root, raw_program_id, body, runtime_sha256
        )
        duplicate_id = executable_ids.get(definition.executable_sha256)
        if duplicate_id is not None:
            raise ScientificProgramRegistryError(
                "renamed duplicate executable identity: "
                f"{duplicate_id} and {definition.program_id}"
            )
        executable_ids[definition.executable_sha256] = definition.program_id
        programs[definition.program_id] = definition
    if {definition.kind for definition in programs.values()} != set(PROGRAM_KINDS):
        raise ScientificProgramRegistryError(
            "scientific program registry must cover all eight dispatch kinds"
        )
    registry_sha256 = _canonical_sha256(
        dict(payload), label="scientific program registry"
    )
    return ScientificProgramRegistry(
        project_root=root,
        path=path,
        relative_path=relative_path,
        registry_sha256=registry_sha256,
        runtime_sha256=runtime_sha256,
        runtime_files=runtime_files,
        programs=programs,
    )


def build_scientific_program_bundle(
    registry: ScientificProgramRegistry,
    payload: Mapping[str, Any],
    *,
    external_source_ids: tuple[str, ...] = (),
) -> ScientificProgramBundle:
    """Resolve one complete kind-to-program-id mapping into a bundle."""

    if not isinstance(registry, ScientificProgramRegistry):
        raise ScientificProgramRegistryError("scientific registry is required")
    if not isinstance(payload, Mapping) or set(payload) != set(PROGRAM_KINDS):
        raise ScientificProgramRegistryError(
            "scientific bundle program ids must cover all eight kinds"
        )
    if tuple(external_source_ids):
        raise ScientificProgramRegistryError(
            "scientific program bundles may not declare external sources"
        )
    programs: dict[str, ScientificProgramDefinition] = {}
    for kind in PROGRAM_KINDS:
        program_id = payload[kind]
        if not isinstance(program_id, str):
            raise ScientificProgramRegistryError(
                f"scientific bundle program id must be a string: {kind}"
            )
        programs[kind] = registry.resolve(program_id, kind=kind)
    return ScientificProgramBundle(programs=programs)


def bind_compression_release_runtime(
    registry: ScientificProgramRegistry,
    batch: ScientificBundleBatch,
) -> Mapping[str, str]:
    """Bind the five registered bundle roles to the executed event surface."""

    from axiom_rift.v2.research.compression_release import EVENT_CONFIGURATIONS

    if set(batch.bundles) != set(SCIENTIFIC_BUNDLE_ROLES):
        raise ScientificProgramRegistryError(
            "compression-release runtime requires all five bundle roles"
        )
    expected_shared: dict[str, dict[str, Any]] = {
        "feature": {"atr_bars": 24, "box_bars": 12},
        "label": {"horizon_bars_after_entry": 6},
        "model": {
            "family": "deterministic_event_score",
            "train_fit": "hashed_no_op",
        },
        "calibration": {"family": "identity_event_calibration"},
        "sizing": {"mode": "fixed_lot", "lots": 1.0},
        "portfolio_risk": {
            "one_position_per_role": True,
            "overlap": "forbidden",
        },
    }
    expected_trade_parameters = {
        "fixed_6bar_observed_spread_v1": {
            "hold_bars": 6,
            "spread": "observed_broker_points",
            "zero_spread": "unknown_cost_observation",
        },
        "fixed_6bar_causal_spread_floor_v1": {
            "hold_bars": 6,
            "policy_id": "V2CF0001",
            "decision_zero_action": "reject_signal_admission",
            "positive_execution_rule": "max_decision_and_execution_spread",
            "execution_zero_action": "positive_decision_spread_floor",
            "policy_parameter_count": 0,
        },
    }
    trade_program_ids = {
        bundle.programs["trade"].program_id for bundle in batch.bundles.values()
    }
    trade_implementation_keys = {
        bundle.programs["trade"].implementation_key
        for bundle in batch.bundles.values()
    }
    if len(trade_program_ids) != 1 or len(trade_implementation_keys) != 1:
        raise ScientificProgramRegistryError(
            "compression-release batch may not mix trade cost policies"
        )
    trade_implementation_key = next(iter(trade_implementation_keys))
    expected_trade = expected_trade_parameters.get(trade_implementation_key)
    if expected_trade is None:
        raise ScientificProgramRegistryError(
            "compression-release trade policy is not registered"
        )
    configurations = {row.role: row for row in EVENT_CONFIGURATIONS}
    release_hashes: dict[str, str] = {}
    for role in SCIENTIFIC_BUNDLE_ROLES:
        bundle = batch.bundles[role]
        for kind, expected in expected_shared.items():
            if dict(bundle.programs[kind].parameters) != expected:
                raise ScientificProgramRegistryError(
                    f"compression-release runtime parameters differ: {role}.{kind}"
                )
            if bundle.programs[kind].runtime_sha256 != registry.runtime_sha256:
                raise ScientificProgramRegistryError(
                    f"compression-release runtime hash differs: {role}.{kind}"
                )
        trade = bundle.programs["trade"]
        if (
            dict(trade.parameters) != expected_trade
            or trade.runtime_sha256 != registry.runtime_sha256
        ):
            raise ScientificProgramRegistryError(
                f"compression-release trade policy differs from runtime: {role}"
            )
        configuration = configurations[role]
        expected_selector = {
            "role": role,
            "event_kind": configuration.event_kind,
            "compression_ratio_max": configuration.compression_ratio_max,
            "daily_entry_safety_cap": 10,
        }
        expected_selector_key = "chronological_compression_selector_v1"
        if trade_implementation_key == "fixed_6bar_causal_spread_floor_v1":
            expected_selector["admission_cost_policy_id"] = "V2CF0001"
            expected_selector_key = (
                "chronological_compression_cost_gated_selector_v1"
            )
        selector = bundle.programs["selector"]
        if (
            dict(selector.parameters) != expected_selector
            or selector.implementation_key != expected_selector_key
            or selector.runtime_sha256 != registry.runtime_sha256
        ):
            raise ScientificProgramRegistryError(
                f"compression-release selector differs from runtime: {role}"
            )
        release_hashes[role] = configuration.identity_sha256
    return MappingProxyType(release_hashes)


def _bundle_role_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept direct role maps and one explicit no-external-source envelope."""

    if "bundle_roles" not in payload:
        return payload
    allowed = {
        "schema",
        "scientific_origin",
        "bundle_roles",
        "external_source_ids",
        "runtime_sha256",
        "runtime_executable_sha256",
        "release_configuration_hashes",
        "selection_rule_sha256",
    }
    if set(payload) - allowed:
        raise ScientificProgramRegistryError(
            "scientific bundle batch envelope fields mismatch"
        )
    if "schema" in payload and payload.get("schema") not in {
        "axiom_rift_v2_scientific_bundle_batch_spec_v1",
        "axiom_rift_v2_scientific_bundle_batch_v1",
    }:
        raise ScientificProgramRegistryError("scientific bundle batch schema mismatch")
    if (
        "scientific_origin" in payload
        and payload.get("scientific_origin") != SCIENTIFIC_ORIGIN
    ):
        raise ScientificProgramRegistryError("scientific bundle batch origin mismatch")
    sources = payload.get("external_source_ids", [])
    if not isinstance(sources, (list, tuple)) or sources:
        raise ScientificProgramRegistryError(
            "scientific bundle batch may not declare external sources"
        )
    roles = payload.get("bundle_roles")
    if not isinstance(roles, Mapping):
        raise ScientificProgramRegistryError(
            "scientific bundle batch roles must be a mapping"
        )
    return roles


def build_scientific_bundle_batch(
    registry: ScientificProgramRegistry,
    payload: Mapping[str, Any],
) -> ScientificBundleBatch:
    """Build a deterministic, no-external-source batch from named role maps."""

    if not isinstance(payload, Mapping):
        raise ScientificProgramRegistryError(
            "scientific bundle batch payload must be a mapping"
        )
    role_payload = _bundle_role_payload(payload)
    if not 3 <= len(role_payload) <= 5:
        raise ScientificProgramRegistryError(
            "scientific bundle batch requires three to five roles"
        )
    unknown = set(role_payload) - set(SCIENTIFIC_BUNDLE_ROLES)
    if unknown:
        raise ScientificProgramRegistryError(
            f"scientific bundle batch has unknown roles: {sorted(unknown)}"
        )
    bundles: dict[str, ScientificProgramBundle] = {}
    for role in SCIENTIFIC_BUNDLE_ROLES:
        if role not in role_payload:
            continue
        program_ids = role_payload[role]
        if not isinstance(program_ids, Mapping):
            raise ScientificProgramRegistryError(
                f"scientific bundle role must map kinds to ids: {role}"
            )
        bundles[role] = build_scientific_program_bundle(registry, program_ids)
    return ScientificBundleBatch(bundles=bundles)


__all__ = [
    "BUNDLE_ROLE_NAMES",
    "DEFAULT_SCIENTIFIC_PROGRAM_REGISTRY_PATH",
    "IMPLEMENTATION_KEY_ALLOWLIST",
    "ProgramDefinition",
    "REUSE_DECISIONS",
    "SAFE_IMPLEMENTATION_KEYS",
    "SCIENTIFIC_BUNDLE_ROLES",
    "SCIENTIFIC_IMPLEMENTATION_KEYS",
    "SCIENTIFIC_ORIGIN",
    "SCIENTIFIC_REGISTRY_SCHEMA",
    "SCIENTIFIC_RUNTIME_PATHS",
    "SCIENTIFIC_RUNTIME_SCHEMA",
    "ScientificBundleBatch",
    "ScientificProgramBundle",
    "ScientificProgramDefinition",
    "ScientificProgramError",
    "ScientificProgramRegistry",
    "ScientificProgramRegistryError",
    "build_scientific_bundle_batch",
    "build_scientific_program_bundle",
    "bind_compression_release_runtime",
    "load_scientific_program_registry",
]
