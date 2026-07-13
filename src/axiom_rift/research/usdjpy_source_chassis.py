"""Canonical architecture baseline for USDJPY source eligibility."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256
from axiom_rift.research.usdjpy_source import usdjpy_source_contract


_THIS_FILE = Path(__file__).resolve()


def usdjpy_source_chassis_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def usdjpy_source_baseline() -> ExecutableSpec:
    digest = usdjpy_source_chassis_implementation_sha256()
    contract = usdjpy_source_contract()
    source = ComponentSpec(
        display_name="FPMarkets USDJPY point-in-time source eligibility",
        protocol="external_source.fpmarkets_usdjpy_m5.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source.usdjpy_source_contract"
            f"@sha256:{digest}"
        ),
        spec={
            "source_contract_id": contract.source_contract_id,
            "runtime_identifier": "USDJPY",
            "performance_allowed": False,
            "eligibility_transitions": [
                "historical_audit",
                "runtime_availability_proof",
            ],
        },
    )
    label = ComponentSpec(
        display_name="source eligibility no-target label",
        protocol="label.source_eligibility_no_target.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source_chassis.usdjpy_source_baseline"
            f"@sha256:{digest}"
        ),
        spec={"performance_label": False},
        semantic_dependencies=(source.identity,),
    )
    decision = ComponentSpec(
        display_name="source eligibility fact validator",
        protocol="model.source_eligibility_fact_validator.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source_eligibility_validation."
            f"SourceEligibilityValidator@sha256:{digest}"
        ),
        spec={"performance_decision": False},
        semantic_dependencies=(label.identity,),
    )
    entry = ComponentSpec(
        display_name="source eligibility no-entry policy",
        protocol="trade.source_eligibility_no_entry.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source_chassis.usdjpy_source_baseline"
            f"@sha256:{digest}"
        ),
        spec={"orders_allowed": False},
        semantic_dependencies=(decision.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="source eligibility no-position lifecycle",
        protocol="lifecycle.source_eligibility_no_position.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source_chassis.usdjpy_source_baseline"
            f"@sha256:{digest}"
        ),
        spec={"positions_allowed": False},
        semantic_dependencies=(entry.identity,),
    )
    execution = ComponentSpec(
        display_name="local MT5 USDJPY source probe",
        protocol="execution.local_mt5_source_probe.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source.probe_usdjpy_runtime"
            f"@sha256:{digest}"
        ),
        spec={"performance_execution": False, "runtime_symbol": "USDJPY"},
        semantic_dependencies=(lifecycle.identity,),
    )
    portfolio = ComponentSpec(
        display_name="USDJPY eligibility-only source boundary",
        protocol="portfolio.source_eligibility_only.v1",
        implementation=(
            "axiom_rift.research.usdjpy_source_chassis.usdjpy_source_baseline"
            f"@sha256:{digest}"
        ),
        spec={"performance_allowed": False},
        semantic_dependencies=(execution.identity,),
    )
    return ExecutableSpec(
        display_name="USDJPY source eligibility baseline",
        components=(source, label, decision, entry, lifecycle, execution, portfolio),
        parameters={"source_state": "eligibility_pending"},
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:source_audit_boundary",
        clock_contract="clock:mt5_epoch_utc_completed_m5_source_audit_v1",
        cost_contract="cost:not_applicable_source_eligibility_v1",
        engine_contract=(
            "engine:usdjpy_source_eligibility_v1:"
            f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"chassis_{digest}"
        ),
    )


__all__ = [
    "usdjpy_source_baseline",
    "usdjpy_source_chassis_implementation_sha256",
]
