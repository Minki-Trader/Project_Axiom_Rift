"""Release-time reuse of runtime evidence across source receipt renewal.

Runtime evidence is bound to the exact source receipt used at engine entry.  A
later Release needs a fresh readiness receipt, but a readiness-only renewal
must not erase an already completed, unchanged runtime success.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.sources import (
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


_SOURCE_CONTRACT_FIELDS = (
    "availability_identity",
    "clock_identity",
    "contract",
    "contract_hash",
    "field_identity",
    "mapping_identity",
    "schema_identity",
)

# These values describe liveness renewal only.  Unknown values fail closed so
# semantic, mapping, schema, clock, terminal-build, or engine-build drift cannot
# be hidden behind a generic same-semantics recertification receipt.
_READINESS_ONLY_DRIFT_SURFACES = frozenset(
    {
        "availability",
        "runtime_availability",
        "runtime_eligibility_receipt_age",
    }
)


class RuntimeSourceReadinessError(ValueError):
    """Typed, completion-scoped source evidence invalidation."""

    def __init__(self, *, code: str, source_contract_id: str, detail: str) -> None:
        self.code = _ascii("source readiness error code", code)
        self.source_contract_id = _ascii(
            "source readiness contract id", source_contract_id
        )
        self.detail = _ascii("source readiness error detail", detail)
        super().__init__(
            f"{self.code} for {self.source_contract_id}: {self.detail}"
        )


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _utc(name: str, value: object) -> datetime:
    text = _ascii(name, value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt(record: IndexRecord) -> SourceEligibilityReceipt:
    payload = record.payload.get("receipt")
    if not isinstance(payload, Mapping):
        raise ValueError("source state receipt is absent")
    receipt = SourceEligibilityReceipt(
        source_contract_id=payload["source_contract_id"],
        evidence=SourceTransitionEvidence(payload["evidence"]),
        producer_completion_id=payload["producer_completion_id"],
        observed_at_utc=payload["observed_at_utc"],
        artifact_hashes=tuple(payload["artifact_hashes"]),
        facts=payload["facts"],
    )
    if (
        receipt.identity != record.payload.get("evidence_receipt_id")
        or receipt.to_identity_payload() != payload
    ):
        raise ValueError("source state receipt identity is invalid")
    return receipt


def _require_state(
    record: IndexRecord | None,
    *,
    source_contract_id: str,
    sequence: int,
    expected_contract: Mapping[str, Any],
) -> IndexRecord:
    if type(sequence) is not int or sequence < 1:
        raise ValueError("source state sequence must be a positive integer")
    if (
        record is None
        or record.kind != "source-state"
        or record.subject != f"Source:{source_contract_id}"
        or record.fingerprint != source_contract_id
        or record.event_stream != f"source:{source_contract_id}"
        or record.event_sequence != sequence
        or record.payload.get("ordinal") != sequence
        or any(
            record.payload.get(name) != expected_contract.get(name)
            for name in _SOURCE_CONTRACT_FIELDS
        )
    ):
        raise ValueError("source state lineage changed contract semantics")
    expected_id = canonical_digest(
        domain="source-state",
        payload={
            "source_id": source_contract_id,
            "state": record.status,
            "ordinal": sequence,
            "evidence_receipt_id": record.payload.get("evidence_receipt_id"),
        },
    )
    if record.record_id != expected_id:
        raise ValueError("source state lineage identity is non-canonical")
    return record


def _ttl_seconds(current_state: IndexRecord) -> int:
    contract = current_state.payload.get("contract")
    availability = (
        None if not isinstance(contract, Mapping) else contract.get("availability_semantics")
    )
    if not isinstance(availability, Mapping):
        raise ValueError("source availability contract is absent")
    value = availability.get(
        "eligibility_receipt_ttl_seconds",
        availability.get("causal_ttl_seconds"),
    )
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("source eligibility receipt TTL is invalid")
    return value


def _invalidation_code(changed_surface: str) -> str:
    normalized = changed_surface.lower()
    if "mapping" in normalized:
        return "mapping_drift_invalidates_completion"
    if "build" in normalized:
        return "build_drift_invalidates_completion"
    if any(
        token in normalized
        for token in ("semantic", "schema", "field", "clock", "instrument")
    ):
        return "semantic_drift_invalidates_completion"
    return "untyped_drift_invalidates_completion"


def current_readiness_payload(
    *,
    source_contract_id: str,
    current_state: IndexRecord,
) -> dict[str, Any]:
    """Return the separately bound current Release readiness receipt."""

    try:
        receipt = _receipt(current_state)
        ttl_seconds = _ttl_seconds(current_state)
        valid_through = _utc("source receipt observed_at_utc", receipt.observed_at_utc)
        valid_through += timedelta(seconds=ttl_seconds)
        if (
            current_state.status != "runtime_eligible"
            or receipt.source_contract_id != source_contract_id
            or receipt.evidence
            not in {
                SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            }
        ):
            raise ValueError("current source state is not runtime readiness")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeSourceReadinessError(
            code="current_readiness_invalid",
            source_contract_id=source_contract_id,
            detail="current receipt is malformed or ineligible",
        ) from exc
    return {
        "mapping_identity": current_state.payload["mapping_identity"],
        "receipt_id": receipt.identity,
        "source_contract_id": source_contract_id,
        "source_state_record_id": current_state.record_id,
        "valid_through_utc": _format_utc(valid_through),
    }


def validate_completion_receipt_reuse(
    *,
    index: LocalIndex,
    source_contract_id: str,
    candidate_mapping_identity: str,
    completion_receipt_ids: Sequence[str],
    completion_source_snapshot: Mapping[str, Any],
    current_state: IndexRecord,
    engine_entry_authority_sequence: int,
    completion_authority_sequence: int,
    engine_entry_occurred_at_utc: str,
    completion_occurred_at_utc: str,
    verify_artifact: Callable[[str], object],
) -> dict[str, Any]:
    """Prove one completion receipt and its safe path to current readiness."""

    _ascii("source contract id", source_contract_id)
    _ascii("candidate mapping identity", candidate_mapping_identity)
    if (
        type(engine_entry_authority_sequence) is not int
        or type(completion_authority_sequence) is not int
        or engine_entry_authority_sequence < 1
        or completion_authority_sequence < engine_entry_authority_sequence
    ):
        raise ValueError(
            "runtime completion authority sequences must be positive integers"
        )
    receipt_ids = frozenset(completion_receipt_ids)
    if (
        not receipt_ids
        or len(receipt_ids) != len(tuple(completion_receipt_ids))
        or any(type(value) is not str for value in receipt_ids)
    ):
        raise RuntimeSourceReadinessError(
            code="completion_receipt_inventory_invalid",
            source_contract_id=source_contract_id,
            detail="completion receipts are absent or duplicated",
        )
    try:
        if set(completion_source_snapshot) != {
            "mapping_identity",
            "source_contract_id",
            "source_receipt_id",
            "source_state_record_id",
        }:
            raise ValueError("completion source snapshot schema is invalid")
        snapshot_source_id = completion_source_snapshot.get(
            "source_contract_id"
        )
        snapshot_receipt_id = completion_source_snapshot.get(
            "source_receipt_id"
        )
        snapshot_state_id = completion_source_snapshot.get(
            "source_state_record_id"
        )
        if (
            snapshot_source_id != source_contract_id
            or completion_source_snapshot.get("mapping_identity")
            != candidate_mapping_identity
            or type(snapshot_receipt_id) is not str
            or snapshot_receipt_id not in receipt_ids
            or type(snapshot_state_id) is not str
        ):
            raise ValueError("completion source snapshot is cross-source or stale")
        if (
            current_state.status != "runtime_eligible"
            or current_state.payload.get("mapping_identity")
            != candidate_mapping_identity
        ):
            raise ValueError("candidate mapping differs from current source")
        entry_state = index.get("source-state", snapshot_state_id)
        entry_sequence = entry_state.event_sequence
        current_sequence = current_state.event_sequence
        if type(entry_sequence) is not int or type(current_sequence) is not int:
            raise ValueError("source state sequence is absent")
        expected_contract = {
            name: current_state.payload.get(name) for name in _SOURCE_CONTRACT_FIELDS
        }
        _require_state(
            entry_state,
            source_contract_id=source_contract_id,
            sequence=entry_sequence,
            expected_contract=expected_contract,
        )
        entry_receipt = _receipt(entry_state)
        if (
            entry_receipt.source_contract_id != source_contract_id
            or entry_receipt.identity != snapshot_receipt_id
            or entry_receipt.evidence
            not in {
                SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
                SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION,
            }
        ):
            raise ValueError("completion entry receipt is not runtime eligible")
        for artifact_hash in entry_receipt.artifact_hashes:
            verify_artifact(artifact_hash)
        if (
            type(entry_state.authority_sequence) is not int
            or type(engine_entry_authority_sequence) is not int
            or type(completion_authority_sequence) is not int
            or not (
                entry_state.authority_sequence
                < engine_entry_authority_sequence
                <= completion_authority_sequence
            )
        ):
            raise ValueError("completion receipt was not authoritative before entry")
        next_state = index.event_record(
            f"source:{source_contract_id}", entry_sequence + 1
        )
        if (
            next_state is not None
            and type(next_state.authority_sequence) is int
            and next_state.authority_sequence <= completion_authority_sequence
        ):
            raise RuntimeSourceReadinessError(
                code="receipt_not_active_through_completion",
                source_contract_id=source_contract_id,
                detail="source left the exact entry receipt before completion",
            )

        observed_at = _utc(
            "completion receipt observed_at_utc", entry_receipt.observed_at_utc
        )
        entered_at = _utc(
            "runtime engine entry occurred_at_utc", engine_entry_occurred_at_utc
        )
        completed_at = _utc(
            "runtime completion occurred_at_utc", completion_occurred_at_utc
        )
        valid_through = observed_at + timedelta(seconds=_ttl_seconds(current_state))
        if not observed_at <= entered_at <= completed_at <= valid_through:
            raise RuntimeSourceReadinessError(
                code="receipt_not_fresh_through_completion",
                source_contract_id=source_contract_id,
                detail="entry receipt TTL does not cover engine entry through completion",
            )

        drift_records: list[str] = []
        recertification_records: list[str] = []
        sequence = entry_sequence
        while sequence < current_sequence:
            suspended = _require_state(
                index.event_record(f"source:{source_contract_id}", sequence + 1),
                source_contract_id=source_contract_id,
                sequence=sequence + 1,
                expected_contract=expected_contract,
            )
            restored = _require_state(
                index.event_record(f"source:{source_contract_id}", sequence + 2),
                source_contract_id=source_contract_id,
                sequence=sequence + 2,
                expected_contract=expected_contract,
            )
            drift_receipt = _receipt(suspended)
            recertification_receipt = _receipt(restored)
            if (
                suspended.status != "suspended"
                or suspended.payload.get("transition_evidence")
                != SourceTransitionEvidence.DRIFT.value
                or drift_receipt.evidence is not SourceTransitionEvidence.DRIFT
                or restored.status != "runtime_eligible"
                or restored.payload.get("transition_evidence")
                != SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION.value
                or recertification_receipt.evidence
                is not SourceTransitionEvidence.SAME_SEMANTICS_RECERTIFICATION
            ):
                raise ValueError("source recertification lineage is not exact")
            for receipt in (drift_receipt, recertification_receipt):
                if receipt.source_contract_id != source_contract_id:
                    raise ValueError("source recertification changed contract identity")
                for artifact_hash in receipt.artifact_hashes:
                    verify_artifact(artifact_hash)
            changed_surface = drift_receipt.fact_values().get("changed_surface")
            if (
                type(changed_surface) is not str
                or changed_surface not in _READINESS_ONLY_DRIFT_SURFACES
            ):
                surface = (
                    "unknown" if type(changed_surface) is not str else changed_surface
                )
                raise RuntimeSourceReadinessError(
                    code=_invalidation_code(surface),
                    source_contract_id=source_contract_id,
                    detail=(
                        f"old completion crossed non-readiness drift surface {surface!r}"
                    ),
                )
            drift_records.append(suspended.record_id)
            recertification_records.append(restored.record_id)
            sequence += 2
        if sequence != current_sequence or (
            current_state.record_id
            != index.event_record(f"source:{source_contract_id}", sequence).record_id
        ):
            raise ValueError("source recertification lineage does not reach readiness head")
        current_receipt = _receipt(current_state)
        disposition = (
            "exact_current_receipt"
            if entry_receipt.identity == current_receipt.identity
            else "unchanged_success_reused"
        )
        return {
            "completion_receipt_id": entry_receipt.identity,
            "completion_source_state_record_id": entry_state.record_id,
            "current_readiness_receipt_id": current_receipt.identity,
            "current_source_state_record_id": current_state.record_id,
            "disposition": disposition,
            "drift_state_record_ids": drift_records,
            "entry_occurred_at_utc": _format_utc(entered_at),
            "receipt_observed_at_utc": _format_utc(observed_at),
            "receipt_valid_through_utc": _format_utc(valid_through),
            "recertification_state_record_ids": recertification_records,
            "source_contract_id": source_contract_id,
        }
    except RuntimeSourceReadinessError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeSourceReadinessError(
            code="source_recertification_lineage_invalid",
            source_contract_id=source_contract_id,
            detail="completion receipt or recertification lineage is malformed",
        ) from exc


__all__ = [
    "RuntimeSourceReadinessError",
    "current_readiness_payload",
    "validate_completion_receipt_reuse",
]
