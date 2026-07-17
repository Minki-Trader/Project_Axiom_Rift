"""Project effective Job implementation through non-implementation Repairs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job import (
    RunningJobAuthorityIntegrityError,
    effective_running_job_implementation,
)
from axiom_rift.storage.index import (
    EventHead,
    IndexRecord,
    LocalIndex,
    LocalIndexView,
)


_NON_IMPLEMENTATION_CLOSE_KEYS = {
    "attempt_record_id",
    "changed_cause_proof_hash",
    "changed_dimension",
    "effective_implementation_identity",
    "implementation_changed",
    "job_id",
    "previous_effective_implementation_identity",
    "prior_attempt_record_id",
    "repair_id",
    "resume_action",
    "scientific_failure_delta",
    "scientific_trial_delta",
    "verification_evidence_hashes",
}


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_digest_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and value == sorted(set(value))
        and all(_is_digest(item) for item in value)
    )


class _RepairPrefixView:
    """Expose one earlier Repair close as the stream head for validation."""

    def __init__(
        self,
        index: LocalIndex | LocalIndexView,
        *,
        stream: str,
        sequence: int,
    ) -> None:
        self._index = index
        self._stream = stream
        self._sequence = sequence

    def event_head(self, stream: str) -> EventHead | None:
        if stream != self._stream:
            return self._index.event_head(stream)
        record = self._index.event_record(stream, self._sequence)
        if record is None:
            return None
        return EventHead(
            stream=stream,
            sequence=self._sequence,
            record_kind=record.kind,
            record_id=record.record_id,
            fingerprint=record.fingerprint,
        )

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self._index.get(kind, record_id)


def effective_repair_head_implementation(
    index: LocalIndex | LocalIndexView,
    *,
    job_id: str,
    declared_implementation_identity: str,
) -> tuple[str, str | None]:
    """Return the implementation carried by the exact terminal Repair head.

    An implementation Repair still uses the production semantic-equivalence
    projection.  A later cause or information Repair is operational only: it
    must preserve the immediately preceding effective implementation exactly
    and cannot be forced to manufacture another implementation proof.
    """

    stream = f"job-repair:{job_id}"
    head = index.event_head(stream)
    if head is None:
        return effective_running_job_implementation(
            index,
            job_id=job_id,
            declared_implementation_identity=declared_implementation_identity,
        )
    if (
        type(head.sequence) is not int
        or head.sequence < 1
        or not _is_digest(declared_implementation_identity)
    ):
        raise RunningJobAuthorityIntegrityError(
            "running Job Repair head is malformed"
        )
    effective = declared_implementation_identity
    terminal_close_id: str | None = None
    for sequence in range(1, head.sequence + 1):
        close = index.event_record(stream, sequence)
        payload = None if close is None else close.payload
        if not isinstance(payload, Mapping):
            raise RunningJobAuthorityIntegrityError(
                "running Job Repair head is unavailable"
            )
        repair_id = payload.get("repair_id")
        proof = payload.get("changed_cause_proof_hash")
        semantic_present = "semantic_equivalence_validation" in payload
        expected_keys = set(_NON_IMPLEMENTATION_CLOSE_KEYS)
        close_identity_payload: dict[str, Any] = {
            "proof": proof,
            "repair_id": repair_id,
        }
        if semantic_present:
            expected_keys.add("semantic_equivalence_validation")
            close_identity_payload["semantic_equivalence_validation"] = (
                payload.get("semantic_equivalence_validation")
            )
        expected_close_id = canonical_digest(
            domain="repair-close",
            payload=close_identity_payload,
        )
        next_effective = payload.get("effective_implementation_identity")
        terminal = sequence == head.sequence
        if (
            close.kind != "repair-close"
            or close.status != "repaired"
            or close.subject != f"Job:{job_id}"
            or close.event_stream != stream
            or close.event_sequence != sequence
            or close.record_id != expected_close_id
            or close.fingerprint != proof
            or (
                terminal
                and (
                    close.record_id != head.record_id
                    or close.fingerprint != head.fingerprint
                )
            )
            or set(payload) != expected_keys
            or payload.get("job_id") != job_id
            or payload.get("previous_effective_implementation_identity")
            != effective
            or not _is_digest(next_effective)
            or payload.get("scientific_failure_delta") != 0
            or payload.get("scientific_trial_delta") != 0
            or type(repair_id) is not str
            or not repair_id.startswith("repair:")
            or not _is_digest(repair_id.removeprefix("repair:"))
            or not _is_digest(proof)
            or not _is_digest(payload.get("attempt_record_id"))
            or (
                payload.get("prior_attempt_record_id") is not None
                and not _is_digest(payload.get("prior_attempt_record_id"))
            )
            or not _is_digest_list(
                payload.get("verification_evidence_hashes")
            )
        ):
            raise RunningJobAuthorityIntegrityError(
                "running Job Repair implementation lineage is malformed"
            )
        dimension = payload.get("changed_dimension")
        if dimension == "implementation":
            if (
                payload.get("implementation_changed") is not True
                or next_effective == effective
            ):
                raise RunningJobAuthorityIntegrityError(
                    "implementation Repair did not change its implementation"
                )
            prefix = _RepairPrefixView(
                index,
                stream=stream,
                sequence=sequence,
            )
            projected, projected_close_id = (
                effective_running_job_implementation(
                    prefix,
                    job_id=job_id,
                    declared_implementation_identity=(
                        declared_implementation_identity
                    ),
                )
            )
            if (
                projected != next_effective
                or projected_close_id != close.record_id
            ):
                raise RunningJobAuthorityIntegrityError(
                    "implementation Repair projection is inconsistent"
                )
        elif dimension in {"cause", "information"}:
            if (
                semantic_present
                or payload.get("implementation_changed") is not False
                or next_effective != effective
            ):
                raise RunningJobAuthorityIntegrityError(
                    "non-implementation Repair changed effective Job "
                    "implementation"
                )
        else:
            raise RunningJobAuthorityIntegrityError(
                "running Job Repair dimension cannot resume implementation"
            )
        effective = str(next_effective)
        terminal_close_id = close.record_id
    return effective, terminal_close_id


__all__ = ["effective_repair_head_implementation"]
