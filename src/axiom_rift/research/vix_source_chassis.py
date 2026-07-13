"""Canonical no-trade architecture for FPMarkets VIX source eligibility."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256
from axiom_rift.research.vix_source import vix_source_contract


_THIS_FILE = Path(__file__).resolve()


def vix_source_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def vix_source_baseline() -> ExecutableSpec:
    implementation = vix_source_chassis_implementation_sha256()
    contract = vix_source_contract()
    source = ComponentSpec(
        display_name="FPMarkets VIX point-in-time source eligibility",
        protocol="external_source.fpmarkets_vix_m5.v1",
        implementation=(
            "axiom_rift.research.vix_source.vix_source_contract@sha256:"
            + implementation
        ),
        spec={
            "performance_allowed": False,
            "roll_semantics_must_be_audited": True,
            "runtime_identifier": "VIX",
            "source_contract_id": contract.source_contract_id,
        },
    )
    label = ComponentSpec(
        display_name="VIX source eligibility no-target label",
        protocol="label.source_eligibility_no_target.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={"performance_label": False},
        semantic_dependencies=(source.identity,),
    )
    decision = ComponentSpec(
        display_name="VIX source and roll fact validator",
        protocol="model.source_and_roll_eligibility_fact_validator.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={
            "performance_decision": False,
            "required_transitions": [
                "historical_coverage_and_roll_audit",
                "runtime_availability_proof",
            ],
        },
        semantic_dependencies=(label.identity,),
    )
    entry = ComponentSpec(
        display_name="VIX source eligibility no-entry policy",
        protocol="trade.source_eligibility_no_entry.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={"orders_allowed": False},
        semantic_dependencies=(decision.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="VIX source eligibility no-position lifecycle",
        protocol="lifecycle.source_eligibility_no_position.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={"positions_allowed": False},
        semantic_dependencies=(entry.identity,),
    )
    execution = ComponentSpec(
        display_name="local MT5 VIX source probe",
        protocol="execution.local_mt5_source_probe.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={"performance_execution": False, "runtime_symbol": "VIX"},
        semantic_dependencies=(lifecycle.identity,),
    )
    portfolio = ComponentSpec(
        display_name="VIX eligibility-only source boundary",
        protocol="portfolio.source_eligibility_only.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + implementation
        ),
        spec={"performance_allowed": False},
        semantic_dependencies=(execution.identity,),
    )
    return ExecutableSpec(
        display_name="VIX source eligibility baseline",
        components=(source, label, decision, entry, lifecycle, execution, portfolio),
        parameters={
            "roll_semantics_state": "unverified_pending_audit",
            "source_state": "eligibility_pending",
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:source_audit_boundary",
        clock_contract="clock:mt5_epoch_utc_completed_m5_source_audit_v1",
        cost_contract="cost:not_applicable_source_eligibility_v1",
        engine_contract=(
            "engine:vix_source_eligibility_v1:python"
            + ".".join(str(value) for value in sys.version_info[:3])
            + ":chassis_"
            + implementation
        ),
    )


__all__ = ["vix_source_baseline", "vix_source_chassis_implementation_sha256"]
