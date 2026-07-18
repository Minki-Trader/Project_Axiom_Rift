"""Read-only authentication of durable historical-family authority records.

This module deliberately excludes writer admission, repository paths, and raw
evidence-store access so a prospective running Job can authenticate an already
recorded family without inheriting management authority.
"""

from __future__ import annotations

from axiom_rift.operations.recorded_transition_authority import (
    RecordedTransitionAuthorityError,
    require_same_event_operation_result,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilyBindingError,
    historical_family_authority_from_payload,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class HistoricalFamilyAuthorityAdmissionError(ValueError):
    """One proposed authority is absent, stale, or historically false."""


def require_recorded_historical_family_authority(
    index: LocalIndex | LocalIndexView,
    record: IndexRecord,
) -> HistoricalFamilyAuthority:
    """Authenticate one accepted family authority and its Writer event."""

    try:
        authority = historical_family_authority_from_payload(record.payload)
        event_kind, result = require_same_event_operation_result(
            index,
            record=record,
            expected_event_kinds=frozenset(
                {
                    "historical_replay_family_authorities_registered",
                    "historical_replay_satisfaction_invalidated",
                    "historical_replay_sibling_evidence_recertified",
                }
            ),
        )
    except (
        HistoricalFamilyBindingError,
        RecordedTransitionAuthorityError,
        TypeError,
        ValueError,
    ) as exc:
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority lacks exact same-event Writer authority"
        ) from exc
    authority_ids = result.get("historical_family_authority_ids")
    result_binding_valid = (
        result.get("historical_family_authority_id") == authority.identity
        if event_kind == "historical_replay_satisfaction_invalidated"
        else isinstance(authority_ids, list)
        and all(type(item) is str for item in authority_ids)
        and len(authority_ids) == len(set(authority_ids))
        and authority.identity in authority_ids
    )
    if (
        record.kind != "historical-family-authority"
        or record.record_id != authority.identity
        or record.subject
        != f"ReplayObligation:{authority.replay_obligation_id}"
        or record.status != "accepted"
        or record.fingerprint
        != authority.identity.removeprefix("historical-family-authority:")
        or record.payload != authority.to_identity_payload()
        or index.get("historical-family-authority", authority.identity) != record
        or not result_binding_valid
    ):
        raise HistoricalFamilyAuthorityAdmissionError(
            "historical family authority lacks exact same-event Writer authority"
        )
    return authority


__all__ = [
    "HistoricalFamilyAuthorityAdmissionError",
    "require_recorded_historical_family_authority",
]
