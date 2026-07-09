"""Fast activation receipt checker; never launches an evidence job."""

from __future__ import annotations

import csv
import hashlib
import json
import time
import tomllib
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.ledger import HashChainLedger
from axiom_rift.v2.lifecycle import prove_full_lifecycle_guard_path
from axiom_rift.v2.state.store import ControlStore
from axiom_rift.v2.validation.receipts import validation_key
from axiom_rift.v2.validation.types import ValidationIssue, ValidationResult


REQUIRED_CONTRACTS = (
    "activation_contract.yaml",
    "architecture.yaml",
    "claim_ladder.yaml",
    "evaluation_contract.yaml",
    "handoff_contract.yaml",
    "identity_policy.yaml",
    "materialization_contract.yaml",
    "project_contract.yaml",
    "research_contract.yaml",
    "split_policy.yaml",
    "state_machine.yaml",
    "validation_contract.yaml",
)
REQUIRED_EVIDENCE_FILES = {
    "V2E000004": "campaigns/v2/V2G0001_v2_activation/evidence/V2DATA0002/receipt.json",
    "V2E000005": "campaigns/v2/V2G0001_v2_activation/evidence/V2FIX0001/receipt.json",
    "V2E000006": "campaigns/v2/V2G0001_v2_activation/evidence/V2S0001/receipt.json",
    "V2E000007": "campaigns/v2/V2G0001_v2_activation/evidence/V2MT50001/receipt.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError("JSON root is not a mapping")
    return payload


def _issue(issues: list[ValidationIssue], code: str, path: Path | str, detail: str) -> None:
    issues.append(ValidationIssue(code, str(path).replace("\\", "/"), detail))


def _check(condition: bool, issues: list[ValidationIssue], code: str, path: Path | str, detail: str) -> None:
    if not condition:
        _issue(issues, code, path, detail)


def _input_hashes(root: Path, phase: str) -> dict[str, str]:
    relatives = [
        "contracts/v2/goal_packet.yaml",
        "contracts/v2/agents_router_candidate.md",
        "configs/v2/validation.yaml",
        "configs/v2/data.yaml",
        "configs/v2/splits.yaml",
        "configs/v2/feature_programs/causal_bar_v1.yaml",
        "registries/v2/control_state.yaml",
        "registries/v2/hypothesis_ledger.jsonl",
        "registries/v2/evidence_ledger.jsonl",
        "registries/v2/material_ledger.jsonl",
        "registries/v2/legacy_debt.yaml",
        ".agents/skills/axiom-v2-goal-operator/SKILL.md",
        "campaigns/v2/V2G0001_v2_activation/negative_memory/V2H0001.yaml",
        *REQUIRED_EVIDENCE_FILES.values(),
    ]
    if phase == "active":
        relatives.append("AGENTS.md")
    hashes = {relative: sha256_file(root / relative) for relative in relatives}
    state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
    hashes["registries/v2/control_state.yaml"] = sha256_payload(
        {
            "active_truth": state.get("active_truth"),
            "status": state.get("status"),
            "cursor": {
                "active_goal_id": state.get("cursor", {}).get("active_goal_id"),
                "active_hypothesis_id": state.get("cursor", {}).get("active_hypothesis_id"),
                "stage": state.get("cursor", {}).get("stage"),
                "stage_id": state.get("cursor", {}).get("stage_id"),
                "stage_status": state.get("cursor", {}).get("stage_status"),
                "stage_outcome": state.get("cursor", {}).get("stage_outcome"),
                "exact_next_action": state.get("cursor", {}).get("exact_next_action"),
            },
            "active_job": state.get("reentry", {}).get("active_job"),
            "claim": state.get("claim"),
            "activation": state.get("activation"),
        }
    )
    return hashes


def validate_v2_activation(root: Path, phase: str = "candidate") -> tuple[ValidationResult, dict[str, Any]]:
    started = time.perf_counter()
    root = root.resolve()
    if phase not in {"candidate", "active"}:
        raise ValueError("activation validation phase must be candidate or active")
    issues: list[ValidationIssue] = []
    contract_hashes: dict[str, str] = {}
    for name in REQUIRED_CONTRACTS:
        path = root / "contracts" / "v2" / name
        try:
            payload = yaml.safe_load(path.read_text(encoding="ascii"))
            _check(isinstance(payload, dict), issues, "invalid_contract", path, "contract root must be a mapping")
            if isinstance(payload, dict):
                expected_status = "active" if phase == "active" else "bootstrap_candidate"
                _check(payload.get("status") == expected_status, issues, "contract_status", path, f"expected status {expected_status}")
            contract_hashes[path.relative_to(root).as_posix()] = sha256_file(path)
        except Exception as exc:
            _issue(issues, "invalid_contract", path, str(exc))
    candidate_router = root / "contracts/v2/agents_router_candidate.md"
    try:
        router_text = candidate_router.read_text(encoding="ascii")
        _check("active_truth: v2" in router_text, issues, "router_missing_v2", candidate_router, "candidate router must select V2")
    except Exception as exc:
        _issue(issues, "invalid_router", candidate_router, str(exc))
        router_text = ""
    if phase == "active":
        active_router = root / "AGENTS.md"
        try:
            _check(active_router.read_text(encoding="ascii") == router_text, issues, "active_router_mismatch", active_router, "AGENTS.md differs from the validated V2 router")
        except Exception as exc:
            _issue(issues, "invalid_active_router", active_router, str(exc))
    skill_path = root / ".agents/skills/axiom-v2-goal-operator/SKILL.md"
    try:
        skill_text = skill_path.read_text(encoding="ascii")
        _check("TODO" not in skill_text, issues, "skill_todo", skill_path, "active skill contains TODO")
        _check("name: axiom-v2-goal-operator" in skill_text, issues, "skill_name", skill_path, "skill frontmatter name is missing")
    except Exception as exc:
        _issue(issues, "invalid_skill", skill_path, str(exc))
    state_path = root / "registries/v2/control_state.yaml"
    objects = ObjectStore(root / "registries/v2/objects")
    try:
        state = ControlStore(state_path, object_store=objects).load()
        expected_truth = "v2" if phase == "active" else "v1_until_v2_activation"
        _check(state.get("active_truth") == expected_truth, issues, "active_truth", state_path, f"expected {expected_truth}")
        _check(state["reentry"].get("active_job") is None, issues, "active_job", state_path, "activation requires no active long job")
        _check(state["cursor"].get("stage") == "S", issues, "stage", state_path, "bootstrap scout must be the completed S stage")
        _check(state["cursor"].get("stage_status") == "completed", issues, "stage_status", state_path, "scout stage is incomplete")
        _check(state["cursor"].get("stage_outcome") == "scout_rejected", issues, "stage_outcome", state_path, "first scout disposition is missing")
        _check(state["claim"].get("current_level") == "diagnostic_observation", issues, "claim_level", state_path, "first scout must remain diagnostic")
        if phase == "active":
            _check(state.get("status") == "active", issues, "state_status", state_path, "V2 state is not active")
            _check(isinstance(state.get("activation"), dict), issues, "activation_receipt", state_path, "activation receipt reference is missing")
        for object_id in state["cursor"].get("authoritative_object_ids", []):
            objects.get(object_id)
    except Exception as exc:
        state = {}
        _issue(issues, "invalid_control_state", state_path, str(exc))
    ledgers = {
        "hypothesis": HashChainLedger(root / "registries/v2/hypothesis_ledger.jsonl", "hypothesis"),
        "evidence": HashChainLedger(root / "registries/v2/evidence_ledger.jsonl", "evidence"),
        "material": HashChainLedger(root / "registries/v2/material_ledger.jsonl", "material"),
        "validation_receipt": HashChainLedger(root / "registries/v2/validation_receipts.jsonl", "validation_receipt"),
    }
    ledger_rows: dict[str, list[dict[str, Any]]] = {}
    for name, ledger in ledgers.items():
        try:
            ledger_rows[name] = ledger.rows()
        except Exception as exc:
            ledger_rows[name] = []
            _issue(issues, "invalid_ledger", ledger.path, str(exc))
    hypothesis_ids = {row["record_id"] for row in ledger_rows["hypothesis"]}
    _check("V2H0001" in hypothesis_ids, issues, "missing_hypothesis", "registries/v2/hypothesis_ledger.jsonl", "V2H0001 preregistration is missing")
    _check("V2H0001_DISPOSITION" in hypothesis_ids, issues, "missing_disposition", "registries/v2/hypothesis_ledger.jsonl", "V2H0001 disposition is missing")
    material_ids = {row["record_id"] for row in ledger_rows["material"]}
    for index in range(11, 21):
        material_id = f"V2MAT{index:06d}"
        _check(material_id in material_ids, issues, "missing_material", "registries/v2/material_ledger.jsonl", material_id)
    evidence_by_id = {row["record_id"]: row for row in ledger_rows["evidence"]}
    receipts: dict[str, dict[str, Any]] = {}
    for evidence_id, relative in REQUIRED_EVIDENCE_FILES.items():
        path = root / relative
        try:
            receipt = _load_json(path)
            receipts[evidence_id] = receipt
            row = evidence_by_id.get(evidence_id)
            _check(row is not None, issues, "missing_evidence_row", path, evidence_id)
            if row is not None:
                stored = objects.get(row["payload"]["receipt_object_id"])["payload"]
                _check(stored == receipt, issues, "evidence_object_mismatch", path, evidence_id)
        except Exception as exc:
            _issue(issues, "invalid_evidence_receipt", path, str(exc))
    data = receipts.get("V2E000004", {})
    _check(data.get("status") == "passed", issues, "data_receipt", REQUIRED_EVIDENCE_FILES["V2E000004"], "data receipt did not pass")
    _check(data.get("row_count") == 571771, issues, "data_row_count", REQUIRED_EVIDENCE_FILES["V2E000004"], "unexpected row count")
    _check(data.get("zero_spread_count") == 3497, issues, "zero_spread_count", REQUIRED_EVIDENCE_FILES["V2E000004"], "zero-spread evidence is missing")
    _check(data.get("scout_anchor_ids") == ["V2D002", "V2D005", "V2D008"], issues, "scout_anchors", REQUIRED_EVIDENCE_FILES["V2E000004"], "season-diverse anchors differ")
    fixture = receipts.get("V2E000005", {})
    parity = fixture.get("parity", {}) if isinstance(fixture.get("parity"), dict) else {}
    _check(fixture.get("status") == "passed", issues, "fixture_status", REQUIRED_EVIDENCE_FILES["V2E000005"], "fixture did not pass")
    _check(parity.get("python_mql_feature_parity") is True, issues, "feature_parity", REQUIRED_EVIDENCE_FILES["V2E000005"], "Python/MQL feature parity missing")
    _check(parity.get("python_onnx_score_parity") is True, issues, "onnx_parity", REQUIRED_EVIDENCE_FILES["V2E000005"], "Python/ONNX score parity missing")
    _check(parity.get("timestamp_direction_lifecycle_exact") is True, issues, "lifecycle_parity", REQUIRED_EVIDENCE_FILES["V2E000005"], "decision lifecycle parity missing")
    scout = receipts.get("V2E000006", {})
    _check(scout.get("status") == "completed", issues, "scout_status", REQUIRED_EVIDENCE_FILES["V2E000006"], "scout is incomplete")
    _check(scout.get("outcome") == "scout_rejected", issues, "scout_outcome", REQUIRED_EVIDENCE_FILES["V2E000006"], "unexpected first scout outcome")
    _check(scout.get("mt5_executed") is False, issues, "scout_mt5", REQUIRED_EVIDENCE_FILES["V2E000006"], "S must not spend MT5")
    _check(scout.get("isolated_nine_fold_executed") is False, issues, "scout_nine_fold", REQUIRED_EVIDENCE_FILES["V2E000006"], "S must not run nine-fold MT5")
    smoke = receipts.get("V2E000007", {})
    _check(smoke.get("status") == "passed" and smoke.get("real_ticks") is True, issues, "tick_smoke", REQUIRED_EVIDENCE_FILES["V2E000007"], "native real-tick smoke did not pass")
    _check(int(smoke.get("admitted_entry_count", 0)) > 0, issues, "tick_entries", REQUIRED_EVIDENCE_FILES["V2E000007"], "native EA admitted no entry")
    decision_path = root / str(smoke.get("decision_ledger_path", ""))
    try:
        with decision_path.open("r", encoding="ascii", newline="") as handle:
            decisions = list(csv.DictReader(handle))
        entries = sum(row.get("event") == "enter" for row in decisions)
        exits = sum(row.get("event") == "exit" for row in decisions)
        _check(entries == exits == int(smoke.get("admitted_entry_count", -1)), issues, "tick_lifecycle_balance", decision_path, f"entries={entries} exits={exits}")
    except Exception as exc:
        _issue(issues, "invalid_tick_decision_ledger", decision_path, str(exc))
    negative_memory = root / "campaigns/v2/V2G0001_v2_activation/negative_memory/V2H0001.yaml"
    try:
        memory = yaml.safe_load(negative_memory.read_text(encoding="ascii"))
        _check(memory.get("outcome") == "scout_rejected", issues, "negative_memory", negative_memory, "negative memory outcome differs")
    except Exception as exc:
        _issue(issues, "invalid_negative_memory", negative_memory, str(exc))
    legacy_debt = root / "registries/v2/legacy_debt.yaml"
    try:
        debt = yaml.safe_load(legacy_debt.read_text(encoding="ascii"))
        _check(debt.get("status") == "classified_nonblocking_for_v2_activation", issues, "legacy_debt", legacy_debt, "legacy debt is not separately scoped")
    except Exception as exc:
        _issue(issues, "invalid_legacy_debt", legacy_debt, str(exc))
    validation_config_path = root / "configs/v2/validation.yaml"
    validation_config = yaml.safe_load(validation_config_path.read_text(encoding="ascii"))
    routine = validation_config.get("routine_validator", {})
    _check(routine.get("target_seconds_min") == 3 and routine.get("target_seconds_max") == 15, issues, "validation_target", validation_config_path, "routine target must be 3-15 seconds")
    _check(routine.get("hard_ceiling_seconds") == 30, issues, "validation_ceiling", validation_config_path, "routine ceiling must be 30 seconds")
    try:
        lifecycle = prove_full_lifecycle_guard_path()
        _check(all(lifecycle.values()) and len(lifecycle) == 5, issues, "lifecycle_guard", "src/axiom_rift/v2/lifecycle.py", "H/S/R/P/M proof path is incomplete")
    except Exception as exc:
        _issue(issues, "lifecycle_guard", "src/axiom_rift/v2/lifecycle.py", str(exc))
    try:
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="ascii"))
        scripts = pyproject["project"]["scripts"]
        _check(scripts.get("axiom-rift-v2") == "axiom_rift.v2.cli:main", issues, "v2_cli", "pyproject.toml", "V2 CLI entrypoint is missing")
        if phase == "active":
            _check(scripts.get("axiom-rift") == "axiom_rift.v2.cli:main", issues, "active_cli", "pyproject.toml", "primary CLI does not route to V2")
            _check(scripts.get("axiom-rift-v1-legacy") == "axiom_rift.cli:main", issues, "legacy_cli", "pyproject.toml", "legacy CLI escape hatch is missing")
    except Exception as exc:
        _issue(issues, "invalid_pyproject", "pyproject.toml", str(exc))
    duration = time.perf_counter() - started
    _check(duration < 30.0, issues, "validation_budget_exceeded", "configs/v2/validation.yaml", f"activation checker took {duration:.6f}s")
    result = ValidationResult(target=f"v2-activation-{phase}", issues=tuple(issues))
    input_hashes = _input_hashes(root, phase)
    code_path = root / "src/axiom_rift/v2/validation/activation.py"
    key = validation_key(
        validator_id=f"axiom_rift_v2_activation_{phase}_v1",
        validator_code_sha256=sha256_file(code_path),
        input_hashes=input_hashes,
        config_hashes={"configs/v2/validation.yaml": sha256_file(validation_config_path)},
        contract_hashes=contract_hashes,
        scope=sorted(input_hashes),
    )
    receipt = {
        "schema": "axiom_rift_v2_activation_validation_receipt_v1",
        "validator_id": f"axiom_rift_v2_activation_{phase}_v1",
        "validator_version": 1,
        "validator_code_sha256": sha256_file(code_path),
        "validation_key": key,
        "phase": phase,
        "scope": sorted(input_hashes),
        "input_hashes": input_hashes,
        "config_hashes": {"configs/v2/validation.yaml": sha256_file(validation_config_path)},
        "contract_hashes": contract_hashes,
        "duration_seconds": duration,
        "outcome": "pass" if result.ok else "fail",
        "issues": [issue.to_dict() for issue in result.issues],
        "evidence_jobs_launched": False,
        "hard_ceiling_seconds": 30,
        "claim_ceiling": "none",
    }
    return result, receipt
