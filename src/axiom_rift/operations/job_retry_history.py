"""Bounded reconstruction of pre-``job_retry_family.v1`` Job history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from axiom_rift.operations.job_retry_family import (
    JobRetryFamily,
    JobRetryFamilyError,
    derive_job_retry_family,
    retry_family_attempt_identity,
    retry_family_attempt_payload,
)
from axiom_rift.storage.index import EventHead, IndexRecord, LocalIndex


class JobRetryHistoryError(ValueError):
    """Legacy Job history cannot safely establish its latest family outcome."""


@dataclass(frozen=True, slots=True)
class JobRetryHistory:
    stream_head: EventHead | None
    stream_attempt: IndexRecord | None
    latest_attempt: IndexRecord | None


def _digest(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise JobRetryHistoryError(
            f"legacy {name} must be a lowercase SHA-256 digest"
        )
    return value


def _optional_ascii(name: str, value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or not value.isascii():
        raise JobRetryHistoryError(f"legacy {name} must be non-empty ASCII")
    return value


def _family_from_declaration(
    declaration: IndexRecord,
    *,
    mission_id: str,
) -> JobRetryFamily:
    payload = declaration.payload
    if (
        declaration.kind != "job-declared"
        or declaration.status != "declared"
        or declaration.subject != f"Job:{declaration.record_id}"
        or not declaration.record_id.startswith("job:")
        or declaration.record_id.removeprefix("job:") != declaration.fingerprint
        or payload.get("mission_id") != mission_id
    ):
        raise JobRetryHistoryError("legacy Job declaration identity is malformed")
    _digest("Job hash", declaration.fingerprint)
    spec = payload.get("spec")
    if not isinstance(spec, Mapping):
        raise JobRetryHistoryError("legacy Job declaration spec is malformed")
    try:
        family = derive_job_retry_family(
            mission_id=mission_id,
            initiative_id=_optional_ascii(
                "Job initiative", payload.get("initiative_id")
            ),
            study_id=_optional_ascii("Job study", payload.get("study_id")),
            batch_id=_optional_ascii("Job Batch", payload.get("batch_id")),
            spec=spec,
        )
    except JobRetryFamilyError as exc:
        raise JobRetryHistoryError(
            "legacy Job declaration cannot derive its retry family"
        ) from exc
    stored_family = payload.get("retry_family")
    stored_fingerprint = payload.get("retry_family_fingerprint")
    if (stored_family is None) != (stored_fingerprint is None):
        raise JobRetryHistoryError(
            "stored Job retry family projection is incomplete"
        )
    if stored_family is not None:
        if (
            not isinstance(stored_family, Mapping)
            or dict(stored_family) != family.payload()
            or stored_fingerprint != family.fingerprint
        ):
            raise JobRetryHistoryError(
                "stored Job retry family differs from its declaration"
            )
    return family


def latest_legacy_family_completion(
    *,
    index: LocalIndex,
    family: JobRetryFamily,
) -> IndexRecord | None:
    """Return the latest exact completion for one family before its stream.

    Prefer the exact indexed Batch slice when the family is Batch-bound.  Only
    non-Batch work falls back to the indexed Mission slice.  Exact attempt
    heads then turn each matching declaration into its authoritative latest
    completion without scanning completion history.
    """

    lookup_name, lookup_value = (
        ("batch_id", family.batch_id)
        if family.batch_id is not None
        else ("mission_id", family.mission_id)
    )
    declarations = index.records_by_payload_text(
        "job-declared",
        lookup_name,
        lookup_value,
    )
    latest: IndexRecord | None = None
    latest_sequence = 0
    for declaration in declarations:
        stored_family = _family_from_declaration(
            declaration,
            mission_id=family.mission_id,
        )
        if stored_family.fingerprint != family.fingerprint:
            continue
        if declaration.payload.get("retry_family") is not None:
            raise JobRetryHistoryError(
                "current Job family stream is absent for a projected declaration"
            )
        work_fingerprint = _digest(
            "work fingerprint",
            declaration.payload.get("work_fingerprint"),
        )
        stream = f"job-attempt:{work_fingerprint}"
        head = index.event_head(stream)
        completion = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        if (
            head is None
            or completion is None
            or completion.kind != "job-completed"
            or completion.status not in {"success", "failed", "not_evaluable"}
            or completion.subject != f"Job:{declaration.record_id}"
            or completion.fingerprint != declaration.fingerprint
            or completion.payload.get("job_id") != declaration.record_id
            or completion.event_stream != stream
            or completion.event_sequence != head.sequence
            or type(completion.authority_sequence) is not int
            or completion.authority_sequence < 1
        ):
            raise JobRetryHistoryError(
                "legacy Job declaration lacks its exact terminal attempt"
            )
        if completion.authority_sequence == latest_sequence:
            raise JobRetryHistoryError(
                "legacy Job family has ambiguous Journal authority order"
            )
        if completion.authority_sequence > latest_sequence:
            latest = completion
            latest_sequence = completion.authority_sequence
    return latest


def resolve_job_retry_history(
    *,
    index: LocalIndex,
    family: JobRetryFamily,
) -> JobRetryHistory:
    """Resolve a current family stream or its bounded legacy predecessor."""

    stream_head = index.event_head(family.stream)
    stream_attempt = (
        None
        if stream_head is None
        else index.get(stream_head.record_kind, stream_head.record_id)
    )
    if stream_head is not None:
        if stream_attempt is None or stream_attempt.status not in {
            "declared",
            "success",
            "failed",
            "not_evaluable",
        }:
            raise JobRetryHistoryError("Job retry family head is invalid")
        try:
            expected_payload = retry_family_attempt_payload(
                family=family,
                phase=stream_attempt.status,
                job_id=stream_attempt.payload.get("job_id"),
                job_hash=stream_attempt.payload.get("job_hash"),
                work_fingerprint=stream_attempt.payload.get(
                    "work_fingerprint"
                ),
                completion_record_id=stream_attempt.payload.get(
                    "completion_record_id"
                ),
            )
        except JobRetryFamilyError as exc:
            raise JobRetryHistoryError(
                "Job retry family head is invalid"
            ) from exc
        if (
            stream_attempt.kind != "job-retry-family-attempt"
            or stream_attempt.record_id
            != retry_family_attempt_identity(expected_payload)
            or stream_attempt.subject != f"Mission:{family.mission_id}"
            or stream_attempt.event_stream != family.stream
            or stream_attempt.event_sequence != stream_head.sequence
            or stream_attempt.fingerprint != family.fingerprint
            or stream_attempt.payload != expected_payload
        ):
            raise JobRetryHistoryError("Job retry family head is invalid")
    if stream_attempt is not None and stream_attempt.status == "declared":
        raise JobRetryHistoryError(
            "Job retry family has an unfinished declaration"
        )
    latest_attempt = (
        stream_attempt
        if stream_attempt is not None
        else latest_legacy_family_completion(index=index, family=family)
    )
    return JobRetryHistory(
        stream_head=stream_head,
        stream_attempt=stream_attempt,
        latest_attempt=latest_attempt,
    )


__all__ = [
    "JobRetryHistory",
    "JobRetryHistoryError",
    "latest_legacy_family_completion",
    "resolve_job_retry_history",
]
