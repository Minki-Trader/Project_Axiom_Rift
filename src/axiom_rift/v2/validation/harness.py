"""Fast V2.1 root-mission harness checker; never launches evidence work."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.operations import V2OperationWriter
from axiom_rift.v2.research.programs import load_program_registry
from axiom_rift.v2.state.store import CONTROL_STATE_SCHEMA_V2, ControlStore
from axiom_rift.v2.validation.receipts import validation_key
from axiom_rift.v2.validation.types import ValidationIssue, ValidationResult


YAML_SCHEMAS = {
    "contracts/v2/operator_contract.yaml": "axiom_rift_v2_operator_contract_v1",
    "configs/v2/mission.yaml": "axiom_rift_v2_mission_config_v1",
    "configs/v2/git.yaml": "axiom_rift_v2_git_config_v1",
    "configs/v2/validation.yaml": "axiom_rift_v2_validation_budget_v1",
    "configs/v2/validation_surfaces.yaml": "axiom_rift_v2_validation_surfaces_v1",
    "configs/v2/program_registry.yaml": "axiom_rift_v2_program_registry_v1",
    "registries/v2/control_state.yaml": CONTROL_STATE_SCHEMA_V2,
}
HASHED_INPUTS = (
    "AGENTS.md",
    "contracts/v2/agents_router_candidate.md",
    ".agents/skills/axiom-v2-goal-operator/SKILL.md",
    ".agents/skills/axiom-v2-goal-operator/agents/openai.yaml",
    "contracts/v2/project_contract.yaml",
    "contracts/v2/research_contract.yaml",
    "contracts/v2/validation_contract.yaml",
    "contracts/v2/handoff_contract.yaml",
    "contracts/v2/operator_contract.yaml",
    "contracts/v2/state_machine.yaml",
    "configs/v2/mission.yaml",
    "configs/v2/git.yaml",
    "configs/v2/validation.yaml",
    "configs/v2/validation_surfaces.yaml",
    "configs/v2/program_registry.yaml",
    "src/axiom_rift/v2/operations.py",
    "src/axiom_rift/v2/state/store.py",
    "src/axiom_rift/v2/state/transitions.py",
    "src/axiom_rift/v2/research/programs.py",
    "src/axiom_rift/v2/research/scout.py",
    "src/axiom_rift/v2/jobs/scout.py",
    "src/axiom_rift/v2/validation/budget.py",
    "src/axiom_rift/v2/git_closeout.py",
    "src/axiom_rift/v2/cli.py",
    "tests/v2/test_v21_state_operations.py",
    "tests/v2/test_identity_state.py",
    "tests/v2/test_v21_canonical_research.py",
    "tests/v2/test_v21_validation_git_cli.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_yaml_payload(path: Path) -> str:
    payload = yaml.safe_load(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError("mission contract must be a YAML mapping")
    return sha256_payload(payload)


def _state_identity(state: dict[str, Any]) -> str:
    return sha256_payload(
        {
            "schema": state.get("schema"),
            "active_truth": state.get("active_truth"),
            "root_mission": state.get("root_mission"),
            "mission_budget": state.get("mission_budget"),
            "namespace": state.get("namespace"),
            "cursor": state.get("cursor"),
            "active_job": state.get("reentry", {}).get("active_job"),
            "claim": state.get("claim"),
            "holdout": state.get("holdout"),
            "migration": state.get("migration"),
        }
    )


def harness_validation_identity(root: Path) -> dict[str, Any]:
    root = root.resolve()
    input_hashes = {relative: sha256_file(root / relative) for relative in HASHED_INPUTS}
    state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
    input_hashes["registries/v2/control_state.yaml"] = _state_identity(state)
    contract_hashes = {
        relative: sha256_file(root / relative)
        for relative in (
            "contracts/v2/project_contract.yaml",
            "contracts/v2/research_contract.yaml",
            "contracts/v2/validation_contract.yaml",
            "contracts/v2/operator_contract.yaml",
        )
    }
    config_hashes = {
        relative: sha256_file(root / relative)
        for relative in (
            "configs/v2/mission.yaml",
            "configs/v2/git.yaml",
            "configs/v2/validation.yaml",
            "configs/v2/validation_surfaces.yaml",
            "configs/v2/program_registry.yaml",
        )
    }
    code_hash = sha256_file(root / "src/axiom_rift/v2/validation/harness.py")
    scope = sorted(input_hashes)
    key = validation_key(
        "axiom_rift_v2_1_harness_v1",
        code_hash,
        input_hashes,
        config_hashes,
        contract_hashes,
        scope,
    )
    return {
        "validator_id": "axiom_rift_v2_1_harness_v1",
        "validator_code_sha256": code_hash,
        "validation_key": key,
        "input_hashes": input_hashes,
        "config_hashes": config_hashes,
        "contract_hashes": contract_hashes,
        "scope": scope,
    }


def validate_v21_harness(root: Path) -> tuple[ValidationResult, dict[str, Any]]:
    started = time.perf_counter()
    root = root.resolve()
    issues: list[ValidationIssue] = []

    def issue(code: str, path: str, detail: str) -> None:
        issues.append(ValidationIssue(code, path, detail))

    for relative, expected_schema in YAML_SCHEMAS.items():
        path = root / relative
        try:
            payload = yaml.safe_load(path.read_text(encoding="ascii"))
            if not isinstance(payload, dict) or payload.get("schema") != expected_schema:
                issue("schema_mismatch", relative, f"expected {expected_schema}")
        except Exception as exc:
            issue("invalid_ascii_yaml", relative, str(exc))
    try:
        if (root / "AGENTS.md").read_text(encoding="ascii") != (
            root / "contracts/v2/agents_router_candidate.md"
        ).read_text(encoding="ascii"):
            issue("router_mismatch", "AGENTS.md", "active and candidate routers differ")
    except Exception as exc:
        issue("invalid_router", "AGENTS.md", str(exc))
    try:
        skill = (root / ".agents/skills/axiom-v2-goal-operator/SKILL.md").read_text(
            encoding="ascii"
        )
        normalized_skill = " ".join(skill.split())
        for token in ("Persist the Root Mission", "failed hypothesis", "origin/main"):
            if token not in normalized_skill:
                issue("skill_boundary_missing", ".agents/skills/axiom-v2-goal-operator/SKILL.md", token)
        if "TODO" in skill:
            issue("skill_todo", ".agents/skills/axiom-v2-goal-operator/SKILL.md", "TODO remains")
    except Exception as exc:
        issue("invalid_skill", ".agents/skills/axiom-v2-goal-operator/SKILL.md", str(exc))
    state: dict[str, Any] = {}
    try:
        state = ControlStore(
            root / "registries/v2/control_state.yaml",
            object_store=ObjectStore(root / "registries/v2/objects"),
        ).load()
        if state.get("active_truth") != "v2":
            issue("active_truth", "registries/v2/control_state.yaml", "V2 is not active")
        if state.get("migration", {}).get("v1_to_v2") != "completed":
            issue("migration", "registries/v2/control_state.yaml", "V2.1 migration is incomplete")
        if state.get("reentry", {}).get("active_job") is not None:
            issue("active_job", "registries/v2/control_state.yaml", "harness closeout requires no job")
        contract = root / str(state.get("root_mission", {}).get("contract_path", ""))
        if not contract.is_file() or sha256_yaml_payload(contract) != state.get("root_mission", {}).get(
            "contract_sha256"
        ):
            issue("mission_contract_drift", "registries/v2/control_state.yaml", "mission hash differs")
    except Exception as exc:
        issue("invalid_control_state", "registries/v2/control_state.yaml", str(exc))
    try:
        if not V2OperationWriter().reconciliation_report(state).get("ok"):
            issue("ledger_control_drift", "registries/v2", "ledger heads differ from control state")
    except Exception as exc:
        issue("reconciliation_failed", "registries/v2", str(exc))
    try:
        load_program_registry(root)
    except Exception as exc:
        issue("program_registry", "configs/v2/program_registry.yaml", str(exc))
    try:
        operations = (root / "src/axiom_rift/v2/operations.py").read_text(encoding="ascii")
        cli = (root / "src/axiom_rift/v2/cli.py").read_text(encoding="ascii")
        if 'if hypothesis_id != "V2H0001"' in operations and "bootstrap writer" not in operations:
            issue("bootstrap_hardcode", "src/axiom_rift/v2/operations.py", "H1 blocks generic use")
        if "run_v2s0001_job" in cli:
            issue("cli_hardcode", "src/axiom_rift/v2/cli.py", "CLI routes to bootstrap scout")
    except Exception as exc:
        issue("invalid_source", "src/axiom_rift/v2", str(exc))
    try:
        from axiom_rift.v2.cli import build_parser

        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        required = {"status", "goal-run", "resume", "validate-surface", "reconcile-state"}
        if not required.issubset(set(action.choices)):
            issue("cli_surface", "src/axiom_rift/v2/cli.py", "required bounded commands are missing")
    except Exception as exc:
        issue("invalid_cli", "src/axiom_rift/v2/cli.py", str(exc))
    duration = time.perf_counter() - started
    if duration > 30:
        issue("duration", "configs/v2/validation.yaml", f"validator took {duration:.6f}s")
    result = ValidationResult("v2-1-harness", tuple(issues))
    identity = harness_validation_identity(root)
    receipt = {
        "schema": "axiom_rift_v2_1_harness_validation_receipt_v1",
        **identity,
        "duration_seconds": duration,
        "outcome": "pass" if result.ok else "fail",
        "issues": [item.to_dict() for item in result.issues],
        "evidence_jobs_launched": False,
        "hard_ceiling_seconds": 30,
        "claim_ceiling": "none",
    }
    return result, receipt
