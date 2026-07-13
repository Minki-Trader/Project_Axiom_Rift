"""Canonical architecture baseline for US500 source eligibility."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256
from axiom_rift.research.us500_source import us500_source_contract


_THIS_FILE = Path(__file__).resolve()


def us500_source_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def us500_source_baseline() -> ExecutableSpec:
    contract = us500_source_contract()
    source = ComponentSpec(display_name="FPMarkets US500 point-in-time source eligibility", protocol="external_source.fpmarkets_us500_m5.v1", implementation=f"axiom_rift.research.us500_source.us500_source_contract@sha256:{us500_source_chassis_implementation_sha256()}", spec={"source_contract_id": contract.source_contract_id, "runtime_identifier": "US500", "performance_allowed": False, "eligibility_transitions": ["historical_audit", "runtime_availability_proof"]})
    label = ComponentSpec(display_name="source eligibility no-target label", protocol="label.source_eligibility_no_target.v1", implementation=f"axiom_rift.research.us500_source_chassis.us500_source_baseline@sha256:{us500_source_chassis_implementation_sha256()}", spec={"performance_label": False}, semantic_dependencies=(source.identity,))
    decision = ComponentSpec(display_name="source eligibility fact validator", protocol="model.source_eligibility_fact_validator.v1", implementation=f"axiom_rift.research.us500_source_eligibility_validation.SourceEligibilityValidator@sha256:{us500_source_chassis_implementation_sha256()}", spec={"performance_decision": False}, semantic_dependencies=(label.identity,))
    entry = ComponentSpec(display_name="source eligibility no-entry policy", protocol="trade.source_eligibility_no_entry.v1", implementation=f"axiom_rift.research.us500_source_chassis.us500_source_baseline@sha256:{us500_source_chassis_implementation_sha256()}", spec={"orders_allowed": False}, semantic_dependencies=(decision.identity,))
    lifecycle = ComponentSpec(display_name="source eligibility no-position lifecycle", protocol="lifecycle.source_eligibility_no_position.v1", implementation=f"axiom_rift.research.us500_source_chassis.us500_source_baseline@sha256:{us500_source_chassis_implementation_sha256()}", spec={"positions_allowed": False}, semantic_dependencies=(entry.identity,))
    execution = ComponentSpec(display_name="local MT5 US500 source probe", protocol="execution.local_mt5_source_probe.v1", implementation=f"axiom_rift.research.us500_source.probe_us500_runtime@sha256:{us500_source_chassis_implementation_sha256()}", spec={"performance_execution": False, "runtime_symbol": "US500"}, semantic_dependencies=(lifecycle.identity,))
    portfolio = ComponentSpec(display_name="US500 eligibility-only source boundary", protocol="portfolio.source_eligibility_only.v1", implementation=f"axiom_rift.research.us500_source_chassis.us500_source_baseline@sha256:{us500_source_chassis_implementation_sha256()}", spec={"performance_allowed": False}, semantic_dependencies=(execution.identity,))
    return ExecutableSpec(display_name="US500 source eligibility baseline", components=(source, label, decision, entry, lifecycle, execution, portfolio), parameters={"source_state": "eligibility_pending"}, data_contract=f"data:{OBSERVED_MATERIAL_ID}", split_contract=f"split:{ROLLING_SPLIT_SHA256}:source_audit_boundary", clock_contract="clock:mt5_epoch_utc_completed_m5_source_audit_v1", cost_contract="cost:not_applicable_source_eligibility_v1", engine_contract=f"engine:us500_source_eligibility_v1:python{'.'.join(str(value) for value in sys.version_info[:3])}:chassis_{us500_source_chassis_implementation_sha256()}")


__all__ = ["us500_source_baseline", "us500_source_chassis_implementation_sha256"]
