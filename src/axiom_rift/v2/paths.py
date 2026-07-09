"""Canonical V2 paths kept separate from legacy active truth during bootstrap."""

from pathlib import Path

from axiom_rift.paths import PROJECT_ROOT


V2_CONTRACT_DIR = PROJECT_ROOT / "contracts" / "v2"
V2_CONFIG_DIR = PROJECT_ROOT / "configs" / "v2"
V2_REGISTRY_DIR = PROJECT_ROOT / "registries" / "v2"
V2_GOAL_SPEC = V2_CONTRACT_DIR / "goal_spec.md"
V2_GOAL_PACKET = V2_CONTRACT_DIR / "goal_packet.yaml"
V2_VALIDATION_CONFIG = V2_CONFIG_DIR / "validation.yaml"
V2_CONTROL_STATE = V2_REGISTRY_DIR / "control_state.yaml"
V2_OBJECT_DIR = V2_REGISTRY_DIR / "objects"
V2_HYPOTHESIS_LEDGER = V2_REGISTRY_DIR / "hypothesis_ledger.jsonl"
V2_EVIDENCE_LEDGER = V2_REGISTRY_DIR / "evidence_ledger.jsonl"
V2_MATERIAL_LEDGER = V2_REGISTRY_DIR / "material_ledger.jsonl"
V2_VALIDATION_RECEIPT_LEDGER = V2_REGISTRY_DIR / "validation_receipts.jsonl"
