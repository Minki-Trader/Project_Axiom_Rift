"""Authenticate historical reconstruction sources for prospective Jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.operations.job_implementation_authority import (
    HistoricalImplementationSourceAuthority,
    JobImplementationAuthorityError,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyBindingError,
    historical_family_authority_from_payload,
    historical_family_from_manifest,
)
from axiom_rift.research.replay_obligation import (
    ReplayObligationError,
    historical_replay_obligation_from_identity_payload,
)
from axiom_rift.storage.index import LocalIndex, LocalIndexView


class HistoricalReplayImplementationAuthorityError(RuntimeError):
    """Registered replay lineage and implementation source disagree."""


def authenticated_historical_implementation_sources(
    spec: Mapping[str, Any],
    *,
    index: LocalIndex | LocalIndexView,
    artifact_reader: Callable[[str], bytes],
) -> tuple[HistoricalImplementationSourceAuthority, ...]:
    """Derive source authority only from one exact replay registration."""

    binding = spec.get("scientific_binding")
    if not isinstance(binding, Mapping):
        return ()
    plan_hash = binding.get("validation_plan_hash")
    if type(plan_hash) is not str:
        return ()
    try:
        plan = parse_canonical(artifact_reader(plan_hash))
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        # A scientific binding is not itself replay authority.  Non-replay
        # declarations may intentionally use a validator-owned or fixture
        # plan that is unavailable at this read boundary.  The generic
        # implementation verifier still rejects any hard-coded historical
        # source unless an exact replay plan below authenticates it.
        return ()
    protocol = (
        plan.get("protocol_definition")
        if isinstance(plan, Mapping)
        else None
    )
    if (
        not isinstance(protocol, Mapping)
        or protocol.get("schema") != "fixed_hold_protocol_definition.v3"
        or not isinstance(protocol.get("historical_family"), Mapping)
    ):
        return ()
    subject = spec.get("evidence_subject")
    historical_context_id = protocol.get("historical_context_id")
    prospective_ids = protocol.get("prospective_executable_ids")
    try:
        family = historical_family_from_manifest(
            dict(protocol["historical_family"])
        )
    except HistoricalFamilyBindingError as exc:
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay implementation family is malformed"
        ) from exc
    if (
        not isinstance(plan, Mapping)
        or plan.get("schema") != "scientific_validation_plan.v2"
        or not isinstance(subject, Mapping)
        or subject.get("kind") != "Executable"
        or type(subject.get("id")) is not str
        or plan.get("executable_id") != subject.get("id")
        or type(historical_context_id) is not str
        or not isinstance(prospective_ids, list)
        or subject.get("id") not in prospective_ids
        or len(prospective_ids) != family.family_size
    ):
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay implementation plan is not subject-bound"
        )
    reconstruction_required = historical_context_id.startswith(
        "historical-replay-obligation:"
    )
    if reconstruction_required:
        obligation_id = historical_context_id
        accepted = tuple(
            record
            for record in index.records_by_subject_status(
                f"ReplayObligation:{obligation_id}",
                "accepted",
            )
            if record.kind == "historical-family-authority"
        )
        if len(accepted) != 1:
            raise HistoricalReplayImplementationAuthorityError(
                "historical replay implementation source authority is ambiguous"
            )
        authority_record = accepted[0]
    elif historical_context_id.startswith("historical-family-authority:"):
        authority_record = index.get(
            "historical-family-authority",
            historical_context_id,
        )
        if authority_record is None:
            raise HistoricalReplayImplementationAuthorityError(
                "historical replay family authority is unavailable"
            )
        obligation_id = authority_record.payload.get("replay_obligation_id")
        if type(obligation_id) is not str:
            raise HistoricalReplayImplementationAuthorityError(
                "historical replay family authority lacks its obligation"
            )
    else:
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay context is not Writer-bound"
        )
    try:
        authority = historical_family_authority_from_payload(
            authority_record.payload
        )
    except HistoricalFamilyBindingError as exc:
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay implementation source authority is malformed"
        ) from exc
    obligation_record = index.event_record(
        f"historical-replay-obligation:{obligation_id}",
        1,
    )
    obligation_payload = (
        obligation_record.payload.get("obligation")
        if obligation_record is not None
        and isinstance(obligation_record.payload, Mapping)
        else None
    )
    try:
        obligation = historical_replay_obligation_from_identity_payload(
            obligation_payload
        )
    except (ReplayObligationError, TypeError, ValueError) as exc:
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay implementation obligation is malformed"
        ) from exc
    if (
        authority_record.record_id != authority.identity
        or authority_record.subject != f"ReplayObligation:{obligation_id}"
        or authority_record.status != "accepted"
        or authority_record.fingerprint
        != authority.identity.removeprefix("historical-family-authority:")
        or authority.replay_obligation_id != obligation_id
        or (
            not reconstruction_required
            and authority.identity != historical_context_id
        )
        or authority.family != family
        or obligation_record is None
        or obligation_record.kind != "historical-replay-obligation"
        or obligation_record.record_id != obligation_id
        or obligation_record.status != "pending"
        or obligation.identity != obligation_id
        or obligation.governing_mission_id != plan.get("mission_id")
        or obligation.original_executable_id
        != family.target_historical_executable_id
    ):
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay implementation lineage differs from authority"
        )
    if not reconstruction_required:
        return ()
    reconstruction_path = authority.reconstruction_source_path
    if not reconstruction_path.startswith("src/"):
        raise HistoricalReplayImplementationAuthorityError(
            "historical replay reconstruction source is outside src"
        )
    try:
        return (
            HistoricalImplementationSourceAuthority(
                path=reconstruction_path.removeprefix("src/"),
                source_sha256=authority.reconstruction_source_sha256,
                original_study_id=family.original_study_id,
            ),
        )
    except JobImplementationAuthorityError as exc:
        raise HistoricalReplayImplementationAuthorityError(str(exc)) from exc


__all__ = [
    "HistoricalReplayImplementationAuthorityError",
    "authenticated_historical_implementation_sources",
]
