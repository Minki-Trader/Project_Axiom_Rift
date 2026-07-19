"""Shared transition types and pure construction helpers for Writer domains."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.index import IndexRecord, LocalIndex


class TransitionError(RuntimeError):
    """A requested transition violates the active lifecycle."""


class RecoveryRequired(TransitionError):
    """A projection trails or conflicts with the durable journal."""


class IdenticalFailedRetryError(TransitionError):
    """A failed work fingerprint was retried without new information."""


@dataclass(frozen=True, slots=True)
class TransitionResult:
    event_id: str
    revision: int
    reused: bool
    result: Mapping[str, Any]


def _copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = parse_canonical(canonical_bytes(dict(value)))
    assert isinstance(copied, dict)
    return dict(copied)


def _digest(value: Mapping[str, Any], *, domain: str) -> str:
    return canonical_digest(domain=domain, payload=dict(value))


def _require_ascii(name: str, value: str) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise TransitionError(f"{name} must be non-empty ASCII")
    return value


def _require_digest(name: str, value: str) -> str:
    _require_ascii(name, value)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise TransitionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _parse_utc(name: str, value: str) -> datetime:
    _require_ascii(name, value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransitionError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TransitionError(f"{name} must be UTC")
    return parsed


def _effective_completion_scope(index: LocalIndex, completion: IndexRecord):
    from axiom_rift.operations.evidence_scope_projection import (
        EvidenceScopeProjectionError,
        effective_completion_evidence_scope,
    )

    try:
        return effective_completion_evidence_scope(index, completion)
    except EvidenceScopeProjectionError as exc:
        raise RecoveryRequired(str(exc)) from exc


def _require_manifest(
    name: str,
    value: Mapping[str, Any],
    *,
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TransitionError(f"{name} must be a mapping")
    missing = required - set(value)
    if missing:
        raise TransitionError(f"{name} is missing fields: {sorted(missing)!r}")
    return _copy(value)


def _require_study_evidence_modes(
    question: Mapping[str, Any],
) -> tuple[str, ...]:
    allowed = {
        "ablation",
        "audit_integrity",
        "causal_contrast",
        "cost_and_execution",
        "extreme_or_boundary",
        "neighborhood",
        "regime_stability",
        "sensitivity_or_stress",
        "temporal_stability",
    }
    modes = question.get("evidence_modes")
    if (
        not isinstance(modes, list)
        or not modes
        or any(type(mode) is not str for mode in modes)
        or len(set(modes)) != len(modes)
        or not set(modes).issubset(allowed)
    ):
        raise TransitionError("Study evidence_modes are invalid")
    return tuple(sorted(modes))


def _record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: Mapping[str, Any],
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=dict(payload),
        event_stream=event_stream,
        event_sequence=event_sequence,
    )
