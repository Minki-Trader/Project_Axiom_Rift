"""Canonical architecture baseline for US500 source eligibility."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research import us500_source as source_module
from axiom_rift.research import (
    us500_source_eligibility_validation as validator_module,
)
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID, ROLLING_SPLIT_SHA256
from axiom_rift.research.sources import (
    MT5_ABSOLUTE_TIME_AUTHORITY,
    MT5_EPOCH_COORDINATE,
    MT5_OFFSET_POLICY,
    MT5_SESSION_TIME_AUTHORITY,
)
from axiom_rift.research.us500_source import us500_source_contract


_THIS_FILE = Path(__file__).resolve()
_CLOCK_CONTRACT = (
    "clock:MT5_epoch_coordinate:completed_m5:"
    "absolute_time_authority_unknown:"
    "broker_session_timezone_DST_authority_unknown:"
    "no_offset_or_shift_inference:source_audit_v2"
)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def us500_source_chassis_implementation_sha256() -> str:
    return _file_sha256(_THIS_FILE)


def us500_source_implementation_sha256() -> str:
    return _file_sha256(Path(source_module.__file__).resolve())


def us500_source_validator_implementation_sha256() -> str:
    return _file_sha256(Path(validator_module.__file__).resolve())


def us500_source_baseline() -> ExecutableSpec:
    chassis_digest = us500_source_chassis_implementation_sha256()
    source_digest = us500_source_implementation_sha256()
    validator_digest = us500_source_validator_implementation_sha256()
    contract = us500_source_contract()
    source = ComponentSpec(
        display_name="FPMarkets US500 reconstruction-only source eligibility",
        protocol="external_source.fpmarkets_us500_m5.v2",
        implementation=(
            "axiom_rift.research.us500_source.us500_source_contract"
            f"@sha256:{source_digest}"
        ),
        spec={
            "absolute_time_authority": MT5_ABSOLUTE_TIME_AUTHORITY,
            "broker_session_timezone_dst_authority": MT5_SESSION_TIME_AUTHORITY,
            "eligibility_transitions": [
                "historical_audit",
                "runtime_availability_proof",
            ],
            "historical_performance_authority": False,
            "offset_policy": MT5_OFFSET_POLICY,
            "performance_allowed": False,
            "runtime_identifier": "US500",
            "source_contract_id": contract.source_contract_id,
            "time_coordinate": MT5_EPOCH_COORDINATE,
        },
    )
    label = ComponentSpec(
        display_name="source eligibility no-target label",
        protocol="label.source_eligibility_no_target.v1",
        implementation=(
            "axiom_rift.research.us500_source_chassis.us500_source_baseline"
            f"@sha256:{chassis_digest}"
        ),
        spec={"performance_label": False},
        semantic_dependencies=(source.identity,),
    )
    decision = ComponentSpec(
        display_name="source eligibility fact validator",
        protocol="model.source_eligibility_fact_validator.v2",
        implementation=(
            "axiom_rift.research.us500_source_eligibility_validation."
            f"SourceEligibilityValidator@sha256:{validator_digest}"
        ),
        spec={"performance_decision": False},
        semantic_dependencies=(label.identity,),
    )
    entry = ComponentSpec(
        display_name="source eligibility no-entry policy",
        protocol="trade.source_eligibility_no_entry.v1",
        implementation=(
            "axiom_rift.research.us500_source_chassis.us500_source_baseline"
            f"@sha256:{chassis_digest}"
        ),
        spec={"orders_allowed": False},
        semantic_dependencies=(decision.identity,),
    )
    lifecycle = ComponentSpec(
        display_name="source eligibility no-position lifecycle",
        protocol="lifecycle.source_eligibility_no_position.v1",
        implementation=(
            "axiom_rift.research.us500_source_chassis.us500_source_baseline"
            f"@sha256:{chassis_digest}"
        ),
        spec={"positions_allowed": False},
        semantic_dependencies=(entry.identity,),
    )
    execution = ComponentSpec(
        display_name="local MT5 US500 source probe",
        protocol="execution.local_mt5_source_probe.v2",
        implementation=(
            "axiom_rift.research.us500_source.probe_us500_runtime"
            f"@sha256:{source_digest}"
        ),
        spec={"performance_execution": False, "runtime_symbol": "US500"},
        semantic_dependencies=(lifecycle.identity,),
    )
    portfolio = ComponentSpec(
        display_name="US500 eligibility-only source boundary",
        protocol="portfolio.source_eligibility_only.v1",
        implementation=(
            "axiom_rift.research.us500_source_chassis.us500_source_baseline"
            f"@sha256:{chassis_digest}"
        ),
        spec={"performance_allowed": False},
        semantic_dependencies=(execution.identity,),
    )
    return ExecutableSpec(
        display_name="US500 reconstruction-only source eligibility baseline",
        components=(source, label, decision, entry, lifecycle, execution, portfolio),
        parameters={"source_state": "context_only"},
        data_contract=f"data:{OBSERVED_MATERIAL_ID}",
        split_contract=f"split:{ROLLING_SPLIT_SHA256}:source_audit_boundary",
        clock_contract=_CLOCK_CONTRACT,
        cost_contract="cost:not_applicable_source_eligibility_v1",
        engine_contract=(
            "engine:us500_source_eligibility_v2:"
            f"python{'.'.join(str(value) for value in sys.version_info[:3])}:"
            f"chassis_{chassis_digest}:source_{source_digest}:"
            f"validator_{validator_digest}"
        ),
    )


__all__ = [
    "us500_source_baseline",
    "us500_source_chassis_implementation_sha256",
    "us500_source_implementation_sha256",
    "us500_source_validator_implementation_sha256",
]
