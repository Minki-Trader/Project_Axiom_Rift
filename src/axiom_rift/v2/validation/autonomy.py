"""Fast V2.4 autonomy-harness validator; never launches research work."""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.research.programs import load_program_registry
from axiom_rift.v2.state.store import ControlStore
from axiom_rift.v2.validation.receipts import validation_key
from axiom_rift.v2.validation.types import ValidationIssue, ValidationResult


VALIDATOR_ID = "axiom_rift_v2_4_autonomy_harness_v1"
HASHED_INPUTS = (
    "AGENTS.md",
    ".agents/skills/axiom-v2-goal-operator/SKILL.md",
    "contracts/v2/agents_router_candidate.md",
    "contracts/v2/autonomy_contract.yaml",
    "contracts/v2/architecture.yaml",
    "contracts/v2/evaluation_contract.yaml",
    "contracts/v2/hypothesis_contract.yaml",
    "contracts/v2/operator_contract.yaml",
    "contracts/v2/project_contract.yaml",
    "contracts/v2/research_contract.yaml",
    "contracts/v2/state_machine.yaml",
    "contracts/v2/validation_contract.yaml",
    "configs/v2/autonomy.yaml",
    "configs/v2/mission.yaml",
    "configs/v2/program_registry.yaml",
    "configs/v2/validation.yaml",
    "configs/v2/validation_surfaces.yaml",
    "registries/v2/scientific/index.yaml",
    "registries/v2/scientific/research_map.yaml",
    "registries/v2/runtime_data_eligibility.yaml",
    "src/axiom_rift/v2/operations.py",
    "src/axiom_rift/v2/cli.py",
    "src/axiom_rift/v2/paths.py",
    "src/axiom_rift/v2/research/__init__.py",
    "src/axiom_rift/v2/research/autonomy.py",
    "src/axiom_rift/v2/research/dispatch.py",
    "src/axiom_rift/v2/research/programs.py",
    "src/axiom_rift/v2/research/runtime_data.py",
    "src/axiom_rift/v2/research/specs.py",
    "src/axiom_rift/v2/state/store.py",
    "src/axiom_rift/v2/state/transitions.py",
    "src/axiom_rift/v2/validation/autonomy.py",
    "src/axiom_rift/v2/validation/__init__.py",
    "tests/v2/test_v24_autonomy_harness.py",
)
SCIENTIFIC_SURFACES = (
    "registries/v2/scientific/index.yaml",
    "registries/v2/scientific/research_map.yaml",
)
FORBIDDEN_TOKENS = (
    re.compile(r"obsidian", re.IGNORECASE),
    re.compile(r"axiom[_ -]?rift[_ -]?v1", re.IGNORECASE),
    re.compile(r"\bstage[0-9]+\b", re.IGNORECASE),
    re.compile(r"\brun[0-9]+\b", re.IGNORECASE),
    re.compile(r"\b(?:C|SC)[0-9]{4}\b"),
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_identity(state: dict[str, Any]) -> str:
    return sha256_payload(
        {
            "schema": state.get("schema"),
            "harness": state.get("harness"),
            "scientific": state.get("scientific"),
            "root_mission": state.get("root_mission"),
            "mission_budget": state.get("mission_budget"),
            "cursor": state.get("cursor"),
            "active_job": state.get("reentry", {}).get("active_job"),
            "claim": state.get("claim"),
            "holdout": state.get("holdout"),
            "ledger_heads": state.get("ledger_heads"),
        }
    )


def autonomy_validation_identity(root: Path) -> dict[str, Any]:
    root = root.resolve()
    inputs = {relative: _sha256_file(root / relative) for relative in HASHED_INPUTS}
    state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
    inputs["registries/v2/control_state.yaml"] = _state_identity(state)
    config_hashes = {
        relative: inputs[relative]
        for relative in (
            "configs/v2/autonomy.yaml",
            "configs/v2/mission.yaml",
            "configs/v2/program_registry.yaml",
            "configs/v2/validation.yaml",
            "configs/v2/validation_surfaces.yaml",
        )
    }
    contract_hashes = {
        relative: inputs[relative]
        for relative in (
            "contracts/v2/autonomy_contract.yaml",
            "contracts/v2/operator_contract.yaml",
            "contracts/v2/research_contract.yaml",
            "contracts/v2/validation_contract.yaml",
        )
    }
    code_hash = inputs["src/axiom_rift/v2/validation/autonomy.py"]
    scope = sorted(inputs)
    return {
        "validator_id": VALIDATOR_ID,
        "validator_code_sha256": code_hash,
        "validation_key": validation_key(
            VALIDATOR_ID,
            code_hash,
            inputs,
            config_hashes,
            contract_hashes,
            scope,
        ),
        "input_hashes": inputs,
        "config_hashes": config_hashes,
        "contract_hashes": contract_hashes,
        "scope": scope,
    }


def _empty(value: object) -> bool:
    return value in (None, [], {}, 0)


def _all_empty(values: Iterable[object]) -> bool:
    return all(_empty(value) for value in values)


def validate_v24_autonomy_harness(root: Path) -> tuple[ValidationResult, dict[str, Any]]:
    started = time.perf_counter()
    root = root.resolve()
    issues: list[ValidationIssue] = []

    def issue(code: str, path: str, detail: str) -> None:
        issues.append(ValidationIssue(code, path, detail))

    try:
        state = ControlStore(
            root / "registries/v2/control_state.yaml",
            object_store=ObjectStore(root / "registries/v2/objects"),
        ).load()
    except Exception as exc:
        state = {}
        issue("control_state", "registries/v2/control_state.yaml", str(exc))

    harness = state.get("harness", {})
    scientific = state.get("scientific", {})
    cursor = state.get("cursor", {})
    if harness.get("status") != "ready" or harness.get("real_research_started") is not False:
        issue("harness_ready", "registries/v2/control_state.yaml", "harness is not ready")
    if scientific.get("status") != "not_started":
        issue("scientific_status", "registries/v2/control_state.yaml", "science already started")
    if not _all_empty(
        scientific.get(field)
        for field in (
            "root_mission_id",
            "epoch_id",
            "selected_bundle_id",
            "hypothesis_object_ids",
            "trial_receipt_ids",
            "negative_memory_object_ids",
            "ingredient_object_ids",
            "candidate_object_ids",
            "holdout_reveals",
        )
    ):
        issue("scientific_not_empty", "registries/v2/control_state.yaml", "scientific refs exist")
    if cursor.get("next_action", {}).get("kind") != "await_new_root_goal":
        issue("next_action", "registries/v2/control_state.yaml", "not awaiting a new root goal")
    if state.get("reentry", {}).get("active_job") is not None:
        issue("active_job", "registries/v2/control_state.yaml", "active job remains")
    if state.get("holdout", {}).get("reveal_count") != 0:
        issue("holdout", "registries/v2/control_state.yaml", "holdout was revealed")
    if state.get("claim", {}).get("current_level") != "none":
        issue("claim", "registries/v2/control_state.yaml", "scientific claim remains")

    for relative in SCIENTIFIC_SURFACES:
        try:
            text = (root / relative).read_text(encoding="ascii")
            for pattern in FORBIDDEN_TOKENS:
                if pattern.search(text):
                    issue("scientific_inheritance", relative, pattern.pattern)
        except Exception as exc:
            issue("scientific_surface", relative, str(exc))

    try:
        index = yaml.safe_load((root / SCIENTIFIC_SURFACES[0]).read_text(encoding="ascii"))
        research_map = yaml.safe_load((root / SCIENTIFIC_SURFACES[1]).read_text(encoding="ascii"))
        if index.get("status") != "not_started" or index.get("scientific_origin") != "v2_current":
            issue("scientific_index", SCIENTIFIC_SURFACES[0], "index is not empty-ready")
        if any(index.get("counts", {}).values()) or index.get("selected_bundle_id") is not None:
            issue("scientific_index", SCIENTIFIC_SURFACES[0], "index contains scientific content")
        if research_map.get("axes") != {} or research_map.get("coverage_audits") != []:
            issue("research_map", SCIENTIFIC_SURFACES[1], "research map is not empty")
        for path in index.get("ledgers", {}).values():
            ledger = root / path
            if ledger.exists() and ledger.read_bytes() != b"":
                issue("scientific_ledger", path, "active scientific ledger is not empty")
    except Exception as exc:
        issue("scientific_registry", "registries/v2/scientific", str(exc))

    try:
        runtime = yaml.safe_load(
            (root / "registries/v2/runtime_data_eligibility.yaml").read_text(encoding="ascii")
        )
        if runtime.get("sources") != {}:
            issue("runtime_registry", "registries/v2/runtime_data_eligibility.yaml", "sources exist")
    except Exception as exc:
        issue("runtime_registry", "registries/v2/runtime_data_eligibility.yaml", str(exc))

    try:
        if load_program_registry(root).scientific_seed_eligible:
            issue("program_seed", "configs/v2/program_registry.yaml", "fixtures may seed research")
    except Exception as exc:
        issue("program_registry", "configs/v2/program_registry.yaml", str(exc))

    try:
        receipt = ObjectStore(root / "registries/v2/objects").get(
            harness.get("ready_receipt_object_id")
        )["payload"]
        if receipt.get("real_research_started") is not False or any(
            receipt.get("scientific_ledger_deltas", {}).values()
        ):
            issue("research_delta", "registries/v2/objects", "real scientific delta exists")
        baseline = receipt.get("baseline_commit")
        tracked = subprocess.run(
            ["git", "diff", "--name-only", str(baseline), "--"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        forbidden_prefixes = (
            "campaigns/v2/",
            "data/",
            "artifacts/",
            "src/axiom_rift/v2/mt5/",
            "src/axiom_rift/v2/materialization/",
        )
        forbidden_suffixes = (
            "scientific/hypothesis_ledger.jsonl",
            "scientific/trial_ledger.jsonl",
            "scientific/negative_memory_ledger.jsonl",
            "scientific/ingredient_ledger.jsonl",
            "scientific/candidate_ledger.jsonl",
        )
        for changed in sorted(set(tracked + untracked)):
            normalized = changed.replace("\\", "/")
            if normalized.startswith(forbidden_prefixes) or normalized.endswith(
                forbidden_suffixes
            ):
                issue("real_research_path_delta", normalized, "reinforcement touched research evidence")
    except Exception as exc:
        issue("ready_receipt", "registries/v2/objects", str(exc))

    duration = time.perf_counter() - started
    if duration > 30:
        issue("duration", "configs/v2/validation.yaml", f"validator took {duration:.6f}s")
    result = ValidationResult("v2-4-autonomy-harness", tuple(issues))
    identity = autonomy_validation_identity(root)
    receipt = {
        "schema": "axiom_rift_v2_4_autonomy_validation_receipt_v1",
        **identity,
        "duration_seconds": duration,
        "outcome": "pass" if result.ok else "fail",
        "issues": [item.to_dict() for item in result.issues],
        "evidence_jobs_launched": False,
        "real_research_started": False,
        "hard_ceiling_seconds": 30,
        "claim_ceiling": "none",
    }
    return result, receipt
