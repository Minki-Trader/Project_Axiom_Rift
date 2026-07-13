"""Typed stale-receipt and same-semantics recertification facts for US500."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.research.sources import (
    SourceContract,
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
    SourceType,
)
from axiom_rift.research.us500_source import (
    derive_runtime_facts,
    us500_source_contract,
)


_THIS_FILE = Path(__file__).resolve()
DRIFT_FACTS = {
    "changed_surface": "runtime_eligibility_receipt_age",
    "dependent_action": "issue_source_permit",
    "observed_change": "eligibility_receipt_stale",
}
RECERTIFICATION_FACTS = {
    "mapping_parity": True,
    "schema_field_clock_parity": True,
    "semantic_equivalence": True,
}


def us500_recertification_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source timestamp is timezone naive")
    return parsed.astimezone(timezone.utc)


def contract_from_payload(payload: Mapping[str, Any]) -> SourceContract:
    return SourceContract(
        display_name="US500 source recertification projection",
        canonical_instrument=payload["canonical_instrument"],
        runtime_identifier=payload["runtime_identifier"],
        source_type=SourceType(payload["source_type"]),
        instrument_semantics=payload["instrument_semantics"],
        mapping_semantics=payload["mapping_semantics"],
        schema_semantics=payload["schema_semantics"],
        field_semantics=payload["field_semantics"],
        clock_semantics=payload["clock_semantics"],
        availability_semantics=payload["availability_semantics"],
    )


def receipt_from_payload(payload: Mapping[str, Any]) -> SourceEligibilityReceipt:
    return SourceEligibilityReceipt(
        source_contract_id=payload["source_contract_id"],
        evidence=SourceTransitionEvidence(payload["evidence"]),
        producer_completion_id=payload["producer_completion_id"],
        observed_at_utc=payload["observed_at_utc"],
        artifact_hashes=tuple(payload["artifact_hashes"]),
        facts=payload["facts"],
    )


def source_recertification_plan(transition_evidence: str) -> dict[str, Any]:
    if transition_evidence == SourceTransitionEvidence.DRIFT.value:
        required = [
            "contract",
            "eligibility_receipt_id",
            "facts",
            "observed_at_utc",
            "receipt",
            "receipt_age_seconds",
            "schema",
            "source_contract_id",
            "source_state_record_id",
            "source_state_status",
        ]
    elif transition_evidence == SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value:
        required = [
            "contract",
            "eligibility_receipt_id",
            "facts",
            "observed_at_utc",
            "receipt",
            "runtime_probe",
            "schema",
            "source_contract_id",
            "source_state_record_id",
            "source_state_status",
        ]
    else:
        raise ValueError("US500 recertification transition is not registered")
    return {
        "performance_allowed": False,
        "required_measurement_fields": required,
        "schema": "us500_source_recertification_plan.v1",
        "source_contract_id": us500_source_contract().source_contract_id,
        "transition_evidence": transition_evidence,
    }


def source_recertification_plan_hash(transition_evidence: str) -> str:
    return sha256(canonical_bytes(source_recertification_plan(transition_evidence))).hexdigest()


def build_drift_measurement(
    *,
    source_state_record_id: str,
    source_state_status: str,
    source_state_payload: Mapping[str, Any],
    observed_at_utc: str,
) -> dict[str, Any]:
    contract_payload = source_state_payload["contract"]
    receipt_payload = source_state_payload["receipt"]
    if not isinstance(contract_payload, Mapping) or not isinstance(receipt_payload, Mapping):
        raise ValueError("current US500 source state lacks contract or receipt")
    contract = contract_from_payload(contract_payload)
    receipt = receipt_from_payload(receipt_payload)
    age_seconds = int((_utc(observed_at_utc) - _utc(receipt.observed_at_utc)).total_seconds())
    value = {
        "schema": "us500_source_drift_measurement.v1",
        "source_state_record_id": source_state_record_id,
        "source_state_status": source_state_status,
        "source_contract_id": contract.source_contract_id,
        "contract": contract.to_identity_payload(),
        "eligibility_receipt_id": receipt.identity,
        "receipt": receipt.to_identity_payload(),
        "observed_at_utc": observed_at_utc,
        "receipt_age_seconds": age_seconds,
        "facts": dict(DRIFT_FACTS),
    }
    return parse_canonical(canonical_bytes(value))


def build_recertification_measurement(
    *,
    source_state_record_id: str,
    source_state_status: str,
    source_state_payload: Mapping[str, Any],
    runtime_probe: Mapping[str, Any],
) -> dict[str, Any]:
    contract_payload = source_state_payload["contract"]
    receipt_payload = source_state_payload["receipt"]
    if not isinstance(contract_payload, Mapping) or not isinstance(receipt_payload, Mapping):
        raise ValueError("suspended US500 source state lacks contract or receipt")
    contract = contract_from_payload(contract_payload)
    receipt = receipt_from_payload(receipt_payload)
    proposed = us500_source_contract()
    runtime_facts = derive_runtime_facts(runtime_probe)
    if any(
        runtime_facts[name] is not True
        for name in runtime_facts
        if name != "latency_ms"
    ):
        raise ValueError("US500 runtime probe is not eligible for recertification")
    facts = {
        "semantic_equivalence": contract.identity == proposed.identity,
        "mapping_parity": contract.mapping_identity == proposed.mapping_identity,
        "schema_field_clock_parity": (
            contract.schema_identity == proposed.schema_identity
            and contract.field_identity == proposed.field_identity
            and contract.clock_identity == proposed.clock_identity
        ),
    }
    value = {
        "schema": "us500_source_recertification_measurement.v1",
        "source_state_record_id": source_state_record_id,
        "source_state_status": source_state_status,
        "source_contract_id": contract.source_contract_id,
        "contract": contract.to_identity_payload(),
        "eligibility_receipt_id": receipt.identity,
        "receipt": receipt.to_identity_payload(),
        "observed_at_utc": runtime_probe["observed_at_utc"],
        "runtime_probe": dict(runtime_probe),
        "facts": facts,
    }
    return parse_canonical(canonical_bytes(value))


__all__ = [
    "DRIFT_FACTS",
    "RECERTIFICATION_FACTS",
    "build_drift_measurement",
    "build_recertification_measurement",
    "contract_from_payload",
    "receipt_from_payload",
    "source_recertification_plan",
    "source_recertification_plan_hash",
    "us500_recertification_implementation_sha256",
]
