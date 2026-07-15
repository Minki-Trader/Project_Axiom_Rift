"""Focused authority checks for a runtime-bound Job success completion.

Runtime entry is an observation, not an enduring capability.  A successful
completion must rejoin the same active candidate and exact source-state
snapshot, with every source still fresh, before any result packet is allowed
to become runtime evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from axiom_rift.runtime.source_lifecycle_coverage import (
    SourceLifecycleCoverageError,
    derive_source_lifecycle_coverage,
    require_source_lifecycle_coverage_ids,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class RuntimeSuccessAuthorityError(RuntimeError):
    """The runtime success basis changed after its authorized entry."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise RuntimeSuccessAuthorityError(f"{name} is not non-empty ASCII")
    return value


def _canonical_string_list(name: str, value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(
            type(item) is not str or not item or not item.isascii()
            for item in value
        )
        or value != sorted(set(value))
    ):
        raise RuntimeSuccessAuthorityError(
            f"runtime success {name} is not sorted and unique"
        )
    return tuple(value)


@dataclass(frozen=True, slots=True)
class RuntimeSourceSnapshotRow:
    """One source-keyed runtime state observation."""

    source_contract_id: str
    source_receipt_id: str
    source_state_record_id: str
    mapping_identity: str

    def payload(self) -> dict[str, str]:
        return {
            "mapping_identity": self.mapping_identity,
            "source_contract_id": self.source_contract_id,
            "source_receipt_id": self.source_receipt_id,
            "source_state_record_id": self.source_state_record_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeSourceSnapshot:
    """Exact current source heads used by one runtime authority boundary."""

    source_contract_ids: tuple[str, ...]
    source_receipt_ids: tuple[str, ...]
    source_state_record_ids: tuple[str, ...]
    rows: tuple[RuntimeSourceSnapshotRow, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "source_receipt_ids": list(self.source_receipt_ids),
            "source_snapshot_rows": [row.payload() for row in self.rows],
            "source_state_record_ids": list(self.source_state_record_ids),
        }


def current_runtime_source_snapshot(
    *,
    index: LocalIndex,
    source_contract_ids: tuple[str, ...],
    require_runtime_source: Callable[[LocalIndex, str], IndexRecord],
) -> RuntimeSourceSnapshot:
    """Read exact fresh current source heads through the writer's typed gate."""

    if source_contract_ids != tuple(sorted(set(source_contract_ids))):
        raise RuntimeSuccessAuthorityError(
            "runtime success source contract set is not canonical"
        )
    rows: list[RuntimeSourceSnapshotRow] = []
    for source_id in source_contract_ids:
        _ascii("runtime success source contract", source_id)
        source = require_runtime_source(index, source_id)
        head = index.event_head(f"source:{source_id}")
        receipt_id = source.payload.get("evidence_receipt_id")
        mapping_identity = source.payload.get("mapping_identity")
        if (
            head is None
            or head.record_kind != "source-state"
            or head.record_id != source.record_id
            or head.sequence != source.event_sequence
            or source.kind != "source-state"
            or source.status != "runtime_eligible"
            or source.subject != f"Source:{source_id}"
            or source.fingerprint != source_id
            or source.event_stream != f"source:{source_id}"
            or type(receipt_id) is not str
            or not receipt_id
            or not receipt_id.isascii()
            or type(mapping_identity) is not str
            or not mapping_identity
            or not mapping_identity.isascii()
        ):
            raise RuntimeSuccessAuthorityError(
                "runtime success source receipt/head is not the exact current state"
            )
        rows.append(
            RuntimeSourceSnapshotRow(
                source_contract_id=source_id,
                source_receipt_id=receipt_id,
                source_state_record_id=source.record_id,
                mapping_identity=mapping_identity,
            )
        )
    receipt_ids = [row.source_receipt_id for row in rows]
    state_ids = [row.source_state_record_id for row in rows]
    if len(set(receipt_ids)) != len(receipt_ids):
        raise RuntimeSuccessAuthorityError(
            "runtime success source receipt set is ambiguous"
        )
    return RuntimeSourceSnapshot(
        source_contract_ids=source_contract_ids,
        source_receipt_ids=tuple(sorted(receipt_ids)),
        source_state_record_ids=tuple(sorted(state_ids)),
        rows=tuple(rows),
    )


def candidate_source_binding_snapshot(
    *,
    index: LocalIndex,
    candidate: IndexRecord,
    current: RuntimeSourceSnapshot,
) -> tuple[dict[str, str], ...]:
    """Validate the candidate's source-keyed freeze bindings.

    A same-semantics runtime recertification may change the current receipt, so
    the frozen eligibility receipt is preserved separately.  Mapping identity
    and source ownership must remain exact.
    """

    bindings = candidate.payload.get("source_bindings")
    if not isinstance(bindings, list):
        raise RuntimeSuccessAuthorityError(
            "runtime success candidate source bindings are absent"
        )
    expected_fields = {
        "eligibility_receipt_id",
        "mapping_identity",
        "source_contract_id",
        "source_state_record_id",
    }
    normalized: list[dict[str, str]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != expected_fields:
            raise RuntimeSuccessAuthorityError(
                "runtime success candidate source binding schema is invalid"
            )
        normalized.append(
            {
                name: _ascii(f"candidate source binding {name}", binding[name])
                for name in sorted(expected_fields)
            }
        )
    original_source_ids = tuple(
        item["source_contract_id"] for item in normalized
    )
    normalized.sort(key=lambda item: item["source_contract_id"])
    if (
        original_source_ids != tuple(sorted(set(original_source_ids)))
        or tuple(item["source_contract_id"] for item in normalized)
        != current.source_contract_ids
        or len(
            {item["eligibility_receipt_id"] for item in normalized}
        )
        != len(normalized)
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success candidate source binding set is ambiguous"
        )
    current_by_source = {
        row.source_contract_id: row for row in current.rows
    }
    if any(
        item["mapping_identity"]
        != current_by_source[item["source_contract_id"]].mapping_identity
        for item in normalized
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success candidate source mapping identity changed"
        )
    for item in normalized:
        source_id = item["source_contract_id"]
        frozen_state = index.get(
            "source-state", item["source_state_record_id"]
        )
        if (
            frozen_state is None
            or frozen_state.status != "runtime_eligible"
            or frozen_state.subject != f"Source:{source_id}"
            or frozen_state.fingerprint != source_id
            or frozen_state.event_stream != f"source:{source_id}"
            or frozen_state.payload.get("evidence_receipt_id")
            != item["eligibility_receipt_id"]
            or frozen_state.payload.get("mapping_identity")
            != item["mapping_identity"]
            or type(frozen_state.authority_sequence) is not int
            or type(candidate.authority_sequence) is not int
            or frozen_state.authority_sequence >= candidate.authority_sequence
        ):
            raise RuntimeSuccessAuthorityError(
                "runtime success candidate frozen source receipt is not source-keyed"
            )
    return tuple(normalized)


def candidate_job_execution_context(
    *,
    index: LocalIndex,
    candidate: IndexRecord,
    current: RuntimeSourceSnapshot,
    runtime_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the Writer-derived candidate and source execution context."""

    bindings = candidate_source_binding_snapshot(
        index=index,
        candidate=candidate,
        current=current,
    )
    executable = candidate.payload.get("executable")
    if not isinstance(executable, Mapping):
        raise RuntimeSuccessAuthorityError(
            "candidate execution context lacks its Executable manifest"
        )
    try:
        coverage_rows = derive_source_lifecycle_coverage(executable)
        if runtime_binding is not None:
            require_source_lifecycle_coverage_ids(
                runtime_binding.get(
                    "planned_source_lifecycle_coverage_ids"
                ),
                allowed_rows=coverage_rows,
                planned_materialization_cases=runtime_binding.get(
                    "planned_materialization_cases", ()
                ),
            )
    except SourceLifecycleCoverageError as exc:
        raise RuntimeSuccessAuthorityError(str(exc)) from exc
    return {
        "candidate_activation_id": candidate.record_id,
        "candidate_source_bindings": [dict(binding) for binding in bindings],
        "executable_id": candidate.subject.removeprefix("Executable:"),
        "schema": "candidate_job_execution_context.v2",
        "source_lifecycle_coverage": [dict(row) for row in coverage_rows],
        **current.payload(),
    }


def require_runtime_success_authority(
    *,
    control: Mapping[str, Any],
    index: LocalIndex,
    job: Mapping[str, Any],
    declaration: IndexRecord,
    start_record: IndexRecord,
    runtime_entry: IndexRecord,
    runtime_binding: Mapping[str, Any],
    provenance: Mapping[str, Any],
    engineering_fixture: bool,
    require_runtime_source: Callable[[LocalIndex, str], IndexRecord],
) -> RuntimeSourceSnapshot:
    """Require the unchanged candidate and fresh source basis for success.

    This check intentionally runs before output validation.  A valid result
    packet cannot compensate for a source or authority basis that changed while
    the Job was in flight.
    """

    science = control.get("scientific")
    if not isinstance(science, Mapping):
        raise RuntimeSuccessAuthorityError(
            "runtime success control lacks scientific authority"
        )
    job_id = _ascii("runtime success Job", job.get("id"))
    job_hash = _ascii("runtime success Job hash", job.get("hash"))
    expected_direction = {"job_id": job_id, "kind": "resume_job"}
    if control.get("next_action") != expected_direction:
        raise RuntimeSuccessAuthorityError(
            "runtime success is not the exact normal running-Job direction"
        )
    mission_id = _ascii(
        "runtime success Mission", science.get("active_mission")
    )
    executable_id = _ascii(
        "runtime success Executable", science.get("active_executable")
    )
    specification = declaration.payload.get("spec")
    if (
        declaration.kind != "job-declared"
        or declaration.record_id != job_id
        or declaration.fingerprint != job_hash
        or declaration.payload.get("mission_id") != mission_id
        or not isinstance(specification, Mapping)
        or specification.get("evidence_subject")
        != {"id": executable_id, "kind": "Executable"}
        or specification.get("runtime_binding") != runtime_binding
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success Job declaration is not the active candidate work"
        )

    candidate_id = _ascii(
        "runtime success candidate", provenance.get("candidate_id")
    )
    candidate_head = index.event_head(f"candidate:{executable_id}")
    candidate = (
        None
        if candidate_head is None
        else index.get(candidate_head.record_kind, candidate_head.record_id)
    )
    expected_candidate = (
        ("engineering-executable-fixture", "bound_fixture")
        if engineering_fixture
        else ("candidate", "frozen")
    )
    candidate_payload = None if candidate is None else candidate.payload
    executable_payload = (
        None
        if not isinstance(candidate_payload, Mapping)
        else candidate_payload.get("executable")
    )
    if (
        candidate is None
        or (candidate.kind, candidate.status) != expected_candidate
        or candidate.record_id != candidate_id
        or candidate.subject != f"Executable:{executable_id}"
        or candidate_payload.get("mission_id") != mission_id
        or candidate_head is None
        or candidate_head.record_id != candidate_id
        or not isinstance(executable_payload, Mapping)
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success lacks the exact current active candidate"
        )
    source_contract_ids = _canonical_string_list(
        "candidate source contracts",
        executable_payload.get("source_contracts"),
    )
    current = current_runtime_source_snapshot(
        index=index,
        source_contract_ids=source_contract_ids,
        require_runtime_source=require_runtime_source,
    )
    candidate_context = declaration.payload.get("candidate_execution_context")
    expected_candidate_context = candidate_job_execution_context(
        index=index,
        candidate=candidate,
        current=current,
        runtime_binding=runtime_binding,
    )
    if candidate_context != expected_candidate_context:
        raise RuntimeSuccessAuthorityError(
            "runtime success candidate source snapshot changed after declaration"
        )

    expected_start = {
        "action": runtime_binding.get("action"),
        "candidate_id": candidate_id,
        "evidence_depth": runtime_binding.get("evidence_depth"),
        "executable_id": executable_id,
        "mission_id": mission_id,
        "runtime_permit_id": provenance.get("runtime_permit_id"),
        **current.payload(),
    }
    if (
        start_record.kind != "job-started"
        or start_record.record_id != job.get("start_record_id")
        or start_record.subject != f"Job:{job_id}"
        or start_record.fingerprint != job_hash
        or start_record.payload.get("runtime") != expected_start
        or dict(provenance) != expected_start
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success differs from its exact Job-start source snapshot"
        )

    authorization = control.get("authorizations", {}).get(
        f"Executable:{executable_id}"
    )
    authorization_hash = (
        None
        if not isinstance(authorization, Mapping)
        else authorization.get("authorization_hash")
    )
    expected_entry = {
        "action": runtime_binding.get("action"),
        "candidate_authorization_hash": authorization_hash,
        "candidate_id": candidate_id,
        "depth": runtime_binding.get("evidence_depth"),
        "engine_contract": executable_payload.get("engine_contract"),
        "executable_id": executable_id,
        "job_id": job_id,
        "job_start_record_id": start_record.record_id,
        "mission_id": mission_id,
        "runtime_permit_id": provenance.get("runtime_permit_id"),
        **current.payload(),
    }
    if (
        type(authorization_hash) is not str
        or not authorization_hash
        or runtime_entry.kind != "runtime-engine-entry"
        or runtime_entry.record_id != job.get("runtime_entry_record_id")
        or runtime_entry.status != "validated"
        or runtime_entry.subject != f"Job:{job_id}"
        or runtime_entry.fingerprint != job_hash
        or dict(runtime_entry.payload) != expected_entry
    ):
        raise RuntimeSuccessAuthorityError(
            "runtime success differs from its exact engine-entry source snapshot"
        )
    return current


__all__ = [
    "RuntimeSourceSnapshotRow",
    "RuntimeSourceSnapshot",
    "RuntimeSuccessAuthorityError",
    "candidate_job_execution_context",
    "candidate_source_binding_snapshot",
    "current_runtime_source_snapshot",
    "require_runtime_success_authority",
]
