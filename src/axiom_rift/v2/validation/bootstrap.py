"""Fast, read-only validation for the V2 bootstrap control plane."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.ledger import HashChainLedger, LedgerError
from axiom_rift.v2.state.store import ControlStateError, validate_control_state
from axiom_rift.v2.validation.types import ValidationIssue, ValidationResult


EXPECTED_SCHEMAS = {
    "contracts/v2/goal_packet.yaml": "axiom_rift_v2_goal_packet_v1",
    "contracts/v2/architecture.yaml": "axiom_rift_v2_architecture_v1",
    "contracts/v2/state_machine.yaml": "axiom_rift_v2_state_machine_v1",
    "contracts/v2/claim_ladder.yaml": "axiom_rift_v2_claim_ladder_v1",
    "contracts/v2/split_policy.yaml": "axiom_rift_v2_split_policy_v1",
    "contracts/v2/identity_policy.yaml": "axiom_rift_v2_identity_policy_v1",
    "configs/v2/market.yaml": "axiom_rift_v2_market_config_v1",
    "configs/v2/data.yaml": "axiom_rift_v2_data_config_v1",
    "configs/v2/splits.yaml": "axiom_rift_v2_split_config_v1",
    "configs/v2/validation.yaml": "axiom_rift_v2_validation_budget_v1",
    "registries/v2/control_state.yaml": "axiom_rift_v2_control_state_v1",
}
LEDGERS = {
    "hypothesis": "registries/v2/hypothesis_ledger.jsonl",
    "evidence": "registries/v2/evidence_ledger.jsonl",
    "material": "registries/v2/material_ledger.jsonl",
    "validation_receipt": "registries/v2/validation_receipts.jsonl",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(root: Path, relative: str, issues: list[ValidationIssue]) -> dict[str, Any] | None:
    path = root / relative
    if not path.is_file():
        issues.append(ValidationIssue("missing_file", relative, "required V2 bootstrap file is missing"))
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="ascii"))
    except UnicodeError:
        issues.append(ValidationIssue("non_ascii", relative, "active V2 file is not ASCII"))
        return None
    except yaml.YAMLError as exc:
        issues.append(ValidationIssue("invalid_yaml", relative, str(exc)))
        return None
    if not isinstance(payload, dict):
        issues.append(ValidationIssue("invalid_shape", relative, "expected a YAML mapping"))
        return None
    expected = EXPECTED_SCHEMAS[relative]
    if payload.get("schema") != expected:
        issues.append(ValidationIssue("schema_mismatch", relative, f"expected {expected}"))
    return payload


def validate_v2_bootstrap(root: Path = PROJECT_ROOT) -> ValidationResult:
    root = root.resolve()
    issues: list[ValidationIssue] = []
    payloads = {relative: _load_yaml(root, relative, issues) for relative in EXPECTED_SCHEMAS}
    spec_path = root / "contracts/v2/goal_spec.md"
    if not spec_path.is_file():
        issues.append(ValidationIssue("missing_file", "contracts/v2/goal_spec.md", "goal spec is missing"))
    else:
        try:
            spec_path.read_text(encoding="ascii")
        except UnicodeError:
            issues.append(ValidationIssue("non_ascii", "contracts/v2/goal_spec.md", "goal spec is not ASCII"))
    packet = payloads["contracts/v2/goal_packet.yaml"]
    validation = payloads["configs/v2/validation.yaml"]
    control = payloads["registries/v2/control_state.yaml"]
    if packet is not None and spec_path.is_file():
        expected_hash = str(packet.get("authoritative_spec", {}).get("sha256", ""))
        if _sha256(spec_path) != expected_hash:
            issues.append(ValidationIssue("goal_spec_hash_mismatch", "contracts/v2/goal_spec.md", "goal spec hash differs from packet"))
    if packet is not None and control is not None and packet.get("goal_id") != control.get("goal_id"):
        issues.append(ValidationIssue("goal_id_drift", "registries/v2/control_state.yaml", "control state and goal packet differ"))
    if control is not None:
        try:
            validate_control_state(control)
        except ControlStateError as exc:
            issues.append(ValidationIssue("invalid_control_state", "registries/v2/control_state.yaml", str(exc)))
    if validation is not None:
        routine = validation.get("routine_validator", {})
        if routine.get("hard_ceiling_seconds") != 30:
            issues.append(ValidationIssue("validation_budget_invalid", "configs/v2/validation.yaml", "hard ceiling must be 30 seconds"))
        if routine.get("may_launch_evidence_jobs") is not False:
            issues.append(ValidationIssue("validator_role_invalid", "configs/v2/validation.yaml", "validator may not launch evidence jobs"))
    for name, relative in LEDGERS.items():
        path = root / relative
        if path.exists():
            try:
                HashChainLedger(path, name).rows()
            except LedgerError as exc:
                issues.append(ValidationIssue("invalid_ledger", relative, str(exc)))
    return ValidationResult("v2-bootstrap", tuple(issues))
