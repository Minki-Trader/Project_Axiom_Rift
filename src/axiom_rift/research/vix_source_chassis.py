"""Canonical no-trade architecture for FPMarkets VIX source eligibility."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import vix_source as source_module
from axiom_rift.research import vix_source_audit as audit_module
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256
from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
)
from axiom_rift.research.vix_source import vix_source_contract


_THIS_FILE = Path(__file__).resolve()
_CLOCK_CONTRACT = (
    "clock:MT5_epoch_coordinate:completed_m5:"
    "absolute_time_authority_unknown:"
    "broker_session_timezone_DST_authority_unknown:"
    "no_offset_or_shift_inference:source_audit_v2"
)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def vix_source_chassis_implementation_sha256() -> str:
    return _file_sha256(_THIS_FILE)


def vix_source_implementation_sha256() -> str:
    return _file_sha256(Path(source_module.__file__).resolve())


def vix_source_audit_implementation_sha256() -> str:
    return _file_sha256(Path(audit_module.__file__).resolve())


def vix_source_baseline() -> ExecutableSpec:
    chassis_digest = vix_source_chassis_implementation_sha256()
    source_digest = vix_source_implementation_sha256()
    audit_digest = vix_source_audit_implementation_sha256()
    contract = vix_source_contract()
    source = ComponentSpec(
        display_name="FPMarkets VIX context-only rolling source",
        protocol="external_source.fpmarkets_vix_m5.v2",
        implementation=(
            "axiom_rift.research.vix_source.vix_source_contract@sha256:"
            + source_digest
        ),
        spec={
            "absolute_time_authority": MT5_ABSOLUTE_TIME_AUTHORITY,
            "broker_session_timezone_dst_authority": MT5_SESSION_TIME_AUTHORITY,
            "evidence_state": "not_identifiable",
            "offset_policy": MT5_OFFSET_POLICY,
            "performance_allowed": False,
            "promotion_allowed": False,
            "roll_semantics_not_identifiable_from_current_surface": True,
            "runtime_identifier": "VIX",
            "source_contract_id": contract.source_contract_id,
            "source_state": "context_only",
            "time_coordinate": MT5_EPOCH_COORDINATE,
        },
    )
    label = ComponentSpec(
        display_name="VIX source eligibility no-target label",
        protocol="label.source_eligibility_no_target.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + chassis_digest
        ),
        spec={"performance_label": False},
        semantic_dependencies=(source.identity,),
    )
    decision = ComponentSpec(
        display_name="VIX context-only and not-identifiable fact boundary",
        protocol="model.source_and_roll_eligibility_fact_validator.v2",
        implementation=(
            "axiom_rift.research.vix_source_audit.audit_vix_source@sha256:"
            + audit_digest
        ),
        spec={
            "evidence_state": "not_identifiable",
            "performance_decision": False,
            "reopen_requires": [
                "independent_point_in_time_contract_map",
                "independent_roll_schedule",
                "independent_adjustment_methodology",
            ],
            "source_state": "context_only",
        },
        semantic_dependencies=(label.identity,),
    )
    entry = ComponentSpec(
        display_name="VIX source eligibility no-entry policy",
        protocol="trade.source_eligibility_no_entry.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + chassis_digest
        ),
        spec={"orders_allowed": False},
        semantic_dependencies=(decision.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="VIX source eligibility no-position lifecycle",
        protocol="lifecycle.source_eligibility_no_position.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + chassis_digest
        ),
        spec={"positions_allowed": False},
        semantic_dependencies=(entry.identity,),
    )
    execution = ComponentSpec(
        display_name="local MT5 VIX source probe",
        protocol="execution.local_mt5_source_probe.v2",
        implementation=(
            "axiom_rift.research.vix_source_audit.audit_vix_source@sha256:"
            + audit_digest
        ),
        spec={"performance_execution": False, "runtime_symbol": "VIX"},
        semantic_dependencies=(lifecycle.identity,),
    )
    portfolio = ComponentSpec(
        display_name="VIX context-only source boundary",
        protocol="portfolio.source_context_only.v1",
        implementation=(
            "axiom_rift.research.vix_source_chassis.vix_source_baseline@sha256:"
            + chassis_digest
        ),
        spec={"performance_allowed": False, "promotion_allowed": False},
        semantic_dependencies=(execution.identity,),
    )
    return ExecutableSpec(
        display_name="VIX context-only source boundary",
        components=(source, label, decision, entry, lifecycle, execution, portfolio),
        parameters={
            "roll_semantics_state": "not_identifiable",
            "source_state": "context_only",
        },
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:source_audit_boundary",
        clock_contract=_CLOCK_CONTRACT,
        cost_contract="cost:not_applicable_source_eligibility_v1",
        engine_contract=(
            "engine:vix_source_eligibility_v2:python"
            + ".".join(str(value) for value in sys.version_info[:3])
            + ":chassis_"
            + chassis_digest
            + ":source_"
            + source_digest
            + ":audit_"
            + audit_digest
        ),
    )


__all__ = [
    "vix_source_audit_implementation_sha256",
    "vix_source_baseline",
    "vix_source_chassis_implementation_sha256",
    "vix_source_implementation_sha256",
]
