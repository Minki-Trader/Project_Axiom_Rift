"""Stable cache identity for activation checks, excluding receipt bookkeeping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.validation.activation import REQUIRED_CONTRACTS, _input_hashes, sha256_file
from axiom_rift.v2.validation.receipts import validation_key


def activation_validation_identity(root: Path, phase: str) -> dict[str, Any]:
    root = root.resolve()
    input_hashes = _input_hashes(root, phase)
    state = yaml.safe_load((root / "registries/v2/control_state.yaml").read_text(encoding="ascii"))
    input_hashes["registries/v2/control_state.yaml"] = sha256_payload(
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
    contract_hashes = {
        f"contracts/v2/{name}": sha256_file(root / "contracts" / "v2" / name)
        for name in REQUIRED_CONTRACTS
    }
    code_hash = sha256_file(root / "src/axiom_rift/v2/validation/activation.py")
    config_hashes = {
        "configs/v2/validation.yaml": sha256_file(root / "configs/v2/validation.yaml")
    }
    validator_id = f"axiom_rift_v2_activation_{phase}_v1"
    scope = sorted(input_hashes)
    return {
        "validator_id": validator_id,
        "validator_code_sha256": code_hash,
        "input_hashes": input_hashes,
        "config_hashes": config_hashes,
        "contract_hashes": contract_hashes,
        "scope": scope,
        "validation_key": validation_key(
            validator_id,
            code_hash,
            input_hashes,
            config_hashes,
            contract_hashes,
            scope,
        ),
    }
